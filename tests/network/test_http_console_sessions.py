"""控制台**会话 API** 与项目内运行的契约测试（Epic 50 / Story 50-3）。

分两层，刻意不混：

- **传输层 ↔ 注入的 console 契约**（``FakeSessionConsole``）：路由存在性、状态码映射、请求体边界、
  会话 id 形态校验「不触碰 console / 文件系统」，以及**常量镜像**（网络层不许 import 运行时模块，
  只能各持一份，故必须由可执行断言钉住不漂移）。
- **入口层 + 运行服务的集成**（真实 ``HttpProjectConsole`` + 真实 ``HttpRunService``，executor 用测试
  替身）：D9 的并发口径（跨项目不共享名额）、在途保护（``session_busy`` / ``project_busy`` 的逐项
  AND 判据）、以及 T9b/AC10 的「同一页面只有一个口径」。

真实 ``AgentLoop`` + ``StubProvider`` 的端到端（运行真的把对话写进项目会话文件）在
``tests/test_http_agent_api.py``。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

import pytest

pytest.importorskip("starlette")

import httpx

from heagent.cli_http import HttpProjectConsole
from heagent.context.session import MAX_SESSION_LIST_LIMIT, MAX_SESSION_TITLE_CHARS, SessionStore
from heagent.network.http_console_protocol import (
    MAX_SESSION_ID_CHARS,
    MAX_SESSION_LIST_ENTRIES,
    MAX_SESSION_TITLE_CHARS as PROTOCOL_TITLE_CHARS,
    ConsoleOperationError,
    ProjectRunRequest,
    ProjectRunResponse,
    SessionDetailResponse,
    SessionEntryResponse,
    SessionListResponse,
    SessionRenameRequest,
    is_valid_session_id,
)
from heagent.network.http_protocol import HttpErrorCode, RunOutcome, RunStatus
from heagent.network.http_server import HttpRunService, HttpServerConfig, build_http_app
from heagent.types import Message, Role

_VERSION = "9.9.9"


# ── 传输层 ↔ console 契约 ──


class FakeSessionConsole:
    """记录调用并回固定结果的 console 替身（``extra="forbid"`` 的模型本身就是契约）。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.fail_with: ConsoleOperationError | None = None

    def _record(self, name: str, *args: Any) -> None:
        self.calls.append((name, *args))
        if self.fail_with is not None:
            raise self.fail_with

    async def list_projects(self) -> Any:  # pragma: no cover - 本文件只测会话面
        raise AssertionError("unexpected list_projects")

    async def register_project(self, request: Any) -> Any:  # pragma: no cover
        raise AssertionError("unexpected register_project")

    async def rename_project(self, project_id: str, request: Any) -> Any:  # pragma: no cover
        raise AssertionError("unexpected rename_project")

    async def project_has_inflight_run(self, project_id: str) -> bool:  # pragma: no cover
        return False

    async def remove_project(self, project_id: str) -> None:  # pragma: no cover
        raise AssertionError("unexpected remove_project")

    async def list_sessions(self, project_id: str) -> SessionListResponse:
        self._record("list_sessions", project_id)
        return SessionListResponse(
            sessions=[SessionEntryResponse(session_id="s1", title="first", message_count=2, version=1, updated_at=None)]
        )

    async def create_session(self, project_id: str, request: Any) -> SessionEntryResponse:
        self._record("create_session", project_id, request)
        return SessionEntryResponse(session_id="s-new", title=request.title or "未命名会话", version=1)

    async def get_session(self, project_id: str, session_id: str) -> SessionDetailResponse:
        self._record("get_session", project_id, session_id)
        return SessionDetailResponse(session_id=session_id, title="t", version=1, messages=[])

    async def rename_session(self, project_id: str, session_id: str, request: Any) -> SessionEntryResponse:
        self._record("rename_session", project_id, session_id, request)
        return SessionEntryResponse(session_id=session_id, title=request.title, version=2)

    async def delete_session(self, project_id: str, session_id: str) -> None:
        self._record("delete_session", project_id, session_id)

    async def start_project_run(self, project_id: str, request: ProjectRunRequest) -> ProjectRunResponse:
        self._record("start_project_run", project_id, request)
        return ProjectRunResponse(run_id="run-1", session_id="s1", status=RunStatus.RUNNING)


def _client(console: Any = None, service: Any = None, *, config: HttpServerConfig | None = None):
    app = build_http_app(
        config or HttpServerConfig(port=0),
        version=_VERSION,
        run_service=service,
        console=console,
    )
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1")


def _error(response: httpx.Response) -> str:
    return response.json()["error"]["code"]


async def test_session_routes_are_absent_without_an_injected_console() -> None:
    async with _client() as client:
        response = await client.get("/api/projects/default/sessions")

    assert response.status_code == 404
    assert _error(response) == HttpErrorCode.NOT_FOUND


async def test_session_routes_reach_the_console_in_order() -> None:
    console = FakeSessionConsole()
    async with _client(console) as client:
        listed = await client.get("/api/projects/default/sessions")
        created = await client.post("/api/projects/default/sessions", json={"title": "  Fresh  "})
        detail = await client.get("/api/projects/default/sessions/s1")
        renamed = await client.patch("/api/projects/default/sessions/s1", json={"title": "Renamed"})
        removed = await client.delete("/api/projects/default/sessions/s1?confirm=true")

    assert listed.status_code == 200
    assert listed.json()["sessions"][0]["session_id"] == "s1"
    assert (created.status_code, created.json()["title"]) == (201, "Fresh")
    assert detail.status_code == 200
    assert (renamed.status_code, renamed.json()["title"]) == (200, "Renamed")
    assert removed.status_code == 204
    assert [call[0] for call in console.calls] == [
        "list_sessions",
        "create_session",
        "get_session",
        "rename_session",
        "delete_session",
    ]


async def test_delete_requires_server_side_confirmation() -> None:
    console = FakeSessionConsole()
    async with _client(console) as client:
        denied = await client.delete("/api/projects/default/sessions/s1")

    assert _error(denied) == HttpErrorCode.CONFIRM_REQUIRED
    assert console.calls == []  # 缺确认即拒：console **一次都没被调用**（无副作用）


@pytest.mark.parametrize("raw", ["../escape", "a/b", "x" * 129, "ab.cd", "a b", "%2e%2e", "sub/dir/file"])
async def test_invalid_session_ids_are_rejected_without_touching_the_console(raw: str) -> None:
    """非法 id 一律 ``invalid_session_id``（AC7），且不落 console / 文件系统。

    请求路径显式 percent-encode，覆盖两种形态：单段的畸形 id（存储层同样判非法）与**含 ``/`` 的
    遍历串**——后者会在路由前被解码成多段路径，由 ``_PROJECT_SESSION_EXTRA_PATH`` 兜底回同一个稳定码
    （否则会退化成 404 ``not_found``，等于把路由结构泄露给客户端）。
    """
    console = FakeSessionConsole()
    async with _client(console) as client:
        response = await client.get(f"/api/projects/default/sessions/{quote(raw, safe='')}")
        patched = await client.patch(f"/api/projects/default/sessions/{quote(raw, safe='')}", json={"title": "t"})

    for result in (response, patched):
        assert result.status_code == 400, result.text
        assert _error(result) == HttpErrorCode.INVALID_SESSION_ID
    assert console.calls == []


@pytest.mark.parametrize(
    ("code", "expected_status"),
    [
        (HttpErrorCode.UNKNOWN_SESSION, 404),
        (HttpErrorCode.INVALID_SESSION_ID, 400),
        (HttpErrorCode.SESSION_CONFLICT, 409),
        (HttpErrorCode.SESSION_BUSY, 409),
        (HttpErrorCode.SESSION_UNREADABLE, 409),
        (HttpErrorCode.PROJECT_UNAVAILABLE, 409),
        (HttpErrorCode.RUN_CONFLICT, 409),
    ],
)
async def test_console_error_codes_map_to_stable_statuses(code: HttpErrorCode, expected_status: int) -> None:
    console = FakeSessionConsole()
    console.fail_with = ConsoleOperationError(code, "boom")
    async with _client(console) as client:
        response = await client.get("/api/projects/default/sessions")

    assert response.status_code == expected_status
    assert _error(response) == code


async def test_unknown_console_code_degrades_to_500() -> None:
    """入口层写错码时降级为 500 + 固定文案，绝不把未知码原样回给客户端。"""
    console = FakeSessionConsole()
    console.fail_with = ConsoleOperationError("not_a_real_code", "boom")
    async with _client(console) as client:
        response = await client.get("/api/projects/default/sessions")

    assert response.status_code == 500
    assert _error(response) == HttpErrorCode.SERVER_ERROR


async def test_request_bodies_are_validated() -> None:
    console = FakeSessionConsole()
    async with _client(console) as client:
        blank_title = await client.post("/api/projects/default/sessions", json={"title": "   "})
        extra_field = await client.post("/api/projects/default/sessions", json={"title": "t", "id": "forged"})
        long_title = await client.post("/api/projects/default/sessions", json={"title": "x" * 500})
        bad_patch = await client.patch("/api/projects/default/sessions/s1", json={"fingerprint": 1})

    for response in (blank_title, extra_field, long_title, bad_patch):
        assert response.status_code == 400, response.text
        assert _error(response) == HttpErrorCode.INVALID_REQUEST
    assert console.calls == []


async def test_oversized_bodies_are_rejected_before_parsing() -> None:
    console = FakeSessionConsole()
    async with _client(console, config=HttpServerConfig(port=0, max_request_bytes=64)) as client:
        oversized = await client.post("/api/projects/default/sessions", json={"title": "x" * 512})

    assert oversized.status_code == 413
    assert _error(oversized) == HttpErrorCode.REQUEST_TOO_LARGE
    assert console.calls == []


async def test_project_run_route_validates_and_returns_the_session() -> None:
    console = FakeSessionConsole()
    async with _client(console) as client:
        created = await client.post("/api/projects/default/runs", json={"prompt": "hi"})
        blank = await client.post("/api/projects/default/runs", json={"prompt": "   "})
        unknown_field = await client.post("/api/projects/default/runs", json={"prompt": "hi", "session": "s1"})

    assert created.status_code == 201
    body = created.json()
    assert (body["run_id"], body["session_id"], body["status"]) == ("run-1", "s1", "running")
    assert _error(blank) == HttpErrorCode.EMPTY_PROMPT
    assert _error(unknown_field) == HttpErrorCode.INVALID_REQUEST


def test_session_limits_are_mirrored_not_drifted() -> None:
    """网络层不许 import 运行时模块，只能各持一份常量 —— 漂移必须由断言挡住。"""
    assert PROTOCOL_TITLE_CHARS == MAX_SESSION_TITLE_CHARS  # 协议侧 ↔ 存储侧
    assert MAX_SESSION_LIST_ENTRIES == MAX_SESSION_LIST_LIMIT
    assert MAX_SESSION_ID_CHARS == 128  # 存储侧 ``_MAX_SESSION_ID_LEN``：由下面的同义性测试钉住


def test_session_id_shape_matches_the_store(tmp_path: Path) -> None:
    """网络层判据与 ``SessionStore`` 的判据必须**同义**（否则会出现「路由放行、存储拒绝」的 500）。"""
    store = SessionStore(base_dir=str(tmp_path / "sessions"))
    candidates = ["ok-1", "ABC_def", "x" * 128, "../escape", "a/b", "a\\b", "", "x" * 129, "ab.cd", "a b"]
    for candidate in candidates:
        try:
            store.path_for(candidate)
            store_accepts = True
        except ValueError:
            store_accepts = False
        assert store_accepts is is_valid_session_id(candidate), candidate


# ── 入口层 + 运行服务集成（D9 / 在途保护 / AC10） ──


class _FakeProjectHandler:
    """项目运行入口的测试替身：**模拟**真实 ``AgentLoop`` 的落盘口径（收尾时 ``SessionStore.save``）。

    刻意按真实语义写：会话文件只在运行收尾时写一次、且**不传** ``expected_version``（R5：运行落盘
    是 last-write-wins）；失败路径同样会把已产生的消息留在文件里（``persist_and_cache`` 在 ``finally``
    里保存）——那正是 AC10 要覆盖的形态。
    """

    def __init__(
        self,
        store: SessionStore,
        *,
        answer: str = "ok",
        error: BaseException | None = None,
        gate: asyncio.Event | None = None,
    ) -> None:
        self.session_store = store
        self.answer = answer
        self.error = error
        self.gate = gate

    async def __call__(self, prompt: str, publisher: Any, *, session_id: str | None = None) -> RunOutcome:
        assert session_id is not None, "控制台必须为项目内运行绑定会话"
        if self.gate is not None:
            await self.gate.wait()
        history = [*self.session_store.load(session_id), Message(role=Role.USER, content=prompt)]
        publisher.text(self.answer)
        self.session_store.save(session_id, [*history, Message(role=Role.ASSISTANT, content=self.answer)])
        if self.error is not None:
            raise self.error
        return RunOutcome(answer=self.answer, model="stub")


class _Harness:
    """真实 console + 真实运行服务 + 临时工作区（项目注册表直接写，不经 HTTP）。"""

    def __init__(self, tmp_path: Path, *, max_inflight_runs: int = 1) -> None:
        self.workspace = tmp_path / "ws"
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.other_root = tmp_path / "other"
        self.other_root.mkdir(parents=True, exist_ok=True)
        self.config = HttpServerConfig(port=0, max_inflight_runs=max_inflight_runs)
        self.gate: asyncio.Event | None = None
        self.failure: BaseException | None = None
        self.service = HttpRunService(self.config, self._unexpected_direct_executor)
        self.console = HttpProjectConsole(self.workspace, runs=self.service, handler_factory=self._factory)
        self.other_id = self.console.registry.register(str(self.other_root), "Other").id

    async def _unexpected_direct_executor(self, prompt: str, publisher: Any) -> RunOutcome:  # pragma: no cover
        raise AssertionError("项目内运行必须走 handler_factory 派生的入口")

    def _factory(self, paths: Any, sessions: SessionStore) -> _FakeProjectHandler:
        return _FakeProjectHandler(sessions, answer="ok", error=self.failure, gate=self.gate)

    def sessions_of(self, project_id: str) -> Path:
        root = self.workspace if project_id == "default" else self.other_root
        return root / ".heagent" / "sessions"

    def client(self) -> httpx.AsyncClient:
        app = build_http_app(self.config, version=_VERSION, run_service=self.service, console=self.console)
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1")

    async def release(self) -> None:
        """放行（若还挂着）并关停服务：测试结束前必须归还名额，避免残留任务。"""
        if self.gate is not None:
            self.gate.set()
        await self.service.close()


async def _wait_terminal(service: HttpRunService, run_id: str, *, budget: float = 5.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + budget
    while loop.time() < deadline:
        record = service.run(run_id)
        if record is not None and record.is_terminal:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"run {run_id} did not finish within {budget}s")


async def test_inflight_quota_is_per_project(tmp_path: Path) -> None:
    """D9 的两条正面断言：**A 项目在跑不挡 B 项目**，而**同一项目内第二个 run 仍被拒**。"""
    harness = _Harness(tmp_path)
    harness.gate = asyncio.Event()
    async with harness.client() as client:
        first = await client.post("/api/projects/default/runs", json={"prompt": "A"})
        second = await client.post(f"/api/projects/{harness.other_id}/runs", json={"prompt": "B"})
        third = await client.post("/api/projects/default/runs", json={"prompt": "A again"})

    try:
        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text  # 跨项目名额不共享
        assert third.status_code == 409
        assert _error(third) == HttpErrorCode.RUN_CONFLICT
        assert harness.service.active_runs == 2  # 两个项目各占一个名额
    finally:
        await harness.release()


async def test_session_delete_is_busy_only_for_its_own_inflight_run(tmp_path: Path) -> None:
    """``session_busy`` 的判据是**逐项 AND**：同项目里别的会话在跑，不得挡住本会话的删除。"""
    harness = _Harness(tmp_path)
    harness.gate = asyncio.Event()
    async with harness.client() as client:
        busy = (await client.post("/api/projects/default/sessions", json={"title": "busy"})).json()["session_id"]
        other = (await client.post("/api/projects/default/sessions", json={"title": "other"})).json()["session_id"]
        started = await client.post("/api/projects/default/runs", json={"prompt": "hi", "session_id": busy})
        refused = await client.delete(f"/api/projects/default/sessions/{busy}?confirm=true")
        allowed = await client.delete(f"/api/projects/default/sessions/{other}?confirm=true")

    try:
        assert started.status_code == 201, started.text
        assert refused.status_code == 409
        assert _error(refused) == HttpErrorCode.SESSION_BUSY
        assert (harness.sessions_of("default") / f"{busy}.json").exists()  # 文件仍在
        assert allowed.status_code == 204, allowed.text
        assert not (harness.sessions_of("default") / f"{other}.json").exists()
    finally:
        await harness.release()


async def test_project_removal_is_refused_while_a_run_is_in_flight(tmp_path: Path) -> None:
    """``project_busy`` 复用同一份在途事实（50-2 的闸门与 50-3 的运行绑定对接）。"""
    harness = _Harness(tmp_path)
    harness.gate = asyncio.Event()
    async with harness.client() as client:
        started = await client.post(f"/api/projects/{harness.other_id}/runs", json={"prompt": "hi"})
        refused = await client.delete(f"/api/projects/{harness.other_id}?confirm=true")

    try:
        assert started.status_code == 201, started.text
        assert refused.status_code == 409
        assert _error(refused) == HttpErrorCode.PROJECT_BUSY
    finally:
        await harness.release()


async def test_failed_run_keeps_one_consistent_history(tmp_path: Path) -> None:
    """T9b / AC10：失败运行的消息**已落会话文件**，详情如实报告 ``failed``；49 的投影不被污染。

    同一页面的历史只有一个口径：页面读会话详情（文件 = 唯一权威），而 ``/api/session`` 的进程内投影
    只含 **49 端点**（无项目归属）的已完成运行——项目内运行一律不投影。
    """
    harness = _Harness(tmp_path)
    harness.failure = RuntimeError("provider exploded")
    async with harness.client() as client:
        created = (await client.post("/api/projects/default/sessions", json={"title": "s"})).json()
        started = await client.post(
            "/api/projects/default/runs", json={"prompt": "hi", "session_id": created["session_id"]}
        )
        run_id = started.json()["run_id"]
        await _wait_terminal(harness.service, run_id)
        detail = await client.get(f"/api/projects/default/sessions/{created['session_id']}")
        projection = await client.get("/api/session")

    try:
        record = harness.service.run(run_id)
        assert record is not None and record.status is RunStatus.FAILED
        assert detail.status_code == 200
        body = detail.json()
        assert [message["text"] for message in body["messages"]] == ["hi", "ok"]
        assert (body["run_id"], body["status"]) == (run_id, "failed")
        assert projection.json()["messages"] == []
    finally:
        await harness.release()


async def test_unreadable_session_file_is_reported_explicitly(tmp_path: Path) -> None:
    """损坏文件：列表里**仍在**（``unreadable=true``），详情回 ``session_unreadable``，绝不当作空会话。"""
    harness = _Harness(tmp_path)
    sessions = harness.sessions_of("default")
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / "broken.json").write_text("{not json", encoding="utf-8")
    async with harness.client() as client:
        detail = await client.get("/api/projects/default/sessions/broken")
        listed = await client.get("/api/projects/default/sessions")

    try:
        assert detail.status_code == 409
        assert _error(detail) == HttpErrorCode.SESSION_UNREADABLE
        entry = next(item for item in listed.json()["sessions"] if item["session_id"] == "broken")
        assert entry["unreadable"] is True
        assert entry["message_count"] is None
    finally:
        await harness.release()


async def test_long_history_is_truncated_explicitly(tmp_path: Path) -> None:
    """超长历史只回最后 N 条，并**显式标注** ``messages_truncated``（绝不静默截断）。"""
    harness = _Harness(tmp_path)
    store = SessionStore(str(harness.sessions_of("default")))
    store.save("long", [Message(role=Role.USER, content=f"m{index}") for index in range(600)])
    async with harness.client() as client:
        detail = await client.get("/api/projects/default/sessions/long")

    try:
        body = detail.json()
        assert detail.status_code == 200
        assert body["messages_truncated"] is True
        assert len(body["messages"]) == 500
        assert body["messages"][-1]["text"] == "m599"
    finally:
        await harness.release()


async def test_default_run_continues_the_most_recent_session(tmp_path: Path) -> None:
    """缺省 ``session_id`` = 该项目**最近的可用**会话（无则新建），而不是每次另起一份历史。"""
    harness = _Harness(tmp_path)
    store = SessionStore(str(harness.sessions_of("default")))
    store.save("a-old", [Message(role=Role.USER, content="older")])
    store.save("b-new", [Message(role=Role.USER, content="newer")])
    _touch_timestamp(store, "a-old", 100.0)
    _touch_timestamp(store, "b-new", 200.0)
    async with harness.client() as client:
        started = await client.post("/api/projects/default/runs", json={"prompt": "hi"})

    try:
        assert started.status_code == 201, started.text
        assert started.json()["session_id"] == "b-new"
    finally:
        await harness.release()


async def test_corrupt_session_is_never_chosen_as_the_default(tmp_path: Path) -> None:
    """缺省会话必须跳过**损坏**文件：直接采用会把它当空会话继续写，等于覆盖掉原内容（AC9）。"""
    harness = _Harness(tmp_path)
    sessions = harness.sessions_of("default")
    sessions.mkdir(parents=True, exist_ok=True)
    (sessions / "broken.json").write_text("{not json", encoding="utf-8")
    async with harness.client() as client:
        started = await client.post("/api/projects/default/runs", json={"prompt": "hi"})

    try:
        assert started.status_code == 201, started.text
        assert started.json()["session_id"] != "broken"
        assert (sessions / "broken.json").read_text(encoding="utf-8") == "{not json"
    finally:
        await harness.release()


async def test_unknown_session_id_is_rejected_before_any_write(tmp_path: Path) -> None:
    harness = _Harness(tmp_path)
    async with harness.client() as client:
        missing = await client.post("/api/projects/default/runs", json={"prompt": "hi", "session_id": "ghost"})

    try:
        assert missing.status_code == 404
        assert _error(missing) == HttpErrorCode.UNKNOWN_SESSION
        assert not harness.sessions_of("default").exists()
    finally:
        await harness.release()


async def test_sessions_without_a_run_entry_are_still_readable(tmp_path: Path) -> None:
    """``executor=None``（默认 CLI 不带运行入口的形态）：会话 API 可用，项目内运行回 409。"""
    workspace = tmp_path / "ws"
    workspace.mkdir(parents=True, exist_ok=True)
    console = HttpProjectConsole(workspace)
    SessionStore(str(workspace / ".heagent" / "sessions")).save(
        "s1", [Message(role=Role.USER, content="saved earlier")]
    )
    app = build_http_app(HttpServerConfig(port=0), version=_VERSION, console=console)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1") as client:
        listed = await client.get("/api/projects/default/sessions")
        detail = await client.get("/api/projects/default/sessions/s1")
        started = await client.post("/api/projects/default/runs", json={"prompt": "hi"})

    assert [item["session_id"] for item in listed.json()["sessions"]] == ["s1"]
    assert [message["text"] for message in detail.json()["messages"]] == ["saved earlier"]
    assert started.status_code == 409
    assert _error(started) == HttpErrorCode.PROJECT_UNAVAILABLE


def _touch_timestamp(store: SessionStore, session_id: str, timestamp: float) -> None:
    """就地改写磁盘 ``timestamp``：排序断言不依赖真实时钟粒度（两次保存可能同毫秒）。"""
    path = Path(store._base) / f"{session_id}.json"  # noqa: SLF001 - 测试内省磁盘布局
    data = json.loads(path.read_text(encoding="utf-8"))
    data["timestamp"] = timestamp
    path.write_bytes(json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))


def test_rename_request_normalizes_and_bounds_the_title() -> None:
    """标题必须单行（折叠空白）且有界：展示层注入与超大响应两头都挡住。"""
    assert SessionRenameRequest(title="  two\nlines  ").title == "two lines"
    with pytest.raises(ValueError):
        SessionRenameRequest(title="   ")
    with pytest.raises(ValueError):
        SessionRenameRequest(title="x" * (MAX_SESSION_TITLE_CHARS + 1))
    assert SessionRenameRequest(title="t", fingerprint=3).fingerprint == 3
