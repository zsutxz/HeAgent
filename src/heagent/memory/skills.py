"""技能存储 — 将可复用的操作模式提炼为标准目录结构。

存储路径：.heagent/skills/{name}/SKILL.md
每个技能是一个目录，SKILL.md 为必需文件，使用 YAML frontmatter 定义元数据。
支持解析、部分更新和基于关键词匹配的自动调用。

目录结构（参考 hermes-agent）：
  skills/<name>/
  ├── SKILL.md           # 必须 — 技能定义（frontmatter + markdown 正文）
  ├── references/        # 可选 — 参考文档
  ├── templates/         # 可选 — 模板文件
  └── scripts/           # 可选 — 可执行脚本
"""

from __future__ import annotations

import contextlib
import re
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, Field

from heagent.engine.persist import atomic_write_text


class SkillContent(BaseModel):
    """解析后的技能结构化字段。

    使用 Pydantic BaseModel（项目硬约束：数据模型一律 Pydantic，不得用 dataclass）。
    """

    name: str
    description: str
    pattern: str
    steps: list[str]
    created: str
    tags: list[str] = Field(default_factory=list)
    usage_count: int = 0
    last_used: str = ""


class SkillStore:
    """技能存储管理器，支持 CRUD 操作。

    每个技能以目录形式存储，SKILL.md 为入口文件。
    """

    def __init__(self, base_dir: str = ".heagent/skills") -> None:
        self._base = Path(base_dir)

    # ---- 路径工具 ----

    def _skill_dir(self, name: str) -> Path:
        """技能目录路径（名称规范化复用 _validate_name，保证 save/delete/load 路径一致）。"""
        return self._base / self._validate_name(name)

    def _skill_md(self, name: str) -> Path:
        """SKILL.md 文件路径。"""
        return self._skill_dir(name) / "SKILL.md"

    @staticmethod
    def _validate_name(name: str) -> str:
        """校验技能名称：仅允许英文、数字、下划线和连字符。"""
        safe = name.replace(" ", "_").replace("/", "-")
        if not safe.isascii() or not all(c.isalnum() or c in "_-" for c in safe):
            raise ValueError(f"Skill name must be English alphanumeric with _ or -, got: '{name}'")
        return safe

    # ---- CRUD ----

    def save(
        self,
        name: str,
        description: str,
        pattern: str,
        steps: list[str],
        *,
        tags: list[str] | None = None,
        usage_count: int = 0,
        last_used: str = "",
        created: str | None = None,
    ) -> str:
        """保存一个技能为标准目录结构。

        创建 skills/<name>/SKILL.md，包含 YAML frontmatter 和 Markdown 正文。
        返回 SKILL.md 的路径。

        ``created`` 为 None 时自动生成当前时间；``update()`` / ``record_usage()``
        透传原值，防止每次调用覆写原始创建时间（P1-7 修复）。
        """
        safe = self._validate_name(name)
        skill_dir = self._base / safe
        skill_dir.mkdir(parents=True, exist_ok=True)

        if created is None:
            created = datetime.now().isoformat()
        tag_str = ", ".join(tags) if tags else ""
        # frontmatter
        fm_lines = [
            "---",
            f"name: {safe}",
            f'description: "{description}"',
            f"created: {created}",
        ]
        if tag_str:
            fm_lines.append(f"tags: [{tag_str}]")
        fm_lines.append(f"usage_count: {usage_count}")
        if last_used:
            fm_lines.append(f'last_used: "{last_used}"')
        fm_lines.append("---")
        fm_lines.append("")

        # 正文
        body_lines = [f"# {safe}", ""]
        if pattern:
            body_lines.append("## Pattern")
            body_lines.append(pattern)
            body_lines.append("")
        body_lines.append("## Steps")
        for i, step in enumerate(steps, 1):
            body_lines.append(f"{i}. {step}")
        body_lines.append("")

        content = "\n".join(fm_lines) + "\n" + "\n".join(body_lines)
        md_path = skill_dir / "SKILL.md"
        atomic_write_text(md_path, content)
        return str(md_path)

    def load(self, name: str) -> str | None:
        """按名称加载 SKILL.md 内容。不存在或名称非法返回 None。"""
        try:
            path = self._skill_md(name)
        except ValueError:
            return None
        if path.exists():
            return path.read_text(encoding="utf-8")
        return None

    def list_skills(self) -> list[str]:
        """返回所有已存储的技能名称（目录名，按名称排序）。"""
        if not self._base.exists():
            return []
        return sorted(d.name for d in self._base.iterdir() if d.is_dir() and (d / "SKILL.md").exists())

    def delete(self, name: str) -> bool:
        """删除指定技能目录。返回是否成功删除。"""
        try:
            skill_dir = self._skill_dir(name)
        except ValueError:
            return False
        if skill_dir.is_dir():
            shutil.rmtree(skill_dir)
            return True
        return False

    def all_skills_content(self) -> list[str]:
        """返回所有技能 SKILL.md 的完整内容（用于注入系统提示词）。"""
        if not self._base.exists():
            return []
        contents: list[str] = []
        for name in self.list_skills():
            raw = self.load(name)
            if raw:
                contents.append(raw)
        return contents

    # ---- 解析与更新 ----

    def parse(self, name: str) -> SkillContent | None:
        """将 SKILL.md 解析为结构化字段。不存在返回 None。"""
        raw = self.load(name)
        if raw is None:
            return None
        return self._parse_skill_md(name, raw)

    def update(
        self,
        name: str,
        *,
        description: str | None = None,
        pattern: str | None = None,
        steps: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> str | None:
        """部分更新已有技能。仅覆盖非 None 字段，其余保持原样。返回 SKILL.md 路径或 None。"""
        existing = self.parse(name)
        if existing is None:
            return None
        return self.save(
            name,
            description if description is not None else existing.description,
            pattern if pattern is not None else existing.pattern,
            steps if steps is not None else existing.steps,
            tags=tags if tags is not None else existing.tags,
            usage_count=existing.usage_count,
            last_used=existing.last_used,
            created=existing.created,  # P1-7 修复：保留原始创建时间
        )

    # ---- 使用追踪与策展 ----

    def record_usage(self, name: str) -> None:
        """递增技能使用计数并更新最后使用时间。"""
        existing = self.parse(name)
        if existing is None:
            return
        now = datetime.now().isoformat()
        self.save(
            name,
            existing.description,
            existing.pattern,
            existing.steps,
            tags=existing.tags or None,
            usage_count=existing.usage_count + 1,
            last_used=now,
            created=existing.created,  # P1-7 修复：保留原始创建时间
        )

    def stale_skills(self, days: int = 30) -> list[str]:
        """返回超过 N 天未使用的技能名称列表。"""
        cutoff = datetime.now() - timedelta(days=days)
        stale: list[str] = []
        for name in self.list_skills():
            parsed = self.parse(name)
            if parsed is None:
                continue
            if parsed.usage_count == 0:
                stale.append(name)
            elif parsed.last_used:
                try:
                    last = datetime.fromisoformat(parsed.last_used)
                    if last < cutoff:
                        stale.append(name)
                except ValueError:
                    pass
        return stale

    def archive(self, name: str) -> bool:
        """将技能目录移动到 .heagent/skills/.archive/。"""
        try:
            src = self._skill_dir(name)
        except ValueError:
            return False
        if not src.is_dir():
            return False
        archive_dir = self._base / ".archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(archive_dir / name))
        return True

    # ---- 匹配 ----

    def matching_skills(self, prompt: str, threshold: float) -> list[str]:
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
            # pattern + tags 都参与匹配
            match_text = f"{parsed.pattern} {' '.join(parsed.tags)}"
            pattern_words = set(match_text.lower().split())
            if not pattern_words:
                continue
            overlap = len(prompt_words & pattern_words)
            ratio = overlap / len(pattern_words)
            if ratio >= threshold:
                matches.append((ratio, name))
        matches.sort(key=lambda x: x[0], reverse=True)
        return [name for _, name in matches]

    # ---- 解析器 ----

    @staticmethod
    def _parse_skill_md(name: str, content: str) -> SkillContent:
        """解析 SKILL.md（YAML frontmatter + Markdown 正文）为结构化字段。

        容错处理：缺失字段默认为空字符串/空列表，不抛异常。
        """
        description = ""
        created = ""
        tags: list[str] = []
        pattern_lines: list[str] = []
        steps: list[str] = []
        usage_count: int = 0
        last_used: str = ""

        # 分离 frontmatter 和正文
        body = content
        fm_match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
        if fm_match:
            fm_text = fm_match.group(1)
            body = content[fm_match.end() :]
            # 简单解析 frontmatter（不引入 yaml 依赖）
            for line in fm_text.splitlines():
                stripped = line.strip()
                if stripped.startswith("description:"):
                    description = stripped.split(":", 1)[1].strip().strip('"').strip("'")
                elif stripped.startswith("created:"):
                    created = stripped.split(":", 1)[1].strip()
                elif stripped.startswith("tags:"):
                    tag_part = stripped.split(":", 1)[1].strip()
                    if tag_part.startswith("[") and tag_part.endswith("]"):
                        tags = [t.strip() for t in tag_part[1:-1].split(",") if t.strip()]
                elif stripped.startswith("usage_count:"):
                    with contextlib.suppress(ValueError):
                        usage_count = int(stripped.split(":", 1)[1].strip())
                elif stripped.startswith("last_used:"):
                    last_used = stripped.split(":", 1)[1].strip().strip('"').strip("'")

        # 解析正文
        section = ""
        for line in body.splitlines():
            stripped = line.strip()
            if stripped == "## Pattern":
                section = "pattern"
            elif stripped == "## Steps":
                section = "steps"
            elif section == "pattern" and stripped:
                pattern_lines.append(stripped)
            elif section == "steps" and stripped:
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
            tags=tags,
            usage_count=usage_count,
            last_used=last_used,
        )
