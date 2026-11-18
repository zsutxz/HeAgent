"""MCP transport + session 开启（transport/session 层，NFR-3 分层）。

transport 细节（stdio 子进程 / Streamable HTTP / 握手）封装于
:func:`default_transport_opener`；:class:`TransportOpener` 是其最小 Protocol——
manager 经构造期 ``transport_opener=`` 注入 fake（测试无需 class-patch 缝），
缺省用 SDK 实现。per-server task 架构（同 task enter/exit，避免 anyio cancel
scope 跨 task）由 manager 的 ``_server_loop`` 承载，本模块只管单次开启。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import httpx

from heagent.tools.mcp.config import HttpServerConfig, ServerConfig, StdioServerConfig
from heagent.tools.mcp.sdk import import_mcp, require_sdk
from heagent.tools.mcp.session_api import handshake
from heagent.tools.mcp.stdio_sandbox import StdioSandboxSpec, stdio_params

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
    from contextlib import AbstractAsyncContextManager
    from typing import Any


@runtime_checkable
class TransportOpener(Protocol):
    """开启一个 server 的 transport + 已握手 session（同 task enter/exit）。

    最小端口：输入 server 配置，返回可 async enter/exit 的 context manager，
    yield 已 initialize 的 :class:`ClientSession`。
    """

    def __call__(self, cfg: ServerConfig) -> AbstractAsyncContextManager[Any]: ...


@asynccontextmanager
async def default_transport_opener(
    cfg: ServerConfig,
    *,
    stdio_sandbox: StdioSandboxSpec | None = None,
) -> AsyncIterator[Any]:
    """建立 transport + ClientSession（SDK 默认实现：stdio / Streamable HTTP 分派 + 握手）。

    ``stdio_sandbox`` 非 None 时 stdio server 经容器拉起（Epic 53 期二 D53-1）；后端不可用
    则**显性降级**回宿主执行（每次 WARNING，见 :mod:`.stdio_sandbox`）。
    """
    # SDK 导入在**调用期**（可选依赖）：模块导入不碰 mcp，缺 `[mcp]` extra 时
    # `import heagent` 与普通 CLI 照常，只有真要开连接时才拿到安装诊断。
    require_sdk("MCP transport")
    client_session = import_mcp("mcp").ClientSession
    stdio_client = import_mcp("mcp.client.stdio").stdio_client
    streamable_http_client = import_mcp("mcp.client.streamable_http").streamable_http_client

    if isinstance(cfg, StdioServerConfig):
        params = stdio_params(cfg, stdio_sandbox)
        async with stdio_client(params) as (read, write), client_session(read, write) as session:
            await handshake(session)
            yield session
    elif isinstance(cfg, HttpServerConfig):
        # streamable_http_client 无 headers 形参；鉴权 header 经自定义 http_client 注入。
        # 多 context with：顺序 enter，后置 context 可引用前置产物（transport[0]/[1]）。
        async with (
            httpx.AsyncClient(headers=cfg.headers) as http_client,
            streamable_http_client(cfg.url, http_client=http_client) as transport,
            client_session(transport[0], transport[1]) as session,
        ):
            await handshake(session)
            yield session
    else:  # pragma: no cover - ServerConfig union 仅两型
        raise TypeError(f"未知 MCP server 配置类型：{type(cfg).__name__}")
