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
import types
from typing import TYPE_CHECKING, Any, Union, get_args, get_origin, get_type_hints

from heagent.tools.registry import ToolRegistry
from heagent.types import ToolAnnotations, ToolSchema

if TYPE_CHECKING:
    from collections.abc import Callable

# Python 类型 → JSON Schema 类型 的映射表
_TYPE_MAP: dict[type, str] = {
    int: "integer",
    float: "number",
    bool: "boolean",
    str: "string",
}


def _resolve_schema_type(annotation: Any) -> tuple[str, bool]:
    """解析 Python 类型注解为 (JSON Schema 类型名, 是否可空)。

    支持 ``int | None``、``Optional[int]``、``Union[str, int]`` 等 Union 语法。
    对于含 ``None`` 的 Union，提取非 ``NoneType`` 的基础类型并标记 nullable。
    无法精确映射时 fallback 到 ``"string"``。
    """
    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin is types.UnionType or origin is Union:
        # int | None / Optional[int] / Union[str, int, None]
        non_none = [a for a in args if a is not type(None)]
        is_nullable = len(non_none) < len(args)
        if len(non_none) == 1:
            return _TYPE_MAP.get(non_none[0], "string"), is_nullable
        # 多类型 Union (str | int) 无法精确映射单一 JSON Schema type
        return "string", is_nullable

    return _TYPE_MAP.get(annotation, "string"), False


def tool(
    func: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    enabled: bool = True,
    read_only: bool | None = None,
    destructive: bool | None = None,
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
        read_only: 若为 True，设置 ToolAnnotations.readOnlyHint（供 PolicyEngine 放行）
        destructive: 若为 True，设置 ToolAnnotations.destructiveHint（供 PolicyEngine 审批）
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
            # 解析参数类型（支持 Union / Optional / int | None）
            ptype, is_nullable = _resolve_schema_type(hints.get(param_name, str))
            if is_nullable:
                prop: dict[str, object] = {
                    "anyOf": [{"type": ptype}, {"type": "null"}]
                }
            else:
                prop = {"type": ptype}
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

        # 构建 annotations（若有 read_only 或 destructive 标志）
        annotations: ToolAnnotations | None = None
        if read_only is not None or destructive is not None:
            annotations = ToolAnnotations(
                readOnlyHint=read_only or False,
                destructiveHint=destructive or False,
            )

        # 创建 Schema 并注册到全局 Registry
        schema = ToolSchema(name=tool_name, description=tool_desc, parameters=parameters, annotations=annotations)
        registry = ToolRegistry.get()
        registry.register(schema, fn)
        if not enabled:
            registry.disable(tool_name)  # 注册但不启用
        return fn

    # 区分 @tool 和 @tool(name="...") 两种调用方式
    if func is not None:
        return _register(func)  # @tool 无参数形式
    return _register  # @tool(name="...") 有参数形式，返回装饰器
