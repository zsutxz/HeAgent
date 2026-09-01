---
title: 'Generic workflow runner and artifact gates'
type: 'feature'
status: 'done'
epic: 47
story: 4
baseline_commit: 'debffea'
context:
  - 'E:/AI/HeAgent/AGENTS.md'
  - 'E:/AI/HeAgent/src/heagent/engine/workflow.py'
  - 'E:/AI/HeAgent/src/heagent/memory/skill_packages.py'
  - 'E:/AI/HeAgent/tests/test_engine_workflow.py'
---

# Story 47-4: 通用 WorkflowRunner 与阶段 Gate

## Acceptance Criteria

- [x] Runner 一次只执行一个 step，并按 Markdown 声明顺序推进。
- [x] 输入、输出、章节、验收和 Definition of Ready/Done 均可验证。
- [x] checkpoint、waiting_user、blocked、failed 均可恢复且不伪造完成。

## Dependencies

47-2, 47-3

## Tasks

- [x] `src/heagent/engine/workflow_runner.py` -- 实现基于 WorkflowResource 的单 step Runner、输入/输出 Gate、状态转换和 checkpoint 回调。
- [x] `src/heagent/engine/__init__.py` -- 导出 Runner 和 Pydantic 执行结果模型。
- [x] `tests/test_workflow_runner.py` -- 覆盖顺序推进、缺失产物、checkpoint、waiting_user、blocked、failed 和重复执行。

## Dev Agent Record

### Completion Notes

- 新增通用 `WorkflowRunner`，一次仅执行一个 Markdown step，按声明顺序推进并校验 input/output/validation。
- waiting_user、blocked、failed 保持当前 step，支持显式 `resume()`；checkpoint 同步保存 runner 和 Goal workflow 元数据。
- 统一 `active_step`/`completed_steps` 为 0-based 内部索引，避免恢复时混用 step 文件 1-based 编号。

### Verification Evidence

- `pytest tests/test_workflow_runner.py tests/test_engine_workflow.py -q --basetemp E:/AI/HeAgent/workflow_test_tmp47_4` -- 25 passed。
- `ruff check src tests` -- passed。
- `mypy src` -- passed，99 source files。
