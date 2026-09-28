"""``/goal`` 消息 sink（台账 A4b）的 CI 判据——不依赖 textual。

三件事：``_echo`` 的默认路径仍是 stderr（CLI 逐字不变）；有 sink 时改投 sink；
``_goal_runner`` 在自己的调用链上绑定 sink 并在结束时复位 ContextVar（不泄漏到后续调用）。
另加一条结构性判据：GUI 的日志配置不得再往 stderr 挂 handler（TUI 独占终端，A4b）。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from heagent.cli import goal as cli_goal

GUI_CLI_SOURCE = Path(__file__).resolve().parents[1] / "src" / "heagent" / "gui" / "cli.py"


def test_echo_default_path_still_writes_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    cli_goal._echo("[goal] hello")
    captured = capsys.readouterr()
    assert "[goal] hello" in captured.err
    assert captured.out == ""


def test_echo_routes_to_the_sink_without_touching_stderr(capsys: pytest.CaptureFixture[str]) -> None:
    lines: list[str] = []
    token = cli_goal._MESSAGE_SINK.set(lines.append)
    try:
        cli_goal._echo("[goal] via sink")
    finally:
        cli_goal._MESSAGE_SINK.reset(token)
    assert lines == ["[goal] via sink"]
    assert capsys.readouterr().err == "", "有 sink 时不得再写 stderr"


def test_sink_contextvar_is_restored_after_reset() -> None:
    token = cli_goal._MESSAGE_SINK.set(str)
    cli_goal._MESSAGE_SINK.reset(token)
    assert cli_goal._MESSAGE_SINK.get() is None


@pytest.mark.asyncio
async def test_goal_runner_binds_the_sink_for_its_call_chain(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``_goal_runner(on_message=…)`` 后，内部 ``_echo`` 调用点改投 sink，且结束后复位。"""
    lines: list[str] = []

    def boom() -> object:
        raise ValueError("workflow missing")

    monkeypatch.setattr(cli_goal, "_goal_declarative_workflow", boom)
    await cli_goal._goal_runner(object(), None, "status", on_message=lines.append)  # type: ignore[arg-type]

    assert lines == ["[goal] workflow missing"], "内部输出未走 sink"
    assert capsys.readouterr().err == "", "绑定了 sink 就不该再写 stderr"
    assert cli_goal._MESSAGE_SINK.get() is None, "ContextVar 必须在 finally 中复位"


@pytest.mark.asyncio
async def test_goal_runner_without_sink_still_writes_stderr(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def boom() -> object:
        raise ValueError("workflow missing")

    monkeypatch.setattr(cli_goal, "_goal_declarative_workflow", boom)
    await cli_goal._goal_runner(object(), None, "status")  # type: ignore[arg-type]
    assert "[goal] workflow missing" in capsys.readouterr().err


def test_all_goal_output_goes_through_the_echo_funnel() -> None:
    """历史 40+ 处 ``click.echo`` 必须都已收敛到 ``_echo``（除 ``_echo`` 自身的兜底调用）。"""
    source = Path(cli_goal.__file__).read_text(encoding="utf-8")
    direct = [
        ln.strip()
        for ln in source.splitlines()
        if "click.echo(" in ln and "``" not in ln and not ln.lstrip().startswith("#")
    ]
    assert direct == ["click.echo(message, err=err)"], f"仍有绕过 sink 的直接输出：{direct}"


def test_gui_logging_no_longer_targets_stderr() -> None:
    """结构性判据：GUI 日志只写文件（TUI 独占终端；也避免日志被吞进对话区，A4b）。"""
    source = GUI_CLI_SOURCE.read_text(encoding="utf-8")
    assert "StreamHandler(sys.stderr)" not in source
    assert "handlers=[_file_handler]" in source
