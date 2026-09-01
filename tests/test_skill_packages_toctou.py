"""Deterministic characterization of the SkillPackage resolve/read TOCTOU window."""

from __future__ import annotations

from pathlib import Path

import pytest

from heagent.memory.skill_packages import SkillPackage


def _make_package(root: Path) -> SkillPackage:
    (root / "SKILL.md").write_text("---\nname: he-build\n---\n", encoding="utf-8")
    return SkillPackage(skill_id="he-build", root=root)


def _replace_after_is_file(monkeypatch: pytest.MonkeyPatch, victim: Path, content: str) -> dict[str, bool]:
    """Replace checked content immediately after its existence check returns."""
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


def test_resource_readers_observe_replacement_after_check(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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
    for resource_name, reader in readers.values():
        resource = tmp_path / resource_name
        resource.parent.mkdir(parents=True, exist_ok=True)
        resource.write_text("trusted", encoding="utf-8")
        with monkeypatch.context() as local:
            state = _replace_after_is_file(local, resource, "replaced")
            assert reader() == "replaced"
            assert state["swapped"] is True

    # Characterization: resolve_under_root has already fenced the path, but the
    # later read follows the replacement made between check and use.
    assert package.read_resource("step.md") == "replaced"


def test_resolved_symlink_target_replacement_can_escape(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
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

    # _resolve() returns the concrete target. Replacing that target after the
    # check still changes what read_text() opens on platforms following links.
    original = Path.is_file
    state = {"swapped": False}

    def hooked(path: Path) -> bool:
        result = original(path)
        if not state["swapped"] and path == target and result:
            target.unlink()
            target.symlink_to(outside)
            state["swapped"] = True
        return result

    monkeypatch.setattr(Path, "is_file", hooked)

    assert package.read_resource("step.md") == "outside"
    assert state["swapped"] is True
