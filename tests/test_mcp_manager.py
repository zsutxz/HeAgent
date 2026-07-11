"""Story 1.4 — MCPClientManager 连接生命周期（FR-1~5）。Stub，无网络。

``_transport_and_session`` 被 monkeypatch 为 yield 预设 StubSession 的
@asynccontextmanager，避免真实 transport / 子进程；
每个测试用独立的 ``ToolRegistry()`` 实例（不碰进程单例，零回归）。
覆盖并发连接 / 单 server 隔离 / 超时 / 发现注册 / namespace 冲突 / handler 桥接 / 卸载。

真实 transport 路径（含 anyio cancel scope 跨 task 回归防护）见
``test_mcp_manager_http.py``（本地 in-process MCP server）。
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from typing import Any

import pytest
from mcp.types import CallToolResult, TextContent, Tool

from heagent.exceptions import ToolError
from heagent.tools.mcp.config import (
    HttpServerConfig,
    MCPConfig,
    StdioServerConfig,
)
from heagent.tools.mcp.manager import MCPClientManager
from heagent.tools.registry import ToolRegistry
from heagent.types import ToolSchema


class StubSession:
    """模拟 ClientSession（initialize / list_tools / call_tool）。"""

    def __init__(
        self,
        tools: list[Tool],
        call_result: CallToolResult | None = None,
        *,
        list_raises: Exception | None = None,
    ) -> None:
        self._tools = tools
        self._call_result = call_result or CallToolResult(content=[TextContent(type="text", text="ok")], isError=False)
        self.list_raises = list_raises
        self.initialized = False
        self.disconnected = False  # 运行时断连标志：置 True 后 send_ping 抛错（模拟 server 崩溃 / 网络断）

    async def initialize(self) -> None:
        self.initialized = True

    async def send_ping(self, **_: Any) -> None:
        """模拟 ClientSession.send_ping：disconnected 时抛错，否则成功（健康探测用）。"""
        if self.disconnected:
            raise RuntimeError("stub session disconnected")

    async def list_tools(self, **_: Any) -> Any:
        if self.list_raises is not None:
            raise self.list_raises

        class _Result:
            tools = self._tools

        return _Result()

    async def call_tool(self, name: str, arguments: Any = None, **_: Any) -> CallToolResult:
        self._last_call = (name, arguments)
        return self._call_result


def _tool(name: str, desc: str = "d") -> Tool:
    return Tool(name=name, description=desc, inputSchema={"type": "object"})


def _patch_transport(monkeypatch: pytest.MonkeyPatch, sessions: dict[str, StubSession]) -> None:
    """让 _transport_and_session yield 预设 StubSession（按 server 原始名分派）。"""

    @asynccontextmanager
    async def fake_transport(self: MCPClientManager, name: str, cfg: Any) -> Any:
        s = sessions[name]
        await s.initialize()
        yield s

    monkeypatch.setattr(MCPClientManager, "_transport_and_session", fake_transport)


# --- 连接 + 发现 + 注册（FR-1/2/4）---


async def test_connect_discovers_and_registers_stdio_and_http(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = MCPConfig(
        servers={
            "local": StdioServerConfig(command="x"),
            "github": HttpServerConfig(url="https://api.example/mcp", headers={"Authorization": "Bearer t"}),
        }
    )
    sessions = {
        "local": StubSession([_tool("run"), _tool("build")]),
        "github": StubSession([_tool("list_issues")]),
    }
    _patch_transport(monkeypatch, sessions)
    reg = ToolRegistry()
    async with MCPClientManager(cfg, registry=reg):
        names = reg.list_names()
    assert {"local__run", "local__build", "github__list_issues"} <= set(names)


async def test_empty_config_is_noop(monkeypatch: pytest.MonkeyPatch) -> None:
    opened: list[str] = []

    @asynccontextmanager
    async def spy(self: MCPClientManager, name: str, cfg: Any) -> Any:
        opened.append(name)
        yield StubSession([])

    monkeypatch.setattr(MCPClientManager, "_transport_and_session", spy)
    reg = ToolRegistry()
    async with MCPClientManager(MCPConfig(), registry=reg):
        pass
    assert opened == []
    assert reg.list_names() == []


# --- 失败 / 超时隔离（FR-3 / NFR-4 / NFR-6）---


async def test_single_server_failure_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    sessions = {
        "bad": StubSession([], list_raises=RuntimeError("conn refused")),
        "good": StubSession([_tool("run")]),
    }
    _patch_transport(monkeypatch, sessions)
    reg = ToolRegistry()
    async with MCPClientManager(
        MCPConfig(
            servers={
                "bad": StdioServerConfig(command="x"),
                "good": StdioServerConfig(command="y"),
            }
        ),
        registry=reg,
    ):
        names = reg.list_names()
    assert "good__run" in names
    assert not any(n.startswith("bad__") for n in names)


async def test_connect_timeout_isolated(monkeypatch: pytest.MonkeyPatch) -> None:
    @asynccontextmanager
    async def slow_transport(self: MCPClientManager, name: str, cfg: Any) -> Any:
        await asyncio.sleep(0.3)
        yield StubSession([])

    monkeypatch.setattr(MCPClientManager, "_transport_and_session", slow_transport)
    reg = ToolRegistry()
    async with MCPClientManager(
        MCPConfig(servers={"s": StdioServerConfig(command="x")}),
        registry=reg,
        connect_timeout=0.05,
    ):
        assert reg.list_names() == []


# --- namespace 冲突（FR-6）---


async def test_namespace_collision_deduped(monkeypatch: pytest.MonkeyPatch) -> None:
    sessions = {
        "GitHub MCP": StubSession([_tool("list")]),
        "github-mcp": StubSession([_tool("list")]),
    }
    _patch_transport(monkeypatch, sessions)
    reg = ToolRegistry()
    async with MCPClientManager(
        MCPConfig(
            servers={
                "GitHub MCP": StdioServerConfig(command="a"),
                "github-mcp": StdioServerConfig(command="b"),
            }
        ),
        registry=reg,
    ):
        names = reg.list_names()
    assert names.count("github_mcp__list") == 1


# --- handler 桥接（FR-5）---


async def test_handler_returns_bridged_text(monkeypatch: pytest.MonkeyPatch) -> None:
    result = CallToolResult(content=[TextContent(type="text", text="done")], isError=False)
    sessions = {"s": StubSession([_tool("run")], call_result=result)}
    _patch_transport(monkeypatch, sessions)
    reg = ToolRegistry()
    async with MCPClientManager(MCPConfig(servers={"s": StdioServerConfig(command="x")}), registry=reg):
        handler = reg.get_handler("s__run")
        assert handler is not None
        out = await handler(arg="v")  # type: ignore[operator]
    assert out == "done"


async def test_handler_iserror_raises_toolerror(monkeypatch: pytest.MonkeyPatch) -> None:
    result = CallToolResult(content=[TextContent(type="text", text="boom")], isError=True)
    sessions = {"s": StubSession([_tool("run")], call_result=result)}
    _patch_transport(monkeypatch, sessions)
    reg = ToolRegistry()
    async with MCPClientManager(MCPConfig(servers={"s": StdioServerConfig(command="x")}), registry=reg):
        handler = reg.get_handler("s__run")
        assert handler is not None
        with pytest.raises(ToolError):
            await handler()  # type: ignore[operator]


# --- 卸载（FR-2 生命周期）---


async def test_unregister_all_on_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    sessions = {"s": StubSession([_tool("run")])}
    _patch_transport(monkeypatch, sessions)
    reg = ToolRegistry()
    async with MCPClientManager(MCPConfig(servers={"s": StdioServerConfig(command="x")}), registry=reg):
        assert "s__run" in reg.list_names()
    assert "s__run" not in reg.list_names()


# --- 运行时断连主动 unregister（FR-3 收紧）---


def test_health_check_interval_must_be_positive() -> None:
    """health_check_interval<=0 会让 _watch 首个 ping 立即 TimeoutError → 误注销健康 server；构造期拒绝。

    Review patch F1：非正值把 interval 直接当 wait_for timeout，首轮即超时判死。
    """
    with pytest.raises(ValueError):
        MCPClientManager(MCPConfig(), health_check_interval=0)
    with pytest.raises(ValueError):
        MCPClientManager(MCPConfig(), health_check_interval=-1)


async def _wait_removed(reg: ToolRegistry, name: str, *, timeout_s: float = 1.0) -> bool:
    """轮询至工具从 registry 消失（抗 CI 抖动，最多等 timeout_s 秒）。"""
    for _ in range(int(timeout_s / 0.01)):
        if name not in reg.list_names():
            return True
        await asyncio.sleep(0.01)
    return name not in reg.list_names()


async def test_disconnect_auto_unregisters(monkeypatch: pytest.MonkeyPatch) -> None:
    """运行时断连 → _watch 探测 ping 失败 → 该 server 工具主动注销（无需调用触发）。"""
    sessions = {"s": StubSession([_tool("run")])}
    _patch_transport(monkeypatch, sessions)
    reg = ToolRegistry()
    async with MCPClientManager(
        MCPConfig(servers={"s": StdioServerConfig(command="x")}),
        registry=reg,
        health_check_interval=0.01,
    ):
        assert "s__run" in reg.list_names()
        sessions["s"].disconnected = True  # 模拟 server 崩溃 / 网络断
        removed = await _wait_removed(reg, "s__run")
    assert removed, "断连后该 server 工具未在探测周期内注销"


async def test_disconnect_isolated_to_one_server(monkeypatch: pytest.MonkeyPatch) -> None:
    """单 server 断连只注销它自己的工具 + 仅关闭它自己的 transport；另一 server 与内置工具零影响（NFR-6）。

    保真度（deferred-work.md 2026-07-01 FR-3 review defer 项收尾）：不止断言工具从 registry
    消失，还断言 (a) 断连 server 的 transport ``__aexit__`` 已执行（``closed`` 标志）、另一
    server transport 仍持有；(b) 内置（非 server 命名空间）工具保留——证 ``_unregister_server``
    只 ``pop`` 该 server 的 key，不误伤其他。
    """
    sessions = {
        "a": StubSession([_tool("run")]),
        "b": StubSession([_tool("build")]),
    }
    closed: dict[str, bool] = {}

    @asynccontextmanager
    async def tracking_transport(self: MCPClientManager, name: str, cfg: Any) -> Any:
        s = sessions[name]
        await s.initialize()
        try:
            yield s
        finally:
            closed[name] = True  # cm.__aexit__ 观测标志（_server_loop finally 关 transport 时触发）

    monkeypatch.setattr(MCPClientManager, "_transport_and_session", tracking_transport)
    reg = ToolRegistry()
    # 手动注册非 server 命名空间的"内置"工具，断言断连不误伤（_unregister_server 只 pop server key）
    async def _builtin(**_: Any) -> str:
        return ""

    reg.register(ToolSchema(name="search", description="builtin", parameters={"type": "object"}), _builtin)
    async with MCPClientManager(
        MCPConfig(
            servers={
                "a": StdioServerConfig(command="x"),
                "b": StdioServerConfig(command="y"),
            }
        ),
        registry=reg,
        health_check_interval=0.01,
    ):
        sessions["a"].disconnected = True
        removed = await _wait_removed(reg, "a__run")
        assert removed, "断连 server 工具未注销"
        assert "b__build" in reg.list_names()  # 另一 server 工具不受影响
        assert "search" in reg.list_names()  # 内置工具不受影响
        # _watch return → _server_loop finally → cm.__aexit__：等一个 tick 让 closed 标志置位
        for _ in range(100):
            if closed.get("a"):
                break
            await asyncio.sleep(0.01)
        assert closed.get("a"), "断连 server 的 transport __aexit__ 未执行"
        assert not closed.get("b"), "未断连 server 的 transport 不应被关闭"


# --- __aexit__ 关停硬上界（transport close hang 兜底，pre-existing LOW-MED）---


def test_shutdown_timeout_must_be_positive() -> None:
    """shutdown_timeout<=0 会让 _await_shutdown 首轮 wait 立即返回全部 pending → 不给任何 task
    graceful 关停机会即 force-cancel（与 health_check_interval<=0 误判同构）；构造期拒绝。"""
    with pytest.raises(ValueError):
        MCPClientManager(MCPConfig(), shutdown_timeout=0)
    with pytest.raises(ValueError):
        MCPClientManager(MCPConfig(), shutdown_timeout=-1)


async def test_aexit_bounded_when_transport_close_hangs(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    """transport cm.__aexit__ 挂死（stdio 忽略 SIGTERM / HTTP 不 FIN）时 __aexit__ 仍有硬上界。

    未修：__aexit__ 的 gather 无限阻塞 → 外层 wait_for(2.0) 超时取消并 raise TimeoutError → 测试失败。
    已修：__aexit__ 在 shutdown_timeout 后 force-cancel 挂死 task 并返回 → body 正常完成，
    且发出「关停超时」WARNING、工具已注销（_unregister_all 先于 hang）。
    """
    sessions = {"s": StubSession([_tool("run")])}
    hang = asyncio.Event()

    @asynccontextmanager
    async def hanging_transport(self: MCPClientManager, name: str, cfg: Any) -> Any:
        s = sessions[name]
        await s.initialize()
        yield s
        await hang.wait()  # 永不 set → cm.__aexit__ 无限阻塞（模拟 transport close hang）

    monkeypatch.setattr(MCPClientManager, "_transport_and_session", hanging_transport)
    caplog.set_level(logging.WARNING)
    reg = ToolRegistry()

    async def body() -> None:
        async with MCPClientManager(
            MCPConfig(servers={"s": StdioServerConfig(command="x")}),
            registry=reg,
            shutdown_timeout=0.05,
        ):
            assert "s__run" in reg.list_names()

    await asyncio.wait_for(body(), timeout=2.0)
    assert any("关停超时" in r.message for r in caplog.records), "挂死时应发出关停超时 WARNING"
    assert "s__run" not in reg.list_names()  # _unregister_all 先于 hang，工具已摘除


async def test_aexit_clean_close_no_spurious_cancel(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    """正常关闭的 transport 不被误判超时 / 误 cancel（零回归：happy path 不受硬上界影响）。

    shutdown_timeout 故意给宽裕值；正常 transport 的 cm.__aexit__ 远 < timeout 即完成 →
    首轮 wait 全部 done、无 pending → 不 cancel、不告警。
    """
    sessions = {"s": StubSession([_tool("run")])}
    _patch_transport(monkeypatch, sessions)
    caplog.set_level(logging.WARNING)
    reg = ToolRegistry()
    async with MCPClientManager(
        MCPConfig(servers={"s": StdioServerConfig(command="x")}),
        registry=reg,
        shutdown_timeout=1.0,
    ):
        assert "s__run" in reg.list_names()
    assert "s__run" not in reg.list_names()
    assert not any("关停超时" in r.message for r in caplog.records)
    assert not any("二次超时" in r.message for r in caplog.records)


async def test_aexit_mixed_hang_and_clean_server(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    """单 server 挂死不阻塞其它 server 的关停：clean 的 task 首轮 done，仅 hang 的被 cancel。

    asyncio.wait 的 done/pending 分离：先完成的 task 进 done（不受 timeout 惩罚），
    真挂死的进 pending 被 cancel。__aexit__ 整体仍 bounded 返回。
    """
    sessions = {"clean": StubSession([_tool("run")]), "hang": StubSession([_tool("build")])}
    hang = asyncio.Event()

    @asynccontextmanager
    async def mixed_transport(self: MCPClientManager, name: str, cfg: Any) -> Any:
        s = sessions[name]
        await s.initialize()
        yield s
        if name == "hang":
            await hang.wait()  # 仅 hang server 的 cm.__aexit__ 挂死

    monkeypatch.setattr(MCPClientManager, "_transport_and_session", mixed_transport)
    caplog.set_level(logging.WARNING)
    reg = ToolRegistry()

    async def body() -> None:
        async with MCPClientManager(
            MCPConfig(
                servers={
                    "clean": StdioServerConfig(command="x"),
                    "hang": StdioServerConfig(command="y"),
                }
            ),
            registry=reg,
            shutdown_timeout=0.05,
        ):
            assert "clean__run" in reg.list_names()
            assert "hang__build" in reg.list_names()

    await asyncio.wait_for(body(), timeout=2.0)
    assert "clean__run" not in reg.list_names()
    assert "hang__build" not in reg.list_names()
    assert any("关停超时" in r.message for r in caplog.records)
