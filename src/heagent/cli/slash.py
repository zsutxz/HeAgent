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

from collections.abc import Awaitable, Callable
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


class SlashRegistry:
    """斜杠命令注册表：``name → (description, handler)``。

    name 一律小写（大小写不敏感）；dispatch 返回是否命中（False = 未注册，调用方
    决定是否透传给 AgentLoop 当普通消息处理）。
    """

    def __init__(self) -> None:
        self._commands: dict[str, tuple[str, SlashHandler]] = {}

    def register(self, name: str, description: str, handler: SlashHandler) -> None:
        """注册（或覆盖）一个斜杠命令。"""
        self._commands[name.lower()] = (description, handler)

    def has(self, name: str) -> bool:
        """是否已注册该命令名。"""
        return name.lower() in self._commands

    def names(self) -> list[str]:
        """返回全部命令名（字典序）。"""
        return sorted(self._commands)

    def describe(self, name: str) -> str:
        """返回命令描述；未注册返回空串。"""
        entry = self._commands.get(name.lower())
        return entry[0] if entry else ""

    async def dispatch(self, name: str, args: str) -> bool:
        """按名分发；命中返回 True，未命中返回 False。"""
        entry = self._commands.get(name.lower())
        if entry is None:
            return False
        await entry[1](args)
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
