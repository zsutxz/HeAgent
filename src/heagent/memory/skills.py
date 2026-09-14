"""技能存储 — 将可复用的操作模式提炼为标准目录结构。

存储路径：.heagent/skills/{name}/SKILL.md
每个技能是一个目录，SKILL.md 为必需文件，使用 YAML frontmatter 定义元数据。
支持解析、部分更新和基于关键词匹配的自动调用。

目录结构（参考 hermes-agent）：
  skills/<name>/
  ├── SKILL.md           # 必须 — 技能定义（frontmatter + markdown 正文）
  ├── references/        # 可选 — 参考文档
  ├── templates/         # 可选 — 模板文件
  └── scripts/           # 可选 — 可执行脚本
"""

from __future__ import annotations

import contextlib
import logging
import re
import shutil
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from heagent.engine.persist import atomic_update_text, atomic_write_text

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping

logger = logging.getLogger(__name__)

# SKILL.md 的 frontmatter 分隔与捕获。``_parse_skill_md`` 与「只改计数、保留正文」的
# 就地改写共用同一模式，避免两份可漂移的副本。
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class SkillRewriteError(ValueError):
    """拒绝会丢正文的技能改写（正文含 ``## Pattern`` / ``## Steps`` 之外的章节）。

    继承 ``ValueError``，与 ``skill_importer.SkillImportError`` 同构；工具层按 ``ValueError``
    捕获，避免 ``tools`` → ``memory`` 的运行时依赖（该方向只允许 ``TYPE_CHECKING``）。
    """


class SkillContent(BaseModel):
    """解析后的技能结构化字段。

    使用 Pydantic BaseModel（项目硬约束：数据模型一律 Pydantic，不得用 dataclass）。
    """

    name: str
    description: str
    pattern: str
    steps: list[str]
    created: str
    tags: list[str] = Field(default_factory=list)
    triggers: list[str] = Field(default_factory=list)
    negative_triggers: list[str] = Field(default_factory=list)
    priority: int = 0
    usage_count: int = 0
    last_used: str = ""


class SkillMatch(BaseModel):
    """Explainable result from the skill matcher."""

    name: str
    score: float
    priority: int = 0
    matched_triggers: list[str] = Field(default_factory=list)


class SkillStore:
    """技能存储管理器，支持 CRUD 操作。

    每个技能以目录形式存储，SKILL.md 为入口文件。
    """

    def __init__(self, base_dir: str = ".heagent/skills") -> None:
        self._base = Path(base_dir)
        # ``record_usage`` performs a read/modify/write cycle and is called
        # from worker threads by parallel sub-agents.  Keep that cycle
        # atomic per store instance; the file lock in ``save`` additionally
        # protects the final replace across processes.
        self._mutation_lock = threading.Lock()

    # ---- 路径工具 ----

    def _skill_dir(self, name: str) -> Path:
        """技能目录路径（名称规范化复用 _validate_name，保证 save/delete/load 路径一致）。"""
        return self._base / self._validate_name(name)

    def _skill_md(self, name: str) -> Path:
        """SKILL.md 文件路径。"""
        return self._skill_dir(name) / "SKILL.md"

    @staticmethod
    def _render_skill_md(
        name: str,
        description: str,
        pattern: str,
        steps: list[str],
        *,
        tags: list[str] | None,
        triggers: list[str] | None,
        negative_triggers: list[str] | None,
        priority: int,
        usage_count: int,
        last_used: str,
        created: str,
    ) -> str:
        """Render the canonical on-disk representation for one skill."""
        fm_lines = [
            "---",
            *_metadata_lines(
                name=name,
                description=description,
                created=created,
                tags=tags,
                triggers=triggers,
                negative_triggers=negative_triggers,
                priority=priority,
                usage_count=usage_count,
                last_used=last_used,
            ),
            "---",
            "",
        ]

        body_lines = [f"# {name}", ""]
        if pattern:
            body_lines.extend(["## Pattern", pattern, ""])
        body_lines.append("## Steps")
        body_lines.extend(f"{i}. {step}" for i, step in enumerate(steps, 1))
        body_lines.append("")
        return "\n".join(fm_lines) + "\n" + "\n".join(body_lines)

    @staticmethod
    def _body_survives_rerender(raw: str) -> bool:
        """正文是否能被 :meth:`_render_skill_md` 无损表达。

        渲染器只产出 ``# <name>`` / ``## Pattern`` / ``## Steps``，解析器也只读后两节；
        其余章节（手写角色契约、附加说明）在任何整体重渲染中都会被丢弃。返回 False 的
        技能必须走「只改 frontmatter 计数、正文逐字节保留」的就地路径。
        """
        match = _FRONTMATTER_RE.match(raw)
        body = raw[match.end() :] if match is not None else raw
        section = ""
        for line in body.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if stripped == "## Pattern":
                section = "pattern"
                continue
            if stripped == "## Steps":
                section = "steps"
                continue
            if stripped.startswith("#"):
                if stripped.startswith("# ") and not section:
                    continue  # 渲染器写的 H1 标题，重渲染会原样重建
                return False
            if not section:
                return False
        return True

    @staticmethod
    def _validate_name(name: str) -> str:
        """校验技能名称：仅允许英文、数字、下划线和连字符。"""
        safe = name.replace(" ", "_").replace("/", "-")
        if not safe.isascii() or not all(c.isalnum() or c in "_-" for c in safe):
            raise ValueError(f"Skill name must be English alphanumeric with _ or -, got: '{name}'")
        return safe

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

        创建 skills/<name>/SKILL.md，包含 YAML frontmatter 和 Markdown 正文。
        返回 SKILL.md 的路径。

        ``created`` 为 None 时自动生成当前时间；``update()`` / ``record_usage()``
        透传原值，防止每次调用覆写原始创建时间（P1-7 修复）。
        """
        safe = self._validate_name(name)
        skill_dir = self._base / safe
        skill_dir.mkdir(parents=True, exist_ok=True)

        if created is None:
            created = datetime.now().isoformat()
        content = self._render_skill_md(
            safe,
            description,
            pattern,
            steps,
            tags=tags,
            triggers=triggers,
            negative_triggers=negative_triggers,
            priority=priority,
            usage_count=usage_count,
            last_used=last_used,
            created=created,
        )
        md_path = skill_dir / "SKILL.md"
        atomic_write_text(md_path, content, lock=True)
        return str(md_path)

    def load(self, name: str) -> str | None:
        """按名称加载 SKILL.md 内容。不存在或名称非法返回 None。"""
        try:
            path = self._skill_md(name)
        except ValueError:
            return None
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def list_skills(self) -> list[str]:
        """返回所有已存储的技能名称（目录名，按名称排序）。"""
        if not self._base.exists():
            return []
        return sorted(d.name for d in self._base.iterdir() if d.is_dir() and (d / "SKILL.md").exists())

    def delete(self, name: str) -> bool:
        """删除指定技能目录。返回是否成功删除。"""
        try:
            skill_dir = self._skill_dir(name)
        except ValueError:
            return False
        if skill_dir.is_dir():
            shutil.rmtree(skill_dir)
            return True
        return False

    def all_skills_content(self) -> list[str]:
        """返回所有技能 SKILL.md 的完整内容（用于注入系统提示词）。"""
        if not self._base.exists():
            return []
        contents: list[str] = []
        for name in self.list_skills():
            raw = self.load(name)
            if raw:
                contents.append(raw)
        return contents

    # ---- 解析与更新 ----

    def parse(self, name: str) -> SkillContent | None:
        """将 SKILL.md 解析为结构化字段。不存在返回 None。"""
        raw = self.load(name)
        if raw is None:
            return None
        return self._parse_skill_md(name, raw)

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
        """部分更新已有技能。仅覆盖非 None 字段，其余保持原样。返回 SKILL.md 路径或 None。

        正文不可被渲染器无损表达时（见 :meth:`_body_survives_rerender`）分两路：只改元数据
        字段 → 就地改写 frontmatter、正文逐字节保留；要求改 ``pattern`` / ``steps`` → 抛
        :class:`SkillRewriteError`（显式拒绝，而非静默丢正文）。
        """
        existing = self.parse(name)
        if existing is None:
            return None
        raw = self.load(name) or ""
        if not self._body_survives_rerender(raw):
            return self._update_preserving_body(
                name,
                raw,
                existing,
                description=description,
                pattern=pattern,
                steps=steps,
                tags=tags,
                triggers=triggers,
                negative_triggers=negative_triggers,
                priority=priority,
            )
        return self.save(
            name,
            description if description is not None else existing.description,
            pattern if pattern is not None else existing.pattern,
            steps if steps is not None else existing.steps,
            tags=tags if tags is not None else existing.tags,
            triggers=triggers if triggers is not None else existing.triggers,
            negative_triggers=negative_triggers if negative_triggers is not None else existing.negative_triggers,
            priority=priority if priority is not None else existing.priority,
            usage_count=existing.usage_count,
            last_used=existing.last_used,
            created=existing.created,  # P1-7 修复：保留原始创建时间
        )

    def _update_preserving_body(
        self,
        name: str,
        raw: str,
        existing: SkillContent,
        *,
        description: str | None,
        pattern: str | None,
        steps: list[str] | None,
        tags: list[str] | None,
        triggers: list[str] | None,
        negative_triggers: list[str] | None,
        priority: int | None,
    ) -> str:
        """就地更新元数据字段、正文逐字节保留；要求改正文则抛错。

        正文含渲染器表达不了的章节时，整体重渲染会把它们丢掉——故只把元数据字段按
        :func:`_metadata_lines` 的规范行就地替换/删除。
        """
        if pattern is not None or steps is not None:
            raise SkillRewriteError(
                f"skill '{name}' has body sections outside '## Pattern'/'## Steps'; rewriting "
                "pattern/steps would drop them. Reflow the body into those two sections first, "
                "or update only description/tags/triggers/negative_triggers/priority."
            )
        merged = _metadata_lines(
            name=name,
            description=description if description is not None else existing.description,
            created=existing.created,
            tags=existing.tags if tags is None else tags,
            triggers=existing.triggers if triggers is None else triggers,
            negative_triggers=existing.negative_triggers if negative_triggers is None else negative_triggers,
            priority=existing.priority if priority is None else priority,
            usage_count=existing.usage_count,
            last_used=existing.last_used,
        )
        upserts: dict[str, str] = {}
        removals: list[str] = []
        for key, value in (
            ("description", description),
            ("tags", tags),
            ("triggers", triggers),
            ("negative_triggers", negative_triggers),
            ("priority", priority),
        ):
            if value is None:
                continue  # 调用方未要求改动该字段，保持原样
            rendered = _key_line(merged, key)
            if rendered is None:
                removals.append(key)  # 规范行缺省（如空 tags）→ 删除该行
            else:
                upserts[key] = rendered
        if not upserts and not removals:
            return str(self._skill_md(name))  # 无元数据改动：不写盘
        patched = _patch_frontmatter(raw, upserts, removals)
        if patched is None:
            raise SkillRewriteError(
                f"skill '{name}' has no frontmatter block; updating metadata in place would require rewriting the body."
            )
        md_path = self._skill_md(name)
        atomic_write_text(md_path, patched, lock=True)
        return str(md_path)

    # ---- 使用追踪与策展 ----

    def record_usage(self, name: str) -> None:
        """递增技能使用计数并更新最后使用时间。"""
        try:
            md_path = self._skill_md(name)
        except ValueError:
            return

        def increment(raw: str) -> tuple[str, bool]:
            if not raw:
                return raw, False
            existing = self._parse_skill_md(name, raw)
            now = datetime.now().isoformat()
            if not self._body_survives_rerender(raw):
                # 正文含 Pattern/Steps 之外的章节：整体重渲染会把它们静默丢弃
                # （实测 130 行角色契约会被削成 411 字符空壳），故只就地改写计数。
                patched = _update_usage_frontmatter(raw, existing, now)
                if patched is None:
                    logger.warning(
                        "Skill %s: no frontmatter to update and a re-render would drop body content; "
                        "usage not recorded",
                        name,
                    )
                    return raw, False
                logger.info("Skill %s: usage counters updated in place to preserve body sections", name)
                return patched, True
            content = self._render_skill_md(
                name,
                existing.description,
                existing.pattern,
                existing.steps,
                tags=existing.tags or None,
                triggers=existing.triggers or None,
                negative_triggers=existing.negative_triggers or None,
                priority=existing.priority,
                usage_count=existing.usage_count + 1,
                last_used=now,
                created=existing.created,
            )
            return content, True

        with self._mutation_lock:
            atomic_update_text(md_path, increment)

    def stale_skills(self, days: int = 30) -> list[str]:
        """返回超过 N 天未使用的技能名称列表。"""
        cutoff = datetime.now() - timedelta(days=days)
        stale: list[str] = []
        for name in self.list_skills():
            parsed = self.parse(name)
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

    def archive(self, name: str) -> bool:
        """将技能目录移动到 .heagent/skills/.archive/。"""
        try:
            src = self._skill_dir(name)
        except ValueError:
            return False
        if not src.is_dir():
            return False
        archive_dir = self._base / ".archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(archive_dir / name))
        return True

    # ---- 匹配 ----

    def match_skill_details(self, prompt: str, threshold: float) -> list[SkillMatch]:
        """Return explainable, backward-compatible skill matches."""
        if not prompt.strip():
            return []
        prompt_text = prompt.casefold()
        prompt_tokens = _skill_tokens(prompt)
        matches: list[SkillMatch] = []
        for name in self.list_skills():
            parsed = self.parse(name)
            if parsed is None:
                continue
            if any(trigger.casefold() in prompt_text for trigger in parsed.negative_triggers):
                continue
            pattern_tokens = _skill_tokens(f"{parsed.pattern} {' '.join(parsed.tags)}")
            matched_triggers = [t for t in parsed.triggers if t.casefold() in prompt_text]
            trigger_hit = bool(matched_triggers)
            if not pattern_tokens and not trigger_hit:
                continue
            overlap = len(prompt_tokens & pattern_tokens)
            ratio = overlap / len(pattern_tokens) if pattern_tokens else 0.0
            # Explicit triggers are high-confidence; ordinary matching retains the old threshold semantics.
            score = 1.0 if trigger_hit else ratio
            if score >= threshold:
                matches.append(
                    SkillMatch(name=name, score=score, priority=parsed.priority, matched_triggers=matched_triggers)
                )
        matches.sort(key=lambda item: (-bool(item.matched_triggers), -item.score, -item.priority, item.name))
        return matches

    def matching_skills(self, prompt: str, threshold: float) -> list[str]:
        """Return matching names; retained as the legacy public API."""
        return [match.name for match in self.match_skill_details(prompt, threshold)]

    # ---- 解析器 ----

    @staticmethod
    def _parse_skill_md(name: str, content: str) -> SkillContent:  # noqa: C901
        """解析 SKILL.md（YAML frontmatter + Markdown 正文）为结构化字段。

        容错处理：缺失字段默认为空字符串/空列表，不抛异常。
        """
        description = ""
        created = ""
        tags: list[str] = []
        pattern_lines: list[str] = []
        steps: list[str] = []
        usage_count: int = 0
        last_used: str = ""
        triggers: list[str] = []
        negative_triggers: list[str] = []
        priority = 0

        # 分离 frontmatter 和正文（模式与「只改计数」的就地改写共用，见 _FRONTMATTER_RE）
        body = content
        fm_match = _FRONTMATTER_RE.match(content)
        if fm_match:
            fm_text = fm_match.group(1)
            body = content[fm_match.end() :]
            # 简单解析 frontmatter（不引入 yaml 依赖）
            for line in fm_text.splitlines():
                stripped = line.strip()
                if stripped.startswith("description:"):
                    description = stripped.split(":", 1)[1].strip().strip('"').strip("'")
                elif stripped.startswith("created:"):
                    created = stripped.split(":", 1)[1].strip()
                elif stripped.startswith("tags:"):
                    tag_part = stripped.split(":", 1)[1].strip()
                    if tag_part.startswith("[") and tag_part.endswith("]"):
                        tags = [t.strip() for t in tag_part[1:-1].split(",") if t.strip()]
                elif stripped.startswith("triggers:"):
                    triggers = _parse_inline_list(stripped.split(":", 1)[1])
                elif stripped.startswith("negative_triggers:"):
                    negative_triggers = _parse_inline_list(stripped.split(":", 1)[1])
                elif stripped.startswith("priority:"):
                    with contextlib.suppress(ValueError):
                        priority = int(stripped.split(":", 1)[1].strip())
                elif stripped.startswith("usage_count:"):
                    with contextlib.suppress(ValueError):
                        usage_count = int(stripped.split(":", 1)[1].strip())
                elif stripped.startswith("last_used:"):
                    last_used = stripped.split(":", 1)[1].strip().strip('"').strip("'")

        # 解析正文
        section = ""
        for line in body.splitlines():
            stripped = line.strip()
            if stripped == "## Pattern":
                section = "pattern"
            elif stripped == "## Steps":
                section = "steps"
            elif section == "pattern" and stripped:
                pattern_lines.append(stripped)
            elif section == "steps" and stripped:
                dot_pos = stripped.find(". ")
                if dot_pos >= 0 and stripped[:dot_pos].isdigit():
                    steps.append(stripped[dot_pos + 2 :])
                else:
                    steps.append(stripped)

        return SkillContent(
            name=name,
            description=description,
            pattern="\n".join(pattern_lines),
            steps=steps,
            created=created,
            tags=tags,
            triggers=triggers,
            negative_triggers=negative_triggers,
            priority=priority,
            usage_count=usage_count,
            last_used=last_used,
        )


def _metadata_lines(
    *,
    name: str,
    description: str,
    created: str,
    tags: list[str] | None,
    triggers: list[str] | None,
    negative_triggers: list[str] | None,
    priority: int,
    usage_count: int,
    last_used: str,
) -> list[str]:
    """frontmatter 主体行（不含首尾 ``---``）——渲染与就地改写共用的唯一格式来源。"""
    lines = [f"name: {name}", f'description: "{description}"', f"created: {created}"]
    for key, values in (
        ("tags", tags),
        ("triggers", triggers),
        ("negative_triggers", negative_triggers),
    ):
        if values:
            lines.append(f"{key}: [{', '.join(values)}]")
    if priority:
        lines.append(f"priority: {priority}")
    lines.append(f"usage_count: {usage_count}")
    if last_used:
        lines.append(f'last_used: "{last_used}"')
    return lines


def _key_line(lines: list[str], key: str) -> str | None:
    """取 ``key:`` 开头的规范行；该字段缺省时返回 None。"""
    prefix = f"{key}:"
    return next((line for line in lines if line.startswith(prefix)), None)


def _patch_frontmatter(raw: str, upserts: Mapping[str, str], removals: Collection[str] = ()) -> str | None:
    """就地改写 frontmatter：``upserts`` 整行替换，``removals`` 删除整行。

    正文与未涉及的 frontmatter 行逐字节保留（按 group(1) 跨度替换，分隔符与空行不受
    影响）。无 frontmatter 块时返回 None——调用方保留原文件，不做猜测性改写。
    """
    match = _FRONTMATTER_RE.match(raw)
    if match is None:
        return None
    remove = set(removals)
    keys = (*upserts, *remove)
    lines: list[str] = []
    seen: set[str] = set()
    for line in match.group(1).splitlines():
        stripped = line.strip()
        key = next((candidate for candidate in keys if stripped.startswith(f"{candidate}:")), None)
        if key is None:
            lines.append(line)
            continue
        seen.add(key)
        if key in upserts:
            lines.append(upserts[key])
    for key, replacement in upserts.items():
        if key not in seen:
            lines.append(replacement)
    return raw[: match.start(1)] + "\n".join(lines) + raw[match.end(1) :]


def _update_usage_frontmatter(raw: str, existing: SkillContent, last_used: str) -> str | None:
    """只改写 usage_count / last_used，正文与其余行逐字节保留。

    供「正文含 ``## Pattern`` / ``## Steps`` 之外章节」的技能使用（见
    :meth:`SkillStore._body_survives_rerender`）。无 frontmatter 时返回 None：不做猜测性
    改写，调用方保留原文件并记 warning（显性可观测，而非静默丢计数）。
    """
    lines = _metadata_lines(
        name=existing.name,
        description=existing.description,
        created=existing.created,
        tags=existing.tags or None,
        triggers=existing.triggers or None,
        negative_triggers=existing.negative_triggers or None,
        priority=existing.priority,
        usage_count=existing.usage_count + 1,
        last_used=last_used,
    )
    return _patch_frontmatter(
        raw,
        {
            "usage_count": _key_line(lines, "usage_count") or f"usage_count: {existing.usage_count + 1}",
            "last_used": _key_line(lines, "last_used") or f'last_used: "{last_used}"',
        },
    )


def _parse_inline_list(value: str) -> list[str]:
    value = value.strip()
    if not (value.startswith("[") and value.endswith("]")):
        return [value.strip().strip("\"'")] if value else []
    return [item.strip().strip("\"'") for item in value[1:-1].split(",") if item.strip()]


def _skill_tokens(text: str) -> set[str]:
    """Dependency-free mixed-language tokens with CJK bigrams/trigrams."""
    chunks = re.findall(r"[a-zA-Z0-9_]+|[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]+", text.casefold())
    tokens: set[str] = set()
    for chunk in chunks:
        if not re.fullmatch(r"[\u3400-\u9fff\u3040-\u30ff\uac00-\ud7af]+", chunk):
            tokens.add(chunk)
            continue
        # Whole CJK runs depend on whitespace boundaries and make coverage unfair:
        # use only two/three-character evidence, excluding low-signal single characters.
        for size in (2, 3):
            tokens.update(chunk[i : i + size] for i in range(len(chunk) - size + 1))
    return tokens
