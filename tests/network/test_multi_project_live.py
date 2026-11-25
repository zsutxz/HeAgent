"""多项目并行开发的端到端判据（todo 条目「验证 heagent 同时支持多个项目开发」的落地面）。

## 验证方案（分层，逐层独立可跑）

| 层 | 判据落点 | 证什么 |
| --- | --- | --- |
| 注册表层 | ``tests/test_projects.py`` | 登记 / 去重 / 路径规范化 / 上限 / 坏表 fail-soft |
| 控制台协议层 | ``tests/network/test_http_console_projects.py`` | HTTP 项目路由与稳定错误码 |
| WS 项目通道（替身） | ``tests/network/test_ws_project_admission.py`` | 名额分档、跨项目不串话、并发交叉计数 |
| WS 真栈 · 单项目 | ``tests/network/test_ws_remote_flow_live.py`` | ADR-005 五步在真 listener + 真 AgentLoop 上跑通 |
| **WS 真栈 · 多项目（本文件）** | — | **两项目同时 in-flight → 各自终态、事件不交叉、会话与根目录互不可见** |

替身层能证明「不串话」，但它的 run 推进由用例手动驱动，证不了**两个 run 真的同时在跑**；本文件补的
正是这一格：真 listener + 真 ``HttpRunService`` + 真 ``AgentLoop`` + 两个独立项目根。

## 能力边界（口径，不是缺陷）

- 每项目在途上限 ``http_max_inflight_runs`` 默认 1 ⇒ 并发随项目数线性；服务级总额
  ``http_max_total_inflight`` 默认 0（不限），显式设 N 后所有项目加总受 N 约束（先撞谁按谁拒）。
- 「一个 ``HttpAgentHandler`` = 一个项目根」是不变量：``for_workspace`` 按项目重建 engine / 记忆 /
  会话存储，跨项目零共享可变状态；共享的只有 ``provider``（连接参数）与用户级全局技能根。
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
from heagent.network.http_protocol import HttpErrorCode, RunEventKind, RunStatus
from heagent.network.http_server import HttpRunService, HttpServerConfig
from heagent.network.ws_host import WsServer, WsServerConfig
from heagent.providers.base import ProviderMetadata
from heagent.pub.types import Message, ProviderResponse, TokenUsage

websockets = pytest.importorskip("websockets")

#: 收帧上限：真跑的 run 只有几条事件，超界说明流没有收敛（比等时长更快暴露问题）。
_MAX_FRAMES = 64

#: 单次等待上限（秒）：只用于兜住「永远不来」的坏路径，正常路径远快于此。
_WAIT = 10.0


class _PromptEchoProvider:
    """脚本 provider：``send`` 阻塞在闸门上，放行后按**用户 prompt** 回不同的答案。

    两个项目共享同一个 provider（生产装配即如此：provider 是连接参数，与项目无关），因此答案按
    prompt 区分，才能对「A 的事件流里混进了 B 的回答」这类串话下断言。
    """

    def __init__(self) -> None:
        self.gate = asyncio.Event()
        self.prompts: list[str] = []
        self.cancelled = 0

    @staticmethod
    def _last_user(messages: list[Message]) -> str:
        for message in reversed(messages):
            if message.role == "user":
                return message.content
        return ""

    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        prompt = self._last_user(messages)
        self.prompts.append(prompt)
        try:
            await self.gate.wait()
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        return ProviderResponse(
            content=f"answer:{prompt}",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            model="stub-multi",
            finish_reason="stop",
        )

    async def stream(self, messages: list[Message], *, tools: list[object] | None = None) -> Any:
        yield await self.send(messages, tools=tools)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub-multi", model="stub-multi")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """在 tmp 里跑：注册表 / 会话 / 审计全落临时目录，不污染仓库。"""
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
        await self.server.close()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self.task, timeout=10)


async def _start(
    workspace: Path, provider: _PromptEchoProvider, *, config: HttpServerConfig | None = None
) -> _LiveStack:
    config = config or HttpServerConfig(port=0, request_timeout=0, idle_timeout=0, tool_inflight_timeout=0)
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
    """收到 run 的终态事件为止（``done`` / ``cancelled`` / ``error``）；之后服务端主动关流。"""
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


async def _wait_terminal(service: HttpRunService, run_id: str) -> Any:
    record = service.run(run_id)
    assert record is not None
    for _ in range(400):
        if record.is_terminal:
            return record
        await asyncio.sleep(0.01)
    raise AssertionError(f"run {run_id} 没有走到终态（{record.status}）")


async def test_two_projects_run_concurrently_to_completion(tmp_path: Path) -> None:
    """核心判据：两个项目**同时**在途，各自跑到 completed，事件与会话互不串味。

    断言链（每一步都是「多项目并行开发」的必要条件）：

    1. 两次提交的 ack 都是 ``running`` 且 ``active_runs == 2`` —— 并行而非串行受理；
    2. 两条终止事件流的 ``seq`` 各自从 1 连续，且只携带**自己** prompt 的答案；
    3. 两条记录的 ``session_id`` 不同，会话文件各落各自项目根，交叉查找为空；
    4. 控制台列会话按项目隔离；
    5. 终态后名额归还（``active_runs`` 归零）。
    """
    workspace = tmp_path / "ws"
    workspace.mkdir()
    root_a = _project(tmp_path / "A")
    root_b = _project(tmp_path / "B")
    provider = _PromptEchoProvider()
    stack = await _start(workspace, provider)
    try:
        entry_a = await stack.console.register_project(ProjectRegisterRequest(path=str(root_a), name="A"))
        entry_b = await stack.console.register_project(ProjectRegisterRequest(path=str(root_b), name="B"))

        async with websockets.connect(stack.uri("/api/runs/ws")) as cli:
            await cli.send(json.dumps({"command": "run", "prompt": "task-A", "project_id": entry_a.id}))
            ack_a = await _recv(cli)
            await cli.send(json.dumps({"command": "run", "prompt": "task-B", "project_id": entry_b.id}))
            ack_b = await _recv(cli)

            assert ack_a["type"] == "ack" and ack_a["command"] == "run"
            assert ack_b["type"] == "ack" and ack_b["command"] == "run"
            assert ack_a["status"] == RunStatus.RUNNING.value
            assert ack_b["status"] == RunStatus.RUNNING.value
            run_a, run_b = ack_a["run_id"], ack_b["run_id"]
            assert run_a != run_b
            # 并行硬证据：两条 run 同时占用各自项目的名额（provider 闸门未放开 ⇒ 都停在 running）。
            assert stack.service.active_runs == 2

            async with (
                websockets.connect(stack.uri(f"/api/runs/{run_a}/ws")) as sub_a,
                websockets.connect(stack.uri(f"/api/runs/{run_b}/ws")) as sub_b,
            ):
                provider.gate.set()
                frames_a = await _recv_until_terminal(sub_a)
                frames_b = await _recv_until_terminal(sub_b)

        # ② 事件不交叉：seq 连续 + 终态 + 只带自己的答案
        seqs_a = [frame["event"]["seq"] for frame in frames_a]
        seqs_b = [frame["event"]["seq"] for frame in frames_b]
        assert seqs_a == list(range(1, len(seqs_a) + 1))
        assert seqs_b == list(range(1, len(seqs_b) + 1))
        assert frames_a[-1]["event"]["kind"] == RunEventKind.DONE.value
        assert frames_b[-1]["event"]["kind"] == RunEventKind.DONE.value
        final_a = frames_a[-1]["event"]["text"]
        final_b = frames_b[-1]["event"]["text"]
        assert final_a == "answer:task-A"
        assert final_b == "answer:task-B"
        # 反向交叉：A 的流里不出现 B 的答案（任一帧的 text / message 都不含）
        assert "answer:task-B" not in json.dumps(frames_a, ensure_ascii=False)
        assert "answer:task-A" not in json.dumps(frames_b, ensure_ascii=False)

        record_a = await _wait_terminal(stack.service, run_a)
        record_b = await _wait_terminal(stack.service, run_b)
        assert record_a.status is RunStatus.COMPLETED
        assert record_b.status is RunStatus.COMPLETED
        assert record_a.session_id and record_b.session_id
        assert record_a.session_id != record_b.session_id

        # ③ 会话文件各落各自项目根，交叉目录里不存在对方的会话
        stored_a = root_a / ".heagent" / "sessions" / f"{record_a.session_id}.json"
        stored_b = root_b / ".heagent" / "sessions" / f"{record_b.session_id}.json"
        for _ in range(200):
            if stored_a.exists() and stored_b.exists():
                break
            await asyncio.sleep(0.01)
        assert stored_a.exists(), "A 项目根下没有会话文件"
        assert stored_b.exists(), "B 项目根下没有会话文件"
        assert not (root_a / ".heagent" / "sessions" / f"{record_b.session_id}.json").exists()
        assert not (root_b / ".heagent" / "sessions" / f"{record_a.session_id}.json").exists()

        # ④ 控制台侧会话列表按项目隔离
        sessions_a = await stack.console.list_sessions(entry_a.id)
        sessions_b = await stack.console.list_sessions(entry_b.id)
        assert {item.session_id for item in sessions_a.sessions} == {record_a.session_id}
        assert {item.session_id for item in sessions_b.sessions} == {record_b.session_id}

        # ⑤ 两条 run 都真的进了 AgentLoop（不是只建记录），且名额已归还
        assert sorted(provider.prompts) == ["task-A", "task-B"]
        assert stack.service.active_runs == 0
    finally:
        await stack.close()


async def test_total_inflight_cap_bounds_concurrent_projects(tmp_path: Path) -> None:
    """服务级总额显式设 1 时并发被收紧：B 撞 ``total_inflight_limit``，不是 ``run_conflict``。

    默认 ``max_total_inflight=0``（不限）⇒ 并发随项目数线性（上一条用例证）；这一条证的是可收紧性，
    并钉住「两个码出自两条不同判据」——按项目判的 `run_conflict` vs 按服务总额判的
    `total_inflight_limit`，客户端据此区分「该等哪个项目」与「整个服务忙」。
    """
    workspace = tmp_path / "ws"
    workspace.mkdir()
    root_a = _project(tmp_path / "A")
    root_b = _project(tmp_path / "B")
    provider = _PromptEchoProvider()
    config = HttpServerConfig(
        port=0,
        request_timeout=0,
        idle_timeout=0,
        tool_inflight_timeout=0,
        max_total_inflight=1,
    )
    stack = await _start(workspace, provider, config=config)
    try:
        entry_a = await stack.console.register_project(ProjectRegisterRequest(path=str(root_a), name="A"))
        entry_b = await stack.console.register_project(ProjectRegisterRequest(path=str(root_b), name="B"))

        async with websockets.connect(stack.uri("/api/runs/ws")) as cli:
            await cli.send(json.dumps({"command": "run", "prompt": "cap-A", "project_id": entry_a.id}))
            ack = await _recv(cli)
            assert ack["type"] == "ack" and ack["status"] == RunStatus.RUNNING.value

            await cli.send(json.dumps({"command": "run", "prompt": "cap-B", "project_id": entry_b.id}))
            rejected = await _recv(cli)
            assert rejected["type"] == "error"
            assert rejected["error"]["error"]["code"] == HttpErrorCode.TOTAL_INFLIGHT_LIMIT.value
            assert stack.service.active_runs == 1

        provider.gate.set()
        await _wait_terminal(stack.service, ack["run_id"])
    finally:
        await stack.close()
