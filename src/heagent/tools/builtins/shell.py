"""Shell 命令执行工具。

经 :func:`~heagent.tools.sandbox.get_command_runner` 取当前 :class:`CommandRunner`
后端执行命令——默认 :class:`~heagent.tools.sandbox.PassthroughRunner`（直接
``create_subprocess_shell``）；``SANDBOX_REQUIRED`` 路径下由
:class:`~heagent.engine.executor.ToolExecutor` ``bind_command_runner`` 注入沙箱后端
（如 :class:`~heagent.tools.sandbox.FirejailBackend`）。stdout/stderr 捕获与超时保护
由后端负责，本 handler 仅声明参数与委托。
"""

from __future__ import annotations

from heagent.tools.decorator import tool
from heagent.tools.sandbox import get_command_runner


@tool
async def shell(command: str, timeout: int = 120) -> str:
    """Execute a shell command and return output."""
    return await get_command_runner().run(command, timeout=timeout)
