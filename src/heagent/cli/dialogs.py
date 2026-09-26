"""原生「选择目录」对话框（**服务端所在机器**）——网页控制台登记项目时的 GUI 接缝。

为什么必须在服务端做：浏览器**拿不到**本机绝对路径（File System Access API 只给沙箱句柄），
所以「用资源管理器挑目录」只能由跑服务的那台机器弹出原生窗口，再把用户选中的绝对路径回给页面。
它带来的是**便利，不是权限**：返回值随后仍要过 ``POST /api/projects`` 的全套校验（存在 / 是目录 /
规范化 / 去重 / 上限）——选择器**不绕过任何既有闸门**。

三条纪律（都**不是**安全边界，见 ``docs/frame.md`` 五）：

- **不阻塞事件循环**：对话框跑在**子进程**里（``asyncio.create_subprocess_exec``）。服务进程既不
  持有 GUI 状态（tkinter 的主线程约束因此天然不适用），也能用「超时 + 终止 + 有界回收」兜住
  「用户把窗口开着不管」；argv 全为**模块级常量**，无用户输入、无 shell（``shell=True`` 绝不出现）。
- **有界**：同一时刻只允许一次在途（:class:`DirectoryPicker`，并发调用抛 :class:`DialogBusyError`）、
  超时上限 :data:`DEFAULT_TIMEOUT_SECONDS`、只解析子进程 stdout 里的**标记行**（其它输出一律忽略）。
- **不可用就说不可用**：没有图形后端（容器 / 缺 ``_tkinter`` / 非 Windows 又无 tkinter）时抛
  :class:`DialogUnavailableError`，由入口层转成稳定错误码——绝不静默卡住、也不假装成「用户取消」。

后端口径：``tkinter``（跨平台；本机 Python 3.13 venv 实测可用）优先 → ``powershell``（Windows
PowerShell 5.1 的 ``System.Windows.Forms.FolderBrowserDialog``）→ ``none`` 明确禁用（容器与测试用，
也是「不可用路径」的确定性入口）。

**为什么在入口层而不在顶层模块**：本模块复用 ``tools.sandbox.process`` 的凭证剥离与有界回收
（:func:`scrub_sensitive_env` / :func:`reap_subprocess`）——顶层模块不得反向依赖 ``tools/``（依赖
DAG），而入口层可以。这正是 Story 50-8 相对 story 文本的一处偏离，理由记录在该 story 的
Dev Agent Record 里。
"""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Final

from heagent.tools.sandbox.process import reap_subprocess, scrub_sensitive_env

logger = logging.getLogger(__name__)

__all__ = [
    "BACKENDS",
    "DEFAULT_TIMEOUT_SECONDS",
    "MARKER",
    "DialogBusyError",
    "DialogUnavailableError",
    "DirectoryPicker",
    "resolve_backend",
]

#: 一次选择的墙钟上限（秒）。超时 = 终止子进程 + 按「取消」返回（不新增错误码：用户没选。
#: 超时是**模块常量**而非 ``Settings`` 字段——避免为它扩张配置面与 ``.env.example`` 同步义务。
DEFAULT_TIMEOUT_SECONDS: Final = 300.0

#: ``--dialog-backend`` 的合法取值。
BACKENDS: Final = ("auto", "tkinter", "powershell", "none")

#: 子进程回传路径的标记行前缀（**纯 ASCII**：路径里可能含非 ASCII，标记本身不能）。
MARKER: Final = "__HEAGENT_PICKED_DIRECTORY__"

_TITLE: Final = "HeAgent：选择项目目录"

# 子进程脚本是**冻结常量**（无插值、无用户输入）；两个后端都把输出编码钉成 UTF-8，父进程按
# UTF-8 解码——否则中文路径会在 Windows 的 cp936 控制台编码下损坏。
_TK_SCRIPT: Final = (
    "import tkinter\n"
    "from tkinter import filedialog\n"
    "root = tkinter.Tk()\n"
    "root.withdraw()\n"
    "try:\n"
    "    root.attributes('-topmost', True)\n"
    "except Exception:\n"
    "    pass\n"
    f"picked = filedialog.askdirectory(parent=root, title={_TITLE!r}, mustexist=True)\n"
    "root.destroy()\n"
    f"print({MARKER!r} + (picked or ''), flush=True)\n"
)

_POWERSHELL_SCRIPT: Final = (
    "$ErrorActionPreference = 'Stop'\n"
    "Add-Type -AssemblyName System.Windows.Forms\n"
    "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
    "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog\n"
    f'$dialog.Description = "{_TITLE}"\n'
    "$dialog.ShowNewFolderButton = $false\n"
    f"if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {{ "
    f"Write-Output ('{MARKER}' + $dialog.SelectedPath) }}\n"
)


class DialogUnavailableError(RuntimeError):
    """没有可用的图形后端（或被 ``none`` 明确禁用）——调用方应回稳定错误码并保留手工输入。"""


class DialogBusyError(RuntimeError):
    """已有一次选择在途（同一时刻只允许一个原生窗口）。"""


def _tkinter_available() -> bool:
    """``find_spec`` 只查**能否导入**（不创建窗口）：容器 / 精简解释器里常见缺失。"""
    return importlib.util.find_spec("tkinter") is not None


def _powershell_path() -> str | None:
    """Windows PowerShell 5.1 的可执行路径；非 Windows 恒为 ``None``（不押 ``pwsh``）。"""
    if os.name != "nt":
        return None
    return shutil.which("powershell") or shutil.which("powershell.exe")


def resolve_backend(backend: str) -> str:
    """把 ``auto`` 解析成具体后端；不可用时抛 :class:`DialogUnavailableError`（带原因）。

    显式指定的后端同样要**可用性检查**——「选了不可用的后端」与「没有后端」对用户是同一件事。
    """
    if backend == "none":
        raise DialogUnavailableError("directory dialog is disabled (--dialog-backend none)")
    if backend == "tkinter":
        if not _tkinter_available():
            raise DialogUnavailableError("tkinter is not available in this Python installation")
        return "tkinter"
    if backend == "powershell":
        if _powershell_path() is None:
            raise DialogUnavailableError("PowerShell is not available on this machine")
        return "powershell"
    if backend != "auto":
        raise ValueError(f"unknown dialog backend: {backend!r}")
    if _tkinter_available():
        return "tkinter"
    if _powershell_path() is not None:
        return "powershell"
    raise DialogUnavailableError("no native directory dialog backend is available on this machine")


def _command_for(backend: str) -> tuple[list[str], str]:
    """后端 → （argv 前缀, 固定脚本）。Windows 的 ``pythonw`` 不参与：``sys.executable`` 足够。"""
    if backend == "tkinter":
        return [sys.executable, "-c"], _TK_SCRIPT
    return [_powershell_path() or "", "-NoProfile", "-NonInteractive", "-STA", "-Command"], _POWERSHELL_SCRIPT


def _child_env() -> dict[str, str]:
    """子进程环境：剥离 ``*_API_KEY`` 等敏感变量（GUI 子进程不需要凭证），并钉住 UTF-8 输出。"""
    env = scrub_sensitive_env()
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _spawn_kwargs() -> dict[str, Any]:
    """spawn 的固定 kwargs（**纯函数**，便于单测断言「双管道 + 凭证剥离 + 无 shell 键」）。

    刻意不出现 ``shell`` 键：本模块**绝不**经 shell 拉起任何东西（argv 全是模块级常量）。
    """
    return {
        "stdout": asyncio.subprocess.PIPE,
        "stderr": asyncio.subprocess.PIPE,
        "env": _child_env(),
    }


async def _spawn(argv: list[str], script: str) -> asyncio.subprocess.Process:
    """拉起对话框子进程——模块内**唯一**的 spawn 点，也是测试用的缝。"""
    return await asyncio.create_subprocess_exec(*argv, script, **_spawn_kwargs())


def parse_marked_path(stdout: bytes) -> str | None:
    """从子进程 stdout 取**最后一条标记行**并复验为存在的目录；否则 ``None``（= 取消）。

    取最后一条而不是第一条：PowerShell 可能先吐别的输出；标记行是我们唯一的契约。
    复验 ``is_dir()`` 是**防脏值**（后端异常输出 / 用户手输不存在的路径），不是安全边界。
    """
    candidate = ""
    for line in stdout.decode("utf-8", errors="replace").splitlines():
        if line.startswith(MARKER):
            candidate = line[len(MARKER) :].strip()
    if not candidate:
        return None
    path = Path(candidate)
    if not path.is_dir():
        logger.warning("dialog returned a path that is not a directory; treated as cancelled")
        return None
    return str(path)


class DirectoryPicker:
    """原生目录选择器：单在途 + 超时 + 终止回收（``backend`` 语义见模块 docstring）。

    不记录选中的路径到日志（那是用户的目录结构，不是我们要留的观测数据）。
    """

    def __init__(self, backend: str = "auto", *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> None:
        if backend not in BACKENDS:
            raise ValueError(f"unknown dialog backend: {backend!r}")
        self._backend = backend
        self._timeout = timeout
        self._in_flight = False

    @property
    def backend(self) -> str:
        """启动配置里的原始取值（``auto`` 原样保留，便于 UI/测试断言）。"""
        return self._backend

    @property
    def in_flight(self) -> bool:
        return self._in_flight

    async def pick(self) -> str | None:
        """弹出一次选择：返回绝对路径；取消/超时/脏值一律 ``None``（调用方按取消处理）。

        :raises DialogBusyError: 已有一次在途（**不排队**：原生窗口不能叠着开）。
        :raises DialogUnavailableError: 无可用后端（含 ``none``）。
        """
        if self._in_flight:
            raise DialogBusyError("a directory dialog is already open")
        resolved = resolve_backend(self._backend)
        argv, script = _command_for(resolved)
        self._in_flight = True
        try:
            return await self._run(argv, script)
        finally:
            self._in_flight = False

    async def _run(self, argv: list[str], script: str) -> str | None:
        try:
            proc = await _spawn(argv, script)
        except OSError as exc:
            raise DialogUnavailableError("could not start the dialog process") from exc
        try:
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=self._timeout)
        except TimeoutError:
            # 超时与取消两条清理路径都要 kill + 有界回收（否则会留下孤儿子进程）。
            await self._abandon(proc)
            logger.warning("directory dialog timed out after %.0fs; treated as cancelled", self._timeout)
            return None
        except asyncio.CancelledError:
            await self._abandon(proc)
            raise
        if proc.returncode != 0:
            # 后端自身失败（无显示、脚本报错）——**不**当成「用户取消」：UI 要能说出原因。
            raise DialogUnavailableError(f"dialog process exited with status {proc.returncode}")
        return parse_marked_path(stdout)

    @staticmethod
    async def _abandon(proc: asyncio.subprocess.Process) -> None:
        """终止并回收（对话框子进程不派生子进程树，故 ``kill()`` 足够——不同于 ``shell`` 路径）。"""
        try:
            proc.kill()
        except ProcessLookupError:  # pragma: no cover - 已退出时无事可做
            pass
        except OSError:  # pragma: no cover - 平台差异，仍继续回收管道
            logger.debug("dialog kill failed; still attempt pipe cleanup", exc_info=True)
        try:
            await reap_subprocess(proc)
        except Exception:  # pragma: no cover - 回收失败只影响日志，不改变「已取消」的结论
            logger.debug("dialog reap failed; subprocess/pipe may leak", exc_info=True)
