"""Story 49-5：HTTP 入口的同源防线与可观测性。

覆盖三条契约：

1. **同源防线（AD-6）**：Host 必须是本 listener（回环绑定时接受本机等价写法）；带 Origin 时必须
   同源；``Origin: null``、重复 Host、forwarded-* 头一律拒绝；被拒的**状态变更**不得产生副作用。
2. **可观测性（AD-9）**：请求/运行日志只有不透明 id、状态与耗时，**不含** prompt、回答或工具输出；
   响应带 ``x-request-id``。
3. **治理链（AD-7）**：网页运行仍走既有 `PolicyEngine` → `ToolExecutor` → `SafetyGuard`；
   需要审批的工具在无人应答的入口维持 fail-safe 阻断（不读服务进程 stdin）、不自动连 MCP。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import pytest

pytest.importorskip("starlette")

import httpx

from heagent.cli.http_console import HttpAgentHandler
from heagent.config import get_settings, reset_settings
from heagent.network.http_protocol import HttpErrorCode
from heagent.network.http_server import HttpRunService, HttpServerConfig, build_http_app
from heagent.providers.base import ProviderMetadata
from heagent.pub.types import Message, ProviderResponse, TokenUsage, ToolCall

_VERSION = "9.9.9"
_PORT = 8766
_PROMPT_MARKER = "PROMPT-MARKER-2f8a"
_ANSWER_MARKER = "ANSWER-MARKER-91b3"
_OUTPUT_MARKER = "OUTPUT-MARKER-77c1"


class _StubProvider:
    """按脚本应答的 provider（首个响应重复）；顺带记录**每次调用看到的完整消息**。"""

    def __init__(self, responses: list[ProviderResponse] | None = None) -> None:
        self._responses = responses or [_response(_ANSWER_MARKER)]
        self.seen: list[list[Message]] = []

    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        self.seen.append([message.model_copy(deep=True) for message in messages])
        return self._responses[0]

    async def stream(self, messages: list[Message], *, tools: list[object] | None = None) -> Any:
        self.seen.append([message.model_copy(deep=True) for message in messages])
        yield self._responses[0]

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


def _response(text: str) -> ProviderResponse:
    return ProviderResponse(
        content=text,
        usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        model="stub",
        finish_reason="stop",
    )


def _config(**overrides: Any) -> HttpServerConfig:
    return HttpServerConfig(**{"port": _PORT, **overrides})


@contextlib.asynccontextmanager
async def _client_with_service(
    provider: Any | None = None,
    *,
    config: HttpServerConfig | None = None,
) -> AsyncIterator[tuple[httpx.AsyncClient, HttpRunService]]:
    resolved = config or _config()
    handler = HttpAgentHandler(provider or _StubProvider(), get_settings())
    service = HttpRunService(resolved, handler)
    transport = httpx.ASGITransport(app=build_http_app(resolved, version=_VERSION, run_service=service))
    async with httpx.AsyncClient(transport=transport, base_url=f"http://127.0.0.1:{resolved.port}") as client:
        yield client, service


@contextlib.asynccontextmanager
async def _static_client(config: HttpServerConfig | None = None) -> AsyncIterator[httpx.AsyncClient]:
    """只有静态页与健康检查的形态（无运行服务）。"""
    resolved = config or _config()
    transport = httpx.ASGITransport(app=build_http_app(resolved, version=_VERSION))
    async with httpx.AsyncClient(transport=transport, base_url=f"http://127.0.0.1:{resolved.port}") as client:
        yield client


@pytest.fixture(autouse=True)
def _isolate_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.chdir(tmp_path)
    reset_settings()


class TestHostGuard:
    async def test_configured_host_is_accepted(self) -> None:
        async with _static_client() as client:
            response = await client.get("/api/health", headers={"host": f"127.0.0.1:{_PORT}"})

        assert response.status_code == 200

    @pytest.mark.parametrize("host", [f"localhost:{_PORT}", f"[::1]:{_PORT}"])
    async def test_loopback_aliases_are_accepted(self, host: str) -> None:
        """本机三个等价写法都指向同一 listener：拒绝其一会让「本机自用」失效。"""
        async with _static_client() as client:
            response = await client.get("/api/health", headers={"host": host})

        assert response.status_code == 200

    @pytest.mark.parametrize(
        "host",
        [
            "evil.example",  # DNS rebinding：域名解析到 127.0.0.1
            "evil.example:8766",
            f"127.0.0.1:{_PORT + 1}",  # 端口不符
            "127.0.0.1",  # 省略端口 ⇒ 按 http 默认 80 处理，不等于本 listener
        ],
    )
    async def test_foreign_hosts_are_rejected(self, host: str) -> None:
        async with _static_client() as client:
            response = await client.get("/api/health", headers={"host": host})

        assert response.status_code == 403
        assert response.json()["error"]["code"] == HttpErrorCode.ORIGIN_FORBIDDEN

    async def test_duplicated_host_header_is_rejected(self) -> None:
        async with _static_client() as client:
            response = await client.get(
                "/api/health",
                headers=[("host", f"127.0.0.1:{_PORT}"), ("host", "evil.example")],
            )

        assert response.status_code == 403

    @pytest.mark.parametrize(
        "header_name",
        ["x-forwarded-host", "x-forwarded-proto", "forwarded", "x-real-ip"],
    )
    async def test_forwarded_headers_are_rejected(self, header_name: str) -> None:
        """绝不信任代理头：出现即拒绝（否则「跨站请求」可以伪装成本机同源）。"""
        async with _static_client() as client:
            response = await client.get("/api/health", headers={header_name: "evil.example"})

        assert response.status_code == 403

    async def test_rejection_still_carries_security_headers_and_request_id(self) -> None:
        async with _static_client() as client:
            response = await client.get("/api/health", headers={"host": "evil.example"})

        assert response.headers["x-content-type-options"] == "nosniff"
        assert "default-src 'none'" in response.headers["content-security-policy"]
        assert response.headers["x-request-id"]

    async def test_rejection_message_does_not_leak_the_allowlist(self) -> None:
        async with _static_client() as client:
            response = await client.get("/api/health", headers={"host": "evil.example"})

        assert "127.0.0.1" not in response.text
        assert response.json()["error"]["message"] == "request origin rejected"


class TestOriginGuard:
    async def test_same_origin_state_change_is_accepted(self) -> None:
        async with _client_with_service() as (client, service):
            response = await client.post(
                "/api/runs",
                json={"prompt": "hi"},
                headers={"origin": f"http://127.0.0.1:{_PORT}"},
            )
            await client.get(f"/api/runs/{response.json()['run_id']}/events")

        assert response.status_code == 201
        assert service.active_runs == 0

    async def test_missing_origin_is_accepted_for_non_browser_clients(self) -> None:
        """curl / 脚本不带 Origin：Host 已校验，故按非浏览器客户端放行。"""
        async with _client_with_service() as (client, _service):
            response = await client.post("/api/runs", json={"prompt": "hi"})
            await client.get(f"/api/runs/{response.json()['run_id']}/events")

        assert response.status_code == 201

    @pytest.mark.parametrize("origin", ["null", "http://evil.example", f"https://127.0.0.1:{_PORT}"])
    async def test_foreign_or_null_origin_is_rejected(self, origin: str) -> None:
        async with _client_with_service() as (client, _service):
            response = await client.post("/api/runs", json={"prompt": "hi"}, headers={"origin": origin})

        assert response.status_code == 403
        assert response.json()["error"]["code"] == HttpErrorCode.ORIGIN_FORBIDDEN

    async def test_rejected_state_change_has_no_side_effects(self) -> None:
        """被拒的提交**不得**创建运行（AC：拒绝请求且不创建、取消或修改 Agent run）。"""
        async with _client_with_service() as (client, service):
            rejected = await client.post(
                "/api/runs",
                json={"prompt": _PROMPT_MARKER},
                headers={"origin": "http://evil.example"},
            )
            snapshot = (await client.get("/api/session")).json()

        assert rejected.status_code == 403
        assert service.active_runs == 0
        assert snapshot["run_id"] is None
        assert snapshot["messages"] == []

    async def test_rejected_cancel_does_not_touch_the_run(self) -> None:
        """被拒的 DELETE 不得取消运行（否则跨站就能停掉别人的运行）。"""
        gate = asyncio.Event()

        async def blocking(prompt: str, publisher: Any) -> Any:
            await gate.wait()

        async with _client_with_service(blocking) as (client, service):
            created = await client.post("/api/runs", json={"prompt": "slow"})
            run_id = created.json()["run_id"]
            rejected = await client.delete(f"/api/runs/{run_id}", headers={"origin": "http://evil.example"})
            record = service.run(run_id)

        assert rejected.status_code == 403
        assert record is not None and record.status == "running"
        gate.set()


class TestObservability:
    async def test_request_log_has_identifiers_and_no_content(self, caplog: pytest.LogCaptureFixture) -> None:
        async with _client_with_service() as (client, _service):
            with caplog.at_level(logging.INFO, logger="heagent.network.http_server"):
                response = await client.post("/api/runs", json={"prompt": _PROMPT_MARKER})
                await client.get(f"/api/runs/{response.json()['run_id']}/events")

        log_text = caplog.text
        assert "http event=request" in log_text
        assert "request_id=" in log_text
        assert "elapsed_ms=" in log_text
        assert "method=POST" in log_text and "path=/api/runs" in log_text
        # 请求日志只记元信息：提示词正文绝不进日志。
        assert _PROMPT_MARKER not in log_text
        assert _ANSWER_MARKER not in log_text

    async def test_run_logs_carry_status_and_elapsed_without_content(self, caplog: pytest.LogCaptureFixture) -> None:
        async with _client_with_service() as (client, _service):
            with caplog.at_level(logging.INFO, logger="heagent.network.http_server"):
                created = await client.post("/api/runs", json={"prompt": _PROMPT_MARKER})
                await client.get(f"/api/runs/{created.json()['run_id']}/events")

        log_text = caplog.text
        assert "http event=run_started" in log_text
        assert "http event=run_finished" in log_text
        assert "status=completed" in log_text
        assert _PROMPT_MARKER not in log_text
        assert _ANSWER_MARKER not in log_text

    async def test_tool_output_is_not_logged(self, caplog: pytest.LogCaptureFixture, tmp_path: Any) -> None:
        """工具**输出正文**不进日志（工具名与作用对象是诊断字段，内容不是）。

        Story 50-8 R5 起 ``file_read`` 的成功结果**在网页事件流里也被收敛**（只留作用对象），
        所以「输出确实存在」这一半改由 provider 侧证明：内容到达了模型，但既不在日志里、
        也不在网页帧里。
        """
        target = tmp_path / "note.txt"
        target.write_text(_OUTPUT_MARKER, encoding="utf-8")
        provider = _StubProvider(
            [
                ProviderResponse(
                    content="",
                    tool_calls=[ToolCall(id="call-1", name="file_read", arguments={"path": str(target)})],
                    usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                    model="stub",
                    finish_reason="tool_calls",
                ),
                _response(_ANSWER_MARKER),
            ]
        )
        async with _client_with_service(provider) as (client, _service):
            with caplog.at_level(logging.DEBUG):
                created = await client.post("/api/runs", json={"prompt": _PROMPT_MARKER})
                events = await client.get(f"/api/runs/{created.json()['run_id']}/events")

        assert _OUTPUT_MARKER not in caplog.text  # 日志里不该出现
        assert _OUTPUT_MARKER not in events.text  # R5：网页事件流也不携带读取内容
        assert any(  # 但模型确实拿到了全文（否则是功能回归，不是隐私收益）
            _OUTPUT_MARKER in (message.content or "") for call in provider.seen for message in call
        ), "读取内容必须仍然到达模型"

    async def test_request_id_header_is_present_and_unique(self) -> None:
        async with _static_client() as client:
            first = await client.get("/api/health")
            second = await client.get("/api/health")

        assert first.headers["x-request-id"]
        assert first.headers["x-request-id"] != second.headers["x-request-id"]


class TestGovernanceChain:
    async def test_approval_required_tool_is_fail_safe_blocked(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        """需要审批的工具在网页入口**阻断**（无 stdin 审批处理器，fail-safe 方向）。"""
        monkeypatch.setenv("APPROVAL_TOOLS", "file_write")
        reset_settings()
        target = tmp_path / "written.txt"
        provider = _StubProvider(
            [
                ProviderResponse(
                    content="",
                    tool_calls=[
                        ToolCall(
                            id="call-1",
                            name="file_write",
                            arguments={"path": str(target), "content": "should not be written"},
                        )
                    ],
                    usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                    model="stub",
                    finish_reason="tool_calls",
                ),
                _response(_ANSWER_MARKER),
            ]
        )
        async with _client_with_service(provider) as (client, _service):
            created = await client.post("/api/runs", json={"prompt": "write a file"})
            events = await client.get(f"/api/runs/{created.json()['run_id']}/events")

        assert not target.exists(), "审批型工具在无人应答的入口必须 fail-safe 阻断"
        assert '"tool_error":true' in events.text

    async def test_handler_does_not_install_a_stdin_approval_handler(self) -> None:
        async with _client_with_service() as (_client, service):
            handler = service._executor  # noqa: SLF001 - 直接核对注入的入口对象

        assert handler.engine.approval_handler is None

    async def test_handler_does_not_connect_mcp_servers(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
        """HTTP 入口不得构造 MCP 生命周期。

        旧的写法打桩 ``console._mcp_lifecycle``——HTTP 路径根本不会调用它，所以那条断言**恒真**、
        什么都证明不了。这里改为打桩真正被构造的类 ``MCPClientManager.__init__``，并先用 CLI 侧
        的生命周期做**正面控制**（证明该缝隙是活的），再断言一次 HTTP 运行从未碰到它。
        """
        from heagent.cli import console
        from heagent.tools.mcp import MCPClientManager

        constructed: list[str] = []
        original_init = MCPClientManager.__init__

        def _spy(manager: Any, *args: Any, **kwargs: Any) -> None:
            constructed.append("mcp")
            original_init(manager, *args, **kwargs)

        monkeypatch.setattr(MCPClientManager, "__init__", _spy)

        # 正面控制：同样的 patch 下，配置非空时 CLI 的 MCP 生命周期确实会构造 manager。
        config_path = tmp_path / ".mcp.json"
        config_path.write_text(
            json.dumps({"mcpServers": {"local": {"command": "python", "args": ["-m", "srv"]}}}),
            encoding="utf-8",
        )
        monkeypatch.setenv("MCP_ENABLED", "true")
        monkeypatch.setenv("MCP_CONFIG_PATH", str(config_path))
        reset_settings()
        console._mcp_lifecycle(get_settings())
        assert constructed == ["mcp"], "正面控制失败：该缝隙没有被 CLI 路径触达"

        constructed.clear()
        async with _client_with_service() as (client, _service):
            created = await client.post("/api/runs", json={"prompt": "hi"})
            await client.get(f"/api/runs/{created.json()['run_id']}/events")

        assert created.status_code == 201
        assert constructed == [], "HTTP 入口不得构造 MCP 生命周期"
