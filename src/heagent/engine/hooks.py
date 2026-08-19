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
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

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


class HookConfig(BaseModel):
    """一条 hook 配置（来自 ``hooks.json`` 的 ``hooks`` 数组元素）。"""

    event: str  # PreToolUse / PostToolUse / SessionStart / SessionEnd
    command: str  # shell 命令
    matcher: str = Field(default="")  # 工具名过滤（PreToolUse/PostToolUse）；空 = 全部
    block: bool = False  # PreToolUse：命令退出码非 0 则阻断工具调用


@dataclass
class HookResult:
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
                hooks.append(HookConfig(**raw))
            except Exception as exc:  # noqa: BLE001 - 单条非法跳过，不影响其他 hook
                logger.warning("Invalid hook config %r: %s", raw, exc)
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
        env = {**os.environ, "HEAGENT_EVENT": hook.event, "HEAGENT_TOOL_NAME": tool_name}
        if run_context is not None:
            env["HEAGENT_RUN_ID"] = run_context.run_id
            env["HEAGENT_SESSION_ID"] = run_context.session_id or ""
        try:
            proc = await asyncio.create_subprocess_shell(
                hook.command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=self._timeout)
            return proc.returncode or 0, stdout.decode(errors="replace")
        except TimeoutError:
            logger.warning("Hook timed out (%s): %s", hook.event, hook.command)
            return 1, "hook timed out"
        except Exception:  # noqa: BLE001 - hook 命令崩溃视为失败（fail-safe 阻断）
            logger.exception("Hook failed (%s): %s", hook.event, hook.command)
            return 1, "hook failed"
