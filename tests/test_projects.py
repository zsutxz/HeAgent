from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from heagent.projects import MAX_PROJECTS, ProjectRegistry, ProjectRegistryError, normalize_project_path, project_id_for


def test_normalized_path_identity_handles_relative_and_trailing_separator(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(tmp_path)
    relative = normalize_project_path("project")
    trailing = normalize_project_path(str(project) + os.sep)
    assert relative == trailing == str(project.resolve())
    assert project_id_for(relative) == project_id_for(trailing)


def test_normalized_path_identity_resolves_symlink_and_case_aliases(tmp_path: Path) -> None:
    project = tmp_path / "Project"
    project.mkdir()
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(project, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable for this test user")
    assert normalize_project_path(alias) == normalize_project_path(project)
    if os.name == "nt":
        assert project_id_for(str(project).lower()) == project_id_for(project)


def test_register_is_idempotent_and_keeps_existing_name(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    registry = ProjectRegistry(tmp_path / "registry.json", default_path=tmp_path)
    first = registry.register(str(project), name="First")
    duplicate = registry.register(str(project) + os.sep, name="Ignored")
    assert duplicate == first
    assert duplicate.name == "First"
    assert len(registry.list()) == 2


def test_registration_rejects_missing_and_non_directory_paths(tmp_path: Path) -> None:
    registry = ProjectRegistry(tmp_path / "registry.json", default_path=tmp_path)
    with pytest.raises(ValueError):
        registry.register(str(tmp_path / "missing"))
    file_path = tmp_path / "file.txt"
    file_path.write_text("data", encoding="utf-8")
    with pytest.raises(ValueError):
        registry.register(str(file_path))
    assert not (tmp_path / "registry.json").exists()


def test_list_preserves_unavailable_entries_and_remove_preserves_directory(tmp_path: Path) -> None:
    project = tmp_path / "project"
    state = project / ".heagent"
    state.mkdir(parents=True)
    payload = state / "data.json"
    payload.write_text('{"keep":true}', encoding="utf-8")
    registry = ProjectRegistry(tmp_path / "registry.json", default_path=tmp_path)
    entry = registry.register(str(project))
    removed = registry.remove(entry.id)
    assert removed.id == entry.id
    assert payload.read_text(encoding="utf-8") == '{"keep":true}'
    unavailable_path = tmp_path / "unavailable"
    unavailable_path.mkdir()
    unavailable = registry.register(str(unavailable_path))
    unavailable_path.rename(tmp_path / "moved")
    assert next(item for item in registry.list() if item.id == unavailable.id).available is False


def test_default_project_is_implicit_and_cannot_be_removed(tmp_path: Path) -> None:
    registry = ProjectRegistry(tmp_path / "registry.json", default_path=tmp_path)
    default = next(item for item in registry.list() if item.is_default)
    assert default.id == "default"
    with pytest.raises(ProjectRegistryError, match="default project"):
        registry.remove("default")
    assert not (tmp_path / "registry.json").exists()


def test_corrupt_registry_warns_and_recovers_empty(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    path = tmp_path / "registry.json"
    path.write_text("{broken", encoding="utf-8")
    registry = ProjectRegistry(path, default_path=tmp_path)
    assert len(registry.list()) == 1
    assert "Invalid project registry" in caplog.text
    project = tmp_path / "project"
    project.mkdir()
    registry.register(str(project))
    assert json.loads(path.read_text(encoding="utf-8"))[0]["path"] == str(project.resolve())


def test_project_limit_including_default_is_enforced_atomically(tmp_path: Path) -> None:
    registry = ProjectRegistry(tmp_path / "registry.json", default_path=tmp_path)
    for index in range(MAX_PROJECTS - 1):
        path = tmp_path / f"p{index}"
        path.mkdir()
        registry.register(str(path))
    overflow = tmp_path / "overflow"
    overflow.mkdir()
    with pytest.raises(ValueError):
        registry.register(str(overflow))
    assert len(registry.list()) == MAX_PROJECTS


def test_rename_and_touch_update_only_registry_metadata(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    registry = ProjectRegistry(tmp_path / "registry.json", default_path=tmp_path)
    entry = registry.register(str(project))
    renamed = registry.rename(entry.id, "Renamed")
    touched = registry.touch(entry.id)
    assert renamed.name == "Renamed"
    assert touched.last_opened_at is not None


def test_list_orders_recent_projects_before_implicit_default(tmp_path: Path) -> None:
    registry = ProjectRegistry(tmp_path / "registry.json", default_path=tmp_path)
    paths = [tmp_path / "one", tmp_path / "two"]
    for path in paths:
        path.mkdir()
        registry.register(str(path))
    entries = registry.load()
    registry.touch(entries[0].id)
    registry.touch(entries[1].id)
    listed = registry.list()
    assert [entry.id for entry in listed] == [entries[1].id, entries[0].id, "default"]
