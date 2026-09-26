"""MCP ↔ ToolRegistry 注入桥（registry 注入分层，FR-3/FR-6）。

MCP 工具的**注册/注销单一入口**：server 工具（发现期注册、断连/关停精确摘除）
与桥接资源工具（``mcp__list_resources`` / ``mcp__read_resource``）的 registry 写入
全部收敛到 :class:`RegistryBridge`。命名冲突策略（跳过 + 告警，不覆盖既有工具）
也定义于此——manager 只编排生命周期，不直接触 registry。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from heagent.pub.types import ToolAnnotations, ToolSchema

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from heagent.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

_BRIDGE_LIST_TOOL = "mcp__list_resources"
_BRIDGE_READ_TOOL = "mcp__read_resource"


class RegistryBridge:
    """MCP 工具注册/注销的单一入口（持有已注册簿与桥接注册标记）。"""

    def __init__(self, registry: ToolRegistry) -> None:
        self._registry = registry
        # server 原始名 → 其已注册的 namespaced 工具名（断连时按 server 精确摘除，FR-3 收紧）
        self._registered: dict[str, list[str]] = {}
        # 桥接工具是否已注册（mcp__list_resources + mcp__read_resource 两者统一标记）
        self._bridge_registered = False

    def register_server_tool(self, *, server_name: str, schema: ToolSchema, handler: Callable[..., Any]) -> bool:
        """注册单个 server 工具；命名冲突跳过 + 告警（FR-6），返回是否实际注册。"""
        if self._registry.get_schema(schema.name) is not None:
            logger.warning("MCP 工具 '%s' 命名冲突（已注册），跳过", schema.name)
            return False
        self._registry.register(schema, handler)
        self._registered.setdefault(server_name, []).append(schema.name)
        return True

    def unregister_server(self, name: str) -> None:
        """注销单个 server 的全部工具（运行时断连用）。``registry.unregister`` 幂等。"""
        for tool_name in self._registered.pop(name, ()):
            self._registry.unregister(tool_name)

    def unregister_all(self) -> None:
        """从 ToolRegistry 摘除全部 MCP 工具（还原纯内置状态，利于测试隔离）。"""
        # 1. 摘除桥接工具（先于 server 工具，避免 server unregister 误判 bridge 存活）
        if self._bridge_registered:
            self._registry.unregister(_BRIDGE_LIST_TOOL)
            self._registry.unregister(_BRIDGE_READ_TOOL)
            self._bridge_registered = False
        # 2. 逐 server 摘除（unregister_server 的 ``pop(name, ())`` 会清键，遍历完后自然为空）
        for name in list(self._registered):
            self.unregister_server(name)

    def register_bridge_tools(
        self,
        list_handler: Callable[..., Any],
        read_handler: Callable[..., Any],
    ) -> None:
        """注册 mcp__list_resources + mcp__read_resource 桥接工具（幂等；冲突回滚）。"""
        if self._bridge_registered:
            return
        # --- mcp__list_resources ---
        if self._registry.get_schema(_BRIDGE_LIST_TOOL) is not None:
            # 命名冲突：server 名为 "mcp" 且其工具叫 "list_resources" 时，namespaced 名同为
            # mcp__list_resources（registry.register 重复注册会静默覆盖）。不覆盖 server 工具——
            # 告警跳过，保留 server 原工具（极端边缘情况，fail-safe 不静默丢工具）。
            logger.warning(
                "mcp__list_resources 命名冲突（registry 已有同名工具，疑似 server 'mcp' 注册），跳过桥接注册"
            )
            return
        list_schema = ToolSchema(
            name=_BRIDGE_LIST_TOOL,
            description="列出所有已连 MCP server 暴露的资源。返回 JSON 数组，每元素含 server/uri/name/description。",
            parameters={"type": "object", "properties": {}, "required": []},
            annotations=ToolAnnotations(readOnlyHint=True),
        )
        self._registry.register(list_schema, list_handler)

        # --- mcp__read_resource ---
        if self._registry.get_schema(_BRIDGE_READ_TOOL) is not None:
            logger.warning("mcp__read_resource 命名冲突（registry 已有同名工具），跳过桥接注册")
            # 回滚已注册的 list_resources
            self._registry.unregister(_BRIDGE_LIST_TOOL)
            return
        read_schema = ToolSchema(
            name=_BRIDGE_READ_TOOL,
            description="读取指定 MCP server 上某 URI 的资源内容。server 必填，uri 为完整资源 URI。返回文本内容。",
            parameters={
                "type": "object",
                "properties": {
                    "server": {"type": "string", "description": "目标 MCP server 名"},
                    "uri": {"type": "string", "description": "资源 URI"},
                },
                "required": ["server", "uri"],
            },
            annotations=ToolAnnotations(readOnlyHint=True),
        )
        self._registry.register(read_schema, read_handler)

        self._bridge_registered = True
        logger.info("MCP 桥接工具 'mcp__list_resources' 和 'mcp__read_resource' 已注册")
