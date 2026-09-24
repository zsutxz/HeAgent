"""Story 50-4：只读配置端点的网络层契约（路由 / 错误码 / 协议模型镜像）。

网络层在这里必须保持「不认识配置」：分组、来源求解、凭证掩码都由注入的 console 提供
（脊柱 I1）。因此本文件用**假 console** 钉住传输契约，另加一条真 ``HttpProjectConsole`` 的端到端用例。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("starlette")

import httpx

from heagent.config import Settings
from heagent.config_catalog import (
    MAX_FILE_DIAGNOSTIC_KEYS,
    MAX_UNKNOWN_KEYS,
    ConfigGuard,
    ConfigItem,
    ConfigReport,
    ConfigSource,
    RoutingPoolView,
    RoutingPoolsReport,
)
from heagent.network.http_console_protocol import (
    MAX_CONFIG_FILE_DIAGNOSTIC_KEYS,
    MAX_CONFIG_UNKNOWN_KEYS,
    ConfigGroupResponse,
    ConfigGuardResponse,
    ConfigItemResponse,
    ConfigSourceValue,
    ConsoleOperationError,
    EnvFileStatusResponse,
    ProjectConfigResponse,
    RoutingPoolResponse,
    RoutingPoolsResponse,
    UnknownKeyResponse,
)
from heagent.network.http_protocol import HttpErrorCode
from heagent.network.http_server import HttpServerConfig, build_http_app

ENV_KEYS = frozenset(name.upper() for name in Settings.model_fields)


def _sample_item(*, secret: bool = False) -> ConfigItemResponse:
    return ConfigItemResponse(
        key="MAX_ITERATIONS",
        group="limits",
        value=None if secret else 50,
        source=ConfigSourceValue.DEFAULT,
        writable=not secret,
        read_only_reason="credential" if secret else None,
        is_secret=secret,
        configured=False,
        masked=None,
        guards=ConfigGuardResponse(kind="range", minimum=1.0),
        notes=(),
    )


def _sample_response() -> ProjectConfigResponse:
    return ProjectConfigResponse(
        project_id="default",
        field_count=len(Settings.model_fields),
        groups=(ConfigGroupResponse(id="limits", label="迭代与限额", items=(_sample_item(),)),),
        env_file=EnvFileStatusResponse(path="/tmp/.env", exists=True, readable=True, fingerprint="abc"),
        unknown_keys=(UnknownKeyResponse(key="UNKNOWN_X", source=ConfigSourceValue.PROJECT_ENV),),
        labels={"console_itself": "控制台自身开关"},
        notes=("project_env_missing",),
    )


class FakeConsole:
    """只实现配置端点的最小 console（传输层契约用）。"""

    def __init__(self, *, code: str | None = None, boom: bool = False) -> None:
        self.code = code
        self.boom = boom
        self.seen: list[str] = []

    async def get_project_config(self, project_id: str) -> ProjectConfigResponse:
        self.seen.append(project_id)
        if self.boom:
            raise RuntimeError("internal detail that must not leak")
        if self.code is not None:
            raise ConsoleOperationError(self.code, "project is not available")
        return _sample_response()


def _app(console=None, *, host: str = "127.0.0.1"):
    return build_http_app(HttpServerConfig(port=0, host=host), version="test", console=console)


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1")


# ── 协议模型镜像（两处常量 / 字段名必须一致） ──


def test_bounded_constants_mirror_the_catalog() -> None:
    assert MAX_CONFIG_UNKNOWN_KEYS == MAX_UNKNOWN_KEYS
    assert MAX_CONFIG_FILE_DIAGNOSTIC_KEYS == MAX_FILE_DIAGNOSTIC_KEYS


def test_protocol_models_mirror_the_domain_models() -> None:
    """协议模型不得出现域模型没有的字段（镜像一旦漂移，映射处的 ``model_validate`` 会炸）。"""
    assert set(ConfigItemResponse.model_fields) <= set(ConfigItem.model_fields)
    assert set(ConfigGuardResponse.model_fields) <= set(ConfigGuard.model_fields)
    assert set(EnvFileStatusResponse.model_fields) <= set(ConfigReport.model_fields["env_file"].annotation.model_fields)
    assert set(RoutingPoolResponse.model_fields) <= set(RoutingPoolView.model_fields)
    assert set(RoutingPoolsResponse.model_fields) <= set(RoutingPoolsReport.model_fields)
    assert {member.value for member in ConfigSourceValue} == {member.value for member in ConfigSource}


def test_sample_response_round_trips_through_the_domain_shape() -> None:
    """协议模型与域模型对同一份数据给出一致形状（``extra="forbid"`` 保证不会静默丢字段）。"""
    payload = _sample_response().model_dump(mode="json")
    assert ConfigItemResponse.model_validate(payload["groups"][0]["items"][0]).key == "MAX_ITERATIONS"
    assert ConfigGuardResponse.model_validate({"kind": "enum", "values": ["a"]}).values == ("a",)


# ── 路由 ──


async def test_config_route_is_absent_without_injected_handler() -> None:
    """I13：没注入 console 时不注册任何控制台路由（Epic 49 的用法不变）。"""
    async with _client(_app()) as client:
        response = await client.get("/api/projects/default/config")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == HttpErrorCode.NOT_FOUND


async def test_config_route_returns_the_console_payload() -> None:
    console = FakeConsole()
    async with _client(_app(console)) as client:
        response = await client.get("/api/projects/default/config")
    assert response.status_code == 200
    body = response.json()
    assert console.seen == ["default"]
    assert body["project_id"] == "default"
    assert body["groups"][0]["id"] == "limits"
    assert body["groups"][0]["items"][0]["key"] == "MAX_ITERATIONS"
    assert body["env_file"]["fingerprint"] == "abc"
    assert body["unknown_keys"][0]["key"] == "UNKNOWN_X"
    assert body["labels"]["console_itself"] == "控制台自身开关"
    assert body["notes"] == ["project_env_missing"]


async def test_config_route_passes_opaque_project_id_through() -> None:
    console = FakeConsole()
    async with _client(_app(console)) as client:
        response = await client.get("/api/projects/p3f7a1b2c/config")
    assert response.status_code == 200
    assert console.seen == ["p3f7a1b2c"]


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (HttpErrorCode.UNKNOWN_PROJECT, 404),
        (HttpErrorCode.PROJECT_UNAVAILABLE, 409),
    ],
)
async def test_config_route_maps_stable_codes(code: str, status: int) -> None:
    async with _client(_app(FakeConsole(code=code))) as client:
        response = await client.get("/api/projects/default/config")
    assert response.status_code == status
    assert response.json()["error"]["code"] == code


async def test_config_route_hides_unexpected_failures() -> None:
    async with _client(_app(FakeConsole(boom=True))) as client:
        response = await client.get("/api/projects/default/config")
    assert response.status_code == 500
    assert response.json()["error"]["code"] == HttpErrorCode.SERVER_ERROR
    assert "internal detail" not in response.text


async def test_config_route_rejects_wrong_method() -> None:
    async with _client(_app(FakeConsole())) as client:
        response = await client.post("/api/projects/default/config", json={})
    assert response.status_code == 405
    assert response.json()["error"]["code"] == HttpErrorCode.METHOD_NOT_ALLOWED


# ── 端到端：真入口层（真实 .env 求解 + 真路由） ──


async def test_real_console_serves_the_config_panel(tmp_path: Path) -> None:
    """真 ``HttpProjectConsole``：项目 ``.env`` 的键必须盖过全局层，凭证只回掩码。"""
    from heagent.cli_http import HttpProjectConsole

    marker = "sk-live-MARKER-abcdef"
    (tmp_path / ".env").write_bytes(f"MAX_ITERATIONS=321\nKIMI_API_KEY={marker}\nTOTALLY_UNKNOWN=1\n".encode())
    console = HttpProjectConsole(tmp_path)
    async with _client(_app(console)) as client:
        response = await client.get("/api/projects/default/config")
        missing = await client.get("/api/projects/nope/config")
    assert response.status_code == 200
    body = response.json()
    assert missing.status_code == 404 and missing.json()["error"]["code"] == HttpErrorCode.UNKNOWN_PROJECT
    assert body["field_count"] == len(Settings.model_fields)
    assert body["env_file"]["path"] == str(tmp_path / ".env")
    assert body["env_file"]["exists"] is True and body["env_file"]["fingerprint"]
    assert body["notes"] == []
    assert [entry["key"] for entry in body["unknown_keys"]] == ["TOTALLY_UNKNOWN"]
    flattened = {item["key"]: item for group in body["groups"] for item in group["items"]}
    assert set(flattened) == ENV_KEYS  # 字段集合固定，不随 .env 内容膨胀
    assert flattened["MAX_ITERATIONS"]["value"] == 321
    assert flattened["MAX_ITERATIONS"]["source"] == "project_env"
    assert flattened["KIMI_API_KEY"]["value"] is None
    assert flattened["KIMI_API_KEY"]["masked"] == "*" * 8
    assert flattened["KIMI_API_KEY"]["writable"] is False
    assert flattened["KIMI_API_KEY"]["read_only_reason"] == "credential"
    assert marker not in json.dumps(body, ensure_ascii=False)


async def test_real_console_reports_unavailable_project(tmp_path: Path) -> None:
    """项目目录被删 ⇒ ``project_unavailable``（409），而不是 500 或空面板。"""
    from heagent.cli_http import HttpProjectConsole

    workspace = tmp_path / "sub"
    workspace.mkdir()
    console = HttpProjectConsole(tmp_path)
    entry = console.registry.register(str(workspace), "Sub")
    workspace.rmdir()
    async with _client(_app(console)) as client:
        response = await client.get(f"/api/projects/{entry.id}/config")
    assert response.status_code == 409
    assert response.json()["error"]["code"] == HttpErrorCode.PROJECT_UNAVAILABLE


async def test_real_console_rejects_non_loopback_project_registration() -> None:
    """既有安全面未受影响（回归）：非回环来源登记项目仍被拒。"""
    from heagent.cli_http import HttpProjectConsole

    console = HttpProjectConsole(Path("."))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(console, host="10.0.0.4"), client=("10.0.0.2", 9000)),
        base_url="http://10.0.0.4",
    ) as client:
        response = await client.post("/api/projects", json={"path": "/tmp/x"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == HttpErrorCode.LOOPBACK_REQUIRED
