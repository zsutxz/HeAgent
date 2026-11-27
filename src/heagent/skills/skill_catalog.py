"""技能检索（memory/skills 拆分层，Phase 4 C4）。

基于关键词/触发词的可解释匹配与过期盘点：:func:`match_skill_details` /
:func:`stale_skills`。均为以 :class:`~heagent.skills.skill_store.SkillStore`
为数据源的纯检索函数（本模块只经 TYPE_CHECKING 引用存储类型，依赖单向）。

匹配分两段：与 prompt **无关**的部分一次性建成 :class:`SkillMatchIndex`（每技能一次
``SkillStore.parse``），按技能库指纹缓存；与 prompt 相关的部分只做集合运算与阈值判定。
结果再按 ``(指纹, prompt, threshold)`` 进 LRU 缓存，故同一 prompt 的重复匹配零解析。
缓存随 ``SkillStore`` 实例存活（见 :class:`SkillMatchCache`），技能库任一文件被写 ⇒
指纹变化 ⇒ 结果与索引一起失效，不靠 TTL、不靠手动清理。
"""

from __future__ import annotations

import hashlib
import logging
import re
import threading
from collections import OrderedDict
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from heagent.skills.skill_meta import META_FILENAME, SkillMetaError
from heagent.skills.skill_models import SkillMatch

if TYPE_CHECKING:
    from pathlib import Path

    from heagent.skills.skill_store import SkillStore

logger = logging.getLogger(__name__)

#: 结果缓存容量（LRU）：一次 run 里的 prompt 数远小于此值，多子代理并发也在预算内。
DEFAULT_MATCH_CACHE_ENTRIES = 32
#: 索引缓存容量：槽位按技能库指纹划分，留几槽容错（并发线程交替构建）。
_INDEX_CACHE_ENTRIES = 4


class _LruCache:
    """固定容量的线程安全 LRU。

    技能读路径会被多个 ``asyncio.to_thread`` 工作线程并发调用（并行子代理各自构建系统
    提示词），故读写都在锁内；键是任意不可变元组，值是**不可变使用**的缓存载荷。
    """

    __slots__ = ("_entries", "_lock", "_max_entries")

    def __init__(self, max_entries: int) -> None:
        self._max_entries = max(1, max_entries)
        self._lock = threading.Lock()
        self._entries: OrderedDict[object, object] = OrderedDict()

    def get(self, key: object) -> object | None:
        with self._lock:
            value = self._entries.get(key)
            if value is not None:
                self._entries.move_to_end(key)
            return value

    def put(self, key: object, value: object) -> None:
        with self._lock:
            self._entries[key] = value
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


class SkillMatchCache:
    """技能匹配的两处进程内缓存，随 :class:`~heagent.skills.skill_store.SkillStore` 实例存活。

    刻意不做跨实例/跨进程共享：缓存只反映**本进程读到的文件状态**（技能库在别的进程
    被改，这里看不到——那是下一次指纹重算的事）。``SkillStore.__init__`` 只新建这两个
    空容器，不预扫描技能库（懒语义不变）。
    """

    __slots__ = ("index", "results")

    def __init__(
        self,
        *,
        results: int = DEFAULT_MATCH_CACHE_ENTRIES,
        index: int = _INDEX_CACHE_ENTRIES,
    ) -> None:
        #: key = ``(技能库指纹, prompt, threshold)`` → ``list[SkillMatch]``
        self.results = _LruCache(results)
        #: key = 技能库指纹 → :class:`SkillMatchIndex`
        self.index = _LruCache(index)


def skill_tokens(text: str) -> set[str]:
    """无外部依赖的中英混排分词，CJK 取二元/三元组。"""
    chunks = re.findall(r"[a-zA-Z0-9_]+|[㐀-鿿぀-ヿ가-힯]+", text.casefold())
    tokens: set[str] = set()
    for chunk in chunks:
        if not re.fullmatch(r"[㐀-鿿぀-ヿ가-힯]+", chunk):
            tokens.add(chunk)
            continue
        # 整段中文依赖空白边界，会让覆盖率不公平：
        # 只用两/三字的证据，排除低信息量的单字。
        for size in (2, 3):
            tokens.update(chunk[i : i + size] for i in range(len(chunk) - size + 1))
    return tokens


def _stat_signature(path: Path) -> tuple[int, int]:
    """文件 ``(mtime_ns, size)``；读不到（竞态删除）按全零计，本轮视作「无该文件」。"""
    try:
        info = path.stat()
    except OSError:
        return (0, 0)
    return (info.st_mtime_ns, info.st_size)


#: 内容抽样字节数（首尾各至多这么多）：粗粒度时间戳 FS（FAT / 部分网络盘 / 9p）上
#: 「同一时间粒度内改写、大小不变」不会让 ``(mtime_ns, size)`` 变化，靠抽样兜住失效。
_SAMPLE_BYTES = 64


def _content_sample(path: Path, size: int) -> str:
    """文件首尾抽样的短摘要（8 位十六进制）；空文件 / 读不到返回空串，与零签名同义。"""
    if size <= 0:
        return ""
    try:
        with path.open("rb") as handle:
            data = handle.read(_SAMPLE_BYTES)
            if size > _SAMPLE_BYTES:
                handle.seek(max(size - _SAMPLE_BYTES, _SAMPLE_BYTES))
                data += handle.read(_SAMPLE_BYTES)
    except OSError:
        return ""
    return hashlib.sha256(data).hexdigest()[:8]


def skill_library_fingerprint(store: SkillStore) -> str:
    """技能库内容指纹：匹配结果与索引的失效判据。

    逐**生效根**技能取 ``meta.yaml`` 与 ``SKILL.md`` 的 ``(mtime_ns, size)`` **加首尾 64 字节
    抽样摘要**，连同技能名排序后做 sha256，取前 16 位十六进制。任一技能文件被写（含
    ``record_usage`` 回写 ``meta.yaml``）或技能增删 ⇒ 指纹变化 ⇒ 全部缓存失效；粗粒度
    时间戳文件系统上「同 size 同 mtime 改内容」也因抽样变化而失效（A70）。

    成本：每技能文件一次 ``stat`` + 一次 ``open``（只读首尾各 64 字节），仍远低于
    :meth:`SkillStore.parse`（读全文 + YAML / frontmatter 解析），故每次匹配都可重算。
    """
    records: list[tuple[str, int, int, str, int, int, str]] = []
    for name in store.list_skills():
        owner = store.owner_root(name)
        if owner is None:  # 竞态：list_skills 到 owner_root 之间目录被移走
            continue
        skill_dir = owner / name
        meta_path = skill_dir / META_FILENAME
        md_path = skill_dir / "SKILL.md"
        meta_mtime, meta_size = _stat_signature(meta_path)
        md_mtime, md_size = _stat_signature(md_path)
        # 抽样只在 stat 命中时做：两文件都读不到时整条记录退化为零签名（= 无该技能）。
        records.append(
            (
                name,
                meta_mtime,
                meta_size,
                _content_sample(meta_path, meta_size),
                md_mtime,
                md_size,
                _content_sample(md_path, md_size),
            )
        )
    records.sort()
    payload = "\n".join("|".join(str(field) for field in record) for record in records)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class SkillIndexEntry(BaseModel):
    """一个技能的**与 prompt 无关**的匹配特征。

    全部来自一次 ``SkillStore.parse``：``pattern_tokens`` 是 ``pattern + tags`` 的词元袋
    （匹配分母），``triggers`` 保留原文（命中后原样回填 ``SkillMatch.matched_triggers``），
    ``triggers_folded`` / ``negative_triggers_folded`` 是 casefold 后的比对用形态。
    """

    name: str
    priority: int = 0
    pattern_tokens: frozenset[str] = Field(default_factory=frozenset)
    triggers: tuple[str, ...] = ()
    triggers_folded: tuple[str, ...] = ()
    negative_triggers_folded: tuple[str, ...] = ()


class SkillMatchIndex(BaseModel):
    """技能库匹配索引：按技能库指纹缓存，任意 prompt 复用同一份。"""

    fingerprint: str = ""
    entries: tuple[SkillIndexEntry, ...] = ()


def build_skill_index(store: SkillStore, *, fingerprint: str | None = None) -> SkillMatchIndex:
    """一次遍历技能库构建索引：每个技能恰好一次 ``store.parse``。

    跳过口径与逐 prompt 版本完全一致：旧格式残留（``SkillMetaError``）告警后跳过、
    ``parse`` 返回 None 跳过、``model_invocable: false`` 不进自动匹配。
    """
    entries: list[SkillIndexEntry] = []
    for name in store.list_skills():
        try:
            parsed = store.parse(name)
        except SkillMetaError as exc:
            # 旧格式残留（meta 契约键还在 SKILL.md）：显性告警并跳过，不炸整条检索链。
            logger.warning("Skill %s skipped: %s", name, exc)
            continue
        if parsed is None:
            continue
        if not parsed.model_invocable:
            # meta.yaml 中 model_invocable: false 的技能不参与自动注入匹配。
            continue
        entries.append(
            SkillIndexEntry(
                name=name,
                priority=parsed.priority,
                pattern_tokens=frozenset(skill_tokens(f"{parsed.pattern} {' '.join(parsed.tags)}")),
                triggers=tuple(parsed.triggers),
                triggers_folded=tuple(trigger.casefold() for trigger in parsed.triggers),
                negative_triggers_folded=tuple(trigger.casefold() for trigger in parsed.negative_triggers),
            )
        )
    return SkillMatchIndex(fingerprint=fingerprint or skill_library_fingerprint(store), entries=tuple(entries))


def _index_for(store: SkillStore, fingerprint: str) -> SkillMatchIndex:
    """取本指纹的索引；未命中（含技能库刚被写）则重建并回填缓存。"""
    cached = store.match_cache.index.get(fingerprint)
    if isinstance(cached, SkillMatchIndex):
        return cached
    index = build_skill_index(store, fingerprint=fingerprint)
    store.match_cache.index.put(fingerprint, index)
    return index


def _match_index(
    index: SkillMatchIndex,
    prompt_text: str,
    prompt_tokens: set[str],
    threshold: float,
) -> list[SkillMatch]:
    """在索引上做集合运算与阈值判定；打分/排序口径与原逐技能版本逐字一致。"""
    matches: list[SkillMatch] = []
    for entry in index.entries:
        if any(trigger in prompt_text for trigger in entry.negative_triggers_folded):
            continue
        matched_triggers = [
            original
            for original, folded in zip(entry.triggers, entry.triggers_folded, strict=True)
            if folded in prompt_text
        ]
        trigger_hit = bool(matched_triggers)
        if not entry.pattern_tokens and not trigger_hit:
            continue
        overlap = len(prompt_tokens & entry.pattern_tokens)
        ratio = overlap / len(entry.pattern_tokens) if entry.pattern_tokens else 0.0
        # 显式触发器是高置信信号；普通匹配沿用旧的阈值语义。
        score = 1.0 if trigger_hit else ratio
        if score >= threshold:
            matches.append(
                SkillMatch(name=entry.name, score=score, priority=entry.priority, matched_triggers=matched_triggers)
            )
    matches.sort(key=lambda item: (-bool(item.matched_triggers), -item.score, -item.priority, item.name))
    return matches


def match_skill_details(store: SkillStore, prompt: str, threshold: float) -> list[SkillMatch]:
    """Return explainable, backward-compatible skill matches.

    结果按 ``(技能库指纹, prompt.casefold(), threshold)`` 缓存：匹配本身就大小写无关
    （``prompt_text`` 与 ``skill_tokens`` 内部都 casefold），把 casefold 提到键上不改变
    任何结果，只让 ``Hello`` / ``hello`` 共用同一个缓存槽。返回的是缓存载荷的**副本**，
    调用方就地改写不会污染后续命中。
    """
    if not prompt.strip():
        return []
    fingerprint = skill_library_fingerprint(store)
    prompt_text = prompt.casefold()
    key = (fingerprint, prompt_text, threshold)
    cached = store.match_cache.results.get(key)
    if isinstance(cached, list):
        return [match.model_copy(deep=True) for match in cached]
    matches = _match_index(_index_for(store, fingerprint), prompt_text, skill_tokens(prompt_text), threshold)
    store.match_cache.results.put(key, matches)
    return [match.model_copy(deep=True) for match in matches]


def stale_skills(store: SkillStore, days: int = 30) -> list[str]:
    """返回超过 N 天未使用的技能名称列表。"""
    cutoff = datetime.now() - timedelta(days=days)
    stale: list[str] = []
    for name in store.list_skills():
        try:
            parsed = store.parse(name)
        except SkillMetaError as exc:
            # 旧格式残留（meta 契约键还在 SKILL.md）：显性告警并跳过，不炸整条检索链。
            logger.warning("Skill %s skipped: %s", name, exc)
            continue
        if parsed is None:
            continue
        if parsed.usage_count == 0:
            stale.append(name)
        elif parsed.last_used:
            try:
                last = datetime.fromisoformat(parsed.last_used)
                if last < cutoff:
                    stale.append(name)
            except ValueError:
                pass
    return stale
