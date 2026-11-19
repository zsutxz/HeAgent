"""CLI 错误格式契约：描述 + 可用选项 + 文档链接（Story 64.5）。

钉三件事：

1. `with_hints` 的**形状**固定（首行原文 / `Try:` 列表 / `Docs:` 行），新增失败分支只要走它就不会漂移；
2. 每个接入点都真的带上了选项与文档链接（不是只有 helper 正确而调用点漏用）；
3. 代码里用的锚点在 `docs/errors.md` 里**真实存在**（防止文档改标题后留下死锚）。
"""

from __future__ import annotations

import re
from pathlib import Path

import click
import pytest
from click.testing import CliRunner

from heagent.cli.errors import (
    ANCHOR_CLI_ERRORS,
    ERRORS_DOC,
    SUGGESTIONS_HEADER,
    exit_with_command_hints,
    exit_with_hints,
    report_with_command_hints,
    with_command_hints,
    with_hints,
)
from heagent.cli.suggestions import CommandSuggestion, suggest_commands
from heagent.cli.http import embedded_http_error_message
from heagent.cli.wiring import _report_provider_config_error
from heagent.network.http_server import HttpStartupError
from heagent.network.optional_deps import HttpDependencyError
from heagent.network.ws_host import WsConfigError, WsStartupError

_DOC_PATH = Path(__file__).resolve().parents[1] / ERRORS_DOC


def _slug(title: str) -> str:
    """GitHub 口径的标题 slug：小写、去中文标点与代码符号、空格转连字符。"""
    text = title.strip().lower()
    text = re.sub(r"[、。，：；！？（）()\[\]`\"'#*]", "", text)
    return text.replace(" ", "-")


def _doc_slugs() -> set[str]:
    slugs: set[str] = set()
    for line in _DOC_PATH.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^#{2,3} (.+)$", line)
        if match:
            slugs.add(_slug(match.group(1)))
    return slugs


class TestShape:
    def test_three_parts_in_order(self) -> None:
        text = with_hints("boom", options=("do a", "do b"), anchor="some-anchor")
        lines = text.splitlines()
        assert lines[0] == "boom"
        assert lines[1] == "  Try:"
        assert lines[2] == "    - do a"
        assert lines[3] == "    - do b"
        assert lines[4] == f"  Docs: {ERRORS_DOC}#some-anchor"

    def test_rejects_empty_options(self) -> None:
        with pytest.raises(ValueError, match="at least one option"):
            with_hints("boom", options=(), anchor="a")

    def test_empty_anchor_links_to_document(self) -> None:
        text = with_hints("boom", options=("do a",), anchor="")
        assert text.splitlines()[-1] == f"  Docs: {ERRORS_DOC}"

    def test_message_is_preserved_verbatim(self) -> None:
        original = "[mcp config error] bad json"
        assert with_hints(original, options=("x",), anchor="a").splitlines()[0] == original

    def test_exit_with_hints_uses_click_error_prefix(self) -> None:
        runner = CliRunner()

        @click.command()
        def cmd() -> None:
            exit_with_hints("boom", options=("do a",), anchor="a")

        result = runner.invoke(cmd)
        # click 8.2+ 把 stderr 从 output 拆出去了；两个来源合起来断言，跨版本都成立。
        stderr = getattr(result, "stderr", "") or ""
        combined = result.output + stderr
        assert result.exit_code == 1
        assert "Error: boom" in combined
        assert "Try:" in combined
        assert f"Docs: {ERRORS_DOC}#a" in combined


class TestProviderConfigErrors:
    @pytest.mark.parametrize(
        ("message", "expected_option"),
        [
            ("Error: No API key configured. Set DEEPSEEK_API_KEY, ...", "DEEPSEEK_API_KEY"),
            (
                "Error: OLLAMA_ENABLED=true requires OLLAMA_MODEL (e.g. OLLAMA_MODEL=qwen3:8b; ...)",
                "OLLAMA_MODEL=qwen3:8b",
            ),
            ("Error: something else went wrong", "check the provider entry this message names"),
        ],
    )
    def test_reports_options_and_docs(
        self, message: str, expected_option: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _report_provider_config_error(message)
        err = capsys.readouterr().err
        assert message in err
        assert "Try:" in err
        assert expected_option in err
        assert f"Docs: {ERRORS_DOC}#{ANCHOR_CLI_ERRORS}" in err

    @pytest.mark.parametrize(
        ("message", "must_not_appear"),
        [
            # 命中前缀表时不应落到兜底文案；期望值刻意与消息本身无关，否则断言会被消息文本满足。
            ("Error: No API key configured. Set DEEPSEEK_API_KEY, ...", "check the provider entry"),
            (
                "Error: OLLAMA_ENABLED=true requires OLLAMA_MODEL (e.g. OLLAMA_MODEL=qwen3:8b; ...)",
                "check the provider entry",
            ),
        ],
    )
    def test_known_messages_do_not_fall_back(
        self, message: str, must_not_appear: str, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _report_provider_config_error(message)
        assert must_not_appear not in capsys.readouterr().err


class TestStartupErrors:
    @pytest.mark.parametrize(
        ("exc", "first_line", "expected_option"),
        [
            (HttpStartupError("could not bind 127.0.0.1:9101"), "HTTP server failed to start", "--port <n>"),
            (
                WsConfigError("auth-enforcing listeners require WS_AUTH_TOKEN"),
                "WS server configuration is invalid",
                "WS_LAN_NO_AUTH=true",
            ),
            (WsStartupError("could not bind"), "WS server failed to start", "--ws-port <n>"),
            (HttpDependencyError("missing 'aiohttp'"), "missing 'aiohttp'", "pip install"),
        ],
    )
    def test_embedded_message_carries_hints(self, exc: Exception, first_line: str, expected_option: str) -> None:
        message = embedded_http_error_message(exc)
        assert message is not None
        assert first_line in message.splitlines()[0]
        assert "Try:" in message
        assert expected_option in message
        assert f"Docs: {ERRORS_DOC}#{ANCHOR_CLI_ERRORS}" in message

    def test_unknown_exception_returns_none(self) -> None:
        assert embedded_http_error_message(RuntimeError("boom")) is None


class TestAnchorsExist:
    def test_cli_anchor_exists_in_doc(self) -> None:
        assert ANCHOR_CLI_ERRORS in _doc_slugs()

    def test_cli_sources_only_pass_the_known_anchor(self) -> None:
        """CLI 源码里 anchor= 的实参必须是 ``ANCHOR_CLI_ERRORS``（或省略），不写字面量。

        这样「锚点是否存在」只需校验一处（`test_cli_anchor_exists_in_doc`），不会因为某处手写
        字符串而留下未被覆盖的死锚。
        """
        cli_dir = Path(__file__).resolve().parents[1] / "src" / "heagent" / "cli"
        allowed = {"ANCHOR_CLI_ERRORS", "anchor"}  # 常量；`anchor` = errors.py 内部原样转发
        offenders: list[str] = []
        for path in cli_dir.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            for arg in re.findall(r"anchor=([A-Za-z_][\w.]*|\"[^\"]*\"|'[^']*')", source):
                if arg not in allowed:
                    offenders.append(f"{path.name}: anchor={arg}")
        assert offenders == [], f"unexpected anchor arguments: {offenders}"


class TestEntryPoints:
    """接入点的端到端形态：不是只有 helper 对，而是命令真的输出三段。"""

    def test_invalid_resume_id(self) -> None:
        from heagent.cli import console

        result = CliRunner().invoke(console.main, ["run", "--resume", "bad/id", "hi"])
        combined = result.output + (getattr(result, "stderr", "") or "")
        assert result.exit_code != 0
        assert "invalid --resume session id" in combined
        assert "  Try:" in combined
        assert "    - " in combined
        assert f"Docs: {ERRORS_DOC}#{ANCHOR_CLI_ERRORS}" in combined

    def test_replay_on_empty_file(self, tmp_path: Path) -> None:
        from heagent.cli import console

        empty = tmp_path / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        result = CliRunner().invoke(console.main, ["replay", str(empty)])
        combined = result.output + (getattr(result, "stderr", "") or "")
        assert f"[replay] no events in {empty}" in combined
        assert "  Try:" in combined
        assert f"Docs: {ERRORS_DOC}#{ANCHOR_CLI_ERRORS}" in combined


class TestCommandSuggestions:
    """建议命令段（Story 64.13）：只在传入 ``commands`` 时出现，且不破坏既有三段块。"""

    def test_without_commands_output_is_unchanged(self) -> None:
        """``commands`` 缺省与显式 ``None`` 必须逐字等同 64.5 的三段块（向后兼容的判据）。"""
        legacy = with_hints("boom", options=("do a", "do b"), anchor="some-anchor")
        explicit_none = with_hints("boom", options=("do a", "do b"), anchor="some-anchor", commands=None)
        assert legacy == explicit_none
        assert "Try these commands:" not in legacy
        assert len(legacy.splitlines()) == 5

    def test_empty_commands_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least 2"):
            with_hints("boom", options=("do a",), anchor="a", commands=())

    def test_single_command_is_rejected(self) -> None:
        """票面要求 ≥2 条：只给一条时宁可在构造期炸，也不输出「只有一条可做」的假象。"""
        with pytest.raises(ValueError, match="at least 2"):
            with_hints(
                "boom", options=("do a",), anchor="a", commands=(CommandSuggestion(command="heagent doctor", when="x"),)
            )

    def test_suggestion_block_follows_docs_line(self) -> None:
        text = with_hints(
            "[mcp config error] bad json",
            options=("fix the JSON",),
            anchor=ANCHOR_CLI_ERRORS,
            commands=suggest_commands(scenario="mcp"),
        )
        lines = text.splitlines()
        assert lines[0] == "[mcp config error] bad json"
        assert lines[-1 - len(suggest_commands(scenario="mcp"))] == SUGGESTIONS_HEADER
        docs_index = next(i for i, line in enumerate(lines) if line.startswith("  Docs:"))
        assert lines[docs_index + 1] == SUGGESTIONS_HEADER

    def test_exit_with_command_hints_keeps_click_prefix(self) -> None:
        runner = CliRunner()

        @click.command()
        def cmd() -> None:
            exit_with_command_hints(
                "Error: No API key configured. Set DEEPSEEK_API_KEY",
                options=("configure a key",),
                anchor=ANCHOR_CLI_ERRORS,
            )

        result = runner.invoke(cmd)
        combined = result.output + (getattr(result, "stderr", "") or "")
        assert result.exit_code == 1
        assert "Error: No API key configured" in combined
        assert SUGGESTIONS_HEADER in combined
        assert "heagent init --interactive" in combined

    def test_report_with_command_hints_writes_stderr_without_exiting(self, capsys: pytest.CaptureFixture[str]) -> None:
        report_with_command_hints("[replay] no events in x", options=("point it at a rollout file",))
        err = capsys.readouterr().err
        assert err.splitlines()[0] == "[replay] no events in x"
        assert SUGGESTIONS_HEADER in err
        assert "/clear" in err

    def test_explicit_scenario_overrides_text(self) -> None:
        text = with_command_hints("totally unrelated text", options=("x",), scenario="port")
        assert "heagent http-server --port" in text
