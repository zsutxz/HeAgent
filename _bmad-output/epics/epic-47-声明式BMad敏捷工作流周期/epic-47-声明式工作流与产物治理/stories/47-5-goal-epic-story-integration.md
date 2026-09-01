---
title: 'Integrate Goal CLI with Epic Story Sprint workflow'
type: 'feature'
status: 'done'
epic: 47
story: 5
baseline_commit: '112c016'
context:
  - 'E:/AI/HeAgent/AGENTS.md'
  - 'E:/AI/HeAgent/src/heagent/cli.py'
  - 'E:/AI/HeAgent/src/heagent/engine/workflow_runner.py'
  - 'E:/AI/HeAgent/src/heagent/engine/artifacts.py'
  - 'E:/AI/HeAgent/tests/test_goal_command.py'
---

# Story 47-5: `/goal` 接入 Goal/Epic/Story/Sprint

## Acceptance Criteria

- [x] `/goal new|next|run|status|pause|resume|audit` 支持 declarative workflow。
- [x] 新模式按 Epic、Sprint、Story 和 gate 推进，旧 GOAL.md-only 模式保持兼容。
- [x] 并发、Ctrl+C、cron 和恢复不会重复完成 Story。

## Dependencies

47-4

## Tasks

- [x] `src/heagent/cli.py` -- 在存在声明式 workflow 配置时路由 Goal 命令到 WorkflowRunner；无配置时完整保留 legacy 路径。
- [x] `src/heagent/engine/workflow_runner.py` -- 如必要，补充 goal metadata、恢复和审计边界，不复制 CLI 业务判断。
- [x] `tests/test_goal_declarative_workflow.py` -- 覆盖 new/next/run/status/pause/resume/audit、gate、重复恢复和 legacy 回归。

## Dev Agent Record

### Completion Notes

- `workflow.md` 存在时作为显式 feature flag，`/goal` 使用声明式 Runner；缺失时完整回退既有 GOAL.md Story 路径。
- 声明式路径支持 new/next/run/status/pause/resume/audit/auto，保存 Goal metadata、runner checkpoint 与 completed-step 历史。
- pause/resume 和同一步不同状态的 checkpoint 使用不同 ID，恢复不会重跑已完成 step。

### Verification Evidence

- `pytest tests/test_goal_declarative_workflow.py tests/test_goal_command.py tests/test_workflow_runner.py -q --basetemp E:/AI/HeAgent/workflow_test_tmp47_5` -- 61 passed。
- `ruff check src tests` -- passed。
- `mypy src` -- blocked by installed numpy stub requiring Python 3.12 (`numpy/__init__.pyi:737`); prior Story 47-4 type check passed before this environment-only dependency issue.
