# Epic 41 目标驱动开发周期遗留项台账（deferred-work）

> **归并来源**：本目录原英文台账（2026-08-31 归档，commit `3c4faeb` `docs(bmad): archive epic 41 and 42 planning artifacts`），2026-09-15 按统一格式归并。
> **归档规则**：按条目**归属的 epic** 归档；「闭合者」注明实际完成它的 spec / 测试。
> **只登记已闭合项**——原始长文历史不再保留，结论全部指向代码与测试。
> **活动（未闭合）遗留项**：此前 1 条（GUI `/goal` 收口）移至
> [`implementation-artifacts/deferred-work-archive.md`](../../implementation-artifacts/deferred-work-archive.md)（工作流 append-only 入口），
> 已于 2026-09-17 闭合归档回本台账（E41-D7），本周期在活动台账暂无未闭合项。
> 立场不变：goal 跨进程锁（E41-D5）是**并发正确性**互斥，**不是 OS 级安全边界**（须 OS 级沙箱兜底的立场不变）。

## 状态总览

| ID | 归属 | 条目 | 状态 | 闭合者 |
|----|------|------|------|--------|
| E41-D1 | Epic 41 · `/goal` 单步技能 | goal 会话迭代预算未接线 | 已修复（2026-09-15 复核） | `spec-41-1-goal-skill-single-step` |
| E41-D2 | Epic 41 · `/goal` 单步技能 | TUI `/goal` 路由（输入补全 + 交给 goal runner） | 已修复（GUI 交互测试另记活动台账） | `spec-41-1-goal-skill-single-step` |
| E41-D3 | Epic 41 · `/goal` 单步技能 | 交互式 REPL 斜杠命令异常围栏 | 已修复 | `spec-41-1-goal-skill-single-step` |
| E41-D4 | Epic 41 · run metadata | `RoleSpec.metadata` 生命周期 | 已裁定（不并入 `RunContext.metadata`） | `spec-41-2-run-loop-run-metadata` |
| E41-D5 | Epic 41 · goal 状态并发 | goal 状态无跨进程锁 | 已修复（2026-09-17） | 优化批次 4（`persist.file_lock` + `_goal_mutex`） |
| E41-D6 | Epic 41 · 声明式工作流 | bmad-build Step 07 迭代预算未声明 | 已闭合（2026-09-17） | 优化批次 1（`max_iterations: 100`） |
| E41-D7 | Epic 41 · GUI `/goal` | 输出转发 / 取消入口 / CronScheduler / 交互测试 | 已收口（2026-09-17） | 优化批次 1（commit `44ab001`） |

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

## E41-D5 goal 状态无跨进程锁

- **来源**：活动台账（`spec-41-1-goal-skill-single-step` 评审 defer 分诊），2026-09-17 优化批次 4 闭合。
- **问题**：`/goal` 的串行化只有进程内 `asyncio.Lock`，同一 workspace 的第二个 CLI 进程（或 cron 与手动命令并发）可同时推进同一 goal，写 `GOAL.md` / `current` 指针时互相覆盖丢进度。
- **结论**：**已修复**。`persist.file_lock()` 新增公开跨进程锁 CM（复用既有 `_acquire_lock/_release_lock`，POSIX `fcntl.flock` / Windows `msvcrt.locking`，获取/释放经 `asyncio.to_thread` 卸载）；`cli_goal._goal_mutex()` 组合「进程内 `_goal_auto_lock`（快速路径，名字保留以兼容既有断言）+ `.heagent/goal.lock` 文件锁（5s 超时显性失败）」，接入 `/goal` 全部 7 个变更入口（new×2 / next / run / resume / reset 补锁 / cron 推进）；手动方超时收到「另一进程正在推进同一 goal」提示、cron 跳过本 tick 下次自动重试。锁文件刻意残留不删（unlink 竞态，同 `atomic_write_text` 论证）。
- **证据**：`src/heagent/persist.py`（`file_lock`）、`src/heagent/cli_goal.py`（`_GOAL_LOCK_PATH`/`_goal_mutex` 六处替换 + reset 补锁）；`tests/test_goal_cross_process_lock.py`（持锁显性失败且步骤不执行、无争用行为不变、锁文件残留无害）；`tests/test_goal_declarative_workflow.py::test_declarative_resume_advances_once_under_goal_lock`（快速路径断言不红）。

## 参考

- `spec-41-1-goal-skill-single-step.md`
- `spec-41-2-run-loop-run-metadata.md`
- `src/heagent/config.py`
- `src/heagent/cli.py`
- `src/heagent/gui/screens/chat.py`

## E41-D6 bmad-build Step 07 迭代预算未声明

- **来源**：活动台账（source_spec `src/heagent/config.py` 的 `goal_max_iterations` 默认 20）。
- **问题**：workflow step 已支持声明独立 `max_iterations`（1–1000），但 bmad-build 的 Step 07 未配置，回退全局 20；原子大 Story 撞上限后整批失败。
- **结论**：**已闭合**（2026-09-17，优化批次 1）。`.heagent/workflows/workflow.md` Step 07 元数据块声明 `max_iterations: 100`（`/goal` 实际只加载该文件，`cli_goal.py:90`；`.claude`/`.agents` 的技能副本属另一管线不消费该字段），正文「本步骤预算」表述同步更新。
- **证据**：真实文件解析验证 `step.max_iterations == 100`；覆盖机制由既有 `test_step_iteration_budget_overrides_the_global_default` 锁定。

## E41-D7 GUI `/goal` 收口（输出转发 / 取消入口 / CronScheduler / 交互测试）

- **来源**：活动台账（合并原 Epic 41 台账 3 条同源 bullet；spec-41-1）；2026-09-17 优化批次 1 闭合（commit `44ab001`）。
- **问题**：GUI 里跑 `/goal` 时 `click.echo` 进度不进 `RichLog`（只见一行 completed）、无取消入口、GUI 不持有 `CronScheduler`（cron 自动推进不生效）、缺「/goal 不落 bridge.submit」的交互测试。
- **结论**：**已收口**（冻结边界内：不改 CLI runner 语义、产物路径与 `click.echo` 文案）。① stderr→RichLog：`_StderrToLogForwarder`（`io.TextIOBase`，按行缓冲 + rich escape）经 `contextlib.redirect_stderr` 包裹 `_goal_runner`——`click.echo(err=True)` 调用时动态查 `sys.stderr`，重定向有效，cli_goal 零改动；② 取消：ChatScreen `Esc` 绑定 `action_cancel_goal()`（ctrl+c 被 Textual 1.0 Input 的 copy 绑定占用，实测后改 Esc）；③ GUI 持有 `CronScheduler`：`gui_main()` 在 `cron_enabled` 时装配（`_run_job` 镜像 cli.py，`goal-advance` 走 `_goal_cron_advance`），`HeAgentApp.on_mount` 启动、`action_quit` 停止；④ 新增 `tests/test_gui_goal.py`（含「`/goal status` 进 goal runner 不落 bridge.submit」锁定测试，pilot 交互驱动）。
- **证据**：`src/heagent/gui/screens/chat.py`（`_StderrToLogForwarder` + `_goal_cmd` + `action_cancel_goal`）；`src/heagent/gui/__init__.py`（cron 装配）；`tests/test_gui_goal.py`（6 用例全绿）。
