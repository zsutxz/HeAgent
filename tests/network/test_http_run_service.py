"""HTTP 运行 API 与 SSE 的传输层测试（Epic 49 Story 49-3）。

用**假 executor**（network 层不认识 ``AgentLoop``，只认可调用对象）驱动运行服务，覆盖：
运行创建与单运行约束、SSE 事件顺序/序号、失败脱敏、会话投影规则、请求体边界、无 service 形态。

真实 AgentLoop + StubProvider 的端到端在 ``tests/test_http_agent_api.py``。
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import pytest

pytest.importorskip("starlette")

import httpx

from heagent.network.http_protocol import (
    MAX_EVENT_TEXT_CHARS,
    MAX_PROMPT_CHARS,
    HttpErrorCode,
    HttpUsage,
    RunEventKind,
    RunOutcome,
    RunStatus,
)
from heagent.network.http_server import (
    HttpRunConflictError,
    HttpRunService,
    HttpServerConfig,
    _parse_last_event_id,
    _RunRecord,
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
    """阻塞在 ``gate`` 上的 executor（测试用它模拟「跑到一半的运行」）。"""

    async def run(prompt: str, publisher: Any) -> RunOutcome:
        await gate.wait()
        return RunOutcome(answer="late")

    return run


def _stubborn_executor(delay: float):
    """吞掉一次取消的假 executor：模拟忽略取消的长工具 / 子代理（asyncio 无法强杀）。"""

    async def run(prompt: str, publisher: Any) -> RunOutcome:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            await asyncio.sleep(delay)
        return RunOutcome(answer="finished anyway")

    return run


async def _drain(service: HttpRunService, *, budget: float = 5.0) -> None:
    """等残留任务自己结束（避免测试结束时留悬挂任务 / 未归还名额）。"""
    deadline = asyncio.get_running_loop().time() + budget
    while service.active_runs and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.02)


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

    async def test_maximal_cjk_prompt_is_deliverable(self) -> None:
        """协议允许的最大提示词必须真的发得进来：中文（3 字节/字）曾先撞传输层 413。

        这是「字符上限 vs 字节上限」口径矛盾的行为级判据：旧默认 65 536 字节时，32768 个
        中文字（98 304 字节）会被传输层拒——用户看到的上限写着 32 768 字，实际约 2.18 万字
        就到顶。修法见 ``http_protocol.MAX_REQUEST_BYTES_FOR_MAX_PROMPT``。
        """
        prompt = "中" * MAX_PROMPT_CHARS
        assert len(prompt.encode()) > 65_536, "回归判据：该 prompt 必须大于旧默认上限"

        service = HttpRunService(_config(), _executor())
        async with _client(service) as client:
            response = await client.post("/api/runs", json={"prompt": prompt})

        assert response.status_code == 201

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
        """失败事件只带脱敏文案：无 traceback、无异常类名、**无宿主绝对路径**。"""

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
        # 宿主路径被掩码（frame.md 4.17 的承诺：客户端文案不含绝对路径）。
        assert frames[-1][2]["message"] == "provider exploded at <path>"
        assert "secret" not in body and "key.txt" not in body
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


class TestCancellation:
    """``DELETE /api/runs/{id}``：只取消指定运行，且释放名额。"""

    async def test_delete_cancels_the_inflight_run(self) -> None:
        gate = asyncio.Event()
        service = HttpRunService(_config(), _blocking_executor(gate))
        async with _client(service) as client:
            created = await client.post("/api/runs", json={"prompt": "slow"})
            run_id = created.json()["run_id"]
            cancelled = await client.delete(f"/api/runs/{run_id}")
            body = (await client.get(f"/api/runs/{run_id}/events")).text

        assert cancelled.status_code == 200
        assert cancelled.json() == {"run_id": run_id, "status": RunStatus.CANCELLED}
        assert [event for _id, event, _data in _parse_sse(body)][-1] == "cancelled"
        assert service.active_runs == 0

    async def test_deleted_run_frees_the_slot_for_the_next_run(self) -> None:
        gate = asyncio.Event()
        service = HttpRunService(_config(), _blocking_executor(gate))
        async with _client(service) as client:
            first = await client.post("/api/runs", json={"prompt": "slow"})
            await client.delete(f"/api/runs/{first.json()['run_id']}")
            # 放行「门」：证明取消确实归还了唯一名额（否则第二次提交会收 409）。
            gate.set()
            second = await client.post("/api/runs", json={"prompt": "fast"})
            await client.get(f"/api/runs/{second.json()['run_id']}/events")

        assert second.status_code == 201
        assert service.active_runs == 0

    async def test_delete_unknown_run_is_a_stable_404(self) -> None:
        service = HttpRunService(_config(), _executor())
        async with _client(service) as client:
            response = await client.delete("/api/runs/nope")

        assert response.status_code == 404
        assert response.json()["error"]["code"] == HttpErrorCode.UNKNOWN_RUN

    async def test_delete_after_completion_is_idempotent(self) -> None:
        """已完成（或已取消）的运行再被 DELETE：返回其真实终态，不报错、不改成 cancelled。"""
        service = HttpRunService(_config(), _executor())
        async with _client(service) as client:
            created = await client.post("/api/runs", json={"prompt": "hi"})
            run_id = created.json()["run_id"]
            await client.get(f"/api/runs/{run_id}/events")
            response = await client.delete(f"/api/runs/{run_id}")

        assert response.status_code == 200
        assert response.json()["status"] == RunStatus.COMPLETED

    async def test_cancelled_run_is_not_projected_into_session(self) -> None:
        gate = asyncio.Event()
        service = HttpRunService(_config(), _blocking_executor(gate))
        async with _client(service) as client:
            created = await client.post("/api/runs", json={"prompt": "slow"})
            await client.delete(f"/api/runs/{created.json()['run_id']}")
            snapshot = (await client.get("/api/session")).json()

        assert snapshot["status"] == RunStatus.CANCELLED
        assert snapshot["messages"] == []


class TestReconnect:
    """``Last-Event-ID`` 续读与窗口外重同步（AD-4）。"""

    async def test_last_event_id_replays_only_newer_events(self) -> None:
        service = HttpRunService(_config(), _executor(with_tool=True))
        async with _client(service) as client:
            created = await client.post("/api/runs", json={"prompt": "hi"})
            run_id = created.json()["run_id"]
            full = _parse_sse((await client.get(f"/api/runs/{run_id}/events")).text)
            resumed = _parse_sse((await client.get(f"/api/runs/{run_id}/events", headers={"last-event-id": "2"})).text)

        assert [frame_id for frame_id, _event, _data in full] == [1, 2, 3, 4]
        # 严格大于：2 之后的事件全部、且只有它们（不重复、顺序稳定）。
        assert [frame_id for frame_id, _event, _data in resumed] == [3, 4]

    async def test_stale_cursor_requires_resync(self) -> None:
        """游标早于缓冲窗口 ⇒ 409 ``resync_required``（不发一条看似连续的流）。"""
        service = HttpRunService(_config(event_buffer_size=2), _executor(with_tool=True))
        async with _client(service) as client:
            created = await client.post("/api/runs", json={"prompt": "hi"})
            run_id = created.json()["run_id"]
            await client.get(f"/api/runs/{run_id}/events")  # 等运行结束（缓冲只剩最后 2 条）
            stale = await client.get(f"/api/runs/{run_id}/events", headers={"last-event-id": "1"})
            boundary = await client.get(f"/api/runs/{run_id}/events", headers={"last-event-id": "2"})

        assert stale.status_code == 409
        assert stale.json()["error"]["code"] == HttpErrorCode.RESYNC_REQUIRED
        # 边界值（下一条正好还在缓冲里）允许续读。
        assert boundary.status_code == 200
        assert [frame_id for frame_id, _event, _data in _parse_sse(boundary.text)] == [3, 4]

    async def test_evicted_cursor_overrun_requires_resync(self) -> None:
        """完全不带到 ``Last-Event-ID`` 的订阅在窗口已淘汰开头时同样要求重新同步。"""
        service = HttpRunService(_config(event_buffer_size=1), _executor(with_tool=True))
        async with _client(service) as client:
            created = await client.post("/api/runs", json={"prompt": "hi"})
            run_id = created.json()["run_id"]
            await client.get(f"/api/runs/{run_id}/events")
            response = await client.get(f"/api/runs/{run_id}/events")

        assert response.status_code == 409
        assert response.json()["error"]["code"] == HttpErrorCode.RESYNC_REQUIRED

    @pytest.mark.parametrize("header", ["abc", "", "-3", "1.5"])
    async def test_invalid_last_event_id_is_treated_as_no_cursor(self, header: str) -> None:
        """畸形游标不变成 400：按「从头读」处理（否则一个坏游标会让客户端再也订阅不上）。"""
        service = HttpRunService(_config(), _executor())
        async with _client(service) as client:
            created = await client.post("/api/runs", json={"prompt": "hi"})
            run_id = created.json()["run_id"]
            await client.get(f"/api/runs/{run_id}/events")
            response = await client.get(f"/api/runs/{run_id}/events", headers={"last-event-id": header})

        assert response.status_code == 200
        assert [event for _id, event, _data in _parse_sse(response.text)][-1] == "done"

    async def test_heartbeat_is_emitted_while_idle(self) -> None:
        """空闲期的保活帧：``yield None``（不占事件 ID、不推进游标）。"""
        gate = asyncio.Event()
        service = HttpRunService(_config(), _blocking_executor(gate))
        record = await service.start_run("hi")
        stream = service.stream_events(record, heartbeat_seconds=0.05)
        try:
            assert await asyncio.wait_for(stream.__anext__(), timeout=2) is None
        finally:
            await stream.aclose()
            gate.set()
            await service.close()

    async def test_subscription_limit_is_enforced(self) -> None:
        config = _config(max_connections=1)
        service = HttpRunService(config, _executor())
        record = await service.start_run("hi")
        # 手动占住唯一名额（等价于一个已建立的 SSE 流）。
        record.subscribers.add(asyncio.Queue())
        async with _client(service, config=config) as client:
            response = await client.get(f"/api/runs/{record.run_id}/events")

        assert response.status_code == 429
        assert response.json()["error"]["code"] == HttpErrorCode.RATE_LIMITED

    async def test_disconnect_releases_the_subscription(self) -> None:
        """客户端断线（生成器被关闭）必须释放订阅者，否则名额会被死连接吃光。"""
        gate = asyncio.Event()
        service = HttpRunService(_config(), _blocking_executor(gate))
        record = await service.start_run("hi")
        stream = service.stream_events(record, heartbeat_seconds=0.05)
        try:
            await stream.__anext__()  # 启动生成器 ⇒ 订阅已登记
            assert service.subscriber_count(record) == 1
        finally:
            await stream.aclose()
        assert service.subscriber_count(record) == 0
        gate.set()
        await service.close()


class TestRunTimeout:
    async def test_run_timeout_marks_timed_out_and_emits_the_event(self) -> None:
        gate = asyncio.Event()
        service = HttpRunService(_config(request_timeout=0.05), _blocking_executor(gate))
        record = await service.start_run("hi")
        async with _client(service) as client:
            body = (await client.get(f"/api/runs/{record.run_id}/events")).text

        assert record.status == RunStatus.TIMED_OUT
        assert [event for _id, event, _data in _parse_sse(body)][-1] == "timed_out"
        assert service.active_runs == 0
        gate.set()

    async def test_timeout_then_shutdown_is_a_noop(self) -> None:
        """超时已写下终态：随后的关停不得改写它、也不得再发一条终态事件（AD-10）。"""
        gate = asyncio.Event()
        service = HttpRunService(_config(request_timeout=0.05), _blocking_executor(gate))
        record = await service.start_run("hi")
        for _ in range(100):
            if record.is_terminal:
                break
            await asyncio.sleep(0.02)
        await service.close()

        assert record.status == RunStatus.TIMED_OUT
        terminal = [
            event.kind.value
            for event in record.events
            if event.kind.value in {"done", "error", "cancelled", "timed_out"}
        ]
        assert terminal == ["timed_out"]
        gate.set()

    async def test_timed_out_run_is_not_projected_into_session(self) -> None:
        gate = asyncio.Event()
        service = HttpRunService(_config(request_timeout=0.05), _blocking_executor(gate))
        async with _client(service) as client:
            created = await client.post("/api/runs", json={"prompt": "slow"})
            await client.get(f"/api/runs/{created.json()['run_id']}/events")
            snapshot = (await client.get("/api/session")).json()

        assert snapshot["status"] == RunStatus.TIMED_OUT
        assert snapshot["messages"] == []
        gate.set()


class TestRunFailureObservability:
    """运行是后台任务：失败必须留下服务端诊断，归因不得被改写。"""

    async def test_run_failure_is_logged_with_traceback(self, caplog: pytest.LogCaptureFixture) -> None:
        service = HttpRunService(_config(), _executor(error=RuntimeError("boom")))
        with caplog.at_level(logging.ERROR, logger="heagent.network.http_server"):
            async with _client(service) as client:
                created = await client.post("/api/runs", json={"prompt": "x"})
                await client.get(f"/api/runs/{created.json()['run_id']}/events")

        failed = [record for record in caplog.records if "event=run_failed" in record.getMessage()]
        assert failed, caplog.text
        assert any(record.exc_info for record in failed), "运行失败的 traceback 只该出现在服务端日志里"

    async def test_inner_timeout_error_is_not_attributed_to_the_deadline(self) -> None:
        """provider / 网络自己抛的 ``TimeoutError`` 不是「超过配置时限」。"""
        service = HttpRunService(
            _config(request_timeout=30.0),
            _executor(error=TimeoutError("connect timeout to the provider endpoint")),
        )
        async with _client(service) as client:
            created = await client.post("/api/runs", json={"prompt": "x"})
            body = (await client.get(f"/api/runs/{created.json()['run_id']}/events")).text

        assert [event for _id, event, _data in _parse_sse(body)] == ["error"]
        assert "configured time limit" not in body

    async def test_ignored_deadline_is_recorded(self, caplog: pytest.LogCaptureFixture) -> None:
        """executor 吞掉取消 ⇒ 时限并未生效：终态按实际结果，但不能静默。"""

        async def stubborn(prompt: str, publisher: Any) -> RunOutcome:
            try:
                await asyncio.sleep(0.5)
            except asyncio.CancelledError:
                await asyncio.sleep(0.05)
            return RunOutcome(answer="finished anyway")

        service = HttpRunService(_config(request_timeout=0.05), stubborn)
        with caplog.at_level(logging.WARNING, logger="heagent.network.http_server"):
            async with _client(service) as client:
                created = await client.post("/api/runs", json={"prompt": "x"})
                body = (await client.get(f"/api/runs/{created.json()['run_id']}/events")).text

        assert "event=timeout_ignored" in caplog.text
        assert [event for _id, event, _data in _parse_sse(body)] == ["done"]
        assert service.active_runs == 0


class TestEventIdCursorParsing:
    """``Last-Event-ID`` 判据必须是「ASCII 十进制 + 位数有界」（畸形游标不得变成 500）。"""

    class _Request:
        def __init__(self, raw: str) -> None:
            self.headers = {"last-event-id": raw}

    @pytest.mark.parametrize("raw", ["²", "9" * 20, "", "  ", "1.5", "-3", "abc", "１２３"])
    def test_malformed_cursors_are_treated_as_absent(self, raw: str) -> None:
        assert _parse_last_event_id(self._Request(raw)) is None

    def test_ascii_decimal_cursor_is_parsed(self) -> None:
        assert _parse_last_event_id(self._Request("42")) == 42

    async def test_superscript_cursor_does_not_break_the_stream(self) -> None:
        """``'²'`` 是 ``isdigit()`` 为真而 ``int()`` 会抛的字符（可经 latin-1 请求头塞进来）。"""
        service = HttpRunService(_config(), _executor())
        async with _client(service) as client:
            created = await client.post("/api/runs", json={"prompt": "x"})
            response = await client.get(
                f"/api/runs/{created.json()['run_id']}/events",
                headers={"last-event-id": b"\xb2"},
            )

        assert response.status_code == 200
        assert [event for _id, event, _data in _parse_sse(response.text)][-1] == "done"


class TestSubscriberBackpressure:
    """订阅者跟不上时必须有界：结束它的流（客户端重连 → ring buffer / resync），而不是无限堆积。"""

    def test_lagging_subscriber_is_dropped_and_its_stream_ends(self) -> None:
        record = _RunRecord("run-1", "prompt", buffer_size=4)
        queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=record.subscriber_queue_size)
        record.subscribers.add(queue)

        for index in range(20):
            record.append(RunEventKind.TEXT, text=f"e{index}")

        assert record.subscribers == set(), "掉队订阅者必须被摘掉，队列不能继续增长"
        drained: list[Any] = []
        while True:
            try:
                drained.append(queue.get_nowait())
            except asyncio.QueueEmpty:
                break
        assert drained == [None], "队列只剩「结束流」哨兵：客户端据此重连并走 resync 路径"

    async def test_healthy_subscriber_receives_every_event(self) -> None:
        """有界队列不得伤到跟得上的订阅者（真实路径里每帧之间都有 await）。"""
        service = HttpRunService(_config(event_buffer_size=4), _executor())
        record = _RunRecord("run-1", "prompt", buffer_size=4)
        received: list[Any] = []

        async def consume() -> None:
            async for payload in service.stream_events(record, heartbeat_seconds=30):
                received.append(payload)
                if len(received) >= 6:
                    return

        task = asyncio.create_task(consume())
        await asyncio.sleep(0)
        for index in range(6):
            record.append(RunEventKind.TEXT, text=f"e{index}")
            await asyncio.sleep(0)
        await asyncio.wait_for(task, timeout=5)

        assert [payload.text for payload in received] == [f"e{index}" for index in range(6)]

    def test_subscriber_queue_is_bounded_like_the_event_window(self) -> None:
        record = _RunRecord("run-1", "prompt", buffer_size=8)

        assert record.subscriber_queue_size == 8


class TestCancellationHonesty:
    """executor 吞掉取消时，``DELETE`` / 关停都只能**有界放弃**并如实反映状态（AD-10 的诚实边界）。"""

    async def test_cancel_is_bounded_and_reports_the_real_status(self, caplog: pytest.LogCaptureFixture) -> None:
        """忽略取消的运行：``cancel_run`` 不在 ``shutdown_timeout`` 之外等待，也不谎报已取消。"""
        config = _config(shutdown_timeout=0.05)
        service = HttpRunService(config, _stubborn_executor(0.5))
        record = await service.start_run("hi")
        await asyncio.sleep(0.05)  # 让运行任务真正开始跑（否则取消发生在协程体执行之前）
        with caplog.at_level(logging.WARNING, logger="heagent.network.http_server"):
            returned = await asyncio.wait_for(service.cancel_run(record.run_id), timeout=5)

        assert returned is not None
        assert "event=cancel_timeout" in caplog.text
        # 如实返回 running（取消未被响应），名额仍由该运行持有——不假装它已经结束。
        assert returned.status is RunStatus.RUNNING
        assert service.active_runs == 1

        await _drain(service)

    async def test_shutdown_is_bounded_when_a_run_ignores_cancellation(self, caplog: pytest.LogCaptureFixture) -> None:
        """关停同样不得无界等待：超时后返回并记日志，运行最终自行结束后名额归还。"""
        config = _config(shutdown_timeout=0.05)
        service = HttpRunService(config, _stubborn_executor(0.5))
        record = await service.start_run("hi")
        await asyncio.sleep(0.05)  # 同上：先让运行进入「在途」状态
        with caplog.at_level(logging.WARNING, logger="heagent.network.http_server"):
            await asyncio.wait_for(service.close(), timeout=5)

        assert "event=run_shutdown_timeout" in caplog.text
        assert not record.is_terminal, "忽略取消的运行在关停超时后仍在跑（asyncio 无法强杀）"

        await _drain(service)


class TestRunHistoryRetention:
    """``run_history_size`` 的语义是「已终结 run 的保留条数」：在途记录不得被淘汰。"""

    async def test_in_flight_record_is_never_evicted(self) -> None:
        gate = asyncio.Event()
        config = _config(run_history_size=1, max_inflight_runs=2)
        service = HttpRunService(config, _blocking_executor(gate))
        async with _client(service, config=config) as client:
            first = (await client.post("/api/runs", json={"prompt": "first"})).json()["run_id"]
            second = (await client.post("/api/runs", json={"prompt": "second"})).json()["run_id"]

            assert service.run(first) is not None
            assert service.run(second) is not None
            cancelled = await client.delete(f"/api/runs/{first}")

            assert cancelled.status_code == 200
            assert cancelled.json()["status"] == RunStatus.CANCELLED
            assert service.active_runs == 1

        gate.set()
        for _ in range(100):
            if service.active_runs == 0:
                break
            await asyncio.sleep(0.02)
        assert service.active_runs == 0

    async def test_terminal_records_are_still_evicted(self) -> None:
        config = _config(run_history_size=1)
        service = HttpRunService(config, _executor())
        async with _client(service, config=config) as client:
            first = (await client.post("/api/runs", json={"prompt": "1"})).json()["run_id"]
            await client.get(f"/api/runs/{first}/events")
            second = (await client.post("/api/runs", json={"prompt": "2"})).json()["run_id"]

        assert service.run(first) is None
        assert service.run(second) is not None
