"""技能存储 — 将可复用的操作模式提炼为标准目录结构。

存储路径：.heagent/skills/{name}/SKILL.md
每个技能是一个目录，system_prompt 装配 / 工具面（skill_load 等）/ GUI 皆经本模块
访问。2026-09-21 Phase 4 C4 拆分：单文件拆为 :mod:`.skill_models`（模型与解析）、
:mod:`.skill_rewrite`（渲染与就地改写）、:mod:`.skill_catalog`（匹配与过期盘点）、
:mod:`.skill_store`（存储门面）。本模块 re-export 全部历史公共名——既有导入与
monkeypatch 缝不受拆分影响。
"""

from __future__ import annotations

from heagent.memory.skill_models import SkillContent, SkillMatch, SkillRewriteError
from heagent.memory.skill_store import SkillStore

__all__ = ["SkillContent", "SkillMatch", "SkillRewriteError", "SkillStore"]
