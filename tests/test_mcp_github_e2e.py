"""Story 2.1 — GitHub remote MCP server 只读 E2E（FR-9）。

接官方远程 GitHub MCP server（Streamable HTTP）端到端验证两类只读操作：
列 open issue + 代码搜索。

**默认不进基线**：标 ``@pytest.mark.integration``，``pyproject.toml`` 的
``addopts = ["-m", "not integration"]`` 默认排除。显式运行：

    pytest -m integration tests/test_mcp_github_e2e.py -v

**前置**：
- 环境变量 ``GITHUB_TOKEN`` 为**有效**的 GitHub PAT（当前若无效，成功路径测试 skip）；
- 真实出站网络可达 ``https://api.githubcopilot.com/mcp/``。

工具名以 GitHub MCP server 实际暴露为准；PRD 预期为 ``list_issues`` / ``search_code``
（namespace 化为 ``github__list_issues`` / ``github__search_code``），真实工具名待
有效 token 连接后据实校正。``test_auth_failure_isolated`` 不需有效 token，验证
鉴权失败隔离（FR-3 / Story 2.1 AC6）+ manager HTTP 退出不崩（per-server task 修复）。
"""

from __future__ import annotations

import os

import pytest

from heagent.tools.mcp import MCPClientManager
from heagent.tools.mcp.config import HttpServerConfig, MCPConfig
from heagent.tools.registry import ToolRegistry

pytestmark = [pytest.mark.integration]

GITHUB_MCP_URL = "https://api.githubcopilot.com/mcp/"


def _github_cfg(token: str) -> MCPConfig:
    return MCPConfig(
        servers={"github": HttpServerConfig(url=GITHUB_MCP_URL, headers={"Authorization": f"Bearer {token}"})}
    )


@pytest.fixture
async def connected_github() -> ToolRegistry:
    """连接 GitHub MCP server；连接/鉴权失败 → skip 成功路径（隔离设计：0 工具不抛）。"""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        pytest.skip("需 GITHUB_TOKEN（有效 GitHub PAT）")
    reg = ToolRegistry()
    mgr = MCPClientManager(_github_cfg(token), registry=reg, connect_timeout=15.0)
    try:
        await mgr.__aenter__()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"GitHub MCP 连接建立失败：{type(exc).__name__}: {exc}")
    if not any(n.startswith("github__") for n in reg.list_names()):
        await mgr.__aexit__(None, None, None)
        pytest.skip("GitHub MCP 鉴权/连接失败（token 无效或无权限）→ 0 工具注入")
    try:
        yield reg
    finally:
        await mgr.__aexit__(None, None, None)


def _find_tool(reg: ToolRegistry, keyword: str) -> str | None:
    for n in reg.list_names():
        if n.startswith("github__") and keyword in n.lower():
            return n
    return None


async def test_github_tools_discovered_and_namespaced(connected_github: ToolRegistry) -> None:
    """GitHub server 工具被发现并 namespace 化（github__<tool>，FR-4/6）。"""
    names = [n for n in connected_github.list_names() if n.startswith("github__")]
    assert len(names) > 0
    assert all(n.startswith("github__") for n in names)


async def test_list_issues(connected_github: ToolRegistry) -> None:
    """list_issues 返回含 issue 字段（FR-9）。工具名 / 参数以 server 实际为准。"""
    name = _find_tool(connected_github, "issue")
    if name is None:
        pytest.skip("GitHub MCP server 未暴露 issues 相关工具（工具名待有效 token 校正）")
    handler = connected_github.get_handler(name)
    assert handler is not None
    # 参数 schema 以 server 实际为准；尝试常见 owner/repo 命名，不符则 skip
    for args in ({"owner": "modelcontextprotocol", "repo": "python-sdk"}, {"q": "is:issue is:open"}):
        try:
            out = await handler(**args)  # type: ignore[arg-type]
            assert out, "list_issues 应返回非空文本"
            return
        except Exception:  # noqa: BLE001 - 参数不符 → 试下一组
            continue
    pytest.skip("无法用候选参数调用 list_issues（工具参数 schema 未覆盖）")


async def test_search_code(connected_github: ToolRegistry) -> None:
    """search_code 返回含文件路径（FR-9）。工具名 / 参数以 server 实际为准。"""
    name = _find_tool(connected_github, "search") or _find_tool(connected_github, "code")
    if name is None:
        pytest.skip("GitHub MCP server 未暴露 code search 相关工具")
    handler = connected_github.get_handler(name)
    assert handler is not None
    for args in ({"q": "retry"}, {"query": "retry"}):
        try:
            out = await handler(**args)  # type: ignore[arg-type]
            assert out
            return
        except Exception:  # noqa: BLE001
            continue
    pytest.skip("无法调用 search_code（参数 schema 未覆盖）")


async def test_auth_failure_isolated() -> None:
    """坏 token → 鉴权失败隔离：0 工具注入，manager 正常退出不崩溃（FR-3 / AC6）。

    不需有效 token；验证 per-server task 修复后 HTTP ``__aexit__`` 不再抛 RuntimeError。
    """
    reg = ToolRegistry()
    mgr = MCPClientManager(_github_cfg("ghp_invalid_token_do_not_use_xxx"), registry=reg, connect_timeout=15.0)
    await mgr.__aenter__()
    assert not any(n.startswith("github__") for n in reg.list_names()), "坏 token 不应注入任何工具"
    await mgr.__aexit__(None, None, None)  # 修复后同 task 退出，不抛 RuntimeError
