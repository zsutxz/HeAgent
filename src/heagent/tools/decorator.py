"""@tool 装饰器 — 从函数签名自动生成工具 Schema 并注册到 Registry。

核心能力：
  - 提取函数名作为工具名（可自定义）
  - 提取 docstring 首行作为工具描述
  - 从类型提示自动映射 Python 类型 → JSON Schema 类型
  - 自动注册到 ToolRegistry（进程级单例）

用法：
    @tool
    def my_tool(param: str, count: int = 5) -> str:
        \"\"\"工具描述。\"\"\"
        ...

    @tool(name="custom_name", enabled=False)
    def another_tool():
        ...
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any, get_type_hints

from heagent.tools.registry import ToolRegistry
from heagent.types import ToolSchema

if TYPE_CHECKING:
    from collections.abc import Callable

# Python 类型 → JSON Schema 类型 的映射表
_TYPE_MAP: dict[type, str] = {
    int: "integer",
    float: "number",
    bool: "boolean",
    str: "string",
}


def tool(
    func: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    enabled: bool = True,
) -> Callable[..., Any]:
    """将函数注册为 Agent 可调用的工具。

    支持两种使用方式：
      @tool              — 直接装饰，函数名即工具名
      @tool(name="...")  — 带参数装饰，可自定义名称/描述/启用状态

    参数：
        func: 被装饰的函数（直接使用 @tool 时自动传入）
        name: 自定义工具名（默认使用函数名）
        description: 自定义描述（默认使用 docstring 首行）
        enabled: 是否启用（False 则注册但不可用）
    """

    def _register(fn: Callable[..., Any]) -> Callable[..., Any]:
        # 确定工具名称：显式指定 > 函数名
        tool_name = name or fn.__name__
        # 确定工具描述：显式指定 > docstring 首行
        tool_desc = description or (fn.__doc__ or "").strip().split("\n")[0]

        # 从函数签名提取类型提示
        hints = get_type_hints(fn)
        sig = inspect.signature(fn)

        # 构建 JSON Schema 的 properties 和 required
        properties: dict[str, object] = {}
        required: list[str] = []
        for param_name, param in sig.parameters.items():
            if param_name == "self":
                continue
            # 获取参数类型，默认为 string
            ptype = hints.get(param_name, str)
            prop: dict[str, object] = {"type": _TYPE_MAP.get(ptype, "string")}
            # 有默认值的参数标记 default
            if param.default is not inspect.Parameter.empty:
                prop["default"] = param.default
            properties[param_name] = prop
            # 无默认值的参数标记为 required
            if param.default is inspect.Parameter.empty:
                required.append(param_name)

        # 组装完整的参数 Schema
        parameters: dict[str, object] = {"type": "object", "properties": properties}
        if required:
            parameters["required"] = required

        # 创建 Schema 并注册到全局 Registry
        schema = ToolSchema(name=tool_name, description=tool_desc, parameters=parameters)
        registry = ToolRegistry.get()
        registry.register(schema, fn)
        if not enabled:
            registry.disable(tool_name)  # 注册但不启用
        return fn

    # 区分 @tool 和 @tool(name="...") 两种调用方式
    if func is not None:
        return _register(func)  # @tool 无参数形式
    return _register  # @tool(name="...") 有参数形式，返回装饰器
