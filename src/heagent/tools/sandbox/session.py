"""沙箱会话目录与 per-run 会话作用域。

「会话目录」是目录**约定**而非安全边界：``sandbox_sessions_root`` 是工作区 →
约定根的唯一定义（EngineContainer 创建 / housekeeping 回收共用），``sandbox_session_dir``
做 run_id 校验与幂等创建。:class:`SandboxSession` 提供同一 run 内 cwd 跨命令保持与
teardown；会话实例经 RuntimeSlot 注入（``bind_sandbox_session``）。
"""

from __future__ import annotations

import asyncio
import shutil
import sys
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING

from heagent.tools.runtime import RuntimeSlot
from heagent.tools.sandbox.process import get_command_runner
from heagent.tools.sandbox.winjob import WinJobBackend

if TYPE_CHECKING:
    from collections.abc import Iterator


_MARKER = "HEAGENT_CWD"


def sandbox_sessions_root(workspace: Path | None = None) -> Path:
    """工作区下的沙箱会话目录**约定根**：``<workspace 或进程 cwd>/.heagent/sandboxes``。

    纯路径计算、无 I/O。调用方必须看同一个根：``EngineContainer.create_run_context`` 在此
    创建 per-run 目录（经 ``sandbox_session_dir(..., base=...)``），``housekeeping.prune_sandbox_dirs``
    在此回收崩溃 run 的孤儿目录——两处共用本函数，避免「目录约定」漂移成两份字面量。

    注意与 ``sandbox_session_dir(base=...)`` 的区别：后者的 ``base`` 是**整个根**的替代
    （测试注入通道，不再追加 ``.heagent/sandboxes``），本函数才是「工作区 → 约定根」的映射。
    """
    from heagent.pub.workspace import WorkspacePaths

    return WorkspacePaths.from_root(workspace if workspace is not None else Path.cwd()).sandboxes


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
