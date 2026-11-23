"""`ProjectRegistry.health()` 的判据：三类读失败映射 `unreadable`，每成因恰一条 WARNING（E75 R5/R7）。"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from heagent.pub.projects import MAX_PROJECTS, ProjectRegistry


def _registry(tmp_path: Path) -> ProjectRegistry:
    return ProjectRegistry(tmp_path / "projects.json", default_path=tmp_path)


def _warnings(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.levelno == logging.WARNING]


def test_healthy_registry_reports_ok(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """可解析的注册表判 `ok` 且 `detail` 为空；探针纯读——既不建文件也不改字节。"""
    caplog.set_level(logging.WARNING)
    path = tmp_path / "projects.json"
    registry = _registry(tmp_path)
    assert registry.health().code == "ok"
    assert not path.exists()  # 文件不存在也算 ok（空表合法），且探针没顺手建它

    project = tmp_path / "project"
    project.mkdir()
    registry.register(str(project))
    before = path.read_bytes()
    health = registry.health()
    assert (health.code, health.detail) == ("ok", "")
    assert path.read_bytes() == before
    assert _warnings(caplog) == []


_UNREADABLE_CONTENT = {
    "broken-json": "{broken",
    "bom": "\ufeff[]",
    "too-many-entries": json.dumps(
        [{"id": f"p{index}", "name": f"p{index}", "path": f"/tmp/p{index}"} for index in range(MAX_PROJECTS + 1)],
        ensure_ascii=False,
    ),
}


@pytest.mark.parametrize("content", list(_UNREADABLE_CONTENT.values()), ids=list(_UNREADABLE_CONTENT))
def test_unreadable_content_reports_unreadable(content: str, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """坏 JSON / BOM / 超 32 条：探针判 `unreadable`，`detail` 不含路径，列表径仍 fail-soft，恰 1 条 WARNING。"""
    caplog.set_level(logging.WARNING)
    path = tmp_path / "projects.json"
    path.write_text(content, encoding="utf-8")
    registry = _registry(tmp_path)

    health = registry.health()
    assert health.code == "unreadable"
    assert health.detail and str(tmp_path) not in health.detail
    assert [item.id for item in registry.list()] == ["default"]  # 读径 fail-soft 逐字不变
    assert path.read_text(encoding="utf-8") == content  # 探针不写盘
    assert len(_warnings(caplog)) == 1  # health + list 合计一条，不随调用数刷屏


def test_unreadable_directory_reports_unreadable(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """注册表路径是目录（`read_text` 抛 `OSError`）：判 `unreadable`，列表径回 default，恰 1 条 WARNING。"""
    caplog.set_level(logging.WARNING)
    (tmp_path / "projects.json").mkdir()  # POSIX = IsADirectoryError，Windows = PermissionError，都属 OSError
    registry = _registry(tmp_path)

    assert registry.health().code == "unreadable"
    assert [item.id for item in registry.list()] == ["default"]
    assert len(_warnings(caplog)) == 1


def test_repeated_probes_warn_only_once(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """同一句柄上反复 `health()` + `list()` 只出**一条** WARNING（实例级去重，不随请求数刷屏）。"""
    caplog.set_level(logging.WARNING)
    (tmp_path / "projects.json").write_text("{broken", encoding="utf-8")
    registry = _registry(tmp_path)

    for _ in range(3):
        assert registry.health().code == "unreadable"
        assert [item.id for item in registry.list()] == ["default"]
    assert len(_warnings(caplog)) == 1
