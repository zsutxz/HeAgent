---
status: review
baseline_commit: current
---

# Story 44.1: 分段 Token 预算与确定性阈值

As a 长目标执行者,
I want 系统分别记录当前 segment、Goal 累计和上下文窗口 Token，并在预计超阈值前发出 rollover 决策,
So that 长目标不会因窗口耗尽而丢失状态或超出预算。

## Acceptance Criteria

- [x] provider 调用前按配置阈值确定继续或 rollover，不调用 LLM 代替判断。
- [x] rollover 后 segment Token 归零，累计 Token 保留，上下文窗口计数独立记录。
- [x] 缺失、负数或不一致计数显式失败并保留状态。

## Tasks/Subtasks

- [x] 定义 `TokenBudgetState` 和 `TokenBudgetError`。
- [x] 实现阈值判断、调用计数和 segment rollover。
- [x] 添加边界计数、累计保留和非法输入测试。
- [x] 运行专项测试、ruff 和 mypy。

## Dev Notes

- 自动创建新 AgentLoop、恢复信封和上下文摘要属于 44.2/44.3。
- `segment_tokens`、`cumulative_tokens`、`context_window_usage` 三类计数不可混用。

## Dev Agent Record

### Implementation Plan

在 `engine/workflow.py` 中实现 Pydantic 预算状态和确定性管理器，阈值为 segment_limit * rollover_threshold，所有计数严格校验。

### Completion Notes

- 新增 `TokenBudgetManager`、`TokenBudgetState`、`TokenBudgetError`。
- 14 项工作流专项测试通过，ruff/mypy 通过。

## File List

- `src/heagent/engine/workflow.py`
- `src/heagent/engine/__init__.py`
- `tests/test_engine_workflow.py`

## Change Log

- 2026-09-01: 完成 Story 44.1 分段预算实现，状态置为 review。
