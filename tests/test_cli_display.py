"""Progress-banner contract: silence switch and run-id labels."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from heagent import cli_display
from heagent.cli_display import show_deferred_work
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
