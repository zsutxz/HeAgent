"""Shell 命令执行工具。

执行面**会话优先**（FR-4 / B1 成文）：RuntimeSlot 注入的
:class:`~heagent.tools.sandbox.SandboxSession`（executor 沙箱路径经
``bind_sandbox_session`` 送达）存在时走 ``session.run``——同一 run 内 cwd 跨命令保持；
无会话时回落 ``get_command_runner()``（RuntimeSlot 注入的后端，默认 Passthrough；
``SANDBOX_REQUIRED`` 路径下 executor ``bind_command_runner`` 注入的沙箱后端）。会话优先
此前只活在代码里，此处成文；代码零变化（B1）。

stdout/stderr 捕获与超时保护由后端/会话负责，本 handler 仅声明参数与委托。
"""

from __future__ import annotations

from heagent.tools.decorator import tool
from heagent.tools.sandbox import get_command_runner, get_sandbox_session


@tool
async def shell(command: str, timeout: int = 120) -> str:
    """Execute a shell command and return output."""
    session = get_sandbox_session()
    if session is not None:
        return await session.run(command, timeout=timeout)
    return await get_command_runner().run(command, timeout=timeout)
