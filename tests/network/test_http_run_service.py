"""HTTP 运行 API 与 SSE 的传输层测试（Epic 49 Story 49-3）。

用**假 executor**（network 层不认识 ``AgentLoop``，只认可调用对象）驱动运行服务，覆盖：
运行创建与单运行约束、SSE 事件顺序/序号、失败脱敏、会话投影规则、请求体边界、无 service 形态。

真实 AgentLoop + StubProvider 的端到端在 ``tests/test_http_agent_api.py``。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

pytest.importorskip("starlette")

import httpx

from heagent.network.http_protocol import (
    MAX_EVENT_TEXT_CHARS,
    HttpErrorCode,
    HttpUsage,
    RunOutcome,
    RunStatus,
)
from heagent.network.http_server import (
    HttpRunConflictError,
    HttpRunService,
    HttpServerConfig,
    build_http_app,
)

_VERSION = "9.9.9"


def _config(**overrides: Any) -> HttpServerConfig:
    return HttpServerConfig(**{"port": 0, **overrides})


def _executor(
    *,
    answer: str = "final answer",
    with_tool: bool = False,
    long_text: int = 0,
    error: BaseException | None = None,
):
    """按脚本推事件的假 executor。"""

    async def run(prompt: str, publisher: Any) -> RunOutcome:
        if error is not None:
            raise error
        if with_tool:
            publisher.tool_call("shell", "pytest -q")
            publisher.tool_result("shell", "1 passed", is_error=False)
        if long_text:
            publisher.text("x" * long_text)
        publisher.text(answer)
        return RunOutcome(
            answer=answer,
            model="stub",
            usage=HttpUsage(prompt_tokens=3, completion_tokens=4, total_tokens=7),
        )

    return run


def _blocking_executor(gate: asyncio.Event):
    async def run(prompt: str, publisher: Any) -> RunOutcome:
        await gate.wait()
        return RunOutcome(answer="late")

    return run


def _client(service: HttpRunService | None, *, config: HttpServerConfig | None = None) -> httpx.AsyncClient:
    resolved = config or _config()
    app = build_http_app(resolved, version=_VERSION, run_service=service)
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8766")


def _parse_sse(body: str) -> list[tuple[int, str, dict[str, Any]]]:
    """把 SSE 响应体解析成 ``(id, event, data)`` 列表。"""
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


class TestRunCreation:
    async def test_create_run_returns_id_and_running_status(self) -> None:
        service = HttpRunService(_config(), _executor())
        async with _client(service) as client:
            response = await client.post("/api/runs", json={"prompt": "hello"})

        assert response.status_code == 201
        payload = response.json()
        assert set(payload) == {"run_id", "status"}
        assert payload["status"] == RunStatus.RUNNING
        assert payload["run_id"]

    async def test_second_run_while_inflight_is_rejected_with_conflict(self) -> None:
        """单运行约束：**不排队、不覆盖**，直接 409（AD-3）。"""
        gate = asyncio.Event()
        service = HttpRunService(_config(), _blocking_executor(gate))
        try:
            async with _client(service) as client:
                first = await client.post("/api/runs", json={"prompt": "first"})
                second = await client.post("/api/runs", json={"prompt": "second"})
            assert first.status_code == 201
            assert second.status_code == 409
            assert second.json()["error"]["code"] == HttpErrorCode.RUN_CONFLICT
        finally:
            gate.set()
            await service.close()

    async def test_run_api_is_absent_without_a_service(self) -> None:
        """没有注入运行服务时（Story 49-1 形态）这些路径不注册：稳定 404，不是 500。"""
        async with _client(None) as client:
            create = await client.post("/api/runs", json={"prompt": "hi"})
            session = await client.get("/api/session")

        assert create.status_code == 404
        assert create.json()["error"]["code"] == HttpErrorCode.NOT_FOUND
        assert session.status_code == 404


class TestRequestBounds:
    async def test_extra_fields_are_forbidden(self) -> None:
        """请求体不能携带 provider/model/system 等：那是安全边界的一部分（AD-7）。"""
        service = HttpRunService(_config(), _executor())
        async with _client(service) as client:
            response = await client.post("/api/runs", json={"prompt": "hi", "model": "gpt-evil"})

        assert response.status_code == 400
        assert response.json()["error"]["code"] == HttpErrorCode.INVALID_REQUEST

    async def test_blank_prompt_is_rejected_as_empty_prompt(self) -> None:
        service = HttpRunService(_config(), _executor())
        async with _client(service) as client:
            response = await client.post("/api/runs", json={"prompt": "   "})

        assert response.status_code == 400
        assert response.json()["error"]["code"] == HttpErrorCode.EMPTY_PROMPT

    async def test_invalid_json_is_rejected(self) -> None:
        service = HttpRunService(_config(), _executor())
        async with _client(service) as client:
            response = await client.post(
                "/api/runs",
                content=b"{not json",
                headers={"content-type": "application/json"},
            )

        assert response.status_code == 400
        assert response.json()["error"]["code"] == HttpErrorCode.INVALID_REQUEST

    async def test_oversized_body_is_rejected(self) -> None:
        config = _config(max_request_bytes=128)
        service = HttpRunService(config, _executor())
        async with _client(service, config=config) as client:
            response = await client.post("/api/runs", json={"prompt": "x" * 500})

        assert response.status_code == 413
        assert response.json()["error"]["code"] == HttpErrorCode.REQUEST_TOO_LARGE

    async def test_event_text_is_bounded(self) -> None:
        """事件文本有界：超长工具输出/增量在写入缓冲前就被截断并显式标记。"""
        service = HttpRunService(_config(), _executor(long_text=MAX_EVENT_TEXT_CHARS * 2))
        async with _client(service) as client:
            created = await client.post("/api/runs", json={"prompt": "hi"})
            body = (await client.get(f"/api/runs/{created.json()['run_id']}/events")).text

        text_frames = [data for _id, event, data in _parse_sse(body) if event == "text"]
        assert text_frames
        for data in text_frames:
            assert len(data["text"]) <= MAX_EVENT_TEXT_CHARS + len("…[truncated]")
        assert any(data["text"].endswith("…[truncated]") for data in text_frames)


class TestSseStream:
    async def test_streams_text_tool_and_done_in_order(self) -> None:
        service = HttpRunService(_config(), _executor(answer="done!", with_tool=True))
        async with _client(service) as client:
            created = await client.post("/api/runs", json={"prompt": "hi"})
            body = (await client.get(f"/api/runs/{created.json()['run_id']}/events")).text

        frames = _parse_sse(body)
        kinds = [event for _id, event, _data in frames]
        assert kinds == ["tool_call", "tool_result", "text", "done"]

        tool_call = frames[0][2]
        assert tool_call["tool_name"] == "shell"
        assert tool_call["tool_target"] == "pytest -q"
        done = frames[-1][2]
        assert done["text"] == "done!"
        assert done["model"] == "stub"
        assert done["usage"] == {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7}

    async def test_event_ids_are_monotonic_from_one(self) -> None:
        service = HttpRunService(_config(), _executor(with_tool=True))
        async with _client(service) as client:
            created = await client.post("/api/runs", json={"prompt": "hi"})
            body = (await client.get(f"/api/runs/{created.json()['run_id']}/events")).text

        ids = [frame_id for frame_id, _event, _data in _parse_sse(body)]
        assert ids == list(range(1, len(ids) + 1))

    async def test_unknown_run_is_a_stable_404(self) -> None:
        service = HttpRunService(_config(), _executor())
        async with _client(service) as client:
            response = await client.get("/api/runs/nope/events")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == HttpErrorCode.UNKNOWN_RUN

    async def test_stream_header_and_framing(self) -> None:
        service = HttpRunService(_config(), _executor())
        async with _client(service) as client:
            created = await client.post("/api/runs", json={"prompt": "hi"})
            response = await client.get(f"/api/runs/{created.json()['run_id']}/events")

        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-store"
        assert response.text.endswith("\n\n")

    async def test_stream_ends_after_terminal_event(self) -> None:
        """终态事件之后流必须结束（不悬挂）：整段响应能读完本身就是断言。"""
        service = HttpRunService(_config(), _executor())
        async with _client(service) as client:
            created = await client.post("/api/runs", json={"prompt": "hi"})
            body = (await client.get(f"/api/runs/{created.json()['run_id']}/events")).text

        assert _parse_sse(body)[-1][1] == "done"


class TestRunFailures:
    async def test_failure_emits_sanitized_error_event(self) -> None:
        """失败事件只带脱敏文案：无 traceback、无异常类名。"""

        class _Boom(Exception):
            def __init__(self) -> None:
                super().__init__("boom")
                self.message = "provider exploded at C:\\secret\\key.txt"

        service = HttpRunService(_config(), _executor(error=_Boom()))
        async with _client(service) as client:
            created = await client.post("/api/runs", json={"prompt": "hi"})
            body = (await client.get(f"/api/runs/{created.json()['run_id']}/events")).text

        frames = _parse_sse(body)
        assert frames[-1][1] == "error"
        assert frames[-1][2]["message"] == "provider exploded at C:\\secret\\key.txt"
        assert "_Boom" not in body
        assert "Traceback" not in body

    async def test_unknown_exception_uses_generic_message(self) -> None:
        service = HttpRunService(_config(), _executor(error=RuntimeError("secret internals")))
        async with _client(service) as client:
            created = await client.post("/api/runs", json={"prompt": "hi"})
            body = (await client.get(f"/api/runs/{created.json()['run_id']}/events")).text

        message = _parse_sse(body)[-1][2]["message"]
        assert message == "request failed"
        assert "secret internals" not in body

    async def test_server_accepts_the_next_run_after_a_failure(self) -> None:
        """失败不粘住名额：下一次运行照样能创建（否则网页会永久卡死）。"""
        service = HttpRunService(_config(), _executor(error=RuntimeError("x")))
        async with _client(service) as client:
            first = await client.post("/api/runs", json={"prompt": "hi"})
            await client.get(f"/api/runs/{first.json()['run_id']}/events")
            second = await client.post("/api/runs", json={"prompt": "again"})

        assert second.status_code == 201
        assert service.active_runs == 1  # 第二次仍在途

    async def test_failed_run_is_not_projected_into_session(self) -> None:
        service = HttpRunService(_config(), _executor(error=RuntimeError("x")))
        async with _client(service) as client:
            created = await client.post("/api/runs", json={"prompt": "hi"})
            await client.get(f"/api/runs/{created.json()['run_id']}/events")
            snapshot = (await client.get("/api/session")).json()

        assert snapshot["status"] == RunStatus.FAILED
        assert snapshot["messages"] == []


class TestSessionSnapshot:
    async def test_completed_run_projects_prompt_and_answer(self) -> None:
        service = HttpRunService(_config(), _executor(answer="42"))
        async with _client(service) as client:
            created = await client.post("/api/runs", json={"prompt": "answer?"})
            await client.get(f"/api/runs/{created.json()['run_id']}/events")
            snapshot = (await client.get("/api/session")).json()

        assert set(snapshot) == {"session_id", "run_id", "status", "messages"}
        assert snapshot["status"] == RunStatus.COMPLETED
        assert snapshot["run_id"] == created.json()["run_id"]
        assert snapshot["messages"] == [
            {"role": "user", "text": "answer?"},
            {"role": "assistant", "text": "42"},
        ]

    async def test_session_history_is_bounded(self) -> None:
        service = HttpRunService(_config(run_history_size=2), _executor())
        async with _client(service) as client:
            for index in range(3):
                created = await client.post("/api/runs", json={"prompt": f"p{index}"})
                await client.get(f"/api/runs/{created.json()['run_id']}/events")
            snapshot = (await client.get("/api/session")).json()

        # 上限 = 2 × run_history_size 条消息（每条运行贡献 user + assistant）。
        assert len(snapshot["messages"]) == 4
        assert snapshot["messages"][0]["text"] == "p1"

    async def test_evicted_run_is_unknown(self) -> None:
        """超出保留条数的运行记录被淘汰 ⇒ 按其 id 订阅得 unknown_run（不伪造历史）。"""
        service = HttpRunService(_config(run_history_size=1), _executor())
        async with _client(service) as client:
            first = await client.post("/api/runs", json={"prompt": "p1"})
            await client.get(f"/api/runs/{first.json()['run_id']}/events")
            second = await client.post("/api/runs", json={"prompt": "p2"})
            await client.get(f"/api/runs/{second.json()['run_id']}/events")
            evicted = await client.get(f"/api/runs/{first.json()['run_id']}/events")

        assert evicted.status_code == 404
        assert evicted.json()["error"]["code"] == HttpErrorCode.UNKNOWN_RUN


class TestRunServiceShutdown:
    async def test_close_cancels_inflight_run_and_marks_it_cancelled(self) -> None:
        """关停赢得的运行记 ``cancelled`` 并发出终态事件（AD-10）。"""
        gate = asyncio.Event()
        service = HttpRunService(_config(), _blocking_executor(gate))
        record = await service.start_run("hi")
        runner = asyncio.create_task(service.close())

        await asyncio.wait_for(runner, timeout=5)

        assert record.status == RunStatus.CANCELLED
        assert [event.kind.value for event in record.events][-1] == "cancelled"
        assert service.active_runs == 0
        # 关闭后不再接受新运行。
        with pytest.raises(HttpRunConflictError):
            await service.start_run("again")
