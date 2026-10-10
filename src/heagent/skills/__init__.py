"""技能库域包 —— 可复用操作模式的存储、解析、匹配与包索引。

存储路径：.heagent/skills/{name}/SKILL.md + meta.yaml。每个技能是一个目录，
system_prompt 装配 / 工具面（skill_load 等）/ GUI / goal 工作流包解析皆经本包访问。
2026-09-21 Phase 4 C4 自 memory/ 拆分；2026-10-10 整体迁出为顶层 ``skills/`` 包
（:mod:`.skill_models` 模型与解析、:mod:`.skill_rewrite` 渲染与就地改写、
:mod:`.skill_catalog` 匹配与过期盘点、:mod:`.skill_store` 存储门面、
:mod:`.skill_meta` meta.yaml 契约、:mod:`.skill_packages` 声明式包索引、
:mod:`.skill_importer` 批量导入），本 ``__init__`` re-export 历史公共名。
"""

from __future__ import annotations

from heagent.skills.skill_meta import SkillMeta, SkillMetaError
from heagent.skills.skill_models import SkillContent, SkillMatch, SkillRewriteError
from heagent.skills.skill_store import SkillStore

__all__ = ["SkillContent", "SkillMatch", "SkillMeta", "SkillMetaError", "SkillRewriteError", "SkillStore"]
