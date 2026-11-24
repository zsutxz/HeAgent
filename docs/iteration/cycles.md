# 迭代历程（怎么走到现在）

> 状态：历史历程。维护责任：各周期变更提交者。迭代流程、经验教训与路线图见 [index.md](index.md)；当前行为以 [framework.md](../framework.md) 和源码为准。

## 二、迭代历程（怎么走到现在）

### 2.1 主线周期 · Epic 1-10

**Epic 1-5（MVP，FR-1~19）** —— 来源 `_bmad-output/epics/epic-01-10-主线规划周期/epics.md`：

| Epic | 主题 | FR |
|------|------|----|
| 1 | 项目基础设施与 LLM 通信 | FR-1~5, 19 |
| 2 | 自主 Agent 核心循环 | FR-6~9, 14 |
| 3 | 对话持久化与上下文管理 | FR-13, 15 |
| 4 | 自学习记忆系统 | FR-10~12 |
| 5 | 多 Agent 并行编排 | FR-16, 17 |

**Epic 6-10（自学习闭环扩展，FR-20~24）** —— 来源 `_bmad-output/epics/epic-01-10-主线规划周期/epics-self-learning.md`，补齐从「被动工具」到「主动学习者」的能力：

| Epic | 主题 | FR |
|------|------|----|
| 6 | Context Files 自动加载 | FR-20 |
| 7 | SOUL.md 人格系统 | FR-21 |
| 8 | Memory Nudge 记忆提醒 | FR-22 |
| 9 | Skill Curator 技能策展 | FR-23 |
| 10 | Cron 定时调度 | FR-24 |

> MVP 范围内的 FR-18（MCP 工具发现）当时标注「延后」，后由 MCP 周期承接。

### 2.2 MCP 客户端集成周期一 · Epic 11-13

来源 `_bmad-output/epics/epic-11-18-MCP集成周期/`（阶段一，原 `mcp-client/`，2026-08-18 合并），独立 brief/prd/architecture/epics：

| Epic | 主题 |
|------|------|
| 11 | MCP 工具桥接（FR-1~8：配置加载、tool↔ToolSchema 映射、ClientManager 生命周期、CLI 装配） |
| 12 | GitHub 只读验收（FR-9：E2E 锁定真实工具名） |
| 13 | 安全边界与开源可用（FR-10/11：安全声明覆盖 MCP 不可信边界 + 开源文档） |

### 2.3 MCP 客户端 V2 集成周期二 · Epic 15-18

来源 `_bmad-output/epics/epic-11-18-MCP集成周期/`（阶段三，原 `mcp-client-v2/`），2026-07-17 启动。延续主线编号 15-18（映射 epics.md 的 Epic A/B/C + 内置工具扩展）：

| Epic | 主题 | 状态 |
|------|------|------|
| 15 | 写操作治理 — MCP 工具危险分级的确定性闸门（FR-A1~A7，AD-1/2/3） | **已完成** — 15-1 annotations 数据管线 + 15-2 policy 注解闸门 + 15-3 零回归确定性 + 15-4 安全声明同步已全部 `done` |
| 16 | Resources on-demand 发现与读取（FR-B1~B4，AD-4/5/6） | **已完成** — 16-1 sessions 查找表 + 16-2 list_resources 桥接工具 + 16-3 read_resource + guard_content 围栏 + 16-4 安全声明同步已全部 `done` |
| 17 | Prompts 交互式协商（FR-C1~C4，AD-7/8/9） | **已完成** — 17-1 manager prompts 入口 + 17-2 slash 命令调度 + 17-3 渲染守卫 + 17-4 测试已全部 `done` |
| 18 | 内置工具扩展（git 工具 + path safety 集成） | **已完成** — 18-1 git-status-diff + 18-2 git-log-blame + 18-3 path-safety-integration + 18-4 tests-docs 已全部 `done` |

### 2.4 沙箱硬化周期 · Epic S1-S4

来源 `_bmad-output/epics/epic-S1-S4-沙箱硬化周期/`，2026-07-20 启动。Sandbox 后端硬化，含 firejail profile 映射、降级、配置入口、Linux 进程组 kill、workspace 隔离：

| Epic | 主题 | 状态 |
|------|------|------|
| S1 | profile 映射 + contextvar 注入 | **已完成** |
| S2 | firejail 可用性降级 + 配置入口 | **已完成** |
| S3 | Linux 进程组 kill + workspace 隔离 | **已完成** |
| S4 | 安全声明同步 | **已完成** — S4-1 emit 事件被跳过，S4-2 安全声明同步 `done` |

### 2.5 健壮性与质量硬化周期 · Epic 19-20

来源 `_bmad-output/epics/epic-19-20-健壮性硬化周期/`，2026-07-21 启动。跨进程文件锁、Cron 范围表达式、WinJobBackend、覆盖率 89%→90%：

| Epic | 主题 | 状态 |
|------|------|------|
| 19 | 健壮性硬化（FR-A1~A5） | **已完成** |
| 20 | 质量工程化（FR-C1~C6） | **已完成** — 覆盖率 89%→90%，922 测试全绿 |

### 2.6 质量工程深化周期 · Epic 21-24

来源 `_bmad-output/epics/epic-21-24-质量工程周期/`，2026-07-22 启动。Coverage 工程化、Benchmark 重构、Docker 硬化、CI 效能/安全左移：

| Epic | 主题 | 状态 |
|------|------|------|
| 21 | Coverage 工程化 | **已完成** |
| 22 | Benchmark 重构 | **已完成** |
| 23 | Docker 硬化 | **已完成** |
| 24 | CI 效能与安全左移 | **已完成** |

### 2.7 GUI 终端界面周期 · Epic 25-28

来源 `_bmad-output/epics/epic-25-28-GUI界面周期/`，2026-07-23 启动。Textual 终端界面，含流式聊天、工具可视化、管理面板、可观测性。

> 下表是 **2026-07-23 规划期快照**（当时尚未动工）；实际状态：**Epic 25-28 全部 `done`**（12 story），以 `_bmad-output/Goal-2-v6/sprint-status.yaml`（v6，已归档）为准。

| Epic | 主题 | 状态（规划期快照） |
|------|------|------|
| 25 | 流式聊天 — 最小可跑（FR-G1~G6） | **in-progress** — 25-1/2/3 ready-for-dev |
| 26 | 工具可视化 + 斜杠命令（FR-G7~G14） | backlog |
| 27 | 管理面板（FR-G15~G19） | backlog |
| 28 | 可观测性（FR-G20~G24） | backlog |

### 2.8 补丁周期 · 技术债收尾

`_bmad-output/patches/`（**2026-09-15 解散**）曾按领域扁平分目录存放计划外补丁 spec，现已**按归属 epic 与它服务的 story 同目录归档**（`epics/<周期>/<epic-NN-主题>/`）；逐文件映射与已交付 spec 清单见 [`_bmad-output/README.md`](../../_bmad-output/README.md)「归档规则」节与 [`retrospective-all-cycles.md`](../../_bmad-output/retrospective-all-cycles.md) §三。
遗留项活动台账与闭合归档机制见 1.4。

### 2.9 engine/ 增量 · epic 外 P0-P5

运行时治理层（`PolicyEngine` + `ToolExecutor` + `store/ledger/observability`）按 P 批演进，不挂 Epic 编号，进度记入 `framework.md` 4.12：

| 批次 | 内容 |
|------|------|
| P0 | loop engine runtime 落地 |
| P1/P2 | 多 agent 角色化 + supervisor 编排 |
| P3/P4 | checkpoint-resume + 工具执行幂等 |
| P5-3/P5-4/P5-5 | 结构化子任务结果（`SubTaskOutcome`）+ `parent_run_id` 树形聚合 + resume 流式版 |
| P5-1/P5-2 | **2026-07-21 已交付**：schema 级工具白名单过滤（`AgentLoop._get_tools()`）+ `SubAgent` 可选 `window_reset` 参数 |
| sandbox 后端 | `execute_in_sandbox` 接 `CommandRunner` 抽象（`tools/sandbox.py`）：默认 Passthrough，可注入 `FirejailBackend`（仅 shell 子进程、Linux-only、非完美边界），经 `RuntimeSlot` 注入 |

### 2.10 迭代时间线（git log 提炼）

| 时间 | 里程碑 |
|------|--------|
| 2026-05-26 | baseline 规划冻结（epics/architecture/prd） |
| 2026-06-08 | 自学习闭环 Epic 6-10 分解 |
| 2026-06-19~20 | P0 provider 技术债收尾 + MCP Client 集成周期（Epic 11-13） |
| 2026-06-21 | `_bmad-output/` 按周期重组 + 去日期化 |
| 2026-06-23 | engine P0 loop engine runtime 落地 |
| 2026-06-25 | engine P1-P5 同日集中落地（多 agent 角色化 + checkpoint-resume + 结构化结果/树形聚合/resume 流式）+ 新增 `design.md`；`framework.md` 4.2 对齐 engine 集成 |
| 2026-06-26 | bmad-method 6.8.0 → 6.9.0；`framework.md` 补 loop engine |
| 2026-06-29 | engine / agent 源码补详细中文注释；`loop.py` 968→797 行拆分（零回归）；新增 GitHub Actions 质量门禁 + pre-commit 钩子；epic-13 retrospective 完成 |
| 2026-07-01 | 收敛工作区路径围栏为 `resolve_under_root` 单一算法；FR-3 收紧（MCP 运行时断连 ping-watch auto-unregister）；engine 健壮性四件套（ledger/store I/O 全套 async 化、缓存命中复核 policy、持久化原子写 + 损坏 JSON 容错、lease-active 命中跳过重复执行） |
| 2026-07-08 | engine sandbox 接真实后端：`execute_in_sandbox` 经 `CommandRunner` 抽象（`tools/sandbox.py`）+ `RuntimeSlot` 注入，默认 Passthrough、可注入 `FirejailBackend`（仅 shell 子进程、Linux-only、非完美边界） |
| 2026-07-09 | sandbox 健壮性 D1/D3/D4：取消执行时 kill+wait 子进程修 `CancelledError` 泄漏；`timeout` 正整数校验（raise 非 clamp，fail-closed 拦 None/str/float/bool/nan）；firejail 测试保真度（returncode per-instance）；engine sandbox 后端 code review 三处修复 |
| 2026-07-10 | sandbox reap 鲁棒性收尾：`CancelledError` 清理不吞取消信号（D-1，`suppress(BaseException)`+裸 raise）+ reap 保护 + `wait` 硬上界（`_REAP_WAIT_TIMEOUT`）+ kill/wait 解耦（item 1/2/3）+ kill 块 `except` 收窄 `Exception`（不吞 KeyboardInterrupt）；DP-4 第二半——MCP 返回内容注入启发式围栏（`mapping.bridge_result` 标记透传，非真正边界）；MCP `__aexit__` 关停硬上界（transport close 挂死兜底） |
| 2026-07-11 | deferred-work 剩余 LOW 项收尾；`_await_shutdown` 二轮 `wait` 收窄为 pending 子集；`CronScheduler.stop` 关停硬上界（task 挂死兜底，与 MCP `__aexit__` 同构）——**三处同构关停硬上界补齐**；docs 同步 DP-4 过时表述 |
| 2026-07-12 | bmad 根除 gds/bmb 残留（uninstall + install --modules core,bmm） |
| 2026-07-14 | `.env` 优先级反转：同 key 冲突 `.env` 胜出（`init > dotenv > env > secrets`），系统环境变量退居兜底（仅填充 `.env` 未声明的键） |
| 2026-07-16 | compressor 切分不产生孤儿 TOOL 消息；三项代码审查必修修复（`loop.py` ExitStack bind 异常 / `sandbox.py` kill 块 / `mapping.py` 注入模式描述）；新增 `docs/code-review-conclusion.md`、`docs/learning.md` |
| 2026-07-17 | MCP Client V2 周期启动（Epic 14-16）；`ToolAnnotations` 数据模型 + `mapping.py` 透传管线（14-1）；`file_read` 新增 `offset`/`limit` 行范围参数 |
| 2026-07-17 | 模板方法重构 `run`/`run_stream`（解耦异步/同步路径）；`PolicyEngine` annotations 感知写操作闸门（14-2：destructive→审批 / readOnly→放行 / 缺省→fail-safe）+ 零回归测试 + 安全声明同步（CLAUDE.md 标注 annotations 不可信）；`_bmad-output/` 旧版 sprint-status 清理；CLI 版本 banner |
| 2026-07-17 | **Resources 桥接工具（Story 15-1/15-2）**：`_sessions` 查找表 + `_get_session` + `_handle_list_resources` 聚合 JSON 桥 + `_register_bridge_tool`（`readOnlyHint=True`）+ `_server_loop` 异常路径 session cleanup —— 14 个新测试，31/31 manager 测试通过，**全线 586/586 通过** |
| 2026-07-20 | **Sandbox 硬化周期（profile 映射 / 降级 / 配置入口 / 进程组 kill / workspace 隔离）**——Epic S1-S4 全部 8 个 story 交付，新增 24 个 sandbox 专项测试，全量 751/751 通过 |
| 2026-07-21 | **Epic 19 完成**——覆盖率 89%→90%：新增 21 个专项测试覆盖 17 个模块，911 测试全绿，ruff 零错误。健壮性与质量硬化周期（Epic 18-19）全部交付。
| 2026-07-21 | **健壮性与质量硬化周期（Epic 18）**：跨进程文件锁（`persist.py` `lock=True` POSIX/Windows 平台自适应 + `EngineContainer.enable_file_locks`）+ Cron 范围表达式（`1-5`/`*/15`/`1-30/10`）+ `WinJobBackend`（Windows Job Objects 进程级隔离）+ 安全声明/文档同步——Epic 18 全部交付，新增 46 个专项测试（9 文件锁 + 27 cron + 10 WinJob），**全线 797/797 通过** |
| 2026-07-21 | **P5-1/P5-2 交付**：schema 级工具过滤 + SubAgent window_reset + CLI 阻塞缺口关闭（文档同步） |
| 2026-07-20 | **Resources 完成（Story 15-3/15-4）**：`guard_content` 提取为公共函数（供 `bridge_result`/`read_resource` 共用）+ `mcp__read_resource` 桥接工具 handler（`_handle_read_resource`，含 `server`/`uri` 参数 + `readOnlyHint`）+ 安全声明同步 + 配套测试（49 个 mapping + 46 个 manager 测试，**全线 607/607 通过**） |
| 2026-07-20 | **Prompts 桥接完成（Epic 16，Story 16-1~4）**：manager prompts 入口 + slash 命令调度 + 渲染守卫 + 测试——MCP V2 周期（Epic 14-16）全部 `done` |
| 2026-07-22 | **质量工程深化（Epic 21-24）**：coverage 工程化 + benchmark 重构 + Docker 硬化 + CI 效能/安全 + pre-commit 加固 + Ruff 扩展——全部 4 个 Epic、20 个 FR 交付，零业务代码改动，922 测试全绿 |
| 2026-07-22 | **全周期回顾完成**：`_bmad-output/retrospective-all-cycles.md` 覆盖全部 24 个已完成 Epic + S1-S4，所有 sprint-status 的 `epic-N-retrospective` 标记 `done` |
| 2026-07-23 | **GUI 终端界面周期启动**：BMad 规划冻结（brief→prd→architecture→epics），Epic 25-28 开始，流式聊天为当前焦点 |
| 2026-08-19 | **交互与可扩展层周期（Epic 29-35）全部交付**：审批闭环 / 会话恢复 / 斜杠命令 / Hooks / Plan Mode / 配置文件驱动角色 + 成本估算 / CLI 体验 + 技术债收尾——7 个 Epic、27 个 story、7 次提交，全量 1052 测试通过 |
| 2026-08-24 | **文件安全与凭证防护周期（Epic 36-39）全部交付**：凭证 deny（读+写）/ env scrubbing / 内部状态读 deny / 文档同步——4 个 Epic、7 个 story，全量 1135 测试通过 |
| 2026-09-14 | **工具调用可见性：CLI 显示「读写的文件 / 委派的子 Agent」**——新增 `tools/call_summary.py`（纯函数、零 heagent 依赖，该信息的唯一来源）；`StreamEvent` 新增 `tool_target`/`tool_error`/`tool_name`，`tool_call` 提前到执行前发出；CLI/TUI 渲染 `[calling file_read → …]`、失败另起 `[failed shell]`（成功不再逐条 `[done]`） |
| 2026-09-14 | **同日续作**：`EngineEvent.target` 提为独立字段（GUI 事件日志同步）；`AgentLoop.active_tool` 状态栏段（暂停/恢复可见卡在哪个工具）；`tool_activity` run 级台账 + 单次模式回显；CLI 提示行 shell 命令显示全文（`_NO_TRUNCATE_TOOLS`，只折叠空白不截断） |
| 2026-09-14 | **同日复核修复**：GUI 状态栏口径统一走 `call_summary.activity_label`、失败红叉归因 + 不可信文本 escape、`_TARGET_FIELDS` 死表项删除（参数化回归哨兵）、`resume` 展示态重置、GBK 控制台图标 ASCII 降级、修 `call_summary` 兜底分支测试假绿——93 个新测试，全量 1678 通过 |

### 2.11 交互与可扩展层周期 · Epic 29-35

来源 `_bmad-output/epics/epic-29-35-交互扩展周期/`（2026-08-19 启动并完成）。对照 Claude Code 补齐「面向使用者的交互与可扩展层」——审批、会话恢复、斜杠命令、Hooks、Plan Mode、自定义角色、成本追踪。全部复用既有基础设施（PolicyEngine / SessionStore / EventBus / RoleSpec / TokenUsage），`AgentLoop` 核心零侵入：

| Epic | 主题 | FR |
|------|------|----|
| 29 | 运行时审批闭环 | FR-A1~A5（`ApprovalHandler` 协议 + `APPROVAL_REQUIRED` 交互授权） |
| 30 | 会话恢复入口 | FR-B1~B3（`--continue`/`--resume`） |
| 31 | 斜杠命令系统 | FR-C1~C4（注册表 + 用户自定义命令） |
| 32 | Hooks 系统 | FR-D1~D4（PreToolUse/PostToolUse/SessionStart/End） |
| 33 | Plan Mode / 只读模式 | FR-E1~E4（readOnlyHint 白名单收敛） |
| 34 | 配置文件驱动角色 + 成本估算 | FR-F1~F4 |
| 35 | CLI 体验优化 + 技术债收尾 | FR-G1~G4（web_fetch guard_content / cron expr 诊断 / init --project / readline） |

详见 `_bmad-output/epics/epic-29-35-交互扩展周期/`（brief/prd/epics/retrospective）。

---

### 2.12 文件安全与凭证防护周期 · Epic 36-39

来源 `_bmad-output/epics/epic-36-39-文件安全防护周期/`（2026-08-24 启动并完成）。借鉴 hermes
`agent/file_safety.py` 的纵深防御设计，补齐凭证文件 deny（读 + 写）、凭证环境变量 scrubbing、
`.heagent/` 内部状态读 deny 三类防护：

| Epic | 主题 | FR |
|------|------|----|
| 36 | 凭证文件精确 deny（读 + 写） | FR-F1/F2 |
| 37 | 凭证环境变量 scrubbing | FR-F3 |
| 38 | `.heagent/` 内部状态读 deny | FR-F4 |
| 39 | 安全声明 + 文档同步 | FR-F5 |

详见 `_bmad-output/epics/epic-36-39-文件安全防护周期/`（brief/prd/architecture/epics/stories）。


---

## 3.3 架构沿革与参考来源

> 状态：历史索引；整理日期 2026-09-27，2026-11-04 自 `docs/architecture-history.md` 整体并入本节。维护责任：架构变更提交者。当前行为以 [framework.md](../framework.md) 和源码为准。

### 迁移记录

| 时间 | 变化 | 当前实现与证据 |
| --- | --- | --- |
| 2026-09 | persist、roles 从 engine 迁出 | `src/heagent/pub/persist.py`、`src/heagent/pub/roles.py`；共享底层能力 |
| 2026-09-17 | 集中 frontmatter 解析 | `src/heagent/pub/frontmatter.py`、`tests/test_architecture_contracts.py` |
| 2026-09-20 | workflow 资源模型和装载职责分离 | `engine/workflow_resource.py`、`goal/workflow_loader.py`，路径均相对于 `src/heagent/` |
| 2026-11-04 | WS 本地强制认证开关 `WS_LOCAL_AUTH_ENABLED`（Epic 56 D5 修订：回环主 listener 可选强制 Bearer token，含旁路端点，默认关） | `src/heagent/network/ws_host.py`（`WsServerConfig.local_auth` + `requires_auth` 派生）、`src/heagent/cli/http.py`（组合根接线 + 公告/告警三态）；判据 `tests/network/test_ws_auth.py`、`tests/network/test_ws_e2e.py`、`tests/network/test_ws_server.py`；安全口径见 [framework.md](../framework.md) §4.18 |

原始周期与验收证据见上文 §二 各周期与 [规划归档](../../_bmad-output/README.md)。本表是历史摘要，不是新一轮待办。

### 参考实现

[hermes-agent](https://github.com/NousResearch/hermes-agent.git)（NousResearch）——同源自学习 agent 架构（skills/facts/profile/soul 记忆、MCP、cron、多 provider 容错），设计与约定可作参考。注意 hermes 为**同步单文件巨型架构**（`run_agent.py`/`cli.py` 各逾万行、多平台 gateway/TUI），HeAgent 为**异步模块化单库**——**不可直接照搬**，须按 HeAgent 栈（Pydantic / asyncio / pytest-asyncio）改造适配；仅硬约束级条目进 `CLAUDE.md`，细节以本文件为准。（2026-09-17 自 CLAUDE.md「参考实现」节原样迁入，常驻改按需查阅。）

### path_safety 对 hermes 的借鉴

`tools/path_safety.py` 的凭证 deny 与内部状态读 deny 借鉴自 hermes `file_safety.py`（2026-08-24），见 [当前工具架构](../framework.md)。
