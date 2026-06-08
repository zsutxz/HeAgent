"""人格加载器 — 从全局和项目两级 SOUL.md 加载 Agent 人格定义。

两级结构：
  - 全局：~/.heagent/SOUL.md（用户默认人格）
  - 项目：.heagent/SOUL.md（项目特定人格，覆盖全局）

合并策略：项目级存在时使用项目级，否则回退到全局级。不做合并。
"""

from __future__ import annotations

from pathlib import Path


class SoulStore:
    """SOUL.md 人格加载器，支持全局/项目两级。"""

    def __init__(
        self,
        global_path: str = "~/.heagent/SOUL.md",
        project_path: str = ".heagent/SOUL.md",
    ) -> None:
        self._global = Path(global_path).expanduser()
        self._project = Path(project_path)

    def load(self) -> str | None:
        """加载人格内容。项目级 SOUL.md 覆盖全局级。"""
        # 项目级优先
        if self._project.is_file():
            content = self._project.read_text(encoding="utf-8").strip()
            return content or None
        # 回退到全局级
        if self._global.is_file():
            content = self._global.read_text(encoding="utf-8").strip()
            return content or None
        return None
