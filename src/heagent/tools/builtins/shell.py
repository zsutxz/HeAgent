"""Shell 命令执行工具。

通过 asyncio.create_subprocess_shell 异步执行命令，
捕获 stdout/stderr 并设置超时保护。
"""

from __future__ import annotations

import asyncio

from heagent.tools.decorator import tool


@tool
async def shell(command: str, timeout: int = 120) -> str:
    """Execute a shell command and return output."""
    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        # 组装结果：退出码 + stdout + stderr
        result = f"exit_code={proc.returncode}\n"
        if stdout:
            result += f"stdout:\n{stdout.decode('utf-8', errors='replace')}"
        if stderr:
            result += f"stderr:\n{stderr.decode('utf-8', errors='replace')}"
        return result
    except TimeoutError:
        return f"exit_code=-1\nstderr: Command timed out after {timeout}s"
