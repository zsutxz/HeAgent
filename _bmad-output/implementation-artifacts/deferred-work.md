# Deferred Work — 活动台账（未闭合项）

> **本文件只登记活动（未闭合）遗留项**，是工作流的 append-only 入口（bmad-build defer 分诊写入）。
> 条目**闭合后**写 `Resolution`，随后按**归属 epic**归档到 `_bmad-output/epics/<周期>/deferred-work.md`，并可从此处移除（历史长文不保留）。
> 已闭合项归档索引见 `_bmad-output/consolidated-overview.md` 13.1；原跨周期台账 `_bmad-output/patches/_meta/deferred-work.md` 已于 2026-09-15 退役并删除。
> 格式：`source_spec` / `summary`（含触发条件、严重度、冻结边界）/ `evidence`。

- source_spec: `_bmad-output/epics/epic-43-46-目标级工作流周期/epic-46-技能资源并发替换安全评估/stories/46-1-skill-resource-toctou-assessment.md`
  summary: 后续评估 descriptor-relative/目录句柄、可信导入 snapshot 或 OS sandbox 加固。
  evidence: Story 46.2 已以 `O_NOFOLLOW` 加固支持平台上的最终路径组件，并保留不支持该标志时的兼容回退；中间目录替换、可信导入 snapshot 与 OS sandbox 仍未交付，现有路径围栏保留竞态残余风险。

- source_spec: `src/heagent/config.py`（`goal_max_iterations` 默认 20）
  summary: 已支持 workflow step 声明独立 `max_iterations`，但 bmad-build 的 Step 07 尚未配置该值，实际仍回退到全局 20；原子大 Story 仍可能撞上限后整批失败。
  evidence: `memory.skill_packages.WorkflowStepResource.max_iterations` 接受 1–1000 的 step 级预算，`cli_goal._goal_execute_step()` 将声明值传给 SubAgent；`.claude`、`.agents` 与 `.heagent` 的 bmad-build 工作流均未声明 `max_iterations`，因此仍使用 `Settings.goal_max_iterations`。`tests/test_goal_declarative_workflow.py::test_step_iteration_budget_overrides_the_global_default` 锁定覆盖行为。

- source_spec: `_bmad-output/epics/epic-41-目标驱动开发周期/spec-41-1-goal-skill-single-step.md`
  summary: GUI `/goal` 收口（合并原 Epic 41 台账的 3 条同源 bullet：输出转发、`RichLog` 路由、GUI 交互测试）：在 `heagent gui` 里跑 `/goal` 时，CLI goal runner 的 `click.echo` 进度与失败信息不进入 Textual `RichLog`（用户只看到一行「command completed」），GUI 也没有取消入口（`AgentBridge.cancel()` 只管 bridge 自持 task）、不持有 `CronScheduler`（cron 自动推进在 GUI 会话里不生效）；另缺一条 GUI 交互测试，证明 `/goal next`、`/goal status` 由 goal runner 处理且不落到 `AgentBridge.submit()` 当普通提示词。触发条件：在 GUI 内执行 `/goal`（含长跑或失败步骤）；严重度：中（命令可用但结果不可见、无法中止）；冻结边界：只补 GUI 接线与测试，不改 CLI runner 语义、产物路径与 `click.echo` 文案。
  evidence: `src/heagent/gui/screens/chat.py:211,216,230`（`_goal_cmd` 直接 `await cli_goal._goal_runner(..., cron_store=app.job_store)`，随后只写一行 `[dim]Goal command completed…[/]`）；`src/heagent/cli_goal.py` 共 66 行含 `click.echo`（走进程 stdout，未接 RichLog）；`src/heagent/gui/bridge.py:102` 的 `cancel()` 仅覆盖 bridge 自持的 task；`src/heagent/gui/` 全目录无 `CronScheduler` 引用；GUI 现有测试仅 `tests/test_gui_tool_state.py`，无 `/goal` 断言。

- source_spec: `_bmad-output/epics/epic-41-目标驱动开发周期/spec-41-1-goal-skill-single-step.md`
  summary: goal 状态无跨进程锁：`/goal` 的串行化只有进程内 `asyncio.Lock`，同一 workspace 起第二个 CLI 进程（或 cron 自动推进与手动命令并发）可同时执行同一条 Story，写 `GOAL.md` / goal 指针时互相覆盖并丢进度。触发条件：同一 workspace 并发跑同一个 goal；严重度：高（丢进度、状态不一致）；冻结边界：加锁不得改变单进程行为、产物格式与 checkpoint 语义，且不得把锁或框架键塞进 `RunContext.metadata`。
  evidence: `src/heagent/cli_goal.py:48` `_goal_auto_lock = asyncio.Lock()`，配 6 处 `async with`（`:1057`、`:1130`、`:1135`、`:1144`、`:1157` 与 cron 自动推进 `_goal_cron_advance` 的 `:1291`）；`:956` / `:957` 以 `atomic_write_text` 写 `GOAL.md` 与 `_GOALS_DIR/"current"`——**未**开 `lock=True`；`src/heagent/engine/persist.py` 既有 `atomic_write_text(lock=True)`（POSIX `fcntl.flock` / Windows `msvcrt.locking`，经 `EngineContainer(enable_file_locks=True)` 自动开启）可直接复用。

- source_spec: `_bmad-output/epics/epic-S1-S4-沙箱硬化周期/brief.md`（`### Deferred（未来考虑）`：「MCP server / cron 子进程接入沙箱」）
  summary: MCP stdio server 子进程未接入沙箱后端：MCP server 由 SDK 自行 spawn，不经过 `ToolExecutor.execute_in_sandbox`，因此 Firejail/WinJob 对它零覆盖（无 FS 隔离、无 `--net=none`）。触发条件：连接任意 `.mcp.json` 声明的 stdio server（第三方不可信代码）；严重度：中-高；冻结边界：不得为接沙箱而改变 MCP 连接/握手契约，且即便接入仍非安全边界（须整体 OS 级沙箱兜底）。注：「cron 子进程」一半不成立——`cron/` 无子进程路径（见下条）。
  evidence: `src/heagent/tools/mcp/manager.py:235` `StdioServerParameters(command=cfg.command, args=cfg.args, env=cfg.env or None)` → SDK 在 `mcp/client/stdio/__init__.py:253` 直接 `anyio.open_process`；沙箱侧只把 `shell` 纳入授权范围（`src/heagent/engine/container.py:240` `container.policy.sandbox_tools.add("shell")`）。

- source_spec: `_bmad-output/epics/epic-S1-S4-沙箱硬化周期/brief.md`（`### Deferred（未来考虑）`：「沙箱执行的资源限额」）
  summary: 沙箱 shell 无资源限额：内存/CPU/进程数无 `--rlimit-as` / `--rlimit-cpu` 之类上界，LLM 触发的大内存或长 CPU 命令可拖垮宿主。触发条件：沙箱内跑失控命令（内存炸弹 / 死循环）；严重度：中（可用性，非机密性）；冻结边界：限额触发须显性失败或显性标记，不得静默截断命令输出语义。
  evidence: 本次核实 `src/heagent/tools/sandbox.py` 全文件对 `rlimit` / `seccomp` / `caps` **零命中**；`FirejailBackend._build_argv` 当前只映射 profile → 参数 + `--private` + `--net=none`（`src/heagent/tools/sandbox.py:264`）。

- source_spec: `_bmad-output/epics/epic-S1-S4-沙箱硬化周期/brief.md`（`### Deferred（未来考虑）`：「`FirejailBackend` 的 `--seccomp` / `--caps` 等高级参数」）
  summary: Firejail 高级隔离参数未启用：无 `--seccomp` / `--caps`（能力集收敛）等硬化参数，隔离强度停留在 `--private` + `--net=none` + 进程组 kill。触发条件：沙箱逃逸面评估 / 高对抗场景；严重度：低（当前立场本就是「非安全边界、须 OS 级沙箱兜底」）；冻结边界：新参数须经 `profiles` 映射声明、默认关闭，避免改变既有默认行为。
  evidence: 本次核实 `src/heagent/tools/sandbox.py` 无 `seccomp` / `caps` 命中；承载点已存在——profile → 参数映射（`src/heagent/tools/sandbox.py:264`、`src/heagent/engine/policy.py:148,165` 的 `sandbox_profiles`）。

- source_spec: `_bmad-output/epics/epic-S1-S4-沙箱硬化周期/brief.md`（`### Deferred（未来考虑）`：「per-tool 粒度的 firejail 参数（目前 per-profile 粒度）」）
  summary: firejail 参数只到 profile 粒度：**tool → profile 的选择已存在**（按工具名查 `sandbox_profiles`，MCP 工具默认落 `mcp` profile），但**参数集是 per-profile**——想给某一个工具单独加参数，必须为它新建一个 profile。触发条件：需要在同 profile 内区分工具参数时；严重度：低（表达力缺口）；冻结边界：不得为粒度而破坏「策略要求沙箱但未授权 → fail-safe 阻断」的既有契约。
  evidence: `src/heagent/engine/policy.py:371`–`:379`（`_sandbox_profile`：`self.sandbox_profiles.get(call.name, "default")`，MCP 分支 `"__mcp__"` → `"mcp"`）；`src/heagent/tools/sandbox.py:264`（profile → argv 映射）；`src/heagent/engine/roles.py:41`（`RoleSpec.sandbox_profile`）。

- source_spec: `_bmad-output/epics/epic-36-39-文件安全防护周期/brief.md`（`### Deferred（未来考虑）`：「凭证 deny 规则的用户可配置入口」）
  summary: 凭证路径 deny 规则是代码内硬编码表，没有项目级可配置入口：用户既不能补充自己的敏感路径，也不能放行误报（如把某测试夹具目录从 deny 中排除）。触发条件：项目有自定义凭证布局，或内置规则误伤合法路径；严重度：低-中；冻结边界：用户配置只允许**收紧或放行显式列举项**，不得整体关闭 deny（fail-safe 默认仍为拒）。
  evidence: `src/heagent/tools/path_safety.py:89`（「凭证 deny / 内部状态读 deny（借鉴 hermes file_safety.py，纯函数）」起的内置表）＋ `:160` `write_deny_reason`、`:172` `read_deny_reason`；同域已有可配置先例可照抄形状——项目级 `.heagent/injection_signatures.json`（注入签名入口）。

- source_spec: `_bmad-output/epics/epic-36-39-文件安全防护周期/brief.md`（`### Deferred（未来考虑）`：「路径级审批分级（若未来引入非 workspace 的受控写场景）」）
  summary: 路径级审批分级（**条件性条目，前置未发生**）：当前审批粒度是工具级（destructive → 审批），file 工具一律被限制在 workspace 内，所以「按路径分级审批」暂无触发场景。触发条件：引入「非 workspace 的受控写场景」（例如经审批向 workspace 外写）；严重度：低（前置未发生）；冻结边界：分级只能是 `PolicyEngine` 的 defense-in-depth 标记，不得表述为 OS 级边界，也不得放松 workspace 围栏默认值。
  evidence: `src/heagent/tools/path_safety.py`（`resolve_under_root`，policy 预检与 file 工具 handler 共用同一算法）；`src/heagent/engine/policy.py`（destructive 注解闸门）；`src/heagent/engine/approval.py`（审批闭环，同为非安全边界）。
