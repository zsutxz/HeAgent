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
  Resolution: 2026-09-17 已闭合。`.heagent/workflows/workflow.md` Step 07 元数据块声明 `max_iterations: 100`（`/goal` 实际只加载该文件；`.claude`/`.agents` 的技能副本属另一管线不消费该字段），正文「本步骤预算」表述同步更新；真实文件解析验证 step.max_iterations == 100。

- source_spec: `_bmad-output/epics/epic-41-目标驱动开发周期/spec-41-1-goal-skill-single-step.md`
  summary: GUI `/goal` 收口（合并原 Epic 41 台账的 3 条同源 bullet：输出转发、`RichLog` 路由、GUI 交互测试）：在 `heagent gui` 里跑 `/goal` 时，CLI goal runner 的 `click.echo` 进度与失败信息不进入 Textual `RichLog`（用户只看到一行「command completed」），GUI 也没有取消入口（`AgentBridge.cancel()` 只管 bridge 自持 task）、不持有 `CronScheduler`（cron 自动推进在 GUI 会话里不生效）；另缺一条 GUI 交互测试，证明 `/goal next`、`/goal status` 由 goal runner 处理且不落到 `AgentBridge.submit()` 当普通提示词。触发条件：在 GUI 内执行 `/goal`（含长跑或失败步骤）；严重度：中（命令可用但结果不可见、无法中止）；冻结边界：只补 GUI 接线与测试，不改 CLI runner 语义、产物路径与 `click.echo` 文案。
  evidence: `src/heagent/gui/screens/chat.py:211,216,230`（`_goal_cmd` 直接 `await cli_goal._goal_runner(..., cron_store=app.job_store)`，随后只写一行 `[dim]Goal command completed…[/]`）；`src/heagent/cli_goal.py` 共 66 行含 `click.echo`（走进程 stdout，未接 RichLog）；`src/heagent/gui/bridge.py:102` 的 `cancel()` 仅覆盖 bridge 自持的 task；`src/heagent/gui/` 全目录无 `CronScheduler` 引用；GUI 现有测试仅 `tests/test_gui_tool_state.py`，无 `/goal` 断言。
  Resolution: 2026-09-17 已收口。① stderr→RichLog：`_StderrToLogForwarder`（chat.py，按行缓冲 + `escape`）经 `contextlib.redirect_stderr` 包裹 `_goal_runner`——`click.echo(err=True)` 调用时动态查 `sys.stderr`，重定向有效，cli_goal 零改动（冻结边界内）；② 取消入口：ChatScreen `Esc` 绑定 `action_cancel_goal()`（ctrl+c 被 Textual 1.0 Input 的 copy 绑定占用，实测后改 Esc）；③ GUI 持有 `CronScheduler`：`gui_main()` 在 `cron_enabled` 时装配（`_run_job` 镜像 cli.py，`goal-advance` 走 `_goal_cron_advance`），`HeAgentApp.on_mount` 启动、`action_quit` 停止；④ 新增 `tests/test_gui_goal.py`（含「`/goal status` 进 goal runner 不落 bridge.submit」锁定测试，pilot 交互驱动）。

- source_spec: `_bmad-output/epics/epic-S1-S4-沙箱硬化周期/brief.md`（`### Deferred（未来考虑）`：「MCP server / cron 子进程接入沙箱」）
  summary: MCP stdio server 子进程未接入沙箱后端：MCP server 由 SDK 自行 spawn，不经过 `ToolExecutor.execute_in_sandbox`，因此 Firejail/WinJob 对它零覆盖（无 FS 隔离、无 `--net=none`）。触发条件：连接任意 `.mcp.json` 声明的 stdio server（第三方不可信代码）；严重度：中-高；冻结边界：不得为接沙箱而改变 MCP 连接/握手契约，且即便接入仍非安全边界（须整体 OS 级沙箱兜底）。注：「cron 子进程」一半不成立——`cron/` 无子进程路径（见下条）。
  evidence: `src/heagent/tools/mcp/manager.py:235` `StdioServerParameters(command=cfg.command, args=cfg.args, env=cfg.env or None)` → SDK 在 `mcp/client/stdio/__init__.py:253` 直接 `anyio.open_process`；沙箱侧只把 `shell` 纳入授权范围（`src/heagent/engine/container.py:240` `container.policy.sandbox_tools.add("shell")`）。

- source_spec: 2026-09-17 架构收敛批次（persist/roles 迁出 engine 包）
  summary: `memory/dream.py:47` 整包导入 `heagent.engine.EngineContainer`——memory→engine 的残余反向边（本批有意不处理，只迁 persist/roles）。触发条件：engine 包级 `__init__` 将来依赖 memory 包级 `__init__`（当前 engine 仅依赖 `memory.skill_packages` 单模块，运行时无环）；严重度：低（无环，架构文本性违规）；冻结边界：迁移不得改变 DreamScheduler 由入口层装配的现状。
  evidence: `src/heagent/memory/dream.py:47` `from heagent.engine import EngineContainer`；engine→memory 允许边为 `engine/workflow_runner.py:21`（`memory.skill_packages` 资源模型）。
  Resolution: 2026-09-17 已闭合。`dream.py` 删除运行时整包导入（`EngineContainer` 移入 TYPE_CHECKING、经 `engine.container` 子模块），构造参数 `engine` 改必传、删除 `EngineContainer.default()` 缺省回退（cli.py:427 与全部测试本就显式注入，零调用方受影响）；`tests/test_architecture_contracts.py` 的 FORBIDDEN_RUNTIME_IMPORTS 为 memory 补 `heagent.engine` 断言，拒绝回退。DreamScheduler 入口层装配现状未变。

- source_spec: 2026-09-17 架构与代码优化勘察
  summary: 四份手写 frontmatter 解析器各自漂移（`engine/artifacts.py:134` parse_frontmatter、`memory/skills.py:37` _FRONTMATTER_RE、`memory/skill_packages.py:440` _parse_resource_frontmatter、`slash.py:104` _parse_command_md），同一文档在不同模块可能解析出不同结果；收敛为单一共享解析工具（strictness 参数化）。触发条件：任一解析器新增键 / 调整宽容度；严重度：低-中（潜伏不一致面）；冻结边界：不改任何现有文档格式，只收敛实现。
  evidence: `src/heagent/engine/artifacts.py:110,134`、`src/heagent/memory/skills.py:37,496`、`src/heagent/memory/skill_packages.py:440,507`、`src/heagent/slash.py:104`。
  Resolution: 2026-09-17 已闭合。新建零 heagent 依赖顶层模块 `src/heagent/frontmatter.py`（persist/roles 同层），收敛实为 **6 处**解析器（台账漏记 `roles.py:99 _parse_role_md` 与 `skill_packages.py:507 _parse_metadata`）：两个分隔符变体（EOF / 须尾随换行，有意并存不改行为）+ 严档 `parse_strict_pairs` / 宽档 `parse_inline_pairs` / 标量 `parse_scalar`；六处调用方改指向共享模块，公开 API、异常类型与消息文案逐字保持（既有测试全绿锁定）；`skills._FRONTMATTER_RE` 常量名保留（就地改写字节跨度依赖）；架构契约新增「frontmatter 正则只允许出现在 frontmatter.py」断言。新增 `tests/test_frontmatter.py` 直测。

- source_spec: 2026-09-17 架构与代码优化勘察
  summary: cli.py（1287 行）与 cli_goal.py（1150+ 行）职责混杂可再拆（斜杠 handler / 装配 / replay+init；goal/ 子包已有 questionnaire.py 先例）。触发条件：再改这两个文件的重复区；严重度：低（可用，可维护性项）；冻结边界：拆分只挪代码不改行为，wiring.py 先例（docstring 记录拆分理由）。
  evidence: `src/heagent/cli.py`（6+ 类职责）、`src/heagent/cli_goal.py`（_goal_runner noqa C901）、`src/heagent/wiring.py:1-6`（拆分先例 docstring）。
  Progress（2026-09-17，保守拆分已落地，条目保持活动）：① cli.py init 块（模板 ×2 + `_init_project_context` + `init_cmd`，约 130 行）已拆至 `cli_init.py`（独立 click 命令 + `main.add_command` 注册，cli.py re-export 保 import 缝）；② cli_goal.py 的 GOAL.md 文档与命名层（常量块 + 9 个文档函数，约 150 行）已拆至 `goal/document.py`（cli_goal re-export，测试零改动）。**剩余**：装配块与斜杠 handler 仍留原处——大量测试 monkeypatch `heagent.cli._run_prompt` / `cli.sys` / `cli_goal._goal_session` 等**模块路径缝**（目标函数及其调用方必须同模块），且有钉死测试锁「cli 只留三个自用 goal 符号」；进一步拆分需同步迁移测试缝，收益低于风险，暂缓。

- source_spec: 2026-09-17 架构与代码优化勘察
  summary: provider 委托骨架（chain/key_rotation/switchable 三套平行 send/stream 回退）是有文档的有意重复（chain.py:127 同构说明），可用「回退模板 + sticky/reset 索引策略参数」收敛；需对照测试。触发条件：三处任一改动时；严重度：低-中；冻结边界：不共用模板则至少保持 chain.py:127 的对照提醒注释。
  evidence: `src/heagent/providers/chain.py:77-171,127-129`、`src/heagent/providers/key_rotation.py:69-143`、`src/heagent/providers/switchable.py:156-247`。
  Resolution: 2026-09-17 评估结论 = **不收敛**。勘察推翻收敛设想：三套（实为四套，含 router）骨架的分歧是有意设计且被护栏测试钉死——`retry.py` 模块 docstring 明言「不要合并成一套」（判据矩阵三方不同：chain 回退一切非 NON_TRANSIENT 含 AUTH_FAILED 跨 provider；key_rotation 仅 RATE_LIMITED+AUTH_FAILED；switchable/router 仅 RATE_LIMITED+TRANSIENT），索引语义两方不同（chain 复位 / key_rotation 成功即粘 / switchable 回退成功才粘 / router 无状态单兄弟重试），`test_retry.py::TestPoolFallbackPolicy`（`test_auth_failed_excluded_even_though_chain_falls_back_on_it` + `test_predicate_has_a_single_implementation`）把分歧钉死防止「误当漂移顺手统一」。交付：switchable.py send/stream 与 router.py send/stream 补齐互指注释（chain↔key_rotation 原有），形成四点互指网；行为零改动。

- source_spec: `_bmad-output/epics/epic-S1-S4-沙箱硬化周期/brief.md`（`### Deferred（未来考虑）`：「沙箱执行的资源限额」）
  summary: 沙箱 shell 无资源限额：内存/CPU/进程数无 `--rlimit-as` / `--rlimit-cpu` 之类上界，LLM 触发的大内存或长 CPU 命令可拖垮宿主。触发条件：沙箱内跑失控命令（内存炸弹 / 死循环）；严重度：中（可用性，非机密性）；冻结边界：限额触发须显性失败或显性标记，不得静默截断命令输出语义。
  evidence: 本次核实 `src/heagent/tools/sandbox.py` 全文件对 `rlimit` / `seccomp` / `caps` **零命中**；`FirejailBackend._build_argv` 当前只映射 profile → 参数 + `--private` + `--net=none`（`src/heagent/tools/sandbox.py:264`）。
  Resolution: 2026-09-17 已闭合。新增 `SANDBOX_MEMORY_LIMIT_MB` / `SANDBOX_CPU_SECONDS`（默认 0=关闭，默认行为逐字节不变）：firejail 映射 `--rlimit-as` / `--rlimit-cpu`（profile 参数后、`--` 前），WinJob 映射 `JOB_OBJECT_LIMIT_JOB_MEMORY` / `JOB_OBJECT_LIMIT_PROCESS_TIME`（与恒开 KILL_ON_JOB_CLOSE 按位或，复用既有内联结构体零新增）；**触发即显性失败**（子进程被终止 → 非零退出码经正常结果回传，对齐超时 `exit_code=-1` 先例），不静默截断。进程数限额未做（两后端均无自然承载点，需要时另立条目）。

- source_spec: `_bmad-output/epics/epic-S1-S4-沙箱硬化周期/brief.md`（`### Deferred（未来考虑）`：「`FirejailBackend` 的 `--seccomp` / `--caps` 等高级参数」）
  summary: Firejail 高级隔离参数未启用：无 `--seccomp` / `--caps`（能力集收敛）等硬化参数，隔离强度停留在 `--private` + `--net=none` + 进程组 kill。触发条件：沙箱逃逸面评估 / 高对抗场景；严重度：低（当前立场本就是「非安全边界、须 OS 级沙箱兜底」）；冻结边界：新参数须经 `profiles` 映射声明、默认关闭，避免改变既有默认行为。
  evidence: 本次核实 `src/heagent/tools/sandbox.py` 无 `seccomp` / `caps` 命中；承载点已存在——profile → 参数映射（`src/heagent/tools/sandbox.py:264`、`src/heagent/engine/policy.py:148,165` 的 `sandbox_profiles`）。
  Resolution: 2026-09-17 已闭合。新增 `SANDBOX_PROFILES`（JSON：profile 名 → firejail 参数表，如 `{"default": ["--seccomp", "--caps.drop=all"]}`）经 `container.default()` 传入 `FirejailBackend.profiles`——此前生产装配下 `profiles` 恒空（勘察确认），高级参数由此声明、**默认关闭**（冻结边界满足）；坏 JSON/坏条目告警丢弃（对齐 routing_pool_map 容错）。

- source_spec: `_bmad-output/epics/epic-S1-S4-沙箱硬化周期/brief.md`（`### Deferred（未来考虑）`：「per-tool 粒度的 firejail 参数（目前 per-profile 粒度）」）
  summary: firejail 参数只到 profile 粒度：**tool → profile 的选择已存在**（按工具名查 `sandbox_profiles`，MCP 工具默认落 `mcp` profile），但**参数集是 per-profile**——想给某一个工具单独加参数，必须为它新建一个 profile。触发条件：需要在同 profile 内区分工具参数时；严重度：低（表达力缺口）；冻结边界：不得为粒度而破坏「策略要求沙箱但未授权 → fail-safe 阻断」的既有契约。
  evidence: `src/heagent/engine/policy.py:371`–`:379`（`_sandbox_profile`：`self.sandbox_profiles.get(call.name, "default")`，MCP 分支 `"__mcp__"` → `"mcp"`）；`src/heagent/tools/sandbox.py:264`（profile → argv 映射）；`src/heagent/roles.py:41`（`RoleSpec.sandbox_profile`）。
  Resolution: 2026-09-17 已闭合。新增 `SANDBOX_TOOL_PROFILES`（JSON：工具名 → profile 名）叠加进 `PolicyEngine.sandbox_profiles`（`container.default()` 注入），与 `SANDBOX_PROFILES` 两段配置组合即得 per-tool 参数差异——不引入新抽象（对齐 epic 边界「不引入 SandboxProfile 类」），fail-safe 阻断契约未动（executor 双重授权复核与 `context_grants_sandbox` 无 context 恒 False 均原样）。

- source_spec: `_bmad-output/epics/epic-36-39-文件安全防护周期/brief.md`（`### Deferred（未来考虑）`：「凭证 deny 规则的用户可配置入口」）
  summary: 凭证路径 deny 规则是代码内硬编码表，没有项目级可配置入口：用户既不能补充自己的敏感路径，也不能放行误报（如把某测试夹具目录从 deny 中排除）。触发条件：项目有自定义凭证布局，或内置规则误伤合法路径；严重度：低-中；冻结边界：用户配置只允许**收紧或放行显式列举项**，不得整体关闭 deny（fail-safe 默认仍为拒）。
  evidence: `src/heagent/tools/path_safety.py:89`（「凭证 deny / 内部状态读 deny（借鉴 hermes file_safety.py，纯函数）」起的内置表）＋ `:160` `write_deny_reason`、`:172` `read_deny_reason`；同域已有可配置先例可照抄形状——项目级 `.heagent/injection_signatures.json`（注入签名入口）。
  Resolution: 2026-09-17 已闭合（函数名勘误：实为 `check_write_denied` / `check_read_denied`）。新增项目级 `.heagent/path_deny.json`（workspace 围栏锚定 + 进程级懒缓存，对齐注入签名先例）：`deny_write_paths`/`deny_write_prefixes`/`deny_read_basenames` 收紧、`allow_write_paths`/`allow_read_basenames` 放行显式列举项（内部状态目录 deny **不接受豁免**）；**无整体关闭入口**，fail-safe 默认仍拒（冻结边界满足）。5 个消费点零改动（两层纵深自动生效）。

- source_spec: `_bmad-output/epics/epic-36-39-文件安全防护周期/brief.md`（`### Deferred（未来考虑）`：「路径级审批分级（若未来引入非 workspace 的受控写场景）」）
  summary: 路径级审批分级（**条件性条目，前置未发生**）：当前审批粒度是工具级（destructive → 审批），file 工具一律被限制在 workspace 内，所以「按路径分级审批」暂无触发场景。触发条件：引入「非 workspace 的受控写场景」（例如经审批向 workspace 外写）；严重度：低（前置未发生）；冻结边界：分级只能是 `PolicyEngine` 的 defense-in-depth 标记，不得表述为 OS 级边界，也不得放松 workspace 围栏默认值。
  evidence: `src/heagent/tools/path_safety.py`（`resolve_under_root`，policy 预检与 file 工具 handler 共用同一算法）；`src/heagent/engine/policy.py`（destructive 注解闸门）；`src/heagent/engine/approval.py`（审批闭环，同为非安全边界）。

- source_spec: 2026-09-17 架构与代码优化勘察
  summary: JsonlSink rollout 落盘逐事件同步 write+flush（docstring 自称「只做一次 write/flush」但含 mkdir+open+write，事件环缓冲仅 200 条），可考虑缓冲写或后台写线程。触发条件：高事件吞吐场景（长 run / 多工具并发）；严重度：低；冻结边界：不得破坏 replay 契约（crash 时已 flush 的前缀必须可回放）。
  evidence: `src/heagent/events/sink.py:111-119`（_append 同步落盘）。
  Resolution: 2026-09-17 评估结论 = **保持逐事件 append，不改实现**。每事件 open+write+close（close 即 flush）天然满足 replay 契约；缓冲/常驻句柄引入句柄生命周期与丢失窗口，当前吞吐（LLM 工具循环级）下开销可忽略。仅修正 docstring 如实描述并记录决策理由。

- source_spec: 2026-09-17 架构与代码优化勘察
  summary: CronScheduler 的 store 调用（list_jobs/update→atomic_write_text 含 time.sleep 锁轮询）在 async 调度路径上同步执行，低频小文件、低危，属一致性修补。触发条件：cron tick 频繁或 job 数大时；严重度：低；冻结边界：只换执行线程不改 store 语义。
  evidence: `src/heagent/cron/scheduler.py:117,177,187` → `src/heagent/cron/jobs.py:133`（atomic_write_text）。
  Resolution: 2026-09-17 已闭合。实为 4 处（台账漏记 one-shot 的 `remove`）：scheduler.py 的 `list_jobs` / 两处 `update(last_run)` / `remove` 全部经 `asyncio.to_thread` 卸载（对齐 273cb89 与 WorkflowCheckpointStore 先例），JobStore 语义零改动；实际阻塞源是同步文件 I/O + Windows 替换退避（jobs.py 未开锁轮询）。新增 tick 路径集成测试 ×2（到期执行 + last_run 落盘 / one-shot 移除）。

- source_spec: 2026-09-17 架构与代码优化勘察
  summary: SafetyGuard / PolicyEngine 拦截时零日志轨迹（只抛异常 + 发事件），108 个 py 文件中 48 个无 logger；裁决不可观测不利事后审计。触发条件：需要审计「谁在何时被拦截了什么」时；严重度：低-中；冻结边界：补 logger 声明与拦截事件日志，不改拦截语义。
  evidence: `src/heagent/tools/safety.py`、`src/heagent/engine/policy.py` 全文件零 logging 引用。
  Resolution: 2026-09-17 已闭合。`safety.py` 在 `_block()` 单点收口落 `logger.warning`（覆盖全部 5 个拦截分支）；`policy.py` 在 5 处 BLOCKED 裁决点落 warning、APPROVAL_REQUIRED 落 info（SANDBOX_REQUIRED 为常规路由不记，避免刷屏）；拦截语义零改动。test_safety.py / test_engine_p0.py 各补 caplog 断言。（注：无 logger 文件数实测 61/108，台账口径 48 已过时。）

- source_spec: 2026-09-17 架构与代码优化勘察
  summary: `GoalWorkflowState.segment_index/segment_tokens/cumulative_tokens` 三字段自 legacy 阶段状态机删除后无人读（构造时不传、仅落盘 schema 保留），后续可选清理（需先定 workflow.json schema 兼容策略：拒绝旧文件 or 容错忽略）。
  触发条件：下次改动 workflow.json schema 时顺带处理；严重度：低；冻结边界：清理不得破坏既有 `_he-output/goals/*/workflow.json` 的读取。
  evidence: `src/heagent/engine/workflow.py`（GoalWorkflowState 三字段）；读者已随 RecoveryEnvelope（2026-09-17 批次 2）删除。
  Resolution: 2026-09-17 已闭合（兼容策略 = 容错忽略）。三字段删除；pydantic 默认 `extra='ignore'` 保证旧 workflow.json 仍可加载，`test_engine_workflow.py` 新增含三键旧文件的加载测试固化该契约；`test_goal_workflow_smoke.py` 的两处无断言写入同步移除。
