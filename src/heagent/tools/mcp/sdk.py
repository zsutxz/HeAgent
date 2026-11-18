"""mcp SDK 导入边界：可选依赖的惰性导入 + 缺失时的显性安装诊断。

``mcp`` 属**可选能力**（``[mcp]`` extra）：核心安装不带它。因此本包内任何模块都不得在
import 期直接 ``from mcp... import ...``——那样 ``import heagent`` 就会因缺可选依赖而炸。
取用 SDK 的唯一通道是本模块：

- :func:`import_mcp` —— 导入 SDK 模块，缺失时抛 :class:`McpSdkMissingError`（带安装命令）；
- :func:`mcp_types` —— 按名取 ``mcp.types`` 成员（同上，路径用于 isinstance 判定）；
- :func:`require_sdk` —— 构造期自检，早于任何连接尝试就 fail loud。

DAG：本模块仅依赖 ``pub.exceptions`` 与标准库，永不导入本包其它子模块（避免与
``session_api`` / ``mapping`` 形成环）。
"""

from __future__ import annotations

import importlib
from typing import TYPE_CHECKING, Any

from heagent.pub.exceptions import HeAgentError

if TYPE_CHECKING:
    from types import ModuleType

#: 用户可执行的一条命令（诊断文案里原样出现，改动前先 grep 文档与测试）。
INSTALL_HINT = 'pip install "heagent[mcp]"'

_MESSAGE = "{feature}需要可选依赖 mcp，但当前环境未安装。安装：{hint}"


class McpSdkMissingError(HeAgentError):
    """可选依赖 ``mcp`` 不可用。

    继承 ``HeAgentError`` 是为了让既有入口层（``cli/console.py`` 的 ``except HeAgentError``）
    把它渲染成一行可执行提示，而不是裸 traceback。非 MCP 功能不受影响。
    """


def import_mcp(module: str = "mcp", *, feature: str = "MCP 支持") -> ModuleType:
    """导入 mcp SDK（子）模块；缺依赖时抛带安装提示的 :class:`McpSdkMissingError`。"""
    try:
        return importlib.import_module(module)
    except ImportError as exc:  # ModuleNotFoundError 是 ImportError 子类
        raise McpSdkMissingError(_MESSAGE.format(feature=feature, hint=INSTALL_HINT)) from exc


def mcp_types(*names: str) -> tuple[Any, ...]:
    """按名取 ``mcp.types`` 成员（调用期解析，不在 import 期触碰 SDK）。

    返回顺序与 ``names`` 一致；名字不存在即 ``AttributeError``（SDK 版本漂移的真实缺陷，
    不掩盖）。
    """
    types = import_mcp("mcp.types")
    return tuple(getattr(types, name) for name in names)


def require_sdk(feature: str = "MCP 支持") -> None:
    """构造期自检：SDK 不可用即 fail loud（早于连接尝试，用户拿到的是安装提示而非连接失败）。"""
    import_mcp("mcp", feature=feature)
