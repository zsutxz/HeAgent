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
    MAX_CONFIG_FINGERPRINT_CHARS,
    MAX_CONFIG_KEY_CHARS,
    MAX_CONFIG_UNKNOWN_KEYS,
    MAX_CONFIG_VALUE_CHARS,
    MAX_CONFIG_WRITE_CHANGES,
    ConfigGroupResponse,
    ConfigGuardResponse,
    ConfigItemResponse,
    ConfigSourceValue,
    ConfigWriteChangeRequest,
    ConfigWriteRequest,
    ConfigWriteResponse,
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

FINGERPRINT = "a" * 64


def envfile_fingerprint(raw: bytes) -> str:
    """项目 ``.env`` 的内容指纹（与面板 ``env_file.fingerprint`` 同一算法）。"""
    import hashlib

    return hashlib.sha256(raw).hexdigest()


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
        write_enabled=True,
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


def test_write_bounds_mirror_the_write_channel() -> None:
    """写入通道的上界两边必须一致（网络层不得 import 顶层写通道模块，故只能镜像 + 钉住）。"""
    from heagent import envfile
    from heagent.config_write import MAX_CONFIG_WRITE_CHANGES as CHANNEL_MAX_CHANGES

    assert MAX_CONFIG_WRITE_CHANGES == CHANNEL_MAX_CHANGES
    assert MAX_CONFIG_KEY_CHARS == envfile.MAX_KEY_CHARS
    assert MAX_CONFIG_VALUE_CHARS == envfile.MAX_VALUE_CHARS
    assert MAX_CONFIG_FINGERPRINT_CHARS >= 64  # sha256 十六进制必然放得下
    assert MAX_CONFIG_WRITE_CHANGES >= 1


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
    assert body["write_enabled"] is True  # 闸门状态随面板一起回（AC5 的判据，见 50-6）
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
    from heagent.cli.http import HttpProjectConsole

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


async def test_panel_reports_the_write_gate_so_the_ui_can_disable_editing(tmp_path: Path) -> None:
    """AC5（Story 50-6）：闸门关着时**面板自己**要说得出来，UI 不必靠「写一次被拒」才能发现。

    闸门关闭时条目上的 ``writable`` 仍是「白名单 + 非系统环境变量」的判定结果（``True``）——UI 只看
    ``writable`` 会显示「可编辑、保存必被拒」。``write_enabled`` 必须与入口层真正执行 PUT 时判的那个
    闸门**同一事实源**（这里直接与方法上的属性比对，而不是与一个字面量比对）。
    """
    from heagent.cli.http import HttpProjectConsole

    (tmp_path / ".env").write_bytes(b"MAX_ITERATIONS=25\n")
    closed = HttpProjectConsole(tmp_path, global_env_file=None)
    opened = HttpProjectConsole(tmp_path, write_enabled=True, global_env_file=None)

    async with _client(_app(closed)) as client:
        closed_body = (await client.get("/api/projects/default/config")).json()
    async with _client(_app(opened)) as client:
        opened_body = (await client.get("/api/projects/default/config")).json()

    assert closed_body["write_enabled"] is closed.write_enabled is False
    assert opened_body["write_enabled"] is opened.write_enabled is True

    def item(body: dict, key: str) -> dict:
        return {entry["key"]: entry for group in body["groups"] for entry in group["items"]}[key]

    # 两种情况下的白名单项都可写 ⇒ 区分「能否编辑」的只有 write_enabled，面板文案由后端给。
    assert item(closed_body, "MAX_ITERATIONS")["writable"] is True
    assert item(opened_body, "MAX_ITERATIONS")["writable"] is True
    assert closed_body["labels"]["write_channel_disabled"].strip()


async def test_panel_shows_the_resource_knob_ceilings(tmp_path: Path) -> None:
    """缺口闭合（只读侧）：面板展示的守卫必须与写入通道**同一常量** —— 逐条覆盖整张上界表。

    面板是用户「这里该填多少」的唯一提示来源，所以上界一落进 ``config_catalog.RESOURCE_CEILINGS`` 就必须
    自己出现在 ``guards`` 里 —— 前端不硬编码任何边界（``app.js::guardHint`` 只渲染后端给的结构）。
    遍历常量表本体而不是在测试里抄几个键：新增上界自动纳入（面板漏传会立刻红）。
    """
    from heagent.cli.http import HttpProjectConsole
    from heagent.config_catalog import RESOURCE_CEILINGS

    (tmp_path / ".env").write_bytes(b"MAX_ITERATIONS=25\n")
    console = HttpProjectConsole(tmp_path, global_env_file=None)
    async with _client(_app(console)) as client:
        body = (await client.get("/api/projects/default/config")).json()

    items = {entry["key"]: entry for group in body["groups"] for entry in group["items"]}
    for key, ceiling in RESOURCE_CEILINGS.items():
        guard = items[key]["guards"]
        assert guard["kind"] == "range", key
        assert guard["maximum"] == ceiling, key
    guard = items["MAX_ITERATIONS"]["guards"]
    assert guard["minimum"] == 1.0  # 字段元数据派生的下界仍在
    assert items["MAX_ITERATIONS"]["guards"]["maximum"] == 10_000.0
    assert items["MAX_CONTEXT_TOKENS"]["guards"]["maximum"] == 16_000_000.0


async def test_real_console_reports_unavailable_project(tmp_path: Path) -> None:
    """项目目录被删 ⇒ ``project_unavailable``（409），而不是 500 或空面板。"""
    from heagent.cli.http import HttpProjectConsole

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
    from heagent.cli.http import HttpProjectConsole

    console = HttpProjectConsole(Path("."))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=_app(console, host="10.0.0.4"), client=("10.0.0.2", 9000)),
        base_url="http://10.0.0.4",
    ) as client:
        response = await client.post("/api/projects", json={"path": "/tmp/x"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == HttpErrorCode.LOOPBACK_REQUIRED


# ── PUT /api/projects/{id}/config（Story 50-5 的传输契约） ──


class FakeWriteConsole:
    """实现写入端点的最小 console（传输层契约用；真正的流水线在 ``tests/test_config_write.py``）。"""

    def __init__(self, *, code: str | None = None, boom: bool = False) -> None:
        self.code = code
        self.boom = boom
        self.seen: list[tuple[str, dict[str, object]]] = []

    async def update_project_config(self, project_id: str, request: ConfigWriteRequest) -> ConfigWriteResponse:
        self.seen.append((project_id, request.model_dump(mode="json")))
        if self.boom:
            raise RuntimeError("internal detail that must not leak")
        if self.code is not None:
            raise ConsoleOperationError(self.code, "write channel refused the change")
        return ConfigWriteResponse(
            project_id=project_id,
            fingerprint="f" * 64,
            backup="env-20260924T164712123456Z-abcdef01.bak",
            audit_recorded=False,
            changes=(_sample_item(),),
            notes=("audit_not_recorded",),
            labels={"audit_not_recorded": "写入已生效，但审计记录未能落盘"},
        )


def _write_app(console=None, *, host: str = "127.0.0.1"):
    return build_http_app(HttpServerConfig(port=0, host=host), version="test", console=console)


def _non_loopback_client(app):
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=("10.0.0.2", 9000)), base_url="http://10.0.0.4"
    )


async def test_write_route_is_absent_without_injected_handler() -> None:
    async with _client(_write_app()) as client:
        response = await client.put(
            "/api/projects/default/config", json={"changes": [{"key": "MAX_ITERATIONS", "value": "30"}]}
        )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == HttpErrorCode.NOT_FOUND


async def test_write_route_passes_the_parsed_request_and_id() -> None:
    console = FakeWriteConsole()
    async with _client(_write_app(console)) as client:
        response = await client.put(
            "/api/projects/p3f7a1b2c/config",
            json={
                "changes": [{"key": "max_iterations", "value": "30"}, {"key": "LOG_LEVEL", "value": "DEBUG"}],
                "fingerprint": FINGERPRINT,
            },
        )

    assert response.status_code == 200
    project_id, payload = console.seen[0]
    assert project_id == "p3f7a1b2c"  # 项目 id 对网络层始终不透明
    assert payload["changes"] == [
        {"key": "MAX_ITERATIONS", "value": "30"},  # 键归一化为大写
        {"key": "LOG_LEVEL", "value": "DEBUG"},
    ]
    assert payload["fingerprint"] == FINGERPRINT
    body = response.json()
    assert body["fingerprint"] == "f" * 64
    assert body["applied"] == "next_run"  # I10：不得声称立即生效
    assert body["backup"].endswith(".bak")
    assert body["audit_recorded"] is False
    assert body["notes"] == ["audit_not_recorded"]  # 审计没落盘必须显式可见
    assert body["labels"]["audit_not_recorded"]
    assert body["changes"][0]["key"] == "MAX_ITERATIONS"


async def test_write_route_can_omit_the_fingerprint() -> None:
    """指纹缺省 = 「客户端认为文件不存在」；传输层不替它做冲突判定（那是流水线第 5 步）。"""
    console = FakeWriteConsole()
    async with _client(_write_app(console)) as client:
        response = await client.put("/api/projects/default/config", json={"changes": [{"key": "A_KEY", "value": "1"}]})

    assert response.status_code == 200
    assert console.seen[0][1]["fingerprint"] is None


async def test_write_route_requires_a_loopback_client() -> None:
    """AC10：非回环来源一律 403，且**根本不会调到 console**（⇒ 文件 / 备份 / 审计都不会变）。"""
    console = FakeWriteConsole()
    async with _non_loopback_client(_write_app(console, host="10.0.0.4")) as client:
        response = await client.put(
            "/api/projects/default/config", json={"changes": [{"key": "MAX_ITERATIONS", "value": "30"}]}
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == HttpErrorCode.LOOPBACK_REQUIRED
    assert console.seen == []


@pytest.mark.parametrize(
    ("code", "status"),
    [
        (HttpErrorCode.WRITE_DISABLED, 403),
        (HttpErrorCode.FIELD_NOT_WRITABLE, 400),
        (HttpErrorCode.INVALID_VALUE, 400),
        (HttpErrorCode.CONFIG_CONFLICT, 409),
        (HttpErrorCode.CONFIG_WRITE_FAILED, 500),
        (HttpErrorCode.UNKNOWN_PROJECT, 404),
        (HttpErrorCode.PROJECT_UNAVAILABLE, 409),
    ],
)
async def test_write_route_maps_stable_codes(code: str, status: int) -> None:
    async with _client(_write_app(FakeWriteConsole(code=code))) as client:
        response = await client.put(
            "/api/projects/default/config", json={"changes": [{"key": "MAX_ITERATIONS", "value": "30"}]}
        )

    assert response.status_code == status
    assert response.json()["error"]["code"] == code


async def test_write_route_hides_unexpected_failures() -> None:
    async with _client(_write_app(FakeWriteConsole(boom=True))) as client:
        response = await client.put(
            "/api/projects/default/config", json={"changes": [{"key": "MAX_ITERATIONS", "value": "30"}]}
        )

    assert response.status_code == 500
    assert response.json()["error"]["code"] == HttpErrorCode.SERVER_ERROR
    assert "internal detail" not in response.text


@pytest.mark.parametrize(
    "payload",
    [
        {},  # 缺 changes
        {"changes": []},  # 空批次
        {"changes": [{"key": "MAX_ITERATIONS", "value": "30"}], "extra": 1},  # 未知字段（extra=forbid）
        {"changes": [{"key": "MAX_ITERATIONS", "value": 30}]},  # 值必须是字符串（.env 是文本）
        {"changes": [{"key": "A", "value": "1"}, {"key": "A", "value": "2"}]},  # 同批重复键
        {"changes": [{"key": "", "value": "1"}]},  # 空键
        {"changes": [{"key": "A" * (MAX_CONFIG_KEY_CHARS + 1), "value": "1"}]},
        {"changes": [{"key": "A", "value": "x" * (MAX_CONFIG_VALUE_CHARS + 1)}]},
        {"changes": [{"key": "A", "value": "1"}], "fingerprint": "x" * (MAX_CONFIG_FINGERPRINT_CHARS + 1)},
        {"changes": [{"key": f"K{i}", "value": "1"} for i in range(MAX_CONFIG_WRITE_CHANGES + 1)]},  # 超批量上限
    ],
)
async def test_write_route_rejects_malformed_bodies(payload: object) -> None:
    console = FakeWriteConsole()
    async with _client(_write_app(console)) as client:
        response = await client.put("/api/projects/default/config", json=payload)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == HttpErrorCode.INVALID_REQUEST
    assert console.seen == []  # 传输层挡下的请求不进 console


async def test_write_route_rejects_wrong_method_on_the_same_path() -> None:
    """同一路径上 GET（面板）/ PUT（写入）共存：POST 仍是 405（回归）。"""
    async with _client(_write_app(FakeWriteConsole())) as client:
        response = await client.post("/api/projects/default/config", json={})
    assert response.status_code == 405
    assert response.json()["error"]["code"] == HttpErrorCode.METHOD_NOT_ALLOWED


class TestWriteRequestModel:
    def test_key_is_stripped_and_uppercased(self) -> None:
        request = ConfigWriteRequest(changes=[ConfigWriteChangeRequest(key=" max_iterations ", value="30")])
        assert request.changes[0].key == "MAX_ITERATIONS"

    def test_value_is_not_normalised(self) -> None:
        request = ConfigWriteRequest(changes=[ConfigWriteChangeRequest(key="DEFAULT_MODEL", value=" gpt-4o ")])
        assert request.changes[0].value == " gpt-4o "

    def test_duplicate_keys_are_rejected(self) -> None:
        with pytest.raises(Exception, match="duplicate key"):
            ConfigWriteRequest(changes=[ConfigWriteChangeRequest(key="A", value="1")] * 2)


# ── 端到端：真入口层（真流水线 + 真路由） ──


async def test_real_console_refuses_writes_while_the_gate_is_closed(tmp_path: Path) -> None:
    """AC1：默认（``HTTP_CONSOLE_WRITE_ENABLED`` 未开）任何写入都是 ``write_disabled``，文件不变。"""
    from heagent.cli.http import HttpProjectConsole

    raw = b"MAX_ITERATIONS=25\n"
    (tmp_path / ".env").write_bytes(raw)
    console = HttpProjectConsole(tmp_path, global_env_file=None)
    async with _client(_app(console)) as client:
        response = await client.put(
            "/api/projects/default/config", json={"changes": [{"key": "MAX_ITERATIONS", "value": "30"}]}
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == HttpErrorCode.WRITE_DISABLED
    assert (tmp_path / ".env").read_bytes() == raw
    assert not (tmp_path / ".heagent").exists()  # 连状态目录都没建


async def test_real_console_writes_when_the_gate_is_open(tmp_path: Path) -> None:
    """端到端：指纹 → 保真写 → 备份 → 审计 → 响应含新指纹与新来源（AC2/AC3/AC7）。"""
    from heagent import envfile
    from heagent.cli.http import HttpProjectConsole

    raw = b"# project\r\nMAX_ITERATIONS=25\r\n"
    (tmp_path / ".env").write_bytes(raw)
    console = HttpProjectConsole(tmp_path, write_enabled=True, global_env_file=None)
    async with _client(_app(console)) as client:
        panel = await client.get("/api/projects/default/config")
        fingerprint = panel.json()["env_file"]["fingerprint"]
        response = await client.put(
            "/api/projects/default/config",
            json={"changes": [{"key": "MAX_ITERATIONS", "value": "30"}], "fingerprint": fingerprint},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    written = (tmp_path / ".env").read_bytes()
    assert written == b"# project\r\nMAX_ITERATIONS=30\r\n"  # 只有目标行变了
    assert body["fingerprint"] == envfile.fingerprint(written)
    assert body["changes"][0]["key"] == "MAX_ITERATIONS"
    assert body["changes"][0]["value"] == 30  # 写后条目取自面板同源求解（类型化）
    assert body["changes"][0]["source"] == "project_env"
    assert body["changes"][0]["writable"] is True
    assert body["audit_recorded"] is True and body["notes"] == []
    assert (tmp_path / ".heagent" / "backups" / body["backup"]).read_bytes() == raw
    assert (tmp_path / ".heagent" / "console" / "audit.jsonl").read_text(encoding="utf-8").strip()


async def test_real_console_has_no_side_effects_for_non_loopback_clients(tmp_path: Path) -> None:
    """AC10 的端到端版本：非回环 + 闸门开 —— 文件 / 备份 / 审计三者都不变。"""
    from heagent.cli.http import HttpProjectConsole

    raw = b"MAX_ITERATIONS=25\n"
    (tmp_path / ".env").write_bytes(raw)
    console = HttpProjectConsole(tmp_path, write_enabled=True, global_env_file=None)
    async with _non_loopback_client(_write_app(console, host="10.0.0.4")) as client:
        response = await client.put(
            "/api/projects/default/config", json={"changes": [{"key": "MAX_ITERATIONS", "value": "30"}]}
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == HttpErrorCode.LOOPBACK_REQUIRED
    assert (tmp_path / ".env").read_bytes() == raw
    assert not (tmp_path / ".heagent").exists()


async def test_real_console_conflict_keeps_the_other_editors_change(tmp_path: Path) -> None:
    """AC6：指纹过期 → 409 ``config_conflict``，**不覆盖**对方的修改。"""
    from heagent.cli.http import HttpProjectConsole

    (tmp_path / ".env").write_bytes(b"MAX_ITERATIONS=25\n")
    console = HttpProjectConsole(tmp_path, write_enabled=True, global_env_file=None)
    async with _client(_app(console)) as client:
        response = await client.put(
            "/api/projects/default/config",
            json={"changes": [{"key": "MAX_ITERATIONS", "value": "30"}], "fingerprint": "0" * 64},
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == HttpErrorCode.CONFIG_CONFLICT
    assert (tmp_path / ".env").read_bytes() == b"MAX_ITERATIONS=25\n"


async def test_real_console_refuses_read_only_keys(tmp_path: Path) -> None:
    """AC4：白名单之外的键由入口层（而非 UI）拒绝，文件不变。"""
    from heagent.cli.http import HttpProjectConsole

    (tmp_path / ".env").write_bytes(b"MAX_ITERATIONS=25\n")
    console = HttpProjectConsole(tmp_path, write_enabled=True, global_env_file=None)
    async with _client(_app(console)) as client:
        panel = await client.get("/api/projects/default/config")
        fingerprint = panel.json()["env_file"]["fingerprint"]
        response = await client.put(
            "/api/projects/default/config",
            json={"changes": [{"key": "KIMI_API_KEY", "value": "sk-x"}], "fingerprint": fingerprint},
        )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == HttpErrorCode.FIELD_NOT_WRITABLE
    assert "credential" in response.json()["error"]["message"]
    assert b"sk-x" not in (tmp_path / ".env").read_bytes()
    assert (tmp_path / ".env").read_bytes() == b"MAX_ITERATIONS=25\n"


async def test_real_panel_marks_the_write_switch_itself_read_only(tmp_path: Path) -> None:
    """I12 的端到端版本：连**开启时**，面板也把 ``HTTP_CONSOLE_*`` 标成只读并给出原因（无法自我解锁）。"""
    from heagent.cli.http import HttpProjectConsole

    console = HttpProjectConsole(tmp_path, write_enabled=True, global_env_file=None)
    async with _client(_app(console)) as client:
        panel = await client.get("/api/projects/default/config")

    items = {item["key"]: item for group in panel.json()["groups"] for item in group["items"]}
    for key in ("HTTP_CONSOLE_WRITE_ENABLED", "HTTP_CONSOLE_PROJECTS_FILE"):
        assert items[key]["writable"] is False
        assert items[key]["read_only_reason"] == "console_itself"
        assert panel.json()["labels"]["console_itself"]


async def test_no_endpoint_serves_backups_or_the_audit_log(tmp_path: Path) -> None:
    """AC7：备份「不提供任何网页下载端点」。审计同理——两者都在内部状态读拒集合内。"""
    from heagent.cli.http import HttpProjectConsole

    raw = b"MAX_ITERATIONS=25\n"
    (tmp_path / ".env").write_bytes(raw)
    console = HttpProjectConsole(tmp_path, write_enabled=True, global_env_file=None)
    async with _client(_app(console)) as client:
        written = await client.put(
            "/api/projects/default/config",
            json={
                "changes": [{"key": "MAX_ITERATIONS", "value": "30"}],
                "fingerprint": envfile_fingerprint(raw),
            },
        )
        backup_name = written.json()["backup"]
        probes = [
            f"/.heagent/backups/{backup_name}",
            "/.heagent/backups/",
            "/.heagent/console/audit.jsonl",
            f"/api/projects/default/backups/{backup_name}",
        ]
        responses = [await client.get(path) for path in probes]

    assert backup_name.endswith(".bak")
    for response in responses:
        assert response.status_code == 404
        assert response.json()["error"]["code"] == HttpErrorCode.NOT_FOUND
