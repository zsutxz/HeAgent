---
title: "Story 42.4 BMad manifest 导入器"
type: feature
created: "2026-09-01"
status: done
---

## 已交付

- 新增 Pydantic manifest/锁模型和 `SkillImporter`。
- 解析 BMad CSV manifest，将 `bmad-*` 来源 ID 映射到规范的 `he-*` 技能包目录。
- 复用 `resolve_under_root` 进行来源路径围栏，拒绝缺失或非 `SKILL.md` 来源。
- 使用 SHA-256 计算入口文件哈希，在 `manifest.lock` 记录源路径、目标路径、版本和哈希。
- 使用原子加锁持久化，并保持条目确定性排序。
- 相同源哈希幂等；元数据变化、哈希变化、重复行和损坏锁均显式失败。
- 提供异步外观，同时保留同步 API。

## 验证

- `pytest tests/test_skill_importer.py tests/test_skill_packages.py tests/test_memory.py tests/test_skill_tools.py`: 75 passed, 2 skipped.
- `ruff check src/heagent/memory/skill_importer.py tests/test_skill_importer.py`: passed.
- `mypy src/heagent/memory/skill_importer.py src/heagent/memory/skill_packages.py`: passed.
