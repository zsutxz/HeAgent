"""76.2 · 两项目并发不串味与名额分层：脊柱 §6.3 四例（E76-S02，cover R1 / R2）。

用例经**真实**适配器（``cli.ws_project_adapter.ProjectChannelAdapter``）与**真实**集合级端点
（``build_runs_collection_endpoint``）跑，控制台由替身注入：本 entry 的判据是「错误码转译」与
「被拒的提交不占名额」，不是控制台内部实现。四例：

① **并发不串味**：两条集合级连接各为 A、B 提交 ⇒ 控制台收到 ``(A, prompt_a)`` 与
   ``(B, prompt_b)``，两个 ack 的 ``run_id`` 不同、跨连接的 ``run_id`` 交集为 0、出站帧里没有
   ``project_id``；
② **项目内上限**：A 已有在途再提交 A ⇒ 前置校验回 ``project_busy``，第二次**未触达**提交端口；
③ **全局上限**：名额耗尽 ⇒ ``total_inflight_limit``，与同一连接上紧随的 ``run_conflict`` 可分辨，
   两条被拒的都没占上名额；
④ **不占名额**：``unknown_project`` / ``project_unavailable`` / ``project_registry_unreadable``
   三条拒绝路径下提交端口 0 次调用、slot 集合为空。

码的**来源分工**（哪条由替身抛出、哪条生产链上真出）见 ``story-e76-s02-plan.md`` 的 Design Notes：
本文件里 ``project_busy`` 由替身端口的前置校验抛出（其生产来源是控制台的移除闸门），WS 提交链上
项目内占用在生产里回的是 ``run_conflict``。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from heagent.cli.ws_project_adapter import ProjectChannelAdapter
from heagent.network.http_console_protocol import (
    ConsoleOperationError,
    ProjectListResponse,
    ProjectRunRequest,
    ProjectRunResponse,
)
from heagent.network.http_protocol import HttpErrorCode, RunStatus
from heagent.network.ws_server import build_runs_collection_endpoint

_PROJECT_A = "pa0000001"
_PROJECT_B = "pb0000001"
_PROJECT_C = "pc0000001"
_PROMPT_A = "把项目 A 的读径写清楚"
_PROMPT_B = "把项目 B 的写径写清楚"

_ORIGIN_OK = lambda _scope: None  # noqa: E731 - OriginCheck 替身，同步口径

#: 会话骨架在帧队列耗尽（对端断开）后走的正常关闭码。错误帧触发的是 ``WS_CLOSE_POLICY``（1008）
#: 或 ``WS_CLOSE_INTERNAL``（1011），因此断言「1000」本身就证明错误帧没把连接按策略关掉。
_GRACEFUL_CLOSE = 1000


class WebSocketDisconnect(Exception):
    """与 Starlette 同名：``_next_command`` 按类型名判「对端断开」。"""


class _QueueWebSocket:
    """按队列返回入站帧的 ``WebSocketLike`` 替身，队列空后抛断开。

    ``receive_text`` 里让一次 ``sleep(0)``：两条连接并发跑时事件循环才会真正交错，否则「并发
    不串味」会退化成顺序执行，测不到「同一适配器 / 同一控制台被两条连接同时使用」。
    """

    def __init__(self, frames: list[str]) -> None:
        self.scope: dict[str, Any] = {}
        self.path_params: dict[str, Any] = {}
        self.query_params: dict[str, Any] = {}
        self._frames = list(frames)
        self.sent: list[str] = []
        self.accepted = False
        self.closed_code: int | None = None

    async def accept(self) -> None:
        self.accepted = True

    async def close(self, code: int = 1000) -> None:
        self.closed_code = code

    async def receive_text(self) -> str:
        await asyncio.sleep(0)
        if not self._frames:
            raise WebSocketDisconnect()
        return self._frames.pop(0)

    async def send_text(self, data: str) -> None:
        self.sent.append(data)


class _RunWebSocketServiceStub:
    """``RunWebSocketService`` 替身：本文件全走 ``project_id`` 分支，run 服务不该被用到。

    ``start_run`` 记一次次数后立刻抛错：走到它就意味着提交回落到启动工作区，这一帧必须失败而不是
    静默跑起来。每个用例另有一条 ``start_run_calls == 0`` 断言，把「一次都没走到」摆到台面上。
    """

    _closing = False

    def __init__(self) -> None:
        self.start_run_calls = 0

    async def start_run(self, prompt: str) -> Any:
        self.start_run_calls += 1
        raise AssertionError("project submissions must never fall back to the startup workspace")


class _FakeProjectConsole:
    """``ConsoleHandler`` 项目面替身：项目内 / 全局名额的**唯一**记账处，可注入前置校验失败。

    形状对齐 ``cli.http_console.HttpProjectConsole`` 那条链：``get_project_config`` 是纯读解析
    （提交前置校验走它，不占名额），``start_project_run`` 才建 run。

    ``precheck_busy=True`` 时 ``get_project_config`` 对「已有在途 run」的项目抛 ``project_busy``
    ——这是控制台 50-2 闸门的形状（生产来源是**移除项目**端点）；本文件用它把「被拒的提交没触达
    提交端口」钉成可观察行为。生产链上项目内占用由 ``HttpRunService.start_run`` 回 ``run_conflict``。
    """

    def __init__(self, *, precheck_busy: bool = False, total_limit: int | None = None) -> None:
        self.calls: list[tuple[str, object]] = []
        self.submissions: list[tuple[str, str]] = []
        self.rejected: list[str] = []
        self.inflight: dict[str, str] = {}  # project_id → run_id（占着名额的那些）
        self.precheck_errors: dict[str, ConsoleOperationError] = {}
        self._precheck_busy = precheck_busy
        self._total_limit = total_limit
        self._seq = 0

    async def list_projects(self) -> ProjectListResponse:
        self.calls.append(("list_projects", None))
        return ProjectListResponse(projects=[])

    async def get_project_config(self, project_id: str) -> object:
        self.calls.append(("get_project_config", project_id))
        error = self.precheck_errors.get(project_id)
        if error is not None:
            raise error
        if self._precheck_busy and project_id in self.inflight:
            raise ConsoleOperationError(HttpErrorCode.PROJECT_BUSY, "project has an in-flight run")
        return object()

    async def start_project_run(self, project_id: str, request: ProjectRunRequest) -> ProjectRunResponse:
        self.calls.append(("start_project_run", project_id))
        self.submissions.append((project_id, request.prompt))
        if project_id in self.inflight:
            # 项目内上限：生产口径（``HttpRunService._inflight_in_scope``）回的是 ``run_conflict``。
            self.rejected.append(HttpErrorCode.RUN_CONFLICT)
            raise ConsoleOperationError(HttpErrorCode.RUN_CONFLICT, "another run is already in flight")
        if self._total_limit is not None and len(self.inflight) >= self._total_limit:
            self.rejected.append(HttpErrorCode.TOTAL_INFLIGHT_LIMIT)
            raise ConsoleOperationError(HttpErrorCode.TOTAL_INFLIGHT_LIMIT, "server is at its total in-flight limit")
        self._seq += 1
        run_id = f"run-{self._seq:04d}"
        self.inflight[project_id] = run_id
        return ProjectRunResponse(run_id=run_id, session_id=f"sess-{self._seq:04d}", status=RunStatus.RUNNING)

    @property
    def start_project_run_calls(self) -> int:
        return sum(1 for name, _ in self.calls if name == "start_project_run")


def _endpoint(
    service: _RunWebSocketServiceStub,
    console: _FakeProjectConsole,
    *,
    health: str = "ok",
) -> Any:
    adapter = ProjectChannelAdapter(console, lambda: health)  # type: ignore[arg-type]
    return build_runs_collection_endpoint(
        service,
        origin_violation=_ORIGIN_OK,
        max_connections=4,
        version="v76-test",
        project_service=adapter,
    )


def _run_frame(prompt: str, project_id: str) -> str:
    return json.dumps({"command": "run", "prompt": prompt, "project_id": project_id})


def _frames(websocket: _QueueWebSocket) -> list[dict[str, Any]]:
    return [json.loads(frame) for frame in websocket.sent]


def _run_ids(websocket: _QueueWebSocket) -> set[str]:
    """这条连接上出现过的 ``run_id``（``hello`` 帧不带该字段，故只有 ack 贡献值）。"""
    return {frame["run_id"] for frame in _frames(websocket) if "run_id" in frame}


def _cross_count(submissions: list[tuple[str, str]]) -> int:
    """``(project_id, prompt)`` 交叉计数：项目配错 prompt 的次数，期望恒 0。"""
    expected = {_PROJECT_A: _PROMPT_A, _PROJECT_B: _PROMPT_B}
    return sum(1 for project_id, prompt in submissions if expected.get(project_id) != prompt)


@pytest.mark.asyncio
async def test_two_projects_submitted_concurrently_do_not_cross_talk() -> None:
    """① 两条集合级连接各提交 A、B：项目 / prompt / run_id 三样都不串。"""
    console = _FakeProjectConsole()
    service = _RunWebSocketServiceStub()
    endpoint = _endpoint(service, console)
    ws_a = _QueueWebSocket([_run_frame(_PROMPT_A, _PROJECT_A)])
    ws_b = _QueueWebSocket([_run_frame(_PROMPT_B, _PROJECT_B)])

    await asyncio.gather(endpoint(ws_a), endpoint(ws_b))

    # 控制台收到的正是「各自的项目 + 各自的 prompt」，交叉计数 0、每个项目恰好一次
    assert dict(console.submissions) == {_PROJECT_A: _PROMPT_A, _PROJECT_B: _PROMPT_B}
    assert len(console.submissions) == 2
    assert _cross_count(console.submissions) == 0

    # 两个 ack 各自指向本次提交的 run；跨连接的 run_id 交叉计数 == 0
    ack_a, ack_b = _frames(ws_a)[1], _frames(ws_b)[1]
    assert (ack_a["type"], ack_b["type"]) == ("ack", "ack")
    assert ack_a["run_id"] != ack_b["run_id"]
    assert len(_run_ids(ws_a) & _run_ids(ws_b)) == 0
    assert len(_run_ids(ws_a) | _run_ids(ws_b)) == 2
    assert console.inflight == {_PROJECT_A: ack_a["run_id"], _PROJECT_B: ack_b["run_id"]}

    # 帧面不扩：出站帧里没有 project_id（客户端靠 ack 的 run_id 认领，见 AD-6）
    assert all("project_id" not in frame for websocket in (ws_a, ws_b) for frame in _frames(websocket))
    assert service.start_run_calls == 0
    # 两条连接都由帧队列耗尽正常收尾（1000），不是错误帧 / 席位拒绝触发的策略关闭
    assert (ws_a.closed_code, ws_b.closed_code) == (_GRACEFUL_CLOSE, _GRACEFUL_CLOSE)


@pytest.mark.asyncio
async def test_second_submit_into_a_busy_project_is_project_busy_and_stops_at_the_precheck() -> None:
    """② A 已有在途再提交 A：``project_busy`` 逐字进错误帧，且第二次没触达提交端口。"""
    console = _FakeProjectConsole(precheck_busy=True)
    service = _RunWebSocketServiceStub()
    ws = _QueueWebSocket([_run_frame(_PROMPT_A, _PROJECT_A), _run_frame(_PROMPT_A, _PROJECT_A)])

    await _endpoint(service, console)(ws)

    frames = _frames(ws)
    assert frames[1]["type"] == "ack"
    assert frames[2]["type"] == "error"
    assert frames[2]["error"]["error"]["code"] == "project_busy"
    assert HttpErrorCode.PROJECT_BUSY.value == "project_busy"

    # 第二次在**前置校验**就被挡回：提交端口只被触达 1 次、项目 slot 仍只有 1 条（不叠加占位）
    assert console.start_project_run_calls == 1
    assert console.submissions == [(_PROJECT_A, _PROMPT_A)]
    assert console.rejected == []
    assert console.inflight == {_PROJECT_A: frames[1]["run_id"]}
    assert service.start_run_calls == 0
    assert ws.closed_code == _GRACEFUL_CLOSE


@pytest.mark.asyncio
async def test_global_limit_is_total_inflight_limit_and_distinguishable_from_run_conflict() -> None:
    """③ 名额耗尽回 ``total_inflight_limit``，与项目内占用的 ``run_conflict`` 是两个不同的码。"""
    console = _FakeProjectConsole(total_limit=2)
    service = _RunWebSocketServiceStub()
    ws = _QueueWebSocket(
        [
            _run_frame(_PROMPT_A, _PROJECT_A),
            _run_frame(_PROMPT_B, _PROJECT_B),
            _run_frame("第三个项目", _PROJECT_C),
            _run_frame(_PROMPT_A, _PROJECT_A),
        ]
    )

    await _endpoint(service, console)(ws)

    frames = _frames(ws)
    assert [frame["type"] for frame in frames] == ["hello", "ack", "ack", "error", "error"]
    assert frames[1]["run_id"] != frames[2]["run_id"]
    # 第三条（新项目）撞全局上限、第四条（已占用的 A）撞项目内上限：两码可分辨
    codes = {frames[3]["error"]["error"]["code"], frames[4]["error"]["error"]["code"]}
    assert codes == {"total_inflight_limit", "run_conflict"}
    assert HttpErrorCode.TOTAL_INFLIGHT_LIMIT.value == "total_inflight_limit"
    assert HttpErrorCode.RUN_CONFLICT.value == "run_conflict"
    assert console.rejected == [HttpErrorCode.TOTAL_INFLIGHT_LIMIT, HttpErrorCode.RUN_CONFLICT]

    # 两条被拒的都没占上名额：slot 仍是 A、B（C 未登记、A 未叠加）
    assert set(console.inflight) == {_PROJECT_A, _PROJECT_B}
    assert service.start_run_calls == 0
    # 两次拒绝都没关连接：命令循环继续收帧，收尾才按正常码关闭
    assert ws.closed_code == _GRACEFUL_CLOSE


@pytest.mark.parametrize(
    ("project_id", "expected_code", "health"),
    [
        ("punknown1", "unknown_project", "ok"),
        ("pgone0001", "project_unavailable", "ok"),
        ("preg00001", "project_registry_unreadable", "unreadable"),
    ],
    ids=["unknown_project", "project_unavailable", "project_registry_unreadable"],
)
@pytest.mark.asyncio
async def test_rejected_submit_never_reaches_the_submit_port(project_id: str, expected_code: str, health: str) -> None:
    """④ 三条拒绝路径下提交端口 0 次调用、slot 集合为空 ⇒ 被拒的提交不占名额。"""
    console = _FakeProjectConsole()
    if expected_code != "project_registry_unreadable":
        console.precheck_errors[project_id] = ConsoleOperationError(expected_code, "rejected")
    service = _RunWebSocketServiceStub()
    ws = _QueueWebSocket([_run_frame("随便写点", project_id), json.dumps({"command": "ping"})])

    await _endpoint(service, console, health=health)(ws)

    frames = _frames(ws)
    # 错误帧之后连接继续收命令（``ping`` 拿到 ack）：拒绝不改写连接状态
    assert [frame["type"] for frame in frames] == ["hello", "error", "ack"]
    assert frames[1]["error"]["error"]["code"] == expected_code
    assert frames[2]["command"] == "ping"

    # 不占名额：提交端口 0 次、没有 slot、也没有任何 ack
    assert console.start_project_run_calls == 0
    assert console.submissions == []
    assert console.inflight == {}
    assert service.start_run_calls == 0
    assert ws.closed_code == _GRACEFUL_CLOSE
    if expected_code == "project_registry_unreadable":
        # 注册表健康守卫把控制台整个挡在外面（区别于「id 打错」的读径解析）
        assert console.calls == []
