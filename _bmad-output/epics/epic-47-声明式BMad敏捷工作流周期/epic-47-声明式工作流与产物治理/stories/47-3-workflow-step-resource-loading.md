---
title: 'Load declarative workflow and ordered step resources'
type: 'feature'
status: 'done'
epic: 47
story: 3
baseline_commit: '9e83a57'
context:
  - 'E:/AI/HeAgent/AGENTS.md'
  - 'E:/AI/HeAgent/src/heagent/memory/skill_packages.py'
  - 'E:/AI/HeAgent/tests/test_skill_packages.py'
---

# Story 47-3: Markdown workflow/step 资源加载

## Acceptance Criteria

- [x] 可从 skill 包加载 `workflow.md` 和有序 step 文件。
- [x] step 的输入、输出、next、checkpoint 和验证规则可解析。
- [x] 缺失、重复、非法顺序或包外资源引用显式失败。

## Dependencies

47-1

## Tasks

- [x] `src/heagent/memory/skill_packages.py` -- 增加 workflow/step 资源模型与有序发现，复用现有根目录围栏。
- [x] `tests/test_workflow_resources.py` -- 覆盖正常加载、顺序、frontmatter、缺失/重复/越界和兼容行为。
- [x] `.heagent/workflows/bmad-development/` -- 增加最小 workflow.md 与两个示例 step，供 Runner 后续使用。

## Dev Agent Record

### Completion Notes

- `SkillPackage` 新增 `WorkflowResource`/`WorkflowStepResource`，支持显式或 `step-NN-*.md` 自动发现的有序步骤。
- step frontmatter 支持 input/output/next/checkpoint/validation，缺失、重复、断序、非法引用和包外路径均显式失败。
- 保留现有 `read_step`、reference/template/asset/script 读取行为和根目录围栏。

### Verification Evidence

- `pytest tests/test_workflow_resources.py tests/test_skill_packages.py -q --basetemp E:/AI/HeAgent/workflow_test_tmp47_3` -- 38 passed, 2 skipped。
- `ruff check src tests` -- passed。
- `mypy src` -- passed，98 source files。
