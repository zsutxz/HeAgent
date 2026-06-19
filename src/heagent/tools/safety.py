"""安全防护 — 工具调用执行前的安全检查。

仅对 "shell" 工具生效，检查分为两层：
  1. 内置危险模式（硬编码的 12 种）：rm -rf、fork bomb、format 等
  2. 用户自定义规则：BLACKLIST（拦截匹配项）或 WHITELIST（仅允许匹配项）

违反安全规则时抛出 SafetyViolation，AgentLoop 将其包装为 is_error 的 ToolResult。
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import TYPE_CHECKING

from heagent.exceptions import SafetyViolation

if TYPE_CHECKING:
    from heagent.types import ToolCall


class SafetyMode(StrEnum):
    """安全检查模式。"""

    BLACKLIST = "blacklist"  # 黑名单模式：拦截匹配的命令（默认）
    WHITELIST = "whitelist"  # 白名单模式：仅允许匹配的命令


# 内置的 12 种危险命令正则模式（不区分大小写）
_DANGEROUS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+|.*-rf\b)",  # rm -rf / rm -f
        r"\bformat\s+[a-zA-Z]:",  # format C:
        r"\bdd\s+if=",  # dd 磁盘操作
        r"\bmkfs\b",  # 格式化文件系统
        r"\bshutdown\b",  # 关机
        r"\breboot\b",  # 重启
        r"\bdel\s+/[sS]",  # del /s 递归删除 (Windows)
        r"\brmdir\s+/[sS]",  # rmdir /s 递归删除 (Windows)
        r":\(\)\{.*;\}",  # fork bomb (:(){ :|:& };:)
        r">\s*/dev/sd",  # 直接写入磁盘设备
        r"\bchmod\s+(-R\s+)?000\b",  # chmod 000 移除所有权限
        r"\bchown\s+(-R\s+)?root\b",  # chown root 提权
    ]
]


class SafetyGuard:
    """工具调用安全检查器，在执行前拦截危险操作。"""

    def __init__(
        self,
        mode: SafetyMode = SafetyMode.BLACKLIST,
        blocked_commands: list[str] | None = None,
        allowed_commands: list[str] | None = None,
    ) -> None:
        self.mode = mode  # 安全模式
        self._blocked: list[str] = blocked_commands or []  # 用户自定义黑名单规则
        self._allowed: list[str] = allowed_commands or []  # 用户自定义白名单规则
        self._blocked_compiled = [re.compile(p, re.IGNORECASE) for p in self._blocked]
        self._allowed_compiled = [re.compile(p, re.IGNORECASE) for p in self._allowed]
        self._violation_log: list[str] = []  # 违规记录，用于审计

    def check(self, call: ToolCall) -> None:
        """检查工具调用是否安全，不安全则抛出 SafetyViolation。

        检查流程（仅对 shell 工具）：
          1. 内置危险模式匹配 → 拦截
          2. 黑名单模式：匹配用户自定义黑名单 → 拦截
          3. 白名单模式：不在白名单中 → 拦截
        """
        # 非 shell 工具不检查
        if call.name != "shell":
            return
        command = call.arguments.get("command", "")
        if not isinstance(command, str):
            return

        # 第一层：内置危险模式检查
        for pat in _DANGEROUS_PATTERNS:
            if pat.search(command):
                msg = f"Blocked dangerous command: {command}"
                self._violation_log.append(msg)
                raise SafetyViolation(msg)

        # 第二层：用户自定义规则
        if self.mode == SafetyMode.BLACKLIST:
            # 黑名单模式：匹配任一规则即拦截
            for pat in self._blocked_compiled:
                if pat.search(command):
                    msg = f"Blocked by blacklist: {command}"
                    self._violation_log.append(msg)
                    raise SafetyViolation(msg)
        elif (
            self.mode == SafetyMode.WHITELIST
            and self._allowed_compiled
            and not any(pat.search(command) for pat in self._allowed_compiled)
        ):
            # 白名单模式：不在白名单中即拦截（空白名单不拦截任何命令）
            msg = f"Blocked (not in whitelist): {command}"
            self._violation_log.append(msg)
            raise SafetyViolation(msg)

    @property
    def violations(self) -> list[str]:
        """返回违规记录的副本（审计用）。"""
        return list(self._violation_log)
