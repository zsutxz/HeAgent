"""A35 读侧回放：进程内的 run 记录消失后，从 ``.heagent/runs/<id>/rollout.jsonl`` 回放事件。

两层一起钉住：
- **映射层**（``heagent.cli.run_history``）：rollout 的引擎事件 → SSE 负载，工具输出缺口如实标注，
  缺终态时补一条 cancelled 说明，run_id 拼路径前必须挡住越界；
- **传输层**（``GET /api/runs/<id>/events``）：内存无记录且注入了历史来源 ⇒ 一次性回放流
  （``x-heagent-replay: rollout``），支持 ``Last-Event-ID`` 断点；未注入来源维持 404。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("starlette")

import httpx

from heagent.cli.run_history import load_run_history, rollout_path
from heagent.events.protocol import RunEvent
from heagent.network.http_protocol import RunEventKind, RunEventPayload
from heagent.network.http_server import HttpRunService, HttpServerConfig, build_http_app

_VERSION = "9.9.9"


def _write_rollout(root: Path, run_id: str, events: list[RunEvent]) -> Path:
    path = root / ".heagent" / "runs" / run_id / "rollout.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(f"{event.to_jsonl()}\n" for event in events), encoding="utf-8")
    return path


async def _unused_executor(prompt: str, publisher: Any) -> Any:  # pragma: no cover - 回放路径不跑 run
    raise AssertionError("history replay must not start a run")


def _service() -> HttpRunService:
    return HttpRunService(HttpServerConfig(port=0), _unused_executor)


def _event(kind: str, **fields: Any) -> RunEvent:
    return RunEvent(kind=kind, run_id="run-1", **fields)


def _client(run_service: HttpRunService, history: Any = None) -> httpx.AsyncClient:
    app = build_http_app(
        HttpServerConfig(port=0),
        version=_VERSION,
        run_service=run_service,
        history=history,
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8766")


def _parse_sse(body: str) -> list[tuple[int, str, dict[str, Any]]]:
    frames: list[tuple[int, str, dict[str, Any]]] = []
    for block in body.split("\n\n"):
        if not block.strip() or block.lstrip().startswith(":"):
            continue
        event_id = 0
        event_name = ""
        data = ""
        for line in block.splitlines():
            if line.startswith("id: "):
                event_id = int(line[4:])
            elif line.startswith("event: "):
                event_name = line[7:]
            elif line.startswith("data: "):
                data = line[6:]
        frames.append((event_id, event_name, json.loads(data)))
    return frames


# --- 映射层 ---


def test_maps_tool_calls_and_final_answer(tmp_path: Path) -> None:
    _write_rollout(
        tmp_path,
        "run-1",
        [
            _event("run_started"),
            _event("tool_call_started", tool="shell", target="pytest -q"),
            _event("tool_call_completed", tool="shell", details={"content_length": 42}),
            _event("assistant_message", details={"content": "done", "model": "stub"}),
        ],
    )

    payloads = load_run_history(tmp_path, "run-1")

    assert payloads is not None
    assert [p.kind for p in payloads] == [
        RunEventKind.TOOL_CALL,
        RunEventKind.TOOL_RESULT,
        RunEventKind.DONE,
    ]
    assert [p.seq for p in payloads] == [1, 2, 3]
    assert payloads[0].tool_name == "shell"
    assert payloads[0].tool_target == "pytest -q"
    # rollout 不记工具输出原文 ⇒ 如实标注，而不是留空或编造
    assert "未记入 rollout" in payloads[1].tool_output
    assert payloads[2].text == "done"
    assert payloads[2].model == "stub"


def test_failed_tool_keeps_error_message(tmp_path: Path) -> None:
    _write_rollout(
        tmp_path,
        "run-1",
        [
            _event("tool_call_started", tool="shell", target="boom"),
            _event("tool_call_failed", tool="shell", details={"error": "command not found"}),
            _event("assistant_message", details={"content": "done"}),
        ],
    )

    payloads = load_run_history(tmp_path, "run-1")

    assert payloads is not None
    result = payloads[1]
    assert result.kind is RunEventKind.TOOL_RESULT
    assert result.tool_error is True
    assert "command not found" in result.tool_output


def test_missing_terminal_event_appends_cancelled(tmp_path: Path) -> None:
    """崩溃的 run 在 rollout 尾部没有终态行 ⇒ 补一条说明，避免客户端等一条永不结束的流。"""
    _write_rollout(tmp_path, "run-1", [_event("tool_call_started", tool="shell", target="x")])

    payloads = load_run_history(tmp_path, "run-1")

    assert payloads is not None
    assert payloads[-1].kind is RunEventKind.CANCELLED
    assert "without a terminal event" in payloads[-1].message


def test_run_failure_maps_to_error(tmp_path: Path) -> None:
    _write_rollout(tmp_path, "run-1", [_event("run_failed", details={"error": "boom"})])

    payloads = load_run_history(tmp_path, "run-1")

    assert payloads is not None
    assert [p.kind for p in payloads] == [RunEventKind.ERROR]
    assert payloads[0].message == "boom"


@pytest.mark.parametrize("run_id", ["../escape", "/etc/passwd", "a/b", "", "..", "x" * 200])
def test_unsafe_run_id_never_resolves(tmp_path: Path, run_id: str) -> None:
    assert rollout_path(tmp_path, run_id) is None
    assert load_run_history(tmp_path, run_id) is None


def test_missing_or_empty_rollout_yields_none(tmp_path: Path) -> None:
    assert load_run_history(tmp_path, "nope") is None
    _write_rollout(tmp_path, "run-2", [_event("run_started")])  # 无可回放事件
    assert load_run_history(tmp_path, "run-2") is None


def test_truncated_rollout_line_is_skipped(tmp_path: Path) -> None:
    """crash 截断的尾行不应毁掉整段回放（复用 read_rollout 的容错口径）。"""
    path = _write_rollout(
        tmp_path,
        "run-1",
        [_event("tool_call_started", tool="shell", target="x"), _event("assistant_message", details={"content": "ok"})],
    )
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"kind": "tool_call_comple')

    payloads = load_run_history(tmp_path, "run-1")

    assert payloads is not None
    assert payloads[-1].kind is RunEventKind.DONE


# --- 传输层 ---


@pytest.mark.asyncio
async def test_events_endpoint_replays_history_for_unknown_run() -> None:
    service = _service()
    history = [
        RunEventPayload(kind=RunEventKind.TOOL_CALL, seq=1, tool_name="shell", tool_target="pytest"),
        RunEventPayload(kind=RunEventKind.DONE, seq=2, text="answer"),
    ]
    async with _client(service, lambda run_id: history if run_id == "old-run" else None) as client:
        response = await client.get("/api/runs/old-run/events")

    assert response.status_code == 200
    assert response.headers["x-heagent-replay"] == "rollout"
    frames = _parse_sse(response.text)
    assert [name for _id, name, _data in frames] == ["tool_call", "done"]
    assert frames[-1][2]["text"] == "answer"


@pytest.mark.asyncio
async def test_history_replay_honours_last_event_id() -> None:
    service = _service()
    history = [
        RunEventPayload(kind=RunEventKind.TOOL_CALL, seq=1, tool_name="shell"),
        RunEventPayload(kind=RunEventKind.DONE, seq=2, text="answer"),
    ]
    async with _client(service, lambda _run_id: history) as client:
        response = await client.get("/api/runs/old-run/events", headers={"Last-Event-ID": "1"})

    assert response.status_code == 200
    assert [event_id for event_id, _name, _data in _parse_sse(response.text)] == [2]


@pytest.mark.asyncio
async def test_unknown_run_without_history_source_stays_404() -> None:
    service = _service()
    async with _client(service) as client:
        response = await client.get("/api/runs/ghost/events")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_history_source_returning_none_stays_404() -> None:
    service = _service()
    async with _client(service, lambda _run_id: None) as client:
        response = await client.get("/api/runs/ghost/events")

    assert response.status_code == 404
