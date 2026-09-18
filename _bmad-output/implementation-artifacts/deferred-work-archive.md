# Deferred Work——活动条目 + 勘察类闭合归档

> 本文件自 2026-09-17 起承接两类条目（原活动台账 `deferred-work.md` 已删除，用户裁定）：
> ① **活动（未闭合）条目**——工作流的 append-only 入口，闭合后按归属 epic 归档至各周期
> `deferred-work.md`（勘察类留在本文件，索引见 `consolidated-overview.md` 13.1）；
> ② **勘察类闭合归档**（source_spec 为勘察批次、无归属 epic）。

## 活动（未闭合）条目——4 条（2026-09-17 自活动台账迁入 6 条，2026-09-18 闭合 2 条 → Z-D8 / Z-D9）

- source_spec: `_bmad-output/epics/epic-43-46-目标级工作流周期/epic-46-技能资源并发替换安全评估/stories/46-1-skill-resource-toctou-assessment.md`
  summary: 后续评估 descriptor-relative/目录句柄、可信导入 snapshot 或 OS sandbox 加固。
  evidence: Story 46.2 已以 `O_NOFOLLOW` 加固支持平台上的最终路径组件，并保留不支持该标志时的兼容回退；中间目录替换、可信导入 snapshot 与 OS sandbox 仍未交付，现有路径围栏保留竞态残余风险。

- source_spec: `_bmad-output/epics/epic-S1-S4-沙箱硬化周期/brief.md`（`### Deferred（未来考虑）`：「MCP server / cron 子进程接入沙箱」）
  summary: MCP stdio server 子进程未接入沙箱后端：MCP server 由 SDK 自行 spawn，不经过 `ToolExecutor.execute_in_sandbox`，因此 Firejail/WinJob 对它零覆盖（无 FS 隔离、无 `--net=none`）。触发条件：连接任意 `.mcp.json` 声明的 stdio server（第三方不可信代码）；严重度：中-高；冻结边界：不得为接沙箱而改变 MCP 连接/握手契约，且即便接入仍非安全边界（须整体 OS 级沙箱兜底）。注：「cron 子进程」一半不成立——`cron/` 无子进程路径。
  evidence: `src/heagent/tools/mcp/manager.py:235` `StdioServerParameters(command=cfg.command, args=cfg.args, env=cfg.env or None)` → SDK 在 `mcp/client/stdio/__init__.py:253` 直接 `anyio.open_process`；沙箱侧只把 `shell` 纳入授权范围（`src/heagent/engine/container.py:248` `container.policy.sandbox_tools.add("shell")`）。

- source_spec: 2026-09-17 架构与代码优化勘察
  summary: cli.py 与 cli_goal.py 职责混杂可再拆（斜杠 handler / 装配 / replay+init；goal/ 子包已有 questionnaire.py 先例）。触发条件：再改这两个文件的重复区；严重度：低（可用，可维护性项）；冻结边界：拆分只挪代码不改行为，wiring.py 先例（docstring 记录拆分理由）。
  evidence: `src/heagent/cli.py`（6+ 类职责）、`src/heagent/cli_goal.py`（_goal_runner noqa C901）、`src/heagent/wiring.py:1-6`（拆分先例 docstring）。
  Progress（2026-09-17，保守拆分已落地，条目保持活动；当前行数：cli.py 1287→**1163**、cli_goal.py 1150+→**1054**）：① cli.py init 块（模板 ×2 + `_init_project_context` + `init_cmd`，约 130 行）已拆至 `cli_init.py`（独立 click 命令 + `main.add_command` 注册，cli.py re-export 保 import 缝）；② cli_goal.py 的 GOAL.md 文档与命名层（常量块 + 9 个文档函数，约 150 行）已拆至 `goal/document.py`（cli_goal re-export，测试零改动）。**剩余**：装配块与斜杠 handler 仍留原处——大量测试 monkeypatch `heagent.cli._run_prompt` / `cli.sys` / `cli_goal._goal_session` 等**模块路径缝**（目标函数及其调用方必须同模块），且有钉死测试锁「cli 只留三个自用 goal 符号」；进一步拆分需同步迁移测试缝，收益低于风险，暂缓。

- source_spec: `_bmad-output/epics/epic-36-39-文件安全防护周期/brief.md`（`### Deferred（未来考虑）`：「路径级审批分级（若未来引入非 workspace 的受控写场景）」）
  summary: 路径级审批分级（**条件性条目，前置未发生**）：当前审批粒度是工具级（destructive → 审批），file 工具一律被限制在 workspace 内，所以「按路径分级审批」暂无触发场景。触发条件：引入「非 workspace 的受控写场景」（例如经审批向 workspace 外写）；严重度：低（前置未发生）；冻结边界：分级只能是 `PolicyEngine` 的 defense-in-depth 标记，不得表述为 OS 级边界，也不得放松 workspace 围栏默认值。
  evidence: `src/heagent/tools/path_safety.py`（`resolve_under_root`，policy 预检与 file 工具 handler 共用同一算法）；`src/heagent/engine/policy.py`（destructive 注解闸门）；`src/heagent/engine/approval.py`（审批闭环，同为非安全边界）。

---

## 勘察类闭合归档

## 状态总览

| ID | 条目 | 结论 | 闭合 commit |
|----|------|------|-------------|
| Z-D1 | memory→engine 残余反向边（dream.py） | 已闭合 | `7b1b16b` |
| Z-D2 | 六处手写 frontmatter 解析器漂移 | 已闭合（实为 6 处，台账原记 4） | `e0d05cb` |
| Z-D3 | provider 三套回退骨架收敛 | **评估结论 = 不收敛**（有意分歧被护栏测试钉死），补四点互指注释 | `beea1a2` |
| Z-D4 | JsonlSink 逐事件同步落盘 | **评估结论 = 保持现状**（replay 契约天然满足），仅 docstring 如实化 | `4b5f037` |
| Z-D5 | CronScheduler 同步 store 调用 | 已闭合（4 处 to_thread，台账漏记 1 处） | `a633c5c` |
| Z-D6 | SafetyGuard/PolicyEngine 拦截零日志 | 已闭合（_block 单点 warning + policy 分级） | `3dd1050` |
| Z-D7 | GoalWorkflowState 三死字段 | 已闭合（容错忽略兼容策略） | `4b5f037` |
| Z-D8 | `RoleSpec.sandbox_profile` 死字段 | 已闭合（取**删除**方向，非激活） | 待提交（2026-09-18） |
| Z-D9 | 沙箱无进程数限额 + WinJob 常量误写 | 已闭合（`SANDBOX_NPROC_LIMIT` + 修正 `PROCESS_TIME=0x2`） | 待提交（2026-09-18） |

---

## Z-D1 memory→engine 残余反向边（dream.py）

- **来源**：2026-09-17 架构收敛批次（persist/roles 迁出 engine 包）遗留登记。
- **问题**：`memory/dream.py:47` 运行期整包导入 `heagent.engine.EngineContainer`（触发条件：engine 包级 `__init__` 将来依赖 memory 包级 `__init__`；当前无环，架构文本性违规）。
- **结论**：**已闭合**（2026-09-17，commit `7b1b16b`）。EngineContainer 移入 TYPE_CHECKING（经 `engine.container` 子模块）、构造参数 `engine` 改必传、删除 `EngineContainer.default()` 缺省回退——cli.py 与全部测试本就显式注入，零调用方受影响；FORBIDDEN_RUNTIME_IMPORTS 为 memory 补 `heagent.engine` 断言。DreamScheduler 入口层装配现状未变（冻结边界）。
- **证据**：`tests/test_dream.py` 全绿 + `tests/test_architecture_contracts.py` 新契约。

## Z-D2 六处手写 frontmatter 解析器漂移

- **来源**：2026-09-17 架构与代码优化勘察（原登记 4 处，收敛时发现实为 **6 处**——漏记 `roles.py _parse_role_md` 与 `skill_packages._parse_metadata`）。
- **问题**：各模块独立维护 `---` frontmatter 正则与键值解析，同一文档在不同模块可能解析出不同结果。
- **结论**：**已闭合**（2026-09-17，commit `e0d05cb`）。新建零 heagent 依赖顶层模块 `frontmatter.py`（persist/roles 同层）：两个分隔符变体（EOF / 须尾随换行，有意并存）+ 严档 `parse_strict_pairs` / 宽档 `parse_inline_pairs` / 标量 `parse_scalar`；六处调用方改指向共享模块，公开 API、异常类型与消息文案逐字保持；`skills._FRONTMATTER_RE` 常量名保留（就地改写字节跨度依赖）；架构契约新增「frontmatter 正则只允许出现在 frontmatter.py」断言。
- **证据**：`tests/test_frontmatter.py`（直测）+ 六个调用方既有测试全绿。

## Z-D3 provider 三套回退骨架收敛

- **来源**：2026-09-17 架构与代码优化勘察（原设想「回退模板 + sticky/reset 策略参数」收敛）。
- **问题**：chain / key_rotation / switchable（加 router 实为四套）各自维护平行 send/stream 回退循环。
- **结论**：**评估结论 = 不收敛**（2026-09-17，commit `beea1a2`）。勘察推翻收敛设想：分歧是有意设计且被护栏测试钉死——`retry.py` docstring 明言「不要合并成一套」（判据矩阵三方不同：chain 回退一切非 NON_TRANSIENT 含 AUTH_FAILED 跨 provider；key_rotation 仅 RATE_LIMITED+AUTH_FAILED；switchable/router 仅 RATE_LIMITED+TRANSIENT），索引语义各异（chain 复位 / key_rotation 成功即粘 / switchable 回退成功才粘 / router 无状态单兄弟重试），`test_retry.py::TestPoolFallbackPolicy` 钉死分歧。按冻结边界交付最低要求：switchable 与 router 的 send/stream 补齐互指注释（chain↔key_rotation 原有），形成四点互指网；行为零改动。

## Z-D4 JsonlSink 逐事件同步落盘

- **来源**：2026-09-17 架构与代码优化勘察。
- **问题**：`_append` 每事件 mkdir+open+write+close，docstring 自称「只做一次 write/flush」与实际不符。
- **结论**：**评估结论 = 保持逐事件 append，不改实现**（2026-09-17，commit `4b5f037`）。close 即 flush 天然满足 replay 契约（crash 已写前缀可回放）；缓冲/常驻句柄引入句柄生命周期与丢失窗口，当前吞吐（LLM 工具循环级）下开销可忽略。仅 docstring 如实化并记录决策理由。

## Z-D5 CronScheduler 同步 store 调用

- **来源**：2026-09-17 架构与代码优化勘察。
- **问题**：store 的 list/update/remove 在 async 调度路径上同步执行（同步文件 I/O + Windows 替换退避）。
- **结论**：**已闭合**（2026-09-17，commit `a633c5c`）。实为 4 处（台账漏记 one-shot 的 `remove`）：全部经 `asyncio.to_thread` 卸载（对齐 273cb89 与 WorkflowCheckpointStore 先例），JobStore 语义零改动。
- **证据**：`tests/test_cron.py::TestCronSchedulerTickPath`（tick 路径集成测试 ×2；两测试用不同 job_id——ledger key 含分钟级时间戳且共享默认 ledger 路径，同分钟重复 id 会被幂等 lease 跳过）。

## Z-D6 SafetyGuard/PolicyEngine 拦截零日志

- **来源**：2026-09-17 架构与代码优化勘察（台账原记「48/108 文件无 logger」，实测已 61/108）。
- **问题**：拦截只抛异常 + 发事件，日志零轨迹，事后无法审计。
- **结论**：**已闭合**（2026-09-17，commit `3dd1050`）。`safety.py` `_block()` 单点收口落 warning（覆盖全部 5 个拦截分支）；`policy.py` 5 处 BLOCKED 落 warning、APPROVAL_REQUIRED 落 info（SANDBOX_REQUIRED 常规路由不记防刷屏）；拦截语义零改动。
- **证据**：`tests/test_safety.py` / `tests/test_engine_p0.py` 各补 caplog 断言。

## Z-D7 GoalWorkflowState 三死字段

- **来源**：2026-09-17 架构与代码优化勘察（读者已随 RecoveryEnvelope 删除）。
- **问题**：`segment_index` / `segment_tokens` / `cumulative_tokens` 三字段无人读，仅落盘 schema 保留。
- **结论**：**已闭合**（2026-09-17，commit `4b5f037`，兼容策略 = 容错忽略）。三字段删除；pydantic 默认 `extra='ignore'` 保证旧 workflow.json 仍可加载；`test_engine_workflow.py` 新增含三键旧文件的加载测试固化契约。

## Z-D8 `RoleSpec.sandbox_profile` 死字段

- **来源**：2026-09-17 沙箱硬化勘察（第二轮优化批次）；2026-09-18 处置。
- **问题**：字段**既无消费方也无写入方**——全仓检索仅 `roles.py` 字段定义与 `sandbox.py` 一句 docstring；`_parse_role_md` 的 `keys=("name", "description", "tools", "max_iterations")` 从未解析它，故连从角色 `.md` 都设不了；`SubAgent._build_engine` 克隆父 policy 时不读该字段。
- **结论**：**已闭合**（2026-09-18，取「**删除**」方向而非「激活」）。① 删除 `roles.py` 字段与其注释；② 改写 `tools/sandbox.py:260` docstring——profile 的真正入口是 `PolicyEngine` 裁决出的 profile 名（`SANDBOX_PROFILES` / `SANDBOX_TOOL_PROFILES`，2026-09-17 硬化批），不再谎称来自角色字段；③ 修正 `docs/frame.md` 4.4 里「使 `RoleSpec.sandbox_profile` 死字段激活」这句**从未成立**的旧表述。**未选激活**的理由：谓词为「角色声明了 profile 但沙箱未授权」时必须 fail-safe 阻断（冻结边界），于是该字段只剩「沙箱已强制时换参数集」这点表达力，低于维护成本（YAGNI）。
- **证据**：`tests/test_roles.py` / `tests/test_architecture_contracts.py` / `tests/test_sandbox*.py` 全绿；`docs/frame.md` 4.4 与本文件引用同步。

## Z-D9 沙箱无进程数限额 + WinJob 常量误写

- **来源**：2026-09-17 沙箱硬化勘察（兑现资源限额 Resolution「进程数限额另立条目」）；2026-09-18 处置。
- **问题**：① 沙箱 shell 无**进程数**上界——firejail 未映射 `--rlimit-nproc`，WinJob 的 `ActiveProcessLimit` 字段虽已内联定义却从未赋值；fork bomb 只被 `tools/safety.py` 黑名单正则启发式覆盖（非资源上界）。② **顺带查出的既有 bug**：`WinJobBackend.run()` 把 `JOB_OBJECT_LIMIT_PROCESS_TIME` 误写为 `0x00000008`——按 Windows SDK（winnt.h）该位是 `JOB_OBJECT_LIMIT_ACTIVE_PROCESS`，`PROCESS_TIME` 的正确值是 `0x00000002`。后果：配了 `SANDBOX_CPU_SECONDS` 时置位的是 ACTIVE_PROCESS 而 `ActiveProcessLimit` 仍为 0——**CPU 时间限额完全不生效，反而施加了「活动进程上限 0」**。
- **结论**：**已闭合**（2026-09-18，取「补齐」方向）。① 新增 `Settings.sandbox_nproc_limit`（`SANDBOX_NPROC_LIMIT`，默认 0=关闭），经 `container.default()` 同时透传两个后端；② `FirejailBackend._build_argv` 在 `--rlimit-cpu` 之后注入 `--rlimit-nproc`（0 时零参数，默认 argv 逐字节不变）；③ `WinJobBackend.run()` 置 `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` + `ActiveProcessLimit`；④ 修正 ②的常量误写（`PROCESS_TIME = 0x2`）。触发行为与内存/CPU 限额一致：**显性失败**（子进程被终止 → 非零退出码），不静默。⚠ **两个后端语义不对称（如实标注，不掩盖）**：firejail 的 `--rlimit-nproc` 底层是 `setrlimit(RLIMIT_NPROC)`，Linux 按**真实 UID** 计数（非 cgroup/job 作用域），设小了会波及同一用户的其他进程；WinJob 的 `ActiveProcessLimit` 才是 job 作用域——故默认关闭。
- **证据**：`tests/test_sandbox_mode.py`（默认值 / 两后端装配 / argv 注入与零参数三条）、`tests/test_coverage_sandbox.py::test_run_applies_resource_limits`（0x2 与 0x8 分开断言，钉死常量区分）；`docs/frame.md` 4.4 与配置表、`.env.example` 同步。
