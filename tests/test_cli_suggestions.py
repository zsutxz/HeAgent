"""错误 → 命令建议的契约：场景覆盖、命令真实性（代码反射）、兜底与文档一致性（Story 64.13）。

钉四件事：

1. 每个场景 **≥2 条**建议（票面 R11），且与场景相关（专属锚点命令出现在该场景里）；
2. 每条命令**真实存在**：`heagent <sub>` 命中 `console.main.commands`、`/<name>` 命中
   `interactive._build_slash_registry()` 的注册表、`--flag` 是该 click 命令真有的参数——用反射而不
   硬编码清单，命令表变了测试自动跟上；
3. 关键词匹配有边界（`port` 不命中 `support` / `export`），未命中走兜底且兜底也 ≥2 条；
4. `docs/errors.md` 真的写了这一节，每个场景 label 都能在文档里找到，既有锚点没漂。
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from heagent.cli import errors as cli_errors
from heagent.cli.suggestions import (
    FALLBACK_SCENARIO,
    FALLBACK_SUGGESTIONS,
    MIN_SUGGESTIONS,
    SCENARIOS,
    detect_scenario,
    scenario_labels,
    suggest_commands,
)

if TYPE_CHECKING:
    import click

_DOC_PATH = Path(__file__).resolve().parents[1] / "docs/errors.md"

#: 每个场景一条真实错误文本（取自 `docs/errors.md` 第三节与 `http.py` / `wiring.py` 的既有文案）。
_SAMPLES: dict[str, str] = {
    "credentials": "Error: No API key configured. Set DEEPSEEK_API_KEY, ANTHROPIC_API_KEY",
    "ws_token": "WS server configuration is invalid: auth-enforcing WS listeners require WS_AUTH_TOKEN",
    "port": "HTTP server could not bind 127.0.0.1:9101: address unavailable",
    "sandbox": "sandbox backend firejail unavailable; falling back to host execution",
    "mcp": "[mcp config error] bad json in .mcp.json",
    "skill": "workflow role 'reviewer' is unavailable",
    "cron": "cron job store could not be loaded",
    "session": "invalid --resume session id: must not contain path separators",
    "provider": "unknown provider 'foo' is not configured",
    # 真实出口报文（cli/wiring.py::load_startup_settings 在 Settings 构造失败时打印的那条）。
    "config_invalid": "Error: configuration could not be loaded: ValidationError: 1 validation error for Settings",
}

#: 每个场景必须出现的一条专属命令片段（「建议与错误场景相关」的可判定口径）。
_SCENARIO_ANCHORS: dict[str, str] = {
    "credentials": "heagent init --interactive",
    "ws_token": "heagent init",
    "port": "heagent http-server --port",
    "sandbox": "--sandbox passthrough",
    "mcp": "/mcp-prompt",
    "skill": "/goal doctor",
    "cron": "/goal auto",
    "session": "/clear",
    "provider": "/provider",
    "config_invalid": "heagent doctor",
}


def _slug(title: str) -> str:
    """GitHub 口径的标题 slug（与 `tests/test_cli_error_format.py` 同口径）。"""
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


def _all_suggestions() -> list[tuple[str, str]]:
    """返回 ``(场景 key, 命令)`` 全量清单（含兜底），供反射校验遍历。"""
    pairs = [(scenario.key, item.command) for scenario in SCENARIOS for item in scenario.suggestions]
    pairs.extend((FALLBACK_SCENARIO, item.command) for item in FALLBACK_SUGGESTIONS)
    return pairs


def _cli_subcommand(command: str) -> tuple[str, click.Command]:
    parts = shlex.split(command)
    assert parts[0] == "heagent", command
    assert len(parts) > 1, f"{command!r} 没有子命令，裸 heagent 是交互模式不是可建议的命令"
    from heagent.cli.console import main

    assert parts[1] in main.commands, f"{command!r} 的子命令 {parts[1]!r} 不在 CLI 命令表里"
    return parts[1], main.commands[parts[1]]


def _slash_registry_command(command: str) -> tuple[str, object]:
    parts = shlex.split(command)
    assert parts[0].startswith("/"), command
    name = parts[0].lstrip("/")
    from heagent.cli.interactive import _build_slash_registry

    # 注册表的构造只把 provider / loop 等用在 handler 闭包里，构造期不解引用 ⇒ 传 None 即可反射。
    registry = _build_slash_registry(None, None, None, "probe-session", None, None)  # type: ignore[arg-type]
    info = registry.info(name)
    assert info is not None, f"{command!r} 的斜杠命令 {name!r} 未注册"
    return name, info


class TestScenarioTable:
    def test_every_scenario_has_at_least_two_commands(self) -> None:
        for scenario in SCENARIOS:
            assert len(scenario.suggestions) >= MIN_SUGGESTIONS, scenario.key
            for item in scenario.suggestions:
                assert item.command.strip() and item.when.strip(), scenario.key

    def test_fallback_has_at_least_two_commands(self) -> None:
        assert len(FALLBACK_SUGGESTIONS) >= MIN_SUGGESTIONS

    def test_scenario_keys_are_unique(self) -> None:
        keys = [scenario.key for scenario in SCENARIOS]
        assert len(keys) == len(set(keys))

    def test_at_least_eight_scenarios_are_covered(self) -> None:
        """票面口径是「≥8 类场景」；只留几类会让多数错误都落到兜底。"""
        assert len(SCENARIOS) >= 8

    def test_samples_cover_exactly_the_declared_scenarios(self) -> None:
        """新增场景却不给样例文本 ⇒ 匹配逻辑没被真正校验过。"""
        assert set(_SAMPLES) == {scenario.key for scenario in SCENARIOS}
        assert set(_SCENARIO_ANCHORS) == {scenario.key for scenario in SCENARIOS}


class TestKeywordMatching:
    @pytest.mark.parametrize("scenario_key", sorted(_SAMPLES))
    def test_sample_message_detects_its_scenario(self, scenario_key: str) -> None:
        assert detect_scenario(_SAMPLES[scenario_key]) == scenario_key

    @pytest.mark.parametrize("scenario_key", sorted(_SAMPLES))
    def test_detected_suggestions_match_the_scenario(self, scenario_key: str) -> None:
        commands = [item.command for item in suggest_commands(_SAMPLES[scenario_key])]
        assert commands == [item.command for item in suggest_commands(scenario=scenario_key)]

    @pytest.mark.parametrize("scenario_key", sorted(_SCENARIO_ANCHORS))
    def test_scenario_suggestions_are_relevant(self, scenario_key: str) -> None:
        commands = [item.command for item in suggest_commands(scenario=scenario_key)]
        anchor = _SCENARIO_ANCHORS[scenario_key]
        assert any(anchor in command for command in commands), commands

    @pytest.mark.parametrize(
        "message",
        ["Error: unsupported file type", "Error: export failed", "Error: reports missing"],
    )
    def test_keyword_boundaries_prevent_false_hits(self, message: str) -> None:
        """`port` 不得命中 `support` / `export` / `reports`。"""
        assert detect_scenario(message) == FALLBACK_SCENARIO

    def test_unknown_message_falls_back(self) -> None:
        assert detect_scenario("Error: something entirely unexpected happened") == FALLBACK_SCENARIO
        assert suggest_commands("Error: something entirely unexpected happened") == FALLBACK_SUGGESTIONS

    def test_fallback_is_doctor_plus_help(self) -> None:
        assert [item.command for item in FALLBACK_SUGGESTIONS] == ["heagent doctor", "/help"]

    def test_unknown_scenario_key_fails_loud(self) -> None:
        with pytest.raises(KeyError, match="unknown error scenario"):
            suggest_commands(scenario="does-not-exist")

    def test_explicit_scenario_wins_over_message(self) -> None:
        assert suggest_commands("totally unrelated text", scenario="port") == suggest_commands(scenario="port")


class TestCommandsExist:
    """代码反射：命令表即真源，本测试不维护第二份清单。"""

    def test_every_cli_command_exists(self) -> None:
        offenders: list[str] = []
        for key, command in _all_suggestions():
            if not command.startswith("heagent "):
                continue
            try:
                _cli_subcommand(command)
            except AssertionError as exc:  # pragma: no cover - 失败时把场景带进报告
                offenders.append(f"{key}: {exc}")
        assert offenders == []

    def test_every_cli_flag_exists_on_that_command(self) -> None:
        offenders: list[str] = []
        for _key, command in _all_suggestions():
            if not command.startswith("heagent "):
                continue
            _sub, cmd = _cli_subcommand(command)
            available = {opt for param in cmd.params for opt in getattr(param, "opts", [])}
            for token in shlex.split(command)[1:]:
                if token.startswith("--") and token not in available:
                    offenders.append(f"{command!r}: {token} 不在 {cmd.name} 的参数表里")
        assert offenders == []

    def test_every_slash_command_is_registered(self) -> None:
        offenders: list[str] = []
        for key, command in _all_suggestions():
            if not command.startswith("/"):
                continue
            try:
                _slash_registry_command(command)
            except AssertionError as exc:  # pragma: no cover - 失败时把场景带进报告
                offenders.append(f"{key}: {exc}")
        assert offenders == []

    def test_slash_command_arguments_are_documented(self) -> None:
        """`/goal doctor` 这类带子参数的命令：子参数必须在该命令的帮助元数据里（不是编的）。"""
        offenders: list[str] = []
        for _key, command in _all_suggestions():
            if not command.startswith("/"):
                continue
            _name, info = _slash_registry_command(command)
            help_text = " ".join(
                [
                    getattr(info, "usage", ""),
                    getattr(info, "arguments", ""),
                    getattr(info, "description", ""),
                ]
            )
            for token in shlex.split(command)[1:]:
                if not token.startswith("-") and token not in help_text:
                    offenders.append(f"{command!r}: 子参数 {token!r} 未在帮助元数据里出现")
        assert offenders == []


class TestDocsConsistency:
    def test_cli_anchor_still_resolves(self) -> None:
        assert cli_errors.ANCHOR_CLI_ERRORS in _doc_slugs()

    def test_suggestions_section_exists(self) -> None:
        assert "建议命令" in _doc_slugs()

    def test_header_wording_is_documented(self) -> None:
        header = cli_errors.SUGGESTIONS_HEADER.strip()
        assert header == "Try these commands:"
        assert header in _DOC_PATH.read_text(encoding="utf-8")

    def test_every_scenario_label_is_documented(self) -> None:
        text = _DOC_PATH.read_text(encoding="utf-8")
        missing = sorted(label for label in scenario_labels().values() if label not in text)
        assert missing == []


class TestRenderViaErrors:
    """建议段在 `errors.py` 的渲染位置：恒在 `Docs:` 之后，且不改首行。"""

    def test_with_command_hints_orders_sections(self) -> None:
        text = cli_errors.with_command_hints(
            _SAMPLES["port"],
            options=("换端口",),
            anchor=cli_errors.ANCHOR_CLI_ERRORS,
        )
        lines = text.splitlines()
        assert lines[0] == _SAMPLES["port"]
        assert lines[1] == "  Try:"
        assert lines[2] == "    - 换端口"
        assert lines[3] == f"  Docs: {cli_errors.ERRORS_DOC}#{cli_errors.ANCHOR_CLI_ERRORS}"
        assert lines[4] == cli_errors.SUGGESTIONS_HEADER
        assert lines[5].startswith("    - heagent http-server --port")

    def test_rendered_commands_carry_a_comment(self) -> None:
        text = cli_errors.with_command_hints(_SAMPLES["credentials"], options=("配凭据",))
        body = text.split(cli_errors.SUGGESTIONS_HEADER, 1)[1]
        entries = [line for line in body.splitlines() if line.strip().startswith("- ")]
        assert len(entries) >= MIN_SUGGESTIONS
        assert all("  # " in line for line in entries)
