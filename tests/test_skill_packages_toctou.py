"""Deterministic characterization of the SkillPackage resolve/read TOCTOU window."""

from __future__ import annotations

import errno
import os
import stat
from types import SimpleNamespace
from pathlib import Path

import pytest

from heagent.memory.skill_packages import SkillPackage, SkillPackageResourceError


def _make_package(root: Path) -> SkillPackage:
    (root / "SKILL.md").write_text("---\nname: he-build\n---\n", encoding="utf-8")
    return SkillPackage(skill_id="he-build", root=root)


def _replace_after_is_file(monkeypatch: pytest.MonkeyPatch, victim: Path, content: str) -> dict[str, bool]:
    """Characterize the legacy check-then-read window without invoking the hardened reader."""
    original = Path.is_file
    state = {"swapped": False}

    def hooked(path: Path) -> bool:
        result = original(path)
        if not state["swapped"] and path == victim and result:
            victim.write_text(content, encoding="utf-8")
            state["swapped"] = True
        return result

    monkeypatch.setattr(Path, "is_file", hooked)
    return state


def test_legacy_resolve_then_read_window_remains_characterized(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    package = _make_package(tmp_path)
    resource = tmp_path / "step.md"
    resource.write_text("trusted", encoding="utf-8")
    resolved = package._resolve("step.md")
    state = _replace_after_is_file(monkeypatch, resolved, "replaced")

    assert resolved.is_file()
    assert resolved.read_text(encoding="utf-8") == "replaced"
    assert state["swapped"] is True


def test_resource_readers_use_one_opened_descriptor(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    package = _make_package(tmp_path)
    readers = {
        "read_entry": ("SKILL.md", lambda: package.read_entry().text),
        "read_resource": ("step.md", lambda: package.read_resource("step.md")),
        "read_step": ("step.md", lambda: package.read_step("step.md")),
        "read_reference": ("references/ref.md", lambda: package.read_reference("ref.md")),
        "read_template": ("templates/template.md", lambda: package.read_template("template.md")),
        "read_asset": ("assets/asset.md", lambda: package.read_asset("asset.md")),
        "read_script": ("scripts/script.md", lambda: package.read_script("script.md")),
    }
    opened: list[tuple[Path, int]] = []
    closed: list[bool] = []
    original_open = os.open
    original_fdopen = os.fdopen

    def record_open(path: str | os.PathLike[str], flags: int, *args: object) -> int:
        opened.append((Path(path), flags))
        return original_open(path, flags, *args)

    class TrackingStream:
        def __init__(self, stream: object) -> None:
            self.stream = stream

        def __enter__(self) -> TrackingStream:
            self.stream.__enter__()  # type: ignore[attr-defined]
            return self

        def __exit__(self, *args: object) -> object:
            closed.append(True)
            return self.stream.__exit__(*args)  # type: ignore[attr-defined]

        def read(self, *args: object) -> bytes:
            return self.stream.read(*args)  # type: ignore[attr-defined,no-any-return]

    def record_fdopen(fd: int, *args: object, **kwargs: object) -> TrackingStream:
        return TrackingStream(original_fdopen(fd, *args, **kwargs))

    monkeypatch.setattr(os, "open", record_open)
    monkeypatch.setattr(os, "fdopen", record_fdopen)
    for resource_name, reader in readers.values():
        resource = tmp_path / resource_name
        resource.parent.mkdir(parents=True, exist_ok=True)
        resource.write_text("trusted", encoding="utf-8")
        assert reader() == "trusted"
        assert len(opened) == 1
        if hasattr(os, "O_NOFOLLOW"):
            assert opened[0][1] & os.O_NOFOLLOW
        assert closed == [True]
        opened.clear()
        closed.clear()


def test_final_symlink_replacement_is_rejected_when_supported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    package = _make_package(tmp_path)
    target = tmp_path / "target.md"
    link = tmp_path / "step.md"
    outside = tmp_path.parent / "outside-target.md"
    target.write_text("trusted", encoding="utf-8")
    outside.write_text("outside", encoding="utf-8")
    probe = tmp_path / "probe-target"
    probe_link = tmp_path / "probe-link"
    probe.write_text("probe", encoding="utf-8")
    try:
        probe_link.symlink_to(probe)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    finally:
        probe_link.unlink(missing_ok=True)
        probe.unlink(missing_ok=True)
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")

    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("O_NOFOLLOW unavailable")
    original = os.open
    state = {"swapped": False}

    def hooked(path: str | os.PathLike[str], flags: int, *args: object) -> int:
        if not state["swapped"] and Path(path) == target:
            target.unlink()
            target.symlink_to(outside)
            state["swapped"] = True
        return original(path, flags, *args)

    monkeypatch.setattr(os, "open", hooked)

    with pytest.raises(SkillPackageResourceError, match="symlink"):
        package.read_resource("step.md")
    assert state["swapped"] is True


def test_final_symlink_replacement_uses_compatibility_fallback_without_nofollow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    package = _make_package(tmp_path)
    target = tmp_path / "target.md"
    link = tmp_path / "step.md"
    outside = tmp_path.parent / "outside-target.md"
    target.write_text("trusted", encoding="utf-8")
    outside.write_text("outside", encoding="utf-8")
    try:
        link.symlink_to(target)
    except OSError as exc:
        pytest.skip(f"symlink creation unavailable: {exc}")
    monkeypatch.delattr(os, "O_NOFOLLOW", raising=False)
    original = os.open
    state = {"swapped": False}

    def hooked(path: str | os.PathLike[str], flags: int, *args: object) -> int:
        if not state["swapped"] and Path(path) == target:
            target.unlink()
            target.symlink_to(outside)
            state["swapped"] = True
        return original(path, flags, *args)

    monkeypatch.setattr(os, "open", hooked)
    assert package.read_resource("step.md") == "outside"
    assert state["swapped"] is True


def test_nofollow_einval_uses_compatibility_fallback(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    package = _make_package(tmp_path)
    resource = tmp_path / "step.md"
    resource.write_text("trusted", encoding="utf-8")
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("O_NOFOLLOW unavailable")
    nofollow = os.O_NOFOLLOW
    original = os.open
    calls: list[int] = []

    def hooked(path: str | os.PathLike[str], flags: int, *args: object) -> int:
        calls.append(flags)
        if len(calls) == 1:
            raise OSError(errno.EINVAL, "nofollow unsupported")
        return original(path, flags, *args)

    monkeypatch.setattr(os, "open", hooked)
    assert package.read_resource("step.md") == "trusted"
    assert len(calls) == 2
    assert calls[0] & nofollow
    assert not calls[1] & nofollow


def test_non_regular_resource_is_rejected(tmp_path: Path) -> None:
    package = _make_package(tmp_path)
    (tmp_path / "directory").mkdir()
    with pytest.raises(SkillPackageResourceError, match="cannot read resource"):
        package.read_resource("directory")


def test_fifo_descriptor_is_rejected_without_reading(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    package = _make_package(tmp_path)
    resource = tmp_path / "fifo"
    resource.write_text("unused", encoding="utf-8")
    monkeypatch.setattr(os, "fstat", lambda _fd: SimpleNamespace(st_mode=stat.S_IFIFO))

    with pytest.raises(SkillPackageResourceError, match="cannot read resource"):
        package.read_resource("fifo")
