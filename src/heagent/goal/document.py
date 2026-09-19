"""goal 需求文档（require.md）生成与 goal 命名约定（/goal 命令族的文档层）。

**为什么单独成模块**（wiring.py 先例）：此前这段「goal 文档与命名」逻辑（约 150 行——
slug 词表、goal_id 规则、目录命名、需求文档生成与增量更新）与工作流驱动（advance /
execute / dispatch / cron）混在 cli_goal.py 里——前者随 BMad 产物约定变，后者随执行
编排变，混在一起使 cli_goal.py 既难读也难测。本模块只做「文档与命名」：不依赖
agent/providers/cron，可被独立测试。

**文档契约**：``/goal new`` 只落盘**原始需求**（``## 原始需求（Original Request）`` 段），
创建时**不再直接写目标看板文档**；「总结的需求」等初步分析做完后由 step 01 补写同一文档的
``## 总结的需求（Derived Requirements）`` 段。存量 goal 的 ``GOAL.md`` 仍可读
（见 :func:`_goal_document_path`），写入落在解析出的那一份上，不会分裂成两份。

分层：本子包属入口层（与 cli/gui 同级，供 cli_goal 消费），不被任何下层模块导入。
cli_goal 经 re-export 保持原命名空间可用（``test_goal_declarative_workflow`` /
``test_story_loop`` 经 cli_goal 导入这些私有符号）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from heagent.frontmatter import parse_strict_pairs, split_frontmatter
from heagent.persist import atomic_update_text

# goal 状态目录与声明式 workflow 路径（相对路径，使用时锚定 Path.cwd()）。
# Durable user-facing Goal and workflow artifacts belong under the project output
# root. ``.heagent`` remains reserved for runtime configuration and skill code.
_GOALS_DIR = Path("_he-output/goals")
_GOAL_DECLARATIVE_WORKFLOW_PATH = Path(".heagent/workflows/workflow.md")
# 需求文档名：新 goal 一律落 require.md；GOAL.md 只作存量 goal 的读取回落（见 _goal_document_path）。
_GOAL_DOCUMENT_NAME = "require.md"
_LEGACY_GOAL_DOCUMENT_NAME = "GOAL.md"
# 段标题匹配：``## <标题>`` 独占一行（与 artifacts._sections 同形，但不引入 artifact 契约）。
_DOCUMENT_SECTION_RE = re.compile(r"(?m)^##\s+(.+?)\s*$")
# step 01 初步分析前「总结的需求」段的显式占位：它是待办标记，不是需求内容。
_DERIVED_REQUIREMENTS_PLACEHOLDER = "待 step 01（market-research）完成初步分析后补写。"
_GOAL_HEX = frozenset("0123456789abcdef")  # 兼容既有 8 位十六进制 goal_id
_GOAL_ID_RE = re.compile(r"^[a-z][a-z-]*$")
_GOAL_NAME_WORDS = {
    "继续": "continue",
    "开发": "development",
    "项目": "project",
    "功能": "feature",
    "需求": "requirements",
    "分析": "analysis",
    "设计": "design",
    "实现": "implementation",
    "修复": "fix",
    "增强": "enhancement",
    "安全": "security",
    "发布": "release",
    "部署": "deployment",
    "测试": "testing",
    "数据": "data",
    "服务": "service",
    "界面": "interface",
    "工作流": "workflow",
    "智能体": "agent",
    "代理": "agent",
}
# 词表按长度降序展开为正则交替项（长词优先匹配），模块级编译一次；与 _GOAL_ID_RE 同属命名规则常量。
_GOAL_WORDS_RE = re.compile(
    rf"(?:{'|'.join(re.escape(item) for item in sorted(_GOAL_NAME_WORDS, key=len, reverse=True))})|[A-Za-z]+"
)


def _fenced_block(text: str) -> str:
    """Wrap *text* in a code fence longer than any backtick run it contains."""
    fence = "`" * max(3, max((len(run) for run in re.findall(r"`+", text)), default=0) + 1)
    body = text if text.endswith("\n") else text + "\n"
    return f"{fence}\n{body}{fence}"


def _goal_document_path(goal_dir: Path) -> Path:
    """Resolve which requirement document this goal owns.

    New goals write ``require.md``. A goal created before the rename still owns its
    ``GOAL.md``, so an existing file wins over the new name; that keeps reads *and*
    writes on the same document instead of splitting the goal across two files.
    """
    document = goal_dir / _GOAL_DOCUMENT_NAME
    if document.is_file():
        return document
    legacy = goal_dir / _LEGACY_GOAL_DOCUMENT_NAME
    return legacy if legacy.is_file() else document


def _document_section(text: str, name: str) -> str:
    """Return the body of the ``## <name>`` section of a goal document (case-insensitive)."""
    split = split_frontmatter(text)
    body = split[2] if split is not None else text
    matches = list(_DOCUMENT_SECTION_RE.finditer(body))
    wanted = name.casefold()
    for index, match in enumerate(matches):
        if match.group(1).casefold() != wanted:
            continue
        end = matches[index + 1].start() if index + 1 < len(matches) else len(body)
        return body[match.end() : end].strip()
    return ""


def _slug(text: str) -> str:
    """Collapse non-alphanumeric runs to single hyphens and trim edge hyphens."""
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def _goal_document(description: str, goal_id: str) -> str:
    """Create the goal requirement document: the durable record of what was asked.

    Only the original request is known at creation time. The derived summary is
    written by step 01 after its initial analysis, so it starts as an explicit
    placeholder rather than an invented summary.
    """
    title = " ".join(description.split())
    return (
        "---\n"
        f"id: goal-{goal_id}\n"
        "type: requirement\n"
        "status: draft\n"
        f"title: {title}\n"
        "---\n\n"
        f"# {title}\n\n"
        "## 原始需求（Original Request）\n\n"
        f"{_fenced_block(description)}\n\n"
        "## 总结的需求（Derived Requirements）\n\n"
        f"{_DERIVED_REQUIREMENTS_PLACEHOLDER}\n"
    )


def _goal_project_id(description: str) -> str:
    """Extract a stable English, letter-only project id from the request."""
    text = re.sub(r"^\s*/goal(?:\s+new)?\s*", "", description.strip(), flags=re.IGNORECASE)
    words = [_GOAL_NAME_WORDS.get(match.group(0), match.group(0)) for match in _GOAL_WORDS_RE.finditer(text)]
    slug = _slug("-".join(words).casefold())
    slug = re.sub(r"-?(?:19|20)\d{2}(?:-?\d{1,2}){0,2}$", "", slug).strip("-")
    return slug or "project"


def _goal_id_is_valid(goal_id: str) -> bool:
    """Accept new letter-only ids and legacy eight-character hex ids."""
    return bool(_GOAL_ID_RE.fullmatch(goal_id)) or (len(goal_id) == 8 and all(char in _GOAL_HEX for char in goal_id))


def _epic_directory_name(epic: str) -> str:
    """Map an Epic reference from a story list (``E1``) to its directory (``epic-e1``)."""
    slug = _slug(str(epic).casefold())
    return f"epic-{slug}" if slug else ""


def _goal_step_artifact_path(goal_dir: Path, step: Any, story: Any = None) -> Path:
    """Map a declared workflow step (or its active story) to a durable output document.

    A story-loop step routes each story into its own subdirectory (``s-1/``,
    ``s-2/``, ...) under the step directory, grouped further by the story's Epic
    (``epic-e1/s-1/``) when the story list declares Epic grouping. Sources
    without grouping keep the flat ``s-<n>/`` layout.

    命名契约：step 文件名由 ``memory/skill_packages.py`` 的 workflow.md 内联步骤解析生成
    （同款 ``_slug`` 归一化，见其 ``step-NN-<slug>.md`` 组装处）；此处剥离前缀后重 slug，
    两侧规则需保持一致，漂移会使产物路径偏离声明的步骤名。
    """
    name = re.sub(r"^step-\d+-", "", step.name.casefold())
    name = re.sub(r"\.md$", "", name)
    slug = _slug(name) or "step"
    if story is not None:
        story_slug = _slug(story.id.casefold()) or "story"
        directory = goal_dir / f"step-{step.index:02d}-{slug}"
        epic_dir = _epic_directory_name(getattr(story, "epic", ""))
        if epic_dir:
            directory = directory / epic_dir
        return directory / story_slug / "report.md"
    return goal_dir / f"step-{step.index:02d}-{slug}.md"


def _goal_description(goal_dir: Path) -> str:
    """Load the marked original request from the goal's requirement document."""
    text = _goal_document_path(goal_dir).read_text(encoding="utf-8")
    section = _document_section(text, "原始需求（original request）")
    if section:
        match = re.fullmatch(r"(`{3,})\n(.*?)\n\1", section, flags=re.DOTALL)
        return match.group(2) if match else section
    return _goal_document_title(text)


def _goal_user_responses(goal_dir: Path) -> str:
    """Return the accumulated user answers recorded in the requirement document."""
    text = _goal_document_path(goal_dir).read_text(encoding="utf-8")
    return _document_section(text, "用户补充（user responses）")


def _goal_record_user_response(goal_dir: Path, response: str) -> None:
    """Append one exact user answer to the single durable requirement document."""
    if not response.strip():
        return

    def update(raw: str) -> tuple[str, None]:
        section_name = "用户补充（User Responses）"
        existing = _document_section(raw, section_name)
        response_number = len(re.findall(r"(?m)^### Response \d+\s*$", existing)) + 1
        entry = f"### Response {response_number}\n\n{_fenced_block(response)}\n"
        if existing:
            return raw.rstrip() + "\n\n" + entry, None
        return raw.rstrip() + f"\n\n## {section_name}\n\n" + entry, None

    atomic_update_text(_goal_document_path(goal_dir), update)


def _goal_document_title(text: str) -> str:
    """Read the requirement document's title without introducing a second metadata file."""
    split = split_frontmatter(text)
    if split is None:
        raise ValueError("declarative requirement document must start with frontmatter")
    values = parse_strict_pairs(split[0])
    if values.get("type", "").strip().casefold() not in {"requirement", "goal"}:
        raise ValueError("declarative requirement document must declare type: requirement")
    title = values.get("title", "").strip()
    if not title:
        title = next((line[2:].strip() for line in split[2].splitlines() if line.startswith("# ")), "")
    if not title:
        raise ValueError("declarative requirement document must declare a title")
    return title
