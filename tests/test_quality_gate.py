from __future__ import annotations

import re
import shlex
from pathlib import Path
from types import SimpleNamespace

from scripts import quality_gate

CI_WORKFLOW = Path(__file__).resolve().parents[1] / ".github" / "workflows" / "ci.yml"
#: 刻意**不**进本地门的 CI 步骤：需要联网查漏洞库（CI 侧本身也是 continue-on-error）。
CI_ONLY_TOOLS = {"pip-audit"}
#: CI lint job 的静态检查工具：每一条都必须在本地门里有等价入口。
STATIC_TOOLS = {"ruff", "mypy", "bandit"}


def test_quality_gate_stops_on_first_failure(monkeypatch) -> None:
    commands = (("first", ["first"]), ("second", ["second"]))
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=7)

    monkeypatch.setattr(quality_gate, "COMMANDS", commands)
    monkeypatch.setattr(quality_gate.subprocess, "run", fake_run)

    assert quality_gate.main() == 7
    assert calls == [["first"]]


def test_quality_gate_reports_missing_executable(monkeypatch) -> None:
    monkeypatch.setattr(quality_gate, "COMMANDS", (("missing", ["missing"]),))

    def fake_run(command, **kwargs):
        raise OSError("not found")

    monkeypatch.setattr(quality_gate.subprocess, "run", fake_run)
    assert quality_gate.main() == 1


def _module_form(command: list[str]) -> list[str]:
    """``python -m tool ...`` 归一成 ``tool ...``，便于和 CI 的裸命令比对。"""
    if len(command) >= 3 and command[1] == "-m":
        return command[2:]
    return command


def _covers(ci_command: list[str], local_command: list[str]) -> bool:
    """较短一方是较长一方的前缀即视为覆盖（本地门允许比 CI 多扫目录）。"""
    shorter, longer = sorted((ci_command, local_command), key=len)
    return longer[: len(shorter)] == shorter


def _lint_job_commands() -> list[list[str]]:
    """切出 `ci.yml` 中 `lint` job 的全部 `run:` 命令行（已切词）。"""
    commands: list[list[str]] = []
    inside = False
    for line in CI_WORKFLOW.read_text(encoding="utf-8").splitlines():
        if re.fullmatch(r"  lint:\s*", line):
            inside = True
            continue
        if inside and re.match(r"  \S", line):
            break
        if not inside:
            continue
        match = re.match(r"\s+run:\s*(\S.*?)\s*$", line)
        if match:
            commands.append(shlex.split(match.group(1)))
    assert commands, f"未能从 {CI_WORKFLOW} 解析出 lint job 的 run 步骤"
    return commands


def _local_commands() -> list[list[str]]:
    return [_module_form(list(command)) for _label, command in quality_gate.COMMANDS]


def test_local_gate_contains_every_ci_static_step() -> None:
    """本地门必须覆盖 CI lint 的静态检查步骤。

    漏一条就能出现「本地全绿 / CI 全红」——lint job 是 fail-fast 源头，它会连带让
    test 矩阵、coverage、goal-smoke、benchmark 全部跳过（2026-10-23 实测过一次）。
    """
    ci_commands = [_module_form(command) for command in _lint_job_commands()]
    static_commands = [command for command in ci_commands if command[0] in STATIC_TOOLS]
    parsed_tools = {command[0] for command in static_commands}
    assert parsed_tools == STATIC_TOOLS, f"CI lint job 的静态检查工具解析不全：{sorted(parsed_tools)}"

    local_commands = _local_commands()
    missing = [
        " ".join(ci_command)
        for ci_command in static_commands
        if not any(_covers(ci_command, local_command) for local_command in local_commands)
    ]
    assert missing == [], f"本地质量门缺少 CI lint 的等价步骤：{missing}"


def test_ci_only_steps_are_intentional() -> None:
    """豁免清单不许变成僵尸：点名的工具仍在 CI 里，且确实没进本地门。"""
    ci_tools = {command[0] for command in (_module_form(command) for command in _lint_job_commands())}
    local_tools = {command[0] for command in _local_commands()}
    assert ci_tools >= CI_ONLY_TOOLS, f"豁免项已不在 CI 中：{sorted(CI_ONLY_TOOLS - ci_tools)}"
    leaked = sorted(CI_ONLY_TOOLS & local_tools)
    assert not leaked, f"豁免项已进本地门，请移出 CI_ONLY_TOOLS：{leaked}"
