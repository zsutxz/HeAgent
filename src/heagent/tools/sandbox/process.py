"""进程监督内核：spawn / 超时 / 取消 / kill-reap / 输出截断的**单点实现**。

本模块是全部子进程收尾语义的公共内核：``_supervise_subprocess`` 保证超时与取消
两条清理路径一致（都先杀进程树再返回/上抛），``_kill_and_reap`` 提供 bounded
reap（5s 上界），``_cap_channel`` 单通道 512KB 保头尾截断，``scrub_sensitive_env``
剥离敏感环境变量。各平台后端（firejail / winjob）与 :class:`PassthroughRunner`
都经由本模块收尾，git 工具与 hooks 执行器亦复用 kill/reap 内核。

命令注入面的默认后端 :class:`PassthroughRunner`（等价 ``create_subprocess_shell``
直接执行）也定义在此。
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
from contextlib import contextmanager, suppress
from typing import TYPE_CHECKING

from heagent.tools.runtime import RuntimeSlot
from heagent.tools.sandbox.contracts import CommandRunner, SandboxTier

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping, Sequence


logger = logging.getLogger(__name__)


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

    @property
    def available(self) -> bool:
        """passthrough 无任何平台依赖，恒可用。"""
        return True

    async def run(self, command: str, *, timeout: int) -> str:
        return await _run_subprocess_shell(command, timeout=timeout)


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
