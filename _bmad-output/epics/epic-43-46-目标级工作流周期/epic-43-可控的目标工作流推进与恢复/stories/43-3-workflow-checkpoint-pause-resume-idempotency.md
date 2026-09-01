---
status: review
baseline_commit: current
---

# Story 43.3: Workflow checkpoint、暂停恢复与幂等提交

As a 目标执行者,
I want 工作流状态和每次运行的 checkpoint 原子保存，并能从最后一个未完成单元恢复,
So that 进程崩溃、Ctrl+C 或重复恢复不会重复完成 Story 或工具事务。

## Acceptance Criteria

- [x] 工作单元完成且工具事务结束后可原子写入结构化 checkpoint。
- [x] 工具执行中禁止 checkpoint，不伪造工具成功。
- [x] 相同 run/step 重复提交幂等，内容冲突显式失败。
- [x] 损坏或不安全 checkpoint 路径显式失败。

## Tasks/Subtasks

- [x] 定义 `WorkflowCheckpoint` 和 `WorkflowCheckpointError`。
- [x] 实现 `WorkflowCheckpointStore` 原子写入、读取和幂等冲突检测。
- [x] 添加工具进行中、重复提交、冲突和路径安全测试。
- [x] 运行专项测试、ruff 和 mypy。

## Dev Notes

- 复用 `engine.persist.atomic_write_text` 和现有 Pydantic 模型约定。
- 跨进程锁与 workflow.json 聚合由后续集成 Story 处理；本 Story 先固定 checkpoint 契约。
- 不把 checkpoint 当作进行中工具的完成证据。

## Dev Agent Record

### Implementation Plan

实现文件型 `WorkflowCheckpointStore`，使用 asyncio 锁保护进程内提交，原子写入 JSON，并以 checkpoint ID + 完整内容实现重复提交幂等和冲突拒绝。

### Completion Notes

- 新增 `WorkflowCheckpoint`、`WorkflowCheckpointError`、`WorkflowCheckpointStore`。
- 覆盖原子保存、读取、工具进行中拒绝、冲突和路径安全；专项测试 12 项通过，ruff/mypy 通过。

## File List

- `src/heagent/engine/workflow.py`
- `src/heagent/engine/__init__.py`
- `tests/test_engine_workflow.py`

## Change Log

- 2026-09-01: 完成 Story 43.3 checkpoint 存储实现，状态置为 review。
