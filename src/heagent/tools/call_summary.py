"""工具调用「作用对象」的单行摘要（纯展示辅助，无副作用）。

CLI / GUI 需要一行文字说明「这次调用在操作什么」——读写的是哪个文件、执行的是哪条
命令、抓的是哪个 URL、委派给哪个角色的子 Agent。本模块是该信息的**唯一来源**（纯
函数、零 heagent 依赖），供 ``AgentLoop.run_stream`` 的流式事件、``ToolExecutor`` 的
执行事件（进日志与审计）以及各展示层共用，避免多处各写一套映射而漂移；
「工具 → 作用对象」的拼接同源（:func:`activity_label`），展示层不得各自拼箭头。

设计约定：

- **绝不抛异常**：参数形状异常一律退化为「无摘要」（空串）——展示逻辑不得因工具参数
  畸形而中断 agent 循环；调用方无需 try/except。
- **只回显参数，不推断语义**：不做路径解析、不碰文件系统，避免展示开销与副作用。
- **单行 + 截断**：换行/多空白折叠为单个空格（防终端串行），超长截断加省略号；
  例外见 :data:`_NO_TRUNCATE_TOOLS`（shell 命令全文保留，只折叠不截断）。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

# 摘要总长上限（字符）：超长截断，防单个参数（超长路径 / 自由文本）刷屏。
# shell 命令不受此限——见 :data:`_NO_TRUNCATE_TOOLS`。
_MAX_LENGTH = 72
# 自由文本参数（task / prompt / fact / query）的展示长度上限。
_MAX_TEXT = 40
# 「主对象 — 细节」的分隔符（如 ``src — *.py`` / ``coder — 实现登录``）。
_SEPARATOR = " — "
# 「工具 → 作用对象」的箭头（展示层统一经 :func:`activity_label` 拼接）。
_ARROW = " → "

# 工具 → 作为「作用对象」优先展示的参数名（格式无特殊者走这张表）。
# ⚠ ``_describe`` 里单独处理的工具（file_write / git_diff / cron_add / task_delegate /
# task_parallel / file_search / content_search）**不得**出现在本表：特殊分支抢先命中，
# 表项会静默失效（改表不生效的死配置，见 tests 的 test_every_table_entry_is_reachable）。
_TARGET_FIELDS: dict[str, str] = {
    "file_read": "path",
    "git_status": "path",
    "git_log": "path",
    "git_blame": "file_path",
    "web_fetch": "url",
    "shell": "command",
    "cron_remove": "job_id",
    "fact_add": "fact",
    "profile_update": "section",
    "skill_create": "name",
    "skill_update": "name",
    "skill_delete": "name",
    "skill_archive": "name",
    "skill_curate": "days",
}

# 未给 path 时以当前目录为作用对象显示的 git 工具（handler 亦缺省为仓库根）。
# ``git_blame`` 不在其中：它的 ``file_path`` 是必填，无参时「无摘要」比谎报 "." 诚实。
_DOT_DEFAULT_TOOLS = frozenset({"git_status", "git_log"})
# 需要按 :data:`_MAX_TEXT` 截断的自由文本参数（其余参数如路径/URL 只受总长限制）。
# ``command`` 不在此列——shell 命令由 :data:`_NO_TRUNCATE_TOOLS` 全文保留。
_FREEFORM_FIELDS = frozenset({"task", "fact"})
# 作用对象必须看全的工具：不做任何长度截断，仅折叠空白（换行 / 连续空格）。
# 截断后的命令无法判断「它到底改了什么、跑了什么」——这是审查与审计场景里
# 信息损失最大的一类参数，版面让位于可读性。
_NO_TRUNCATE_TOOLS = frozenset({"shell"})


def summarize_tool_call(name: str, arguments: Mapping[str, object] | None = None) -> str:
    """返回一次工具调用的「作用对象」摘要，如 ``docs/frame.md`` / ``0 9 * * * — 每日摘要``。

    无法归纳（无参工具、参数缺失、形状异常）时返回空串——调用方据此省略摘要段。
    shell 命令不做长度截断（全文），其余按 :data:`_MAX_LENGTH` / :data:`_MAX_TEXT` 截断。
    本函数永不抛异常。
    """
    try:
        args = dict(arguments or {})
        raw = _describe(name, args)
        # shell 命令全文保留（含超长多行命令）：审查时「跑的是什么」比版面重要。
        limit = None if name in _NO_TRUNCATE_TOOLS else _MAX_LENGTH
    except Exception:  # noqa: BLE001 - 展示层兜底：任何意外都退化为「无摘要」
        return ""
    return _collapse(raw, limit) if raw else ""


def activity_label(name: str, target: str) -> str:
    """``<tool> → <target>`` 单行活动标签（无作用对象时只留工具名）。

    CLI 提示行 / 状态行、GUI 聊天日志 / 状态栏、工具活动台账**统一走本函数**。
    各展示层自行拼 ``f"{name} → {target}"`` 即是漂移源头（一处改了，另三处漏改），
    2026-09-14 复核实测 GUI 曾出现「带 target」与「不带 target」两套口径并存。
    纯字符串拼接，永不抛异常。
    """
    if not target:
        return name or ""
    return f"{name}{_ARROW}{target}" if name else target


def _describe(name: str, args: dict[str, Any]) -> str:
    """按工具名分派到「主对象（+ 细节）」的摘要策略；返回未截断原文。"""
    if "__" in name:  # MCP 工具命名约定：<server>__<tool>（与 PolicyEngine._is_mcp_tool 一致）
        return _mcp_target(name)
    if name in {"file_search", "content_search"}:
        return _search_target(name, args)
    if name == "file_write":
        return _with_detail(_text(args.get("path")), _written_size(args.get("content")))
    if name == "git_diff":
        return _with_detail(_text(args.get("path")) or ".", "staged" if args.get("staged") else "")
    if name == "cron_add":
        return _with_detail(_text(args.get("schedule")), _clip(args.get("prompt")))
    if name == "task_delegate":
        return _with_detail(_text(args.get("role")), _clip(args.get("task")))
    if name == "task_parallel":
        return _parallel_target(args)

    field = _TARGET_FIELDS.get(name)
    if field is not None:
        value = args.get(field)
        if name in _NO_TRUNCATE_TOOLS:
            summary = _flatten(value)
        else:
            summary = _clip(value) if field in _FREEFORM_FIELDS else _text(value)
        # git 系列未给 path 时作用对象是仓库根（handler 自身也如此缺省），显示为 "."。
        return summary or ("." if name in _DOT_DEFAULT_TOOLS else "")
    return _first_text(args)


def _mcp_target(name: str) -> str:
    """``github__create_issue`` → ``github/create_issue``（server/tool 一行可读）。"""
    server, _, tool = name.partition("__")
    return f"{server}/{tool}" if tool else name


def _search_target(name: str, args: dict[str, Any]) -> str:
    """搜索类：目录为主、检索式为细节（``src — *.py`` / ``. — 正则``），目录缺省为 ``.``。"""
    detail = _clip(args.get("pattern")) if name == "file_search" else _clip(args.get("query"))
    return _with_detail(_text(args.get("directory")) or ".", detail)


def _parallel_target(args: dict[str, Any]) -> str:
    """并行委派：``coder — 3 个子任务``（任务数从 tasks_json 解析，解析失败则不显示）。"""
    count = _task_count(args.get("tasks_json"))
    return _with_detail(_text(args.get("role")), f"{count} 个子任务" if count else "")


def _task_count(raw: object) -> int:
    """从 ``tasks_json``（JSON 数组字符串）解析子任务数；非数组/解析失败返回 0。"""
    if not isinstance(raw, str):
        return 0
    try:
        payload = json.loads(raw)
    except ValueError:
        return 0
    return len(payload) if isinstance(payload, list) else 0


def _written_size(content: object) -> str:
    """写入内容长度（字符）；非字符串（缺参）返回空串。"""
    return f"{len(content)} 字符" if isinstance(content, str) else ""


def _first_text(args: dict[str, Any]) -> str:
    """兜底：展示第一个非空字符串参数（无显式映射的工具）。"""
    for value in args.values():
        if isinstance(value, str) and value.strip():
            return _clip(value)
    return ""


def _with_detail(primary: str, detail: str) -> str:
    """拼接「主对象 — 细节」；缺一侧时只返回另一侧。"""
    if primary and detail:
        return f"{primary}{_SEPARATOR}{detail}"
    return primary or detail


def _text(value: object) -> str:
    """把参数值渲染为单行短文本（接受字符串与数值标量，其余类型忽略）。"""
    if isinstance(value, str):
        return _collapse(value, _MAX_LENGTH)
    if value is None or isinstance(value, bool):
        return ""
    if isinstance(value, int | float):
        return str(value)
    return ""


def _clip(value: object) -> str:
    """自由文本参数：折叠空白后按 :data:`_MAX_TEXT` 截断。"""
    return _collapse(value, _MAX_TEXT) if isinstance(value, str) else _text(value)


def _flatten(value: object) -> str:
    """必须看全的自由文本（shell 命令）：折叠空白但不截断，字符内容零丢失。"""
    return _collapse(value, None) if isinstance(value, str) else _text(value)


def _collapse(text: str, limit: int | None) -> str:
    """折叠内部空白为单空格、去首尾；``limit=None`` 表示不截断。"""
    flat = " ".join(text.split())
    if limit is None or len(flat) <= limit:
        return flat
    return f"{flat[: limit - 1]}…"
