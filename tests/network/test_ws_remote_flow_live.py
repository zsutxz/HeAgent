"""E76 收口补判据：ADR-005 五步在**真 listener** 上跑一遍（R1 M-4 的延期项回捞）。

`test_ws_remote_flow.py` 用端口替身把五步的顺序与交叉判据钉得很细，但那些替身绕过了三样东西：
`WsServer` 的真路由与真握手、`HttpRunService` 的记录/取消/续流实现、以及**真 `AgentLoop`**（脚本
provider 驱动）。本文件补的正是这一层：WS 客户端经真 WebSocket 连真 listener，提交走
`ProjectChannelAdapter` → `HttpProjectConsole` → 真 run service → 真 AgentLoop。

替身只留在 LLM 侧（脚本 provider，按闸门阻塞），因为要证的是「远程面把活干成了」而不是模型行为。
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from heagent.cli.http import _project_channel
from heagent.cli.http_console import HttpAgentHandler, HttpProjectConsole
from heagent.config import get_settings, reset_settings
from heagent.network.http_console_protocol import ProjectRegisterRequest
from heagent.network.http_protocol import RunEventKind, RunStatus
from heagent.network.http_server import HttpRunService, HttpServerConfig
from heagent.network.ws_host import WsServer, WsServerConfig
from heagent.providers.base import ProviderMetadata
from heagent.pub.types import Message, ProviderResponse, TokenUsage

websockets = pytest.importorskip("websockets")

#: 收帧上限：真跑的 run 只有几条事件，超界说明流没有收敛（比等时长更快暴露问题）。
_MAX_FRAMES = 64

#: 单次等待上限（秒）：只用于兜住「永远不来」的坏路径，正常路径远快于此。
_WAIT = 10.0


class _GatedProvider:
    """脚本 provider：``send`` 阻塞在闸门上，直到用例放行或取消（取消不被吞掉）。"""

    def __init__(self, answer: str) -> None:
        self.gate = asyncio.Event()
        self.answer = answer
        self.calls = 0
        self.cancelled = 0

    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        self.calls += 1
        try:
            await self.gate.wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        return ProviderResponse(
            content=self.answer,
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            model="stub-live",
            finish_reason="stop",
        )

    async def stream(self, messages: list[Message], *, tools: list[object] | None = None) -> Any:
        yield await self.send(messages, tools=tools)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub-live", model="stub-live")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """在 tmp 里跑：注册表 / 会话 / run 快照 / 审计全落临时目录，不污染仓库。"""
    monkeypatch.chdir(tmp_path)
    reset_settings()
    yield
    reset_settings()


def _project(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / ".heagent" / "sessions").mkdir(parents=True, exist_ok=True)
    return root


class _LiveStack:
    """真 listener + 真 console + 真 run service；生产装配走 ``_project_channel``。"""

    def __init__(self, console: HttpProjectConsole, service: HttpRunService, server: WsServer, task: Any) -> None:
        self.console = console
        self.service = service
        self.server = server
        self.task = task

    def uri(self, path: str) -> str:
        return f"ws://127.0.0.1:{self.server.port}{path}"

    async def close(self) -> None:
        """关 listener 并等 serve 循环收敛（收尾异常不掩盖用例结果，关闭本身已由 close 覆盖）。"""
        await self.server.close()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self.task, timeout=10)


async def _start(workspace: Path, provider: _GatedProvider) -> _LiveStack:
    config = HttpServerConfig(port=0, request_timeout=0, idle_timeout=0, tool_inflight_timeout=0)
    handler = HttpAgentHandler(provider, get_settings())
    service = HttpRunService(config, handler)
    console = HttpProjectConsole(
        workspace,
        runs=service,
        handler_factory=handler.for_workspace,
        write_enabled=False,
        global_setting_file=None,
    )
    server = WsServer(
        WsServerConfig(port=0, shutdown_timeout=1),
        run_service=service,
        project_service=_project_channel(console),
    )
    await server.start()
    task = asyncio.create_task(server.serve_forever())
    await asyncio.sleep(0)  # 让 serve 协程先进入 main_loop，避开「建任务后立刻关闭」的首次调度竞态
    return _LiveStack(console, service, server, task)


async def _recv(ws: Any) -> dict[str, Any]:
    return json.loads(await asyncio.wait_for(ws.recv(), timeout=_WAIT))


async def _recv_until_terminal(ws: Any) -> list[dict[str, Any]]:
    """收到 run 的终态事件为止（``done`` / ``cancelled`` / ``error``）。

    终态之后服务端会主动关流（``sent 1000``），所以把关闭当作「流已结束」而不是错误：这样同一条
    断言既能覆盖「终态是最后一帧」，也能覆盖「补完最后一帧后立刻收尾」。
    """
    frames: list[dict[str, Any]] = []
    terminal = {RunEventKind.DONE.value, RunEventKind.CANCELLED.value, RunEventKind.ERROR.value}
    for _ in range(_MAX_FRAMES):
        try:
            frame = await _recv(ws)
        except websockets.exceptions.ConnectionClosed:
            break
        frames.append(frame)
        if frame["type"] == "event" and frame["event"]["kind"] in terminal:
            return frames
    assert frames, "一条事件都没收到"
    raise AssertionError(f"事件流没有走到终态：{frames}")


async def test_adr_005_baseline_runs_against_a_real_listener_and_real_agent_loop(tmp_path: Path) -> None:
    """五步里的四步在真 listener 上成立：列项目 → 提交 → 取消到终态 → 跑到 completed → cursor 续流。

    「两项目并发交叉计数」仍由 ``test_ws_remote_flow.py`` 的替身用例承担（那需要精确的事件插入
    时序）；本用例证的是「真路由 + 真服务 + 真 AgentLoop 这条链路本身能跑完」。
    """
    workspace = tmp_path / "ws"
    workspace.mkdir()
    root_a = _project(tmp_path / "A")
    root_b = _project(tmp_path / "B")
    provider = _GatedProvider("live-answer")
    stack = await _start(workspace, provider)
    try:
        await stack.console.register_project(ProjectRegisterRequest(path=str(root_a), name="A"))
        await stack.console.register_project(ProjectRegisterRequest(path=str(root_b), name="B"))

        async with websockets.connect(stack.uri("/api/runs/ws")) as cli:
            # ① 列项目：真路由 + 真注册表健康探针
            await cli.send('{"command":"projects"}')
            listed = await _recv(cli)
            assert listed["type"] == "projects"
            assert listed["registry_state"] == "ok"
            # 服务启动工作区会被注册表合成为默认项目（`default`），所以按名字挑而不是按位置。
            named = {entry["name"]: entry for entry in listed["projects"]}
            assert {"A", "B"} <= set(named)
            assert all(set(entry) == {"id", "name", "available"} for entry in listed["projects"])

            # ② 提交 B（闸门未放开 ⇒ run 停在 running），集合级 cancel_run 生效
            await cli.send(json.dumps({"command": "run", "prompt": "live B", "project_id": named["B"]["id"]}))
            ack_b = await _recv(cli)
            assert ack_b["type"] == "ack" and ack_b["command"] == "run"
            assert ack_b["status"] == RunStatus.RUNNING.value
            run_b = ack_b["run_id"]

            await cli.send(json.dumps({"command": "cancel_run", "run_id": run_b}))
            ack = await _recv(cli)
            assert ack["type"] == "ack" and ack["command"] == "cancel_run"
            assert ack["run_id"] == run_b and ack["status"] == RunStatus.CANCELLED.value

            # ③ 取消后订阅：ring buffer 补齐到 cancelled 终态（真 run service 的记录面）
            async with websockets.connect(stack.uri(f"/api/runs/{run_b}/ws")) as sub:
                cancelled_frames = await _recv_until_terminal(sub)
                cancelled_seqs = [frame["event"]["seq"] for frame in cancelled_frames]
                assert cancelled_seqs == list(range(1, len(cancelled_seqs) + 1))
                assert cancelled_frames[-1]["event"]["kind"] == RunEventKind.CANCELLED.value

            # ④ 放行闸门后提交 A：真 AgentLoop 跑到 completed，事件流连续无空洞
            provider.gate.set()
            await cli.send(json.dumps({"command": "run", "prompt": "live A", "project_id": named["A"]["id"]}))
            ack_a = await _recv(cli)
            assert ack_a["type"] == "ack" and ack_a["command"] == "run"
            assert ack_a["status"] in {RunStatus.RUNNING.value, RunStatus.COMPLETED.value}
            run_a = ack_a["run_id"]

            async with websockets.connect(stack.uri(f"/api/runs/{run_a}/ws")) as sub:
                done = await _recv_until_terminal(sub)
                done_seqs = [frame["event"]["seq"] for frame in done]
                assert done_seqs == list(range(1, len(done_seqs) + 1))
                assert done[-1]["event"]["kind"] == RunEventKind.DONE.value

            # ⑤ cursor 续流：断线后凭游标重连，从游标 + 1 接着补到同一个终态
            async with websockets.connect(stack.uri(f"/api/runs/{run_a}/ws?last_event_id=1")) as sub:
                resumed = await _recv_until_terminal(sub)
                resumed_seqs = [frame["event"]["seq"] for frame in resumed]
                assert resumed_seqs[0] == 2  # 从游标 + 1 起
                assert resumed_seqs == list(range(2, 2 + len(resumed_seqs)))  # 无空洞
                assert resumed_seqs[-1] == done_seqs[-1]  # 补到与首段相同的终态
    finally:
        await stack.close()


async def test_the_project_run_actually_executed_the_agent_loop(tmp_path: Path) -> None:
    """第三条腿：真 AgentLoop 跑完并落了会话（不是只建了记录就回终态）。"""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    root = _project(tmp_path / "A")
    provider = _GatedProvider("loop-answer")
    stack = await _start(workspace, provider)
    try:
        entry = await stack.console.register_project(ProjectRegisterRequest(path=str(root), name="A"))
        provider.gate.set()
        async with websockets.connect(stack.uri("/api/runs/ws")) as cli:
            await cli.send(json.dumps({"command": "run", "prompt": "live A", "project_id": entry.id}))
            ack = await _recv(cli)
            run_id = ack["run_id"]
        record = stack.service.run(run_id)
        assert record is not None
        for _ in range(200):
            if record.is_terminal:
                break
            await asyncio.sleep(0.01)
        assert record.status is RunStatus.COMPLETED
        assert provider.calls == 1  # 真走了一次 provider（AgentLoop 的 send 面）
        assert record.session_id  # 会话归属由控制台解析并落到记录上
        stored = root / ".heagent" / "sessions" / f"{record.session_id}.json"
        for _ in range(200):
            if stored.exists():
                break
            await asyncio.sleep(0.01)
        assert stored.exists(), "会话文件没有落盘"
    finally:
        await stack.close()
