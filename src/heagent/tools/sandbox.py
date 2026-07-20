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
import logging
import os
import shutil
import signal
import sys
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING, Protocol

from heagent.tools.runtime import RuntimeSlot

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping, Sequence


logger = logging.getLogger(__name__)


class CommandRunner(Protocol):
    """执行一条 shell 命令的抽象后端。"""

    async def run(self, command: str, *, timeout: int) -> str:
        """执行 ``command``，返回 ``exit_code=...\nstdout:...\nstderr:...`` 格式结果。"""
        ...


def _format_result(returncode: int | None, stdout: bytes, stderr: bytes) -> str:
    result = f"exit_code={returncode}\n"
    if stdout:
        result += f"stdout:\n{stdout.decode('utf-8', errors='replace')}"
    if stderr:
        result += f"stderr:\n{stderr.decode('utf-8', errors='replace')}"
    return result


_TIMEOUT_RESULT = "exit_code=-1\nstderr: Command timed out after {timeout}s"
_REAP_WAIT_TIMEOUT = 5.0


async def _kill_and_reap(proc: asyncio.subprocess.Process) -> None:
    try:
        if sys.platform == "linux":
            with suppress(ProcessLookupError):
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        else:
            with suppress(ProcessLookupError):
                proc.kill()
    except OSError:
        logger.warning("kill failed; still attempt wait to reap pipe FD", exc_info=True)
    await asyncio.wait_for(proc.wait(), timeout=_REAP_WAIT_TIMEOUT)


def _validate_timeout(timeout: int) -> None:
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        raise ValueError(f"timeout must be a positive integer (seconds), got {timeout!r}")


async def _run_subprocess_shell(command: str, *, timeout: int) -> str:
    _validate_timeout(timeout)
    kwargs: dict[str, object] = {"stdout": asyncio.subprocess.PIPE, "stderr": asyncio.subprocess.PIPE}
    if sys.platform == "linux":
        kwargs["start_new_session"] = True
    proc = await asyncio.create_subprocess_shell(command, **kwargs)  # type: ignore[arg-type]
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        try:
            await _kill_and_reap(proc)
        except Exception:
            logger.debug("timeout cleanup: _kill_and_reap failed; subprocess/pipe may leak", exc_info=True)
        return _TIMEOUT_RESULT.format(timeout=timeout)
    except asyncio.CancelledError:
        try:
            await _kill_and_reap(proc)
        except BaseException:
            logger.debug("cancel cleanup: _kill_and_reap failed; subprocess/pipe may leak", exc_info=True)
        raise
    return _format_result(proc.returncode, stdout, stderr)


async def _run_subprocess_exec(argv: Sequence[str], *, timeout: int) -> str:
    _validate_timeout(timeout)
    kwargs: dict[str, object] = {"stdout": asyncio.subprocess.PIPE, "stderr": asyncio.subprocess.PIPE}
    if sys.platform == "linux":
        kwargs["start_new_session"] = True
    proc = await asyncio.create_subprocess_exec(*argv, **kwargs)  # type: ignore[arg-type]
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        try:
            await _kill_and_reap(proc)
        except Exception:
            logger.debug("timeout cleanup: _kill_and_reap failed; subprocess/pipe may leak", exc_info=True)
        return _TIMEOUT_RESULT.format(timeout=timeout)
    except asyncio.CancelledError:
        try:
            await _kill_and_reap(proc)
        except BaseException:
            logger.debug("cancel cleanup: _kill_and_reap failed; subprocess/pipe may leak", exc_info=True)
        raise
    return _format_result(proc.returncode, stdout, stderr)


class PassthroughRunner:
    """直接执行后端（不隔离）——等价原 ``shell`` 工具的 ``create_subprocess_shell``。"""

    async def run(self, command: str, *, timeout: int) -> str:
        return await _run_subprocess_shell(command, timeout=timeout)


class FirejailBackend:
    """经 firejail 包裹子进程的后端（OS 级隔离，Linux-only，非完美边界）。

    用 ``create_subprocess_exec`` 启动 firejail。``extra_args`` 透传给 firejail；
    ``profiles`` 提供 per-profile 参数映射（如 ``{"network-isolated": ("--net=none",)}``），
    使 ``RoleSpec.sandbox_profile`` 产生实际隔离差异。``workspace_root`` 自动映射为
    ``--private`` 参数（OS 级文件系统隔离）。firejail 不可用时通过 :meth:`run` 优雅降级
    到 PassthroughRunner。
    """

    def __init__(
        self,
        firejail_path: str = "firejail",
        extra_args: Sequence[str] = (),
        profiles: Mapping[str, Sequence[str]] | None = None,
        workspace_root: str | None = None,
    ) -> None:
        self._firejail_path = firejail_path
        self._extra_args = tuple(extra_args)
        self._workspace_root = workspace_root
        self._profiles: dict[str, tuple[str, ...]] = {}
        if profiles:
            self._profiles = {k: tuple(v) for k, v in profiles.items()}

        # FR-S3：构造期检测 firejail 可用性
        resolved = shutil.which(self._firejail_path)
        if resolved is None:
            self._firejail_available = False
            self._resolved_path: str | None = None
            logger.warning(
                "firejail not found at %r, sandbox disabled — falling back to passthrough",
                self._firejail_path,
            )
        else:
            self._firejail_available = True
            self._resolved_path = resolved

    @property
    def available(self) -> bool:
        """firejail 是否可用（构造期 ``shutil.which`` 检测结果）。"""
        return self._firejail_available

    def _build_argv(
        self,
        command: str,
        profile: str | None,
        workspace_root: str | None = None,
    ) -> list[str]:
        """纯函数：给定 command 与 profile 名，返回完整 firejail argv。

        拼接顺序：``[firejail, *extra_args, --private=<ws>, *profile_args, "--", "sh", "-c", command]``。
        ``workspace_root`` 未显式传入时默认取 ``self._workspace_root``。
        """
        if workspace_root is None:
            workspace_root = self._workspace_root
        argv: list[str] = [self._resolved_path or self._firejail_path]
        argv.extend(self._extra_args)

        if workspace_root:
            argv.append(f"--private={workspace_root}")

        if profile is not None and profile in self._profiles:
            argv.extend(self._profiles[profile])

        argv.extend(["--", "sh", "-c", command])
        return argv

    async def run(self, command: str, *, timeout: int) -> str:
        # FR-S3：优雅降级——firejail 不可用时走 Passthrough
        if not self._firejail_available:
            return await PassthroughRunner().run(command, timeout=timeout)

        profile = get_sandbox_profile()
        argv = self._build_argv(command, profile)
        return await _run_subprocess_exec(argv, timeout=timeout)


# —— RuntimeSlot 注入 ——
_command_runner_slot = RuntimeSlot[CommandRunner]("heagent_command_runner")
_DEFAULT_RUNNER = PassthroughRunner()


def configure_command_runner(runner: CommandRunner | None) -> None:
    _command_runner_slot.configure(runner)


def reset_command_runner() -> None:
    _command_runner_slot.reset()


@contextmanager
def bind_command_runner(runner: CommandRunner | None) -> Iterator[None]:
    with _command_runner_slot.bind(runner):
        yield


def get_command_runner() -> CommandRunner:
    runner = _command_runner_slot.get()
    return runner if runner is not None else _DEFAULT_RUNNER


# —— Sandbox profile contextvar（S1-2：executor 注入 pipeline）——
_sandbox_profile_slot: RuntimeSlot[str | None] = RuntimeSlot[str | None]("heagent_sandbox_profile")


def get_sandbox_profile() -> str | None:
    return _sandbox_profile_slot.get()


def reset_sandbox_profile() -> None:
    _sandbox_profile_slot.reset()


@contextmanager
def bind_sandbox_profile(profile: str | None) -> Iterator[None]:
    with _sandbox_profile_slot.bind(profile):
        yield
