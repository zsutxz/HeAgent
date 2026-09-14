"""Tests for heagent.tools.call_summary — 工具调用「作用对象」摘要。"""

from __future__ import annotations

from collections.abc import Iterator, Mapping

import pytest

from heagent.tools.call_summary import _TARGET_FIELDS, activity_label, summarize_tool_call


class _BrokenArguments(Mapping[str, object]):
    """参数映射本身损坏（迭代即抛）——用于锁定「摘要绝不抛异常」契约。"""

    def __getitem__(self, key: str) -> object:
        raise RuntimeError("broken arguments")

    def __iter__(self) -> Iterator[str]:
        raise RuntimeError("broken arguments")

    def __len__(self) -> int:
        # 必须非 0：``summarize_tool_call`` 里 ``arguments or {}`` 按 __len__ 判真值，
        # 返回 0 会让它短路成空字典——损坏映射根本不被迭代，except 兜底分支也就永远
        # 测不到（本类存在的唯一目的正是覆盖那个分支）。
        return 1


@pytest.mark.parametrize(
    ("name", "arguments", "expected"),
    [
        # ── 文件读写：路径即作用对象，写操作附带内容长度 ──────────────
        ("file_read", {"path": "docs/frame.md"}, "docs/frame.md"),
        ("file_read", {"path": "src/a.py", "offset": 10, "limit": 20}, "src/a.py"),
        ("file_write", {"path": "docs/x.md", "content": "abc"}, "docs/x.md — 3 字符"),
        # ── 搜索：目录为主、检索式为细节；目录缺省为当前目录 ──────────
        ("file_search", {"directory": "src", "pattern": "*.py"}, "src — *.py"),
        ("file_search", {"pattern": "*.py"}, ". — *.py"),
        ("content_search", {"directory": ".", "query": "policy"}, ". — policy"),
        # ── shell / 联网 / git ──────────────────────────────────────
        ("shell", {"command": "pytest -q"}, "pytest -q"),
        # shell 命令不截断：超过 40 / 72 字符也全文保留（审查要看全「跑了什么」）
        (
            "shell",
            {"command": "cd /d E:\\AI\\HeAgent && git diff src/heagent/agent/loop.py"},
            "cd /d E:\\AI\\HeAgent && git diff src/heagent/agent/loop.py",
        ),
        ("shell", {"command": 42}, "42"),
        ("web_fetch", {"url": "https://example.com/a"}, "https://example.com/a"),
        ("git_status", {}, "."),
        ("git_log", {"max_count": 5}, "."),
        ("git_diff", {"path": "src", "staged": True}, "src — staged"),
        ("git_diff", {"path": "src"}, "src"),
        ("git_blame", {"file_path": "src/heagent/cli.py"}, "src/heagent/cli.py"),
        # file_path 必填：无参时「无摘要」比谎报仓库根 "." 诚实（对照 git_status 缺省 "."）
        ("git_blame", {}, ""),
        # tasks_json 非 str（模型直接给数组）→ 解析为 0 个子任务，只留角色
        ("task_parallel", {"role": "tester", "tasks_json": ["a", "b"]}, "tester"),
        # ── 记忆 / 技能 / cron ──────────────────────────────────────
        ("fact_add", {"fact": "用户偏好中文提交信息"}, "用户偏好中文提交信息"),
        ("profile_update", {"section": "偏好", "value": "任意"}, "偏好"),
        ("skill_create", {"name": "fetch_ai_news", "description": "d", "pattern": "p", "steps": "s"}, "fetch_ai_news"),
        ("skill_update", {"name": "fetch_ai_news"}, "fetch_ai_news"),
        ("skill_delete", {"name": "old_skill"}, "old_skill"),
        ("skill_curate", {"days": 30}, "30"),
        ("cron_add", {"schedule": "0 9 * * *", "prompt": "生成 AI 新闻摘要"}, "0 9 * * * — 生成 AI 新闻摘要"),
        ("cron_remove", {"job_id": "878ec512"}, "878ec512"),
        # ── 子 Agent 委派（展示「执行的 subagent」）──────────────────
        ("task_delegate", {"role": "coder", "task": "实现登录模块"}, "coder — 实现登录模块"),
        ("task_delegate", {"task": "只给任务不给角色"}, "只给任务不给角色"),
        ("task_parallel", {"role": "tester", "tasks_json": '["a", "b", "c"]'}, "tester — 3 个子任务"),
        ("task_parallel", {"role": "tester", "tasks_json": "not json"}, "tester"),
        # ── MCP：<server>__<tool> 归一为 server/tool ─────────────────
        ("github__create_issue", {"title": "t"}, "github/create_issue"),
        # ── 无参 / 参数缺失 / 无映射工具的自定义别名 → 无摘要 ────────
        ("task_status", {}, ""),
        ("cron_list", {}, ""),
        ("skill_list", {}, ""),
        ("file_read", {}, ""),
        ("file_read", {"path": None}, ""),
        ("file_write", {"path": "", "content": ""}, "0 字符"),
    ],
)
def test_summarize_tool_call(name: str, arguments: dict[str, object], expected: str) -> None:
    assert summarize_tool_call(name, arguments) == expected


class TestTruncation:
    """超长参数截断（防单行刷屏 / 终端串行），且换行被折叠为空格。"""

    def test_path_is_truncated_with_ellipsis(self) -> None:
        summary = summarize_tool_call("file_read", {"path": "a" * 200})

        assert summary.endswith("…")
        assert len(summary) == 72

    def test_shell_command_is_never_truncated(self) -> None:
        """shell 命令全文保留——截断后无法判断「它到底跑了什么」（审查 / 审计）。"""
        command = "x" * 200

        summary = summarize_tool_call("shell", {"command": command})

        assert summary == command
        assert "…" not in summary

    def test_long_multiline_shell_command_keeps_every_character(self) -> None:
        """多行长命令折叠为单行后仍零丢失，且不受 40 / 72 任一上限约束。"""
        command = "\n".join(f"echo step-{index}" for index in range(50))

        summary = summarize_tool_call("shell", {"command": command})

        assert summary == " ".join(f"echo step-{index}" for index in range(50))
        assert len(summary) > 72

    def test_freeform_task_and_fact_stay_clipped(self) -> None:
        """自由文本（子 Agent 任务 / 记忆事实）仍按 40 字符截断。"""
        assert len(summarize_tool_call("task_delegate", {"task": "y" * 200})) == 40
        assert summarize_tool_call("fact_add", {"fact": "z" * 200}).endswith("…")

    def test_newlines_are_collapsed(self) -> None:
        summary = summarize_tool_call("shell", {"command": "line1\nline2\n  line3"})

        assert summary == "line1 line2 line3"


class TestNeverRaises:
    """展示层契约：任何异常形状都退化为「无摘要」，绝不向上抛。"""

    def test_broken_mapping_returns_empty(self) -> None:
        assert summarize_tool_call("file_read", _BrokenArguments()) == ""

    def test_none_arguments_returns_empty(self) -> None:
        assert summarize_tool_call("file_read", None) == ""

    def test_non_string_arguments_return_empty(self) -> None:
        assert summarize_tool_call("file_read", {"path": {"nested": "dict"}}) == ""


class TestActivityLabel:
    """P2：``<tool> → <target>`` 拼接的唯一来源（CLI / GUI / 台账共用，不得各拼一套）。"""

    def test_pairs_tool_and_target(self) -> None:
        assert activity_label("file_read", "docs/frame.md") == "file_read → docs/frame.md"

    def test_keeps_the_tool_name_when_there_is_no_target(self) -> None:
        assert activity_label("task_status", "") == "task_status"

    def test_degrades_when_the_tool_name_is_missing(self) -> None:
        assert activity_label("", "0 9 * * *") == "0 9 * * *"
        assert activity_label("", "") == ""

    def test_label_length_is_bounded_for_clipped_targets(self) -> None:
        """作用对象经 summarize 后≤72 字符，故标签长度有界（shell 例外：全文，见 TestTruncation）。"""
        target = summarize_tool_call("file_read", {"path": "p" * 200})

        assert len(activity_label("file_read", target)) == len("file_read → ") + 72


class TestTableIntegrity:
    """P4：映射表不得含不可达条目——特殊分支抢先命中即「改表不生效」的死配置。"""

    # _describe 里单独处理（格式特殊）的工具，它们不得回到 _TARGET_FIELDS
    SPECIALIZED = frozenset(
        {
            "file_search",
            "content_search",
            "file_write",
            "git_diff",
            "cron_add",
            "task_delegate",
            "task_parallel",
        }
    )

    def test_specially_handled_tools_are_not_in_the_table(self) -> None:
        assert not (set(_TARGET_FIELDS) & self.SPECIALIZED)

    @pytest.mark.parametrize("tool", sorted(_TARGET_FIELDS))
    def test_every_table_entry_is_reachable(self, tool: str, monkeypatch: pytest.MonkeyPatch) -> None:
        """把表项换成哨兵字段名并传该字段：摘要必须体现哨兵值，否则该表项被特殊分支遮蔽。"""
        sentinel = "__sentinel_field__"
        monkeypatch.setitem(_TARGET_FIELDS, tool, sentinel)

        summary = summarize_tool_call(tool, {sentinel: "SENTINEL-VALUE"})

        assert "SENTINEL-VALUE" in summary, f"{tool} 的表项不可达（被特殊分支抢先命中）"


def test_target_fields_reference_real_tools() -> None:
    """映射表里每个工具名都必须是真实注册的工具（防改名后静默失配）。"""
    from heagent.tools import builtins as _builtins  # noqa: F401  (导入即注册内置工具)
    from heagent.tools.call_summary import _TARGET_FIELDS
    from heagent.tools.registry import ToolRegistry

    registered = {schema.name for schema in ToolRegistry.get().enabled_schemas()}

    assert set(_TARGET_FIELDS) <= registered, f"unknown tools in map: {sorted(set(_TARGET_FIELDS) - registered)}"
