"""本进程的资源采样（零第三方依赖：Linux 读 ``/proc``，Windows 走 ``ctypes``）。

状态面（``GET /api/status``）要回答「这个进程现在吃多少资源」，但依赖树里**没有** ``psutil``——
按 Epic 67 的「依赖精简」立场不为一个只读展示再引一个带 C 扩展的包。因此这里只做两件事：

- 两条平台通路（``procfs`` / ``ctypes``），各读一次文件或调一次 Win32 API；
- 不支持的平台一律返回 ``source="unavailable"`` 且三个数值为 ``None``——**绝不填 0 冒充**，
  0 会被读成「这个进程不吃内存 / 没开线程」。

不是精确计量器：``rss_bytes`` 是进程当前驻留集，``cpu_seconds`` 是用户+系统 CPU 时间累计，
``threads`` 是 OS 线程数。采样本身无副作用、不加锁、不做 I/O 以外的动作。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

PROCFS_SOURCE = "procfs"
CTYPES_SOURCE = "ctypes"
UNAVAILABLE_SOURCE = "unavailable"


@dataclass(frozen=True)
class ProcessStats:
    """一次采样结果；``None`` 表示该平台/该次采样拿不到（不是 0）。"""

    rss_bytes: int | None = None
    threads: int | None = None
    cpu_seconds: float | None = None
    source: str = UNAVAILABLE_SOURCE


def read_process_stats() -> ProcessStats:
    """按平台取本进程的 RSS / 线程数 / CPU 时间；任何异常都降级为 ``unavailable``。"""
    platform = sys.platform
    try:
        if platform.startswith("linux"):
            return _read_procfs()
        if platform.startswith("win"):
            return _read_windows()
    except (OSError, ValueError, RuntimeError):  # 采样失败不该影响状态面的其他字段
        return ProcessStats()
    return ProcessStats()


def _read_procfs() -> ProcessStats:
    """Linux：``/proc/self/status`` 取 VmRSS/Threads，``/proc/self/stat`` 取 CPU 时钟节拍。"""
    rss_bytes: int | None = None
    threads: int | None = None
    for line in Path("/proc/self/status").read_text(encoding="ascii", errors="replace").splitlines():
        if line.startswith("VmRSS:"):
            rss_bytes = int(line.split()[1]) * 1024
        elif line.startswith("Threads:"):
            threads = int(line.split()[1])
    stat = Path("/proc/self/stat").read_text(encoding="ascii", errors="replace")
    # 第 2 个字段是带括号的进程名，可能含空格 ⇒ 从最后一个 ')' 之后开始切。
    fields = stat[stat.rfind(")") + 2 :].split()
    ticks = int(fields[11]) + int(fields[12])  # utime + stime（第 14/15 字段）
    cpu_seconds = ticks / os.sysconf("SC_CLK_TCK")
    return ProcessStats(rss_bytes=rss_bytes, threads=threads, cpu_seconds=cpu_seconds, source=PROCFS_SOURCE)


def _read_windows() -> ProcessStats:  # pragma: no cover - 只在 Windows 上执行
    """Windows：``GetProcessMemoryInfo`` 取 WorkingSetSize，``GetProcessTimes`` 取 CPU 时间。

    线程数走 ``Toolhelp32Snapshot`` 太重（每次采样要枚举全进程线程），因此 Windows 上留 ``None``。
    """
    import ctypes
    from ctypes import wintypes

    class _MemoryCounters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    # ``WinDLL`` 只在 Windows 上存在（在 Linux 上跑 mypy 时看不到它，故按平台忽略该属性检查）。
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    psapi = ctypes.WinDLL("psapi", use_last_error=True)  # type: ignore[attr-defined]
    process = kernel32.GetCurrentProcess()

    counters = _MemoryCounters()
    counters.cb = ctypes.sizeof(_MemoryCounters)
    if not psapi.GetProcessMemoryInfo(process, ctypes.byref(counters), counters.cb):
        raise RuntimeError("GetProcessMemoryInfo failed")

    creation, exit_, kernel, user = (wintypes.FILETIME() for _ in range(4))
    if not kernel32.GetProcessTimes(
        process, ctypes.byref(creation), ctypes.byref(exit_), ctypes.byref(kernel), ctypes.byref(user)
    ):
        raise RuntimeError("GetProcessTimes failed")

    def _to_seconds(value: wintypes.FILETIME) -> float:
        return ((value.dwHighDateTime << 32) | value.dwLowDateTime) / 10_000_000.0

    return ProcessStats(
        rss_bytes=int(counters.WorkingSetSize),
        threads=None,
        cpu_seconds=_to_seconds(kernel) + _to_seconds(user),
        source=CTYPES_SOURCE,
    )


__all__ = ["CTYPES_SOURCE", "PROCFS_SOURCE", "UNAVAILABLE_SOURCE", "ProcessStats", "read_process_stats"]
