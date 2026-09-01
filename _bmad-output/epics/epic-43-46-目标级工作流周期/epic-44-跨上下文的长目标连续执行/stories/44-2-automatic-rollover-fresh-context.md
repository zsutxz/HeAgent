---
status: review
baseline_commit: current
---

# Story 44.2: 自动 rollover 与新运行上下文

As a 长目标执行者,
I want 达到阈值时自动 checkpoint、清理当前 AgentLoop 并启动新 run,
So that 目标可以跨多个上下文连续推进而不重复工作。

## Acceptance Criteria

- [x] checkpoint 完成后才切换 segment 并创建新 run。
- [x] 工具进行中拒绝 rollover，不伪造工具结果。
- [x] 新 run ID 和 segment 编号可审计。

## Tasks/Subtasks

- [x] 实现 `RolloverResult` 和 `RolloverCoordinator`。
- [x] 固定 checkpoint -> reset -> fresh run 顺序。
- [x] 添加成功与工具进行中拒绝测试。

## Dev Agent Record

### Completion Notes

Rollover 协调协议不反向导入 agent，16 项专项测试通过。

## File List

- `src/heagent/engine/workflow.py`
- `src/heagent/engine/__init__.py`
- `tests/test_engine_workflow.py`

## Change Log

- 2026-09-01: 完成 Story 44.2，状态置为 review。
