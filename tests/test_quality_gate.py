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


# --------------------------------------------------------------------------- S-5：双向一致判据


def _lint_job_commands_with_lines() -> list[tuple[int, list[str]]]:
    """同 :func:`_lint_job_commands`，但保留 `ci.yml` 行号——失败信息必须能点名到行。"""
    commands: list[tuple[int, list[str]]] = []
    inside = False
    for lineno, line in enumerate(CI_WORKFLOW.read_text(encoding="utf-8").splitlines(), start=1):
        if re.fullmatch(r"  lint:\s*", line):
            inside = True
            continue
        if inside and re.match(r"  \S", line):
            break
        if not inside:
            continue
        match = re.match(r"\s+run:\s*(\S.*?)\s*$", line)
        if match:
            commands.append((lineno, shlex.split(match.group(1))))
    assert commands, f"未能从 {CI_WORKFLOW} 解析出 lint job 的 run 步骤"
    return commands


def _spec(command: list[str]) -> tuple[str, str, frozenset[str]]:
    """把一条命令归一成 ``(工具, 动作, 路径集合)``，用于**结构化**比对。

    刻意不做整行字符串比对：那种判据会把空格、引号、参数顺序一起锁死，任何无害排版改动
    都变红，最后只能加白名单——本仓已记录过「放行表变成僵尸白名单」的教训。
    """
    normalized = _module_form(list(command))
    tool, rest = normalized[0], normalized[1:]
    if tool == "ruff":
        action = rest[0] if rest and not rest[0].startswith("-") else ""
        paths = {token.rstrip("/") for token in rest[1:] if not token.startswith("-")}
    else:  # mypy / bandit：动作维度无意义，只比目标集合
        action = ""
        paths = {token.rstrip("/") for token in rest if not token.startswith("-")}
    return tool, action, frozenset(paths)


def test_local_and_ci_static_commands_are_identical() -> None:
    """S-5：本地六门与 CI lint job 的静态命令必须**双向**一致，且每门两侧各出现恰好一次。

    为什么不能只做「CI ⊆ 本地」的单向包含（既有 :func:`test_local_gate_contains_every_ci_static_step`
    就是单向的）：单向包含下，本地删一台门、或 CI 多出台门，都不会变红。
    为什么不用白名单：需要不同的项（如 ``python -m bandit`` vs ``bandit``）由 :func:`_spec`
    归一成一个规范形，归一函数本身失效时会变红，而不是被放过。
    """
    # 键是 (工具, 动作)——`ruff check` 与 `ruff format --check` 是两台门，不能按工具合并。
    ci_by_gate: dict[tuple[str, str], list[tuple[int, tuple[str, str, frozenset[str]]]]] = {}
    for lineno, command in _lint_job_commands_with_lines():
        spec = _spec(command)
        if spec[0] in STATIC_TOOLS:
            ci_by_gate.setdefault((spec[0], spec[1]), []).append((lineno, spec))

    local_by_gate: dict[tuple[str, str], list[tuple[str, str, frozenset[str]]]] = {}
    for _label, command in quality_gate.COMMANDS:
        spec = _spec(list(command))
        if spec[0] in STATIC_TOOLS:
            local_by_gate.setdefault((spec[0], spec[1]), []).append(spec)

    gates = sorted(set(ci_by_gate) | set(local_by_gate))
    assert gates, "两侧都没有解析出任何静态门"
    for gate in gates:
        label = " ".join(part for part in gate if part)
        ci_entries = ci_by_gate.get(gate, [])
        local_entries = local_by_gate.get(gate, [])
        assert len(ci_entries) == 1, f"CI lint job 中 `{label}` 应恰好 1 条，实际 {len(ci_entries)}"
        assert len(local_entries) == 1, f"本地门中 `{label}` 应恰好 1 条，实际 {len(local_entries)}"

        lineno, ci_spec = ci_entries[0]
        local_spec = local_entries[0]
        only_ci = ci_spec[2] - local_spec[2]
        only_local = local_spec[2] - ci_spec[2]
        if not only_ci and not only_local:
            continue
        raise AssertionError(
            f"门 `{label}` 两侧路径集合不一致：\n"
            f"  本地 = {sorted(local_spec[2])}\n"
            f"  CI   = {sorted(ci_spec[2])}（.github/workflows/ci.yml:{lineno}）\n"
            f"  仅在本地存在：{sorted(only_local) or '（无）'}\n"
            f"  仅在 CI 存在：{sorted(only_ci) or '（无）'}"
        )


def test_consistency_judge_has_no_whitelist() -> None:
    """S-5：「无白名单」要可证——静态门不得出现在任何豁免清单里。

    这条防的是「下次有人不一致就加个例外」的路径依赖：只要静态工具跟豁免集有交集，
    一致性判据就等于被绕开了。
    """
    overlap = STATIC_TOOLS & CI_ONLY_TOOLS
    assert not overlap, f"静态门出现在豁免清单：{sorted(overlap)}"
    assert len(STATIC_TOOLS) >= 3, f"静态门集合疑似被削减：{sorted(STATIC_TOOLS)}"
