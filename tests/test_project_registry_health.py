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


def test_a_second_outage_after_recovery_warns_again(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """去重只压同一段故障期：注册表修好后再坏必须**再响一次**，否则同句柄上的第二次故障永久静默。"""
    caplog.set_level(logging.WARNING)
    path = tmp_path / "projects.json"
    path.write_text("{broken", encoding="utf-8")
    registry = _registry(tmp_path)

    assert registry.health().code == "unreadable"
    assert len(_warnings(caplog)) == 1

    path.write_text("[]", encoding="utf-8")  # 运维修好
    assert registry.health().code == "ok"

    path.write_text("{broken again", encoding="utf-8")  # 又坏一次
    assert registry.health().code == "unreadable"
    assert len(_warnings(caplog)) == 2


def _too_many(count: int) -> str:
    return json.dumps(
        [{"id": f"p{index:08d}", "name": f"p{index}", "path": f"/tmp/p{index}"} for index in range(count)],
        ensure_ascii=False,
    )


def test_a_full_registry_is_unreadable_instead_of_overflowing_the_frame(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """恰 `MAX_PROJECTS` 条登记（= 上限 + default 会变 33）判不可读，而不是让 `list()` 回 33 条。

    登记上限是 `MAX_PROJECTS - 1`（`register()` 的判定同源）：手改成 32 条时宁可整表 fail-soft
    回 `default` 一条 + 一条 WARNING，也不要把 33 条交给 `ProjectListResponse(max_length=32)`——
    那会让 `projects` 命令回 `server_error` 并断连，客户端拿不到任何可用项目。
    """
    caplog.set_level(logging.WARNING)
    path = tmp_path / "projects.json"
    path.write_text(_too_many(MAX_PROJECTS), encoding="utf-8")
    registry = _registry(tmp_path)

    assert registry.health().code == "unreadable"
    assert [item.id for item in registry.list()] == ["default"]  # 不会溢出成 33 条
    assert len(_warnings(caplog)) == 1


def test_non_utf8_registry_reports_a_path_free_detail(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """非 UTF-8 字节（读径抛 `UnicodeError`）：判不可读，`detail` 只说是编码问题、不回显路径。"""
    caplog.set_level(logging.WARNING)
    (tmp_path / "projects.json").write_bytes(b"\xff\xfe\x00bad")
    registry = _registry(tmp_path)

    health = registry.health()

    assert health.code == "unreadable"
    assert health.detail == "registry file is not valid UTF-8 text"
    assert str(tmp_path) not in health.detail


def test_schema_mismatch_reports_a_schema_detail(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """条目字段不合规（`ValidationError`）：`detail` 折叠成一句 schema 不符，不带出条目字段值。"""
    caplog.set_level(logging.WARNING)
    (tmp_path / "projects.json").write_text(json.dumps([{"id": "p1", "name": "缺 path"}]), encoding="utf-8")
    registry = _registry(tmp_path)

    health = registry.health()

    assert health.code == "unreadable"
    assert health.detail == "registry entries do not match the expected schema"


def test_deleting_the_corrupt_file_also_rearms_the_warning(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """删掉坏表（`app.js` 明示的运维动作）同样算恢复：之后再坏必须**再响一次**。"""
    caplog.set_level(logging.WARNING)
    path = tmp_path / "projects.json"
    path.write_text("{broken", encoding="utf-8")
    registry = _registry(tmp_path)

    assert registry.health().code == "unreadable"
    assert len(_warnings(caplog)) == 1

    path.unlink()  # 运维修法之二：删掉坏表
    assert registry.health().code == "ok"

    path.write_text("{broken again", encoding="utf-8")
    assert registry.health().code == "unreadable"
    assert len(_warnings(caplog)) == 2
