# Deferred Work

## Deferred from: code review of story 51-2 (2026-09-29)

- 异常路径转换后不持久化：`run_step` 异常分支（`workflow_runner.py:439-455`）转换状态并 re-raise，不调用 `_persist`；进程重启后 `restore_runner` 从 checkpoint 复活为 RUNNING，内存中的 FAILED/PENDING 不落盘。修复涉及「异常路径的磁盘语义」设计选择，建议并入 Story 51-3 结构化执行证据模型一并处理。
- KeyboardInterrupt / SystemExit 语义不对称：串行异常分支只特判 `CancelledError`，`KeyboardInterrupt` 落 `EXECUTOR_FAILED → FAILED`（空 reason、可 resume），而 CLI 层把 KeyboardInterrupt 与 CancelledError 同视为用户中断。
- except 内 `transition()` 理论上可抛 `WorkflowTransitionError` 掩盖原异常（若回调未来能改动 runner 状态使其脱离 RUNNING）；已核实当前生产回调链拿不到 runner 引用，不可达，仅作新代码形态的脆弱点记录。
- COMPLETED 且 phase 未走完的 runner（`from_checkpoint` 恢复的 multi-phase 目标）执行 pause 会落入 `transition(COMPLETED, USER_PAUSE)` 非法转换异常路径，报错文案为原始枚举值。
- `reason: str(exc)` 无长度上限直通持久化字段（`next_action` / `blocked_reason`），frame.md 已有 16384 截断纪律仅覆盖 HTTP 事件文本。
- `workflow_step_failed` 观测事件不携带驱动状态转换的事件类型（CANCELLED vs EXECUTOR_FAILED）；`last_event` / `transition_reason` checkpoint 字段按计划（docs/goal-optimization-plan.md §deferred）本就未实现。

## Deferred from: code review of story 51-4 (2026-09-29)

- source_spec: `_bmad-output/epics/epic-51-goal-workflow优化周期/stories/51-4-quality-gates-verify.md`
  summary: workflow/revision 冻结绑定在 CLI 求值路径未接线（verify_step 的 revision 参数无调用方传入）
  evidence: **已于 Story 51-6 接线**（2026-09-30）：`cli/goal.py` 的 `_goal_verify_report` 读取 goal
  冻结绑定的 revision 传入 `verify_step(revision=...)`，受控重跑写下的证据带同一 revision；接线判据见
  `tests/test_goal_workflow_selection.py::test_frozen_revision_flows_into_verify_step`。
- source_spec: `_bmad-output/epics/epic-51-goal-workflow优化周期/stories/51-4-quality-gates-verify.md`
  summary: 受治理重跑在事件总线与 ledger 上零痕迹（executor.execute 未传 emit、不写 ledger）
  evidence: 与 agent 循环内工具调用不同，验证重跑无可审计事件；先以 docstring 显性声明省略，接线随 51-8 安全并行与收口
- source_spec: `_bmad-output/epics/epic-51-goal-workflow优化周期/stories/51-4-quality-gates-verify.md`
  summary: 声明验证命令在完成门与受控重跑中重复执行（假设幂等）
  evidence: 步骤执行期证据自动记录未接线（51-3/51-8 领域）；接线后完成门可直接消费执行期证据，消解重复执行

## Deferred from: three-layer review merge of story 51-6 (2026-09-30)

- source_spec: `_bmad-output/epics/epic-51-goal-workflow优化周期/stories/51-6-workflow-templates-freeze.md`
  summary: 半键绑定（有 workflow 无 workflow_revision）按声明解析、revision 空串不比对漂移——手改文档形态下冻结保证的显式兼容决定
  evidence: `src/heagent/goal/application.py` 的 `read_workflow_binding` docstring +
  `tests/test_goal_workflow_selection.py::test_read_workflow_binding_returns_frozen_values`（正向半键）与
  `::test_read_workflow_binding_rejects_a_revision_without_a_workflow_key`（反向半键显性拒绝，审查 L3 已收口）

## Deferred from: story 51-7 delivery boundary (2026-09-30)

- source_spec: `_bmad-output/epics/epic-51-goal-workflow优化周期/stories/51-7-controlled-goalscript-runtime.md`
  summary: **已闭合**（2026-09-30 同日第二轮）：原先「`step` / `parallel` 只能声明自己、无法选择
  后续声明步骤」的缺口按 A1 + A2 交付——A1 = `WorkflowRunner.run_declared_step(name)`（跑指名的
  已声明步骤；已完成幂等跳过、只允许向前、挂起/失败/已完成不改状态）；A2 = `advance` 每轮取计划
  队首提交，计划存 `WorkflowRunnerState.requested_steps` 并随 `WorkflowCheckpoint.requested_steps`
  **持久化**（重启后按同一选择恢复，不退回声明顺序）；累计计划超过声明步骤数由 Runner 落 `BLOCKED`。
  evidence: `docs/frame.md` §4.13.1 的 A1 / A2 两段 + `tests/test_goal_script_step.py`（9 例，含
  `test_script_declares_a_follow_up_step_that_runs` 刻意让目标**不是**下一步）+
  `tests/test_goal_script_recovery.py`（2 例，计划落盘 + 重启恢复）+ `.heagent/tmp/neg51_7.py`
  （21/21 变异体精确变红）。**残留（设计边界，非缺口）**：脚本不能**重跑**已完成的声明步骤
  （幂等跳过），故「按状态反复重试某一个声明步骤」不在此设计内——被跳过的声明步骤保持未执行，
  `completed_steps` 出现缺口，由 `/goal status` 照实投影。
  已交付面：声明词汇（`executor_mode` / `script_resource`）、包内资源完整性（manifest.json / manifest.lock）、
  `workflow_revision` 纳入脚本内容、加载期 AST 形态校验、受控 facade 七操作、请求数 / 深度 / 协作式超时限额、
  CLI 侧**两阶段提交**（脚本只声明、宿主按序提交：`checkpoint` / `decision` 落本步证据、
  `validate` 跑注册门）、脚本产物与 subagent 步骤走**同一条结构化完成门**（不得绕过 Gate）、
  脚本异常收敛为有界 `FAILED`（不打崩 run）。
  evidence: `docs/frame.md` §4.13.1 + `tests/test_goal_script_declarations.py` /
  `tests/test_goal_script_runtime.py` / `tests/test_goal_script_step.py` /
  `tests/test_goal_script_recovery.py`（共 30 例）+ `.heagent/tmp/neg51_7.py`（21/21 变异体精确变红）。
- source_spec: 同上
  summary: 协作式超时对同步 CPU 密集脚本无效——`asyncio.wait_for` 只能在脚本让出事件循环时取消；
  超大 `range` 推导等同步循环可绕过 `timeout_seconds`。已如实写入 `ScriptRuntime` docstring 与
  `docs/frame.md` §4.13.1，**不**声称它是边界。
  evidence: `src/heagent/goal/script_runtime.py` 的类 docstring「限额的真实强度」段。
  闭合条件：OS 级隔离 worker（Phase B，不在 Epic 51 强制范围）。
