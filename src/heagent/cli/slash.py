"""斜杠命令系统（Epic 31）。

为 CLI 交互模式提供**注册表驱动的斜杠命令**（替代 ``cli.py`` 里的 if/elif 硬编码），
并支持**用户自定义命令**——从 ``.heagent/commands/*.md``（项目级，优先）与
``~/.heagent/commands/*.md``（用户级）加载，frontmatter 声明 ``name``/``description``，
正文为 prompt 模板，触发时作为一条用户消息提交给 AgentLoop。

本模块是**零 heagent 依赖的纯数据/注册表模块**（仅依赖 pydantic + 零依赖公共模块
``heagent.pub.frontmatter``），handler 由调用方（``cli/interactive.py``）以闭包注入，避免 ``slash``
反向依赖 ``agent``/``providers``——对齐项目 DAG 硬约束（新增能力不得从 ``agent/`` 导入核心）。
"""

from __future__ import annotations

import difflib
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

from pydantic import BaseModel

from heagent.pub.frontmatter import parse_inline_pairs, split_frontmatter


class CustomSlashCommand(BaseModel):
    """用户自定义斜杠命令（来自 ``.heagent/commands/*.md``）。"""

    name: str
    description: str
    prompt: str  # 正文模板：触发时作为用户消息提交给 AgentLoop


# 斜杠命令 handler：async (args: str) -> None。
SlashHandler = Callable[[str], Awaitable[None]]

#: ``/help <command>`` 详情里每段的最多条数（超出截断，只留前若干条免得刷屏）。
_HELP_EXAMPLE_LIMIT = 8


class SlashCommandInfo(BaseModel):
    """一条斜杠命令的对外可见信息（``/help`` 列表与详情共用同一数据源）。

    ``usage`` / ``arguments`` / ``examples`` 为空表示**未提供元数据**（如走 3 参
    ``register`` 的调用方、或自定义命令）——渲染层负责给显式兜底文案，不留空块。
    ``usage`` / ``arguments`` 为多行文本（渲染层按行缩进两格）。
    """

    name: str
    description: str
    usage: str = ""
    arguments: str = ""
    examples: list[str] = []
    custom: bool = False


@dataclass(frozen=True)
class _Registration:
    """注册表内部条目：命令信息 + handler（handler 不外泄到渲染层）。"""

    info: SlashCommandInfo
    handler: SlashHandler


class SlashRegistry:
    """斜杠命令注册表：``name → (命令信息, handler)``。

    name 一律小写（大小写不敏感）；dispatch 返回是否命中（False = 未注册，调用方
    决定是否透传给 AgentLoop 当普通消息处理）。
    """

    def __init__(self) -> None:
        self._commands: dict[str, _Registration] = {}

    def register(self, name: str, description: str, handler: SlashHandler) -> None:
        """注册（或覆盖）一个斜杠命令（仅描述，无详细帮助元数据）。"""
        self.register_command(name, description, handler)

    def register_command(
        self,
        name: str,
        description: str,
        handler: SlashHandler,
        *,
        usage: str = "",
        arguments: str = "",
        examples: Sequence[str] = (),
        custom: bool = False,
    ) -> None:
        """注册（或覆盖）一个斜杠命令，并登记 ``/help <command>`` 所需的元数据。

        ``custom=True`` 标记来自 ``.heagent/commands/*.md`` 的自定义命令——缺元数据时
        渲染层据此给出「自定义命令，无参数说明」而非通用兜底。
        """
        info = SlashCommandInfo(
            name=name.lower(),
            description=description,
            usage=usage,
            arguments=arguments,
            examples=list(examples)[:_HELP_EXAMPLE_LIMIT],
            custom=custom,
        )
        self._commands[info.name] = _Registration(info=info, handler=handler)

    def has(self, name: str) -> bool:
        """是否已注册该命令名。"""
        return name.lower() in self._commands

    def names(self) -> list[str]:
        """返回全部命令名（字典序）。"""
        return sorted(self._commands)

    def describe(self, name: str) -> str:
        """返回命令描述；未注册返回空串。"""
        entry = self._commands.get(name.lower())
        return entry.info.description if entry else ""

    def info(self, name: str) -> SlashCommandInfo | None:
        """返回命令的完整信息；未注册返回 None。"""
        entry = self._commands.get(name.lower())
        return entry.info if entry else None

    def commands(self) -> list[SlashCommandInfo]:
        """返回全部命令信息（按名排序，与 :meth:`names` 同序）。"""
        return [self._commands[name].info for name in self.names()]

    def suggest(self, name: str, *, limit: int = 3) -> list[str]:
        """给出与 ``name`` 最接近的已注册命令名（拼错兜底，至少 1 条）。

        ``difflib`` 判定无相似项时按「长度差 → 字典序」取最近一条——帮助页宁愿给一个
        不完美建议，也不留空的「Did you mean」。
        """
        candidate = name.lower().strip()
        names = self.names()
        if not names:
            return []
        if not candidate:
            return names[:limit]
        matches = difflib.get_close_matches(candidate, names, n=limit, cutoff=0.5)
        if matches:
            return matches
        return sorted(names, key=lambda item: (abs(len(item) - len(candidate)), item))[:1]

    async def dispatch(self, name: str, args: str) -> bool:
        """按名分发；命中返回 True，未命中返回 False。"""
        entry = self._commands.get(name.lower())
        if entry is None:
            return False
        await entry.handler(args)
        return True


def load_custom_commands(commands_dirs: list[str | Path] | None = None) -> list[CustomSlashCommand]:
    """加载用户自定义斜杠命令。

    默认目录（后者优先覆盖前者）：
      - ``~/.heagent/commands/``（用户级，先加载）
      - ``.heagent/commands/``（项目级，后加载，覆盖同名）

    只扫描 ``*.md``；解析失败（缺正文 / 读错误）静默跳过，不阻断启动。
    """
    if commands_dirs is None:
        commands_dirs = [str(Path.home() / ".heagent" / "commands"), ".heagent/commands"]
    merged: dict[str, CustomSlashCommand] = {}
    for directory in commands_dirs:
        for command in _load_dir(directory):
            merged[command.name] = command
    return [merged[name] for name in sorted(merged)]


def _load_dir(directory: str | Path) -> list[CustomSlashCommand]:
    """加载单个目录下的全部 ``*.md`` 命令（忽略错误）。"""
    base = Path(directory)
    if not base.is_dir():
        return []
    commands: list[CustomSlashCommand] = []
    for path in sorted(base.glob("*.md")):
        try:
            command = _parse_command_md(path)
        except (OSError, ValueError):
            continue
        if command is not None:
            commands.append(command)
    return commands


def _parse_command_md(path: Path) -> CustomSlashCommand | None:
    """解析一个命令 ``.md`` 文件：frontmatter 取 name/description，正文为 prompt 模板。"""
    raw = path.read_text(encoding="utf-8")
    name = ""
    description = ""
    body = raw
    split = split_frontmatter(raw)
    if split is not None:
        fm_text, _end, body = split
        pairs = parse_inline_pairs(fm_text, keys=("name", "description"))
        name = pairs.get("name", "").strip().strip('"').strip("'")
        description = pairs.get("description", "").strip().strip('"').strip("'")
    if not name:
        name = path.stem  # 无 frontmatter 时回退为文件名
    prompt = body.strip()
    if not prompt:
        return None
    return CustomSlashCommand(name=name, description=description, prompt=prompt)
