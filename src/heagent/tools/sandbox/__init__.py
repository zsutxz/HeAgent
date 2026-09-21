"""工具子进程执行的沙箱后端抽象（CommandRunner）——包入口（兼容命名空间）。

为 ``shell`` 等需要 spawn 子进程的工具提供可注入的执行抽象：默认
:class:`PassthroughRunner`（等价 ``asyncio.create_subprocess_shell`` 直接执行），
可替换为 :class:`FirejailBackend`（经 firejail 包裹子进程施加 OS 级隔离）。

子模块分层（2026-09-21 Phase 4 C1，自单文件 ``tools/sandbox.py`` 拆出）：
:mod:`.contracts`（分级 / Protocol / 注入 slot）、:mod:`.process`（进程监督内核）、
:mod:`.firejail`、:mod:`.winjob`（平台后端）、:mod:`.session`（会话目录与作用域）。
本 ``__init__`` re-export 全部历史公共名——``from heagent.tools.sandbox import X``
的既有导入与 monkeypatch 缝不受拆分影响。

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

from heagent.tools.sandbox.contracts import (
    CommandRunner,
    SandboxTier,
    bind_sandbox_profile,
    bind_sandbox_workspace,
    get_sandbox_profile,
    get_sandbox_workspace,
    reset_sandbox_profile,
    reset_sandbox_workspace,
)
from heagent.tools.sandbox.firejail import FirejailBackend
from heagent.tools.sandbox.process import (
    _REAP_WAIT_TIMEOUT,
    _TIMEOUT_RESULT,
    PassthroughRunner,
    _cap_channel,
    _format_result,
    _kill_and_reap,
    _run_subprocess_exec,
    _run_subprocess_shell,
    _supervise_subprocess,
    bind_command_runner,
    configure_command_runner,
    get_command_runner,
    reset_command_runner,
    scrub_sensitive_env,
)
from heagent.tools.sandbox.session import (
    SandboxSession,
    bind_sandbox_session,
    get_or_create_session,
    get_sandbox_session,
    pop_session,
    sandbox_session_dir,
    sandbox_sessions_root,
)
from heagent.tools.sandbox.winjob import WinJobBackend, _winjob_spawn

__all__ = [
    "CommandRunner",
    "FirejailBackend",
    "PassthroughRunner",
    "SandboxSession",
    "SandboxTier",
    "WinJobBackend",
    "_REAP_WAIT_TIMEOUT",
    "_TIMEOUT_RESULT",
    "_cap_channel",
    "_format_result",
    "_kill_and_reap",
    "_run_subprocess_exec",
    "_run_subprocess_shell",
    "_supervise_subprocess",
    "_winjob_spawn",
    "bind_command_runner",
    "bind_sandbox_profile",
    "bind_sandbox_session",
    "bind_sandbox_workspace",
    "configure_command_runner",
    "get_command_runner",
    "get_or_create_session",
    "get_sandbox_profile",
    "get_sandbox_session",
    "get_sandbox_workspace",
    "reset_command_runner",
    "reset_sandbox_profile",
    "reset_sandbox_workspace",
    "sandbox_session_dir",
    "sandbox_sessions_root",
    "scrub_sensitive_env",
    "pop_session",
]
