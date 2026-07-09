"""工具子进程执行的沙箱后端抽象（CommandRunner）。

为 ``shell`` 等需要 spawn 子进程的工具提供可注入的执行抽象：默认
:class:`PassthroughRunner`（等价 ``asyncio.create_subprocess_shell`` 直接执行），
可替换为 :class:`FirejailBackend`（经 firejail 包裹子进程施加 OS 级隔离）。

注入机制沿用项目既有 :class:`~heagent.tools.runtime.RuntimeSlot`（contextvar）惯例如
``memory`` / ``skills`` / ``cron`` / ``subagent`` / ``workspace_root``：进程级 fallback +
上下文局部 bind。:class:`~heagent.engine.executor.ToolExecutor` 在 ``SANDBOX_REQUIRED``
路径下 ``bind_command_runner(backend)`` 包住 handler 调用，shell handler 内
``get_command_runner()`` 取当前后端；``DIRECT`` 路径不 bind，取默认 Passthrough。

⚠ 安全边界声明：:class:`FirejailBackend` 仅对 **shell 子进程** 产生 OS 级隔离，且 firejail
非完美边界（可被绕过）、Linux-only（Windows 无 firejail）。file / memory 等宿主进程内
I/O 工具不 spawn 子进程，本抽象对它们无意义。仍须整体在 OS 级沙箱内运行，见 CLAUDE.md。
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING, Protocol

from heagent.tools.runtime import RuntimeSlot

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


class CommandRunner(Protocol):
    """执行一条 shell 命令的抽象后端。"""

    async def run(self, command: str, *, timeout: int) -> str:
        """执行 ``command``，返回 ``exit_code=...\nstdout:...\nstderr:...`` 格式结果。"""
        ...


def _format_result(returncode: int | None, stdout: bytes, stderr: bytes) -> str:
    """把子进程退出码与输出组装成与 ``shell`` 工具一致的字符串契约。"""
    result = f"exit_code={returncode}\n"
    if stdout:
        result += f"stdout:\n{stdout.decode('utf-8', errors='replace')}"
    if stderr:
        result += f"stderr:\n{stderr.decode('utf-8', errors='replace')}"
    return result


_TIMEOUT_RESULT = "exit_code=-1\nstderr: Command timed out after {timeout}s"


async def _kill_and_reap(proc: asyncio.subprocess.Process) -> None:
    """超时收尾：SIGKILL 子进程并 ``await wait()`` 回收，避免僵尸 / pipe FD 泄漏。

    ``proc.kill()`` 在进程恰好已退出时抛 ``ProcessLookupError``（超时边界竞态），
    吞掉该竞态；``await proc.wait()`` 确保 reaped、transport 关闭管道。
    """
    with suppress(ProcessLookupError):
        proc.kill()
    await proc.wait()


async def _run_subprocess_shell(command: str, *, timeout: int) -> str:
    """经 ``create_subprocess_shell`` 执行；超时 kill 子进程并返回统一超时串。"""
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        await _kill_and_reap(proc)  # 超时收尾子进程，避免僵尸（原 shell 实现漏了 kill）
        return _TIMEOUT_RESULT.format(timeout=timeout)
    return _format_result(proc.returncode, stdout, stderr)


async def _run_subprocess_exec(argv: Sequence[str], *, timeout: int) -> str:
    """经 ``create_subprocess_exec`` 执行（argv 列表，免双层 shell / 注入）。"""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        await _kill_and_reap(proc)
        return _TIMEOUT_RESULT.format(timeout=timeout)
    return _format_result(proc.returncode, stdout, stderr)


class PassthroughRunner:
    """直接执行后端（不隔离）——等价原 ``shell`` 工具的 ``create_subprocess_shell``。"""

    async def run(self, command: str, *, timeout: int) -> str:
        return await _run_subprocess_shell(command, timeout=timeout)


class FirejailBackend:
    """经 firejail 包裹子进程的后端（OS 级隔离，Linux-only，非完美边界）。

    ``argv = [firejail_path, *extra_args, "--", "sh", "-c", command]``，用
    ``create_subprocess_exec`` 启动 firejail（exec 非 shell，避免双层 shell；``command`` 仍经
    ``sh -c`` 解释，即 shell 工具本意，并非免注入），firejail 再拉起 ``sh -c command``。
    firejail 再拉起 ``sh -c command``。``extra_args`` 透传给 firejail（如
    ``("--private-tmp",)``）；per-profile 参数映射为未来扩展，当前不按 profile 分。
    """

    def __init__(
        self,
        firejail_path: str = "firejail",
        extra_args: Sequence[str] = (),
    ) -> None:
        self._firejail_path = firejail_path
        self._extra_args = tuple(extra_args)

    async def run(self, command: str, *, timeout: int) -> str:
        argv = [self._firejail_path, *self._extra_args, "--", "sh", "-c", command]
        return await _run_subprocess_exec(argv, timeout=timeout)


# —— RuntimeSlot 注入（仿 memory.py 等工具族）——
_command_runner_slot = RuntimeSlot[CommandRunner]("heagent_command_runner")
# 进程级默认：未 bind 时 shell 等 handler 取此单例（DIRECT 路径行为等价原 shell）。
_DEFAULT_RUNNER = PassthroughRunner()


def configure_command_runner(runner: CommandRunner | None) -> None:
    """设进程级 fallback 后端（供无 agent run 的场景，如 CLI 外直接调 shell）。"""
    _command_runner_slot.configure(runner)


def reset_command_runner() -> None:
    """清进程级 fallback（测试隔离用）。"""
    _command_runner_slot.reset()


@contextmanager
def bind_command_runner(runner: CommandRunner | None) -> Iterator[None]:
    """上下文局部覆盖当前后端（供 ToolExecutor 在 SANDBOX_REQUIRED 路径包住 handler 调用）。"""
    with _command_runner_slot.bind(runner):
        yield


def get_command_runner() -> CommandRunner:
    """取当前后端：bind 覆盖 > 进程级 fallback > 默认 Passthrough 单例。"""
    runner = _command_runner_slot.get()
    return runner if runner is not None else _DEFAULT_RUNNER
