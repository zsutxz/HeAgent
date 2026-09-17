"""GOAL.md 文档生成与 goal 命名约定（/goal 命令族的文档层）。

**为什么单独成模块**（wiring.py 先例）：此前这段「goal 文档与命名」逻辑（约 150 行——
slug 词表、goal_id 规则、目录命名、GOAL.md 生成与增量更新）与工作流驱动（advance /
execute / dispatch / cron）混在 cli_goal.py 里——前者随 BMad 产物约定变，后者随执行
编排变，混在一起使 cli_goal.py 既难读也难测。本模块只做「文档与命名」：不依赖
agent/providers/cron，可被独立测试。

分层：本子包属入口层（与 cli/gui 同级，供 cli_goal 消费），不被任何下层模块导入。
cli_goal 经 re-export 保持原命名空间可用（``test_goal_declarative_workflow`` /
``test_story_loop`` 经 cli_goal 导入这些私有符号）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from heagent.engine.artifacts import GoalArtifact, parse_artifact
from heagent.persist import atomic_update_text

# goal 状态目录与声明式 workflow 路径（相对路径，使用时锚定 Path.cwd()）。
# Durable user-facing Goal and workflow artifacts belong under the project output
# root. ``.heagent`` remains reserved for runtime configuration and skill code.
_GOALS_DIR = Path("_he-output/goals")
_GOAL_DECLARATIVE_WORKFLOW_PATH = Path(".heagent/workflows/workflow.md")
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
_GOAL_RUN_MAX_ROUNDS = 10
_GOAL_ADVANCED = "advanced"
_GOAL_DONE = "done"
_GOAL_FAILED = "failed"
_GOAL_WAITING = "waiting"


def _goal_document(description: str, goal_id: str) -> str:
    """Create the standard BMad Goal artifact used as the durable goal record."""
    title = " ".join(description.split())
    fence_size = max((len(run) for run in re.findall(r"`+", description)), default=0) + 1
    fence = "`" * max(3, fence_size)
    original = description if description.endswith("\n") else description + "\n"
    return (
        "---\n"
        f"id: goal-{goal_id}\n"
        "type: goal\n"
        "status: planning\n"
        f"title: {title}\n"
        "---\n\n"
        f"# {title}\n\n"
        "## 原始需求（Original Request）\n\n"
        f"{fence}\n{original}{fence}\n\n"
        "## Epics\n\n"
        "- No epics have been decomposed yet.\n"
    )


def _goal_project_id(description: str) -> str:
    """Extract a stable English, letter-only project id from the request."""
    text = re.sub(r"^\s*/goal(?:\s+new)?\s*", "", description.strip(), flags=re.IGNORECASE)
    terms = "|".join(re.escape(item) for item in sorted(_GOAL_NAME_WORDS, key=len, reverse=True))
    words = [
        _GOAL_NAME_WORDS.get(match.group(0), match.group(0)) for match in re.finditer(rf"(?:{terms})|[A-Za-z]+", text)
    ]
    slug = re.sub(r"-+", "-", "-".join(words).casefold()).strip("-")
    slug = re.sub(r"-?(?:19|20)\d{2}(?:-?\d{1,2}){0,2}$", "", slug).strip("-")
    return slug or "project"


def _goal_id_is_valid(goal_id: str) -> bool:
    """Accept new letter-only ids and legacy eight-character hex ids."""
    return bool(_GOAL_ID_RE.fullmatch(goal_id)) or (len(goal_id) == 8 and all(char in _GOAL_HEX for char in goal_id))


def _epic_directory_name(epic: str) -> str:
    """Map an Epic reference from a story list (``E1``) to its directory (``epic-e1``)."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(epic).casefold()).strip("-")
    return f"epic-{slug}" if slug else ""


def _goal_step_artifact_path(goal_dir: Path, step: Any, story: Any = None) -> Path:
    """Map a declared workflow step (or its active story) to a durable output document.

    A story-loop step routes each story into its own subdirectory (``s-1/``,
    ``s-2/``, ...) under the step directory, grouped further by the story's Epic
    (``epic-e1/s-1/``) when the story list declares Epic grouping. Sources
    without grouping keep the flat ``s-<n>/`` layout.
    """
    name = re.sub(r"^step-\d+-", "", step.name.casefold())
    name = re.sub(r"\.md$", "", name)
    slug = re.sub(r"[^a-z0-9]+", "-", name).strip("-") or "step"
    if story is not None:
        story_slug = re.sub(r"[^a-z0-9]+", "-", story.id.casefold()).strip("-") or "story"
        directory = goal_dir / f"step-{step.index:02d}-{slug}"
        epic_dir = _epic_directory_name(getattr(story, "epic", ""))
        if epic_dir:
            directory = directory / epic_dir
        return directory / story_slug / "report.md"
    return goal_dir / f"step-{step.index:02d}-{slug}.md"


def _goal_description(goal_dir: Path) -> str:
    """Load the marked original request from GOAL.md, with legacy fallback."""
    text = (goal_dir / "GOAL.md").read_text(encoding="utf-8")
    artifact = parse_artifact(text)
    section = artifact.sections.get("原始需求（original request）")
    if section:
        match = re.fullmatch(r"(`{3,})\n(.*?)\n\1", section, flags=re.DOTALL)
        return match.group(2) if match else section
    return _goal_document_title(text)


def _goal_user_responses(goal_dir: Path) -> str:
    """Return the accumulated user answers recorded in GOAL.md."""
    text = (goal_dir / "GOAL.md").read_text(encoding="utf-8")
    artifact = parse_artifact(text)
    return artifact.sections.get("用户补充（user responses）", "")


def _goal_record_user_response(goal_dir: Path, response: str) -> None:
    """Append one exact user answer to the single durable Goal document."""
    if not response.strip():
        return
    fence_size = max((len(run) for run in re.findall(r"`+", response)), default=0) + 1
    fence = "`" * max(3, fence_size)
    answer = response if response.endswith("\n") else response + "\n"

    def update(raw: str) -> tuple[str, None]:
        artifact = parse_artifact(raw)
        section_name = "用户补充（User Responses）"
        existing = artifact.sections.get(section_name.casefold(), "")
        response_number = len(re.findall(r"(?m)^### Response \d+\s*$", existing)) + 1
        entry = f"### Response {response_number}\n\n{fence}\n{answer}{fence}\n"
        if existing:
            return raw.rstrip() + "\n\n" + entry, None
        return raw.rstrip() + f"\n\n## {section_name}\n\n" + entry, None

    atomic_update_text(goal_dir / "GOAL.md", update)


def _goal_document_title(text: str) -> str:
    """Read a Goal artifact title without introducing a second metadata file."""
    artifact = parse_artifact(text)
    if not isinstance(artifact, GoalArtifact):
        raise ValueError("declarative GOAL.md must be a Goal artifact")
    return artifact.title
