"""控制台项目编排的**落点**与**会话二分**判据（E75-S04 / 75.4）。

两份契约，各自可执行：

1. **六项落点锚定项目根**：`context.workspace_root`、会话文件、产物目录（状态根）、
   `ExecutionLedger` 行、`RunContext.state_root`（工具审计根）、memory 根。判据不是比对
   `WorkspacePaths` 的字符串属性（那只证明「拼得对」），而是取**运行时实物**：真
   ``HttpAgentHandler.for_workspace`` 派生的 per-project 运行时（带 ``engine`` / ``facts`` /
   ``paths``）+ 一次真 run（真 ``AgentLoop`` + 脚本化 provider）落下的会话文件。
2. **会话二分是两条显式分支**：该项目有历史会话 ⇒ 复用最近一次；从未有会话 ⇒ 新建。

启动工作区（console 自身的 workspace）零新增产物的口径见 ``_Harness`` docstring。
"""

from __future__ import annotations

import asyncio
import shutil
import uuid
from pathlib import Path
from typing import Any

import pytest

from heagent.cli.http_console import HttpAgentHandler, HttpProjectConsole
from heagent.config import get_settings
from heagent.network.http_console_protocol import ConsoleOperationError, ProjectRunRequest
from heagent.network.http_protocol import HttpErrorCode
from heagent.network.http_server import HttpRunService, HttpServerConfig
from heagent.providers.base import ProviderMetadata
from heagent.pub.types import Message, ProviderResponse, TokenUsage

# 运行产物四个目录：**只允许**出现在项目根下，不接受出现在启动工作区根。
_ARTIFACT_DIRS = ("runs", "sessions", "ledger", "memory")


def _answer(text: str) -> ProviderResponse:
    return ProviderResponse(
        content=text,
        usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        model="stub-1",
        finish_reason="stop",
    )


class _StubProvider:
    """固定应答的 provider：本文件只关心**落点**，不关心对话内容。"""

    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        return _answer("ok")

    async def stream(self, messages: list[Message], *, tools: list[object] | None = None) -> Any:
        yield _answer("ok")

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


def _tree(root: Path) -> set[str]:
    """目录树下的相对路径集合（快照/比对「有没有新增」用）。"""
    return {str(path.relative_to(root)) for path in root.rglob("*")}


class _Harness:
    """真 console + 真运行服务 + 真 per-project 运行时，三个临时根。

    - ``launch_root``：控制台自己的 workspace（``HttpProjectConsole(workspace)`` 的注册表落点）；
    - ``project_a`` / ``project_b``：两个被登记的项目根。

    ``sandbox_backend="passthrough"`` 显式压住仓库 ``.env`` 的 docker 档：本文件不断言沙箱
    隔离，只要后端不进 ``EngineContainer`` 时不要每个项目探测一次 daemon。
    """

    def __init__(self, tmp_path: Path) -> None:
        self.launch_root = tmp_path / "launch"
        self.project_a = tmp_path / "proj-a"
        self.project_b = tmp_path / "proj-b"
        for root in (self.launch_root, self.project_a, self.project_b):
            root.mkdir(parents=True, exist_ok=True)
        self.service = HttpRunService(HttpServerConfig(port=0), self._unexpected_executor)
        handler = HttpAgentHandler(_StubProvider(), get_settings(), sandbox_backend="passthrough")
        self.console = HttpProjectConsole(self.launch_root, runs=self.service, handler_factory=handler.for_workspace)
        # 项目 id 由路径派生；登记动作本身写启动工作区（``<ws>/.heagent/console/``），
        # 因此「零新增」的基线必须取在登记**之后**（见 _baseline）。
        self.a_id = self.console.registry.register(str(self.project_a), "A").id
        self.b_id = self.console.registry.register(str(self.project_b), "B").id

    async def _unexpected_executor(self, prompt: str, publisher: Any) -> Any:  # pragma: no cover
        raise AssertionError("项目内运行必须走 handler_factory 派生的入口")

    def root_of(self, project_id: str) -> Path:
        return self.project_a if project_id == self.a_id else self.project_b

    def _baseline(self) -> set[str]:
        return _tree(self.launch_root)

    async def start(self, project_id: str, *, session_id: str | None = None) -> Any:
        """提交一次项目内运行并等它终态（真 AgentLoop 收尾后才落会话文件）。"""
        response = await self.console.start_project_run(
            project_id, ProjectRunRequest(prompt="hello", session_id=session_id)
        )
        await _wait_terminal(self.service, response.run_id)
        return response

    def assert_launch_root_untouched(self, baseline: set[str]) -> None:
        """启动工作区根零新增产物、零新增 ledger 条目。"""
        for name in _ARTIFACT_DIRS:
            assert not (self.launch_root / ".heagent" / name).exists(), f"启动工作区多出 .heagent/{name}"
        assert _tree(self.launch_root) == baseline, "启动工作区根出现新增文件"
        assert not (self.launch_root / ".heagent" / "ledger").exists()

    async def release(self) -> None:
        await self.service.close()


async def _wait_terminal(service: HttpRunService, run_id: str, *, budget: float = 30.0) -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + budget
    while loop.time() < deadline:
        record = service.run(run_id)
        if record is not None and record.is_terminal:
            return
        await asyncio.sleep(0.01)
    raise AssertionError(f"run {run_id} did not finish within {budget}s")


def _assert_landing_points(harness: _Harness, project_id: str, session_id: str) -> None:
    """六项落点逐项断言：取值来源都指向**该项目根**，不是控制台的启动工作区。"""
    root = harness.root_of(project_id).resolve()
    runtime = harness.console._runtime_for(project_id)  # noqa: SLF001 - 判据要读 per-project 运行时实物
    executor = runtime.executor
    # ① 会话文件：SessionStore 的根与真实落盘位置
    assert runtime.paths.root == root
    assert Path(str(runtime.sessions._base)).resolve() == root / ".heagent" / "sessions"  # noqa: SLF001
    assert (root / ".heagent" / "sessions" / f"{session_id}.json").is_file()
    # ② 产物目录（状态根）：所有运行产物都在它下面
    assert runtime.paths.state_dir == root / ".heagent"
    assert (root / ".heagent" / "sessions").is_dir()
    # ③ ExecutionLedger 行：写入行为发生在项目根账本目录
    assert Path(str(executor.engine.ledger._base)).resolve() == root / ".heagent" / "ledger"  # noqa: SLF001
    # ④ context.workspace_root 与 ⑤ RunContext.state_root（工具审计根）：取容器自己的解析结果
    context = executor.engine.create_run_context()
    assert Path(context.workspace_root).resolve() == root
    assert Path(str(context.state_root)).resolve() == root
    # ⑥ memory 根
    assert runtime.paths.memory_file == root / ".heagent" / "memory" / "MEMORY.md"
    assert Path(str(executor.facts._path)).resolve() == root / ".heagent" / "memory" / "MEMORY.md"  # noqa: SLF001


async def test_single_project_run_lands_entirely_inside_the_project_root(tmp_path: Path) -> None:
    """单项目：六项落点全在项目根，启动工作区零新增。

    无修复时的可观察偏差：任一落点退回「进程 cwd / 控制台 workspace」⇒ 对应文件出现在
    ``launch_root`` 下，断言逐项变红。
    """
    harness = _Harness(tmp_path)
    baseline = harness._baseline()  # noqa: SLF001 - 登记后的基线
    try:
        response = await harness.start(harness.a_id)
        _assert_landing_points(harness, harness.a_id, response.session_id)
        # 零新增：真跑过一次之后，启动工作区仍与基线逐项相等
        harness.assert_launch_root_untouched(baseline)
        # 账本真的可写且落在项目根（写入一次，不依赖工具调用的幂等键形状）
        executor = harness.console._runtime_for(harness.a_id).executor  # noqa: SLF001
        await executor.engine.ledger.acquire("probe-key", scope="test")
        ledger_files = list((harness.project_a / ".heagent" / "ledger").glob("*"))
        assert ledger_files, "ledger 行没有落到项目根账本目录"
        ledger_root = harness.project_a.resolve() / ".heagent" / "ledger"
        assert {path.resolve().parent for path in ledger_files} == {ledger_root}
    finally:
        await harness.release()


async def test_two_projects_each_land_in_their_own_root(tmp_path: Path) -> None:
    """两项目：各自锚定自己的根，跨项目零串味（两个 run 的会话文件互不出现在对方根下）。"""
    harness = _Harness(tmp_path)
    baseline = harness._baseline()  # noqa: SLF001
    try:
        first = await harness.start(harness.a_id)
        second = await harness.start(harness.b_id)
        _assert_landing_points(harness, harness.a_id, first.session_id)
        _assert_landing_points(harness, harness.b_id, second.session_id)
        harness.assert_launch_root_untouched(baseline)
        assert (harness.project_a / ".heagent" / "sessions" / f"{first.session_id}.json").is_file()
        assert (harness.project_b / ".heagent" / "sessions" / f"{second.session_id}.json").is_file()
        assert not (harness.project_b / ".heagent" / "sessions" / f"{first.session_id}.json").exists()
        assert not (harness.project_a / ".heagent" / "sessions" / f"{second.session_id}.json").exists()
    finally:
        await harness.release()


async def test_existing_session_is_continued_instead_of_starting_a_new_one(tmp_path: Path) -> None:
    """有历史会话 ⇒ 续**最近一次**：返回的 ``session_id`` 就是既有那条，且不新建文件。"""
    harness = _Harness(tmp_path)
    try:
        history_id = harness.console._runtime_for(harness.a_id).sessions.create(uuid.uuid4().hex).session_id  # noqa: SLF001
        response = await harness.start(harness.a_id)
        sessions_dir = harness.project_a / ".heagent" / "sessions"
        assert response.session_id == history_id
        assert sorted(path.name for path in sessions_dir.glob("*.json")) == [f"{history_id}.json"]
    finally:
        await harness.release()


async def test_project_without_history_creates_a_new_session(tmp_path: Path) -> None:
    """从未有会话 ⇒ 新建：``session_id`` 新生成、与会话文件一一对应，且不等于别的项目的历史 id。"""
    harness = _Harness(tmp_path)
    try:
        history_id = harness.console._runtime_for(harness.a_id).sessions.create(uuid.uuid4().hex).session_id  # noqa: SLF001
        response = await harness.start(harness.b_id)
        sessions_dir = harness.project_b / ".heagent" / "sessions"
        assert response.session_id
        assert response.session_id != history_id
        assert sorted(path.name for path in sessions_dir.glob("*.json")) == [f"{response.session_id}.json"]
    finally:
        await harness.release()


async def test_unavailable_project_is_rejected_without_creating_a_run(tmp_path: Path) -> None:
    """``available=false``：抛 ``project_unavailable``，不建 run、不占名额、不落任何产物。"""
    harness = _Harness(tmp_path)
    gone = tmp_path / "proj-gone"
    gone.mkdir()
    gone_id = harness.console.registry.register(str(gone), "Gone").id
    baseline = harness._baseline()  # noqa: SLF001
    try:
        shutil.rmtree(gone)
        with pytest.raises(ConsoleOperationError) as caught:
            await harness.console.start_project_run(gone_id, ProjectRunRequest(prompt="hello"))
        assert caught.value.code == HttpErrorCode.PROJECT_UNAVAILABLE
        assert harness.service.active_runs == 0
        harness.assert_launch_root_untouched(baseline)
        assert not (tmp_path / "proj-gone").exists()
    finally:
        await harness.release()
