"""安全防护 — 工具调用执行前的安全检查。

检查分两类：
  - 工具名 blacklist（对所有工具生效，含 MCP/内置/shell）：按 ``call.name`` 正则命中即拦截
  - shell 命令检查（仅 "shell" 工具）：两层——内置危险模式（17 种）+
    用户自定义规则（BLACKLIST 拦截匹配项 / WHITELIST 仅允许匹配项）
  - 非 shell 工具的 command 参数检查（P1-14）：对参数中含 "command" 键的任意工具
    也执行命令级检查（defense-in-depth）

违反安全规则时抛出 SafetyViolation，AgentLoop 将其包装为 is_error 的 ToolResult。
非真正安全边界，须 OS 级沙箱兜底（见 CLAUDE.md 安全声明）。
"""

from __future__ import annotations

import re
from collections import deque
from enum import StrEnum
from typing import TYPE_CHECKING, NoReturn

from heagent.exceptions import SafetyViolation

if TYPE_CHECKING:
    from heagent.types import ToolCall


class SafetyMode(StrEnum):
    """安全检查模式。"""

    BLACKLIST = "blacklist"  # 黑名单模式：拦截匹配的命令（默认）
    WHITELIST = "whitelist"  # 白名单模式：仅允许匹配的命令


# 内置的危险命令正则模式（不区分大小写），P1-2 补全：新增 poweroff/halt/curl-pipe-sh/wget-pipe-sh/
# /dev/tcp reverse shell/chmod 777/chmod +s/eval/source/fork bomb 通用形式/rm 分离标志位。
# P1-15 扩展：新增 nc/ncat 反向 shell、python/perl/ruby/php -e/-r 内联执行、
# iptables/systemctl 防火墙/服务篡改、crontab 持久化。
_DANGEROUS_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\brm\s+(-[a-zA-Z]*f[a-zA-Z]*\s+|.*-rf\b|.*\s-f\b)",  # rm -rf / rm -f / rm ... -f
        r"\bformat\s+[a-zA-Z]:",  # format C:
        r"\bdd\b",  # dd 磁盘操作（含 dd of=/dev/sda if=/dev/zero）
        r"\bmkfs\b",  # 格式化文件系统
        r"\bshutdown\b",  # 关机
        r"\breboot\b",  # 重启
        r"\bpoweroff\b",  # 关机变体
        r"\bhalt\b",  # 关机变体
        r"\bdel\s+/[sS]",  # del /s 递归删除 (Windows)
        r"\brmdir\s+/[sS]",  # rmdir /s 递归删除 (Windows)
        r":\(\)\s*\{[^}]*[;&|][^}]*\}",  # fork bomb — 花括号内含 ; & | 任一 shell 分隔符
        r"\.[^/\s]+\s*\{[^}]*[;&|][^}]*\}",  # fork bomb 通用形式 .name(){ ...|...& };.name
        r">\s*/dev/sd",  # 直接写入磁盘设备
        r"\bchmod\s+(-R\s+)?000\b",  # chmod 000 移除所有权限
        r"\bchmod\s+.*777\b",  # chmod 777 全局可写
        r"\bchmod\s+.*\+s\b",  # chmod +s setuid
        r"\bchown\s+(-R\s+)?root\b",  # chown root 提权
        r"\bcurl\b.*\|\s*(?:sh|bash)",  # curl ... | sh
        r"\bwget\b.*\|\s*(?:sh|bash)",  # wget ... | sh
        r"/dev/tcp/",  # /dev/tcp reverse shell
        r"\beval\b",  # eval 动态代码执行
        r"\bsource\b\s+(?:/|~|\.\.)",  # source 执行外部脚本
        # P1-15 新增：以下 6 条覆盖此前遗漏的常见攻击向量
        r"\b(?:nc|ncat|netcat)\b.*-e\b",  # netcat -e reverse shell
        r"\bpython\d*\s+-c\b",  # python -c 内联执行
        r"\b(?:perl|ruby|php)\d*\s+-[er]\b",  # perl/ruby/php -e/-r 内联执行
        r"\biptables\b\s+-F\b",  # iptables 清空所有规则
        r"\bsystemctl\b\s+disable\b",  # systemctl 禁用服务
        r"\bcrontab\b",  # crontab 修改持久化
    ]
]


class SafetyGuard:
    """工具调用安全检查器，在执行前拦截危险操作。"""

    def __init__(
        self,
        mode: SafetyMode = SafetyMode.BLACKLIST,
        blocked_commands: list[str] | None = None,
        allowed_commands: list[str] | None = None,
        blocked_tools: list[str] | None = None,
    ) -> None:
        self.mode = mode  # 安全模式
        self._blocked: list[str] = blocked_commands or []  # 用户自定义黑名单规则
        self._allowed: list[str] = allowed_commands or []  # 用户自定义白名单规则
        self._blocked_compiled = [re.compile(p, re.IGNORECASE) for p in self._blocked]
        self._allowed_compiled = [re.compile(p, re.IGNORECASE) for p in self._allowed]
        # 工具名 blacklist（对所有工具生效，含 MCP/内置/shell），按 call.name 正则命中拦截
        self._blocked_tools_compiled = [re.compile(p, re.IGNORECASE) for p in (blocked_tools or [])]
        # P2-1 修复：用 deque 限长，防止长运行会话无限增长导致内存泄漏
        self._violation_log: deque[str] = deque(maxlen=1000)

    def _block(self, msg: str) -> NoReturn:
        """记录违规并抛出 SafetyViolation。"""
        self._violation_log.append(msg)
        raise SafetyViolation(msg)

    def check(self, call: ToolCall) -> None:
        """检查工具调用是否安全，不安全则抛出 SafetyViolation。

        检查流程：
          0. 工具名 blacklist（对所有工具生效，含 MCP/内置/shell）→ 命中拦截
          1. 内置危险模式匹配（仅 shell）→ 拦截
          2. 黑名单模式：匹配用户自定义黑名单（仅 shell）→ 拦截
          3. 白名单模式：不在白名单中（仅 shell）→ 拦截
          4. P1-14：非 shell 但参数中含 "command" 键的工具，同样执行命令级检查
             （defense-in-depth，防止恶意 MCP tool 把危险命令藏在参数中绕过）
        """
        # 第零层：工具名 blacklist，对所有工具生效（MCP/内置/shell），命中即拦截
        for pat in self._blocked_tools_compiled:
            if pat.search(call.name):
                self._block(f"Blocked tool by name: {call.name}")

        # 提取 command 参数（shell 工具或其他携带 command 的工具）
        command = ""
        if call.name == "shell":
            command = call.arguments.get("command", "")
        else:
            # P1-14：非 shell 工具若参数中含 "command" 键，也做命令级检查
            # （defense-in-depth — 恶意 MCP tool 可把危险命令藏在参数中）
            command = call.arguments.get("command", "")
            if not isinstance(command, str) or not command:
                return

        if not isinstance(command, str) or not command:
            return

        # 第一层：内置危险模式检查
        for pat in _DANGEROUS_PATTERNS:
            if pat.search(command):
                self._block(f"Blocked dangerous command: {command}")

        # 第二层：用户自定义规则
        if self.mode == SafetyMode.BLACKLIST:
            # 黑名单模式：匹配任一规则即拦截
            for pat in self._blocked_compiled:
                if pat.search(command):
                    self._block(f"Blocked by blacklist: {command}")
        elif (
            self.mode == SafetyMode.WHITELIST
            and self._allowed_compiled
            and not any(pat.search(command) for pat in self._allowed_compiled)
        ):
            # 白名单模式：不在白名单中即拦截（空白名单不拦截任何命令）
            self._block(f"Blocked (not in whitelist): {command}")

    @property
    def violations(self) -> list[str]:
        """返回违规记录的副本（审计用）。"""
        return list(self._violation_log)
