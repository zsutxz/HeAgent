"""技能存储 — 将可复用的操作模式提炼为独立的 Markdown 文件。

存储路径：.heagent/skills/{name}.md
每个技能文件包含：名称、描述、创建时间、模式描述、步骤列表。
支持解析、部分更新和基于关键词匹配的自动调用。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


@dataclass
class SkillContent:
    """解析后的技能结构化字段。"""

    name: str
    description: str
    pattern: str
    steps: list[str]
    created: str


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

    def parse(self, name: str) -> SkillContent | None:
        """将技能 Markdown 文件解析为结构化字段。不存在返回 None。"""
        raw = self.load(name)
        if raw is None:
            return None
        return self._parse_markdown(name, raw)

    def update(
        self,
        name: str,
        *,
        description: str | None = None,
        pattern: str | None = None,
        steps: list[str] | None = None,
    ) -> str | None:
        """部分更新已有技能。仅覆盖非 None 字段，其余保持原样。返回文件路径或 None。"""
        existing = self.parse(name)
        if existing is None:
            return None
        return self.save(
            name,
            description if description is not None else existing.description,
            pattern if pattern is not None else existing.pattern,
            steps if steps is not None else existing.steps,
        )

    def matching_skills(self, prompt: str, threshold: float = 0.3) -> list[str]:
        """返回与用户提示词关键词重叠的技能名称（按相关度降序）。

        匹配算法：prompt 词集 ∩ pattern 词集 / pattern 词集长度 ≥ threshold。
        """
        if not prompt.strip():
            return []
        prompt_words = set(prompt.lower().split())
        matches: list[tuple[float, str]] = []
        for name in self.list_skills():
            parsed = self.parse(name)
            if parsed is None:
                continue
            pattern_words = set(parsed.pattern.lower().split())
            if not pattern_words:
                continue
            overlap = len(prompt_words & pattern_words)
            ratio = overlap / len(pattern_words)
            if ratio >= threshold:
                matches.append((ratio, name))
        matches.sort(key=lambda x: x[0], reverse=True)
        return [name for _, name in matches]

    @staticmethod
    def _parse_markdown(name: str, content: str) -> SkillContent:
        """解析技能 Markdown 内容为结构化字段。

        容错处理：缺失字段默认为空字符串/空列表，不抛异常。
        """
        lines = content.strip().splitlines()
        description = ""
        created = ""
        pattern_lines: list[str] = []
        steps: list[str] = []
        section = ""
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("- **Description:**"):
                description = stripped.split("**Description:**", 1)[1].strip()
            elif stripped.startswith("- **Created:**"):
                created = stripped.split("**Created:**", 1)[1].strip()
            elif stripped == "## Pattern":
                section = "pattern"
            elif stripped == "## Steps":
                section = "steps"
            elif section == "pattern" and stripped:
                pattern_lines.append(stripped)
            elif section == "steps" and stripped:
                # 去掉 "1. step text" 前缀 → "step text"
                dot_pos = stripped.find(". ")
                if dot_pos >= 0 and stripped[:dot_pos].isdigit():
                    steps.append(stripped[dot_pos + 2 :])
                else:
                    steps.append(stripped)
        return SkillContent(
            name=name,
            description=description,
            pattern="\n".join(pattern_lines),
            steps=steps,
            created=created,
        )
