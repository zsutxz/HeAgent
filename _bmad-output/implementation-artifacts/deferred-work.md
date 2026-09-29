# Deferred Work

## Deferred from: code review of story 51-2 (2026-09-29)

- 异常路径转换后不持久化：`run_step` 异常分支（`workflow_runner.py:439-455`）转换状态并 re-raise，不调用 `_persist`；进程重启后 `restore_runner` 从 checkpoint 复活为 RUNNING，内存中的 FAILED/PENDING 不落盘。修复涉及「异常路径的磁盘语义」设计选择，建议并入 Story 51-3 结构化执行证据模型一并处理。
- KeyboardInterrupt / SystemExit 语义不对称：串行异常分支只特判 `CancelledError`，`KeyboardInterrupt` 落 `EXECUTOR_FAILED → FAILED`（空 reason、可 resume），而 CLI 层把 KeyboardInterrupt 与 CancelledError 同视为用户中断。
- except 内 `transition()` 理论上可抛 `WorkflowTransitionError` 掩盖原异常（若回调未来能改动 runner 状态使其脱离 RUNNING）；已核实当前生产回调链拿不到 runner 引用，不可达，仅作新代码形态的脆弱点记录。
- COMPLETED 且 phase 未走完的 runner（`from_checkpoint` 恢复的 multi-phase 目标）执行 pause 会落入 `transition(COMPLETED, USER_PAUSE)` 非法转换异常路径，报错文案为原始枚举值。
- `reason: str(exc)` 无长度上限直通持久化字段（`next_action` / `blocked_reason`），frame.md 已有 16384 截断纪律仅覆盖 HTTP 事件文本。
- `workflow_step_failed` 观测事件不携带驱动状态转换的事件类型（CANCELLED vs EXECUTOR_FAILED）；`last_event` / `transition_reason` checkpoint 字段按计划（docs/goal-optimization-plan.md §deferred）本就未实现。
