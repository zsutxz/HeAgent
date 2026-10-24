# Epic 51 Deferred Work

> 归档来源：`implementation-artifacts/deferred-work-archive.md` 的 A25、A26、A27、A28、A33（2026-10-07 收口批）与 A37、A38、A39（2026-10-23 登记并当日实施闭合）。以下条目均已闭合，保留摘要和证据入口；当前活动项无。

| ID | 主题 | 结论 | 主要证据 |
| --- | --- | --- | --- |
| A25 | checkpoint id 中已删除并行批次后缀 | 删除运行期分支；旧格式容忍读，新写入格式不冲突 | `tests/test_story_loop.py::test_legacy_parallel_checkpoint_id_recovers_and_rewrites_new_format` |
| A26 | `active_stories` 镜像字段 | 三个状态模型删除镜像字段，消费方现场派生，旧盘键容忍读 | `tests/test_story_scheduling_integration.py` |
| A27 | CLI 与 Runner 重复的事件隔离包装 | 收敛为 Runner 单一包装，CLI 只传扩展字段 | `tests/test_workflow_runner.py::test_emit_isolation_covers_hostile_duck_step_and_story` |
| A28 | `/goal verify` 手写台账审计生命周期 | `LedgerAudit` 下沉到 engine，覆盖续租、完成、失败和策略阻断 | `tests/test_engine_p0.py::test_audit_covers_the_policy_blocked_path`、`TestLedgerAudit` |
| A33 | `artifact_refs` 镜像与 dispatch 前导重复 | 镜像字段删除，dispatch 统一使用 `_goal_bound_workflow()` | Goal CLI/锁/决策回归测试 |
| A37 | 工作流状态 `reason` / `next_action` 无长度上限 | 新增截断函数 `_bounded_reason()`（上限 2000 字符，超出者尾部记 `...`），覆盖 9 个状态写点：异常吸收 / 批结算失败 / 回调终态 / `_stop` / 审批备注 / reject 备注 / `_persist` 两处 / `from_checkpoint` 读侧；语义为**截断不抛**，只限落盘与展示体积，不改控制流 | `tests/test_workflow_runner.py::test_oversized_failure_reason_is_bounded_in_state_and_checkpoint`、`::test_batch_failure_reason_is_bounded_and_records_the_event`；变异体 2/2 精确变红 |
| A38 | 工作流事件与 checkpoint 缺「驱动本次转换的事件类型」 | `WorkflowCheckpoint.last_event`（AD-2 追加可选字段，默认空串，旧 checkpoint 照常加载）+ `WorkflowRunnerState.last_event`；唯一写点 `_transition_fields(event)` 使 `status` 与事件同源（无半更新路径）；failed / paused / resumed / approved / rejected / amended 六个事件带 `transition_event`；`transition_reason` **不加**（与 `next_action` 同义，属镜像字段） | `tests/test_workflow_runner.py::test_every_transition_records_the_event_that_drove_it` 等 5 例 + `tests/test_architecture_contracts.py::test_transition_fields_helper_is_the_only_status_writer`；变异体 6/6 精确变红 |
| A39 | `KeyboardInterrupt` / `SystemExit` 与 `CancelledError` 的中断语义不一致 | `_CANCEL_EXCEPTIONS = (CancelledError, KeyboardInterrupt, SystemExit)`：三者同路落 CANCELLED→PENDING（可恢复，resume 即重跑）；`_absorb_step_exception()` 返回所用事件，story 状态判定与 `workflow_step_failed.transition_event` 同源（不再各判一次） | `tests/test_workflow_runner.py::test_keyboard_interrupt_is_treated_as_user_cancellation`、`::test_system_exit_is_treated_as_user_cancellation`；变异体精确变红 |

详细当前行为见 [`docs/frame.md`](../../../docs/frame.md) 和 [`docs/goal-workflow.md`](../../../docs/goal-workflow.md)；历史完整证据由提交记录和测试保留。
