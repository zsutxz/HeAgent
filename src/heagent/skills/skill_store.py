"""技能存储管理器（skills 域包核心门面）。

:class:`SkillStore` 是技能 CRUD 与使用追踪的门面：文件读取走
:func:`~heagent.tools.path_safety.open_text_under_root` 单一安全入口（围栏 +
O_NOFOLLOW + fstat），渲染/就地改写委托 :mod:`.skill_rewrite`，解析委托
:mod:`.skill_models`，meta.yaml 契约委托 :mod:`.skill_meta`，匹配/过期盘点委托
:mod:`.skill_catalog`。

存储路径：.heagent/skills/{name}/SKILL.md（触发面四键 + 正文）与
.heagent/skills/{name}/meta.yaml（包元数据 + 运行时计数）。record_usage 只回写
meta.yaml，SKILL.md 运行时只读。

双根（2026-10-10）：构造接受多根目录，序即优先级（全局 ~/.heagent/skills 先、项目
本地兜底）。读取沿根序 first-hit-wins，同名冲突全局生效 + 每名一次警告（见
:func:`default_skill_roots` 与 :meth:`conflicts`）；写入按拥有根路由，删除/归档仅限
authoring 根。
"""

from __future__ import annotations

import logging
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel

from heagent.config import GLOBAL_CONFIG_DIR
from heagent.pub.persist import atomic_update_text, atomic_write_text
from heagent.skills.skill_catalog import match_skill_details as _match_skill_details
from heagent.skills.skill_catalog import stale_skills as _stale_skills
from heagent.skills.skill_meta import META_FILENAME, SkillMeta, parse_meta_yaml, render_meta_yaml
from heagent.skills.skill_models import SkillContent, SkillRewriteError, parse_skill_md, validate_skill_name
from heagent.skills.skill_rewrite import (
    body_survives_rerender,
    key_line,
    metadata_lines,
    patch_frontmatter,
    render_skill_md,
)
from heagent.tools.path_safety import open_text_under_root

if TYPE_CHECKING:
    from collections.abc import Sequence

    from heagent.skills.skill_models import SkillMatch

logger = logging.getLogger(__name__)


def default_skill_roots(project_root: str | Path) -> list[str]:
    """双根技能库（序即优先级）：全局 ``~/.heagent/skills`` 先，项目 ``<root>/.heagent/skills`` 兜底。

    与 roles/commands 的「本地覆盖全局」方向相反——技能库刻意全局优先：自研技能跨项目共享
    一份（usage 计数跨项目累计是特性），本地根只放项目特有技能。同名冲突全局生效 + 警告，
    合并入口见 :meth:`SkillStore.conflicts`。
    """
    return [str(GLOBAL_CONFIG_DIR / "skills"), str(Path(project_root) / ".heagent" / "skills")]


class SkillConflict(BaseModel):
    """同一技能名同时存在于多个根：生效根与被遮蔽根（含各自 meta 供差异展示与合并）。"""

    name: str
    effective_root: str
    shadowed_root: str
    effective_meta: SkillMeta
    shadowed_meta: SkillMeta


class SkillStore:
    """技能存储管理器，支持 CRUD 操作。

    每个技能以目录形式存储，SKILL.md 为入口文件，meta.yaml 为元数据/计数文件。
    多根构造时序即优先级（全局先），默认单根保持既有行为。
    """

    def __init__(self, base_dir: str | Path | Sequence[str | Path] = ".heagent/skills") -> None:
        items: tuple[str | Path, ...] = (base_dir,) if isinstance(base_dir, (str, Path)) else tuple(base_dir)
        if not items:
            raise ValueError("SkillStore needs at least one root directory")
        self._roots = tuple(Path(item).expanduser() for item in items)
        #: 同名遮蔽警告每（实例, 技能）只发一次
        self._warned_shadowed: set[str] = set()
        # 本锁使同一实例的「读」与「写」互斥。并行子代理经 ``asyncio.to_thread``
        # 在多个工作线程里同时构建系统提示词（读技能文件做技能匹配）并调用
        # ``record_usage``（原子替换 meta.yaml），而 Windows 的 ``open`` 不共享删除
        # 权限：读者只要持有句柄，写者的 ``os.replace`` 就会以 ``WinError 5`` 失败。
        # 故读路径与写路径共用这一把锁；``atomic_write_text(lock=True)`` 的
        # ``.lock`` 文件锁另行覆盖跨进程场景，:func:`_replace_with_retry` 兜住瞬时占用。
        # 用 ``RLock`` 是因为 ``parse`` → ``load`` 等路径会嵌套获取。
        self._mutation_lock = threading.RLock()

    # 拆分兼容面：测试经类名访问这两个改写内核（原 SkillStore 静态方法，随 Phase 4 C4
    # 归位 skill_rewrite；别名保持类属性访问缝原位）。
    _render_skill_md = staticmethod(render_skill_md)
    _body_survives_rerender = staticmethod(body_survives_rerender)

    # ---- 根与路径 ----

    @property
    def roots(self) -> tuple[Path, ...]:
        """全部根目录（序即优先级，首位先生效）。"""
        return self._roots

    @property
    def authoring_root(self) -> Path:
        """创作根（末位 = 最低优先级）：create 的落点，delete/archive 的唯一允许根。"""
        return self._roots[-1]

    def _candidate_dirs(self, name: str) -> list[Path]:
        """技能名在各根下的候选目录（名称规范化保证 save/delete/load 路径一致）。"""
        safe = validate_skill_name(name)
        return [root / safe for root in self._roots]

    def owner_root(self, name: str) -> Path | None:
        """首个实际拥有该技能（SKILL.md 在场）的根；无则 None。"""
        for skill_dir in self._candidate_dirs(name):
            if (skill_dir / "SKILL.md").is_file():
                return skill_dir.parent
        return None

    def read_resource(self, name: str, resource: str) -> str | None:
        """Read one package-local resource through the SkillPackage integrity gate."""
        from heagent.skills.skill_packages import SkillPackage

        try:
            owner = self.owner_root(name)
        except ValueError:
            return None
        if owner is None:
            return None
        try:
            package = SkillPackage(skill_id=validate_skill_name(name), root=owner / validate_skill_name(name))
            return package.read_resource(resource)
        except (ValueError, FileNotFoundError):
            return None

    def _read_text(self, path: Path, *, fence: Path | None = None) -> str:
        """读取技能文件，并与同实例的写操作互斥。

        经 :func:`open_text_under_root` 单一安全入口（围栏 + 最终组件 O_NOFOLLOW +
        fstat 普通文件校验）；多根下 ``fence`` 必须是文件所属的根（围栏基址逐根独立）。
        见 :meth:`__init__` 的锁说明：Windows 上读者持句柄会让写者的 ``os.replace``
        失败，故读路径不得与写路径并发。文件缺失抛 ``FileNotFoundError``，由调用方
        （如 :meth:`load`）决定语义。
        """
        with self._mutation_lock:
            return open_text_under_root(fence or self._roots[0], path)

    def _read_meta_at(self, root: Path, name: str) -> SkillMeta:
        """读取指定根下技能的 meta.yaml；缺文件返回全默认（纯声明面技能的常态）。"""
        try:
            path = root / validate_skill_name(name) / META_FILENAME
        except ValueError:
            return SkillMeta()
        try:
            return parse_meta_yaml(self._read_text(path, fence=root))
        except FileNotFoundError:
            return SkillMeta()

    def _read_meta(self, name: str) -> SkillMeta:
        """读取生效根下的 meta.yaml。"""
        owner = self.owner_root(name)
        if owner is None:
            return SkillMeta()
        return self._read_meta_at(owner, name)

    # ---- CRUD ----

    def save(
        self,
        name: str,
        description: str,
        pattern: str,
        steps: list[str],
        *,
        tags: list[str] | None = None,
        triggers: list[str] | None = None,
        negative_triggers: list[str] | None = None,
        priority: int = 0,
        usage_count: int = 0,
        last_used: str = "",
        created: str | None = None,
    ) -> str:
        """保存一个技能为标准目录结构。

        创建 <root>/<name>/SKILL.md（触发面四键 + 正文）与 meta.yaml（tags/priority/
        usage_count/last_used/created），返回 SKILL.md 的路径。落点：技能已存在时写
        **拥有根**（就地更新语义），否则写 **authoring 根**（新建永远落本地）。

        ``created`` 为 None 时自动生成当前时间；``update()`` / ``record_usage()``
        透传原值，防止每次调用覆写原始创建时间（P1-7 修复）。
        """
        safe = validate_skill_name(name)
        target_root = self.owner_root(safe) or self.authoring_root
        skill_dir = target_root / safe

        if created is None:
            created = datetime.now().isoformat()
        content = self._render_skill_md(
            safe,
            description,
            pattern,
            steps,
            triggers=triggers,
            negative_triggers=negative_triggers,
        )
        meta = SkillMeta(
            tags=tags or [],
            priority=priority,
            usage_count=usage_count,
            last_used=last_used,
            created=created,
        )
        md_path = skill_dir / "SKILL.md"
        with self._mutation_lock:
            skill_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_text(md_path, content, lock=True)
            atomic_write_text(skill_dir / META_FILENAME, render_meta_yaml(meta), lock=True)
        return str(md_path)

    def load(self, name: str) -> str | None:
        """按名称加载生效根的 SKILL.md 内容。不存在或名称非法返回 None。"""
        try:
            candidates = self._candidate_dirs(name)
        except ValueError:
            return None
        for skill_dir in candidates:
            try:
                return self._read_text(skill_dir / "SKILL.md", fence=skill_dir.parent)
            except FileNotFoundError:
                continue
        return None

    def _warn_shadowed(self, name: str, effective: Path, shadowed: Path) -> None:
        """同名遮蔽警告，每（实例, 技能）只发一次。"""
        if name in self._warned_shadowed:
            return
        self._warned_shadowed.add(name)
        logger.warning(
            "Skill '%s' exists in multiple roots: using %s (global-first), shadowing %s; "
            "run /skill-merge to reconcile or conflicts() to inspect",
            name,
            effective,
            shadowed,
        )

    def list_skills(self) -> list[str]:
        """返回所有技能名称（跨根并集，同名取优先根；每名只警告一次）。"""
        seen: dict[str, Path] = {}
        for root in self._roots:
            if not root.is_dir():
                continue
            for entry in root.iterdir():
                if not entry.is_dir() or not (entry / "SKILL.md").is_file():
                    continue
                if entry.name in seen:
                    self._warn_shadowed(entry.name, seen[entry.name], root)
                else:
                    seen[entry.name] = root
        return sorted(seen)

    def conflicts(self) -> list[SkillConflict]:
        """跨根同名技能的冲突清单（首位根生效；供警告复核与合并展示）。"""
        by_name: dict[str, list[Path]] = {}
        for root in self._roots:
            if not root.is_dir():
                continue
            for entry in root.iterdir():
                if entry.is_dir() and (entry / "SKILL.md").is_file():
                    by_name.setdefault(entry.name, []).append(root)
        result: list[SkillConflict] = []
        for name, owning_roots in sorted(by_name.items()):
            for shadowed in owning_roots[1:]:
                result.append(
                    SkillConflict(
                        name=name,
                        effective_root=str(owning_roots[0]),
                        shadowed_root=str(shadowed),
                        effective_meta=self._read_meta_at(owning_roots[0], name),
                        shadowed_meta=self._read_meta_at(shadowed, name),
                    )
                )
        return result

    def delete(self, name: str) -> bool:
        """删除指定技能目录。全局根技能显性拒绝（可逆删除只在 authoring 根做）。"""
        try:
            owner = self.owner_root(name)
        except ValueError:
            return False
        if owner is not None and owner != self.authoring_root:
            raise ValueError(
                f"skill '{name}' is owned by another root ({owner}); delete it there or reconcile "
                "with /skill-merge — refusing to delete across roots"
            )
        skill_dir = self.authoring_root / validate_skill_name(name)
        with self._mutation_lock:
            if skill_dir.is_dir():
                shutil.rmtree(skill_dir)
                return True
        return False

    def all_skills_content(self) -> list[str]:
        """返回所有技能 SKILL.md 的完整内容（用于注入系统提示词）。"""
        contents: list[str] = []
        for name in self.list_skills():
            raw = self.load(name)
            if raw:
                contents.append(raw)
        return contents

    # ---- 解析与更新 ----

    def parse(self, name: str) -> SkillContent | None:
        """将 SKILL.md ⊕ meta.yaml 解析为结构化字段。不存在返回 None。

        触发面字段来自 SKILL.md，元数据/计数字段来自 meta.yaml（缺文件取默认）。
        """
        raw = self.load(name)
        if raw is None:
            return None
        content = parse_skill_md(name, raw)
        meta = self._read_meta(name)
        return content.model_copy(
            update={
                "created": meta.created,
                "tags": meta.tags,
                "priority": meta.priority,
                "usage_count": meta.usage_count,
                "last_used": meta.last_used,
            }
        )

    def _rerender_or_patch(
        self,
        name: str,
        raw: str,
        existing: SkillContent,
        *,
        description: str | None,
        pattern: str | None,
        steps: list[str] | None,
        triggers: list[str] | None,
        negative_triggers: list[str] | None,
    ) -> str:
        """SKILL.md 事务内核：正文可无损重渲染则整体渲染，否则就地 patch 元数据行（正文逐字节保留）。

        正文含 ``## Pattern`` / ``## Steps`` 之外的章节（手写角色契约等）时，改 pattern/steps
        会丢正文 ⇒ 显性拒绝；只改 description/triggers/negative_triggers 则按行 upsert/remove。
        """
        if self._body_survives_rerender(raw):
            return self._render_skill_md(
                name,
                description if description is not None else existing.description,
                pattern if pattern is not None else existing.pattern,
                steps if steps is not None else existing.steps,
                triggers=triggers if triggers is not None else existing.triggers,
                negative_triggers=negative_triggers if negative_triggers is not None else existing.negative_triggers,
            )
        if pattern is not None or steps is not None:
            raise SkillRewriteError(
                f"skill '{name}' has body sections outside '## Pattern'/'## Steps'; rewriting "
                "pattern/steps would drop them. Reflow the body into those two sections first, "
                "or update only description/triggers/negative_triggers."
            )
        merged = metadata_lines(
            name=name,
            description=description if description is not None else existing.description,
            triggers=existing.triggers if triggers is None else triggers,
            negative_triggers=existing.negative_triggers if negative_triggers is None else negative_triggers,
        )
        upserts: dict[str, str] = {}
        removals: list[str] = []
        for key, value in (
            ("description", description),
            ("triggers", triggers),
            ("negative_triggers", negative_triggers),
        ):
            if value is None:
                continue
            rendered = key_line(merged, key)
            if rendered is None:
                removals.append(key)
            else:
                upserts[key] = rendered
        if not upserts and not removals:
            return raw
        patched = patch_frontmatter(raw, upserts, removals)
        if patched is None:
            raise SkillRewriteError(
                f"skill '{name}' has no frontmatter block; updating metadata in place would require rewriting the body."
            )
        return patched

    def update(
        self,
        name: str,
        *,
        description: str | None = None,
        pattern: str | None = None,
        steps: list[str] | None = None,
        tags: list[str] | None = None,
        triggers: list[str] | None = None,
        negative_triggers: list[str] | None = None,
        priority: int | None = None,
    ) -> str | None:
        """部分更新已有技能，并把读、合并、写入置于同一跨进程事务中。

        SKILL.md 事务（description/pattern/steps/triggers/negative_triggers）与
        meta.yaml 事务（tags/priority）各自持锁原子替换；两文件间没有跨文件不变量，
        无需跨文件事务。``atomic_update_text`` 持有各自的文件锁，因此与 ``record_usage``
        或另一个 ``SkillStore`` 实例的更新不会以旧快照覆盖彼此的变更。落点为**拥有根**
        （全局技能的可逆编辑放行，写回它自己的根）。
        """
        try:
            owner = self.owner_root(name)
        except ValueError:
            return None
        if owner is None:
            return None
        safe = validate_skill_name(name)
        md_path = owner / safe / "SKILL.md"
        meta_path = owner / safe / META_FILENAME

        def apply(raw: str) -> tuple[str, bool]:
            if not raw:
                return raw, False
            existing = parse_skill_md(name, raw)
            return (
                self._rerender_or_patch(
                    name,
                    raw,
                    existing,
                    description=description,
                    pattern=pattern,
                    steps=steps,
                    triggers=triggers,
                    negative_triggers=negative_triggers,
                ),
                True,
            )

        with self._mutation_lock:
            updated = atomic_update_text(md_path, apply)
            if tags is not None or priority is not None:

                def apply_meta(meta_raw: str) -> tuple[str, bool]:
                    meta = parse_meta_yaml(meta_raw) if meta_raw.strip() else SkillMeta()
                    meta_updates: dict[str, object] = {}
                    if tags is not None:
                        meta_updates["tags"] = tags
                    if priority is not None:
                        meta_updates["priority"] = priority
                    return render_meta_yaml(meta.model_copy(update=meta_updates)), True

                atomic_update_text(meta_path, apply_meta)
        return str(md_path) if updated else None

    # ---- 使用追踪与策展 ----

    def record_usage(self, name: str) -> None:
        """递增技能使用计数并更新最后使用时间（只写拥有根的 meta.yaml，SKILL.md 零写入）。"""
        try:
            owner = self.owner_root(name)
        except ValueError:
            return
        if owner is None:
            return
        meta_path = owner / validate_skill_name(name) / META_FILENAME

        def increment(meta_raw: str) -> tuple[str, bool]:
            meta = parse_meta_yaml(meta_raw) if meta_raw.strip() else SkillMeta()
            updated = meta.model_copy(
                update={"usage_count": meta.usage_count + 1, "last_used": datetime.now().isoformat()}
            )
            return render_meta_yaml(updated), True

        with self._mutation_lock:
            atomic_update_text(meta_path, increment)

    def stale_skills(self, days: int = 30) -> list[str]:
        """返回超过 N 天未使用的技能名称列表。"""
        return _stale_skills(self, days)

    def archive(self, name: str) -> bool:
        """将技能目录移动到 authoring 根的 .archive/；全局根技能显性拒绝（同 delete）。"""
        try:
            owner = self.owner_root(name)
        except ValueError:
            return False
        if owner is not None and owner != self.authoring_root:
            raise ValueError(
                f"skill '{name}' is owned by another root ({owner}); archive it there or reconcile "
                "with /skill-merge — refusing to archive across roots"
            )
        try:
            src = self.authoring_root / validate_skill_name(name)
        except ValueError:
            return False
        archive_dir = self.authoring_root / ".archive"
        with self._mutation_lock:
            if not src.is_dir():
                return False
            archive_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(archive_dir / name))
            return True

    # ---- 匹配 ----

    def match_skill_details(self, prompt: str, threshold: float) -> list[SkillMatch]:
        """Return explainable, backward-compatible skill matches."""
        return _match_skill_details(self, prompt, threshold)
