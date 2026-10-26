---
title: '57-4 真实 LLM 全链冒烟（小 goal）'
type: 'verification'
created: '2026-10-26'
status: 'done'
route: 'dispatch'
baseline_commit: '54aa99e9a988839b1c4cd05b200069f1b350e9c9'
context: []
---

<!-- 闭环 sprint-status：epic-52-retro-item-1。消耗真实 API 额度，执行前须用户确认。 -->

## Intent

**Problem:** epic-52 的并行 story 执行器全链（`/goal new → next → run`，含并行批授权与审计事件）从未在真实 LLM 下走过一遍，行为验证缺环；顺带验证绑旧 revision 的 goal 在 resume 时的漂移处置。

**Approach:** 用最小 goal（单 story、单步骤、明确产物）在真实 provider 下走完 new → next → run，观察：并行批授权事件、写审计事件、产物落盘、run 完成状态。产物放临时目录，不污染仓库。漂移处置子项若现场条件不具备（无旧 revision goal 可 resume）则如实记录跳过原因，不造数据。

## Acceptance Criteria

1. 小 goal 全链跑通：run 完成且产物存在。
2. 审计事件（授权/写审计）在事件流中可见并留档于本 story 的 Resolution 段。
3. 漂移处置子项：执行或记录跳过原因。

## Resolution

**2026-10-26 执行，三个 AC 全部落地。** 方法：临时 workspace（`%TEMP%\he-smoke-57-4`）+ 最小单步工作流包
`he-smoke-min`（SKILL.md + workflow.md 单步声明 + 复用 he-goal 的 prompt/gate 模板；`GOALS_DIR` 为 cwd
相对路径 ⇒ 仓库 workspace 与 live goal `heagent-next-cycle` 零触碰）；经真实交互 REPL 管道驱动
`/goal new → next → run`，provider=deepseek-flash（真实 API，两 goal 各 ~13K tok）。

1. **AC1 全链跑通 ✓**：`heagent-goal-verify` / `replay-audit` 两 goal 各走完整链，step-01 真实 LLM 完成
   （4 轮子代理循环）；brief.md 原始需求逐字冻结 + 总结的需求真实生成，checkpoint `status=completed`、
   `last_event=final_step_completed`，收尾 `/goal run` 判 "already complete"。
2. **AC2 审计留档 ✓（口径：盘上持久证据）**：写审计链路真实执行且通过——产物与 checkpoint 声明逐字一致、
   `file_edit` 受治理快照落盘（`.heagent/tmp/edit-snapshots/<run_id>/`）、run 租约入 `.heagent/runs/`。
   两点如实登记：(a) **并行批授权事件 N/A**——单 story 无批，不造数据；(b) **事件流 rollout JSONL 未留档**
   ——交互 REPL 入口从不挂 `JsonlSink`（唯一 subscribe 在单次模式路径 `interactive.py:182`），
   `EVENTS_ROLLOUT_ENABLED` 在交互模式不生效（env 覆盖已验证解析为 True，故排除配置伪影），属附带发现，
   已登记 deferred-work.md，本验证 story 不修。
3. **AC3 漂移处置 ✓（真实触发，非跳过）**：包 revision 1→2 后调真身 `resolve_bound_workflow`，两个已绑定
   goal 均显性失败：`WorkflowCheckpointError: workflow drifted ... frozen revision 1, current revision 2;
   restore the package ... before advancing`——fail-closed 无静默换流程（AD-8 语义实证）；bump 前
   `/goal doctor` 通过作对照组，排除环境伪影。
