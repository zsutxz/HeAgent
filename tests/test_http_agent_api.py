"""HTTP 运行 API 端到端（Epic 49 Story 49-3）：真实 uvicorn + 真实 AgentLoop + StubProvider。

与 ``tests/network/test_http_run_service.py``（假 executor、ASGI transport）的分工：这里验证
**入口层的适配**——``HttpAgentHandler`` 把 ``AgentLoop.run_stream`` 映射成协议事件、每运行独立 loop、
不装审批处理器、不连 MCP，且真的绑定端口接受请求。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

pytest.importorskip("starlette")

import httpx

from heagent.cli_http import HttpAgentHandler
from heagent.config import get_settings, reset_settings
from heagent.exceptions import HeAgentError
from heagent.network.http_server import HttpRunService, HttpServer, HttpServerConfig
from heagent.providers.base import ProviderMetadata
from heagent.types import Message, ProviderResponse, TokenUsage, ToolCall


def _answer(text: str, *, model: str = "stub-1", total: int = 5) -> ProviderResponse:
    return ProviderResponse(
        content=text,
        usage=TokenUsage(prompt_tokens=2, completion_tokens=3, total_tokens=total),
        model=model,
        finish_reason="stop",
    )


def _tool_request(name: str, arguments: dict[str, Any]) -> ProviderResponse:
    return ProviderResponse(
        content="",
        tool_calls=[ToolCall(id="call-1", name=name, arguments=arguments)],
        usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        model="stub-1",
        finish_reason="tool_calls",
    )


class _ScriptedProvider:
    """按脚本应答：第 N 次调用返回第 N 项（``BaseException`` 则抛出），末项重复。"""

    def __init__(self, script: list[Any]) -> None:
        self._script = script
        self.calls = 0

    def _next(self) -> Any:
        item = self._script[min(self.calls, len(self._script) - 1)]
        self.calls += 1
        if isinstance(item, BaseException):
            raise item
        if callable(item):
            return item(self.calls)
        return item

    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        return self._next()

    async def stream(self, messages: list[Message], *, tools: list[object] | None = None) -> Any:
        yield self._next()

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


@contextlib.asynccontextmanager
async def _served(provider: Any, **config_overrides: Any) -> AsyncIterator[tuple[str, HttpRunService]]:
    """起一个真实 listener（随机端口）+ 真实 ``HttpAgentHandler``，退出时关闭。"""
    config = HttpServerConfig(**{"port": 0, **config_overrides})
    handler = HttpAgentHandler(provider, get_settings())
    service = HttpRunService(config, handler)
    server = HttpServer(config, version="9.9.9", run_service=service)
    await server.start()
    task = asyncio.create_task(server.serve_forever())
    try:
        yield f"http://127.0.0.1:{server.port}", service
    finally:
        await server.close()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(task, timeout=5)


def _parse_sse(body: str) -> list[tuple[int, str, dict[str, Any]]]:
    frames: list[tuple[int, str, dict[str, Any]]] = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        fields = {}
        for line in block.splitlines():
            if ": " in line:
                key, value = line.split(": ", 1)
                fields[key] = value
        frames.append((int(fields["id"]), fields["event"], json.loads(fields["data"])))
    return frames


async def _run_prompt(client: httpx.AsyncClient, base_url: str, prompt: str) -> list[tuple[int, str, dict[str, Any]]]:
    created = await client.post(f"{base_url}/api/runs", json={"prompt": prompt})
    assert created.status_code == 201, created.text
    run_id = created.json()["run_id"]
    events = await client.get(f"{base_url}/api/runs/{run_id}/events")
    assert events.status_code == 200, events.text
    return _parse_sse(events.text)


@pytest.fixture(autouse=True)
def _isolate_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    """在 tmp 目录里跑：引擎的 ledger / 会话 / 日志都相对 cwd（不污染仓库）。"""
    monkeypatch.chdir(tmp_path)
    reset_settings()


async def test_end_to_end_run_streams_answer_and_updates_session() -> None:
    provider = _ScriptedProvider([_answer("hello from stub")])
    async with _served(provider) as (base_url, _service), httpx.AsyncClient(timeout=10.0) as client:
        frames = await _run_prompt(client, base_url, "hi there")
        snapshot = (await client.get(f"{base_url}/api/session")).json()

    assert [event for _id, event, _data in frames] == ["text", "done"]
    assert frames[-1][2]["text"] == "hello from stub"
    assert frames[-1][2]["model"] == "stub-1"
    assert snapshot["status"] == "completed"
    assert snapshot["messages"] == [
        {"role": "user", "text": "hi there"},
        {"role": "assistant", "text": "hello from stub"},
    ]
    assert provider.calls == 1


async def test_real_loop_streams_tool_events() -> None:
    """真实循环的工具事件：``tool_call`` → ``tool_result`` → 最终答案。"""
    provider = _ScriptedProvider(
        [
            _tool_request("file_read", {"path": "pyproject.toml"}),
            _answer("read it"),
        ]
    )
    async with _served(provider) as (base_url, _service), httpx.AsyncClient(timeout=10.0) as client:
        frames = await _run_prompt(client, base_url, "read the project file")

    kinds = [event for _id, event, _data in frames]
    assert kinds == ["tool_call", "tool_result", "text", "done"]
    tool_call = frames[0][2]
    assert tool_call["tool_name"] == "file_read"
    assert "pyproject.toml" in tool_call["tool_target"]
    assert frames[1][2]["tool_error"] is False
    assert frames[-1][2]["text"] == "read it"


async def test_unknown_tool_comes_back_as_a_failed_tool_result() -> None:
    """工具执行仍走治理链：不存在的工具由执行器给出 ``is_error`` 结果，而不是让 run 崩掉。"""
    provider = _ScriptedProvider([_tool_request("definitely_not_a_tool", {}), _answer("done")])
    async with _served(provider) as (base_url, _service), httpx.AsyncClient(timeout=10.0) as client:
        frames = await _run_prompt(client, base_url, "call a bogus tool")

    tool_results = [data for _id, event, data in frames if event == "tool_result"]
    assert tool_results and tool_results[0]["tool_error"] is True


async def test_provider_error_is_sanitized_and_server_keeps_serving() -> None:
    provider = _ScriptedProvider([HeAgentError("upstream provider failed"), _answer("recovered")])
    async with _served(provider) as (base_url, _service), httpx.AsyncClient(timeout=10.0) as client:
        failed = await _run_prompt(client, base_url, "boom")
        recovered = await _run_prompt(client, base_url, "again")
        snapshot = (await client.get(f"{base_url}/api/session")).json()

    assert [event for _id, event, _data in failed][-1] == "error"
    assert failed[-1][2]["message"] == "upstream provider failed"
    assert "Traceback" not in json.dumps(failed)
    assert [event for _id, event, _data in recovered][-1] == "done"
    assert recovered[-1][2]["text"] == "recovered"
    # 失败的那次不投影进历史：会话里只有成功那次。
    assert snapshot["messages"][0]["text"] == "again"


async def test_each_run_reports_its_own_model_and_usage() -> None:
    """顺序两次运行各自报告自己的模型与用量（共享 provider 不得串味）。"""
    provider = _ScriptedProvider([_answer("one", model="model-a", total=11), _answer("two", model="model-b", total=22)])
    async with _served(provider) as (base_url, _service), httpx.AsyncClient(timeout=10.0) as client:
        first = await _run_prompt(client, base_url, "first")
        second = await _run_prompt(client, base_url, "second")

    assert (first[-1][2]["model"], first[-1][2]["usage"]["total_tokens"]) == ("model-a", 11)
    assert (second[-1][2]["model"], second[-1][2]["usage"]["total_tokens"]) == ("model-b", 22)


async def test_handler_keeps_the_network_entry_decisions(monkeypatch: pytest.MonkeyPatch) -> None:
    """网络入口的两条安全决策：**不装 stdin 审批处理器**、**不自动连接 MCP server**。"""
    monkeypatch.setattr(
        "heagent.cli._mcp_lifecycle",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("HTTP 入口不得构造 MCP 生命周期")),
    )
    provider = _ScriptedProvider([_answer("ok")])
    async with _served(provider) as (base_url, service):
        handler = service._executor  # noqa: SLF001 - 直接核对注入的入口对象
        assert handler.engine.approval_handler is None
        async with httpx.AsyncClient(timeout=10.0) as client:
            frames = await _run_prompt(client, base_url, "hi")

    assert frames[-1][2]["text"] == "ok"


async def test_each_run_uses_a_fresh_agent_loop() -> None:
    """每次运行新建 ``AgentLoop``：loop 持有跨 run 可变态，共享实例会互相覆盖（与 TCP 入口同决策）。"""
    provider = _ScriptedProvider([_answer("ok")])
    async with _served(provider) as (_base_url, service):
        handler = service._executor  # noqa: SLF001 - 直接核对入口对象
        first = handler.new_loop()
        second = handler.new_loop()

    assert first is not second
    assert first.provider is second.provider  # provider 是服务级共享
