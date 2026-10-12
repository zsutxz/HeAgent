"""Tests for slash command system (Epic 31)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from heagent.cli.interactive import _handle_slash, _render_command_prompt
from heagent.cli.slash import SlashRegistry, load_custom_commands


class TestSlashRegistry:
    @pytest.mark.asyncio
    async def test_dispatch_hits_and_misses(self) -> None:
        registry = SlashRegistry()
        calls: list[str] = []

        async def handler(args: str) -> None:
            calls.append(args)

        registry.register("foo", "a command", handler)
        assert registry.has("foo")
        assert registry.has("FOO")  # 大小写不敏感
        assert not registry.has("bar")
        assert (await registry.dispatch("foo", "hello world")) is True
        assert calls == ["hello world"]
        assert (await registry.dispatch("bar", "")) is False

    def test_names_sorted_and_describe(self) -> None:
        registry = SlashRegistry()

        async def handler(args: str) -> None:
            return None

        registry.register("b", "bee", handler)
        registry.register("a", "aye", handler)
        assert registry.names() == ["a", "b"]
        assert registry.describe("a") == "aye"
        assert registry.describe("missing") == ""


class TestLoadCustomCommands:
    def test_loads_frontmatter(self, tmp_path) -> None:
        (tmp_path / "review.md").write_text(
            "---\nname: review\ndescription: Review code\n---\n请审查代码变更", encoding="utf-8"
        )
        cmds = load_custom_commands([str(tmp_path)])
        assert len(cmds) == 1
        assert cmds[0].name == "review"
        assert cmds[0].description == "Review code"
        assert cmds[0].prompt == "请审查代码变更"

    def test_falls_back_to_filename_when_no_name(self, tmp_path) -> None:
        (tmp_path / "foo.md").write_text("正文内容", encoding="utf-8")
        cmds = load_custom_commands([str(tmp_path)])
        assert len(cmds) == 1
        assert cmds[0].name == "foo"

    def test_skips_empty_prompt(self, tmp_path) -> None:
        (tmp_path / "empty.md").write_text("---\nname: empty\n---\n   \n", encoding="utf-8")
        cmds = load_custom_commands([str(tmp_path)])
        assert cmds == []

    def test_later_dir_overrides_earlier(self, tmp_path) -> None:
        d1 = tmp_path / "global"
        d2 = tmp_path / "project"
        d1.mkdir()
        d2.mkdir()
        (d1 / "x.md").write_text("---\nname: x\n---\nglobal prompt", encoding="utf-8")
        (d2 / "x.md").write_text("---\nname: x\n---\nproject prompt", encoding="utf-8")
        cmds = load_custom_commands([str(d1), str(d2)])
        assert len(cmds) == 1
        assert cmds[0].prompt == "project prompt"

    def test_nonexistent_dir_yields_empty(self, tmp_path) -> None:
        assert load_custom_commands([str(tmp_path / "nope")]) == []


class TestRenderCommandPrompt:
    def test_placeholder_replaced_with_args(self) -> None:
        assert _render_command_prompt("处理参数：$ARGUMENTS", "next step") == "处理参数：next step"

    def test_args_appended_when_no_placeholder(self) -> None:
        assert _render_command_prompt("固定正文", "hello") == "固定正文\n\nhello"

    def test_no_args_keeps_prompt_verbatim(self) -> None:
        # 无占位符 + 空白参数：正文逐字不变（存量命令零行为变化）
        assert _render_command_prompt("   ", "  ") == "   "

    def test_placeholder_always_replaces_even_blank(self) -> None:
        # 声明了占位符就按占位符语义走：空白参数原样替换，不做静默回退
        assert _render_command_prompt("带 $ARGUMENTS 占位", "") == "带  占位"
        assert _render_command_prompt("参数：[$ARGUMENTS]", "  ") == "参数：[  ]"


class TestHandleSlash:
    @pytest.mark.asyncio
    async def test_dispatches_to_registry(self) -> None:
        registry = SlashRegistry()
        got: list[str] = []

        async def handler(args: str) -> None:
            got.append(args)

        registry.register("test", "", handler)
        assert (await _handle_slash("/test a b", registry)) is True
        assert got == ["a b"]

    @pytest.mark.asyncio
    async def test_unknown_returns_false(self) -> None:
        registry = SlashRegistry()
        assert (await _handle_slash("/nope", registry)) is False

    @pytest.mark.asyncio
    async def test_non_slash_returns_false(self) -> None:
        registry = SlashRegistry()
        assert (await _handle_slash("hello", registry)) is False


class TestGoalCommandRouting:
    """``/goal`` 走内置（Python 状态机），``/work`` 走自定义命令（新技能包）。

    ``/goal`` 必须由内置注册且不被文件命令顶掉：若内置注册没叫 ``goal``，
    ``/goal`` 未注册会被当普通消息透传给 AgentLoop —— 不报错、只静默失效。
    """

    def _registry(self) -> SlashRegistry:
        from heagent.cli.interactive import _build_slash_registry

        return _build_slash_registry(
            provider=None,  # type: ignore[arg-type] - 仅构造注册表，handler 不被调用
            mcp_manager=None,
            session=None,
            session_id="test",
            loop=None,  # type: ignore[arg-type]
            system=None,
        )

    def test_goal_is_builtin_and_goal_old_is_gone(self) -> None:
        registry = self._registry()
        assert registry.has("goal")
        assert "new/next/run/status" in registry.describe("goal")
        assert not registry.has("goal_old")

    def test_custom_command_overrides_builtin_on_name_collision(self, tmp_path, monkeypatch) -> None:
        monkeypatch.chdir(tmp_path)
        commands_dir = tmp_path / ".heagent" / "commands"
        commands_dir.mkdir(parents=True)
        (commands_dir / "goal.md").write_text(
            "---\nname: goal\ndescription: new workflow\n---\n执行 goal 技能包：$ARGUMENTS\n",
            encoding="utf-8",
        )
        registry = self._registry()
        # 自定义命令后注册、覆盖内置同名项：/goal 必须描述新工作流，而非内置状态机。
        assert registry.describe("goal") == "new workflow"

    def test_shipped_work_command_points_at_the_work_skill_package(self) -> None:
        """随仓库发布的命令必须指向实际存在的技能包目录（改名后易漂移的目录名引用）。"""
        root = Path(__file__).resolve().parents[1]
        command = (root / ".heagent" / "commands" / "work.md").read_text(encoding="utf-8")
        match = re.search(r"`(\.heagent/skills/[^`]+)/SKILL\.md`", command)
        assert match, f"work.md 必须引用技能包 SKILL.md 路径：{command!r}"
        assert (root / match.group(1) / "SKILL.md").is_file(), f"引用的技能包不存在：{match.group(1)}"
