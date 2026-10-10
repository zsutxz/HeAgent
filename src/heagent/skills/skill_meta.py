"""技能元数据文件（``meta.yaml``）——SKILL.md 触发面与包/运行态元数据的分离契约。

SKILL.md frontmatter 只保留触发面四键（``name`` / ``description`` / ``triggers`` /
``negative_triggers``）；包元数据与运行时状态落在本模块定义的 ``meta.yaml``。
:func:`parse_meta_yaml` / :func:`render_meta_yaml` 是其唯一解析/渲染来源（对齐
:mod:`.skill_rewrite` 之于 SKILL.md 的「唯一格式来源」惯例）。``record_usage`` 只回写
meta.yaml，SKILL.md 运行时只读。语法复用 :func:`heagent.pub.frontmatter.parse_inline_pairs`
行内语法（合法 YAML 流子集），不引入 pyyaml 依赖。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

from heagent.pub.frontmatter import parse_inline_pairs

if TYPE_CHECKING:
    from pathlib import Path

#: SKILL.md frontmatter 的保留键（触发面声明）。
SKILL_MD_KEYS = frozenset({"name", "description", "triggers", "negative_triggers"})
#: meta.yaml 的契约键。
META_KEYS = frozenset(
    {
        "canonical_id",
        "source_id",
        "aliases",
        "version",
        "available",
        "tags",
        "created",
        "priority",
        "usage_count",
        "last_used",
    }
)
META_FILENAME = "meta.yaml"

#: 历史驼峰键 → 规范键（迁移与旧格式检测共用；新格式不再产出驼峰）。
_KEY_ALIASES = {"canonicalId": "canonical_id", "sourceId": "source_id"}

#: 渲染固定键序。缺省约定对齐 skill_rewrite.metadata_lines：列表非空才写、priority 非 0
#: 才写、available 仅 False 才写、usage_count 总写、last_used 非空才写。
META_KEY_ORDER = (
    "canonical_id",
    "source_id",
    "aliases",
    "version",
    "available",
    "tags",
    "created",
    "priority",
    "usage_count",
    "last_used",
)


class SkillMetaError(ValueError):
    """meta.yaml 出现契约外键/非法值，或 SKILL.md 残留 meta 契约键。

    显性失败不做静默兜底。继承 ``ValueError``，与 ``SkillRewriteError`` 同构；
    工具层按 ``ValueError`` 捕获，避免 ``tools`` → ``memory`` 的运行时依赖。
    """


class SkillMeta(BaseModel):
    """一个技能的包元数据与运行时状态（全字段默认值 ⇒ meta.yaml 可整体缺省）。"""

    canonical_id: str = ""
    source_id: str = ""
    aliases: list[str] = Field(default_factory=list)
    version: str = ""
    available: bool = True
    tags: list[str] = Field(default_factory=list)
    created: str = ""
    priority: int = 0
    usage_count: int = 0
    last_used: str = ""


def normalize_meta_key(key: str) -> str:
    """历史驼峰键 → 规范键（解析、旧格式检测与迁移脚本共用同一张别名表）。"""
    return _KEY_ALIASES.get(key, key)


def parse_inline_list(value: str) -> list[str]:
    """``[a, b]`` 行内列表解析——skills 家族共用语法（原 skill_models 私有实现收敛于此）。"""
    value = value.strip()
    if not (value.startswith("[") and value.endswith("]")):
        return [value.strip().strip("\"'")] if value else []
    return [item.strip().strip("\"'") for item in value[1:-1].split(",") if item.strip()]


def parse_meta_yaml(text: str) -> SkillMeta:
    """解析 meta.yaml 全文（裸键值行，无 ``---`` 围栏）；契约外键显性抛 :class:`SkillMetaError`。"""
    pairs = parse_inline_pairs(text.lstrip(chr(0xFEFF)), keys=())
    known: dict[str, str] = {}
    unknown: list[str] = []
    for key, value in pairs.items():
        normalized = normalize_meta_key(key)
        if normalized in META_KEYS:
            known[normalized] = value
        else:
            unknown.append(key)
    if unknown:
        raise SkillMetaError(
            f"{META_FILENAME} has keys outside the contract {sorted(META_KEYS)}: {sorted(set(unknown))}"
        )
    available_value = known.get("available", "true").strip().lower()
    if available_value not in {"true", "false", "1", "0", "yes", "no"}:
        raise SkillMetaError(f"invalid available flag '{available_value}'")
    try:
        priority = int(known.get("priority", "").strip()) if known.get("priority", "").strip() else 0
        usage_count = int(known.get("usage_count", "").strip()) if known.get("usage_count", "").strip() else 0
    except ValueError as exc:
        raise SkillMetaError(f"non-integer priority/usage_count in {META_FILENAME}: {exc}") from exc
    return SkillMeta(
        canonical_id=known.get("canonical_id", "").strip(),
        source_id=known.get("source_id", "").strip(),
        aliases=parse_inline_list(known.get("aliases", "")),
        version=known.get("version", "").strip(),
        available=available_value not in {"false", "0", "no"},
        tags=parse_inline_list(known.get("tags", "")),
        created=known.get("created", "").strip().strip("\"'"),
        priority=priority,
        usage_count=usage_count,
        last_used=known.get("last_used", "").strip().strip("\"'"),
    )


def render_meta_yaml(meta: SkillMeta) -> str:
    """渲染 meta.yaml 全文（:data:`META_KEY_ORDER` 固定键序，缺省字段不写）。"""
    lines: list[str] = []
    if meta.canonical_id:
        lines.append(f"canonical_id: {meta.canonical_id}")
    if meta.source_id:
        lines.append(f"source_id: {meta.source_id}")
    if meta.aliases:
        lines.append(f"aliases: [{', '.join(meta.aliases)}]")
    if meta.version:
        lines.append(f"version: {meta.version}")
    if not meta.available:
        lines.append("available: false")
    if meta.tags:
        lines.append(f"tags: [{', '.join(meta.tags)}]")
    if meta.created:
        lines.append(f"created: {meta.created}")
    if meta.priority:
        lines.append(f"priority: {meta.priority}")
    lines.append(f"usage_count: {meta.usage_count}")
    if meta.last_used:
        lines.append(f'last_used: "{meta.last_used}"')
    return "\n".join(lines) + "\n"


def load_meta(skill_dir: Path) -> SkillMeta:
    """读取技能目录的 meta.yaml；缺文件返回全默认（纯声明面镜像包的常态）。"""
    path = skill_dir / META_FILENAME
    if not path.is_file():
        return SkillMeta()
    return parse_meta_yaml(path.read_text(encoding="utf-8"))


def detect_legacy_skill_md_keys(fm_text: str) -> list[str]:
    """SKILL.md frontmatter 里残留的 meta 契约键（含驼峰别名），排序去重。"""
    found = {
        normalized
        for key in parse_inline_pairs(fm_text, keys=())
        if (normalized := normalize_meta_key(key)) in META_KEYS
    }
    return sorted(found)
