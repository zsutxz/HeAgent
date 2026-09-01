---
status: review
baseline_commit: current
---

# Story 43.2: 阶段路由、前置条件与人工闸门

As a 目标执行者,
I want 系统依据当前产物和阶段选择下一个 `he-*` 技能，并在需要确认、缺少产物或发生阻塞时停下,
So that 目标按 BMad 顺序推进且每个决策点可由人检查。

## Acceptance Criteria

- [x] 编排器通过 `SkillResolver` 计算唯一候选，不允许技能自行跳阶段。
- [x] 缺少 PRD/Spec、架构或 ready Story 时进入 `blocked`，错误包含缺失产物和下一动作。
- [x] step 返回等待信号时进入 `waiting_user`，保留当前 step、提示和恢复位置。
- [x] `bmad-*` 映射到唯一 `he-*` canonical ID，显式技能名优先于自动匹配。

## Tasks/Subtasks

- [x] 定义阶段候选与产物前置条件模型。
- [x] 实现编排器与 `SkillResolver` 的确定性路由接口。
- [x] 实现 blocked/waiting_user 闸门结果及错误诊断。
- [x] 添加合法候选、缺失产物、别名冲突和人工等待测试。
- [x] 运行专项测试、ruff 和 mypy。

## Dev Notes

- 依赖 Story 43.1 的 `GoalWorkflowState` 与 `WorkflowOrchestrator`。
- 不导入 `agent`；工作流规则由结构化配置/模型承载，避免散落硬编码。
- `SkillResolver` 来自 Epic 42，显式技能 ID 必须优先于自动匹配。

## Dev Agent Record

### Implementation Plan

在 `WorkflowOrchestrator` 中加入显式阶段优先级、产物存在性检查和 `SkillResolver` 路由；多出口阶段默认路径固定，修复回退需显式指定。

### Completion Notes

- 新增 `WorkflowRoute` 结构化路由结果。
- `review` 默认进入 `retrospective`，避免按集合排序回到 implementation。
- 专项测试 10 项通过，ruff/mypy 通过。

## File List

- `src/heagent/engine/workflow.py`
- `src/heagent/engine/__init__.py`
- `tests/test_engine_workflow.py`

## Change Log

- 2026-09-01: 创建 Story 43.2，状态 ready-for-dev。
- 2026-09-01: 完成 Story 43.2 路由与闸门实现，状态置为 review。
