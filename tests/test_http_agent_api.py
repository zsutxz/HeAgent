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
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("starlette")

import httpx

from heagent.cli_http import HttpAgentHandler, HttpProjectConsole
from heagent.config import get_settings, reset_settings
from heagent.context.session import SessionStore
from heagent.exceptions import HeAgentError
from heagent.network.http_server import HttpRunService, HttpServer, HttpServerConfig
from heagent.providers.base import ProviderMetadata
from heagent.types import Message, ProviderResponse, Role, TokenUsage, ToolCall


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


class _RecordingProvider(_ScriptedProvider):
    """记录每次 provider 调用看到的完整消息（用于断言「模型仍拿到全文」）。"""

    def __init__(self, script: list[Any]) -> None:
        super().__init__(script)
        self.seen: list[list[Message]] = []

    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        self.seen.append([message.model_copy(deep=True) for message in messages])
        return await super().send(messages, tools=tools)

    async def stream(self, messages: list[Message], *, tools: list[object] | None = None) -> Any:
        self.seen.append([message.model_copy(deep=True) for message in messages])
        async for item in super().stream(messages, tools=tools):
            yield item


class _BlockingProvider(_ScriptedProvider):
    """一直等门的 provider：模拟「跑到一半的真实运行」，用于取消与断线语义。"""

    def __init__(self, gate: asyncio.Event) -> None:
        super().__init__([_answer("late")])
        self._gate = gate

    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        await self._gate.wait()
        return await super().send(messages, tools=tools)

    async def stream(self, messages: list[Message], *, tools: list[object] | None = None) -> Any:
        # 必须同时覆盖 stream：运行入口走 ``run_stream``，只用父类的 ``stream`` 会绕过这里的门。
        yield await self.send(messages, tools=tools)


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


async def test_real_loop_streams_tool_events(tmp_path: Path) -> None:
    """真实循环的工具事件：``tool_call`` → ``tool_result`` → 最终答案。"""
    (tmp_path / "pyproject.toml").write_text("[tool.pytest]\n", encoding="utf-8")
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
    # Story 50-8 R5：**成功**的读取类工具内容不进网页事件流（只留作用对象）。
    assert frames[1][2]["tool_output"] == ""
    assert "[tool.pytest]" not in json.dumps(frames)


async def test_read_content_is_hidden_in_web_events_but_still_reaches_the_model(tmp_path: Path) -> None:
    """R5 的两半：网页事件流里**一个字都不出现**文件内容；模型侧照旧拿到全文。

    「模型也看不到」会是真实功能回归（读文件就没意义了）——所以这里用一个记录 provider 断言
    模型收到的消息里**确实有**哨兵内容，证明收敛发生在我们自己新加的**网页桥**，而不是事件源。
    """
    sentinel = "SENTINEL-CONTENT-50-8"
    (tmp_path / "note.txt").write_text(sentinel, encoding="utf-8")
    provider = _RecordingProvider([_tool_request("file_read", {"path": "note.txt"}), _answer("read it")])
    async with _served(provider) as (base_url, _service), httpx.AsyncClient(timeout=10.0) as client:
        frames = await _run_prompt(client, base_url, "read the note")

    tool_call = next(data for _id, event, data in frames if event == "tool_call")
    result = next(data for _id, event, data in frames if event == "tool_result")
    assert "note.txt" in tool_call["tool_target"], "作用对象（文件名）照旧进网页"
    assert result["tool_error"] is False
    assert result["tool_output"] == ""
    assert sentinel not in json.dumps(frames), "读取到的内容不得出现在任何事件帧里"
    seen = [message.content or "" for call in provider.seen for message in call]
    assert any(sentinel in text for text in seen), "模型必须仍能读到文件内容（收敛只发生在网页侧）"


async def test_read_tool_error_message_is_still_shown_in_web() -> None:
    """读取失败的消息**不收敛**——注意内置工具用「返回值 ``Error: ...``」表达可预期失败（``is_error``
    仍为 ``False``），所以收敛判据必须同时看内容；否则「文件不存在」这类诊断会从网页上消失。"""
    provider = _ScriptedProvider([_tool_request("file_read", {"path": "definitely-missing-50-8.txt"}), _answer("done")])
    async with _served(provider) as (base_url, _service), httpx.AsyncClient(timeout=10.0) as client:
        frames = await _run_prompt(client, base_url, "read a missing file")

    result = next(data for _id, event, data in frames if event == "tool_result")
    assert result["tool_error"] is False, "内置工具「返回 Error 字符串」不算异常（仓库既有约定）"
    assert result["tool_output"].startswith("Error:"), "诊断消息必须照旧可见"


async def test_other_tools_keep_their_output_in_web_events(tmp_path: Path) -> None:
    """收敛范围**只有** ``file_read``：别的工具结果原样进网页（R5 是展示策略，不是通用裁剪）。"""
    sentinel = "SENTINEL-OTHER-TOOL-50-8"
    (tmp_path / "out.txt").write_text(sentinel, encoding="utf-8")
    provider = _ScriptedProvider(
        [_tool_request("file_edit", {"path": "out.txt", "old": "a", "new": "b"}), _answer("done")]
    )
    async with _served(provider) as (base_url, _service), httpx.AsyncClient(timeout=10.0) as client:
        frames = await _run_prompt(client, base_url, "edit the file")

    result = next(data for _id, event, data in frames if event == "tool_result")
    assert result["tool_output"] != "" or result["tool_error"] is True


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


async def test_delete_cancels_a_real_run() -> None:
    """``DELETE`` 取消真实运行：真 loop 收到取消信号、终态是 ``cancelled``、历史不投影。"""
    gate = asyncio.Event()
    provider = _BlockingProvider(gate)
    async with _served(provider) as (base_url, service), httpx.AsyncClient(timeout=15.0) as client:
        created = await client.post(f"{base_url}/api/runs", json={"prompt": "hi"})
        run_id = created.json()["run_id"]
        await asyncio.sleep(0.1)  # 让运行真的进入 provider 调用
        cancelled = await client.delete(f"{base_url}/api/runs/{run_id}")
        events = await client.get(f"{base_url}/api/runs/{run_id}/events")
        snapshot = (await client.get(f"{base_url}/api/session")).json()

    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert [event for _id, event, _data in _parse_sse(events.text)][-1] == "cancelled"
    assert snapshot["messages"] == []
    assert service.active_runs == 0
    gate.set()


async def test_disconnect_does_not_cancel_the_run() -> None:
    """SSE 断开只是释放订阅者，**绝不**取消运行（取消只能通过 DELETE，AD-4）。"""
    gate = asyncio.Event()
    provider = _BlockingProvider(gate)
    async with _served(provider) as (base_url, service), httpx.AsyncClient(timeout=15.0) as client:
        created = await client.post(f"{base_url}/api/runs", json={"prompt": "hi"})
        run_id = created.json()["run_id"]
        async with client.stream("GET", f"{base_url}/api/runs/{run_id}/events") as response:
            assert response.status_code == 200
        await asyncio.sleep(0.05)  # 给服务端释放订阅者的时间
        record = service.run(run_id)
        assert record is not None
        assert service.subscriber_count(record) == 0
        snapshot = (await client.get(f"{base_url}/api/session")).json()

    assert snapshot["status"] == "running"
    gate.set()


async def test_project_run_persists_the_conversation_into_the_project_sessions_dir() -> None:
    """Story 50-3 的 AC1/AC2/AC3：项目内运行把对话写进**该项目**的会话文件，且与 CLI 同库同格式。

    与前两个用例（49 的 ``POST /api/runs`` 只做进程内投影、不落盘）刻意对照：这里真的起了一个带
    console 的 listener，运行走 ``HttpProjectHandler.for_workspace`` 派生的 per-project 运行时，
    会话文件落在 ``<项目根>/.heagent/sessions/`` —— 用 ``SessionStore`` 直接读（就是 CLI 的读取路径）。
    """
    session_dir = Path.cwd() / ".heagent" / "sessions"
    provider = _ScriptedProvider([_answer("project answer")])
    config = HttpServerConfig(port=0)
    handler = HttpAgentHandler(provider, get_settings())
    service = HttpRunService(config, handler)
    console = HttpProjectConsole(Path.cwd(), runs=service, handler_factory=handler.for_workspace)
    server = HttpServer(config, version="9.9.9", run_service=service, console=console)
    await server.start()
    task = asyncio.create_task(server.serve_forever())
    base_url = f"http://127.0.0.1:{server.port}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            created = await client.post(f"{base_url}/api/projects/default/runs", json={"prompt": "remember me"})
            assert created.status_code == 201, created.text
            run_id, session_id = created.json()["run_id"], created.json()["session_id"]
            events = await client.get(f"{base_url}/api/runs/{run_id}/events")
            detail = await client.get(f"{base_url}/api/projects/default/sessions/{session_id}")
    finally:
        await server.close()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(task, timeout=5)

    assert [event for _id, event, _data in _parse_sse(events.text)][-1] == "done"
    assert (session_dir / f"{session_id}.json").exists()
    loaded = SessionStore(str(session_dir)).load(session_id)
    assert [message.content for message in loaded if message.role == Role.USER] == ["remember me"]
    body = detail.json()
    assert [message["text"] for message in body["messages"]] == ["remember me", "project answer"]
    assert (body["run_id"], body["status"]) == (run_id, "completed")
