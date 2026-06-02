"""技能存储 — 将可复用的操作模式提炼为独立的 Markdown 文件。

存储路径：.heagent/skills/{name}.md
每个技能文件包含：名称、描述、创建时间、模式描述、步骤列表。

当前状态：已实现但未接入 AgentLoop。
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


class SkillStore:
    """技能存储管理器，支持 CRUD 操作。"""

    def __init__(self, base_dir: str = ".heagent/skills") -> None:
        self._base = Path(base_dir)

    def save(self, name: str, description: str, pattern: str, steps: list[str]) -> str:
        """保存一个技能为 Markdown 文件。

        参数：
            name: 技能名称（空格替换为下划线，斜杠替换为连字符）
            description: 技能描述
            pattern: 模式描述（何时使用此技能）
            steps: 执行步骤列表
        返回：
            保存的文件路径
        """
        self._base.mkdir(parents=True, exist_ok=True)
        safe = name.replace(" ", "_").replace("/", "-")
        path = self._base / f"{safe}.md"
        lines = [
            f"# {name}",
            "",
            f"- **Description:** {description}",
            f"- **Created:** {datetime.now().isoformat()}",
            "",
            "## Pattern",
            pattern,
            "",
            "## Steps",
        ]
        for i, step in enumerate(steps, 1):
            lines.append(f"{i}. {step}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(path)

    def load(self, name: str) -> str | None:
        """按名称加载技能文件内容。不存在返回 None。"""
        safe = name.replace(" ", "_").replace("/", "-")
        path = self._base / f"{safe}.md"
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def list_skills(self) -> list[str]:
        """返回所有已存储的技能名称（按名称排序）。"""
        if not self._base.exists():
            return []
        return sorted(p.stem for p in self._base.glob("*.md"))

    def delete(self, name: str) -> bool:
        """删除指定技能文件。返回是否成功删除。"""
        safe = name.replace(" ", "_").replace("/", "-")
        path = self._base / f"{safe}.md"
        if path.exists():
            path.unlink()
            return True
        return False

    def all_skills_content(self) -> list[str]:
        """返回所有技能文件的完整内容（可用于注入系统提示词）。"""
        if not self._base.exists():
            return []
        return [p.read_text(encoding="utf-8") for p in sorted(self._base.glob("*.md"))]
