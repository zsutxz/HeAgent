"""技能数据模型与 SKILL.md 解析（memory/skills 拆分层，Phase 4 C4）。

承载解析/校验的纯函数与 Pydantic 模型：:class:`SkillContent`（结构化字段）、
:class:`SkillMatch`（匹配结果）、:class:`SkillRewriteError`、
:func:`parse_skill_md`（frontmatter + 正文解析）、
:func:`validate_skill_name`（名称白名单）。持久化更新见 :mod:`.skill_rewrite`，
存储类见 :mod:`.skill_store`，检索见 :mod:`.skill_catalog`，
meta.yaml 契约见 :mod:`.skill_meta`。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from heagent.pub.frontmatter import FRONTMATTER_NEWLINE_RE, parse_inline_pairs
from heagent.skills.skill_meta import SkillMetaError, detect_legacy_skill_md_keys, parse_inline_list

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
    #: ``created`` 及以下五个字段不在 SKILL.md frontmatter——由 SkillStore.parse 从
    #: meta.yaml 合并填充；直接调用 parse_skill_md 时取默认值。
    created: str = ""
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

    触发面四键之外的元数据字段（created/tags/priority/usage_count/last_used 等）不在
    frontmatter 里——它们由调用方（:meth:`SkillStore.parse`）从 meta.yaml 合并，此处恒为
    默认值。frontmatter 残留 meta 契约键 ⇒ :class:`SkillMetaError`（旧格式显性失败，
    指向迁移脚本），缺失字段仍默认为空字符串/空列表。
    """
    description = ""
    pattern_lines: list[str] = []
    steps: list[str] = []
    triggers: list[str] = []
    negative_triggers: list[str] = []

    # 分离 frontmatter 和正文（模式与「只改元数据」的就地改写共用，见 FRONTMATTER_RE）
    body = content
    fm_match = FRONTMATTER_RE.match(content)
    if fm_match:
        fm_text = fm_match.group(1)
        body = content[fm_match.end() :]
        legacy = detect_legacy_skill_md_keys(fm_text)
        if legacy:
            raise SkillMetaError(
                f"SKILL.md frontmatter holds meta contract keys {legacy}; "
                "move them to meta.yaml (scripts/migrate_skill_meta.py migrates existing skills)"
            )
        # 简单解析 frontmatter（不引入 yaml 依赖）：键识别移入共享宽档解析，值 coercion 留在本地。
        pairs = parse_inline_pairs(fm_text, keys=("description", "triggers", "negative_triggers"))
        description = pairs.get("description", "").strip().strip('"').strip("'")
        triggers = parse_inline_list(pairs.get("triggers", ""))
        negative_triggers = parse_inline_list(pairs.get("negative_triggers", ""))

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
        triggers=triggers,
        negative_triggers=negative_triggers,
    )
