# HeAgent 项目架构与工作流程

> 状态：当前实现参考。历史来源与迁移索引见 [iteration/cycles.md §3.3 架构沿革](iteration/cycles.md)。维护责任：对应模块的变更提交者。

> 相关文档：总览与快速开始见 [`README.md`](../README.md)，设计目标见 [`design.md`](design.md)，文档导航见 [`文档索引`](README.md)，部署边界见 [`deploy/README.md`](../deploy/README.md)，协作约定见 [`AGENTS.md`](../AGENTS.md)。本文为**代码实现层面的架构参考**，以当前 `src/` 实现为准。

## 目录

- [一、项目定位](#一项目定位)
- [二、数据流](#二数据流)
- [三、模块依赖关系 (DAG)](#三模块依赖关系-dag)
- [四、核心模块（职责与边界）](#四核心模块职责与边界)
  - [4.1 CLI 入口 (`cli/console.py`)](#41-cli-入口-cliconsolepy)
  - [4.2 Agent 核心 (`agent/`)](#42-agent-核心-agent)
  - [4.3 Provider 层 (`providers/`)](#43-provider-层-providers)
  - [4.4 Tool 系统 (`tools/`)](#44-tool-系统-tools)
  - [4.5 上下文管理 (`context/`)](#45-上下文管理-context)
  - [4.6 记忆系统 (`memory/` + `skills/`)](#46-记忆系统-memory--skills)
  - [4.7 Cron 调度 (`cron/`)](#47-cron-调度-cron)
  - [4.8 共享类型 (`pub/types.py`)](#48-共享类型-pubtypespy)
  - [4.9 异常体系 (`pub/exceptions.py`)](#49-异常体系-pubexceptionspy)
  - [4.10 配置管理 (`config/` 包)](#410-配置管理-config-包)
  - [4.11 MCP 集成 (`tools/mcp/`)](#411-mcp-集成-toolsmcp)
  - [4.12 运行时引擎 (`engine/`)](#412-运行时引擎-engine)
  - [4.13 Goal 驱动工作流 (`/goal`)](#413-goal-驱动工作流-goal)
  - [4.13.1 受控 GoalScript（Story 51-7）](#4131-受控-goalscriptstory-51-7)
  - [4.13.2 状态迁移与中断语义矩阵（S-3）](#4132-状态迁移与中断语义矩阵s-3)
  - [4.14 技能资源读取 TOCTOU 评估与安全打开加固（Epic 46.1/46.2）](#414-技能资源读取-toctou-评估与安全打开加固epic-461462)
  - [4.15 事件契约 (`events/`)](#415-事件契约-events)
  - [4.16 HTTP 网页入口 (`network/http_*` + `cli/http.py` + `web/`)](#416-http-网页入口-networkhttp_--clihttppy--web)
  - [4.16.1 WebSocket 入口（Epic 54；Epic 56 迁至独立 server）](#4161-websocket-入口epic-54epic-56-迁至独立-server)
  - [4.17 网页控制台 (`pub/workspace.py` + `pub/projects.py` + `config/catalog/` + `config/write.py` + `cli/http.py` + `cli/dialogs.py` + `web/`)](#417-网页控制台-pubworkspacepy--pubprojectspy--configcatalog--configwritepy--clihttppy--clidialogspy--web)
  - [4.18 安全口径（canonical）](#418-安全口径canonical)
- [五、已知缺口](#五已知缺口)
- [六、目录与调用链](#六目录与调用链)
- [七、扩展页索引（`docs/frame/`）](#七扩展页索引docsframe)
- [八、技术规范](#八技术规范)
  - [8.1 目标工作流质量收口](#81-目标工作流质量收口)
  - [8.2 Goal/Epic/Story 产物契约](#82-goalepicstory-产物契约)
  - [8.3 声明式敏捷流程收口](#83-声明式敏捷流程收口)
  - [8.4 工程纪律条款](#84-工程纪律条款)
  - [8.5 台账与规划产物布局](#85-台账与规划产物布局)

## 一、项目定位

HeAgent 是一个**自学习 AI Agent 框架**——单进程异步 Python 库，编排 LLM ↔ 工具执行循环。所有 I/O 均为 `async/await`，CLI 通过 `asyncio.run()` 桥接入口。

---

## 二、数据流

```
用户输入
  │
  ▼
CLI (click) ──── 参数解析 + Provider 构建
  │
  ▼
AgentLoop.run(prompt)
  │
  ▼
┌──────────── Agent Loop 循环 ────────────┐
│                                          │
│  Middleware Pipeline (retry 等)           │
│       │                                  │
│       ▼                                  │
│  Provider.send(messages, tools)          │
│       │                                  │
│       ▼                                  │
│  ProviderResponse                        │
│       │                                  │
│       ├── 无 tool_calls → 返回文本答案    │
│       │                                  │
│       └── 有 tool_calls → 并行执行        │
│              │                           │
│              ▼                           │
│         PolicyEngine.evaluate() ── 准入/审批/沙箱裁决
│              │                           │
│              ▼                           │
│         ToolExecutor（按 verdict 分发）  │
│              │                           │
│              ▼                           │
│         SafetyGuard.check()  ── 拦截危险命令
│              │                           │
│              ▼                           │
│         asyncio.gather() 并行执行 handler│
│              │                           │
│         ToolResult[] → 追加到消息列表     │
│              │                           │
│         ContextCompressor（可选）         │
│              │                           │
│              └──→ 回到循环顶部            │
│                                          │
└──────────────────────────────────────────┘
  │
  ▼
最终文本答案 + Token 统计 → 输出给用户
```

> **流式路径**：`AgentLoop.run_stream()` 走相同的 Provider→Tool 循环，但文本经
> `provider.stream()` 逐块 yield 为 `StreamEvent`（`text` / `tool_call` / `tool_result` / `done`）。
> 多数 Provider 在流式模式不返回 `tool_calls`，命中 `finish_reason=tool_calls` 时回退 `send()`
> 重取该轮调用，再并行执行工具并继续流式下一轮。
>
> `tool_call` 事件在**执行之前**逐个发出（工具可能耗时数十秒，展示层需实时可见），
> 并携带 `tool_target`——该调用作用对象的单行摘要（读写的文件 / 命令 / URL / 子 Agent 角色），
> 由 `tools/call_summary.py` 统一产出；`tool_result` 事件携带 `tool_name` 与 `tool_error`
> 供失败归因（批次并发执行，结果按调用顺序返回）。
>

---

## 三、模块依赖关系 (DAG)

```
公共层 pub/（零 heagent 依赖）：exceptions · types · safe_logging · log_config · persist · frontmatter · roles · workspace · task_shutdown
配置面 config/（依赖 pub/）：__init__ = Settings · catalog/ = 来源求解（2026-11-11 拆为 9 子模块：models·groups·masking·guards·envscan·sources·classify·report，由包壳统一 re-export）· write = 受闸门写通道 · envfile = .env 保真读写 · user_settings = 用户级 setting.md（读/迁移/用户层源）

主脊：  providers ─┐
        tools ─────┼─→ engine ─→ agent ─→ 入口层（cli/ 包 · gui · goal/）
        context ───┘

旁支：  memory（依赖 tools/context/pub.persist；对 engine 仅 TYPE_CHECKING，实例由入口层注入）
        cron/expr.py（零 heagent 依赖的纯叶子，被 memory 与 cron/scheduler 共用）
        events（运行期仅依赖 pub.exceptions；engine 单向借用 events.protocol.error_kind_for）
        network/（传输叶子：仅 stdlib + pydantic + pub.safe_logging，被入口层单向使用，禁止伸手进运行栈）
        skills/（技能库域包：只依赖 tools.path_safety 一类叶子能力，不依赖 engine/memory、不反向依赖 agent/）
        web/（控制台静态投递面：HTML/CSS/JS 零 heagent 导入，契约测试钉死）
```

**依赖规则：**
- `agent/` 是顶层编排器，依赖所有其他模块
- `providers/` 和 `tools/` 互不依赖（唯一声明例外：`tools/builtins/web_search_engine.py → providers.retry` 复用容错分类判据，`test_architecture_contracts.py::test_tools_providers_edge_is_pinned_to_retry` 钉死唯一性）
- `pub/exceptions.py` 和 `pub/types.py` 是叶子模块，无内部依赖
- 新增 Provider 或 Tool **禁止**从 `agent/` 导入（**全仓无例外**：`builtins/subagent.py` 只持可注入委派回调，子 Agent 编排由 `agent/delegation.py` 提供、`AgentLoop._runtime_scope` 每 run 绑定；`tools/mcp/*` 同）
- **分层（2026-09-26 收敛）**：`pub/` 是**公共层**——收零 heagent 运行栈依赖的共用模块（exceptions/types/safe_logging/log_config/persist/frontmatter/roles/workspace/task_shutdown/event_lines），**任何层都可依赖它、它不依赖任何层**（`pub/__init__.py` 零 import）；`config/` 是其**上一层**的配置面（`__init__.py` 即 Settings 本体 + catalog 来源求解 + write 写通道 + envfile 保真读写 + user_settings 用户级 setting.md），只依赖 `pub/` 与 stdlib/pydantic。persist/roles 2026-09 自 `engine/` 迁出，消除下层模块反向依赖：`pub/persist.py` 供 engine/tools/context/memory/cron/goal/housekeeping 共用；`pub/roles.py` 供 engine.policy/agent.sub/tools.builtins.subagent/cli 共用；`pub/safe_logging.py`（零 heagent 依赖，2026-09-23）收敛日志卫生：`safe_log` 逐调用点容错 + `install_logging_fault_guard()` 进程级守卫 + `redact_secrets`/`redact_details` 启发式脱敏，`network/`（不得依赖 engine）与 engine/agent 共用同一实现；`pub/frontmatter.py`（零 heagent 依赖，2026-09-17）收敛原六处手写 `---` frontmatter 解析器（engine.artifacts / 时为 memory.skills 与 memory.skill_packages，现 skills 包 / goal.workflow_loader / slash / roles；skill_packages 原两处其一随工作流装配迁入 goal），严/宽两档 + 两个分隔符变体，架构契约断言正则不得漂移出该模块
- `memory/` 运行期**不依赖 `engine/`**（`memory/dream.py` 的 `EngineContainer` 仅 TYPE_CHECKING 引用，实例由入口层注入、无 `default()` 回退；契约断言见 `test_architecture_contracts.py` FORBIDDEN_RUNTIME_IMPORTS）
- `engine/` 是运行时治理层（policy/executor/store/ledger/observability + workflow 运行时模型），依赖 `pub.types`/`pub.exceptions` + `tools.call_summary`/`tools.sandbox`/`tools.path_safety`（container 另有 lazy `config` 导入）；工作流资源模型在 `engine/workflow_resource.py`（原 memory.skill_packages，2026-09-20 迁入）；被 `agent/` 依赖（`AgentLoop` 经 `EngineContainer` 注入）
- `events/` 是事件传输层（JSONL 对外契约），运行时**零 engine 依赖**（EngineEvent 仅 TYPE_CHECKING 引入）；反向地，`engine/` 运行期引用 `events.protocol` 的**纯函数单点** `error_kind_for`（Phase 5 C1 失败分类）——events.protocol 运行期仅依赖 `pub.exceptions`，该边无环且不引入 EngineEvent→RunEvent 的反向耦合（4.15）
- `cron/expr.py` 是**零 heagent 导入的纯叶子**（5-field cron 表达式解析：`cron_matches`/`parse_field` 等），被 `cron/scheduler`（包内）与 `memory/dream` 共用——类比 `heagent.pub.persist`（纯 util）。`memory → cron` 包级边仅指此纯叶子（做 cron 匹配），**不依赖 `cron.scheduler` 调度器**；`CronScheduler._matches` 已降为薄委托（`return cron_matches(...)`）。
- `network/` 是**入口传输层**（Epic 49–50）：只承载 HTTP 协议 / 路由 / 静态资源 / 连接与超时生命周期 / 暴露判定，运行期**不依赖运行栈**（`agent`/`engine`/`providers`/`tools`/`memory`/`skills`/`context`/`cron`/`events`）与任何配置面模块（`config`（整包：Settings/catalog/write/envfile）/`pub.projects`/`pub.workspace`——粒度必须细到模块，唯一例外是零依赖的 `pub.safe_logging`）、任何入口层模块（`cli` 包（含 `cli/wiring.py`）/`cli/goal`/`cli/http`/`gui`）；Provider 与 `AgentLoop` 的装配由入口层 `cli/http.py` 单向伸手（契约断言：`test_architecture_contracts.py` 的 FORBIDDEN_RUNTIME_IMPORTS["network"]）

---

## 四、核心模块（职责与边界）

本节只回答**每个模块是什么、边界在哪、哪些约束违反即架构错误**。逐模块的实现事实已按同一编号迁到
[`frame/`](frame/README.md)（编号不变，正文里「见 4.x」仍指对应扩展页）；安全立场统一见 §4.18，
模块的机制细节不再在此复述。

### 4.1 CLI 入口 (`cli/console.py`)

`heagent/cli/` 是入口层包：`__init__.py` **零 import**（入口脚本指向 `heagent.cli.console:main`），
Click 命令组与启动编排在 `console.py`，装配（provider→engine→AgentLoop、soul、上下文策略、事件 sink）
在 `composition.py`，单次/交互执行与斜杠命令族在 `interactive.py`，HTTP/WS 装配在 `http.py` /
`http_config.py` / `http_console.py`，`/goal` 命令族在 `goal/` 子包。

**约束**：子模块清单即契约（`tests/test_architecture_contracts.py::test_cli_package_layout_is_pinned`），
新增/改名要同步白名单与本页指向的扩展页；monkeypatch 缝按调用方分模块（`_run_prompt` / `_run_single`
在 `interactive`，`_build_loop` 在 `composition`），搬代码前先 grep 缝路径。

细节（子模块职责表 / 缝位置 / 功能表）→ [`frame/cli.md`](frame/cli.md#41-cli-入口-cliconsolepy) 4.1。

### 4.2 Agent 核心 (`agent/`)

`AgentLoop` 是顶层编排器：Provider → 工具执行 → 直到得到文本答案；流式（`run_stream`）、续跑
（`resume` / `resume_stream`）、协作式暂停（`pause` / `unpause`）同属一个循环体。`loop.py` 是 façade，
循环策略拆在 `run_lifecycle` / `stream_runtime` / `resume_runtime` / `context_runtime` / `message_ports`
（策略模块运行期不反向导入 loop）。工具执行链固定 `PolicyEngine.evaluate()` → `ToolExecutor` →
`SafetyGuard.check()` → handler，带 ledger 幂等 / 租约；子 Agent 委派回调由 `agent/delegation.py` 组装、
`_runtime_scope` 每次 run 绑定。

**约束**：新增 provider / tool **禁止**从 `agent/` 导入；系统提示词的注入顺序里**稳定块必须排在易变块之前**
（自动前缀缓存按字节匹配，易变块前置会让稳定内容每次吃全价输入）。

细节（状态与参数表 / 中间件 / 子 Agent / 注入顺序）→ [`frame/agent.md`](frame/agent.md#42-agent-核心-agent) 4.2。

### 4.3 Provider 层 (`providers/`)

`BaseProvider` 是 Protocol（`send` / `stream` / `get_metadata`）。实现有 OpenAI 兼容（含本地 Ollama）、
Anthropic，以及四层容错包装：重试中间件（内层）→ 多密钥轮换 → 跨类型回退链 → 运行时切换 / 路由
（外层；`SwitchableProvider` 以用户选择为起点，`RoutingProvider` 按请求特征主动选档）。装配规则在
`providers/composition.py`（原 `cli/wiring.py` 组合根），入口层只留呈现薄壳。

**约束**：`Settings` 仅 TYPE_CHECKING 引用（运行期零 config 依赖）；回退精度只对 `RATE_LIMITED` /
`AUTH_FAILED` / `TRANSIENT`，`NON_TRANSIENT` 立即抛出（换 provider 不会让坏请求变好）；路由池是声明式
配置（`ROUTING_POOLS`），改档位 / 角色 / 关键词只改配置。

细节（各 provider / 容错三层 / 路由判据）→ [`frame/providers.md`](frame/providers.md#43-provider-层-providers) 4.3。

### 4.4 Tool 系统 (`tools/`)

`@tool` 装饰器从签名 + 类型提示 + docstring 生成 `ToolSchema` 并注册进 `ToolRegistry` 单例；
`SafetyGuard`（工具名黑名单 + shell 命令模式）是执行链的最后一环，`ToolExecutor` 在它之前按 verdict 分发。
`tools/sandbox/` 是子进程执行抽象（Passthrough / WinJob / Firejail / Docker 四档，见 [`sandbox.md`](sandbox.md)）；
`tools/path_safety.py` 是文件工具围栏与凭证 deny 的**单一实现**；`call_summary` 是工具调用「作用对象」
摘要的唯一来源；`edits` 提供行尾保真 / diff 回执 / 落盘前快照。

**约束**：文件类工具的路径必须经 `path_safety`；`@tool` docstring 是**模型可见**的工具描述，保持英文；
新增工具放 `tools/builtins/` 并在 `builtins/__init__.py` 注册。

细节（内置工具清单 / 沙箱后端 / 路径围栏 / 编辑护栏）→ [`frame/tools.md`](frame/tools.md#44-tool-系统-tools) 4.4。

### 4.5 上下文管理 (`context/`)

上下文文件**分层发现**（仓库根 → cwd，同层 `CONTEXT.md` > `AGENTS.md` > `CLAUDE.md`，字节预算近端优先）；
Token 计量（真实 tokenizer + 在线校准）；两条**互斥**的上下文策略——`compressor` 原位摘要（默认）与
`window_reset` 整窗重置（阈值触发清窗重建 + `resume` 续跑）；旁路调用统一记账 `sidecall.send_accounted`；
会话持久化 `SessionStore`（`.heagent/sessions/`，跨进程锁 + 并发写合并）。

**约束**：`compressor` 与 `window_reset` 二选一（构造期断言）；会话 id 走白名单 + Windows 保留设备名拒绝；
摘要提示词单源（`STRUCTURED_SUMMARY_PROMPT`）。

细节（分层语义 / 校准 / 并发写判据）→ [`frame/context.md`](frame/context.md#45-上下文管理-context) 4.5。

### 4.6 记忆系统 (`memory/` + `skills/`)

四库（事实 `MEMORY.md` / 画像 `USER.md` / 人格 `SOUL.md` / 技能库）+ 离线巩固调度器 `DreamScheduler`。
事实是 append-only，注入侧有字节预算与自动归档（最旧前缀移入 `archive/MEMORY-archive.md`），语义合并由
`fact_compact` 在 dream 侧执行（默认关）；技能库是双根（全局先、项目兜底），`SKILL.md` 只承载触发面四键、
其余在 `meta.yaml`，运行时计数只回写 `meta.yaml`。

**约束**：`memory/` 运行期**不依赖** `engine/`（`EngineContainer` 仅 TYPE_CHECKING，实例由入口层注入）；
dream = 无人监督 + 联网 + 改持久记忆，边界地位见 §4.18。

细节（四库 / 技能库双根 / dream 调度与 misfire 口径）→ [`frame/memory.md`](frame/memory.md#46-记忆系统-memory) 4.6。

### 4.7 Cron 调度 (`cron/`)

#### jobs.py — 任务模型与持久化

| 组件 | 说明 |
|------|------|
| `CronJob` | Pydantic 模型（id, prompt, cron, recurring, created, last_run, enabled） |
| `JobStore` | `.heagent/cron/jobs.json` JSON 持久化，提供 CRUD + 工厂方法 |

#### scheduler.py — 后台调度器

| 组件 | 说明 |
|------|------|
| `CronScheduler` | asyncio 后台任务，每 `cron_tick_seconds` 秒检查到期任务 |
| 手写 cron 解析 | 5-field（分 时 日 月 星期），支持 `*`、`*/N`、范围 `1-5`、步进 `1-30/10`、逗号列表；实现在纯叶子 `cron/expr.py`（`cron_matches`），`scheduler.py` 的 `CronScheduler._matches` 为薄委托（`memory/dream` 经 `cron.expr` 共用，不 reach-through 调度器） |
| 构造函数注入 | provider + stores，执行时创建独立 AgentLoop |

一次性任务（`recurring=False`）成功后自动删除。投递语义（misfire 口径）与 dream 共用同一口径，见 §4.6 dream「触发投递语义」。

### 4.8 共享类型 (`pub/types.py`)

所有模块间数据流通过 Pydantic 模型传递，**禁止**跨模块传递原始 dict。

| 类型 | 用途 |
|------|------|
| `Role` | 枚举：USER / ASSISTANT / SYSTEM / TOOL |
| `Message` | 对话消息（role, content, tool_calls, tool_call_id） |
| `ToolCall` | LLM 发起的工具调用请求（id, name, arguments） |
| `ToolResult` | 工具执行结果（tool_call_id, content, is_error） |
| `ToolSchema` | 工具的 JSON Schema 描述（name, description, parameters） |
| `ProviderResponse` | Provider 返回（content, tool_calls, usage, model） |
| `TokenUsage` | Token 使用量（prompt, completion, total） |

### 4.9 异常体系 (`pub/exceptions.py`)

```
HeAgentError (base)
  ├── ProviderError      — API 调用失败（Auth / RateLimit / Timeout / ResponseFormat）
  ├── ToolError          — 工具执行失败（Argument / Execution / Unknown / SafetyViolation / McpSdkMissing）
  ├── EngineError        — 运行时治理（PolicyViolation / PolicyExecution / Ledger / WorkflowExecution / FactCompactConflict）
  ├── AgentError         — 循环与子 Agent（BudgetExceeded → IterationLimit / SubAgent / AgentResume）
  ├── SessionError       — 会话持久化（Conflict / NotFound / Unreadable）
  └── ConfigurationError — 配置与输入校验（InputValidationError）
```

**禁止**抛出裸 `Exception`。

**入口兜底口径（A72）**：入口层不写 `except HeAgentError`，而是 `except ERROR_FAMILIES`
（= 上述 6 个直接子类的显式元组，同一模块导出）。新增直接子类必须登记进 `ERROR_FAMILIES`，
否则 `tests/test_exception_families.py` 红——新错误族要被显式接纳，而不是被根类静默吞成一行；
该测试同时守卫 `cli/` 下不再出现裸 `except HeAgentError`。

### 4.10 配置管理 (`config/` 包)

`Settings`（pydantic-settings）四层来源：系统环境变量 > 项目 `.env` > 用户 `~/.heagent/setting.md` > 字段默认值；
`config/catalog/` 是来源求解子包（`heagent.config.catalog` 是对外唯一入口，子模块是内部实现），`write.py` 是
受闸门写通道，`envfile` 负责 `.env` 保真读写，`user_settings` 读用户级 `setting.md`。运行配置在装配期解析一次成
冻结快照 `ResolvedRuntimeConfig`（每字段带来源），engine 与主 / cron loop 共用，运行中全局 `Settings` 漂移不影响
已创建的运行。

**约束**：业务方法禁止隐式 `get_settings()`（构造期回退与无 run 绑定的工具路径除外）；逐键默认值不与代码
对抄——`config/__init__.py` 字段与 `.env.example` 是唯一事实面。

细节（四层来源 / 快照语义 / 逐键默认值与说明）→ [`frame/config.md`](frame/config.md#410-配置管理-config-包) 4.10。

### 4.11 MCP 集成 (`tools/mcp/`)

`.mcp.json` 声明 → 连接 → 工具发现并注册进 `ToolRegistry`（退出时注销）；`MCPClientManager` 是生命周期
façade，单 server 失败隔离。`mcp` 是可选 extra（`pip install "heagent[mcp]"`），SDK 的唯一导入通道是
`sdk.import_mcp()`（缺包抛 `McpSdkMissingError`，不让 `import heagent` 炸）。

**约束**：MCP 工具与内置工具同等不可信（执行前拦截 + 返回内容启发式围栏）；stdio 子进程在容器档经同一镜像
容器拉起，后端不可用时**显性降级**并每次 WARNING。

细节（模块分工 / stdio 沙箱）→ [`frame/tools.md`](frame/tools.md#411-mcp-集成-toolsmcp) 4.11。

### 4.12 运行时引擎 (`engine/`)

`EngineContainer` 是 DI 容器，向 `AgentLoop` 注入运行期服务：`PolicyEngine`（准入 / 路径围栏 / 审批与沙箱裁决）、
`ToolExecutor`（按 verdict 分发，内部串行 `SafetyGuard.check()`）、`RunContext` / `RunStore`（单次运行上下文与
快照）、`ExecutionLedger`（幂等与租约）、`EventBus` / `LoggingObserver`（运行时事件），以及 workflow 运行时模型
（`workflow_runner` / `workflow_transition` / `checkpoint` / `state_machine`）。

**约束**：工具执行链固定 `PolicyEngine.evaluate()` → `ToolExecutor` → `SafetyGuard.check()` → handler；
workflow 状态写入唯一经 `workflow_transition._TRANSITIONS`（两条 AST 判据钉住）；`engine/` 运行期只借
`events.protocol` 的纯函数 `error_kind_for`，不反向依赖 events 模型。

细节（模块表 / 持久化健壮性 / 日志卫生）→ [`frame/engine.md`](frame/engine.md#412-运行时引擎-engine) 4.12。

### 4.13 Goal 驱动工作流 (`/goal`)

声明式工作流由 `.heagent/skills/he-goal/workflow.md` 定义。**确定性内核与渲染分离**：校验、gate 装配、故事选择、
checkpoint 恢复与推进 use-case 在 `goal/application.py` + `goal/workflow_support.py`（两者 click-free），
`cli/goal/` 只是渲染薄壳 + 测试缝；CLI / GUI / cron 三入口收敛同一 use-case。跨进程互斥在
`goal/mutex.goal_mutex()`（进程内锁 + `.heagent/goal.lock`），**变更内核自持锁**。声明门控并行（Epic 52）是
「授权 + 每次重新推导」——批成员不持久化，写集围栏是纵深防御（post-hoc Git 审计 + 单向撤销闩），不是安全边界。
目标状态唯一写入口是 `engine/workflow_transition.py` 的 `_TRANSITIONS`（见 §4.13.2）。

细节（命令族 / 审批与决策记录 / 并行与写集围栏 / 产物分组）→ [`frame/goal.md`](frame/goal.md#413-goal-驱动工作流-goal) 4.13。

### 4.13.1 受控 GoalScript（Story 51-7）

步骤 frontmatter 可声明 `executor_mode: script` + `script_resource`：脚本是**包内资源**（内容完整性凭据同技能包），
入口固定 `build_workflow(goal)`，加载期用 AST 拒绝 import / while / 多余函数 / 私有属性与 `open`/`eval`/`exec` 类能力，
运行期只经 `GoalScript` facade 的七个操作发 Pydantic 请求 / 响应，状态变更仍归 `WorkflowRunner`（两阶段提交）。

**⚠ 边界地位见 §4.18**：脚本在**宿主解释器**内执行，约束只是「形态 + 资源 + 请求面」，用于可信本地包的误用防控，
不承载不可信输入；第三方 workflow 包必须先有 OS 级隔离。

细节（加载期校验 / facade / 两阶段提交 / 有界执行）→ [`frame/goal.md`](frame/goal.md#4131-受控-goalscriptstory-51-7) 4.13.1。

### 4.13.2 状态迁移与中断语义矩阵（S-3）

**状态迁移与中断语义矩阵（S-3，2026-10-26）**。`src/heagent/engine/workflow_transition.py` 的
`_TRANSITIONS` 是**唯一**迁移表，任何状态赋值都必须经它（`tests/test_architecture_contracts.py` 有两条
AST 判据钉住：写点必须走 `transition()`，且唯一写点 `_transition_fields` 必须同时写状态与驱动事件）。
下表把「事件 → 原因 → 落点」固化成可核对的形式：事件列取值集合必须与 `WorkflowEvent` 完全一致
（缺一个或写错一个都会被 `tests/test_workflow_transition_reason.py::test_interrupt_matrix_covers_vocabulary` 打红），
中断语义只固化 **A39（2026-10-23）已裁定**的口径，本表不新增裁决。

<!-- S-3:transition-matrix:start -->

| 状态 | 事件 | 原因 | 下一步 | 代码锚点 |
|---|---|---|---|---|
| `PENDING` | `start` | 步骤开始执行 | → `RUNNING` | `src/heagent/engine/workflow_transition.py:11` |
| `PENDING` | `input_missing` | 必需输入缺失，无法开工 | → `BLOCKED` | `src/heagent/engine/workflow_transition.py:11` |
| `PENDING` · `RUNNING` | `user_pause` | 用户主动暂停（`/goal pause`） | → `WAITING_USER` | `src/heagent/engine/state_machine.py:311` |
| `RUNNING` | `step_completed` | 普通步骤完成且仍有后续步骤 | → `PENDING` | `src/heagent/engine/state_machine.py:248` |
| `RUNNING` | `final_step_completed` | 末步完成 | → `COMPLETED` | `src/heagent/engine/state_machine.py:248` |
| `RUNNING` | `checkpoint_required` | 该步声明了 checkpoint，需人工确认后继续 | → `WAITING_USER` | `src/heagent/engine/state_machine.py:248` |
| `RUNNING` | `approval_required` | 该步声明 `approval: required`，完成簿记延后 | → `WAITING_USER` | `src/heagent/engine/state_machine.py:228` |
| `RUNNING` | `gate_failed` | 步骤完成门求值未通过 | → `BLOCKED` | `src/heagent/engine/workflow_transition.py:11` |
| `RUNNING` | `executor_failed` | 执行器/回调抛非取消异常（见中断语义表） | → `FAILED` | `src/heagent/engine/workflow_runner.py:589` |
| `RUNNING` | `cancelled` | 用户取消（见中断语义表，可恢复） | → `PENDING` | `src/heagent/engine/workflow_runner.py:589` |
| `WAITING_USER` | `user_resume` | 用户回复并恢复执行（**不等于批准**）；`BLOCKED` / `FAILED` 恢复同此事件 | → `PENDING` | `src/heagent/engine/workflow_transition.py:11` |
| `WAITING_USER` | `user_approve` | 人工批准：唯一把该步标记完成的路径 | → `RUNNING` | `src/heagent/engine/state_machine.py:331` |
| `WAITING_USER` | `user_reject` | 人工驳回：步骤未完成，修订后 `resume` 重跑 | → `BLOCKED` | `src/heagent/engine/state_machine.py:338` |
| `WAITING_USER` | `user_amend` | 带补充重跑，补充同时进需求文档「用户补充」段 | → `PENDING` | `src/heagent/engine/state_machine.py:338` |

**中断语义（A39，2026-10-23 裁定，本表只固化不重裁）**：

| 异常类型 | 事件 | 落状态 | 可恢复 | 代码锚点 |
|---|---|---|---|---|
| `asyncio.CancelledError` | `cancelled` | `PENDING` | 是（`resume`） | `src/heagent/engine/workflow_runner.py:589` |
| `KeyboardInterrupt` | `cancelled` | `PENDING` | 是（`resume`） | `src/heagent/engine/workflow_runner.py:589` |
| `SystemExit` | `cancelled` | `PENDING` | 是（`resume`） | `src/heagent/engine/workflow_runner.py:589` |
| 其余 `BaseException` | `executor_failed` | `FAILED` | 是（`resume`） | `src/heagent/engine/workflow_runner.py:589` |

<!-- S-3:transition-matrix:end -->

### 4.14 技能资源读取 TOCTOU 评估与安全打开加固（Epic 46.1/46.2）

技能资源读取收敛为 `tools/path_safety.open_text_under_root` **单一入口**（解析 → 加固打开 → `fstat` 常规文件校验），
并有 `manifest.json` / `manifest.lock` 两级内容完整性凭据（漂移即 fail-loud）。**如实声明**：这是
defense-in-depth 层——Windows 无 `dir_fd`、组件之间仍有时间差，残余竞态窗口未消除，边界地位见 §4.18。

细节（加固通道 / 凭据语义 / 残余面 / 判据）→ [`frame/tools.md`](frame/tools.md#414-技能资源读取-toctou-评估与安全打开加固epic-461462) 4.14。

### 4.15 事件契约 (`events/`)

`RunEvent` JSONL 是对外机器可读契约：字段集由 `SCHEMA_VERSION` 锚定 + 黄金测试锁死；`kind` 是**开集**
（`KNOWN_KINDS` 只作文档与测试依据，不作过滤）。`events/` 只做「映射 + 序列化 + 落盘」，不重复插桩。
事件分**两域一约定**：运行事实域（`RunEvent` / rollout，持久、append-only 可回放）与进程观察域
（`EventBus`，易失、有界缓冲、丢失即丢失）；观察者异常逐个隔离，不向发布方传播。

**约束**：改字段须 bump `SCHEMA_VERSION` 并同步黄金测试；`target` / `details` 携带工具原始输出，
与工具返回**同等不可信**；rollout 属项目内部状态，不得改写到可提交路径。

细节（11 字段表 / 逐 kind 发射点与 details 约定 / sink 与分发语义）→ [`frame/events.md`](frame/events.md#415-事件契约-events) 4.15。

### 4.16 HTTP 网页入口 (`network/http_*` + `cli/http.py` + `web/`)

HTTP/SSE 入口的实现事实（协议、就绪门禁、限额与超时、状态 API 等）见 [frame/network.md](frame/network.md#416-http-网页入口-networkhttp_--clihttppy--web)。

### 4.16.1 WebSocket 入口（Epic 54；Epic 56 迁至独立 server）

WebSocket 入口（四端点、帧契约、三档监听模式、认证与 TLS、CLI 旁路、通知流）见 [frame/network.md](frame/network.md#4161-websocket-入口epic-54epic-56-迁至独立-server)。

### 4.17 网页控制台 (`pub/workspace.py` + `pub/projects.py` + `config/catalog/` + `config/write.py` + `cli/http.py` + `cli/dialogs.py` + `web/`)

网页控制台（工作区、项目注册表、配置写入通道、原生目录选择）见 [frame/network.md](frame/network.md#417-网页控制台-pubworkspacepy--pubprojectspy--configcatalog--configwritepy--clihttppy--clidialogspy--web)。

### 4.18 安全口径（canonical）

> **本节是安全口径的唯一真源**：本文件其它章节、`AGENTS.md`（派生副本）与各周期产物只引用不复述，
> 表述不一致时以本节为准。本节只裁定「是不是边界」；校验点、限额、默认值等机制细节留在各自章节，
> 缺口正文留在「五、已知缺口」与 `_bmad-output/open-items.md`（「活动（未闭合）条目」节）
> （活动项唯一真源；闭合/归档历史见 `_bmad-output/retrospective-all-cycles.md` §三）。

1. **三层非边界**：`SafetyGuard` / `PolicyEngine` / sandbox 后端**均非真正安全边界**——它们是
   defense-in-depth 的标记与拦截层（机制见 4.4 `safety.py` / `path_safety.py`、4.12 `policy.py`）。
2. **OS 级沙箱兜底立场**：shell 路径的 OS 级兜底实施项是容器档 Docker 后端（Epic 53 期一，2026-10-21），
   **默认链路未启用**（须显式 `--sandbox docker` / env 选择），**启用也非绝对边界**（宿主内核 / Docker
   daemon 逃逸面仍在）；MCP stdio 子进程**同一容器兜底已实施**（Epic 53 期二 53-5，2026-11-03：`--sandbox docker`
   且 daemon 可用时经同一镜像容器拉起，`--network=none` 默认；后端不可用时**显性降级**为宿主执行并**每次** WARNING，
   绝不静默假装已隔离）。
3. **本地模式口径**（listener 绑回环，默认）：HTTP+SSE（9101）与 WS（9201）**都无认证、无 TLS**；
   **回环绑定不等于可信**（回环客户端同样不可信）；`Origin` / `Host` 校验只是**入口层 defense-in-depth**，不是认证。
   **2026-11-04 D5 修订**：WS listener 可经 `WS_LOCAL_AUTH_ENABLED=true` **也**强制 Bearer token（默认关）——
   开启时前门由 Origin/Host 换成 token，旁路 `/api/cli/ws` 一并强制（不再免认证）；HTTP 无对外模式、不在本修订范围。
   内网免认证档（`lan`，见要素 4）**同样无认证、无 TLS**：绑定地址是私有 IP **不等于**同网段可信。
4. **非回环绑定分两档，生产形态是 `wss` + token**（WS listener 绑非回环地址）：
   - **`external`（默认档，未开 `WS_LAN_NO_AUTH`）**：**强制** `Authorization: Bearer <token>`，缺 token
     **拒绝启动**（fail-closed，绝不降级成无认证对外）；`WS_TLS_CERT_FILE` + `WS_TLS_KEY_FILE` 配齐即
     `wss`（Epic 73 第二步），此时「加密 + token」才是完整生产形态。认证**不是绝对边界**（token 可泄露），
     加密也不是（客户端信任锚是服务端身份公钥的 **SPKI-SHA256 pin**，由 `heagent tls fingerprint` 给出；
     重签叶证书复用身份密钥 ⇒ pin 不变，`heagent tls rotate-key` 是**唯一**改变 pin 的动作）；
     浏览器 WebSocket API 无法自定义请求头 ⇒ 该档**不适用**于浏览器页面。
   - **`lan`（内网调试入口，须显式 `WS_LAN_NO_AUTH=true`）**：**无认证、无 TLS**，只接受**私有地址
     字面量**（通配 `0.0.0.0` / 公网地址 / 主机名一律拒绝启动），身份是同一局域网内的调试入口——同网段
     任何设备都能驱使代理（执行命令、读写文件），只能靠网络侧兜底（不映射公网、不长期监听），每次启动
     一条 WARNING。它与 TLS **互斥**：`wss` + `WS_LAN_NO_AUTH=true` **拒绝启动**（加密了却不认证毫无意义）。
     台阶明确：这是**显式选择的安全放宽**，不是默认，也不构成边界。
5. **端点可见性**：**HTTP listener 没有对外模式**（恒按本地模式口径对待，不得绑公网）；终端旁路
   `/api/cli/ws` **只**挂回环（`local`）listener（`lan` / `external` 恒不注册——旁路含终端里尚未提交的输入）；
   只读通知流 `/api/notifications/ws`（Epic 58）随 listener 注册，`lan` 与 `external` 上同样可见
   （`external` 在 token 之后；`lan` 上无认证，同网段即可订阅）——但**仅当** `CRON_PUSH_ENABLED=true`
   建起中枢时注册；关闭（默认）则路由不存在，客户端拿裸 403。
6. **已知缺口与台账指针**：活动缺口清单落 `_bmad-output/open-items.md`（「活动（未闭合）条目」节）
   （闭合/归档历史见 `_bmad-output/retrospective-all-cycles.md` §三）与本文件「五、已知缺口」，**本节不复述**；
   本节只裁定边界地位，**不宣告任何缺口已闭合**。

## 五、已知缺口

| 缺口 | 说明 |
|------|------|
| 流式 tool_calls 回退 | `run_stream()` 流式模式不返回 `tool_calls`，命中时回退 `send()` 重取（已知设计权衡） |
| MCP / engine sandbox 安全边界 | 三层非边界与 OS 级兜底立场见 §4.18；本行的缺口事实是 shell 路径的兜底实施项 = container 档 Docker 后端（Epic 53 期一，2026-10-21；**默认链路未启用**，须显式 --sandbox docker / env 选择） |
| MCP stdio 子进程不经沙箱——**已闭合**（Epic 53 期二 53-5，2026-11-03；2026-09-27 的「裁定 (c) 不做」被 2026-10-21 起的容器档兜底推翻） | 实施：`SANDBOX_BACKEND=docker` 时 `cli/console.py::_stdio_sandbox_spec` 产出 `StdioSandboxSpec`，`MCPClientManager(stdio_sandbox=…)` → `default_transport_opener` → `tools/mcp/stdio_sandbox.py::stdio_params` 把 SDK 的 stdio 子进程换成 **docker CLI**：`docker run -i --rm --pull=never --cap-drop=ALL --security-opt no-new-privileges --user sandbox --network <none|bridge> <image> <server-cmd> …`，容器内进程的 stdin/stdout 即 JSON-RPC 管道（长命双向，不经 `CommandRunner` 的 `sh -c` 短命形状）。env 只对 `.mcp.json` 显式声明的键发 `-e KEY`（不带值，值不进 argv），宿主其它变量不进容器。**降级**：daemon 不可用 / CLI 缺席 / 探测抛错 ⇒ 显性降级回宿主执行，**每次**连接打 WARNING（判据 `tests/test_mcp_stdio_sandbox.py`）。残留：镜像里没有的二进制（典型 `npx`）会显性失败——属预期，镜像供给是配置面职责；边界地位仍见 §4.18（容器档非绝对边界）。历史裁定正文见 `_bmad-output/epics/epic-S1-S4-沙箱硬化周期/deferred-work.md`（Z-D24） |
| 用户可配置 MCP 签名入口 | **两级都生效**（2026-11-18 起，活动台账 A36 闭合）：项目级 `.heagent/injection_signatures.json` + 全局级 `<用户 home>/.heagent/injection_signatures.json`，两级均在进程内缓存一次（改文件需重启进程）；合并语义 = 全局作底、**同名 `pattern` 由项目级覆盖**，条目校验逐条报错并**带来源**（global / project），缺文件是合法空载。判据 `tests/test_mcp_mapping.py`（加载 / 覆盖 / 缺失零噪声 / 来源归因四例）+ 变异 3/3 全红（`scripts/mutation/mutate_mcp_signature_hint.py`）；签名围栏的边界地位见 §4.18 |
| 凭证 deny 项目级配置入口 | `.heagent/path_deny.json`（2026-09-17）允许收紧（追加 deny 项）或放行显式列举项（精确路径 / basename 豁免；内部状态目录 deny 不接受豁免），无整体关闭入口、fail-safe 默认仍拒；边界地位见 §4.18 |
| Web 工具注入围栏 | `web_fetch` / `web_search` 返回路径已接 `guard_content`（机制出自 Epic 35，2026-08-19：命中内置注入签名即加 warning 标记透传，不阻断），与 MCP `bridge_result` 同语义；标记仅 observable defense-in-depth（边界地位见 §4.18），dreamer 的兜底要求见 4.6 dream.py |
| 交互式审批非安全边界 | 审批闭环（Epic 29）把「要不要执行」交给用户，边界地位见 §4.18（见 4.12 approval.py） |
| 文件安全与凭证防护非边界 | path_safety 凭证 deny / scrub_sensitive_env 均为 defense-in-depth 启发式层（2026-08-24），边界地位见 §4.18 |
| 沙箱会话目录非安全边界 | `sandbox_session_workspace`（FR-1，2026-08-26）只提供 per-run 目录约定：WinJob 仅把目录作为子进程 cwd（**零文件系统/网络隔离**），Firejail `--private` 亦无完整隔离——边界地位见 §4.18（机制见 `docs/sandbox.md`） |
| 沙箱后端分级 | `SandboxTier`（FR-2，2026-08-26）container 档首个实现后端 `DockerRunner` 已落地（Epic 53 期一，2026-10-21；仅 shell 路径、默认链路未启用）；审批降级（`can_relax_approval`）已于 Epic 53 期二（Story 53-4，2026-11-03）接入 `PolicyEngine`，仅当「真进沙箱 + 容器档 + 后端可用」时放松、弱后端一律维持原审批要求——分级的边界地位见 §4.18 |
| 沙箱 env 豁免非安全边界 | `sandbox_env_allowlist`（FR-3，2026-08-26）仅豁免 `scrub_sensitive_env` 剥离，边界地位见 §4.18 |
| SandboxSession 非安全边界 | SandboxSession（FR-4，2026-08-26）会话 cwd 保持仅「cd 前缀 + 尾捕获」约定，WinJob 无 FS 隔离、Firejail 无完整隔离——边界地位见 §4.18；crash 孤儿目录 GC/保留策略已于 2026-09-15（E40-D1）交付（housekeeping.prune_sandbox_dirs + sandbox_dir_retention_days） |
| WebSocket 入口非安全边界（Epic 54 / Epic 56 / Epic 58） | 四条 WS 端点（提交 /api/runs/ws、订阅 /api/runs/{run_id}/ws、旁路 /api/cli/ws、通知流 /api/notifications/ws）的边界地位见 §4.18（要素 3–5）。本行的缺口事实：对外模式的凭证机制是静态 token（只读用户级 ~/.heagent/setting.md）+ 握手前常量时间比较 + 按来源失败限速，且只走握手头 ⇒ 不支持浏览器直连；**对外能提交 run ⇒ 容器沙箱档（--sandbox docker）从建议升级为强烈建议**（仍默认未启用） |
| HTTP 入口不接 MCP | 网页入口**不连接** `.mcp.json` 声明的 server（入口层隔离第三方代码的既有决策）：入口的边界地位见 §4.18，自动拉起第三方 stdio 子进程 / 连远端端点等于把触达面暴露给任何能连上端口的人 |
| HTTP 会话/事件无持久化（2026-11-18 A35 部分改判） | 网页入口的会话投影、运行记录与 SSE 事件缓冲都是**进程内状态**：进程退出即丢；事件缓冲按 `HTTP_EVENT_BUFFER_SIZE` 有界，越过窗口的重连只能得到 `resync_required` 并改拉 `/api/session` 快照。**读侧已补**：`EVENTS_ROLLOUT_ENABLED=true` 时旧 run 的 `GET /api/runs/<id>/events` 从 `<项目根>/.heagent/runs/<id>/rollout.jsonl` **一次性回放**（粗粒度：工具输出未落盘 ⇒ 标注、文本增量未落盘 ⇒ 以一条 `done` 交付完整答案；响应头 `x-heagent-replay: rollout`；进程内仍有记录时以内存为准），未开 rollout 或文件缺失仍 404。写侧（在途 run 跨进程续跑、事件缓冲持久化）仍不做 |
| 日志行的凭证脱敏（**启发式，非边界**；2026-09-23 交付） | `LoggingObserver` 打印前对 `target`/`details` 掩码：键值（`API_KEY=…`/`token: …`）、CLI 旗标、厂商前缀（`sk-`/`ghp_`/`AKIA`/`AIza`/JWT）、`Bearer`、URL userinfo，以及**凭证命名的键**（短值无形状可认）。**肯定漏网**：模式匹配非完备，`shell` target 仍不截断（审查需要原文），且 `logs/`、`.heagent/runs/`（快照/rollout）按设计保存完整 prompt 与消息——边界地位与兜底要求见 §4.18；另遵守「不要把凭证写进命令或路径」 |
| 控制台「回环来源」不等于安全（**评审 F9**，2026-09-24） | 写通道 / 项目登记 / 项目移除要求**回环来源**（`_loopback_error`），该闸门的边界地位见 §4.18（要素 3）；本行的缺口事实是跨站写入的实际防线只有 [frame/network.md](frame/network.md) 4.16 的 `Origin` / `Host` 校验（AD-6）。文档不得把回环门写成信任依据 |
| 控制台「只读」不是安全边界 | 面板上的「只读 / 只读原因」是**用户体验标记**（`classify()` 的划分），不是访问控制：白名单之外的键照样能被任何能改 `.env` 的进程改动（边界地位见 §4.18）。写通道的 fail-closed 校验同样只作用于这条通道 |
| 配置改动无热生效（**有意**） | 写成功后只丢该项目运行时缓存 ⇒ **下一次 run** 才用新值，在途 run 继续用旧快照（响应 `applied=next_run`）。没有「立即生效」通道；要即时生效只能新起一次 run |
| 用户层 `~/.heagent/setting.md` 永久只读 | 写入通道**只写项目 `.env`**（I4）；用户层那份（`heagent init` 生成 / 旧 `.env` 一次性迁移、对所有项目生效）只能手工编辑，网页改不到 |
| 备份与审计仍在宿主文件系统上 | 两者都在项目状态根内、已进内部状态读拒集合（工具读不到、也无任何网页下载端点），但**没有加密**：备份是写入前的**原样配置**（可能含凭证），审计含键名与值的哈希。兜底要求见 §4.18（另需磁盘权限） |
| 跨项目并发默认无全局上限（**D9 已裁定**） | 默认（`HTTP_MAX_TOTAL_INFLIGHT=0`）在途上限 = 项目数 × `HTTP_MAX_INFLIGHT_RUNS`（默认最多 32），**无全局软上限**；`HTTP_MAX_CONNECTIONS` 不随项目数放大 ⇒ 多项目并行时连接层可能先成为瓶颈（既有限制面的延续）。多项目并行是有意能力，见 [frame/network.md](frame/network.md) 4.17。**2026-09-27 起**可选设 `HTTP_MAX_TOTAL_INFLIGHT=N` 得到**服务级**总额（跨项目共享，超限 409 `total_inflight_limit`）；它**不改写**上面这条按项目语义，只是叠加一层 |
| 非回环运行姿态（**裁定：维持现状**） | 项目**重命名**、四个**会话**写操作与项目内**运行入口**当前**没有**回环门（登记 / 移除 / 配置写入有）。**裁定维持现状**理由：① 这是 Epic 49 的设计姿态，Epic 50 未扩大暴露面；② 入口的边界地位见 §4.18；③ 添加回环门会破坏既有端点契约。冻结边界：不得把闸门表述为安全边界 |
| 控制台 UI 无自动化回归 | `tests/fixtures/js/console_acceptance.mjs` 需要真实浏览器（CDP）与 `heagent[http]`，而 CI 侧没有任何浏览器（workflow 里没有 node / 浏览器步骤，依赖也不含 playwright/puppeteer；install 步骤只装 `.[dev,gui,http]`（lint job）与 `.[dev,http]`（test / coverage / benchmark / goal-smoke）） ⇒ 只能**手动**跑（清单见 `epics/epic-50-网页控制台周期/reviews.md`）。CI 里跑得动的是 node 探针（最小 DOM 替身）；DOM API 的 `click()` 会绕过命中测试，故「真浏览器」这一步不可省略。**裁定：保持手动**（2026-09-28）——冻结边界禁止为它给 dev 依赖加 playwright/puppeteer；「真实模型 → SSE → 流式渲染」这条链的前端侧由 node 探针覆盖、服务端由 Epic 49 用例覆盖，本机无可用 provider 时不升级为门禁 |
| `cli_console.py` 从未落地（脊柱 D7 的覆盖率口径作废） | 脊柱 §10 / D7 预判控制台逻辑会拆到独立模块 `cli_console.py` 并「默认不 omit」；实现期它**没有存在过**——控制台装配在 `cli/http.py`（**不在**覆盖率 omit 列表里，靠测试覆盖，实测 `cli/http.py` 计入总量）。若将来拆分，口径随模块走并在此更新。**2026-09-26 补充**：交互式 CLI 主体现位于 `cli/console.py`（原 `cli.py`）+ `cli/interactive.py`（REPL 与斜杠命令族，自 cli.py 拆出），与 `cli/goal/` 子包、`cli/display.py` 一并列入覆盖率 omit（`pyproject.toml`）；`cli/composition.py`（装配）、`cli/init.py`、`cli/http.py`、`cli/http_console.py`、`cli/dialogs.py` 仍计入总量（实测 `http.py` 83% / `http_console.py` 93% / `composition.py` 92%） |
| 网页请求可拉起**宿主 GUI 进程**（Story 50-8 R2，**新暴露面**；**裁定：维持现状** 2026-09-28） | `POST /api/dialogs/pick-directory` 会在**服务端所在机器**弹原生窗口（子进程 `tkinter` / `powershell`）。防线只有「回环来源 + 单在途 + 冻结 argv + 300s 超时 kill」——回环 peer ≠ 可信（见上），任何能连上端口的本机进程都能让服务机弹窗（骚扰面）；其边界地位见 §4.18。**默认关闭**（`--dialog-backend` 默认 `none`，2026-09-27 修改）：需要时显式传 `--dialog-backend auto` 开启；内嵌服务同样默认关闭（`build_http_service` 不传该参数，`HttpProjectConsole` 默认值已同步改为 `"none"`）。与配置写入通道的 `HTTP_CONSOLE_WRITE_ENABLED` 默认 False 惯例一致 |
| 原生目录选择在部分环境**不可用**（Story 50-8 R2） | ①无图形后端（容器 / 缺 `_tkinter` 的 Linux）；②服务跑在远程机器而浏览器在别处（窗口弹在服务机，对调用者无用）；③默认即 `--dialog-backend none`（禁用；2026-09-27 起，须显式传 `auto` / `tkinter` / `powershell` 才启用）。三种都回 `dialog_unavailable` 并**保留手工输入**（不静默失败、也没有服务端目录浏览 API —— 那会把宿主目录结构开放给回环客户端） |
| 网页侧读取结果收敛是**展示策略**，不是数据边界（Story 50-8 R5 + `content_search` / `file_edit`） | 只是「网页事件流不放结果**正文**」——`file_read` / `file_edit` 成功时**整份置空**（对话区只留「工具名 → 作用对象」），`content_search` 成功时**折叠成去重的命中文件清单**（`cli.http_console._matched_files`；未命中消息与超大文件跳过行属诊断，原样保留）；同一份内容仍写进**会话文件**与 `rollout.jsonl`（审计 / 回放需要），模型侧也照旧收到全文；失败消息靠 `Error:` 前缀约定识别（内置工具的既有约定，若将来改结构化错误，该判据可退化为只看 `is_error`）。**已知限制（裁定：收紧规格）**：正文以 `Error:` 开头的文件（日志/错误报告/栈转储）成功读取时，整份正文会照旧显示在网页对话区——AC9「成功只显示文件名」与「失败消息可见」在该输入类上互斥。冻结边界：不得收敛失败消息（那会让诊断从页面消失） |
| 配置掩码域是后缀制（**裁定：维持现状**） | 掩码域只认 `*_API_KEY` / `*_API_KEYS` 后缀（`config/catalog/masking.py::is_secret_key`），而 `*_BASE_URL` 走排除组模式 ⇒ 把中转站 token 写进 base URL（如 `https://user:token@relay/v1`）的值会**原样回显**。`GET /api/projects/{id}/config` 无回环门 ⇒ 任何能连到服务的客户端都能读到。**裁定维持现状**理由：① URL 本身不以凭证命名；② 部分掩码会破坏诊断用途（"为什么连不上"需要完整 URL）；③ 同仓 `safe_logging` 已对 URL userinfo 脱敏，口径分场景。冻结边界：不得对 URL 做部分掩码（破坏诊断），不得给只读 GET 加回环门（与 49/50 姿态冲突） |
| 路径级审批分级（**裁定：维持条件性**，2026-09-28） | 审批粒度是**工具级**（`PolicyEngine.approval_tools` ∪ MCP `schema.annotations.destructiveHint`），**不看路径**；而 workspace 围栏（`evaluate_tool_call` 第 4 步 `_validate_paths`）对越界路径一律**硬阻断** ⇒ 今天**不存在**「被批准的 workspace 外写」这个对象，故本项**无触发场景**。**触发条件**：引入「非 workspace 的受控写」能力（如经审批向 workspace 外写）——届时改法 = 让第 4 步的越界结果按**声明式路径策略**在 `allow / ask / deny` 之间分级（未配置 = 现状逐字节不变；默认仍 fail-closed）。**若实现，判据要求**：越界且未声明 ⇒ 仍 `BLOCKED`；声明 `ask` ⇒ `APPROVAL_REQUIRED` 且拒绝后不落盘；凭证 basename 与内部状态目录**永远 deny**（不可被审批放行）；`..`／符号链接／短名按**解析后真实路径**分级（复用 `path_safety.resolve_under_root` 同一算法）；不得改变 `sandbox_mode` 语义。**冻结边界**：分级只是 `PolicyEngine` 的 defense-in-depth 标记（边界地位见 §4.18），不得放松 workspace 围栏默认值。证据见 `_bmad-output/retrospective-all-cycles.md` §三「跨周期勘察与裁定索引」A1 / A6 行 |

---

## 六、目录与调用链

**目录即代码**：`src/heagent/` 的分层与文件职责以代码为准，包边界与布局由
`tests/test_architecture_contracts.py` 的白名单钉住（新增 / 搬移模块先改那张表）。带一行注释的目录树快照住
[`frame/layout.md`](frame/layout.md)——它只是阅读辅助，与 `src/` 不一致时一律以代码为准；「哪层能依赖哪层」看 §三。

**调用链**是代码的推导结果，架构级数据流见 §二；单次 / 交互 / HTTP+WS / 控制台四条完整链路见
[`frame/call-chains.md`](frame/call-chains.md)。

## 七、扩展页索引（`docs/frame/`）

`4.x` 的机制细节按主题住在 `docs/frame/`，编号与本文件一致；本文件只留职责、边界与契约。

| 扩展页 | 覆盖小节 | 一句话 |
| --- | --- | --- |
| [frame/README.md](frame/README.md) | — | 索引与阅读顺序 |
| [frame/layout.md](frame/layout.md) | 六（原） | `src/heagent/` 目录树速查（辅助，`src/` 为准） |
| [frame/cli.md](frame/cli.md) | 4.1 | 子模块表、启动编排、测试缝 |
| [frame/agent.md](frame/agent.md) | 4.2 | façade、状态与参数、注入顺序、子 Agent |
| [frame/providers.md](frame/providers.md) | 4.3 | 各 provider、容错四层、路由 |
| [frame/tools.md](frame/tools.md) | 4.4 · 4.11 · 4.14 | 工具系统与沙箱后端、MCP、资源读取加固 |
| [frame/context.md](frame/context.md) | 4.5 | 分层发现、计量、压缩与窗口重置、会话 |
| [frame/memory.md](frame/memory.md) | 4.6 | 四库、技能库、dream |
| [frame/config.md](frame/config.md) | 4.10 | 四层来源、运行快照、逐键默认值 |
| [frame/engine.md](frame/engine.md) | 4.12 | 容器、策略链、持久化、日志卫生 |
| [frame/goal.md](frame/goal.md) | 4.13 · 4.13.1 | 命令族、审批决策、并行写集、GoalScript |
| [frame/events.md](frame/events.md) | 4.15 | 字段表、逐 kind 发射点、分发语义 |
| [frame/network.md](frame/network.md) | 4.16 · 4.16.1 · 4.17 | HTTP/SSE、WS 四端点与三档、网页控制台 |
| [frame/call-chains.md](frame/call-chains.md) | 七（原） | 完整调用链 |

## 八、技术规范

| 规范 | 说明 |
|------|------|
| Python 版本 | 3.11+ |
| 异步模型 | 全 async/await，CLI 用 asyncio.run() 桥接 |
| 数据模型 | 统一 Pydantic BaseModel，禁止跨模块传 raw dict（例外：`AgentState` / `SubAgentResult` 用 dataclass） |
| 命名 | PEP 8 — snake_case 文件、PascalCase 类名（不加后缀），4 空格缩进 |
| 日志 | `logging.getLogger(__name__)`，stdlib only |
| 行宽 | 120（ruff.toml） |
| 测试 | pytest + pytest-asyncio，`StubProvider` 模拟 |
| Provider 接口 | Protocol（结构化子类型），不强制继承 |
| 文件规模 | `src/heagent/**/*.py` 逐文件 ≤ 1000 行（判据 `tests/test_architecture_contracts.py::test_source_files_stay_under_the_line_ceiling`，常量 `MAX_SOURCE_FILE_LINES`），超限即红并点名；接近上限先拆模块再加功能（先例：`cli/help_view.py` 自 `interactive.py` 拆出 `/help` 渲染面） |
| 包边界契约 | 改包间依赖必须同步 `tests/test_architecture_contracts.py` 的 `FORBIDDEN_RUNTIME_IMPORTS`；新增/删除 `cli/*.py` 要同步 `test_cli_package_layout_is_pinned` 白名单与 §4.1 子模块表；`cli/__init__.py` 零 import（`test_cli_package_shell_stays_thin`），子模块延迟导入必须指向实模块 |
| 注释 | 只写当前不变量与契约；开发历程（story 号、评审过程、日期沿革）归 git log 与规划产物，存量历史注释动到哪处顺手净化哪处 |
| Windows 兼容 | subprocess `text=True` 必须显式 `encoding="utf-8"`，否则中文输出解码失败 |
| 发版契约 | 版本真源 = `src/heagent/__init__.py::__version__`，与 `pyproject.toml` 一致且纯 semver；`CHANGELOG.md` 保有 `## [Unreleased]` 与当前版本条目（判据 `tests/test_release_workflow_contract.py`） |

### 8.1 目标工作流质量收口

Epic 43-45 的目标级编排、checkpoint、恢复和 CLI 审计由确定性测试覆盖。`tests/test_goal_workflow_smoke.py` 使用无网络执行，验证两个 story 单元、workflow/checkpoint、ledger 与 EventBus 证据，并覆盖损坏状态显式失败（legacy 阶段状态机与其 route 门控已于 2026-09 删除）。

本地可运行 `python scripts/quality_gate.py` 串行执行冒烟、默认回归/覆盖率、ruff lint、ruff format、mypy 和 bandit（`-ll`，与 CI lint job 同参数——本地门缺这一步时「本地绿 / CI 红」无从察觉）；CI 另设无凭据的 `goal-smoke` job。真实 LLM 冒烟只能作为显式外部步骤，凭据缺失必须记录 blocked。当前声明式 `/goal` 的步骤权威是 `.heagent/skills/he-goal/workflow.md`；目标目录中的 `workflow.json` 只保存运行时元数据。SafetyGuard、path_safety 与 engine sandbox 的边界地位见 §4.18。

### 8.2 Goal/Epic/Story 产物契约

> **产物契约（三层 Goal/EPIC/Story）已退役**：声明式 `/goal` 切换后 CLI 不再写入 Goal 产物
> （旧 `engine/artifacts.py` 的 `validate_hierarchy` / `parse_artifact` / `validate_sprint_status_path`
> 均已随产物写路径删除，src 内无对应符号）；现行 `/goal` 持久化目标需求文档 `brief.md`，
> Epic/Story 列表存放在工作流自己的 `epics.md`。工作流能力面校验由
> `goal/workflow_support.py::validate_goal_workflow` 承担（entrypoint / on_create / executor 声明面）。

模板位于 `.heagent/skills/he-goal/templates/`（EPIC/STORY/GOAL/gate/prompt）。历史 Epic/Story 状态只由 `_bmad-output/Goal-2-v6/sprint-status.yaml`（v6，已归档）维护（BMad 外部工具写入，src 内无路径校验；v7 起状态真源换成 goal 树自带的 `docs/<goal-id>/tickets/` 票树，见 §8.5）；`workflow.json` 只保存运行时元数据，绝不作为第二份状态看板。

### 8.3 声明式敏捷流程收口

`.heagent/skills/he-goal/workflow.md` 是必需且自包含的 `/goal` 工作流。它声明初始化过程和完整的有序步骤；CLI 只把受支持的声明映射为确定性操作。`WorkflowRunner` 每次调用执行一个声明步骤，持久化从零开始编号的已完成步骤 checkpoint，并拒绝缺失输入、无效输出以及不匹配的工作流恢复状态。`brief.md` 是目标的持久需求文档（创建时保存原始请求，随后由步骤 01 在初步分析后写入派生需求）；重命名之前创建的目标继续使用自己的 `require.md`（或更早的 `GOAL.md`），由 `goal/document.py` 按最新名称优先解析，并将解析出的文件名注入步骤提示词的 `{goal_document}`，因此工作流声明不会硬编码文件名。它取代 `goal.txt`，并且有意不作为 `parse_artifact()` 的 Goal 产物。Goal 文档和 `workflow.json` 仍位于 `_he-output/` 下。新目标在 `checkpoint-workspace.txt` 记录绝对工作区，并将 checkpoint 存放在 `<workspace>/.heagent/checkpoints/<goal_id>/`；没有该标记的目标继续使用原有的目标目录内 `checkpoints/`。无效标记会显式失败；缺少工作流也会显式失败。原先命令式的 `goal.txt` 看板路径已经删除，声明式 Runner 是唯一的 `/goal` 执行路径。转换策略仍由当前工作流及其确定性 Runner 负责。工作流本身作为技能包（`he-goal`）提供，并通过 `SkillCatalog`/`SkillResolver` 解析；因此每次运行的策略（`max_rounds`、`auto_schedule`、开放问题措辞）以及步骤提示词/门禁措辞，都声明在包内的（`workflow.md`；步骤/门禁模板文件名由 frontmatter `prompt_template` / `gate_template` 键声明，文件为 `templates/prompt.md` / `templates/gate.md`）。模板是否必需也由这些声明控制：声明的模板缺失或为空时，加载器会显式失败（`required_resources` 与模板键条目都会做前缀规范化且逐项强制检查；拼写错误的名称会导致加载失败，不会被静默忽略）；未声明但内容为空的模板会在渲染提示词时显式失败，不会生成空的步骤提示词或门禁块；CLI 不包含内置模板文案。

### 8.4 工程纪律条款

Canonical 工程纪律（评审与实现共用判据；2026-11-06 自 dsh AGENTS 纪律精选采纳）：

1. **fails loud at load**：自含的配置/装配错误在装载期显性失败。既有先例：http-server 双开关全关 fail-fast、对外模式缺 token 拒启动、畸形 cron 构造期校验。「静默降级」是例外，必须有明文立场（如 MCP 桥接降级 WARNING + 每次提醒）。
2. **常量≠配置**：部署可变项必须是可校验 Config 字段；`DEFAULT_*` 常量不算可配置——这是「用户声明优于代码立场」的判定线。
3. **空 catch 必须具名**：`except Exception:` 后空处理（或仅 pass）必须注释写明吞掉的是什么错误、为什么安全；匿名吞错违反显性失败准则。
4. **不解释的对称破缺暗示漏提取**：并行值/对称结构出现无理由差异时先怀疑漏提取；有理由的不对称必须在差异处留注释（先例：workflow_runner 串行/批两路闩置位 AD-18 刻意不对称并留注）。
5. **注释与 docstring 的口径分面**（判据 = `tests/test_comment_conventions.py`，2026-11-24 落地）：
   - **对外可见面保持英文**：`@tool` 函数的 docstring（被 `tools/decorator.py` 取作模型可见的工具描述）、Click 命令 docstring 与 `help=`（CLI UX）、HTTP/WS 错误码与 `code=` 值——这些是对外契约，换语言等于换契约。
   - **其余注释与 docstring 用中文**：模块 / 类 / 函数 docstring、行内 `#` 注释、`#:` 属性注释。代码主要给维护者读，本仓的会话语言是中文。
   - **段标题单一形态**：`# ── 段名 ──`；`# ---- … ----` 与 `# ====` 两种分隔线不再使用（同一仓库两套分隔线会让「找某段」变成猜风格）。纯分隔线（无文字）同样用 `─`。
   - **不翻译「不是散文」的东西**：`# noqa` / `# type: ignore` / `# nosec` 指令、ASN.1 记法、cron 字段编号、shell 片段、字段名枚举保持原文。
   - **注释写「为什么」**：记录设计不变量与刻意的不对称；交付过程（评审轮次、triage 统计、plan 闭合状态）归 plan 与台账，不写进代码注释。

### 8.5 台账与规划产物布局

**当前规划区是 goal 树（`docs/<goal-id>/`），不是 `_bmad-output/`。** `/loop` 每轮在 goal 目录下产出 PRD
（`prd-<slug>/`）、架构（`architecture-<slug>/`）、逐故事报告（`step-NN-*/report.md`）、`progress.md`
与票树 `tickets/`；指针 `docs/current` 存当前 goal-id（`reset` 只删指针、不删目录）。票树接口只走
`_bmad/method/scripts/tickets.py`，且每条命令都要带显式根：
`tickets.py --project-root docs/<goal-id>/tickets mark <epic-dir> <epic>.<entry> done`。
`mark` 是 Epic/Story 状态的**唯一合法写路径**（不手改 plan frontmatter）；`done` 只在审批放行后写。
`/goal`（v6）的产物仍落 `_he-output/goals/`，与 goal 树互不读写。

**`_bmad-output/` = 根级台账 + 历史归档**（规划/台账区，非代码事实源）：

| 位置 | 内容 |
| --- | --- |
| `open-items.md` | **唯一活动台账**：「活动（未闭合）条目」表 + 按行动姿态分组的速读节 |
| `epic-overview.md` | 当前状态总览 + epic 总目录 + 文档地图 |
| `retrospective-all-cycles.md` | 历史唯一载体（§二编号位**有意空缺**，保 §三锚点，勿当缺陷修） |
| `README.md` | 本目录导航 + 归档规则 |
| `epics/` | 第一代周期产物（27 个周期目录，67-ID 契约钉死，勿动） |
| `Goal-2-v6/` | 第二代：BMad v6 时代归档（只读） |
| `Goal-3/` | 第三代：goal-3 票树归档（只读，状态已不活跃） |

ADR 住 `docs/decisions/`。`_bmad/custom/config.user.toml` 的 `active_initiative` 是 gitignored
用户配置（换机器 / 新 clone 需重写），不是文档事实源。

**待办池住仓库根 `todo/`（不在 `docs/` 下）**：`todo/todo.md` 是唯一手工入口（`## 待整理` 追加区 /
`## 已归档`），`todo/solutions/<主题名>.md` 装主题化的细化与方案（每个文件**先写 `## 细化（六项）`、
再写方案正文**）。维护者 = `todo` 技能（`.heagent/skills/todo/`，手工触发、不挂 cron）；链接覆盖见
`tests/test_docs_links.py` 的 `todo/**/*.md` 与位置守卫 `test_todo_pool_lives_at_repo_root_and_stays_covered`。

**台账改写前的守卫**：`tests/test_deferred_id_registry.py`（活动计数在 `open-items.md` /
`epic-overview.md` / `_bmad-output/README.md` 三站点逐处严格比对；速读节只允许引用活动项；闭环/退役
一个条目要同步删速读节引用）+ `tests/test_deferred_ledger.py`（67 基线 ID 守恒）。改台账路径须同步
`cli/display.py::_DEFERRED_LEDGER` 回退链。
