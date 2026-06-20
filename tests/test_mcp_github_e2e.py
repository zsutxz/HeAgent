"""Story 2.1 — GitHub remote MCP server 只读 E2E（FR-9）。

接官方远程 GitHub MCP server（Streamable HTTP）端到端验证两类只读操作：
列 open issue + 代码搜索。

**默认不进基线**：标 ``@pytest.mark.integration``，``pyproject.toml`` 的
``addopts = ["-m", "not integration"]`` 默认排除。显式运行：

    pytest -m integration tests/test_mcp_github_e2e.py -v

**前置**：
- 环境变量 ``GITHUB_TOKEN`` 为**有效**的 GitHub PAT（当前若无效，成功路径测试 skip）；
- 真实出站网络可达 ``https://api.githubcopilot.com/mcp/``。

**已据实校正（2026-06-20 有效 token 连官方远程 server 实测）**：GitHub MCP server 实际
暴露 ``github__list_issues`` / ``github__search_code``，与 PRD/epics FR-9 预期命名**完全
一致**；参数 schema：``list_issues(owner, repo, [perPage, state, ...])``、
``search_code(query, [perPage, ...])``。故测试锁定真实工具名而非模糊匹配——server 若改名
应让 E2E 响亮失败。``test_auth_failure_isolated`` 不需有效 token，验证鉴权失败隔离
（FR-3 / Story 2.1 AC6）+ manager HTTP 退出不崩（per-server task 修复）。
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


# 真实工具名（2026-06-20 有效 token 连 GitHub 官方远程 MCP server 实测确认），
# 与 PRD/epics FR-9 预期命名一致。锁定真实名而非模糊匹配——server 改名应让 E2E 响亮失败。
LIST_ISSUES_TOOL = "github__list_issues"
SEARCH_CODE_TOOL = "github__search_code"


async def test_github_tools_discovered_and_namespaced(connected_github: ToolRegistry) -> None:
    """GitHub server 工具被发现并 namespace 化（github__<tool>，FR-4/6）。

    强于「任意 github__ 工具存在」：断言 PRD 预期的两个只读工具确实注入。
    """
    names = {n for n in connected_github.list_names() if n.startswith("github__")}
    assert names, "应至少发现一个 github__ 工具"
    assert LIST_ISSUES_TOOL in names, f"{LIST_ISSUES_TOOL} 未发现（server 工具集变更？）"
    assert SEARCH_CODE_TOOL in names, f"{SEARCH_CODE_TOOL} 未发现（server 工具集变更？）"


async def test_list_issues(connected_github: ToolRegistry) -> None:
    """github__list_issues(owner, repo) 返回含 issue 字段（FR-9）。

    参数 schema 实测：required=(owner, repo)，可选 perPage/state/labels 等。
    """
    handler = connected_github.get_handler(LIST_ISSUES_TOOL)
    assert handler is not None
    out = await handler(  # type: ignore[arg-type]
        owner="modelcontextprotocol", repo="python-sdk", perPage=5, state="open"
    )
    assert out, "list_issues 应返回非空文本"
    lowered = str(out).lower()
    assert any(k in lowered for k in ("number", "title", "issue", "nodeid", "html_url")), (
        "list_issues 返回应含 issue 字段（number/title/...）"
    )


async def test_search_code(connected_github: ToolRegistry) -> None:
    """github__search_code(query) 返回含文件路径（FR-9）。

    参数 schema 实测：required=(query)，返回命中代码的 path/html_url。
    """
    handler = connected_github.get_handler(SEARCH_CODE_TOOL)
    assert handler is not None
    out = await handler(query="retry language:python", perPage=5)  # type: ignore[arg-type]
    assert out, "search_code 应返回非空文本"
    lowered = str(out).lower()
    assert any(k in lowered for k in ("path", "html_url", "repository", "name")), (
        "search_code 返回应含文件路径（path/html_url/...）"
    )


async def test_auth_failure_isolated() -> None:
    """坏 token → 鉴权失败隔离：0 工具注入，manager 正常退出不崩溃（FR-3 / AC6）。

    不需有效 token；验证 per-server task 修复后 HTTP ``__aexit__`` 不再抛 RuntimeError。
    """
    reg = ToolRegistry()
    mgr = MCPClientManager(_github_cfg("ghp_invalid_token_do_not_use_xxx"), registry=reg, connect_timeout=15.0)
    await mgr.__aenter__()
    assert not any(n.startswith("github__") for n in reg.list_names()), "坏 token 不应注入任何工具"
    await mgr.__aexit__(None, None, None)  # 修复后同 task 退出，不抛 RuntimeError
