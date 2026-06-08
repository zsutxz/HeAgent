"""上下文文件扫描器 — 从项目目录加载上下文文件注入系统提示词。

扫描顺序（高→低优先级）：.heagent/CONTEXT.md > AGENTS.md > CLAUDE.md
找到的文件按优先级合并，每段以文件路径作为分隔标记。
"""

from __future__ import annotations

from pathlib import Path

# 优先级从高到低
_CONTEXT_FILES: list[str] = [
    ".heagent/CONTEXT.md",
    "AGENTS.md",
    "CLAUDE.md",
]


def load_context_files(cwd: str | None = None) -> str | None:
    """扫描 CWD 下的上下文文件，按优先级合并返回。

    参数：
        cwd: 扫描的根目录，默认为当前工作目录
    返回：
        合并后的上下文内容，无文件时返回 None
    """
    base = Path(cwd or ".")
    parts: list[str] = []
    for rel_path in _CONTEXT_FILES:
        path = base / rel_path
        if path.is_file():
            content = path.read_text(encoding="utf-8").strip()
            if content:
                parts.append(f"## {rel_path}\n\n{content}")
    return "\n\n---\n\n".join(parts) if parts else None
