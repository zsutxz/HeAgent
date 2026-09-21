"""技能数据模型与 SKILL.md 解析（memory/skills 拆分层，Phase 4 C4）。

承载解析/校验的纯函数与 Pydantic 模型：:class:`SkillContent`（结构化字段）、
:class:`SkillMatch`（匹配结果）、:class:`SkillRewriteError`、
:func:`parse_skill_md`（frontmatter + 正文解析，容错不抛）、
:func:`validate_skill_name`（名称白名单）。持久化更新见 :mod:`.skill_rewrite`，
存储类见 :mod:`.skill_store`，检索见 :mod:`.skill_catalog`。
"""

from __future__ import annotations

import contextlib

from pydantic import BaseModel, Field

from heagent.frontmatter import FRONTMATTER_NEWLINE_RE, parse_inline_pairs

# SKILL.md 的 frontmatter 分隔与捕获。解析与「只改计数、保留正文」的就地改写（skill_rewrite）
# 共用同一模式，避免两份可漂移的副本。
FRONTMATTER_RE = FRONTMATTER_NEWLINE_RE


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


def validate_skill_name(name: str) -> str:
    """校验技能名称：仅允许英文、数字、下划线和连字符。"""
    safe = name.replace(" ", "_").replace("/", "-")
    if not safe.isascii() or not all(c.isalnum() or c in "_-" for c in safe):
        raise ValueError(f"Skill name must be English alphanumeric with _ or -, got: '{name}'")
    return safe


def parse_skill_md(name: str, content: str) -> SkillContent:
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

    # 分离 frontmatter 和正文（模式与「只改计数」的就地改写共用，见 FRONTMATTER_RE）
    body = content
    fm_match = FRONTMATTER_RE.match(content)
    if fm_match:
        fm_text = fm_match.group(1)
        body = content[fm_match.end() :]
        # 简单解析 frontmatter（不引入 yaml 依赖）：键识别移入共享宽档解析，值 coercion 留在本地。
        pairs = parse_inline_pairs(
            fm_text,
            keys=(
                "description",
                "created",
                "tags",
                "triggers",
                "negative_triggers",
                "priority",
                "usage_count",
                "last_used",
            ),
        )
        description = pairs.get("description", "").strip().strip('"').strip("'")
        created = pairs.get("created", "").strip()
        tag_part = pairs.get("tags", "").strip()
        if tag_part.startswith("[") and tag_part.endswith("]"):
            tags = [t.strip() for t in tag_part[1:-1].split(",") if t.strip()]
        triggers = _parse_inline_list(pairs.get("triggers", ""))
        negative_triggers = _parse_inline_list(pairs.get("negative_triggers", ""))
        with contextlib.suppress(ValueError):
            priority = int(pairs.get("priority", "").strip())
        with contextlib.suppress(ValueError):
            usage_count = int(pairs.get("usage_count", "").strip())
        last_used = pairs.get("last_used", "").strip().strip('"').strip("'")

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


def _parse_inline_list(value: str) -> list[str]:
    value = value.strip()
    if not (value.startswith("[") and value.endswith("]")):
        return [value.strip().strip("\"'")] if value else []
    return [item.strip().strip("\"'") for item in value[1:-1].split(",") if item.strip()]
