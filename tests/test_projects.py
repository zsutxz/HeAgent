from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from heagent.pub.projects import (
    MAX_PROJECTS,
    ProjectRegistry,
    ProjectRegistryError,
    normalize_project_path,
    project_id_for,
)


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


def test_corrupt_registry_is_read_fail_soft_but_never_overwritten(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """读 fail-soft（列表仍可用）**且**写 fail-closed（绝不把自己解析不了的内容回写成空表）。

    评审发现（镜头一 H2）：本用例原先断言「损坏后 ``register`` 会把文件重写成新表」——那等于把
    「一次坏字节（BOM / 超 32 条 / 重复 id / 缺字段）在下次改动时清空全部已登记项目」钉成预期。
    现改为断言：读路径照旧 fail-soft，写路径**拒绝**改写且原字节一字未动（失败要响亮）。
    """
    path = tmp_path / "registry.json"
    path.write_text("{broken", encoding="utf-8")
    registry = ProjectRegistry(path, default_path=tmp_path)
    assert len(registry.list()) == 1  # 读：只剩隐式 default，服务不阻断
    assert "Invalid project registry" in caplog.text
    project = tmp_path / "project"
    project.mkdir()
    with pytest.raises(ProjectRegistryError) as failure:
        registry.register(str(project))
    assert failure.value.code == "server_error"
    assert path.read_text(encoding="utf-8") == "{broken"


def test_corrupt_registry_never_loses_registered_projects(tmp_path: Path) -> None:
    """带 BOM 的注册表（本项目对 BOM 有前科）不得让已登记项目在下次写入时消失。"""
    good = tmp_path / "good"
    good.mkdir()
    path = tmp_path / "registry.json"
    registry = ProjectRegistry(path, default_path=tmp_path)
    registry.register(str(good))
    before = path.read_text(encoding="utf-8")
    path.write_text("\ufeff" + before, encoding="utf-8")  # 外部编辑 / 编辑器加 BOM
    other = tmp_path / "other"
    other.mkdir()
    with pytest.raises(ProjectRegistryError):
        registry.register(str(other))
    assert path.read_text(encoding="utf-8") == "\ufeff" + before  # 原字节保留，未清空


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


class TestFindSingleProject:
    """``find`` = 控制台热路径的单条解析：语义与 ``list`` 一致，但只 stat 目标项（台账 A10）。"""

    @staticmethod
    def _registry(tmp_path: Path, count: int) -> ProjectRegistry:
        registry = ProjectRegistry(tmp_path / "registry.json", default_path=tmp_path)
        for i in range(count):
            project = tmp_path / f"p{i}"
            project.mkdir()
            registry.register(str(project), name=f"p{i}")
        return registry

    def test_default_entry_matches_list(self, tmp_path: Path) -> None:
        registry = self._registry(tmp_path, 2)
        found = registry.find("default")
        listed = next(entry for entry in registry.list() if entry.is_default)
        assert found == listed

    def test_registered_entry_matches_list_row(self, tmp_path: Path) -> None:
        registry = self._registry(tmp_path, 1)
        target = registry.list()[0]
        assert registry.find(target.id) == target

    def test_unknown_project_returns_none(self, tmp_path: Path) -> None:
        registry = self._registry(tmp_path, 1)
        assert registry.find("p0badbeef") is None

    def test_find_stats_only_the_target_while_list_stats_every_project(self, tmp_path: Path, monkeypatch) -> None:
        """量化判据：``find`` = 1 次注册表读 + 1 次 ``is_dir``；``list`` = 1 次读 + (1 + N) 次 ``is_dir``。"""
        registry = self._registry(tmp_path, 5)
        stats = {"is_dir": 0, "read": 0}
        real_is_dir = Path.is_dir
        real_read = Path.read_text

        def counting_is_dir(self: Path) -> bool:
            stats["is_dir"] += 1
            return real_is_dir(self)

        def counting_read(self: Path, *args: object, **kwargs: object) -> str:
            stats["read"] += 1
            return real_read(self, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(Path, "is_dir", counting_is_dir)
        monkeypatch.setattr(Path, "read_text", counting_read)

        target = registry.list()[0]  # 先取目标（计入统计后再清零）
        stats["is_dir"] = stats["read"] = 0
        assert registry.find(target.id) is not None
        assert stats == {"is_dir": 1, "read": 1}, f"find 只应 stat 目标项：{stats}"

        stats["is_dir"] = stats["read"] = 0
        registry.list()
        assert stats == {"is_dir": 6, "read": 1}, f"list 逐项 stat（默认 1 + 已登记 5）：{stats}"
