"""Progress-banner contract: silence switch and run-id labels."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from heagent import cli_display
from heagent.cli_display import show_deferred_work, show_tool_activity
from heagent.config import get_settings, reset_settings

if TYPE_CHECKING:
    import pytest


def test_announce_start_labels_banner_with_the_run_id(capsys: pytest.CaptureFixture[str]) -> None:
    """Parallel children of one step stay distinguishable on screen."""
    get_settings().announce_progress = True
    try:
        cli_display._announce_start("bmad-build / S-1", "实现故事", run_id="9b860b166ea64e65ac2b1a8c963ec547")
    finally:
        reset_settings()
    assert capsys.readouterr().err.strip() == "▶ 启动 [bmad-build / S-1#9b860b16] — 实现故事"


def test_announce_start_without_run_id_keeps_the_plain_label(capsys: pytest.CaptureFixture[str]) -> None:
    get_settings().announce_progress = True
    try:
        cli_display._announce_start("subagent", "review")
    finally:
        reset_settings()
    assert capsys.readouterr().err.strip() == "▶ 启动 [subagent] — review"


def test_announce_progress_switch_silences_banners(capsys: pytest.CaptureFixture[str]) -> None:
    """Banners share the terminal with the interactive input line; they must be silenceable."""
    settings = get_settings()
    settings.announce_progress = False
    try:
        cli_display._announce_start("subagent", "review")
    finally:
        reset_settings()
    assert capsys.readouterr().err == ""


def _ledger(root: Path, relative: str, entries: int) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(
        f"- source_spec: `spec-{index}.md`\n  summary: finding {index}\n  evidence: because {index}\n\n"
        for index in range(1, entries + 1)
    )
    path.write_text(body, encoding="utf-8")
    return path


def test_show_deferred_work_reads_the_canonical_ledger(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The bmad-build ledger finally has a reader."""
    _ledger(tmp_path, "_bmad-output/implementation-artifacts/deferred-work.md", 3)
    show_deferred_work(tmp_path, tail=2)
    err = capsys.readouterr().err
    assert "[deferred] _bmad-output/implementation-artifacts/deferred-work.md: 3 entries" in err
    assert "spec-2.md — finding 2" in err
    assert "spec-3.md — finding 3" in err
    assert "spec-1.md" not in err


def test_show_deferred_work_includes_legacy_and_goal_local_ledgers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The three drifted locations are surfaced together instead of silently diverging."""
    _ledger(tmp_path, "_bmad-output/implementation-artifacts/deferred-work.md", 1)
    _ledger(tmp_path, "_bmad-output/deferred-work.md", 1)
    _ledger(tmp_path, "_he-output/goals/demo/step-07-implement-story/epic-e1/deferred-work.md", 2)
    show_deferred_work(tmp_path)
    err = capsys.readouterr().err
    assert "_bmad-output/implementation-artifacts/deferred-work.md: 1 entries" in err
    assert "_bmad-output/deferred-work.md: 1 entries" in err
    assert "_he-output/goals/demo/step-07-implement-story/epic-e1/deferred-work.md: 2 entries" in err


def test_show_deferred_work_reports_a_missing_ledger(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    show_deferred_work(tmp_path)
    assert "[deferred] no ledger found" in capsys.readouterr().err


def _activity_loop(*labels: str):
    """Duck-typed stand-in — show_tool_activity only reads ``tool_activity``."""
    from types import SimpleNamespace

    return SimpleNamespace(tool_activity=list(labels))


def test_show_tool_activity_is_silent_without_calls(capsys: pytest.CaptureFixture[str]) -> None:
    """零调用不输出（与 _print_usage 零用量静默一致）。"""
    show_tool_activity(_activity_loop())

    assert capsys.readouterr().err == ""


def test_show_tool_activity_dedupes_repeated_targets(capsys: pytest.CaptureFixture[str]) -> None:
    """同一文件读三次只列一次，但头部仍报真实调用次数。"""
    show_tool_activity(_activity_loop("file_read → a.md", "shell → pytest -q", "file_read → a.md"))

    assert capsys.readouterr().err.splitlines() == [
        "[tools] 3 次调用尝试，2 个不同目标：",
        "  file_read → a.md",
        "  shell → pytest -q",
    ]


def test_icon_degrades_when_the_console_cannot_encode_it() -> None:
    """GBK（cp936）控制台 / 重定向下 emoji 与几何符号不可编码——必须降级而非抛异常。"""
    from heagent.cli_display import _icon

    assert _icon("🔧", "[tool]", encoding="cp936") == "[tool]"
    assert _icon("🔧", "[tool]", encoding="utf-8") == "🔧"
    assert _icon("▶ ", "> ", encoding="cp936") == "> "
    assert _icon("✔ ", "", encoding="cp936") == ""
    # 未知编码名（LookupError）同样降级，不能让状态行把 run 带崩。
    assert _icon("✔ ", "", encoding="no-such-codec") == ""


def test_show_tool_activity_folds_overflow(capsys: pytest.CaptureFixture[str]) -> None:
    """超出 limit 的目标折叠成一行计数，不刷屏。"""
    show_tool_activity(_activity_loop(*[f"file_read → {index}.md" for index in range(5)]), limit=2)

    assert capsys.readouterr().err.splitlines() == [
        "[tools] 5 次调用尝试：",
        "  file_read → 0.md",
        "  file_read → 1.md",
        "  … 另有 3 个目标",
    ]


def test_current_version_matches_the_package_attribute() -> None:
    """版本只有一处事实源：``heagent.__version__``。"""
    import heagent

    assert cli_display._current_version() == heagent.__version__


def test_banner_ignores_stale_installed_metadata(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """回归锁（2026-09-22 实测故障）：横幅原读 ``importlib.metadata``，editable 安装未刷新时
    报出旧版本（`.venv` dist-info=0.6.1 而源码=0.6.2）。把安装元数据打成哨兵值后，
    横幅仍须输出源码版本——即不再依赖「已安装」这一前提。
    """
    import importlib.metadata

    import heagent

    monkeypatch.setattr(importlib.metadata, "version", lambda _name: "0.0.0-stale-metadata")
    cli_display._print_banner()

    banner = capsys.readouterr().err.strip()
    assert banner == f"HeAgent v{heagent.__version__} — A self-improving AI Agent core framework"
    assert "stale-metadata" not in banner


def test_package_version_matches_pyproject() -> None:
    """源码版本与 ``pyproject.toml`` 必须同步——两处漂移正是横幅撒谎的温床。"""
    import tomllib

    import heagent

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    declared = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]

    assert heagent.__version__ == declared
