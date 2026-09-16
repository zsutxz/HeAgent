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
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from heagent.tools.runtime import RuntimeSlot

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping, Sequence
    from typing import Any


logger = logging.getLogger(__name__)


_TIER_RANK: dict[str, int] = {
    "passthrough": 0,
    "job": 1,
    "firejail": 2,
    "container": 3,
}


class SandboxTier(StrEnum):
    """沙箱后端强度分级（passthrough < job < firejail < container）。

    强度递增；``container`` 档（OS 级强隔离，如 Docker / bubblewrap / AppContainer）
    为预留枚举，当前无实现后端。仅 ``container`` 档允许审批降级
    （:attr:`can_relax_approval`）——弱后端（passthrough/job/firejail）一律维持原
    审批要求（NFR-2，测试锁定）。
    """

    PASSTHROUGH = "passthrough"
    JOB = "job"
    FIREJAIL = "firejail"
    CONTAINER = "container"

    @property
    def rank(self) -> int:
        """强度序（0=最弱，3=最强），供强度比较。"""
        return _TIER_RANK[self.value]

    @property
    def can_relax_approval(self) -> bool:
        """是否允许审批降级——仅 ``container`` 档（OS 级强隔离）可降审批。

        弱后端（passthrough/job/firejail）一律 False：不得因后端强度跳过审批
        （NFR-2，测试锁定）。
        """
        return self is SandboxTier.CONTAINER


class CommandRunner(Protocol):
    """执行一条 shell 命令的抽象后端。"""

    tier: SandboxTier

    async def run(self, command: str, *, timeout: int) -> str:
        """执行 ``command``，返回 ``exit_code=...\nstdout:...\nstderr:...`` 格式结果。"""
        ...


_MAX_CHANNEL_BYTES = 512 * 1024
_TRUNCATION_MARKER = "[truncated]"


def _cap_channel(raw: bytes, limit: int = _MAX_CHANNEL_BYTES) -> str:
    """Decode one channel, keeping head and tail once it exceeds ``limit`` bytes.

    The tail is preserved on purpose: ``SandboxSession`` reads its cwd/exit-code marker
    from the end of stdout.  A single unbounded shell result used to be fed back into
    the model verbatim (one 1.97 MB stdout blew a 1M-token context window).
    """
    if len(raw) <= limit:
        return raw.decode("utf-8", errors="replace")
    # Reserve room for the diagnostic line so the final UTF-8 result, rather
    # than only the raw payload, stays within the per-channel byte budget.
    marker = f"\n{_TRUNCATION_MARKER}"
    marker_bytes = len(marker.encode("utf-8"))
    payload_limit = max(limit - marker_bytes - 1, 0)
    head_bytes = payload_limit // 2
    tail_bytes = payload_limit - head_bytes
    dropped = len(raw) - payload_limit
    head = raw[:head_bytes].decode("utf-8", errors="replace")
    tail = raw[-tail_bytes:].decode("utf-8", errors="replace") if tail_bytes else ""
    detail = f" {dropped} bytes dropped (kept first {head_bytes} and last {tail_bytes})\n"

    # Malformed UTF-8 can expand when decoded with replacement characters.
    # Trim text (tail first, to preserve its final marker) if that expansion
    # would otherwise exceed the byte budget.
    detail_bytes = len((marker + detail).encode("utf-8"))
    available = max(limit - detail_bytes, 0)
    tail_encoded = tail.encode("utf-8")
    if len(tail_encoded) > available:
        tail = tail_encoded[-available:].decode("utf-8", errors="ignore") if available else ""
        tail_encoded = tail.encode("utf-8")
    head_available = max(available - len(tail_encoded), 0)
    head_bytes_text = head.encode("utf-8")
    if len(head_bytes_text) > head_available:
        head = head_bytes_text[:head_available].decode("utf-8", errors="ignore")
    return head + marker + detail + tail


def _format_result(returncode: int | None, stdout: bytes, stderr: bytes) -> str:
    result = f"exit_code={returncode}\n"
    if stdout:
        result += f"stdout:\n{_cap_channel(stdout)}"
    if stderr:
        result += f"stderr:\n{_cap_channel(stderr)}"
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


def scrub_sensitive_env(
    env: Mapping[str, str] | None = None,
    *,
    allowlist: Iterable[str] | None = None,
) -> dict[str, str]:
    """剥离敏感环境变量（``*_API_KEY`` / ``*_TOKEN`` 等），透传其余。纯函数。

    默认从 ``os.environ`` 取源。匹配按键名大小写不敏感（``.upper().endswith(suffix)``）。
    ``allowlist`` 为豁免变量名集合（大小写不敏感精确匹配）：命中者即使匹配敏感后缀也保留；
    未配置（None/空）时行为与现状一致（全剥离）。非真正安全边界——仅减少 casual 凭证泄露，
    须 OS 级沙箱兜底。
    """
    allowed = {name.upper() for name in (allowlist or ())}
    source = dict(os.environ if env is None else env)
    return {
        k: v
        for k, v in source.items()
        if k.upper() in allowed or not any(k.upper().endswith(suffix) for suffix in _SENSITIVE_ENV_SUFFIXES)
    }


def _env_allowlist() -> frozenset[str]:
    """从 Settings 读沙箱 env 豁免 allowlist（惰性 import 防顶层循环）。"""
    from heagent.config import get_settings

    return get_settings().sandbox_env_allowlist_set


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
        logger.warning("kill failed; still attempt pipe cleanup", exc_info=True)
    await asyncio.wait_for(proc.communicate(), timeout=_REAP_WAIT_TIMEOUT)


def _validate_timeout(timeout: int) -> None:
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        raise ValueError(f"timeout must be a positive integer (seconds), got {timeout!r}")


def _spawn_kwargs() -> dict[str, object]:
    """子进程启动的公共 kwargs：双管道 + 新会话（Linux 进程组隔离）+ 剥离敏感环境变量。"""
    kwargs: dict[str, object] = {"stdout": asyncio.subprocess.PIPE, "stderr": asyncio.subprocess.PIPE}
    if sys.platform == "linux":
        kwargs["start_new_session"] = True
    kwargs["env"] = scrub_sensitive_env(allowlist=_env_allowlist())
    return kwargs


async def _supervise_subprocess(proc: asyncio.subprocess.Process, *, timeout: int) -> str:
    """有界等待子进程收尾：超时/取消都先杀进程树，再给出格式化结果。

    超时与取消**两条清理路径必须一致**（否则「被取消」会留下孤儿进程树）——这正是本函数存在的
    理由：shell 与 exec 两条路径曾各持一份逐字副本，2026-09-15 修复收尾不一致时要改两处。
    """
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


async def _run_subprocess_shell(command: str, *, timeout: int) -> str:
    _validate_timeout(timeout)
    proc = await asyncio.create_subprocess_shell(command, **_spawn_kwargs())  # type: ignore[arg-type]
    return await _supervise_subprocess(proc, timeout=timeout)


async def _run_subprocess_exec(argv: Sequence[str], *, timeout: int) -> str:
    _validate_timeout(timeout)
    proc = await asyncio.create_subprocess_exec(*argv, **_spawn_kwargs())  # type: ignore[arg-type]
    return await _supervise_subprocess(proc, timeout=timeout)


class PassthroughRunner:
    """直接执行后端（不隔离）——等价原 ``shell`` 工具的 ``create_subprocess_shell``。"""

    tier = SandboxTier.PASSTHROUGH

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

    tier = SandboxTier.FIREJAIL

    def __init__(
        self,
        firejail_path: str = "firejail",
        extra_args: Sequence[str] = (),
        profiles: Mapping[str, Sequence[str]] | None = None,
        workspace_root: str | None = None,
        network: bool = True,
    ) -> None:
        self._firejail_path = firejail_path
        self._extra_args = tuple(extra_args)
        self._workspace_root = workspace_root
        # P0-2：False 时在 argv 中插入 ``--net=none``（禁止子进程出站）。
        self._network = network
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

        if not self._network:
            # --net=none 必须排在 profile -- 之前；与 profile 参数同为 defense-in-depth，
            # 非完美边界（firejail 本身非安全边界，见模块 docstring）。
            argv.append("--net=none")

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


def _winjob_spawn(command: str, workspace: Path | None) -> subprocess.Popen[bytes]:
    """启动 WinJob 子进程——**单处**决定 ``cwd`` 是否传入（E40-D3 的可测缝）。

    未 bind 会话目录时与改动前逐字段一致（不传 ``cwd``，不改既有进程语义）。抽成模块级
    纯函数（不触任何 Windows 内核 API）使该决定能在非 Windows 平台被断言：原实现把它写在
    ``run()`` 的两条 ``subprocess.Popen`` 分支里，Linux CI 上无法覆盖（测试整段跳过）。

    ⚠ 目录约定而非安全边界：``cwd`` 只决定子进程工作目录，WinJob 不提供任何文件系统 /
    网络隔离（仅进程级 Job Objects），须 OS 级沙箱兜底。
    """
    # noqa 依据：``command`` 就是 ``shell`` 工具的用户/LLM 命令（不可信是本模块的前提），
    # 隔离由 Job Objects + OS 级沙箱兜底承担，而非靠这里「检查输入」；``cmd`` 为 Windows
    # 系统内置解释器，无绝对路径可给（沿用改动前的调用形态）。
    if workspace is None:
        return subprocess.Popen(  # noqa: S603
            ["cmd", "/c", command],  # noqa: S607
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    return subprocess.Popen(  # noqa: S603
        ["cmd", "/c", command],  # noqa: S607
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(workspace),
    )


class WinJobBackend:
    """Windows Job Objects sandbox backend (process-level isolation, Windows-only).

    Uses Windows Job Object API to wrap child processes. When the job handle
    is closed or parent exits, OS auto-terminates all child processes via
    ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``.

    Gracefully degrades to :class:`PassthroughRunner` when unavailable.
    """

    tier = SandboxTier.JOB

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

        # 经 Any 访问：windll / get_last_error 是 Windows 平台专属（typeshed 在 Linux
        # 上不暴露），而 CI 的 mypy 跑在 Ubuntu；Structure / byref / sizeof 等跨平台属性
        # 保持原样，不受影响。
        ctypes_win: Any = ctypes
        kernel32 = ctypes_win.windll.kernel32

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
            err = ctypes_win.get_last_error()
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
                err = ctypes_win.get_last_error()
                logger.error("SetInformationJobObject failed (err=%d)", err)

            # ── Start child process ──
            proc = await asyncio.to_thread(_winjob_spawn, command, get_sandbox_workspace())

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


def sandbox_sessions_root(workspace: Path | None = None) -> Path:
    """工作区下的沙箱会话目录**约定根**：``<workspace 或进程 cwd>/.heagent/sandboxes``。

    纯路径计算、无 I/O。调用方必须看同一个根：``EngineContainer.create_run_context`` 在此
    创建 per-run 目录（经 ``sandbox_session_dir(..., base=...)``），``housekeeping.prune_sandbox_dirs``
    在此回收崩溃 run 的孤儿目录——两处共用本函数，避免「目录约定」漂移成两份字面量。

    注意与 ``sandbox_session_dir(base=...)`` 的区别：后者的 ``base`` 是**整个根**的替代
    （测试注入通道，不再追加 ``.heagent/sandboxes``），本函数才是「工作区 → 约定根」的映射。
    """
    return (workspace if workspace is not None else Path.cwd()) / ".heagent" / "sandboxes"


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


# —— Sandbox session（FR-4：per-run 会话作用域，cwd 跨命令保持 + teardown）——

_MARKER = "HEAGENT_CWD"


class SandboxSession:
    """同一 run 的沙箱会话作用域：持久 workspace + cwd 跨命令保持 + teardown。

    通过在每条命令前 ``cd <cwd>``、末尾上报 ``$PWD``/``%CD%`` 捕获新 cwd 实现跨命令
    状态保持——shell 子进程每次退出后 cwd 丢失，本类把「上一条命令结束时的 cwd」显式
    记录并作为下一条命令的起点（多步操作「写→编译→运行」自然衔接）。

    ⚠ 会话非安全边界：WinJob 仅目录约定、Firejail ``--private`` 亦非完美边界，须
    OS 级沙箱兜底（见 CLAUDE.md）。
    """

    def __init__(self, workspace: str | Path) -> None:
        self.workspace = Path(workspace)
        self.cwd: Path = self.workspace

    def _wrap(self, command: str, *, cmd_shell: bool) -> str:
        """把命令包装成「在 session.cwd 下执行 + 末尾上报新 cwd（marker 行 + 路径行）+ 退出码保持」。

        退出码保持：链尾上报命令（echo/cd/printf）会重置进程级退出码——POSIX 以
        ``__rc=$?; exit "$__rc"`` 复原；Windows 经 ``call echo %^ERRORLEVEL%`` 把真实 rc 随
        marker 行带回（``%^`` 转义 + ``call`` 重解析拿执行后值），由 :meth:`run` 回填。
        用户命令为 ``exit N`` 时 shell 直接终止、marker 缺失：进程 rc 已正确，cwd 保持
        上一条（固有限制）。
        """
        if cmd_shell:
            # Windows cmd：cd /d 跨盘符；末尾 `cd`（无参）输出当前目录作 marker 行后一行。
            # 注意不用 %CD%——cmd /c 在解析阶段就展开 %VAR%，拿不到 cd 后的目录；
            # 同理 %ERRORLEVEL% 直接展开拿到的是执行前旧值，须 %^ 转义 + call 重解析。
            return f'cd /d "{self.cwd}" && {command} & call echo {_MARKER} %^ERRORLEVEL% & cd'
        # POSIX sh：cd 后分组执行（分组不建子 shell，命令内 cd 影响 $PWD）；先捕获 rc、
        # printf 上报 cwd，再 exit 复原真实退出码。
        return f'cd "{self.cwd}" && {{ {command}; }}; __rc=$?; printf "\n{_MARKER}\n%s\n" "$PWD"; exit "$__rc"'

    @staticmethod
    def _extract_cwd(output: str) -> Path | None:
        """从命令输出解析 marker 行（``{MARKER}`` 或 ``{MARKER} <rc>``）后一行的新 cwd；未找到返回 None。"""
        lines = output.splitlines()
        for i, line in enumerate(lines):
            parts = line.strip().split()
            if parts and parts[0] == _MARKER and i + 1 < len(lines):
                path = lines[i + 1].strip()
                if path:
                    return Path(path)
        return None

    @staticmethod
    def _extract_rc(output: str) -> int | None:
        """从 marker 行（``{MARKER} <rc>``）解析用户命令真实退出码；未找到/非整数返回 None。"""
        for line in output.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2 and parts[0] == _MARKER:
                with suppress(ValueError):
                    return int(parts[1])
        return None

    @staticmethod
    def _strip_marker(output: str) -> str:
        """去掉输出里的 marker 行（含可选 rc 尾巴）及其后一行（路径），返回干净输出。"""
        lines = output.splitlines()
        kept: list[str] = []
        skip_next = False
        for line in lines:
            parts = line.strip().split()
            if parts and parts[0] == _MARKER:
                skip_next = True
                continue
            if skip_next:
                skip_next = False
                continue
            kept.append(line)
        return "\n".join(kept)

    @staticmethod
    def _rewrite_exit_code(result: str, rc: int) -> str:
        """把结果首行 ``exit_code=`` 重写为用户命令真实退出码。

        Windows cmd 链尾的 echo/cd 会重置 ERRORLEVEL，进程级返回码恒 0——真实 rc 经
        marker 行带回，此处回填。非 ``exit_code=`` 开头（如超时结果）不改写。
        """
        if not result.startswith("exit_code="):
            return result
        nl = result.find("\n")
        rest = result[nl:] if nl >= 0 else ""
        return f"exit_code={rc}{rest}"

    async def run(self, command: str, *, timeout: int) -> str:
        """在当前会话执行命令：cd 前缀 + 执行 + cwd/rc 回填 + 输出清理。"""
        runner = get_command_runner()
        # Windows 上 create_subprocess_shell 走 cmd.exe（Passthrough/WinJob 均 cmd）；
        # Linux 上 sh（Passthrough/Firejail 均 POSIX）。WinJob 恒 cmd。
        cmd_shell = isinstance(runner, WinJobBackend) or sys.platform == "win32"
        result = await runner.run(self._wrap(command, cmd_shell=cmd_shell), timeout=timeout)
        new_cwd = self._extract_cwd(result)
        if new_cwd is not None:
            self.cwd = new_cwd
        rc = self._extract_rc(result)
        if rc is not None:
            result = self._rewrite_exit_code(result, rc)
        return self._strip_marker(result)

    async def close(self, *, keep: bool) -> None:
        """teardown：按配置清理会话目录（保留/删除）。"""
        if not keep:
            await asyncio.to_thread(shutil.rmtree, self.workspace, ignore_errors=True)


_sandbox_sessions: dict[str, SandboxSession] = {}


def get_or_create_session(run_id: str, workspace: str | Path) -> SandboxSession:
    """按 run_id 获取/创建会话（同一 run 复用同一会话）。"""
    session = _sandbox_sessions.get(run_id)
    if session is None:
        session = SandboxSession(workspace)
        _sandbox_sessions[run_id] = session
    return session


def pop_session(run_id: str) -> SandboxSession | None:
    """取出并移除会话（teardown 用）。"""
    return _sandbox_sessions.pop(run_id, None)


_sandbox_session_slot: RuntimeSlot[SandboxSession] = RuntimeSlot[SandboxSession]("heagent_sandbox_session")


def get_sandbox_session() -> SandboxSession | None:
    return _sandbox_session_slot.get()


@contextmanager
def bind_sandbox_session(session: SandboxSession | None) -> Iterator[None]:
    with _sandbox_session_slot.bind(session):
        yield
