---
title: "/goal next 推进声明式工作流检查点"
type: bugfix
created: "2026-09-03"
status: completed
baseline_commit: "9060e6cfa41d7aaee32d61c3032848da53bad1dc"
review_loop_iteration: 0
context:
  - "E:\\AI\\HeAgent\\AGENTS.md"
---

<frozen-after-approval reason="human-owned intent - do not modify unless human renegotiates">

## Intent

声明式工作流在某一步完成并设置 `checkpoint: true` 后，会进入 `waiting_user`。此前 `/goal resume` 只把状态改回 `pending`，不会执行下一步，用户还必须额外执行 `/goal next`。本修复让 `/goal resume` 在成功恢复并持久化后，立即执行一次下一步；同时保证最后一步即使声明检查点，也仍然以 `completed` 结束。

## Boundaries & Constraints

- 保留 `WorkflowRunner` 的单步执行、持久化和检查点语义。
- 只有存在后续步骤时，检查点才会进入 `waiting_user`。
- 恢复和下一步执行必须继续持有 `_goal_auto_lock`。
- `/goal next`、`run`、cron 不得绕过等待中的检查点。
- 失败、阻塞和持久化错误必须保持显性失败，不得自动跳过。

## I/O & Edge-Case Matrix

| 场景 | 预期行为 |
| --- | --- |
| 中间步骤完成并等待检查点 | `/goal resume` 恢复后只执行一次下一步，并保留前一步输出 |
| 等待检查点时执行 `/goal next` | 不执行子会话，提示先使用 `/goal resume` |
| 用户主动暂停 | `/goal resume` 只执行当前活动步骤一次 |
| 状态为 `pending` 或已完成 | `/goal resume` 不执行步骤，显示当前状态提示 |
| 最后一步带 `checkpoint: true` | 直接持久化为 `completed`，无需再次恢复 |

## Code Map

- `src/heagent/cli.py`：`/goal resume` 的恢复、持锁和单次推进边界。
- `src/heagent/engine/workflow_runner.py`：检查点仅适用于存在后续步骤的已完成步骤。
- `tests/test_goal_declarative_workflow.py`：CLI 恢复、锁、等待拒绝、阻塞恢复和最终完成回归。
- `tests/test_workflow_runner.py`：末步检查点直接完成及持久化回归。

## Tasks & Acceptance

- [x] `/goal resume` 成功恢复后调用一次 `_goal_declarative_advance()`。
- [x] 恢复和推进在同一个 `_goal_auto_lock` 范围内完成。
- [x] `/goal next` 在 `waiting_user` 状态下拒绝执行。
- [x] 最后一步的 `checkpoint: true` 不覆盖 `completed` 终态。
- [x] 补齐 CLI 与 Runner 回归测试。

## Design Notes

恢复辅助函数只负责状态转换和持久化，并返回是否发生了真正的恢复。命令层在成功恢复后复用既有的 `_goal_declarative_advance()`，避免复制步骤执行和持久化逻辑。Runner 通过判断当前步骤之后是否仍有步骤，区分中间检查点与最终完成。

## Verification

- `pytest --basetemp=.pytest_tmp_local/goal-resume-final tests/test_goal_declarative_workflow.py tests/test_workflow_runner.py -q`：15 passed。
- `ruff check src/heagent/cli.py src/heagent/engine/workflow_runner.py tests/test_goal_declarative_workflow.py tests/test_workflow_runner.py`：通过。
- 完整测试集另有一个既有的 Windows hook 超时测试失败：`tests/test_hooks.py::TestHookTimeout::test_timeout_blocks_and_returns_promptly`，与本修复无关。
