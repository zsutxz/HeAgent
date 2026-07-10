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
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING, Protocol

from heagent.tools.runtime import RuntimeSlot

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence


logger = logging.getLogger(__name__)


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

# reap wait 硬上界（秒）。SIGKILL 后正常子进程应毫秒级退出；不可中断内核态（Linux
# D-state / pipe transport 对端 hang）下 ``proc.wait()`` 不返回也不抛，此上界防永久 hang——
# 否则整个 except 块卡在 reap，超时串 / 取消信号被阻塞（比 reap 抛错替换更坏的形态，item 2）。
_REAP_WAIT_TIMEOUT = 5.0


async def _kill_and_reap(proc: asyncio.subprocess.Process) -> None:
    """超时/取消收尾：SIGKILL 子进程并回收，best-effort。

    - ``proc.kill()`` 进程已退出竞态抛 ``ProcessLookupError``，吞掉。
    - **item 3（kill/wait 解耦）**：``proc.kill()`` 权限失败（``PermissionError`` 等，逃出
      ``suppress(ProcessLookupError)``）不再阻断后续 ``wait()``——记 debug 日志后**仍执行 wait**
      回收 pipe FD（即便子进程未被杀，pipe transport 仍可关）。kill 失败是局部 best-effort 关注，
      在此吞掉、不逸出。
    - **item 2（wait 硬上界）**：``await proc.wait()`` 经 ``wait_for`` 限时 ``_REAP_WAIT_TIMEOUT``
      秒；D-state 下 wait 不返回，此上界防永久 hang。D-state 超时逸出 ``TimeoutError``，由调用方
      ``except`` 保护（TimeoutError 路径 item 1 / CancelledError 路径 D-1）。
    - **不吞 re-entrant** ``CancelledError``（wait 又被取消）——取消传播优先，逸出由调用方保护。

    契约（Y）：本函数吞 kill 失败，但 wait 失败（D-state ``TimeoutError`` / re-entrant
    ``CancelledError``）逸出。调用方两 except 块各自兜底（见 item 1 / D-1），D-1 保护因此仍非死代码。
    """
    try:
        with suppress(ProcessLookupError):
            proc.kill()
    except BaseException:
        # item 3：kill 权限失败不阻断 wait（解耦）——记日志后仍落到下方 wait 回收 pipe FD。
        logger.debug("kill failed; still attempt wait to reap pipe FD", exc_info=True)
    # item 2：wait 硬上界防 D-state 永久 hang；超时逸出 TimeoutError 由调用方 except 保护。
    await asyncio.wait_for(proc.wait(), timeout=_REAP_WAIT_TIMEOUT)


def _validate_timeout(timeout: int) -> None:
    """校验 ``timeout`` 为正整数（秒），否则抛 ``ValueError``（fail-closed）。

    LLM 经 JSON 工具调用传入的 ``timeout`` 不经 ``@tool`` schema 运行期强制（decorator
    仅生成 JSON Schema 描述、无 isinstance 校验），故在 spawn 前于此 fail-closed 守卫：

      - 非 ``int``（``None`` / ``str`` / ``float`` …）→ 拒绝（``nan`` / ``inf`` 属 float
        亦在此拦截——``nan <= 0`` 恒 False 会绕过 ``<=`` 守卫并破坏 asyncio timer 堆全序）
      - ``bool``（``int`` 子类）→ 拒绝，守住 "integer" 契约（``True`` 会被当 ``1`` 静默接受）
      - ``<= 0`` → 拒绝（spawn 后 ``wait_for`` 立即超时 → 竞态 kill 未启动的进程）

    拒绝时统一抛 ``ValueError``（而非让 ``<=`` 对非数值抛 ``TypeError``），消息含
    ``repr(timeout)``，经 :class:`~heagent.engine.executor.ToolExecutor` ``except Exception``
    转成错误 ``ToolResult`` 回喂 LLM、不中断循环。
    """
    if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
        raise ValueError(f"timeout must be a positive integer (seconds), got {timeout!r}")


async def _run_subprocess_shell(command: str, *, timeout: int) -> str:
    """经 ``create_subprocess_shell`` 执行；超时 kill 子进程并返回统一超时串。"""
    _validate_timeout(timeout)
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        # item 1：reap 的非取消失败（D-state TimeoutError / RuntimeError 等）不得替换超时返回串——
        # 仍返回超时串（reap 是 best-effort）。用 ``except Exception``（非 BaseException）：放行
        # re-entrant CancelledError（reap 期间任务被取消时取消信号上抛，延续 D-1「取消传播优先」）。
        try:
            await _kill_and_reap(proc)
        except Exception:
            logger.debug(
                "timeout cleanup: _kill_and_reap failed; subprocess/pipe may leak",
                exc_info=True,
            )
        return _TIMEOUT_RESULT.format(timeout=timeout)
    except asyncio.CancelledError:
        # D-1：reap 失败（item 2 的 D-state 超时 / wait 再取消）不可吞掉取消信号。``except BaseException``
        # 吞掉 reap 异常后，块尾裸 ``raise`` 回到本 ``except CancelledError`` 语境、重新抛出原始
        # ``CancelledError``（budget/window-reset/SubAgent-abort 清理依赖它上抛）。不用
        # ``try/finally: raise``——实证其在 reap 抛错时抛 reap 异常、Cancel 沦为 ``__context__``。
        # D-1-A：reap 是 best-effort，失败记 debug 日志暴露诊断线索（子进程/FD 泄漏等），但绝不让
        # 异常替换取消信号（取消传播优先，遵循 CLAUDE.md「显性失败」此处表现为取消）。
        try:
            await _kill_and_reap(proc)  # 外层取消（budget/abort）也须 kill+wait，避免泄漏子进程
        except BaseException:
            logger.debug(
                "cancel cleanup: _kill_and_reap failed; subprocess/pipe may leak",
                exc_info=True,
            )
        raise
    return _format_result(proc.returncode, stdout, stderr)


async def _run_subprocess_exec(argv: Sequence[str], *, timeout: int) -> str:
    """经 ``create_subprocess_exec`` 执行（argv 列表，免双层 shell / 注入）。"""
    _validate_timeout(timeout)
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        # item 1：reap 的非取消失败（D-state TimeoutError / RuntimeError 等）不得替换超时返回串——
        # 仍返回超时串（reap 是 best-effort）。用 ``except Exception``（非 BaseException）：放行
        # re-entrant CancelledError（reap 期间任务被取消时取消信号上抛，延续 D-1「取消传播优先」）。
        try:
            await _kill_and_reap(proc)
        except Exception:
            logger.debug(
                "timeout cleanup: _kill_and_reap failed; subprocess/pipe may leak",
                exc_info=True,
            )
        return _TIMEOUT_RESULT.format(timeout=timeout)
    except asyncio.CancelledError:
        # D-1：reap 失败（item 2 的 D-state 超时 / wait 再取消）不可吞掉取消信号。``except BaseException``
        # 吞掉 reap 异常后，块尾裸 ``raise`` 回到本 ``except CancelledError`` 语境、重新抛出原始
        # ``CancelledError``（budget/window-reset/SubAgent-abort 清理依赖它上抛）。不用
        # ``try/finally: raise``——实证其在 reap 抛错时抛 reap 异常、Cancel 沦为 ``__context__``。
        # D-1-A：reap 是 best-effort，失败记 debug 日志暴露诊断线索（子进程/FD 泄漏等），但绝不让
        # 异常替换取消信号（取消传播优先，遵循 CLAUDE.md「显性失败」此处表现为取消）。
        try:
            await _kill_and_reap(proc)  # 外层取消（budget/abort）也须 kill+wait，避免泄漏子进程
        except BaseException:
            logger.debug(
                "cancel cleanup: _kill_and_reap failed; subprocess/pipe may leak",
                exc_info=True,
            )
        raise
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
