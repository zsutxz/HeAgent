"""``/skill-merge`` 交互收口：TTY 三选择、非 TTY 指引、覆盖方向与跳过。"""

from __future__ import annotations

import sys
from pathlib import Path

import click
import pytest

from heagent.cli.skill_merge import run_skill_merge
from heagent.skills.skill_store import SkillStore


@pytest.fixture()
def two_roots(tmp_path: Path) -> tuple[SkillStore, Path, Path]:
    global_root = tmp_path / "global"
    local_root = tmp_path / "local"
    SkillStore(str(global_root)).save("demo", "global version", "pg", ["sg"])
    SkillStore(str(local_root)).save("demo", "local version", "pl", ["sl"])
    return SkillStore([str(global_root), str(local_root)]), global_root, local_root


def _skill_text(root: Path, name: str) -> str:
    return (root / name / "SKILL.md").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_no_conflicts_prints_ok(capsys: pytest.CaptureFixture[str]) -> None:
    store = SkillStore(str(Path("whatever-does-not-exist")))
    await run_skill_merge(store)
    assert "no cross-root skill conflicts" in capsys.readouterr().err


@pytest.mark.asyncio
async def test_non_tty_prints_guidance_and_merges_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    global_root, local_root = tmp_path / "g", tmp_path / "l"
    SkillStore(str(global_root)).save("demo", "gv", "p", ["s"])
    SkillStore(str(local_root)).save("demo", "lv", "p", ["s"])
    store = SkillStore([str(global_root), str(local_root)])
    monkeypatch.setattr(sys, "stdin", type("FakeStdin", (), {"isatty": lambda self: False})())

    await run_skill_merge(store)

    err = capsys.readouterr().err
    assert "non-interactive session" in err
    assert _skill_text(local_root, "demo") != _skill_text(global_root, "demo")  # 未被覆盖


@pytest.mark.asyncio
async def test_choice_one_overwrites_local_with_global(
    two_roots: tuple[SkillStore, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store, global_root, local_root = two_roots
    monkeypatch.setattr(sys, "stdin", type("FakeStdin", (), {"isatty": lambda self: True})())
    monkeypatch.setattr(click, "prompt", lambda *a, **k: 1)
    monkeypatch.setattr(click, "confirm", lambda *a, **k: True)

    await run_skill_merge(store)

    assert "全局覆盖本地 done" in capsys.readouterr().err
    assert _skill_text(local_root, "demo") == _skill_text(global_root, "demo")
    assert store.parse("demo") is not None  # 合并后仍可用


@pytest.mark.asyncio
async def test_choice_two_overwrites_global_with_local(
    two_roots: tuple[SkillStore, Path, Path],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store, global_root, local_root = two_roots
    monkeypatch.setattr(sys, "stdin", type("FakeStdin", (), {"isatty": lambda self: True})())
    monkeypatch.setattr(click, "prompt", lambda *a, **k: 2)
    monkeypatch.setattr(click, "confirm", lambda *a, **k: True)

    await run_skill_merge(store)

    assert "本地覆盖全局 done" in capsys.readouterr().err
    assert _skill_text(global_root, "demo") == _skill_text(local_root, "demo")


@pytest.mark.asyncio
async def test_skip_and_decline_change_nothing(
    two_roots: tuple[SkillStore, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    store, global_root, local_root = two_roots
    before_global, before_local = _skill_text(global_root, "demo"), _skill_text(local_root, "demo")
    monkeypatch.setattr(sys, "stdin", type("FakeStdin", (), {"isatty": lambda self: True})())
    monkeypatch.setattr(click, "prompt", lambda *a, **k: 3)  # 全部跳过
    monkeypatch.setattr(click, "confirm", lambda *a, **k: True)

    await run_skill_merge(store)

    assert _skill_text(global_root, "demo") == before_global
    assert _skill_text(local_root, "demo") == before_local


@pytest.mark.asyncio
async def test_confirm_refusal_aborts(
    two_roots: tuple[SkillStore, Path, Path], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    store, _global_root, local_root = two_roots
    before_local = _skill_text(local_root, "demo")
    monkeypatch.setattr(sys, "stdin", type("FakeStdin", (), {"isatty": lambda self: True})())
    monkeypatch.setattr(click, "prompt", lambda *a, **k: 1)
    monkeypatch.setattr(click, "confirm", lambda *a, **k: False)  # 确认时拒绝

    await run_skill_merge(store)

    assert "aborted by user" in capsys.readouterr().err
    assert _skill_text(local_root, "demo") == before_local
