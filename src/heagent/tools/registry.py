"""工具注册中心 — 进程级单例，管理所有已注册的工具。

ToolRegistry 维护三组数据：
  - _tools: name → ToolSchema（工具的 JSON Schema 描述）
  - _handlers: name → callable（工具的实际执行函数）
  - _disabled: set[str]（已禁用的工具名称集合）

通过 @tool 装饰器自动注册，AgentLoop 通过 get_handler() 查找并执行。
"""

from __future__ import annotations

from heagent.types import ToolSchema


class ToolRegistry:
    """工具注册中心（进程级单例）。

    使用方式：
        registry = ToolRegistry.get()    # 获取单例
        registry.register(schema, fn)    # 注册工具
        handler = registry.get_handler(name)  # 查找执行函数
    """

    _instance: ToolRegistry | None = None  # 单例缓存

    def __init__(self) -> None:
        self._tools: dict[str, ToolSchema] = {}     # 工具 Schema 注册表
        self._handlers: dict[str, object] = {}       # 工具执行函数注册表
        self._disabled: set[str] = set()             # 已禁用工具集合

    @classmethod
    def get(cls) -> ToolRegistry:
        """获取全局单例。首次调用时创建。"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """清除单例（测试隔离用）。"""
        cls._instance = None

    def register(self, schema: ToolSchema, handler: object) -> None:
        """注册工具：同时记录 Schema 和对应的执行函数。

        重复注册同一名称会覆盖旧值，并自动从禁用集合中移除。
        """
        self._tools[schema.name] = schema
        self._handlers[schema.name] = handler
        self._disabled.discard(schema.name)  # 重新注册自动启用

    def unregister(self, name: str) -> None:
        """注销工具：同时移除 Schema、handler 和禁用状态。"""
        self._tools.pop(name, None)
        self._handlers.pop(name, None)
        self._disabled.discard(name)

    def get_schema(self, name: str) -> ToolSchema | None:
        """根据名称查找工具 Schema（用于发送给 LLM）。"""
        return self._tools.get(name)

    def get_handler(self, name: str) -> object | None:
        """根据名称查找工具执行函数（用于 AgentLoop 实际调用）。"""
        return self._handlers.get(name)

    def enable(self, name: str) -> None:
        """启用指定工具。"""
        self._disabled.discard(name)

    def disable(self, name: str) -> None:
        """禁用指定工具（Schema 和 handler 保留，但不发送给 LLM）。"""
        if name in self._tools:
            self._disabled.add(name)

    def is_enabled(self, name: str) -> bool:
        """检查工具是否已注册且未禁用。"""
        return name in self._tools and name not in self._disabled

    def all_schemas(self) -> list[ToolSchema]:
        """返回所有已注册的工具 Schema（包括禁用的）。"""
        return list(self._tools.values())

    def enabled_schemas(self) -> list[ToolSchema]:
        """返回所有已启用的工具 Schema（发送给 LLM 的列表）。"""
        return [s for s in self._tools.values() if s.name not in self._disabled]

    def list_names(self) -> list[str]:
        """返回所有已注册的工具名称。"""
        return list(self._tools.keys())
