# Deferred Work Review Notes

> 历史 code review 摘要（2026-09-29 至 2026-09-30）。本文件不是当前活动遗留项总账；活动状态以 [`deferred-work-archive.md`](deferred-work-archive.md) 为准。这里仅保留仍有维护价值的观察和已闭合事项索引。

## 仍需维护的观察

来源：Story 51-2 code review。

- `WorkflowRunner.run_step()` 的执行异常分支转换状态后直接重新抛出，未必持久化新的 `FAILED`/`PENDING` 状态；需明确异常路径的 checkpoint 语义，并补充进程重启判据。
- `KeyboardInterrupt` / `SystemExit` 与 `CancelledError` 的中断语义不完全一致；需决定哪些情况可恢复、哪些情况应视为用户取消。
- 异常处理中的 `transition()` 理论上可能覆盖原始异常；当前生产回调无法触达该路径，保留为未来改动的脆弱点。
- 已完成但仍有后续 phase 的 runner 执行 `pause` 会触发非法转换；需明确多 phase 状态下 `COMPLETED` 的含义和错误文案。
- `reason: str(exc)` 可无上限写入 `next_action` / `blocked_reason`；应补充持久化字段长度上限。
- `workflow_step_failed` 事件未记录驱动转换的事件类型，checkpoint 也没有 `last_event` / `transition_reason` 字段；如需审计转换原因，应先更新事件与存储契约。

这些观察尚未登记为活动台账条目；需要实施时，应先在 `deferred-work-archive.md` 登记编号、触发条件、裁决和验收证据。

## 已闭合事项索引

| 来源 | 结论 | 证据 |
| --- | --- | --- |
| Story 51-4 | workflow/revision 冻结绑定已接入 `/goal verify`；执行期证据复用完成门，受治理重跑经过审计链 | `tests/test_goal_workflow_selection.py::test_frozen_revision_flows_into_verify_step`；Story 51-6/51-8 |
| Story 51-6 | workflow 与 revision 半键绑定规则已明确并有正反向测试 | `src/heagent/goal/application.py::read_workflow_binding`；`tests/test_goal_workflow_selection.py` |
| Story 51-7 | GoalScript 后续步骤声明、持久化恢复、受控 facade 和限额已完成；同步 CPU 密集脚本的超时限制仍依赖 OS 隔离 worker | `docs/frame.md` §4.13.1；`tests/test_goal_script_*.py`；`src/heagent/goal/script_runtime.py` |

当前实现状态以源码、测试、`docs/frame.md` 和 `sprint-status.yaml` 为准；本文件不重复复制完整验收报告。
