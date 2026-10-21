"""Progress-banner contract: silence switch and run-id labels."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from heagent.cli import display as cli_display
from heagent.cli.display import show_deferred_work, show_tool_activity
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


def test_show_deferred_work_reads_the_archive_ledger(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """2026-09-17 起项目台账正名为 ``deferred-work-archive.md``（原 ``deferred-work.md`` 已并入）。

    只认旧名的读法会让 /deferred 静默漏掉整份项目台账（本仓当前正是这个形态）。
    """
    _ledger(tmp_path, "_bmad-output/implementation-artifacts/deferred-work-archive.md", 2)
    show_deferred_work(tmp_path, tail=1)
    err = capsys.readouterr().err
    assert "deferred-work-archive.md: 2 entries" in err
    assert "spec-2.md — finding 2" in err


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
    from heagent.cli.display import _icon

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


# --- 沙箱启动提示（echo_sandbox_hint）-----------------------------------------
# 判据目的：让「这次到底请求了哪种隔离」在启动时一眼可见——firejail 一直有提示，
# docker 档此前完全静默（用户只能翻日志才知道有没有上容器）。


def test_sandbox_hint_is_silent_for_non_isolating_backends(capsys: pytest.CaptureFixture[str]) -> None:
    """auto / passthrough / winjob 无隔离能力，启动时不制造噪音。"""
    settings = get_settings()
    for backend in (None, "", "auto", "passthrough", "winjob"):
        cli_display.echo_sandbox_hint(backend, settings)
    assert capsys.readouterr().err == ""


def test_sandbox_hint_keeps_firejail_messages_unchanged(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """firejail 分支文案逐字保留（重构前已有的行为，别在扩后端口径时改掉）。"""
    settings = get_settings()
    monkeypatch.setattr("shutil.which", lambda _name: None)
    cli_display.echo_sandbox_hint("firejail", settings, install_hint=True)
    err = capsys.readouterr().err
    assert f"WARNING: firejail not found ({settings.sandbox_firejail_path})" in err
    assert "Shell commands will run WITHOUT sandbox isolation." in err
    assert "sudo apt install firejail" in err


def test_sandbox_hint_reports_docker_request(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """docker 档必须出声，并把镜像与网络档如实写出来（便于对照 sandbox_decision）。"""
    settings = get_settings()
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/docker")
    cli_display.echo_sandbox_hint("docker", settings)
    err = capsys.readouterr().err
    assert "docker sandbox REQUESTED" in err
    assert f"image={settings.sandbox_docker_image}" in err
    assert "network=none" in err
    assert "falls back to passthrough" in err


def test_sandbox_hint_warns_when_docker_cli_missing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """CLI 缺席 = 必然降级，必须明确说「没有隔离」而不是假装已启用。"""
    monkeypatch.setattr("shutil.which", lambda _name: None)
    cli_display.echo_sandbox_hint("docker", get_settings(), install_hint=True)
    err = capsys.readouterr().err
    assert "WARNING: docker CLI not found" in err
    assert "docs.docker.com" in err


def test_sandbox_hint_shows_bridge_and_pinned_digest(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """网络档与 digest pin 都影响隔离强度，提示行必须反映实际配置。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "sandbox_network", True)
    monkeypatch.setattr(settings, "sandbox_docker_digest", "sha256:" + "a" * 64)
    monkeypatch.setattr("shutil.which", lambda _name: "/usr/bin/docker")
    cli_display.echo_sandbox_hint("Docker", settings)  # 大小写无关
    err = capsys.readouterr().err
    assert "network=bridge" in err
    assert "digest=sha256:" in err
