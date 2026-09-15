# Deferred Work — 活动台账（未闭合项）

> **本文件只登记活动（未闭合）遗留项**，是工作流的 append-only 入口（bmad-build defer 分诊写入）。
> 条目**闭合后**写 `Resolution`，随后按**归属 epic**归档到 `_bmad-output/epics/<周期>/deferred-work.md`，并可从此处移除（历史长文不保留）。
> 已闭合项归档索引见 `_bmad-output/consolidated-overview.md` 11.1；重定向见 `_bmad-output/patches/_meta/deferred-work.md`。
> 格式：`source_spec` / `summary`（含触发条件、严重度、冻结边界）/ `evidence`。

- source_spec: `_bmad-output/epics/epic-43-46-目标级工作流周期/epic-46-技能资源并发替换安全评估/stories/46-1-skill-resource-toctou-assessment.md`
  summary: 后续评估 descriptor-relative/目录句柄、可信导入 snapshot 或 OS sandbox 加固。
  evidence: Story 46.2 已以 `O_NOFOLLOW` 加固支持平台上的最终路径组件，并保留不支持该标志时的兼容回退；中间目录替换、可信导入 snapshot 与 OS sandbox 仍未交付，现有路径围栏保留竞态残余风险。

- source_spec: `src/heagent/config.py`（`goal_max_iterations` 默认 20）
  summary: 已支持 workflow step 声明独立 `max_iterations`，但 bmad-build 的 Step 07 尚未配置该值，实际仍回退到全局 20；原子大 Story 仍可能撞上限后整批失败。
  evidence: `memory.skill_packages.WorkflowStepResource.max_iterations` 接受 1–1000 的 step 级预算，`cli_goal._goal_execute_step()` 将声明值传给 SubAgent；`.claude`、`.agents` 与 `.heagent` 的 bmad-build 工作流均未声明 `max_iterations`，因此仍使用 `Settings.goal_max_iterations`。`tests/test_goal_declarative_workflow.py::test_step_iteration_budget_overrides_the_global_default` 锁定覆盖行为。
