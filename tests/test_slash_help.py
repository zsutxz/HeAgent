"""``/help`` 与 ``/help <command>`` 的渲染口径（Story 64.12）。

钉住三件事：
1. **四段齐全**——每个内置命令的详情都有「/名字  描述」首行 + 语法 / 参数 / 示例三段；
2. **格式统一**——列表版与详情版取自同一注册表数据源，未知命令给建议而非静默；
3. **降级显式**——缺元数据的自定义命令打印「自定义命令，无参数说明」，不渲染空块。

测试一律 monkeypatch 掉 ``load_custom_commands`` 或 chdir 到 ``tmp_path``：仓库与用户级
``.heagent/commands/`` 的内容不得影响断言。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from heagent.cli import interactive
from heagent.cli.interactive import _handle_slash, _render_command_help, _render_help_list
from heagent.cli.slash import SlashRegistry, load_custom_commands

# 内置命令全集（命令面冻结：新增斜杠命令须同步本表与 /help 元数据）。
BUILTIN_COMMANDS = ("provider", "model", "mcp-prompt", "deferred", "clear", "compact", "help", "goal")

_SECTIONS = ("语法:", "参数:", "示例:")


def _no_custom_commands() -> list[object]:
    """内置命令断言用：屏蔽 ``.heagent/commands`` 加载（仓库与用户级目录都不得影响断言）。"""
    return []


def _build_registry(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> SlashRegistry:
    """构造内置命令注册表：chdir 到 tmp_path 且屏蔽自定义命令（断言与仓库内容解耦）。"""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(interactive, "load_custom_commands", _no_custom_commands)
    return interactive._build_slash_registry(
        provider=None,  # type: ignore[arg-type] - 仅构造注册表，handler 不被调用
        mcp_manager=None,
        session=None,
        session_id="test",
        loop=None,  # type: ignore[arg-type]
        system=None,
    )


async def _help_output(registry: SlashRegistry, args: str) -> None:
    """跑一条 ``/help <args>``（断言确实被注册表命中，未被透传给 AgentLoop）。"""
    assert (await _handle_slash(f"/help {args}".strip(), registry)) is True


def _sections(output: str) -> dict[str, list[str]]:
    """把详情输出切成 ``{标签: 内容行}``（标签行本身不计入内容）。"""
    result: dict[str, list[str]] = {}
    current = ""
    for line in output.splitlines():
        if line in _SECTIONS:
            current = line
            result[current] = []
            continue
        if current:
            result[current].append(line)
    return result


class TestDetailSections:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("name", BUILTIN_COMMANDS)
    async def test_every_builtin_has_description_usage_arguments_examples(
        self, name: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        registry = _build_registry(monkeypatch, tmp_path)
        await _help_output(registry, name)
        output = capsys.readouterr().err
        lines = output.splitlines()
        # 第一段：``/名字  描述``，描述与列表版逐字一致（同一数据源）。
        assert lines[0] == f"/{name}  {registry.describe(name)}"
        # 第二至四段：语法 / 参数 / 示例，顺序固定且内容非空。
        sections = _sections(output)
        assert list(sections) == list(_SECTIONS)
        for label in _SECTIONS:
            content = [line for line in sections[label] if line.strip()]
            assert content, f"/help {name} 的 {label} 段为空"

    @pytest.mark.asyncio
    async def test_usage_shows_command_name_and_arguments_are_indented(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        registry = _build_registry(monkeypatch, tmp_path)
        await _help_output(registry, "compact")
        output = capsys.readouterr().err
        assert "/compact" in _sections(output)["语法:"][0]
        assert _sections(output)["参数:"][0].startswith("  ")

    @pytest.mark.asyncio
    async def test_goal_detail_lists_subcommands_and_examples(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        registry = _build_registry(monkeypatch, tmp_path)
        await _help_output(registry, "goal")
        sections = _sections(capsys.readouterr().err)
        arguments = " ".join(sections["参数:"])
        for sub in ("new", "next", "status", "doctor", "verify", "approve", "reject", "amend", "reset", "auto"):
            assert sub in arguments
        assert any(example.strip() == "/goal status" for example in sections["示例:"])

    @pytest.mark.asyncio
    async def test_help_detail_documents_itself(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        registry = _build_registry(monkeypatch, tmp_path)
        await _help_output(registry, "help")
        sections = _sections(capsys.readouterr().err)
        assert any(line.strip() == "/help <command>" for line in sections["语法:"])
        assert any("/help goal" in example for example in sections["示例:"])


class TestHelpList:
    @pytest.mark.asyncio
    async def test_lists_every_command_sorted_with_description(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        registry = _build_registry(monkeypatch, tmp_path)
        assert (await _handle_slash("/help", registry)) is True
        output = capsys.readouterr().err
        lines = output.splitlines()
        assert lines[0] == "Available slash commands:"
        listed = [line.split()[0].lstrip("/") for line in lines[1:] if line.startswith("  /")]
        assert listed == sorted(registry.names())
        assert set(BUILTIN_COMMANDS) <= set(listed)
        for name in BUILTIN_COMMANDS:
            assert registry.describe(name) in output

    @pytest.mark.asyncio
    async def test_list_hints_at_detail_form(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        registry = _build_registry(monkeypatch, tmp_path)
        assert (await _handle_slash("/help", registry)) is True
        assert "/help <command>" in capsys.readouterr().err

    def test_render_help_list_aligns_names(self, capsys: pytest.CaptureFixture[str]) -> None:
        registry = SlashRegistry()

        async def handler(args: str) -> None:
            return None

        registry.register("a", "短名", handler)
        registry.register("long-name", "长名", handler)
        _render_help_list(registry)
        lines = capsys.readouterr().err.splitlines()
        assert lines[0] == "Available slash commands:"
        # 描述列起点一致：名字列按最长名补空格（对齐是「格式统一」的一部分）。
        assert lines[1].index("短名") == lines[2].index("长名")
        assert lines[1].startswith("  /a ") and lines[2].startswith("  /long-name  ")


class TestUnknownCommand:
    @pytest.mark.asyncio
    async def test_typo_gets_error_suggestion_and_hint(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        registry = _build_registry(monkeypatch, tmp_path)
        await _help_output(registry, "providr")
        output = capsys.readouterr().err
        assert "[help] Unknown slash command: /providr" in output
        assert "[help] Did you mean: /provider" in output
        assert "[help] Run /help to list all commands." in output

    @pytest.mark.asyncio
    async def test_far_off_name_still_yields_at_least_one_suggestion(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        registry = _build_registry(monkeypatch, tmp_path)
        await _help_output(registry, "zzzzzz")
        output = capsys.readouterr().err
        assert "Did you mean:" in output
        suggestions = output.split("Did you mean:", 1)[1].strip()
        assert suggestions.startswith("/")


class TestCustomCommandDegrade:
    def _registry_with_custom(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, files: dict[str, str]
    ) -> SlashRegistry:
        commands_dir = tmp_path / ".heagent" / "commands"
        commands_dir.mkdir(parents=True)
        for filename, body in files.items():
            (commands_dir / filename).write_text(body, encoding="utf-8")
        monkeypatch.chdir(tmp_path)
        # 只加载本次夹具目录：用户级 ~/.heagent/commands 不得影响断言。
        monkeypatch.setattr(interactive, "load_custom_commands", lambda: load_custom_commands([str(commands_dir)]))
        return interactive._build_slash_registry(
            provider=None,  # type: ignore[arg-type]
            mcp_manager=None,
            session=None,
            session_id="test",
            loop=None,  # type: ignore[arg-type]
            system=None,
        )

    @pytest.mark.asyncio
    async def test_missing_metadata_prints_explicit_note(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        registry = self._registry_with_custom(
            monkeypatch, tmp_path, {"review.md": "---\nname: review\ndescription: Review code\n---\n请审查"}
        )
        await _help_output(registry, "review")
        output = capsys.readouterr().err
        assert output.splitlines()[0] == "/review  Review code"
        sections = _sections(output)
        assert list(sections) == list(_SECTIONS)
        assert any("自定义命令，无参数说明" in line for line in sections["参数:"])
        assert ".heagent/commands/review.md" in " ".join(sections["参数:"])
        assert any(line.strip() == "/review" for line in sections["示例:"])

    @pytest.mark.asyncio
    async def test_custom_command_appears_in_list(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        registry = self._registry_with_custom(
            monkeypatch, tmp_path, {"review.md": "---\nname: review\ndescription: Review code\n---\n请审查"}
        )
        assert (await _handle_slash("/help", registry)) is True
        output = capsys.readouterr().err
        assert "/review" in output
        assert "Review code" in output

    @pytest.mark.asyncio
    async def test_command_without_examples_falls_back_to_bare_invocation(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        registry = self._registry_with_custom(monkeypatch, tmp_path, {"bare.md": "只有正文"})
        await _help_output(registry, "bare")
        sections = _sections(capsys.readouterr().err)
        assert any(line.strip() == "/bare" for line in sections["示例:"])


class TestGenericFallback:
    """走 3 参 ``register`` 的命令（无元数据、非自定义）也要渲染出完整四段。"""

    def test_plain_registration_renders_generic_sections(self, capsys: pytest.CaptureFixture[str]) -> None:
        registry = SlashRegistry()

        async def handler(args: str) -> None:
            return None

        registry.register("plain", "无元数据命令", handler)
        _render_command_help(registry, "plain")
        output = capsys.readouterr().err
        assert output.splitlines()[0] == "/plain  无元数据命令"
        sections = _sections(output)
        assert sections["语法:"] == ["  /plain"]
        assert sections["参数:"] == ["  未提供参数说明。"]
        assert sections["示例:"] == ["  /plain"]


class TestHelpArgumentParsing:
    @pytest.mark.asyncio
    async def test_leading_slash_and_extra_args_are_tolerated(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        registry = _build_registry(monkeypatch, tmp_path)
        assert (await _handle_slash("/help /goal", registry)) is True
        first = capsys.readouterr().err.splitlines()[0]
        assert first.startswith("/goal  ")
        assert (await _handle_slash("/help goal extra", registry)) is True
        assert capsys.readouterr().err.splitlines()[0] == first

    @pytest.mark.asyncio
    async def test_bare_slash_after_help_lists_commands(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        registry = _build_registry(monkeypatch, tmp_path)
        assert (await _handle_slash("/help /", registry)) is True
        assert capsys.readouterr().err.startswith("Available slash commands:")
