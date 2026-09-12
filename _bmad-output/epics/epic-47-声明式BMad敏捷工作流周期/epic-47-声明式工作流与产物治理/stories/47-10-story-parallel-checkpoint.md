---
id: 47-10
title: Story 批次 checkpoint 与恢复
status: done
parent_epic: E47
priority: P0
depends_on: 47-9
---

# 47-10 Story 批次 checkpoint 与恢复

## 用户故事

作为工作流执行者，我希望并行批次的每条 Story 都有独立状态和恢复记录，以便单条失败或进程中断时不重复已完成工作。

## 范围

- 批次启动时记录 active Stories。
- 每条 Story 独立记录 completed、failed、blocked 或 interrupted 状态。
- 恢复时 completed 不重跑；interrupted 回到 pending；失败不掩盖。
- 保留现有每 Story 产物目录与 Step 08 单次集成边界。

## 验收标准

- Given 批次内一条 Story 已完成，when 从 checkpoint 恢复，then 该 Story 不再次调用 callback。
- Given 批次内一条 Story 运行中断，when 恢复，then 只重新调度该 Story。
- Given 一条 Story 失败，when 读取 checkpoint，then 失败原因可见且独立 Story 结果不丢失。
- Given 所有 Story 完成，when Step 07 收口，then Step 08 仍只需执行一次。

## DoD

- 状态模型兼容旧 `active_story` checkpoint。
- checkpoint 写入保持原子、可恢复和幂等。
- 有成功、失败、中断恢复测试及全量相关测试证据。

## 代码地图

- `src/heagent/engine/workflow_runner.py`：批次状态推进与恢复。
- `src/heagent/engine/workflow.py`：checkpoint 模型/存储契约。
- `tests/test_story_loop.py`：checkpoint 和恢复测试。

## 验证

- `pytest tests/test_story_loop.py tests/test_workflow_runner.py -q`
