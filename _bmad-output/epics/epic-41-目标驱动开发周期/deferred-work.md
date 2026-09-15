# Epic 41 目标驱动开发周期遗留项台账（deferred-work）

> **归并来源**：本目录原英文台账（2026-08-31 归档，commit `3c4faeb` `docs(bmad): archive epic 41 and 42 planning artifacts`），2026-09-15 按统一格式归并。
> **归档规则**：按条目**归属的 epic** 归档；「闭合者」注明实际完成它的 spec / 测试。
> **只登记已闭合项**——原始长文历史不再保留，结论全部指向代码与测试。
> **活动（未闭合）遗留项**：2 条（GUI `/goal` 收口、goal 状态跨进程锁）已移至
> [`implementation-artifacts/deferred-work.md`](../../implementation-artifacts/deferred-work.md)（工作流 append-only 入口）。
> 立场不变：`/goal` 的并发串行化目前只有**单进程 `asyncio.Lock`**，**不是跨进程安全边界**。

## 状态总览

| ID | 归属 | 条目 | 状态 | 闭合者 |
|----|------|------|------|--------|
| E41-D1 | Epic 41 · `/goal` 单步技能 | goal 会话迭代预算未接线 | 已修复（2026-09-15 复核） | `spec-41-1-goal-skill-single-step` |
| E41-D2 | Epic 41 · `/goal` 单步技能 | TUI `/goal` 路由（输入补全 + 交给 goal runner） | 已修复（GUI 交互测试另记活动台账） | `spec-41-1-goal-skill-single-step` |
| E41-D3 | Epic 41 · `/goal` 单步技能 | 交互式 REPL 斜杠命令异常围栏 | 已修复 | `spec-41-1-goal-skill-single-step` |
| E41-D4 | Epic 41 · run metadata | `RoleSpec.metadata` 生命周期 | 已裁定（不并入 `RunContext.metadata`） | `spec-41-2-run-loop-run-metadata` |

---

## E41-D1 goal 会话迭代预算未接线

- **来源**：`spec-41-1-goal-skill-single-step` 评审（2026-08-29）。
- **问题**：`/goal` 会话的迭代预算未显式接线，可能与主 `AgentLoop` / dreaming 预算混用。
- **结论**：**已修复**。预算链收敛为「step 显式声明 > 全局 `Settings.goal_max_iterations`（`src/heagent/config.py:122`，默认 `20`，`ge=1`）」，且与主循环、`Settings.dream_max_iterations`、`Settings.subagent_max_iterations` 各自独立；`cli_goal._goal_execute_step` 在 step 未声明（或声明 `0`）时回退全局值并传给 `SubAgent`（`src/heagent/cli_goal.py:1220`）。
- **证据**：`tests/test_goal_declarative_workflow.py::test_step_iteration_budget_overrides_the_global_default`（`tests/test_goal_declarative_workflow.py:709`，钉住「声明 40 生效、声明 0 继承」）；`tests/test_subagent_budget.py`（嵌套链「显式参数 > 角色声明 > `Settings.subagent_max_iterations`」）。

## E41-D2 TUI `/goal` 路由

- **来源**：`spec-41-1-goal-skill-single-step` 评审（2026-08-29）。
- **问题**：TUI 里输入 `/goal ...` 可能被当作普通提示词交给 LLM。
- **结论**：**已修复**（代码）。`InputArea` 的补全列表含 `/goal`（`src/heagent/gui/widgets/input_area.py:23`）；`ChatScreen._goal_cmd` 把命令交给共享 CLI 实现 `cli_goal._goal_runner(..., cron_store=app.job_store)`（`src/heagent/gui/screens/chat.py:211,216,230`），不再落进 `AgentBridge.submit()`。
- **未闭合部分**：GUI 交互测试（证明 `/goal next`、`/goal status` 走 goal runner 且不落 `AgentBridge.submit()`）已移至活动台账。

## E41-D3 交互式 REPL 斜杠命令异常围栏

- **问题**：交互式 REPL 分发斜杠命令时若 handler 抛普通异常，曾可能打断 REPL 或静默吞掉失败。
- **结论**：**已修复**。`_dispatch_slash_interactive`（`src/heagent/cli.py:996`）把 `_handle_slash` 包进 `try`：`asyncio.CancelledError` 重新抛出（`:999`，保持关停干净）；`KeyboardInterrupt`（`:1001`）与普通 `Exception`（`:1004`）回显原始错误到 stderr 并返回 `True`——REPL 继续且不静默。
- **证据**：`tests/test_cli.py::test_interactive_slash_runtime_error_is_visible_and_handled`（`tests/test_cli.py:128`，断言 `RuntimeError("slash boom")` 文本出现在 stderr 且分发返回 `True`）。

## E41-D4 `RoleSpec.metadata` 生命周期

- **问题**：角色声明的 metadata 是否会不经筛选取代 caller metadata，或污染框架自有（policy / window-reset）键。
- **裁定**：**已裁定 = 按现状即正确 + 明确不做「默认并入 `RunContext.metadata`」**。`SubAgent` 先并入 `role.metadata`、再并入 caller metadata（**caller 胜**），并按既有 reserved-key 策略过滤框架自有键；随后写入子 run 快照 metadata（`kind="subagent"`、`role=<名>`）。**不得**默认并入 `RunContext.metadata`——policy 与 window-reset 键归框架所有，不接受用户覆盖。
- **证据**：`src/heagent/agent/sub.py:203`–`:210`；`tests/test_sub_agent.py::test_role_metadata_is_observable_and_caller_metadata_wins`（`tests/test_sub_agent.py:66`，断言 caller 的 `scope` 胜出、伪造的 `kind: spoofed` 被覆盖为 `subagent`）。

## 参考

- `spec-41-1-goal-skill-single-step.md`
- `spec-41-2-run-loop-run-metadata.md`
- `src/heagent/config.py`
- `src/heagent/cli.py`
- `src/heagent/gui/screens/chat.py`
