---
id: 51-2
title: 显式 Workflow 事件与转换表
status: in-progress
parent_epic: E51
priority: P0
depends_on: [51-1]
blocks: [51-3, 51-5]
created: '2026-09-29'
---

# Story 51-2：显式 Workflow 事件与转换表

## 用户故事

作为维护者，我希望所有状态变化都经单一事件转换表完成，以便恢复、审批、失败和并行路径不会出现互相矛盾的状态语义。

## 现有工作区基线

当前未提交改动已新增 `engine/workflow_events.py`、`engine/workflow_transition.py`、`tests/test_workflow_transition.py`，并部分接入 `workflow_runner.py`。必须对抗式审查现有接线，尤其检查异常路径、Story batch、pause/resume 与直接赋值残留。

## 验收标准

- 合法状态转换仅由单一 `_TRANSITIONS` 表定义。
- Runner、pause/resume、审批路径不得直接把业务状态赋成目标值。
- 非法转换抛 `WorkflowTransitionError`，原 checkpoint 状态不被覆盖。
- 回调异常、取消、Gate 失败、输入缺失、最终完成均有明确事件。
- 现有 checkpoint JSON 不迁移即可恢复。
- 每次转换产生可观测事件；观测失败不改变状态结果。
- 架构判据能发现新增的绕过转换表的直接状态写入。

## 任务

- [ ] 审查并修正当前 `workflow_runner.py` 的部分接线。
- [ ] 补 `CANCELLED` 和异常回滚语义，不用临时直接写 `PENDING` 掩盖失败。
- [ ] 统一普通步骤、Story batch、resume、pause 与 stop 路径。
- [ ] 增加合法矩阵、非法矩阵、旧 checkpoint 恢复和观测 fail-soft 测试。
- [ ] 负向验证：删除非法转换拒绝、绕过 transition、把 BLOCKED 改 COMPLETED 时精确变红。

## 验证命令（规划，执行时亲跑）

```bash
pytest tests/test_workflow_transition.py tests/test_engine_workflow.py tests/test_goal_application.py -q
pytest tests/test_architecture_contracts.py -q
ruff check src tests
ruff format --check src tests
mypy src
mypy src --platform linux
```
