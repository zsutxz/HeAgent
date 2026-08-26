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
import subprocess
import sys
from contextlib import contextmanager, suppress
from pathlib import Path
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

_SENSITIVE_ENV_SUFFIXES = (
    "_API_KEY",
    "_API_KEYS",
    "_TOKEN",
    "_SECRET",
    "_PASSWORD",
    "_CREDENTIALS",
    "_PRIVATE_KEY",
)


def scrub_sensitive_env(env: Mapping[str, str] | None = None) -> dict[str, str]:
    """剥离敏感环境变量（``*_API_KEY`` / ``*_TOKEN`` 等），透传其余。纯函数。

    默认从 ``os.environ`` 取源。匹配按键名大小写不敏感（``.upper().endswith(suffix)``）。
    非真正安全边界——仅减少 casual 凭证泄露，须 OS 级沙箱兜底。
    """
    source = dict(os.environ if env is None else env)
    return {
        k: v
        for k, v in source.items()
        if not any(k.upper().endswith(suffix) for suffix in _SENSITIVE_ENV_SUFFIXES)
    }



async def _kill_and_reap(proc: asyncio.subprocess.Process) -> None:
    try:
        if sys.platform == "linux":
            # start_new_session=True 保证 proc.pid 即进程组长 pid，直接对其组发 SIGKILL。
            # 不用 os.getpgid(proc.pid)：子进程已退出且 PID 被 OS 回收时，getpgid 会返回别的
            # 进程的 pgid，导致 killpg 误杀无关进程组（PID 复用竞态）。
            with suppress(ProcessLookupError):
                os.killpg(proc.pid, signal.SIGKILL)
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
    kwargs["env"] = scrub_sensitive_env()
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
    kwargs["env"] = scrub_sensitive_env()
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
        # FR-1：per-run 沙箱会话目录（经 executor bind）优先作为 --private 根；
        # 未 bind（None）时 _build_argv 回退构造期 self._workspace_root，行为与现状一致。
        workspace = get_sandbox_workspace()
        argv = self._build_argv(
            command,
            profile,
            workspace_root=str(workspace) if workspace is not None else None,
        )
        return await _run_subprocess_exec(argv, timeout=timeout)


class WinJobBackend:
    """Windows Job Objects sandbox backend (process-level isolation, Windows-only).

    Uses Windows Job Object API to wrap child processes. When the job handle
    is closed or parent exits, OS auto-terminates all child processes via
    ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``.

    Gracefully degrades to :class:`PassthroughRunner` when unavailable.
    """

    def __init__(self) -> None:
        self._available: bool | None = None

    @staticmethod
    def available() -> bool:
        """Windows Job Objects available on current platform."""
        if sys.platform != "win32":
            return False
        try:
            import ctypes

            _ = ctypes.windll.kernel32.CreateJobObjectW
            return True
        except (ImportError, AttributeError, OSError):
            return False

    async def run(self, command: str, *, timeout: int) -> str:
        if not self.available():
            logger.warning("WinJobBackend not available; falling back to Passthrough")
            return await PassthroughRunner().run(command, timeout=timeout)

        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32

        # ── Job Object constants ──
        JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

        class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_ulonglong),
                ("PerJobUserTimeLimit", ctypes.c_ulonglong),
                ("LimitFlags", ctypes.c_ulong),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_ulong),
                ("Affinity", ctypes.c_ulonglong),
                ("PriorityClass", ctypes.c_ulong),
                ("SchedulingClass", ctypes.c_ulong),
            ]

        class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
                ("IoInfo", ctypes.c_byte * 48),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t),
            ]

        # ── Create Job Object ──
        hJob = kernel32.CreateJobObjectW(None, None)
        if not hJob:
            err = ctypes.get_last_error()
            logger.error("CreateJobObject failed (err=%d), falling back to Passthrough", err)
            return await PassthroughRunner().run(command, timeout=timeout)

        try:
            # Configure job limits
            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE

            JobObjectExtendedLimitInformation = 9
            ret = kernel32.SetInformationJobObject(
                wintypes.HANDLE(hJob),
                JobObjectExtendedLimitInformation,
                ctypes.byref(info),
                ctypes.sizeof(info),
            )
            if not ret:
                err = ctypes.get_last_error()
                logger.error("SetInformationJobObject failed (err=%d)", err)

            # ── Start child process ──
            # FR-1：per-run 沙箱会话目录（经 executor bind）作为子进程 cwd——
            # 目录约定 only：仅决定命令的工作目录，无任何文件系统/网络隔离
            # （WinJob 仅做进程级隔离），非安全边界。未 bind 时不传 cwd（与现状一致）。
            workspace = get_sandbox_workspace()
            if workspace is not None:
                proc = await asyncio.to_thread(
                    subprocess.Popen,
                    ["cmd", "/c", command],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    cwd=str(workspace),
                )
            else:
                proc = await asyncio.to_thread(
                    subprocess.Popen,
                    ["cmd", "/c", command],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )

            # Assign to job object
            kernel32.AssignProcessToJobObject(
                wintypes.HANDLE(hJob),
                wintypes.HANDLE(int(proc._handle)),  # type: ignore[attr-defined]  # Windows 私有句柄属性
            )

            # ── Wait for completion ──
            try:
                stdout, stderr = await asyncio.wait_for(
                    asyncio.to_thread(proc.communicate),
                    timeout=timeout,
                )
                return _format_result(proc.returncode, stdout, stderr)
            except TimeoutError:
                try:
                    proc.kill()
                    await asyncio.to_thread(proc.wait)
                except Exception as _exc:
                    logger.debug("timeout cleanup: kill/wait failed", exc_info=True)
                return _TIMEOUT_RESULT.format(timeout=timeout)
            except asyncio.CancelledError:
                try:
                    proc.kill()
                    await asyncio.to_thread(proc.wait)
                except BaseException:
                    logger.debug("cancel cleanup: kill/wait failed", exc_info=True)
                raise

        finally:
            kernel32.CloseHandle(wintypes.HANDLE(hJob))

    def __repr__(self) -> str:
        return f"WinJobBackend(available={self.available()})"


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


# —— Sandbox session workspace（FR-1：per-run 沙箱会话目录）——


def sandbox_session_dir(run_id: str, *, base: Path | None = None) -> Path:
    """返回 ``<base>/<run_id>/`` 沙箱会话目录并幂等创建（``mkdir(parents=True, exist_ok=True)``）。

    幂等目录解析（有 I/O 副作用、默认根依赖进程 cwd）：默认根为
    ``Path.cwd()/".heagent"/"sandboxes"``，``base`` 显式传入时替代整个默认根
    （EngineContainer.create_run_context 以 workspace_root 回退链锚定）。同一 ``run_id``
    重复调用返回同一路径；不依赖任何执行器实例状态。

    ``run_id`` 非法（空串 / 含路径分隔符 ``/`` 或 ``\\`` / 含 ``\\x00`` / ``.`` / ``..`` /
    绝对路径 / Windows 盘符前缀如 ``C:evil``）抛 :class:`ValueError`——防任意 metadata
    字符串直入 ``--private=`` / ``cwd=``；目标路径已存在且为符号链接同样抛
    :class:`ValueError`（防符号链接逃逸锚定根）。

    ⚠ 目录约定而非安全边界：WinJob 后端仅将其作为子进程 cwd（无文件系统/网络隔离）；
    Firejail 将其作为 ``--private`` 根（OS 级文件系统隔离，但 firejail 非完美边界）。
    """

    if (
        not run_id
        or run_id in (".", "..")
        or "/" in run_id
        or "\\" in run_id
        or "\x00" in run_id
        or Path(run_id).is_absolute()
        or Path(run_id).drive
    ):
        raise ValueError(f"invalid run_id: {run_id!r} (must be a single non-traversal path segment)")
    root = base if base is not None else Path.cwd() / ".heagent" / "sandboxes"
    path = root / run_id
    if path.is_symlink():
        raise ValueError(f"sandbox session path is a symlink (refusing to anchor through it): {path}")
    path.mkdir(parents=True, exist_ok=True)
    return path


_sandbox_workspace_slot: RuntimeSlot[Path | None] = RuntimeSlot[Path | None]("heagent_sandbox_workspace")


def get_sandbox_workspace() -> Path | None:
    return _sandbox_workspace_slot.get()


def reset_sandbox_workspace() -> None:
    _sandbox_workspace_slot.reset()


@contextmanager
def bind_sandbox_workspace(path: Path | None) -> Iterator[None]:
    with _sandbox_workspace_slot.bind(path):
        yield
