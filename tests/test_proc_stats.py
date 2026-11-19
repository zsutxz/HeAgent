"""``proc_stats`` 三条采样通路的单测：procfs 文本解析 / 失败收敛 / Windows ctypes 分支。

数值断言一律钉成**精确值**：只断言量级会让字段下标错位、单位错乘（1024 写成 1000）、
64 位句柄截断这类缺陷全部漏过。Windows 分支通过给 ``sys.modules["ctypes"]`` 装替身模块执行，
不依赖真实平台。
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import TYPE_CHECKING, Any, ClassVar

from heagent.network import proc_stats

if TYPE_CHECKING:
    import pytest

# 真实 ``/proc/self/status`` 的形态：目标行被若干无关行夹住，字段间用制表符分隔。
_STATUS_TEXT = """\
Name:\tpython
State:\tR (running)
Tgid:\t4321
VmPeak:\t 1048576 kB
VmRSS:\t   12345 kB
VmData:\t  204800 kB
Threads:\t7
voluntary_ctxt_switches:\t42
nonvoluntary_ctxt_switches:\t3
"""

# 真实 ``/proc/self/stat`` 的形态：进程名含空格与嵌套括号，其后 20+ 个数值字段。
# utime 是第 14 字段、stime 第 15 字段 ⇒ 从 ')' 之后 split 得 [11] / [12]。
_STAT_TEXT = (
    "1234 (my proc (x)) S 1200 1234 1234 0 -1 4194560 12345 67 0 0 123 45 0 0 "
    "20 0 7 0 987654 123456789 3000 18446744073709551615 1 1 0 0 0 0 0 0 0 0 0 0 17 3 0 0 0 0 0"
)
_UTIME = 123
_STIME = 45
_CLK_TCK = 100

_WORKING_SET_BYTES = 52_428_800
_KERNEL_100NS = 10_000_000  # 1.0 秒
_USER_HIGHDATETIME = 1  # 1 << 32 个 100ns 单位


def _write_proc_fixture(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    status: str = _STATUS_TEXT,
    stat: str = _STAT_TEXT,
) -> None:
    """把 ``_proc_self()`` 指向装着已知样例文本的临时目录。"""
    (tmp_path / "status").write_text(status, encoding="ascii")
    (tmp_path / "stat").write_text(stat, encoding="ascii")
    monkeypatch.setattr(proc_stats, "_proc_self", lambda: tmp_path)
    monkeypatch.setattr(sys, "platform", "linux")


class _FileTime:
    """替身 ``wintypes.FILETIME``：只保留两个 32 位分量的读写。"""

    def __init__(self, dwLowDateTime: int = 0, dwHighDateTime: int = 0) -> None:
        self.dwLowDateTime = dwLowDateTime
        self.dwHighDateTime = dwHighDateTime


def _fake_ctypes_module(*, memory_ok: bool) -> tuple[ModuleType, SimpleNamespace, SimpleNamespace]:
    """替身 ``ctypes``：只实现 ``_read_windows`` 用到的那几个符号（连同两个假 DLL 一并返回）。"""

    class _Structure:
        _fields_: ClassVar[list[Any]] = []

    def GetCurrentProcess() -> int:  # noqa: N802 - 复刻 Win32 名称
        return 1

    def GetProcessMemoryInfo(_handle: Any, counters: Any, _cb: Any) -> int:  # noqa: N802
        if not memory_ok:
            return 0
        counters.WorkingSetSize = _WORKING_SET_BYTES
        return 1

    def GetProcessTimes(_handle: Any, _creation: Any, _exit: Any, kernel: Any, user: Any) -> int:  # noqa: N802
        kernel.dwLowDateTime = _KERNEL_100NS
        kernel.dwHighDateTime = 0
        user.dwLowDateTime = 0
        user.dwHighDateTime = _USER_HIGHDATETIME
        return 1

    wintypes = SimpleNamespace(DWORD="DWORD", HANDLE="HANDLE", BOOL="BOOL", FILETIME=_FileTime)
    kernel32 = SimpleNamespace(GetCurrentProcess=GetCurrentProcess, GetProcessTimes=GetProcessTimes)
    psapi = SimpleNamespace(GetProcessMemoryInfo=GetProcessMemoryInfo)

    def WinDLL(name: str, use_last_error: bool = False) -> SimpleNamespace:  # noqa: N802 - 复刻 ctypes 名称
        assert use_last_error is True
        return kernel32 if name == "kernel32" else psapi

    fake = ModuleType("ctypes")
    fake.Structure = _Structure  # type: ignore[attr-defined]
    fake.c_size_t = "c_size_t"  # type: ignore[attr-defined]
    fake.sizeof = lambda _obj: 48  # type: ignore[attr-defined]
    fake.byref = lambda obj: obj  # type: ignore[attr-defined]
    fake.POINTER = lambda tp: ("pointer", tp)  # type: ignore[attr-defined]
    fake.WinDLL = WinDLL  # type: ignore[attr-defined]
    fake.wintypes = wintypes  # type: ignore[attr-defined]
    return fake, kernel32, psapi


def _install_fake_windows(
    monkeypatch: pytest.MonkeyPatch, *, memory_ok: bool = True
) -> tuple[SimpleNamespace, SimpleNamespace]:
    """装好替身 ``ctypes`` 并把平台切成 Windows；返回两个假 DLL 供断言已声明的签名。"""
    fake, kernel32, psapi = _fake_ctypes_module(memory_ok=memory_ok)
    monkeypatch.setitem(sys.modules, "ctypes", fake)
    monkeypatch.setattr(sys, "platform", "win32")
    return kernel32, psapi


class TestProcfs:
    def test_reports_exact_rss_and_thread_counts(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _write_proc_fixture(monkeypatch, tmp_path)
        monkeypatch.setattr(proc_stats.os, "sysconf", lambda _name: _CLK_TCK)

        stats = proc_stats.read_process_stats()

        assert stats.source == proc_stats.PROCFS_SOURCE == "procfs"
        # 单位是 kB ⇒ 12345 * 1024；按 1000 折算会得 12345000。
        assert stats.rss_bytes == 12_641_280
        assert stats.threads == 7

    def test_reads_utime_stime_past_a_parenthesised_name(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        _write_proc_fixture(monkeypatch, tmp_path)
        monkeypatch.setattr(proc_stats.os, "sysconf", lambda _name: _CLK_TCK)

        stats = proc_stats.read_process_stats()

        assert stats.source == "procfs"
        # 字段下标错一位（取到 minflt 或 cutime）都会得到别的值。
        assert stats.cpu_seconds == (_UTIME + _STIME) / _CLK_TCK == 1.68

    def test_missing_proc_directory_degrades_to_unavailable(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setattr(proc_stats, "_proc_self", lambda: tmp_path / "absent")
        monkeypatch.setattr(sys, "platform", "linux")

        stats = proc_stats.read_process_stats()

        assert stats.source == "unavailable"
        assert (stats.rss_bytes, stats.threads, stats.cpu_seconds) == (None, None, None)

    def test_truncated_stat_degrades_to_unavailable(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        # 字段不足时 int(fields[11]) 会抛 IndexError，必须收敛为「采不到」而不是冒到端点层。
        _write_proc_fixture(monkeypatch, tmp_path, stat="1234 (python) S 1 2 3\n")

        stats = proc_stats.read_process_stats()

        assert stats.source == "unavailable"
        assert (stats.rss_bytes, stats.threads, stats.cpu_seconds) == (None, None, None)


class TestWindows:
    def test_reports_exact_memory_and_cpu_times(self, monkeypatch: pytest.MonkeyPatch) -> None:
        kernel32, psapi = _install_fake_windows(monkeypatch)

        stats = proc_stats.read_process_stats()

        assert stats.source == proc_stats.CTYPES_SOURCE == "ctypes"
        assert stats.rss_bytes == _WORKING_SET_BYTES
        expected_cpu = _KERNEL_100NS / 10_000_000.0 + (_USER_HIGHDATETIME << 32) / 10_000_000.0
        assert stats.cpu_seconds == expected_cpu
        # Windows 通路不枚举线程，留 None（填 0 会被读成「没开线程」）。
        assert stats.threads is None
        # 三个 API 都必须显式声明签名：不声明时 64 位句柄会被截断成 32 位。
        assert getattr(kernel32.GetCurrentProcess, "argtypes", None) == []
        assert getattr(kernel32.GetCurrentProcess, "restype", None) == "HANDLE"
        memory_argtypes = getattr(psapi.GetProcessMemoryInfo, "argtypes", None)
        assert memory_argtypes is not None and memory_argtypes[0] == "HANDLE" and memory_argtypes[2] == "DWORD"
        # 第二个参数必须是指向计数器结构的指针，且结构里确实排着 ``WorkingSetSize``。
        kind, counters_type = memory_argtypes[1]
        assert kind == "pointer"
        assert "WorkingSetSize" in [name for name, _type in counters_type._fields_]
        assert getattr(psapi.GetProcessMemoryInfo, "restype", None) == "BOOL"
        assert getattr(kernel32.GetProcessTimes, "argtypes", None) == ["HANDLE", *[("pointer", _FileTime)] * 4]
        assert getattr(kernel32.GetProcessTimes, "restype", None) == "BOOL"

    def test_memory_query_failure_degrades_to_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_fake_windows(monkeypatch, memory_ok=False)

        stats = proc_stats.read_process_stats()

        assert stats.source == "unavailable"
        assert (stats.rss_bytes, stats.threads, stats.cpu_seconds) == (None, None, None)
