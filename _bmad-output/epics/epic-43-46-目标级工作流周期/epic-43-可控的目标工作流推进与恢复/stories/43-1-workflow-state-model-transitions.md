---
status: done
baseline_commit: current
---

# Story 43.1: 目标工作流状态模型与确定性迁移

As a 框架维护者,
I want 用 Pydantic 模型表达目标阶段、活动技能、活动 step、状态和阻塞原因，并由代码校验合法迁移,
So that LLM 输出不能绕过工作流边界或伪造完成状态。

## Acceptance Criteria

- [x] 新目标默认从 `discovery` 和 `pending` 开始，并包含运行时元数据字段。
- [x] 合法迁移更新 phase/status/reason，且返回新状态而不修改原状态。
- [x] 非法迁移、未满足前置条件、空 reason 显式失败且原状态不变。
- [x] blocked/failed 状态不可继续迁移；done 为终态。
- [x] 不复制或修改 `GOAL.md` 的 Story checkbox 状态。

## Tasks/Subtasks

- [x] 新增 `engine/workflow.py` 的 Pydantic 状态模型与阶段/状态枚举。
- [x] 实现 `WorkflowOrchestrator` 的合法迁移、阻塞和失败操作。
- [x] 从 `engine` 包导出工作流公共类型。
- [x] 添加状态边界与迁移意图测试。
- [x] 运行专项测试、ruff 和 mypy。

### Review Findings

- [x] [Review][Patch] 终态、等待闸门、回顾阶段可达性、输入校验和深拷贝边界 — 已修复并通过专项回归。
- [x] [Review][Patch] `can_transition` 对 blocked/failed 状态返回错误可用性 — 已修复并增加测试。

## Dev Notes

- 保持 engine -> types/exceptions/tools 的依赖方向；本 Story 不导入 `agent`。
- `GOAL.md` 是看板状态权威，`GoalWorkflowState` 只保存运行时元数据。
- 后续 checkpoint、Token 分段和 CLI Story 依赖本模型，但不在本 Story 实现。

## Dev Agent Record

### Implementation Plan

新增 `engine/workflow.py`，用不可变迁移返回新 Pydantic 状态；通过显式迁移表拒绝跳阶段、失败状态继续推进和缺失前置条件。

### Completion Notes

- 实现 `WorkflowPhase`、`WorkflowStatus`、`GoalWorkflowState` 和 `WorkflowOrchestrator`。
- 新增 5 个意图级测试，专项测试全部通过；ruff/mypy 通过。

## File List

- `src/heagent/engine/workflow.py`
- `src/heagent/engine/__init__.py`
- `tests/test_engine_workflow.py`

## Change Log

- 2026-09-01: 完成 Story 43.1 状态模型与确定性迁移实现，状态置为 done。
