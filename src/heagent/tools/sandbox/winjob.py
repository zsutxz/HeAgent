"""Windows Job Objects 沙箱后端（进程级隔离，Windows-only）。

Job Object API 包裹子进程：句柄关闭或父进程退出时 OS 经
``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`` 自动终止全部子进程。不可用时优雅降级
Passthrough。收尾语义（``_format_result`` / ``_TIMEOUT_RESULT``）复用
:mod:`.process` 内核。

⚠ 非完美边界：仅进程级隔离，无文件系统 / 网络隔离，须 OS 级沙箱兜底（见 CLAUDE.md）。
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
from typing import TYPE_CHECKING

from heagent.tools.sandbox.contracts import SandboxTier, get_sandbox_workspace
from heagent.tools.sandbox.process import (
    _REAP_WAIT_TIMEOUT,
    _TIMEOUT_RESULT,
    PassthroughRunner,
    _env_allowlist,
    _format_result,
    scrub_sensitive_env,
)

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any


logger = logging.getLogger(__name__)


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
            env=scrub_sensitive_env(allowlist=_env_allowlist()),
        )
    return subprocess.Popen(  # noqa: S603
        ["cmd", "/c", command],  # noqa: S607
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=str(workspace),
        env=scrub_sensitive_env(allowlist=_env_allowlist()),  # Phase 4 V1：与 asyncio 路径同一卫生基线
    )


def _winjob_platform_available() -> bool:
    """平台探测：非 Windows 即不可用；Windows 上经 ctypes 探针确认 Job Object API。"""
    if sys.platform != "win32":
        return False
    try:
        import ctypes

        _ = ctypes.windll.kernel32.CreateJobObjectW
        return True
    except (ImportError, AttributeError, OSError):
        return False


class WinJobBackend:
    """Windows Job Objects sandbox backend (process-level isolation, Windows-only).

    Uses Windows Job Object API to wrap child processes. When the job handle
    is closed or parent exits, OS auto-terminates all child processes via
    ``JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE``.

    Gracefully degrades to :class:`PassthroughRunner` when unavailable.
    """

    tier = SandboxTier.JOB

    def __init__(self, memory_limit_mb: int = 0, cpu_seconds: int = 0, nproc_limit: int = 0) -> None:
        # 资源限额（2026-09-17 硬化批，2026-09-18 补进程数，0=关闭）：
        # JOB_OBJECT_LIMIT_JOB_MEMORY / PROCESS_TIME / ACTIVE_PROCESS。
        # 触发为显性失败（进程被终止 → 非零退出码）。
        self._memory_limit_mb = memory_limit_mb
        self._cpu_seconds = cpu_seconds
        self._nproc_limit = nproc_limit

    @property
    def available(self) -> bool:
        """Windows Job Objects available on current platform."""
        return _winjob_platform_available()

    async def run(self, command: str, *, timeout: int) -> str:
        if not self.available:
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
            # Configure job limits：KILL_ON_JOB_CLOSE 恒开；资源限额按配置叠加（0=关闭，
            # flags 与现状一致）。限额触发 → 进程被终止 → 非零退出码（显性失败）。
            # ⚠ 常量值以 Windows SDK（winnt.h）为准：PROCESS_TIME=0x2、ACTIVE_PROCESS=0x8。
            # 2026-09-18 修正：此前 PROCESS_TIME 误写为 0x8（那是 ACTIVE_PROCESS 的位），
            # 于是配了 CPU 限额时置位的是 ACTIVE_PROCESS 而 ActiveProcessLimit 仍为 0——
            # 时间限额没生效，反而施加了「活动进程上限 0」。
            JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
            JOB_OBJECT_LIMIT_PROCESS_TIME = 0x00000002
            JOB_OBJECT_LIMIT_ACTIVE_PROCESS = 0x00000008
            info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if self._memory_limit_mb > 0:
                info.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_JOB_MEMORY
                info.JobMemoryLimit = self._memory_limit_mb * 1024 * 1024
            if self._cpu_seconds > 0:
                info.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_PROCESS_TIME
                # PerProcessUserTimeLimit 单位为 100ns。
                info.BasicLimitInformation.PerProcessUserTimeLimit = self._cpu_seconds * 10_000_000
            if self._nproc_limit > 0:
                info.BasicLimitInformation.LimitFlags |= JOB_OBJECT_LIMIT_ACTIVE_PROCESS
                info.BasicLimitInformation.ActiveProcessLimit = self._nproc_limit

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
                    # Phase 4 V2：有界回收——无界 wait 在孙进程持管道时可无限挂起。
                    await asyncio.wait_for(asyncio.to_thread(proc.wait), timeout=_REAP_WAIT_TIMEOUT)
                except Exception as _exc:
                    logger.debug("timeout cleanup: kill/wait failed", exc_info=True)
                return _TIMEOUT_RESULT.format(timeout=timeout)
            except asyncio.CancelledError:
                try:
                    proc.kill()
                    # Phase 4 V2：同上，取消路径同样有界（对称）。
                    await asyncio.wait_for(asyncio.to_thread(proc.wait), timeout=_REAP_WAIT_TIMEOUT)
                except BaseException:
                    logger.debug("cancel cleanup: kill/wait failed", exc_info=True)
                raise

        finally:
            kernel32.CloseHandle(wintypes.HANDLE(hJob))

    def __repr__(self) -> str:
        return f"WinJobBackend(available={self.available})"
