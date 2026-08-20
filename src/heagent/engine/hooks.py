"""用户可配置事件钩子（hooks，Epic 32）。

在 :class:`~heagent.engine.observability.EventBus`（进程内、同步观察者）之上，提供**用户
可配置的外部命令钩子**——从 ``.heagent/hooks.json`` 加载，在关键事件点执行 shell 命令。

设计要点：

- **显式 ``await`` 而非 EventObserver**：``EventObserver.handle`` 是同步派发、不得阻塞
  （见 ``observability.py``），而 hook 命令是异步子进程 I/O——故 HookManager 作为独立服务，
  在工具执行链 / 会话生命周期中**显式 ``await`` 调用**，既支持异步执行也支持「阻断」语义。
- 事件映射（对齐 Claude Code 语义）：
  - ``PreToolUse`` —— 工具执行前（可 ``block`` 阻断：命令退出码非 0 则阻断，stdout 作反馈）；
  - ``PostToolUse`` —— 工具执行后（fire-and-forget 通知）；
  - ``SessionStart`` / ``SessionEnd`` —— 单次 run 开始 / 结束。
- 注入环境变量：``HEAGENT_EVENT`` / ``HEAGENT_TOOL_NAME`` / ``HEAGENT_RUN_ID`` /
  ``HEAGENT_SESSION_ID`` 供 hook 命令读取。

⚠ 安全立场（与文首声明一致，诚实不造假象）：hook 是**用户自配置的本地命令**，其执行与
阻断是策略层 defense-in-depth，**不是安全边界**——hook 命令本身以当前用户权限运行，
既可能被绕过，也可能被恶意 hook 利用。须 OS 级沙箱兜底（见 CLAUDE.md 安全声明）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from heagent.engine.context import RunContext
    from heagent.types import ToolCall

logger = logging.getLogger(__name__)

# 事件名常量
PRE_TOOL_USE = "PreToolUse"
POST_TOOL_USE = "PostToolUse"
SESSION_START = "SessionStart"
SESSION_END = "SessionEnd"

# hook 命令默认超时（秒）：防止恶意/挂死的 hook 拖死 agent 主循环。
_DEFAULT_HOOK_TIMEOUT = 30.0

# hook 子进程环境白名单：**不透传全量 os.environ**（防 API key 等敏感变量随 hook 命令
# 外传），仅保留 shell 找到可执行文件所需的基本变量（跨平台并集）+ ``HEAGENT_*`` 前缀。
_ENV_ALLOWLIST = frozenset(
    {
        "PATH", "PATHEXT", "COMSPEC", "SYSTEMROOT", "WINDIR",  # Windows shell 必需
        "HOME", "LANG", "LC_ALL", "TERM", "TMPDIR",  # POSIX shell 常用
        "TEMP", "TMP",  # 临时目录（两平台）
    }
)


class HookConfig(BaseModel):
    """一条 hook 配置（来自 ``hooks.json`` 的 ``hooks`` 数组元素）。"""

    # Literal 校验：拼错事件名（如 "PostToolUs"）在加载期即失败（load 跳过 + warning），
    # 而非静默注册一条永不触发的 hook。
    event: Literal["PreToolUse", "PostToolUse", "SessionStart", "SessionEnd"]
    command: str  # shell 命令
    matcher: str = Field(default="")  # 工具名过滤（PreToolUse/PostToolUse）；空 = 全部
    block: bool = False  # PreToolUse：命令退出码非 0 则阻断工具调用


class HookResult(BaseModel):
    """一次 PreToolUse hook 运行的结果。"""

    blocked: bool = False
    feedback: str = ""


class HookManager:
    """加载并执行用户配置的 hooks.json 钩子。"""

    def __init__(self, hooks: list[HookConfig], *, timeout: float = _DEFAULT_HOOK_TIMEOUT) -> None:
        self._hooks = hooks
        self._timeout = timeout

    @classmethod
    def load(cls, path: str | Path, *, timeout: float = _DEFAULT_HOOK_TIMEOUT) -> HookManager:
        """从 ``hooks.json`` 加载；文件不存在 / 损坏 / 单项非法均不崩溃（跳过）。"""
        p = Path(path)
        if not p.exists():
            return cls([], timeout=timeout)
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to parse hooks config %s: %s", path, exc)
            return cls([], timeout=timeout)
        raw_hooks = data.get("hooks", []) if isinstance(data, dict) else []
        hooks: list[HookConfig] = []
        for raw in raw_hooks:
            if not isinstance(raw, dict):
                continue
            try:
                hook = HookConfig(**raw)
            except Exception as exc:  # noqa: BLE001 - 单条非法跳过，不影响其他 hook
                logger.warning("Invalid hook config %r: %s", raw, exc)
                continue
            if hook.event in (SESSION_START, SESSION_END) and hook.matcher:
                # session 事件无工具名可匹配，matcher 恒不生效——告警防静默错配置。
                logger.warning("Hook %r: matcher has no effect on %s events", hook.command, hook.event)
            hooks.append(hook)
        return cls(hooks, timeout=timeout)

    # ---- 事件执行入口 ----

    async def run_pre_tool(self, call: ToolCall, run_context: RunContext | None = None) -> HookResult:
        """PreToolUse：执行匹配的 hooks；block hook 退出码非 0 则返回阻断结果。"""
        for hook in self._matching(PRE_TOOL_USE, call.name):
            code, stdout = await self._run(hook, tool_name=call.name, run_context=run_context)
            if hook.block and code != 0:
                return HookResult(blocked=True, feedback=stdout.strip() or f"Hook '{hook.command}' exited {code}")
        return HookResult()

    async def run_post_tool(self, call: ToolCall, run_context: RunContext | None = None) -> None:
        """PostToolUse：执行匹配的 hooks（通知，不阻断）。"""
        for hook in self._matching(POST_TOOL_USE, call.name):
            await self._run(hook, tool_name=call.name, run_context=run_context)

    async def run_session(self, event: str, run_context: RunContext | None = None) -> None:
        """SessionStart / SessionEnd：执行匹配的 hooks（通知，不阻断）。"""
        for hook in self._matching(event, ""):
            await self._run(hook, tool_name="", run_context=run_context)

    # ---- 内部 ----

    def _matching(self, event: str, tool_name: str) -> list[HookConfig]:
        """返回匹配某事件（及可选工具名）的 hooks，按配置顺序。"""
        matched: list[HookConfig] = []
        for hook in self._hooks:
            if hook.event != event:
                continue
            if hook.matcher and hook.matcher != tool_name:
                continue
            matched.append(hook)
        return matched

    async def _run(self, hook: HookConfig, *, tool_name: str, run_context: RunContext | None) -> tuple[int, str]:
        """执行一条 hook 命令，返回 (退出码, stdout)。执行异常 / 超时返回 (1, 说明)。"""
        env = {k: v for k, v in os.environ.items() if k.startswith("HEAGENT_") or k in _ENV_ALLOWLIST}
        env.update({"HEAGENT_EVENT": hook.event, "HEAGENT_TOOL_NAME": tool_name})
        if run_context is not None:
            env["HEAGENT_RUN_ID"] = run_context.run_id
            env["HEAGENT_SESSION_ID"] = run_context.session_id or ""
        try:
            kwargs: dict[str, Any] = {}
            if sys.platform != "win32":
                # 独立进程组：超时可 killpg 整组终止（shell 的孙进程一并回收，防孤儿）。
                kwargs["start_new_session"] = True
            proc = await asyncio.create_subprocess_shell(
                hook.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                **kwargs,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=self._timeout)
            return proc.returncode or 0, stdout.decode(errors="replace")
        except TimeoutError:
            logger.warning("Hook timed out (%s): %s", hook.event, hook.command)
            # 超时仅取消 communicate 协程不终止子进程，须显式终止整棵进程树并回收：
            # - 直接子进程是 shell（cmd.exe / sh），kill 它杀不掉孙进程，且孙进程持有
            #   stdout 管道使 wait() 挂到孙进程退出——挂死的 hook 每次触发都泄漏进程。
            # - Windows 用 taskkill /T 按树终止；POSIX 用 killpg 杀整个进程组。
            # 竞态下进程组恰已消亡则跳过（ProcessLookupError / Windows 已退出竞态）。
            with suppress(ProcessLookupError, PermissionError):
                if sys.platform == "win32":
                    killer = await asyncio.create_subprocess_exec(
                        "taskkill",
                        "/PID",
                        str(proc.pid),
                        "/T",
                        "/F",
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await killer.wait()
                else:
                    os.killpg(proc.pid, signal.SIGKILL)
                await proc.wait()
            return 1, "hook timed out"
        except Exception:  # noqa: BLE001 - hook 命令崩溃视为失败（fail-safe 阻断）
            logger.exception("Hook failed (%s): %s", hook.event, hook.command)
            return 1, "hook failed"
