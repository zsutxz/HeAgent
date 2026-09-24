# HeAgent 项目架构与工作流程

> 状态：当前实现参考。历史来源与迁移索引见 [architecture-history.md](architecture-history.md)。维护责任：对应模块的变更提交者。

> 相关文档：总览与快速开始见 [`README.md`](../README.md)，设计目标见 [`design.md`](design.md)，文档导航见 [`文档索引`](README.md)，部署边界见 [`deploy/README.md`](../deploy/README.md)，协作约定见 [`CLAUDE.md`](../CLAUDE.md)。本文为**代码实现层面的架构参考**，以当前 `src/` 实现为准。

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
> **TCP 入口路径（Epic 48，实验性）**：`heagent tcp-server` **不走** CLI 循环——
> `TcpServer`（`network/tcp_server.py`：一行一条 JSON Lines 请求）→ 解析 + 非等待式在途名额
> → `TcpAgentHandler.__call__`（`cli_tcp.py`，**每请求新建一个 `AgentLoop`**）→ 与上面同一条
> `AgentLoop.run` → 响应经 `network/protocol.py` 映射为**一条** JSON 行。
> 通道隔离：响应只走 socket、启动告警与监听地址走 stderr、rollout 由 `events.JsonlSink`
> 按 `EVENTS_ROLLOUT_ENABLED` 落盘（详见 4.16）。

---

## 三、模块依赖关系 (DAG)

```
exceptions  types  config  persist  roles
    ↑          ↑       ↑
    └─ providers ─┴── tools ─┴── context ── engine ── agent
                            ↑              ↑
                        memory ───── cron ──┘
```

**依赖规则：**
- `agent/` 是顶层编排器，依赖所有其他模块
- `providers/` 和 `tools/` 互不依赖
- `exceptions.py` 和 `types.py` 是叶子模块，无内部依赖
- 新增 Provider 或 Tool **禁止**从 `agent/` 导入（**全仓无例外**：`builtins/subagent.py` 只持可注入委派回调，子 Agent 编排由 `agent/delegation.py` 提供、`AgentLoop._runtime_scope` 每 run 绑定；`tools/mcp/*` 同）
- `persist.py` / `roles.py` / `frontmatter.py` 是顶层底层共用模块（与 exceptions/types/config 同层；persist/roles 2026-09 自 `engine/` 迁出，消除下层模块反向依赖）：`persist.py` 供 engine/tools/context/memory/cron/goal/housekeeping 共用；`roles.py` 供 engine.policy/agent.sub/tools.builtins.subagent/cli 共用；`safe_logging.py`（零 heagent 依赖，2026-09-23）收敛日志卫生：`safe_log` 逐调用点容错 + `install_logging_fault_guard()` 进程级守卫 + `redact_secrets`/`redact_details` 启发式脱敏，`network/`（不得依赖 engine）与 engine/agent 共用同一实现；`frontmatter.py`（零 heagent 依赖，2026-09-17）收敛原六处手写 `---` frontmatter 解析器（engine.artifacts / memory.skills / memory.skill_packages / goal.workflow_loader / slash / roles；skill_packages 原两处其一随工作流装配迁入 goal），严/宽两档 + 两个分隔符变体，架构契约断言正则不得漂移出该模块
- `memory/` 运行期**不依赖 `engine/`**（`memory/dream.py` 的 `EngineContainer` 仅 TYPE_CHECKING 引用，实例由入口层注入、无 `default()` 回退；契约断言见 `test_architecture_contracts.py` FORBIDDEN_RUNTIME_IMPORTS）
- `engine/` 是运行时治理层（policy/executor/store/ledger/observability + workflow 运行时模型），依赖 `types`/`exceptions` + `tools.call_summary`/`tools.sandbox`/`tools.path_safety`（container 另有 lazy `config` 导入）；工作流资源模型在 `engine/workflow_resource.py`（原 memory.skill_packages，2026-09-20 迁入）；被 `agent/` 依赖（`AgentLoop` 经 `EngineContainer` 注入）
- `events/` 是事件传输层（JSONL 对外契约），运行时**零 engine 依赖**（EngineEvent 仅 TYPE_CHECKING 引入）；反向地，`engine/` 运行期引用 `events.protocol` 的**纯函数单点** `error_kind_for`（Phase 5 C1 失败分类）——events.protocol 运行期仅依赖 `exceptions`，该边无环且不引入 EngineEvent→RunEvent 的反向耦合（4.15）
- `cron/expr.py` 是**零 heagent 导入的纯叶子**（5-field cron 表达式解析：`cron_matches`/`_parse_field` 等），被 `cron/scheduler`（包内）与 `memory/dream` 共用——类比 `heagent.persist`（纯 util）。`memory → cron` 包级边仅指此纯叶子（做 cron 匹配），**不依赖 `cron.scheduler` 调度器**；`CronScheduler._matches` 已降为薄委托（`return cron_matches(...)`）。
- `network/` 是**入口传输层**（Epic 48，2026-09-22）：只承载 framing（TCP JSON Lines）与 HTTP 协议 / 路由 / 静态资源 / 连接与超时生命周期 / 暴露判定，运行期**不依赖运行栈**（`agent`/`engine`/`providers`/`tools`/`memory`/`context`/`cron`/`events`）与任何入口层模块（`wiring`/`cli`/`cli_goal`/`cli_tcp`/`cli_http`/`gui`）；Provider 与 `AgentLoop` 的装配由入口层 `cli_tcp.py` / `cli_http.py` 单向伸手（契约断言：`test_architecture_contracts.py` 的 FORBIDDEN_RUNTIME_IMPORTS["network"]）

---

## 四、核心模块详解

### 4.1 CLI 入口 (`cli.py`)

| 功能 | 说明 |
|------|------|
| 入口命令 | `python -m heagent [PROMPT]` |
| 单次模式 | 传入 PROMPT 参数，执行后退出 |
| 交互模式 | 不传参数，进入 REPL 聊天循环 |
| Provider 构建 | 自动检测 `DEEPSEEK_API_KEY` → `OPENAI_API_KEY` → `ANTHROPIC_API_KEY`；本地 Ollama 经 `OLLAMA_ENABLED=true` 显式启用 |
| 工具注册 | 导入 `heagent.tools.builtins` 触发 `@tool` 注册 |
| 模块初始化 | 自动创建 SkillStore、FactStore、ProfileStore、SoulStore、SessionStore、ContextCompressor、JobStore |
| Cron 调度 | 交互模式下启动 CronScheduler 后台任务 |
| 重试中间件 | 通过 `make_retry_middleware()` 接入 AgentLoop |
| Token 统计 | 每次回答后显示 `[tokens: N in + M out = T total]` |
| 运行暂停/恢复/中断 | 交互模式运行期间按 Esc 暂停当前 run、Enter 恢复、双击 Esc 打断（取消当前 run、回到输入状态，见 `terminal.py`） |
| TCP 入口 | `heagent tcp-server`（实验性，实现拆在 `cli_tcp.py` + `network/`，协议与安全立场见 4.16） |
| HTTP 入口 | `heagent http-server`（实验性，实现拆在 `cli_http.py` + `network/http_*.py` + 包内 `web/`，协议、静态页与安全立场见 4.17） |

### 4.2 Agent 核心 (`agent/`)

#### loop.py — 主循环（façade）

> **Phase 2 façade 化（2026-09-21）**：`AgentLoop` 保留依赖注入装配、公共入口与同名委托；循环策略拆为 sibling 模块——`run_lifecycle.py`（状态数据类 `AgentState`/`_RunInit`/`_ResumeState` + 初始化分叉 + 非流式循环体 + 终结/检查点）、`stream_runtime.py`（流式循环体）、`resume_runtime.py`（快照重建续跑状态）、`context_runtime.py`（迭代控制/消息追加/压缩/窗口重置）、`message_ports.py`（steering/follow-up 注入 + 协作式暂停）。下表方法在 façade 上保留同名委托，实现位于对应策略模块；`AgentLoop` 与状态类的导入路径不变（策略模块运行期不反向导入 loop，仅 TYPE_CHECKING）。

| 组件 | 说明 |
|------|------|
| `AgentState` | 单次运行的可变状态（消息列表、迭代计数、结果） |
| `AgentLoop` | 核心编排器，循环调用 Provider → 执行 Tool → 直到获得文本回答 |
| `run(prompt)` | 入口方法，构建初始消息后进入循环 |
| `run_stream(prompt)` | 流式入口，逐步 yield `StreamEvent`（`text`/`tool_call`/`tool_result`/`done`）；`tool_call` 在执行前发出并带 `tool_target`（作用对象摘要），`tool_result` 带 `tool_name`/`tool_error`；命中 `tool_calls` 时回退 `send()` 重取该轮调用 |
| `resume(run_id)` | 从 `RunStore` 加载快照续跑（P3）：COMPLETED 直接返回 `final_answer`，否则用 `metadata['progress_summary']` 重建窗口续跑，同 `run_id` 跨多段 context window；内部经 `_resume` 注入 `run()` 的初始化分支 |
| `resume_stream(run_id)` | `resume` 的流式版（P5-5）：COMPLETED 产出单个携带缓存答案的 `done` 事件；否则同上重建窗口后经 `_resume` 注入 `run_stream()` 流式续跑 |
| `pause()` / `unpause()` / `is_paused` | 协作式暂停/恢复当前循环（`asyncio.Event` 实现）：`pause()` 后循环在下一轮边界挂起（进行中的 LLM 调用跑完），`unpause()` 从挂起点原地继续；`is_paused` 反映请求态。每次 run 结束（完成/失败/取消）在 `_persist_and_cache` 自动复位，不泄漏到下一次 run |
| `_build_system()` | 构建系统提示词（含人格/上下文/技能/记忆注入，见下方注入顺序） |
| `_call_provider()` | 通过 Middleware 链调用 Provider，含 Token 估算对比 |
| `_execute_tools()` | `asyncio.gather()` 并行执行所有 tool_calls |
| `_execute_one()` | `ExecutionLedger.acquire()` 幂等/租约（key=`run_id:call.id`；COMPLETED 短路返回缓存，但**命中仍复核 policy**——若已收紧为 `BLOCKED` 则 bypass 缓存走正常链路，防策略变更后泄漏旧结果；lease-active 即 RUNNING 未过期则跳过执行、返回 `is_error` skip 提示防并发/重入）→ **在途期间后台续租**（`_renew_ledger_lease`，工具可跑数分钟，固定租约会让记录被 prune 误判为孤儿删除）→ `PolicyEngine.evaluate()` → `ToolExecutor` 分发（内部 `SafetyGuard.check()`）→ handler → `ledger.complete()`/`fail()` 回写（**回写失败只记 warning，不改写工具结果**；成功路径带 `recreate_if_missing=True`，记录被清则**重建为 COMPLETED** 以保住幂等缓存）；防 window_reset 后模型重发相同 `tool_call.id`（P4，见 4.12） |
| `last_usage` | 最近一次 `run()` 的累计 `TokenUsage` |
| `last_iteration` | 最近一次 `run()`/`run_stream()` 的迭代次数 |
| `last_run_context` | 最近一次 `run()` 的 `RunContext`（run_id / 迭代 / 审批·沙箱授权元数据） |
| `active_tool` | **在途**工具批次摘要（如 `file_read → src/a.py`；多调用带 `(+N)`），由 `activity_label` 拼接：批次执行期间非空、结束或取消即清空，run 开始（含 `resume`）即重置——状态栏 `🔧 …` 段据此显示「卡在哪个工具」 |
| `tool_activity` | 本次 run 的**调用尝试**活动标签（每次调用一条，run 开始即重置，`resume` 路径同样重置）——执行前登记，被阻止 / 命中 ledger 缓存的调用同样留痕；单次模式跑完由 `cli_display.show_tool_activity` 回显 |

**`AgentLoop.__init__()` 参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `provider` | `BaseProvider` | LLM 提供者（必需） |
| `registry` | `ToolRegistry` | 工具注册中心（默认全局单例） |
| `guard` | `SafetyGuard` | 安全防护（默认黑名单模式） |
| `middlewares` | `list[MiddlewareFn]` | 中间件链 |
| `max_iterations` | `int` | 最大迭代次数 |
| `skills` | `SkillStore` | 技能存储（激活技能工具） |
| `facts` | `FactStore` | 事实记忆（激活记忆工具） |
| `profile` | `ProfileStore` | 用户画像（激活画像工具） |
| `session` | `SessionStore` | 会话持久化 |
| `compressor` | `ContextCompressor` | 上下文压缩器（原位摘要，见 4.5） |
| `window_reset` | `WindowResetConfig` | 上下文窗口重置配置（token≥阈值清窗重建 + resume，与 `compressor` **互斥**，见 4.5；P3） |
| `context_dir` | `str` | 上下文文件扫描目录 |
| `soul` | `SoulStore` | 人格加载器 |
| `cron_store` | `JobStore` | Cron 任务存储（激活 Cron 工具） |
| `engine` | `EngineContainer` | 运行时治理容器（policy/executor/store/ledger/events），默认 `EngineContainer.default()`，见 4.12 |
| `run_context` | `RunContext` | 预置的单次运行上下文（一次性，用后清空） |

**系统提示词注入顺序（`_build_system()`）：**

```
1. <identity>        — SOUL.md 人格（最顶层，insert(0) 插到最前）
2. 用户 system 字符串
3. <project-context> — 上下文文件（CONTEXT.md > AGENTS.md > CLAUDE.md）
4. <shell-workspace> — 本 run 的 shell 沙箱工作目录（E40-D2；仅真正生效时注入）
5. <skills>          — 自动匹配的技能
6. <memory>          — 事实记忆
7. <memory-nudge>    — 记忆保存提醒
8. <profile>         — 用户画像
```

#### middleware.py — 中间件管道

```python
# 类型定义
MiddlewareFn = Callable[[Request, NextFn], Any]

# 组合函数：递归构建中间件链
compose(middlewares, handler) -> NextFn

# 工厂函数：创建重试中间件
make_retry_middleware(max_attempts, base_delay, max_delay) -> MiddlewareFn
```

每个中间件接收 `(Request, NextFn)`，可拦截、修改或短路请求/响应。

#### sub.py — 子 Agent

| 组件 | 说明 |
|------|------|
| `SubAgent` | 隔离的 Agent 实例，独立的 Loop + Context；经 `parent_run_id` 继承父 `engine`；可带 `role`（`RoleSpec`：system/allowed_tools/blocked_tools）/`system`/`allowed_tools` 角色化（P1） |
| `SubAgentResult` | 子任务结果（task, output, success, iterations, **run_id**：子 agent 自身 run_id，P5-3 供结构化结果与树形聚合） |
| `run_parallel()` | `asyncio.gather()` 并行运行多个子 Agent |
| `build_subagent_delegates()` | `agent/delegation.py`：为 tools 层组装单任务/并行委派回调（`DelegateOne`/`DelegateMany`），把 `SubAgentResult` 映射为工具层 `SubTaskOutcome`；`AgentLoop._runtime_scope` 每次 run 绑定、退出解绑；`depth` 入参 +1 写入子 Agent（递归深度闸门输入） |

子 Agent 默认带 `ContextCompressor`（短任务走原位压缩），可经 `window_reset` 参数启用跨窗口续跑（长任务场景，P5-2 已交付）。角色化时由父 `engine` 经 `dataclasses.replace` 换角色专属 `PolicyEngine`（allowed_tools/blocked_tools），其余运行时服务（store/ledger/events）复用。

### 4.3 Provider 层 (`providers/`)

#### base.py — Protocol 定义

```python
class BaseProvider(Protocol):
    async def send(messages, *, tools) -> ProviderResponse
    async def stream(messages, *, tools) -> AsyncIterator[ProviderResponse]
    def get_metadata() -> ProviderMetadata
```

使用 `typing.Protocol`（结构化子类型），无需继承。

#### openai.py — OpenAI 兼容 Provider

- 支持自定义 `base_url`（DeepSeek、智谱 AI 等）
- 消息/工具调用格式转换：HeAgent ↔ OpenAI API
- **本地 Ollama**：`ollama_enabled=true` 时 CLI 构建 `ollama` 条目（`OpenAIProvider`，`base_url` 指向 Ollama `/v1`）。Ollama 不校验 API Key，故以**显式开关**（而非密钥存在性）判定是否构建——默认关闭，避免默认向 localhost 发请求、也避免「装了没启动」混进回退池；`ollama_model` 未配置时 fail-fast（不猜模型名）

#### anthropic.py — Anthropic Provider

- 提取系统消息（`_extract_system()` 合并为 Anthropic 顶层 `system` 字段）
- 消息/工具调用格式转换：HeAgent ↔ Anthropic API
- **提示词缓存（FR-3）**：`_build_system_param()` 在 system prompt 末块注入
  `cache_control: {"type": "ephemeral"}` 断点，后续请求复用稳定的 system/tools 内容以降低成本。
  由 `anthropic_prompt_caching` 开关控制（默认开启；使用不支持 cache_control 的代理时应关闭）

#### chain.py — Provider 回退链（**外层**）

有序 Provider 列表，失败时自动切换下一个。**回退精度（FR-4）**：仅对
`RATE_LIMITED` / `AUTH_FAILED` / `TRANSIENT` 错误回退；`NON_TRANSIENT`（400/422 等客户端错误）
立即抛出——切换 Provider 不会让坏请求变好，回退只会浪费配额并掩盖真实问题。
所有抛出异常经 `_raise_provider_error()` 统一为 `ProviderError`（已是 ProviderError 则原样
抛出保留既有 cause 链，否则包装并保留原始 cause 与状态码），避免裸 SDK 异常穿透到 CLI。

```
ProviderChain([deepseek, KeyRotatingProvider([openai×N]), KeyRotatingProvider([anthropic×N])])
  │
  ├── 当前 Provider → 失败(可回退) → _advance() 切下一个 Provider
  ├── 任一 NON_TRANSIENT → 立即抛出 ProviderError（不回退）
  └── 全部失败 → _current_index 恢复到起始位，抛出最后的 ProviderError
```

#### key_rotation.py — 密钥池轮换（**中层**）

同一 Provider 类型的多实例包装（每个实例使用不同 API Key）。`429/401/403`
（或消息含 rate/auth/forbidden 关键词）时自动切换到下一个密钥重试；密钥池全部耗尽后
恢复原索引并抛出异常，交由上层 `ProviderChain` 回退到其他 Provider 类型。
`get_metadata()` 名称带 `+keypool` 后缀以便日志区分。`send()`/`stream()` 双路支持轮换。

#### retry.py — 错误分类与重试（**内层** + 共享分类器）

`classify_exception()` / `classify_error()` 将错误分为四类，供三层共用：

```
错误分类（优先级：429 > 401 > 5xx > 其他）：
  RATE_LIMITED (429)      → ProviderChain 回退 / KeyRotating 轮换；retry 中间件不重试
  AUTH_FAILED (401/403)   → ProviderChain 回退 / KeyRotating 轮换；retry 中间件不重试
  TRANSIENT (5xx/超时/过载) → retry 中间件指数退避 + 随机抖动重试；也触发 ProviderChain 回退
  NON_TRANSIENT (400/422) → 各层均不重试/不回退，立即抛出
```

`retry_with_backoff()` 仅对 `TRANSIENT` 错误重试；`make_retry_middleware()` 将其包装为
Middleware 接入 `AgentLoop.middlewares`。

**三层故障转移组装**（cli.py `_build_provider()`）——由内到外依次接管可恢复错误：

```
AgentLoop
  ├─ provider = ProviderChain([                    # 外层：跨 Provider 类型回退（NON_TRANSIENT 不回退）
  │     deepseek,                                   #   单 key
  │     KeyRotatingProvider([openai sk1, sk2, ...]),# 中层：同 Provider 多 key 轮换（429/401 触发）
  │     KeyRotatingProvider([anthropic k1, k2, ...])# 中层
  │   ])
  └─ middlewares = [make_retry_middleware()]         # 内层：仅 TRANSIENT 指数退避重试
```

#### switchable.py — 运行时多 vendor 切换（**外层选择层**）

`SwitchableProvider` 持有 `{名称: provider}` 池（每个命名 provider 独立 key/base_url/model），实现 `BaseProvider` 协议、对 `AgentLoop` 透明。与 `ProviderChain` 的全自动按序回退不同，它以**用户当前选择**为默认起点，自动回退仅作「当前选择不可用时的应急接管」：

- **手动切换**：`switch(name)` 经交互模式 `/model` 命令触发（cli.py）。
- **自动回退**：当前 provider 抛 `RATE_LIMITED`/`TRANSIENT`（429/5xx/超时）时自动切到池中下一个；`AUTH_FAILED`/`NON_TRANSIENT` 不回退（与 chain 同精度）。
- **粘性停留**：成功回退后 `_active` 更新为新 provider，后续不再重试已限流的旧 provider。
- **流式约束**：`stream()` 已下发 chunk 则不回退，防重复前缀。

可包住 `ProviderChain` 等任意 provider，与三层容错叠加：用户选择（switchable）→ 跨类型回退（chain）→ 多 key 轮换（key_rotation）→ 重试（retry）。

#### router.py — 智能路由（按任务特征选模型，**主动选择层**）

`RoutingProvider` 持有 `{名称: provider}` 池，每次 `send`/`stream` **调用前**由 `Router`
根据请求内容（消息历史 + 工具列表）**主动**决定用哪个 provider——与 `SwitchableProvider`/
`ProviderChain` 的「出错才切换」正交（本类在无错误的正常路径上做主动选择）。对 `AgentLoop`
透明（实现 `BaseProvider` 协议）。

- `HeuristicRouter`：**默认尽量用 fast（只按当前请求判定）**，决策顺序 = ① **推理链续接**
  （**默认关闭**，`continuity=True` / `ROUTING_REASONING_CONTINUITY=true` 时启用：**上一轮
  实际选中 pro** 且历史里仍有 ASSISTANT 的 `reasoning_content` → 继续 pro；默认关是因为它
  会把会话钉在 pro，与「尽量 fast」冲突）→ ② **复杂度关键词**（扫描**最近一条 USER
  消息**，反向查找以跳过尾部 ASSISTANT/TOOL，命中 `DEFAULT_REASONING_KEYWORDS` 或自定义词
  → pro）→ ③ **中档关键词**（配置 mid 档时，同样只看最近一条 USER 消息 → mid）→ ④ 兜底
  fast。关键词范围是「最近一条 USER 消息」而非「全部历史」——历史命中过关键词不会让后续
  轮次（含简单追问）持续走 pro；反向查找则保证同一轮 tool 调用后（尾部是 TOOL 结果）仍
  能取到本轮请求，不漏判。判据 ① 以「上一轮是否 pro」而非「历史有无
  `reasoning_content`」为准——DeepSeek v4 的 flash/pro 都是思考模型、都返回该字段，按后者
  会让走过一次 flash 后永久锁死 pro；`RoutingProvider._pick` 经可选钩子 `note_selection`
  回传实际选中项（供判据 ①）。内置复杂度表不含「为什么」「解释」「why」「explain」等纯疑问词
  （pro 主要误判源），需要时用该池 `ROUTING_POOLS` 的 `keywords` 追加回来。纯启发式（非安全机制）。
- `RoutingProvider.send/stream`：`_pick()` 决策 → 未知名称回退 `default` → 委托。
- `last_decision`（`RouteDecision`）记录最近一次决策，供日志/`/route` 命令观测。
- **决策可见性**：`active_route_reason()` / `annotate_route()` 把最近一次决策的 reason 附到
  状态行模型名后（如 `deepseek-v4-pro←keyword:分析`），使「**为什么**是这个模型」当场可解释
  ——关键词命中、推理链续接、`/route` 强制、池外名称回退四种来源在状态栏上原本完全同形，
  只能靠猜或翻日志。未启用路由 / 尚未决策时 `annotate_route` 原样返回模型名（展示串逐字节
  不变）；CLI 状态行（`cli_display._format_status`）与 GUI 状态栏共用该标注。兜底理由
  `default_fast`（「没命中关键词、用默认档」）**不进展示层**——状态行不贴、`/route` 的
  `last decision` 行不显示括号内理由（`display_reason()` 是唯一白名单入口，两处共用）。
  它不解释任何东西，还易被误读成模型名；需要观测时看日志（`active_route_reason()` 仍
  原样返回 `default_fast`）。
  `/route <name>` 的强制与 `last_decision` **同步刷新**（`set_force` 即时写入 `forced`；
  清空强制时置空决策）——否则命令之后、下一次 LLM 调用之前，提示符会显示「新模型 +
  旧理由」的混合态（模型已换 luna、理由还是上一次的 `keyword:分析`），据此无法判断
  到底强制了没有。
- CLI：路由池是**声明式**的——`ROUTING_POOLS`（JSON）按 provider 条目名声明池：
  档位（池内名 → 模型名）、角色映射（fast/mid/pro → 池内名）、默认档、各档追加关键词、
  `base_url` 覆盖。`_build_provider` 对每个条目查 `Settings.routing_pool_map`：命中即构建
  `RoutingProvider`（规格由 `RoutingPoolSpec` 校验，`types.py`），否则单模型条目；两种情况
  都照常放入 `SwitchableProvider` 池（Multiple providers Choose / `/model` 切换不受影响）。
  **新增/调整档位、模型名、角色、关键词全部只改配置，无需改代码**（新增 provider 条目仍需
  代码接入凭据）。路由池**只有这一个入口**：条目出现在 `ROUTING_POOLS` 里即为启用该池；
  旧版按 provider 的开关（`ROUTING_ENABLED` / `ROUTING_FAST_MODEL` / `ROUTING_PRO_MODEL` /
  `ROUTING_REASONING_KEYWORDS` / `GPT_ROUTING_*`）已移除。全局仅保留
  `ROUTING_REASONING_CONTINUITY`（所有池的续接默认值，可在池内覆盖）。
  `/route <池内名>` 命令解包嵌套路由、展示当前生效池与最近决策；状态行同一决策另见
  `active_route_reason`。

### 4.4 Tool 系统 (`tools/`)

#### decorator.py — @tool 装饰器

```python
@tool
def shell(command: str) -> str:
    """Execute a shell command."""
    ...

# 自动提取：
#   name = "shell"
#   description = "Execute a shell command."
#   parameters = {"type": "object", "properties": {"command": {"type": "string"}}}
```

- 从函数签名 + 类型提示 + docstring 自动生成 `ToolSchema`
- 注册到 `ToolRegistry`

#### registry.py — 工具注册中心（单例）

| 方法 | 说明 |
|------|------|
| `get()` | 获取单例实例 |
| `register(schema, handler)` | 注册工具 |
| `get_handler(name)` | 查找执行函数 |
| `enable(name)` / `disable(name)` | 启用/禁用工具 |
| `unregister(name)` | 注销工具（MCP 退出时清理注册） |
| `get_schema(name)` | 查询工具 Schema（存在性检查） |
| `enabled_schemas()` | 返回所有已启用的 ToolSchema |

#### safety.py — 安全防护

```
SafetyGuard
  ├── 工具名黑名单（blocked_tools）：对所有工具生效（含 MCP/内置/shell），正则匹配 call.name → 命中拦截
  └── shell 命令检查（仅 "shell"）：BLACKLIST（12 种危险模式 + 自定义）/ WHITELIST
```

工具名黑名单对所有工具生效；shell 命令检查仅对 `shell` 工具生效。违反时抛出 `SafetyViolation`。

#### tools/sandbox/ 包 — 子进程沙箱后端（CommandRunner）

> **Phase 4 C1（2026-09-21）拆分**：原单文件 `sandbox.py` 拆为 `contracts.py`（SandboxTier / CommandRunner Protocol / profile+workspace 注入 slot）、`process.py`（进程监督内核：supervise / kill-reap / `cap_channel` 512KB 截断 / `scrub_sensitive_env` / `reap_subprocess` 有界回收 / `PassthroughRunner` / command_runner slot）、`firejail.py`、`winjob.py`、`session.py`（会话目录 + SandboxSession）；`__init__` re-export 全历史公共名，导入面不变。`CommandRunner` Protocol 补 `available` property（三 backend 形状统一）。`git.py` / `engine/hooks.py` 复用 `reap_subprocess`（有界回收）+ `cap_channel`（截断）内核——超时/取消/回收/截断语义全仓统一；WinJob 补 env 剥离（V1）与有界 wait（V2）。

`shell` 等子进程工具的可注入执行抽象。默认 `PassthroughRunner`（等价 `create_subprocess_shell` 直接执行）；`SANDBOX_REQUIRED` 路径下 `ToolExecutor.execute_in_sandbox` 经 `bind_command_runner` + `bind_sandbox_profile` 注入配置的后端与 profile 名。注入走 `RuntimeSlot`（contextvar），与 memory/skills 等工具族一致；`DIRECT` 路径不 bind，取默认 Passthrough。

**FirejailBackend（2026-07-20 硬化）：** 新增 `profiles` dict（profile 名 → firejail 参数映射），供 `PolicyEngine` 裁决出的 profile 名选用（配置注入见下段；原设想的 `RoleSpec.sandbox_profile` 激活路径从未落地，该死字段已于 2026-09-18 删除）；`shutil.which` 构造期检测 firejail 可用性，不可用时 `run()` 优雅降级到 Passthrough（warn + 不崩溃）；Linux 进程组 killing（`start_new_session` + `os.killpg`）解决 `sh -c "cmd &"` 子孙泄漏；自动 `--private=<workspace_root>` OS 级文件系统隔离。⚠ `FirejailBackend` 仅隔离 shell 子进程、Linux-only、非完美边界——须 OS 级沙箱兜底。

**沙箱硬化配置接入（2026-09-17）：** 此前 `FirejailBackend.profiles` 与 `PolicyEngine.sandbox_profiles` 在生产装配下恒空（仅测试/库消费者手工注入），profile 名产生零参数。本次把两段映射接入配置（**默认全关闭，默认行为逐字节不变**）：① `SANDBOX_PROFILES`（JSON：profile 名 → firejail 参数表，如 `{"default": ["--seccomp", "--caps.drop=all"]}`）经 `container.default()` 传入 `FirejailBackend.profiles`——高级隔离参数（--seccomp/--caps 类）由此声明，默认关闭；② `SANDBOX_TOOL_PROFILES`（JSON：工具名 → profile 名）叠加进 `PolicyEngine.sandbox_profiles`，per-tool 差异化选用 profile（与代码内映射同形状，不引入新抽象）；③ 资源限额 `SANDBOX_MEMORY_LIMIT_MB` / `SANDBOX_CPU_SECONDS`（0=关闭）——firejail 映射 `--rlimit-as` / `--rlimit-cpu`（排在 profile 参数后、`--` 前），WinJob 映射 `JOB_OBJECT_LIMIT_JOB_MEMORY` / `JOB_OBJECT_LIMIT_PROCESS_TIME`（与恒开的 KILL_ON_JOB_CLOSE 按位或）。**限额触发为显性失败**：子进程被终止 → 非零退出码经正常结果回传（对齐超时 `exit_code=-1` 先例），不静默截断输出。JSON 配置坏行/坏条目告警丢弃（对齐 `routing_pool_map` 容错）。**2026-09-18 补齐进程数限额 + 修一处常量 bug**：④ `SANDBOX_NPROC_LIMIT`（0=关闭）——firejail 映射 `--rlimit-nproc`，WinJob 映射 `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` + `ActiveProcessLimit`（该 struct 字段早已声明却从未赋值）；⚠ 两后端语义不对称：firejail 侧底层 `setrlimit(RLIMIT_NPROC)` 按**真实 UID** 计数（非 per-sandbox 作用域），WinJob 侧才是 job 作用域，故默认关闭；⑤ 修正 WinJob 常量表——`JOB_OBJECT_LIMIT_PROCESS_TIME` 原误写为 `0x8`（实为 `ACTIVE_PROCESS` 的位，正确值 `0x2`），导致配了 CPU 时间限额时置位的是 ACTIVE_PROCESS 而 `ActiveProcessLimit` 仍为 0：时间限额不生效、反而施加「活动进程上限 0」。以上均 defense-in-depth，**非真正安全边界**，须 OS 级沙箱兜底。

**沙箱会话目录（FR-1，2026-08-26）：** `Settings.sandbox_session_workspace`（env `SANDBOX_SESSION_WORKSPACE`，默认 False）开启后，`EngineContainer.create_run_context` 经 `sandbox_session_dir(run_id)`（幂等目录解析；run_id 非法——空串/含分隔符/`..`/绝对路径——抛 `ValueError`）为每个 run 幂等创建 `<workspace_root 回退链>/.heagent/sandboxes/<run_id>/` 并写入 `RunContext.metadata["sandbox_workspace"]`——**根锚定 workspace_root 回退链**（参数→container→policy→cwd）而非进程 cwd，目录落在 file 工具围栏内；目录创建失败**显性抛异常**（消息含 try 外预推导的目标路径）、严禁静默降级。开关关闭时清除 caller 预含键、不建目录、不 bind，argv/cwd 与现状逐字节一致。`ToolExecutor.execute_in_sandbox` 检测到该键并校验（非 str/空串不 bind；目录缺失 bind 前抛 `RuntimeError` 显性失败）后经 `bind_sandbox_workspace` 送达后端——Firejail 复用既有 `_build_argv(workspace_root=)` 通道**优先**作为 `--private` 根（优先于构造期 workspace_root），WinJob 将其作为子进程 cwd（**目录约定 only，零文件系统/网络隔离**，非安全边界）；`sandbox_runner=None` 时记 "sandbox_workspace ignored" warning 照旧透传；对子类 override 经 `inspect.signature` 探测做旧签名兼容。firejail 不可用时目录照常解析创建、后端照旧 warn + Passthrough 降级。

**沙箱后端强度分级（FR-2，2026-08-26）：** 引入 `SandboxTier(StrEnum)` 四档强度枚举 `passthrough(0) < job(1) < firejail(2) < container(3)`——`PassthroughRunner`→`passthrough`、`WinJobBackend`→`job`、`FirejailBackend`→`firejail`；`container` 档（OS 级强隔离，如 Docker/bubblewrap/AppContainer）为预留枚举、当前无实现后端。`CommandRunner` Protocol 新增 `tier` 属性，执行路径经 `ToolExecutor._runner_tier()` 查询当前后端档位（无后端→`PASSTHROUGH`；自定义 runner 缺 `tier`→`PASSTHROUGH` fail-safe），并随 `SANDBOX_REQUIRED` emit 事件 `details["sandbox_tier"]` 可观测。审批降级（`SandboxTier.can_relax_approval`）仅 `container` 档返回 True——弱后端（passthrough/job/firejail）一律维持原审批要求（NFR-2 测试锁定）；该判定点当前**未接入** `PolicyEngine` 裁决（container 后端落地时的独立工作）。

**沙箱 env 豁免（FR-3，2026-08-26）：** `scrub_sensitive_env(env, *, allowlist=...)` 新增 `allowlist` 参数（精确变量名、大小写不敏感）——命中 allowlist 的变量即使匹配敏感后缀也保留，其余仍剥离；未配置时行为与现状逐字节一致（默认全剥离）。配置入口 `Settings.sandbox_env_allowlist`（env `SANDBOX_ENV_ALLOWLIST`，逗号分隔）经 `sandbox_env_allowlist_set` property 解析，`_run_subprocess_shell`/`_run_subprocess_exec` 经 `_spawn_kwargs()` → `_env_allowlist()` 读 Settings 传入（2026-09-15 起两条路径共用同一 kwargs 构造，env 剥离不会分叉）。豁免仅作用于 env 剥离，不影响 `path_safety` 凭证 deny 与 `SafetyGuard` 凭证路径拦截。

**SandboxSession 会话生命周期（FR-4，2026-08-26）：** 引入 `SandboxSession` 会话作用域——同一 run 的连续 shell 命令共享同一 session workspace（40.1 目录）并**跨命令保持 cwd**：`run()` 以「cd 前缀 + 末尾上报（POSIX `printf $PWD` / cmd `cd`）回填 `session.cwd`」包装命令，多步操作（写→编译→运行）自然衔接；包装同时**保持用户命令退出码**（POSIX `exit "$__rc"` 复原 / Windows `call echo %^ERRORLEVEL%` 经 marker 行带回并由 `run()` 回填 `exit_code=`，修复包装后失败命令恒 `exit_code=0` 的缺陷；`exit N` 直退类命令 marker 缺失属固有限制，rc 仍正确）。会话经 `get_or_create_session(run_id)` 按 run 缓存、`bind_sandbox_session` 送达 shell handler（handler 优先走 session）；`EngineContainer.close_run`（`AgentLoop._persist_and_cache` 尾部调用）teardown 按 `sandbox_session_keep`（默认 False=删除）清理会话目录。⚠ 会话非安全边界：cwd 保持仅「cd 前缀 + 尾捕获」约定，WinJob 无文件系统隔离、Firejail 亦非完美边界——须 OS 级沙箱兜底。

**E40 补齐（2026-09-15，四项）：** ① **孤儿目录 GC（E40-D1）**——crash / SIGKILL 的 run 不走 teardown，其 `<workspace>/.heagent/sandboxes/<run_id>/` 由 CLI/GUI 启动时的 `housekeeping.prune_sandbox_dirs` 按 `sandbox_dir_retention_days`（默认 7 天）回收：判活取「目录 + **直接子项**」最新 mtime（正在写的 run 不被删；只扫一层，成本有界），非目录条目与符号链接一律不动（符号链接记 warning，绝不穿透），单趟删除数有上限、删除失败记 warning 留待下次启动。约定根由 `tools.sandbox.sandbox_sessions_root(workspace)` 单一表达（创建方与回收方共用，防空漂移）。② **目录对模型可见（E40-D2）**——`_build_system()` 在本 run 会话目录**真正生效**（存在真实沙箱后端）时注入 `<shell-workspace>` 块，告知绝对路径与「file 工具相对路径按 workspace root 解析」的差异；开关开但后端缺席（passthrough）时**不报路径**（与真实 cwd 不一致比不提示更坏）。③ **WinJob cwd 可测缝（E40-D3）**——子进程启动收敛到 `_winjob_spawn(command, workspace)` 单点（未 bind 时不传 `cwd`，与改动前逐字段一致），使该决定可在非 Windows 平台被断言（原实现写在 `run()` 两条 `Popen` 分支里，Linux CI 整段跳过）。④ **CLI/GUI 平权（E40-D4）**——`--sandbox-session-workspace` / `--sandbox-session-keep`（含 `--no-...`）三态覆盖 `Settings`（未传标志时行为与改动前逐字节一致）。

#### call_summary.py — 工具调用「作用对象」摘要（纯展示辅助）

`summarize_tool_call(name, arguments)` 把一次调用归纳为**单行**说明：读写哪个文件、
执行哪条命令、抓哪个 URL、委派给哪个角色的子 Agent（如 `docs/frame.md`、
`src — *.py`、`0 9 * * * — 生成 AI 新闻摘要`、`coder — 实现登录模块`）。
该摘要出现在四个展示面：CLI 提示行 `[calling <tool> → <target>]`
（`cli_display._print_stream_event`，在执行**前**发出）、TUI 聊天日志、工具事件的
`target` 字段（`EngineEvent.target`——独立成段而非埋进 `details`，见 4.12）、以及状态栏的
`🔧 <tool> → <target>` 段（`loop.active_tool`，暂停/恢复时据此判断卡在哪个工具）、
GUI 状态栏与 TUI 聊天日志（`gui/bridge.py` 流式路径与 `gui/observers.py` 引擎事件路径同口径）。
单次模式（`python -m heagent "..."`，走 `run()` 无流式事件）跑完另由
`cli_display.show_tool_activity` 回显 run 级台账 `loop.tool_activity`（**调用尝试**：
执行前登记，被阻止 / 命中缓存的调用同样留痕；同目标去重、超 20 条折叠为一行计数），
保证「执行中没有提示行」的场景事后仍有记录。

纯函数、零 heagent 依赖，是该信息的**唯一来源**（`AgentLoop.run_stream` 的流式事件、
`ToolExecutor` 工具事件的 `target` 字段、`loop.active_tool` 与 `tool_activity` 共用，
避免多处映射漂移）。契约：
**永不抛异常**（参数形状异常退化为空摘要，展示逻辑不得中断 agent 循环）、只回显参数
不推断语义、单行折叠（换行 / 连续空白折叠为单空格，防终端串行）。长度：路径类
72 字符、自由文本（子 Agent 任务 / 记忆事实）40 字符，超长加省略号；**shell 命令不截断**
（全文保留，只折叠空白）——截断后的命令无法判断「它到底跑了什么」，是审查与审计场景里
信息损失最大的一类参数（`_NO_TRUNCATE_TOOLS`）。

`<tool> → <target>` 的**拼接**同样同源：`activity_label(name, target)`——CLI 提示行 / 状态行、
GUI 聊天日志 / 状态栏、工具活动台账统一经它拼接。各展示层自行拼箭头曾是漂移源头
（2026-09-14 复核：GUI 两条事件路径一个带 target、一个不带，同一状态字段被互相覆盖）。

#### path_safety.py — 工作区路径校验（文件工具）

文件类工具（`file_read` / `file_write` / `file_search` / `content_search`）写入前调用
`resolve_workspace_path(path)`，解析后若逃逸出当前工作区根（含 `../` 越界、绝对路径指向外部），
抛出 `WorkspacePathError`。`workspace_root()` 默认取 `Path.cwd()`，`set_workspace_root()`
提供测试可注入的覆盖入口（无需 monkeypatch cwd）。

围栏算法集中在 `resolve_under_root(path, root)`：`engine.policy._validate_paths()` 的执行前
预检与各 file 工具的 handler 守卫（`resolve_workspace_path`）共用同一实现——两层是有意的纵深
防御（policy 预检 + handler 守卫），不再是两份可各自漂移的副本。root 来源策略是两层唯一有意
差异：policy 用 `context/self.workspace_root`（皆空则放行），handler 用 `workspace_root()`
（RuntimeSlot → override → cwd）。

另含**凭证 deny**与**内部状态读 deny**（借鉴 hermes `file_safety.py`，2026-08-24）：`build_write_denied_paths` / `build_write_denied_prefixes` 拦截对凭证文件（`~/.ssh/*` / `~/.aws/*` / `.env` / `.netrc` 等）的写入；`check_read_denied` 拦截对 secret-bearing 文件名（`.env` 等）与 `.heagent/` 内部状态目录（sessions/ledger/runs/memory/skills）的读取。**项目级可配置入口（2026-09-17）**：`.heagent/path_deny.json`（workspace 围栏锚定 + 进程级懒缓存）允许收紧（追加 deny 项）或放行显式列举项（精确路径 / basename 豁免；内部状态目录 deny 不接受豁免），无整体关闭入口、fail-safe 默认仍拒。deny 与围栏是**并列的独立层**（先围栏后 deny），git 工具只走围栏不接 deny。⚠ 均为 defense-in-depth 启发式层，非真正安全边界——shell 工具仍可 `cat .env` 绕过，须 OS 级沙箱兜底。

#### edits.py — 编辑原语支撑（行尾保真 / diff 回执 / 落盘前快照）

`file_write` / `file_edit` 共用的编辑护栏（2026-09-14 新增）：

- **行尾与 BOM 保真**：`read_text_file` / `write_text_file` 走 `read_bytes` / `write_bytes`
  ——`Path.read_text/write_text` 默认做 universal-newline 翻译（Windows 上把 LF 文件写成 CRLF），
  编辑类工具若破坏行尾即是真实事故面（本仓 2026-09-08 行尾治理）。读写两侧都保真，才能保证
  「只改一处、其余字节不动」。`file_read` 与 `file_edit` **共用同一文本形态**（去 BOM + 行尾
  归一为 `\n`），使模型从 `file_read` 复制的片段可直接用于匹配（否则 BOM 会造成隐形失配）。
- **diff 回执**：`render_diff` 回 `+N -M` 与有界 hunk 预览（行数 40 / 字符 4000 双限 + 截断标注）；
  `file_write` 回执含 diff，不再是裸的 `wrote N chars`——模型与用户都能在回执里自证「实际改了什么」。
- **落盘前快照**：`snapshot_before_write` 复制旧字节到
  `<workspace>/.heagent/tmp/edit-snapshots/<run_id>/` 并追加 `manifest.jsonl` 台账
  （`at` / `op` / `path` / `snapshot` / `bytes`）。run 绑定由 `AgentLoop._runtime_scope` 经
  `bind_edit_snapshot_run(run_context.run_id)` 完成；未绑定（直接调工具 / 子进程 / 测试）退化为
  工作区级共享目录。快照是 **best-effort**：文件超 2 MB 或 I/O 失败均跳过快照、不阻断编辑
  （回执不出现 snapshot 行，仅记日志）。快照 GC 见「五、已知缺口」。
- ⚠ 行尾保真与快照均属**可用性**护栏，非安全边界：快照目录位于 workspace 内、可被 shell 删除。

#### builtins/ — 25 个内置工具

**基础工具（6 个）：**

| 工具 | 文件 | 功能 |
|------|------|------|
| `shell` | `shell.py` | 执行 shell 命令 |
| `file_read` | `file.py` | 读取文件内容 |
| `file_write` | `file.py` | 全量覆写文件（回 `+N -M` diff 摘要，写前留快照） |
| `file_edit` | `file.py` | 精确替换文件中的唯一片段（失配/歧义即报错，磁盘零改动） |
| `file_search` | `search.py` | 按文件名搜索 |
| `content_search` | `search.py` | 按内容搜索文件 |

**技能管理工具（7 个，`skills.py`）：**

| 工具 | 功能 |
|------|------|
| `skill_create` | 创建新技能（SKILL.md + 目录结构；支持 triggers / negative_triggers / priority 匹配元数据） |
| `skill_update` | 更新已有技能内容（仅改非空字段） |
| `skill_list` | 列出所有已注册技能 |
| `skill_load` | 按规范化技能名只读完整 SKILL.md（不执行 steps/scripts、不读取任意资源；受手动读取 token 预算限制） |
| `skill_delete` | 删除指定技能 |
| `skill_curate` | 列出超 N 天未使用的过期技能（含使用次数/最后使用时间） |
| `skill_archive` | 归档技能到 `.archive/`（不参与匹配/列出，可恢复） |

**记忆管理工具（2 个，`memory.py`）：**

| 工具 | 功能 |
|------|------|
| `fact_add` | 保存一条事实到长期记忆 |
| `profile_update` | 更新用户画像的指定部分 |

**Cron 管理工具（3 个，`cron.py`）：**

| 工具 | 功能 |
|------|------|
| `cron_add` | 创建定时任务（cron 表达式） |
| `cron_list` | 列出所有已调度任务 |
| `cron_remove` | 删除指定任务 |

**子 Agent 委派工具（3 个，`subagent.py`）：**

| 工具 | 功能 |
|------|------|
| `task_delegate` | 将单个任务委派给隔离的子 Agent（可传 `role`=planner/coder/tester/supervisor 角色化，或 `system` 自定义提示词；独立上下文+迭代预算）执行；**返回结构化 JSON** `SubTaskOutcome`（status ok/failed/error + role/task/iterations/run_id/output，P5-3） |
| `task_parallel` | 并行执行多个子任务（`tasks_json` 传 JSON 数组，`run_parallel()` 汇总；同 `role`/`system`）；返回 `{"status": ok/partial/error, "outcomes": [SubTaskOutcome...]}`（P5-3） |
| `task_status` | 读回本 run 已完成的委派步骤（`run_context.metadata['completed_steps']`，含 iterations/run_id，跨窗口重置存活，P2/P5-3） |

**Web 工具（1 个，`web.py`）：**

| 工具 | 功能 |
|------|------|
| `web_fetch` | 抓取 HTTP URL 内容（`@tool(read_only=True)`，`max_length` 截断；SSRF 围栏 + 流式截断 + 重定向再校验） |

**Git 工具（4 个，`git.py`，均 `@tool(read_only=True)`）：**

| 工具 | 功能 |
|------|------|
| `git_status` | 仓库工作区状态 |
| `git_diff` | 提交/工作区差异 |
| `git_log` | 提交历史 |
| `git_blame` | 行级作者追溯 |

技能工具在 `AgentLoop` 接收 `SkillStore` 时激活；记忆工具在接收 `FactStore`/`ProfileStore` 时激活；
Cron 工具在接收 `JobStore` 时激活；子 Agent 工具由 `AgentLoop._runtime_scope` 在每次 run 注入委派回调（`agent/delegation.build_subagent_delegates`）激活，run 退出即解绑（单次与交互模式均如此）。委派结果经 `_record_step()` 写入 supervisor 的 `metadata['completed_steps']`（含 iterations/run_id，跨窗口重置存活）。未注入时工具返回 `status=error` 结构化错误，不抛异常。`task_delegate`/`task_parallel` 另受**递归深度闸门**约束：当前 loop 的 `depth` `>= Settings.subagent_max_depth`（默认 3）时直接返回 `status=error`、不再构造子 Agent，防止 LLM 自我委派无限递归；根 loop `depth=0`，SubAgent 创建的子 loop 为父深度 +1。子 Agent 的迭代预算按「显式参数 > 角色显式声明 > `Settings.subagent_max_iterations`（默认 20）」解析；角色未声明即跟随配置（内置 `tester` 已改为不声明，使验证器预算可调）。

### 4.5 上下文管理 (`context/`)

#### loader.py — 上下文文件分层扫描

| 函数 | 说明 |
|------|------|
| `load_context_files(cwd, *, max_bytes=None, user_level=None, home=None)` | 分层扫描并渲染（无命中返回 None）；其余参数为测试/调用方覆盖，默认取 Settings |
| `collect_context_files(cwd, ...)` | 同上但返回结构化 `ContextBundle`（files/omitted/bytes_used），供断言层序与预算行为 |
| `_level_dirs(start, *, max_levels=8)` | 由外到内的目录链 `[仓库根, …, cwd]`；不在仓库内时为 `[start]` |

**分层发现语义（对齐 Codex 的 `AGENTS.md` 约定）**：①**仓库边界**——自 `cwd` 向上找 `.git`/`.hg`，命中即纳入该级并停止上溯（`max_levels=8` 超限则退化为单层，不做无界上溯）；不在仓库内时只扫 `cwd` 一层，**既有行为逐字节不变**。②**层序由泛到专**——仓库根在前、`cwd` 在后，同一层内保持既有优先级 `.heagent/CONTEXT.md` > `AGENTS.md` > `CLAUDE.md`；段落标题为相对最外层目录的 POSIX 路径（`## sub/AGENTS.md`），最外层即旧标签本身。③**用户级文件** `~/.heagent/AGENTS.md` 由 `CONTEXT_FILES_USER_LEVEL` 控制，**默认关闭**（全局文件静默影响每个项目，且会让测试依赖开发机 home）；标题固定渲染为 `~/.heagent/AGENTS.md`，不泄绝对路径。④**字节预算** `CONTEXT_FILES_MAX_BYTES`（默认 32768，Codex 同量级）——超预算时**近端优先**（越靠近 cwd 越具体），单段放不下但预算 ≥1024 字节时保留头部并按**悲观标记长度**预留，末尾追加 `… (truncated — kept the first N of M bytes)`；整段丢弃者汇总为一行 `(context files omitted: N — CONTEXT_FILES_MAX_BYTES=… exhausted; raise the budget to include: …)` 并打 `logger.warning`，**绝不静默**。坏编码文件按不可读处理并告警，不打断 run。

#### tokens.py — Token 计量（真实 tokenizer + 在线校准，P0-3）

| 函数 | 说明 |
|------|------|
| `count_tokens(messages, *, model=None)` | 真实 tokenizer 优先，其次**校准后**的启发式；`model` 决定 encoding 与校准系数 |
| `note_actual_usage(model, *, estimated, actual)` | 用 provider 真实 usage 回收校准系数（指数滑动平均，按模型记录） |
| `tokenizer_backend(model)` / `calibration_factor(model)` | 当前后端名 / 当前系数（诊断与状态展示） |
| `reset_calibration()` | 清空系数与 encoding 缓存 |

后端口径由 `Settings.tokenizer`（`TOKENIZER`）控制：`auto`（默认）= 装了 tiktoken 就用真实
encoding（模型名不被识别时退 `cl100k_base`），否则用 CJK 感知启发式；`estimate` = 强制启发式；
`tiktoken` = 强制真实（依赖缺失时告警一次后回退）。encoding 按模型缓存（含「不可用」这一结果，
避免反复尝试导入）。

校准：`AgentLoop._call_provider` 在拿到真实 `usage.prompt_tokens` 时调用 `note_actual_usage`——
这是**唯一**校准入口（非流式调用必经此处；流式 usage 缺失时无样本可学）。坏样本被丢弃
（`actual<=0`，或比值超出 0.2~5），因为坏样本会把压缩阈值带偏。启发式路径返回
`round(raw × factor)`，两条路径量纲因此可比。

⚠ 计量结果直接喂给压缩阈值与窗口重置判定：偏差会放大成「该压缩时没压缩（撞 API 400）」
或「提前压缩、白丢上下文」，故不再满足于纯估算。

#### compressor.py — 上下文压缩

Token 用量 ≥ `compression_threshold` 时，通过 LLM 摘要旧消息，防止上下文窗口溢出。

摘要提示词为**结构化四段**（`STRUCTURED_SUMMARY_PROMPT`，公开名）：`## Goal` /
`## Changed files` / `## Todo` / `## Constraints and failures`，并要求标识符、路径、命令与
报错**逐字保留**。旧版只要「一段话 + 保留 key facts」，实测会把「改过哪些文件、还剩什么
没做」这类**可重放状态**揉成模糊叙述，压缩后接着干时容易重做已完成的改动或丢掉未完成的
步骤。`window_reset.py` 的 `DEFAULT_SUMMARY_PROMPT` 直接复用该常量（此前两处各写一份、仅
靠注释约定一致）。

#### window_reset.py — 上下文窗口重置（checkpoint-resume）

Token 用量 ≥ 阈值（默认 0.6）时**清窗重建**：把整段对话压成一条进度摘要 + 原始 task + 续跑提示，
写入 `RunContext.metadata['progress_summary']/['segment']`（跨清窗存活），配合 `AgentLoop.resume()`
同 `run_id` 跨多段 context window 续跑。与 `compressor` **互斥**（运行期二选一，`AgentLoop.__init__`
断言，D3）——compressor 原位摘要保留 recent 消息，window_reset 更激进地整窗重置；摘要提示词与
compressor 一致。reset 不重置 iteration/accumulated（防绕预算）。`run`/`run_stream` 在工具消息追加后检查触发。
CLI 经 `CONTEXT_STRATEGY`（`compressor`/`reset`）二选一接线，`WINDOW_RESET_THRESHOLD` 控制重置触发阈值（见 cli.py `_build_context_strategy`）。

#### session.py — 会话持久化

`.heagent/sessions/<session_id>.json` 存储/恢复**对话历史**（消息列表）。交互模式下通过 `session_id` 自动保存/恢复。

> 注意：另有一套 `engine/store.py` 的 `RunStore`（`.heagent/runs/<run_id>.json`）保存**单次运行快照**（含上下文 / 结果 / 最终答案），见 4.12。两者用途不同——session 是跨轮对话历史，RunStore 是单次 run 的可恢复快照。

### 4.6 记忆系统 (`memory/`)

#### facts.py — 事实存储

`.heagent/memory/MEMORY.md`，70% 关键词重叠去重。通过 `fact_add` 工具由 LLM 自主保存（**append-only**）。

注入侧有字节预算 `memory_inject_max_bytes`（默认 49152，0=不限制）：`_memory_block` 按文件顺序累计`- <fact>` 的字节数，超预算保留**前部**条目并在块尾追加省略标注（含省略条数/总条数/预算值）同时打 warning——绝不静默；文件本体不被修改，超预算条目仍在盘上，整理该文件即释放预算。（2026-09-23 实测：无预算时 336 KB / 170 条 = 每轮 89 183 token 的 SYSTEM 前缀，整理后 33 KB / 81 条 = 8 591 token。）

#### memory/skills* — 技能存储

> **Phase 4 C4（2026-09-21）拆分**：原单文件 `skills.py` 拆为 `skill_models.py`（模型 + `parse_skill_md` + 名称校验）、`skill_rewrite.py`（渲染 / `body_survives_rerender` / frontmatter 就地改写）、`skill_catalog.py`（匹配 + 过期盘点，以 store 为数据源的纯函数）、`skill_store.py`（`SkillStore` 门面）；`skills.py` re-export 兼容。`SkillStore` 文件读取走 `path_safety.open_text_under_root` 单一安全入口（契约测试钉 `os.open` 白名单 = path_safety + persist 锁文件）。

`.heagent/skills/<name>/SKILL.md`，HermesAgent 标准目录结构（可选 `templates/`、`references/`）。frontmatter 可选 `triggers`、`negative_triggers`、`priority`：负向触发优先排除，显式触发优先于常规相关度，随后按相关度、priority、名称稳定排序。常规匹配使用无依赖的混合 tokenizer：ASCII 标识符完整分词，CJK 使用二/三字片段（避免空格边界和单字高频误匹配）；旧 Skill 缺新字段时退化为原有 `pattern + tags` 相关度。自动注入同时受数量上限与可选总 token 预算限制，只注入完整正文、跳过超预算项且仅对最终注入项记录 usage；`skill_load` 可显式按名读取完整技能（同样不截断）。

**重渲染安全性（2026-09-14）：** 渲染器只能表达 `# <name>` / `## Pattern` / `## Steps`，解析器也只读后两节，因此 `record_usage` 先经 `_body_survives_rerender` 判定：正文若含这两节之外的章节（手写角色契约、`deploy_production` 式的阶段说明），改走 `_update_usage_frontmatter`「只就地改写 frontmatter 计数、正文逐字节保留」，避免一次自动匹配即把 130 行契约削成 411 字符空壳；无 frontmatter 时保留原文件并记 `logger.warning`（显性失败，不静默丢计数）。`skill_update` 走同一判定：只改元数据字段（description / tags / triggers / negative_triggers / priority）时就地改写 frontmatter、正文逐字节保留；要求改 `pattern` / `steps` 则抛 `SkillRewriteError(ValueError)` 显式拒绝（工具层转成可读 `Error:` 文案），无 frontmatter 块同样拒绝——至此已无「静默重排正文」的路径（`save()` 仍是显式全量覆写 API，只在创建与无损技能更新时被调用）。

#### profile.py — 用户画像

`.heagent/user/USER.md`，按 section 更新。通过 `profile_update` 工具由 LLM 自主维护。

#### soul.py — 人格系统

两级 SOUL.md 加载：全局 `~/.heagent/SOUL.md` + 项目 `.heagent/SOUL.md`。项目级存在时覆盖全局级，不做合并。

#### dream.py — 离线记忆巩固调度器（Dreaming 模式，epic 外增量）

后台 asyncio 调度器，到点起角色化 `SubAgent(role="dreamer")` 对近期 session 历史 + 记忆库做巩固（去重 / 提炼 / 查证 / 归档），经 memory 工具回写四库，下个会话 `_build_system()` 自然注入。tick 逻辑**模仿而非塞进 `CronScheduler`**（dream 不进 `JobStore`、不是用户 prompt、有专属巩固流程；两者可并存于交互模式后台）。

| 组件 | 说明 |
|------|------|
| `DreamScheduler` | 双触发共用 tick（每 `cron_tick_seconds` 秒）：cron 时刻命中 + idle 超时（距上次 run ≥ `dream_idle_minutes`）；`_dreaming` 互斥（同时最多一个 dream）；`stop()` 带硬上界（对齐 `CronScheduler._await_stop`）；`__init__` fail-fast 校验 `dream_cron` |
| `DreamRunner` | agent 层注入的执行协议（`prompt → DreamResult`）；dreamer SubAgent 由 `cli.py` 组合根构造注入（`memory/` **不导入 `agent/`**，DAG 合规——与 `CronScheduler`+`JobRunner` 同构） |
| idle 计时 | 经 `EventBus` 订阅 `run_completed` 更新 `last_active_ts`（不改 REPL 同步 `input()`）；`_run_dream` finally 兜底重置（防失败/取消 dream 不发 `run_completed` 致每 tick 重燃） |
| session 预注入 | `SessionStore.recent_session_ids()` 按 timestamp 降序取最近 N，截断拼进 prompt（dreamer **不持 `file_read`**，最小权限） |
| `dreamer` 角色 | `RoleSpec` allowed/blocked 双层（见顶层 `roles.py`）；`dream_enabled` 默认 `False`（opt-in） |

事件：`dream_start` / `dream_end`（trigger / success / iterations / run_id）经 `EventBus` 发布，`LoggingObserver` 落日志。

⚠ **安全立场**（与文首声明一致，诚实不造假象）：dreaming = 无人监督 + 联网（`web_fetch`）+ 改持久记忆，比交互式更危险——被污染网页可经 prompt injection 跨会话污染记忆库。`PolicyEngine`/`RoleSpec` 工具白名单均**非真正安全边界**（defense-in-depth 标记/拦截）；`web_fetch` 返回现经 `guard_content` 启发式围栏（Epic 35，2026-08-19：命中内置注入签名加 warning 标记后**透传**，不阻断；与 MCP `bridge_result` 同语义、**非隔离**）。须 OS 级沙箱兜底；OS 沙箱就绪后 dreamer 须迁移进沙箱。

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

一次性任务（`recurring=False`）成功后自动删除。

### 4.8 共享类型 (`types.py`)

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

### 4.9 异常体系 (`exceptions.py`)

```
HeAgentError (base)
  ├── ProviderError      — API 调用失败
  ├── ToolError          — 工具执行失败
  ├── SafetyViolation    — 安全检查拦截
  ├── BudgetExceeded     — 迭代/Token 预算超限
  └── PolicyViolation    — 策略门控拦截（`engine/`）
```

**禁止**抛出裸 `Exception`。

### 4.10 配置管理 (`config.py`)

- `pydantic-settings` 的 `Settings` 类，从 `.env` + 环境变量加载
- **加载优先级（2026-07-14 反转）**：`init > dotenv > env > secrets`——同 key 冲突时 `.env` 胜出，系统环境变量退居兜底（仅填充 `.env` 未声明的键）。此前为 `env > dotenv`（环境变量胜出）
- `get_settings()` 单例访问，`reset_settings()` 用于测试重置
- **运行配置快照（Phase 1，2026-09-21）**：`ResolvedRuntimeConfig`（冻结 `Settings` 子类，集合深拷贝、凭证 `exclude` 不入 repr/JSON）+ `resolve_runtime_config(settings=None, **overrides)`——显式非 `None` 覆盖才生效（保留「显式 `False` 反向压过 env `True`」三态语义），每个字段经 `RuntimeConfigSource` 记录来源（`settings`/`override`）。入口层（`cli._build_loop`/`gui_main`）组装期解析一次，engine（`EngineContainer.runtime_config`，并把实际生效后端记入 `SandboxDecision` 写入 run metadata）与两类 loop（主/cron）共用同一份；`AgentLoop`/`SubAgent` 业务执行（压缩/窗口重置/委派深度/提示词块/技能预算）只读快照，运行中全局 Settings 漂移不影响已创建的运行。`PolicyVerdict.source` 标记裁决来源。业务方法禁止隐式 `get_settings()`；构造期回退与无 run 绑定的工具路径（housekeeping/dream/skills 未绑定回退）除外，详见下表口径。

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `deepseek_api_key` | None | DeepSeek API Key（优先） |
| `active_provider` | None | 默认激活的 provider 条目名（多条目时作为启动选择与 `SwitchableProvider` 的默认项）；未设或该条目不可用 → 回退到第一个可用条目（构建顺序 `deepseek` → `kimi` → `glm` → `ollama` → `openai` → `gpt` → `anthropic`） |
| `openai_api_key` | None | OpenAI API Key |
| `anthropic_api_key` | None | Anthropic API Key |
| `kimi_api_key` / `glm_api_key` | None | Kimi、GLM Provider API Key |
| `openai_responses_api_key` | None | OpenAI Responses API / 中转站 API Key |
| `openai_responses_base_url` | None | Responses API 中转站地址（`wire_api="responses"`，如 `https://www.komapi.top/v1`） |
| `ollama_enabled` | False | 本地 Ollama 条目开关（OpenAI 兼容 `/v1`，显式 opt-in，无需 API Key） |
| `ollama_base_url` | `http://127.0.0.1:11434/v1` | Ollama OpenAI 兼容端点 |
| `ollama_model` | None | Ollama 模型名（启用时必填，否则 fail-fast） |
| `ollama_api_key` | None | Ollama 占位 key（缺省用 `"ollama"`；Ollama 不校验 key） |
| `deepseek_base_url` | None | DeepSeek API 基础 URL |
| `openai_base_url` | None | OpenAI 兼容服务 URL |
| `anthropic_base_url` | None | Anthropic 代理地址 |
| `kimi_base_url` / `glm_base_url` | None | Kimi、GLM API 基础 URL（缺省用内置端点 `api.moonshot.cn/v1` / `open.bigmodel.cn/api/paas/v4`） |
| `anthropic_prompt_caching` | True | Anthropic 提示词缓存（注入 cache_control 断点，FR-3；不兼容代理时关闭） |
| `routing_pools` | "" | 声明式路由池 JSON（任意 provider 条目多档池；改档位/角色/关键词无需改代码） |
| `routing_reasoning_continuity` | False | 推理链续接（**所有池的默认值**，单池可用 spec 的 `reasoning_continuity` 覆盖）：true 时「上一轮走了 pro 且思考痕迹仍在历史中」继续走 pro，否则只按当前请求命中关键词判定 |
| `openai_api_keys` | "" | OpenAI 多密钥池（逗号分隔） |
| `anthropic_api_keys` | "" | Anthropic 多密钥池（逗号分隔） |
| `default_model` | `gpt-4o` | openai（Chat Completions）/ anthropic 条目的兜底模型 |
| `deepseek_model` / `kimi_model` / `glm_model` | `deepseek-v4-pro` / `kimi-k3` / `glm-5.3` | 各 Provider 默认模型（**仅该条目未出现在 `routing_pools` 时生效**；有池时模型由池的 `tiers` 决定，`--model` 亦被忽略并告警） |
| `openai_model` | `gpt-5.6-terra` | gpt（Responses API）条目默认模型（声明 gpt 池时由 `tiers` 决定） |
| `max_iterations` | 50 | Agent 循环最大迭代次数 |
| `max_context_tokens` | 512000 | 模型上下文窗口大小 |
| `max_output_tokens` | None | 单次输出 token 上限（None=不设；本地思考模型建议设） |
| `compression_threshold` | 0.8 | 上下文压缩触发阈值 |
| `context_strategy` | `compressor` | 上下文管理策略：`compressor`=原地摘要压缩（默认）/ `reset`=窗口重置（清窗后 resume 续跑；与 compressor 互斥） |
| `window_reset_threshold` | 0.6 | 窗口重置触发阈值（`context_strategy=reset` 时生效） |
| `shell_timeout` | 120 | Shell 命令超时（秒） |
| `retry_max_attempts` | 3 | 最大重试次数 |
| `retry_base_delay` | 1.0 | 重试基础延迟（秒） |
| `retry_max_delay` | 30.0 | 重试最大延迟（秒） |
| `skill_match_threshold` | 0.3 | 技能关键词匹配阈值（0.0–1.0） |
| `skill_max_auto_invoke` | 3 | 最多自动注入技能数 |
| `skill_max_auto_invoke_tokens` | None | 自动注入技能正文的总估算 token 预算（None 保持旧行为；超预算完整 Skill 跳过而不截断） |
| `skill_max_manual_load_tokens` | 8192 | `skill_load` 单个完整 Skill 的估算 token 上限（超限显式拒绝） |
| `context_files_enabled` | True | 是否自动加载项目上下文文件（分层扫描） |
| `context_files_max_bytes` | 32768 | 上下文文件字节预算；超预算时近端优先保留，被丢弃/截断者显式标注 |
| `context_files_user_level` | False | 是否纳入用户级 `~/.heagent/AGENTS.md`（默认关闭，避免全局文件静默影响每个项目） |
| `events_rollout_enabled` | False | 是否把每次 run 的事件落盘为 `.heagent/runs/<run_id>/rollout.jsonl`（默认关闭；内容含工具原始输出） |
| `memory_nudge_enabled` | True | 是否注入记忆保存提醒 |
| `memory_inject_max_bytes` | 49152 | 注入 `<memory>` 的字节预算（0=不限制）；超预算**按文件顺序保留前部条目**并在块尾显式标注省略条数 + warning，文件本体不改动（`MEMORY.md` 是 append-only 且整份注入，无预算会无界增长） |
| `skill_curator_stale_days` | 30 | `skill_curate` 未显式传 `days` 时的过期天数默认值 |
| `cron_enabled` | True | 是否启用 cron 调度 |
| `cron_tick_seconds` | 60 | 调度器检查间隔（秒） |
| `dream_enabled` | False | 是否启用 dreaming（离线记忆巩固，opt-in；无人监督后台跑+联网+改持久记忆） |
| `dream_cron` | `0 3 * * *` | dream cron 触发表达式（构造期 fail-fast 校验，须 5 字段） |
| `dream_idle_minutes` | 30 | dream idle 触发阈值（分钟，距上次 run 结束；0=禁用 idle 触发） |
| `dream_max_iterations` | 20 | dreamer SubAgent 独立迭代预算（不复用全局 `max_iterations`） |
| `goal_max_iterations` | 20 | `/goal` 单步 SubAgent 最大迭代轮数（步骤可用 `max_iterations:` 覆盖） |
| `subagent_max_depth` | 3 | 子 Agent 委派嵌套深度上限（0=禁止委派；超限工具返回 `status=error`） |
| `subagent_max_iterations` | 20 | 嵌套子代理兜底迭代预算（角色未声明 `max_iterations` 时生效：显式参数 > 角色声明 > 本项） |
| `goal_checkpoint_mode` | `prompt` | `/goal` 检查点策略：自动继续或等待用户 |
| `goal_open_question_mode` | `block` | `/goal` 未决问题策略：阻塞或采用默认值 |
| `goal_workflow_skill` | `he-goal` | `/goal` 工作流包 id（包在自己 `SKILL.md` 里声明 `canonical_id`，按 id/别名解析） |
| `announce_progress` | True | 是否把「▶ 启动 / ✔ 完成 + 状态行」进度公告写到 stderr（false=静音） |
| `dream_session_lookback` | 5 | 预加载近期 session 个数（按 timestamp 降序） |
| `mcp_enabled` | True | 是否启用 MCP server 连接（门控，False 则跳过加载） |
| `mcp_config_path` | `.mcp.json` | MCP server 声明式配置文件路径 |
| `safety_blocked_tools` | `[]` | 工具名黑名单（**JSON 数组**，元素为正则片段、大小写不敏感）：命中即由 `SafetyGuard` 在执行前拦截，对内置 / shell / MCP 工具同等生效（默认空=不拦） |
| `sandbox_backend` | `auto` | Shell 沙箱后端：`auto`（探测 firejail，缺则回退 passthrough）/ `passthrough` / `firejail` / `winjob`（Windows 需显式指定） |
| `sandbox_firejail_path` | `firejail` | firejail 可执行文件路径（PATH 查找或绝对路径） |
| `sandbox_mode` | `workspace-write` | 权限档位：`read-only`（只放行只读工具，未知工具 fail-closed）/ `workspace-write` / `danger-full-access`（跳过围栏与凭证 deny 预检）；非法值回退并告警 |
| `sandbox_network` | False | 是否允许子进程出站；False 时 firejail 追加 `--net=none`，其余后端记「网络隔离未生效」 |
| `run_retention_days` | 7 | `.heagent/runs/` 运行快照（`<run_id>.json` + 配套 `.lock` + `<run_id>/` 产物目录）保留天数；全新 run 启动时清理一次（0=禁用）。`persist.py` 刻意保留 `.lock`（规避 unlink 竞态），本项是 runs 侧唯一回收时机 |
| `ledger_retention_days` | 7 | `.heagent/ledger/` 幂等记录保留天数；全新 run 启动时清理一次（0=禁用） |
| `prune_min_interval_seconds` | 900 | 过期清理的**跨进程节流**：距上次清理不足此间隔就跳过扫描（0=每次都扫）。短命 CLI 进程靠它省掉「每次启动重扫万级目录」 |
| `log_retention_days` | 14 | `logs/` 日志文件保留天数（CLI/GUI 启动时回收；0=禁用） |
| `session_retention_days` | 30 | `.heagent/sessions/` 会话文件保留天数（启动时按 mtime 回收；0=禁用） |
| `edit_snapshot_retention_days` | 7 | `.heagent/tmp/edit-snapshots/` 编辑快照保留天数（启动时回收 run 目录；0=禁用） |
| `sandbox_dir_retention_days` | 7 | `.heagent/sandboxes/<run_id>/` 沙箱会话目录保留天数（E40-D1：崩溃/SIGKILL 的 run 不会 teardown，由启动时回收**孤儿**目录；0=禁用。判活取「目录 + 直接子项」最新 mtime，故正在写的 run 不会被删；单趟有上限、失败记 warning） |
| `sandbox_enforce` | True | 探测到**真实**后端时自动把 `shell` 纳入沙箱工具集并授权当次 run（passthrough 下零行为变更） |
| `tokenizer` | `auto` | Token 计量后端：`auto`（有 tiktoken 用真实 encoding，否则启发式 + 在线校准）/ `estimate` / `tiktoken` |
| `sandbox_session_workspace` | False | 是否为每个 run 建立会话工作目录；CLI/GUI `--sandbox-session-workspace` / `--no-...` 可**双向**覆盖（E40-D4，三态：未传则跟随本项） |
| `sandbox_session_keep` | False | run 结束后是否保留会话目录；同上，CLI/GUI `--sandbox-session-keep` / `--no-...` 可覆盖 |
| `sandbox_env_allowlist` | `""` | 逗号分隔的 env 豁免变量名（如 `GITHUB_TOKEN`）：命中者不参与 `scrub_sensitive_env` 的敏感剥离；空=全剥离 |
| `sandbox_profiles` | `""` | JSON：profile 名 → firejail 参数表（如 `{"default": ["--seccomp", "--caps.drop=all"]}`），高级隔离参数由此声明、默认关闭；坏 JSON/坏条目告警丢弃 |
| `sandbox_tool_profiles` | `""` | JSON：工具名 → profile 名（per-tool 参数粒度），叠加进 `PolicyEngine.sandbox_profiles`；空=现状（缺省落 `default`） |
| `sandbox_memory_limit_mb` | 0 | 沙箱 shell 内存限额（MB；firejail `--rlimit-as` / winjob Job Memory）；0=关闭。触发=子进程被终止 → 非零退出码（显性失败） |
| `sandbox_cpu_seconds` | 0 | 沙箱 shell CPU 时间限额（秒；firejail `--rlimit-cpu` / winjob Process Time）；触发行为同上 |
| `sandbox_nproc_limit` | 0 | 沙箱 shell 进程数限额（firejail `--rlimit-nproc` / winjob Active Process）；触发行为同上。⚠ 语义不对称：firejail 侧按**真实 UID** 计数（非 per-sandbox），winjob 侧为 job 作用域 |
| `tcp_host` | `127.0.0.1` | TCP 入口绑定地址；非回环值启动时日志记一条 `event=exposed` 且 stderr 打印一行告警（判定单点 `network/exposure.py`，不解析 DNS） |
| `tcp_port` | 8765 | TCP 入口端口（1..65535） |
| `tcp_max_connections` | 32 | 同时打开的客户端连接上限（超限的新连接立即收 `rate_limited`，不排队） |
| `tcp_max_inflight_requests` | 4 | 同时在途的 Agent 运行上限（**非等待式**：满即 `rate_limited`，绝不排队） |
| `tcp_max_request_bytes` | 1048576 | 单条请求行最大字节数（`StreamReader` limit 与协议校验共用同一上限） |
| `tcp_idle_timeout` | 60 | 等待完整请求行的秒数（只覆盖读取阶段，不含 Agent 预算） |
| `tcp_request_timeout` | 300 | 单次 Agent 运行的秒数（只覆盖 handler，不含写回与关连接） |
| `tcp_shutdown_timeout` | 5 | `close()` 等待在途任务收尾的秒数；超时后结算登记、强制关闭残留 writer 并记 warning（`asyncio` 无法强杀忽略取消的任务） |
| `http_host` | `127.0.0.1` | HTTP 网页入口绑定地址；非回环值启动时日志记一条 `event=exposed` 且 stderr 打印一行告警（判定单点复用 `network/exposure.py`） |
| `http_port` | 8766 | HTTP 网页入口端口（1..65535；与 TCP 默认 8765 错开，两个入口可同时开） |
| `http_max_connections` | 16 | 同时打开的 HTTP 客户端连接上限（交给 Uvicorn `limit_concurrency`，超限连接被直接拒绝而非排队） |
| `http_max_inflight_runs` | 1 | 同时在途的网页 Agent 运行上限（MVP 单会话单运行；超限提交收 `run_conflict`） |
| `http_max_request_bytes` | 394240 | 单个 JSON 请求体的字节上限（超限收 `request_too_large`）。默认 = `12 × MAX_PROMPT_CHARS(32768) + 1 KiB` 信封，**保证协议允许的最大 prompt 在任何客户端编码下都发得进来**（旧默认 65536 使中文约 2.18 万字就撞 413——2026-09-23 修复；三处默认值的关系由 `tests/network/test_http_protocol.py` 钉住） |
| `http_event_buffer_size` | 512 | 每个 run 的 SSE 事件环形缓冲条数（越过窗口的重连收 `resync_required`） |
| `http_run_history_size` | 64 | 已终结 run 记录的保留条数（淘汰后按其 id 订阅收 `unknown_run`） |
| `http_request_timeout` | 300 | 单次网页 Agent 运行的秒数（超时按 `timed_out` 终结并释放 In-flight 名额） |
| `http_shutdown_timeout` | 5 | 关闭时「停止接收 → 终结在途 run → 关订阅 → 关 listener」全过程的等待上限 |
| `approval_tools` | `""` | 需要交互审批的工具名列表 |
| `hooks_enabled` | False | 是否启用 `.heagent/hooks.json` |
| `plan_mode` | False | 是否启用只读计划模式 |
| `model_pricing` | `""` | 模型价格表 JSON `{"<model>": {"input": 单价, "output": 单价}}`（$/M token）；空=不显示成本 |
| `log_dir` | `logs` | 日志文件目录（相对 cwd），每次启动新建 `heagent-<时间戳>.log` |
| `log_level` | `INFO` | stderr 控制台日志级别：`DEBUG` / `INFO` / `WARNING` / `ERROR` |
| `log_file_level` | None | 文件日志级别；未设（None）时回退到 `log_level` |

---

### 4.11 MCP 集成 (`tools/mcp/`)

MCP server 桥接层（非必要功能，已交付）。连接时发现+注册到 `ToolRegistry`，退出时 unregister。

| 模块 | 说明 |
|------|------|
| `config.py` | `MCPConfig` + `load_mcp_config()`（`.mcp.json` + `${ENV}` 插值） |
| `mapping.py` | `mcp_tool_to_schema()`（namespace `<server>__<tool>`）、`bridge_result()` |
| `client.py` | `TransportOpener` Protocol + `default_transport_opener`（stdio/http 分派 + 握手），构造期可注入（Phase 4 C2） |
| `registry_bridge.py` | `RegistryBridge` — server 工具 + 桥接工具注册/注销单一入口，命名冲突策略（Phase 4 C2） |
| `manager.py` | `MCPClientManager`（生命周期 façade）— 并发连接+发现+注册，单 server 失败隔离；`discovery_failures` 结构化记录失败，cli 渲染 stderr（不隐藏发现错误） |

⚠ MCP 工具与内置工具同等不可信（执行前拦截 + 返回启发式围栏均已落地，但**均非真正安全边界**，须 OS 级沙箱兜底）。

---

### 4.12 运行时引擎 (`engine/`)

`EngineContainer`（DI 容器）注入 `AgentLoop`，工具执行走**策略门控**：`PolicyEngine` 裁决 → `ToolExecutor` 分发 → `SafetyGuard` 检查。子 Agent 经 `parent_run_id` 继承父 `engine`。

| 模块 | 说明 |
|------|------|
| `container.py` | `EngineContainer` — DI 容器，`default(workspace_root=)` 装配全部服务；`create_run_context` 含 FR-1 沙箱会话目录解析（根锚定 workspace_root 回退链，开关开启时写 `metadata["sandbox_workspace"]`、关闭时清除预含键，失败显性抛异常） |
| `context.py` | `RunContext`（run_id/session_id/parent_run_id/workspace_root/iteration/metadata）、`RunStatus`；终态唯一写入口 `RunContext.mark_terminal`（Phase 2 C2：RUNNING→COMPLETED/FAILED 合法、终态再写显性失败；`touch` 是裸 setter 仅供迭代期刷新。取消路径不写终态——status 保持 RUNNING 可 resume） |
| `approval.py` | `ApprovalHandler` 协议 + `ApprovalDecision`/`ApprovalRequest` + `ConsoleApprovalHandler`/`DenyAllApprovalHandler` — 交互式审批闭环（Epic 29） |
| `hooks.py` | `HookConfig`/`HookManager` — 用户可配置事件钩子（PreToolUse/PostToolUse/SessionStart/SessionEnd，Epic 32） |
| `policy.py` | `PolicyEngine` — 准入 allowlist/blocklist、MCP 门控、工作区路径围栏、审批/沙箱裁决 |
| `executor.py` | `ToolExecutor` — 按 verdict 分发；内部串行 `SafetyGuard.check()`；sandbox 路径默认 Passthrough，可注入后端；FR-1 会话目录经 `bind_sandbox_workspace` 送达；FR-2 后端强度档位经 `_runner_tier()` 查询并随 emit 事件 `sandbox_tier` 可观测（见 4.4 sandbox.py） |
| `store.py` | `RunStore` — `.heagent/runs/` 运行快照（async I/O + 原子写），`build_run_tree()` 按 `parent_run_id` 聚合；`prune(retention_days=)` 按 mtime 轻量回收过期快照 + 配套 `.lock` + `<run_id>/` 产物目录（不 load Pydantic），由 `prune_runs_once()` 在全新 run 启动时触发一次 |
| `ledger.py` | `ExecutionLedger` — `.heagent/ledger/` 幂等与租约（async I/O），防 window_reset 重发 + 防并发/重入；`heartbeat()` 由工具在途续租（`agent/tool_execution._renew_ledger_lease`）调用，使「过期 RUNNING = 孤儿」成为 prune 的可靠判据 |
| `observability.py` | `EventBus`/`EngineEvent`/`LoggingObserver` — 运行时事件发布；`LoggingObserver` 经 `safe_logging.safe_log` 落日志（日志故障不改写调用方），并对 `target`/`details` 做启发式脱敏（`redact_secrets`/`redact_mapping`）；`EventBus.emit` 的观察者兜底同样走 `safe_log` |

**已完成：**

- **策略门控链**：`PolicyEngine.evaluate()` → `ToolExecutor.execute()` → `SafetyGuard.check()`，串行执行，职责分离
- **角色化 + checkpoint-resume**：supervisor 委派角色化 `SubAgent`，结构化结果写 `metadata['completed_steps']`；`window_reset` 清窗重建 + `resume`/`resume_stream` 跨窗口续跑；`build_run_tree()` 树形聚合；Schema 级工具隐藏
- **持久化健壮性**：store/ledger 全部 async I/O + 原子写 + 损坏 JSON 容错；可选跨进程文件锁（`EngineContainer(enable_file_locks=True)`）
- **日志卫生（2026-09-23）**：`safe_logging` 两层防线——插桩/best-effort 路径逐调用点 `safe_log`；入口层（CLI/GUI/TCP）配置 logging 时调 `install_logging_fault_guard()`，把 `logging.Handler.handle` 包一层（失败仍走 stdlib `handleError` 诊断，但不向业务传播），故运行栈任意 `logger.*` 不再中断 run。同时 `LoggingObserver` 对 `target`/`details` 按凭证形态掩码——日志行不再出现 `API_KEY=…`/`sk-…` 原文 |

**已知限制：**

- **Sandbox 后端**：`execute_in_sandbox()` 默认 Passthrough 透传；`FirejailBackend` 仅隔离 shell 子进程、非完美边界（见 4.4 sandbox.py）
- **安全边界**：`SafetyGuard` / `PolicyEngine` / sandbox 均非真正安全边界，须 OS 级沙箱兜底（详见 CLAUDE.md 安全声明）

#### 事件传输：JSONL / rollout（`events/`）

对外的**机器可读契约**（对齐 Codex 的 `--json` 事件流）。事件源仍是引擎事件总线（`observability.py`），
`events/` 只做「映射 + 序列化 + 落盘」，**不重复插桩**：

| 入口 | 说明 |
|------|------|
| `RunEvent` / `SCHEMA_VERSION` | 单条事件（`seq` 单调递增 / `ts` / `run_id` / `iteration` / `kind` / `tool` / `target` / `details`）；字段集由 `schema_version` 锚定，改字段须 bump 版本并更新黄金测试 |
| `from_engine_event()` | `EngineEvent` → `RunEvent`；**开集** `kind`（沿用引擎事件名，引擎新增事件无需改协议）；`KNOWN_KINDS` 仅作文档与测试依据，**不作**过滤 |
| `JsonlSink` | 观察者：写 stdout（`--json`）与/或 `<cwd>/.heagent/runs/<run_id>/rollout.jsonl`（`EVENTS_ROLLOUT_ENABLED`，默认关闭）。`handle` 由总线**同步**派发，故只做「序列化 + 一次 write/flush」，不压缩不轮转；写盘失败仅告警，不打断 run；每 run 一个文件 ⇒ 单写者，无需跨进程锁 |
| `assistant_message` | 传输层补充的**唯一**非引擎事件：CLI 在 run 结束后交回最终答案（引擎侧无对应事件） |
| `read_rollout()` / `render_event()` | 读回 JSONL（坏行跳过并告警——crash 截断的尾行不毁整次回放）/ 渲染人读单行 |

**CLI 契约**：`heagent run "…" --json` 时 **stdout 只出 JSONL**（`run_started` 开头、`run_completed`/`run_failed` 收尾、`assistant_message` 交回答案），横幅 / 用量 / 活动回顾等人读信息一律走 stderr，故可直接管道消费；`heagent replay <file> [--json]` 回放。两个动作**互不隐式耦合**：`--json` 不落盘（可自行重定向），落盘不要求输出到 stdout。

**不可信性**：JSONL 的 `target` / `details` 携带命令与工具原始输出（含 MCP / 远端内容），与工具返回**同等不可信**，不得因「结构化」提升信任；rollout 属项目内部状态（`.heagent/` 已 gitignore，path_safety 亦设内部状态读拒），不得改写到可提交路径。

---

### 4.13 Goal 驱动工作流 (`/goal`)

`/goal` 是 CLI 层的机制入口（命令族实现位于 `cli_goal.py`）。当前工作流的唯一方法论入口是
`.heagent/skills/he-goal/workflow.md`（属 `he-goal` 包，由 skill catalog 按 id/别名解析）；步骤声明中的 `role` 再解析对应的 `.heagent/skills/*/SKILL.md`。
声明的确定性装载在 `goal/workflow_loader.py`（`read_workflow(package)`：frontmatter 策略、内嵌步骤、
`required_resources` 模板必需性），产出 `engine/workflow_resource.py` 的 `WorkflowResource` 供
`WorkflowRunner` 消费——装载与执行分离，模板文案零代码副本。
**确定性内核与渲染分离（2026-09-21 Phase 3）**：workflow 校验、gate/prompt 装配、story 选择、
checkpoint 恢复（`restore_runner`，恢复顺序与显性失败语义见其 docstring）与推进 use-case
（`advance`/`pause_resume`，用户可见文案以结构化 outcome.messages 携带）收敛在
`goal/application.py`——click-free（架构契约测试钉死 import 图）；`cli_goal.py` 是渲染薄壳
（messages 逐行 `click.echo(err=True)`）+ 缝宿主（`_goal_session`/`_goal_declarative_prepare`/
`_goal_declarative_advance`/`_goal_runner` 等测试缝原位）+ settings 注入边界。CLI/GUI/cron
三入口仍收敛同一 use-case（GUI 经 `_goal_runner`、cron 经 `_goal_cron_advance`），无复制推进逻辑。
当前工作流的维护说明见[文档索引的「Goal 工作流」章节](README.md#goal-工作流)。

- `/goal <description>` 或 `/goal new <description>` 创建 `_he-output/goals/<goal_id>/brief.md`（只含原始需求）
  和 `current` 指针，然后执行 workflow 的第一个声明步骤；「总结的需求」由 step 01 初步分析后写回同一文档。
  `goal_id` 由 LLM 命名（`goal/naming.py` 一次性 provider 调用生成 kebab-case 名，清洗/校验/`-a`..`-z`
  去重为代码内确定性逻辑）；调用失败或输出非法时 stderr 显性提示并回退固定名 `project`。
  id 字符集锁定 `^[a-z][a-z-]*$`（current 指针校验、cron prompt 解析、旧 job 注销匹配三处下游依赖）。
- `/goal next` 执行一个声明步骤，`story_loop`（当前为 `02-epics.md`）步骤则每次执行一条 Story；`/goal run` 可连续推进，遇到检查点、
  阻塞或失败即停止。
- `/goal status` 只读回显运行状态和目标产物；`/goal reset` 只清除 current 指针并保留目标目录。
- `/goal resume [回复]` 记录用户回复并恢复等待中的步骤；`/goal auto [cron]` 通过 JobStore 复用同一推进路径。
- **跨进程互斥（2026-09）**：`/goal` 全部变更入口（new/next/run/resume/reset/cron 推进）经 `_goal_mutex()`
  复合互斥——进程内 `asyncio.Lock`（`_goal_auto_lock`，快速路径）+ `.heagent/goal.lock` 跨进程文件锁
  （`persist.file_lock`，5s 超时显性失败：手动方收到「另一进程正在推进」提示，cron 下一 tick 自动重试）。
  锁文件刻意保留不删（规避 unlink 竞态）；防「双进程从同一状态各自推进后互相覆盖 brief.md」丢进度。

每个步骤或 Story 都由新的 SubAgent/RunContext 执行。`WorkflowRunner` 负责顺序、输入、输出、checkpoint
和恢复；它不决定 Epic/Story 的拆分方法。

checkpoint id 同时是幂等键（`WorkflowCheckpointStore.save` 对「同 id 不同内容」fail-safe 报错），因此必须是「位置」的
完全函数：`story_loop` 步骤的激活 Story 参与 id —— `<goal>-<run>-step-<N>-story-<index>[-<S-n>]-active-<step>-<status>`。
同一 `(step, story_index)` 槽位确实存在两种快照（「尚未进入首个 Story」与「Story S-1 待执行」），不区分会让 resume
重写被误判为 checkpoint conflict（2026-09-10 修复）。

Goal SubAgent run snapshot 的 `context.metadata` 包含 `goal_id`、`goal_kind`（planning/story）
与框架权威的 `kind=subagent`。metadata 仅用于观测，不能覆盖 PolicyEngine 的授权字段；
无人值守 cron 不提升权限，审批与 sandbox 策略仍由 engine 处理。该层同样不是 OS 安全边界，
外部工具与 LLM 输出仍须在 OS 级沙箱中运行。

`workflow.md` 是自包含的声明式入口。其 `on_create` 声明创建规范化 `GoalArtifact` 和 `current` 指针；
每个 inline `## Step NN:` 区块声明 prompt、输入输出和 checkpoint。CLI 只映射已支持的
`persist_goal_identity` 与 `subagent` 声明到确定性操作；成功输出保存为
`step-XX-<step-name>.md`，Story 输出保存到对应的 Story 子目录——`parse_story_list` 从 story list 的
`## E<N> — <标题>` 段落（或 Story 块内的 `父 Epic` 字段，后者优先）解析出 `StorySpec.epic`，产物按
`step-NN-<slug>/epic-<eN>/s-<n>/report.md` 分组（`E1` → `epic-e1`；无 Epic 分组时退化为
`step-NN-<slug>/s-<n>/report.md`）。旧的 imperative goal board 路径不再作为回退。

### 4.14 技能资源读取 TOCTOU 评估与安全打开加固（Epic 46.1/46.2）

`SkillPackage` 的入口、step、reference、template、asset 和 script 均采用“`resolve_under_root` 解析 ->
`os.open()`（平台支持时附加 `O_NOFOLLOW`）”。Phase 4 C4（2026-09-21）起该实现收敛为
`tools/path_safety.open_text_under_root` 单一入口，`SkillPackage`、`SkillStore` 与 importer 的 manifest.lock
读取全部接入（契约测试钉 `os.open` 白名单）；-> `fstat()` 常规文件校验 -> 已打开 descriptor 读取”。这能拒绝
绝对路径、路径穿越、解析后越界符号链接，以及支持 `O_NOFOLLOW` 的平台上最终组件在打开前被替换为符号链接的情形。
不支持该标志的平台保留兼容打开；特征证据与回退覆盖见 `tests/test_skill_packages_toctou.py`，评估与候选方案见
`_bmad-output/epics/epic-43-46-目标级工作流周期/epic-46-技能资源并发替换安全评估/spec-skill-resource-toctou-assessment.md`，2026-09-23 的复核与决策见同目录 `assessment-toctou-residual-2026-09-23.md`，故事流程规格见
`_bmad-output/epics/epic-43-46-目标级工作流周期/epic-46-技能资源并发替换安全评估/stories/46-1-skill-resource-toctou-assessment.md`，
实现规格见 `_bmad-output/epics/epic-43-46-目标级工作流周期/epic-46-技能资源并发替换安全评估/spec-46-2-skill-resource-open-hardening.md`。

**内容完整性校验（2026-09-23 交付）**：读路径不再只做围栏与常规文件校验——若包根有合法的
`manifest.json`（**复用**渲染器 `_bmad/scripts/render_skill.py` 的既有产物，其 `outputs` 为
「相对 POSIX 路径 → sha256」，不为本特性新增文件或 lock 字段），则读到的**原始字节**摘要必须与清单一致，
否则 `SkillPackageResourceError("content hash differs from manifest.json")` 显性失败。
摘要取原始字节（`path_safety.read_text_with_digest_under_root`）而非归一化文本——固有 CRLF 的文件同样可校验；
无 `manifest.json` 的包（手写技能占多数）行为**逐字节不变**——凭据读取**先 stat 再读**（`is_file()` 门控），
未托管包零额外 `os.open`（读取次数刻画测试与 `O_NOFOLLOW` 的 EINVAL 兼容回退测试依赖此点，
2026-09-23 由 Linux 等价验证抓出：无门控时会多开一次文件），凭据不可用（损坏 / `outputs` 形状不符）时
跳过并记 warning（`manifest.json` 是通用文件名，可能属于别的工具，不据此拒读）。
代价与边界：渲染/导入后被**手工编辑**的包将拒读（有意，fail-loud；渲染器对漂移本就 `RenderError`）；
清单只钉它列出的文件，包内新增文件不在校验范围；能写该目录者本就能直接改写 `SKILL.md`，故本项是
defense-in-depth 而非边界。

该加固只保护最终路径组件，不能消除中间目录替换、恶意挂载或更高权限宿主进程造成的竞态；不声称已完成
TOCTOU 防护。descriptor-relative/目录句柄与 OS sandbox 仍须另立 story（2026-09-23 复核仍维持该结论：
逐组件 `openat` 仅 POSIX 可用且仍是收窄）；所有方案仍是 defense-in-depth，OS sandbox 才能处理
hostile filesystem/process context。


### 4.15 事件契约 (`events/`)

机器可读运行事件（JSONL）的对外契约。`RunEvent` 顶层 **11 字段**由黄金测试
（`tests/test_events_jsonl.py::_EXPECTED_FIELDS`）锁死、`SCHEMA_VERSION="2"`（v2，2026-09-22
Phase 5 C1：+`duration_ms`/`error_kind`；旧 rollout 缺省读、新字段被旧码 `extra=ignore`）。
`kind` 是开集（`KNOWN_KINDS` 仅文档/黄金测试依据，不过滤）。

| 字段 | 语义 |
| --- | --- |
| `schema_version` / `seq` / `ts` / `run_id` / `iteration` | 协议版本、sink 内单调序号、秒精度 ISO 时间、run/迭代关联 |
| `kind` / `tool` / `target` | 事件名（引擎事件名同形）/ 工具名 / 作用对象摘要 |
| `duration_ms` | 耗时（整数毫秒，`perf_counter` 源头测量）；0=未计时 |
| `error_kind` | 失败分类（封闭映射：`timeout`/`cancelled`/`policy_denied`/`safety_blocked`/`tool_error`/`exception` 兜底；映射单点 `protocol.error_kind_for`） |
| `details` | 自由扩展 dict（与工具返回同等不可信） |

逐 kind 发射点与 details 约定（发射点把 `duration_ms`/`error_kind` 放 `EngineEvent.details`，
由 `from_engine_event` 提升到顶层并摘除——EngineEvent 模型与 GUI 消费面不动）：

| kind | 发射点 | details 关键键 | duration/error_kind |
| --- | --- | --- | --- |
| `run_started` / `run_paused` / `run_resumed` | `agent/run_lifecycle.py` | `stream`/`session_id`/`resume`/委派键 | — |
| `run_completed` | `run_lifecycle.finish_run` | `answer_length` | duration（run 全程） |
| `run_failed` | `run_lifecycle.on_run_failed` | `error` | duration（缺省由 `run_elapsed_ms(loop)` 现算——facade `_on_run_failed` 路径 2026-09-23 前恒 0）+ error_kind |
| `iteration_started` | `agent/context_runtime.py` | — | — |
| `provider_call_started` / `provider_call_completed` | `agent/loop.py` | `message_count,estimated_tokens` / `model,finish_reason,actual_tokens` | completed 带 duration（中间件链整体） |
| `tool_call_started` / `tool_call_completed` / `tool_call_failed` / `tool_call_blocked` | `engine/executor.py`（`_emit_tool_event` 单点） | `mode`（+sandbox_profile/tier）/`content_length`/`error`/`reason` | completed/failed 带 duration；failed 带 error_kind |
| `context_compressed` / `window_reset` | `agent/context_runtime.py` | `before,after` | — |
| `workflow_step_started` / `workflow_step_completed` / `workflow_step_failed` | `engine/workflow_runner`（`emit` 注入端口，缺省 None=不发） | `step,story`（+`result`/`error`） | 三种带 duration；failed 带 error_kind。并发批次（`max_parallel_stories>1`）除批级一条（`story` 空）外，**批内每条 story 各发一组**（2026-09-23 起，`story` 非空） |
| `dream_start` / `dream_end`、`cron_job_*` | `memory/dream.py`、`cron/scheduler.py`（开集现状收编） | `success` 等 | — |
| `assistant_message`（传输层补充） | `events/sink.py` | `content` | — |

**持久化影响**：rollout 落盘 `<rollout_dir>/<run_id>/rollout.jsonl`（逐事件 append+close，
crash 前缀可回放）；`heagent replay` 人读渲染有值时追加 `[Nms]` / `error_kind=`；
黄金测试改字段须 bump `SCHEMA_VERSION` 并同步 `_EXPECTED_FIELDS`。
workflow 事件经 `goal/application.advance(emit=...)` 透传、`cli_goal._workflow_event_emitter`
绑 `EngineContainer.events` 总线；emit 异常隔离（warning，不改变业务控制流）。

### 4.16 TCP 入口 (`network/` + `cli_tcp.py`)

实验性入口（Epic 48）：把 agent 暴露成「一行请求 / 一行响应」的 UTF-8 JSON Lines 服务。
分层是硬约束——`network/` 只承载传输（framing / 协议模型 / 连接与超时生命周期 / 暴露判定），
装配放在入口层 `cli_tcp.py`（provider 经 `wiring._build_provider`、loop 经 `cli._build_loop`，
**函数内延迟导入**：`cli` 在模块尾部 import 本模块注册命令，模块级互相导入会成环）。

| 关注点 | 实现事实 |
| --- | --- |
| 协议 | `network/protocol.py`：请求只读 `id` / `prompt`（`extra="forbid"`）；响应 `ok` / `result` / `error` / `model` / `usage`；`TcpErrorCode` 为封闭 8 码（`invalid_json` / `invalid_request` / `empty_prompt` / `request_too_large` / `rate_limited` / `timeout` / `agent_error` / `server_error`），客户端**拿不到** traceback、异常类名或绝对路径 |
| 限额与生命周期 | 连接上限 + **非等待式**在途名额（满即 `rate_limited`，不排队；用任务集合而非计数/Semaphore）+ 空闲/单请求/关闭三类超时；`close()` 有界返回并**结算**残留登记（`asyncio` 无法强杀忽略取消的任务），且主动关闭仍登记的 writer——吞掉取消的 handler 会让等待它的连接任务永久挂起（取消经 `await request_task` 转发吸收，`finally` 不运行），不强制关 writer 客户端连接会随 `close()` 返回而泄漏 |
| 每请求一个 loop | `AgentLoop` 持有跨 run 可变展示态（`last_usage` / `last_model` / `active_tool` / 暂停 Event…），共享单实例并发会互相覆盖 ⇒ 每请求 `new_loop()`，共享 provider / engine / 4 个记忆存储（48-3 决策，含并发回归测试） |
| 审批 | **不装**交互式审批处理器（`ConsoleApprovalHandler` 读服务进程 stdin，无人应答会把请求挂死）⇒ 需要审批的调用维持既有 fail-safe 阻断，而不是把服务变成交互终端 |
| MCP | **不连接** `.mcp.json` 声明的 server（48-5 决策）：入口无认证、客户端不可信，自动拉起第三方 stdio 子进程 / 连远端端点等于把触达面暴露给任何能连上端口的人；需要 MCP 时在可控交互式会话里显式启用（回归测试钉死） |
| 暴露判定 | `network/exposure.py` 单点：IP 字面量走 `ipaddress.is_loopback`（含 `[::1]`），字面量 `localhost` 直接判回环，**其余主机名不解析 DNS**（解析是阻塞 I/O，且「解析到本机」≠「实际绑定到本机」）⇒ fail-safe 按暴露处理；非回环绑定向 stderr 与 logger 各出一条明确告警 |
| 可观测性 | 阶段日志 `event=started/exposed/accepted/rejected/processing/completed` 与 `event=failed`/`event=cancelled`，字段为 request_id / peer / bytes / reason / 稳定 code / `elapsed_ms`；**永不**记录 prompt 正文或工具原始输出；入口层所有日志经 `_safe_log`——日志设施抛异常时业务响应不变（成功仍成功、`agent_error` 不会被改写成 `server_error`）；详细 traceback 只进服务端 error 日志。⚠ 运行栈（agent/engine/…）自身的 `logger.*` 不在该保护内（见五、已知缺口） |
| 通道隔离 | 三条通道互不串线：TCP 响应（socket，一次请求只一条 JSON 行）／CLI stderr（启动告警、监听地址、用量）／rollout JSONL（`events.JsonlSink`，`EVENTS_ROLLOUT_ENABLED`）——注意 rollout 目前**只属于 CLI 单次模式**，TCP 入口不构造 sink |
| 输入卫生 | 客户端可控的 `id` 有界（≤128 字符）且禁止控制字符：它会被原样写进 3 个日志点，换行可**伪造日志记录**、超长可把日志放大约 3 倍请求体（48-5 评审 W-4 实测） |

⚠ **安全立场**：本入口**无认证、无 TLS**；回环判定与启动告警都**不是**安全边界——默认只绑
`127.0.0.1` 只是减少暴露面，回环客户端同样不可信。运行本入口须放在容器 / VM 等 OS 级隔离中，
并收紧出站网络与文件系统权限（与 `SafetyGuard` / `PolicyEngine` / sandbox 的立场一致）。

### 4.17 HTTP 网页入口 (`network/http_*` + `cli_http.py` + `web/`)

本机网页入口（Epic 49）：`heagent http-server` 起来后，浏览器打开 stderr 提示的地址即可使用内置
聊天页；默认 CLI 也会在同一进程内自动提供该入口（见下表「默认 CLI 自启动」）。分层与 TCP 入口同构
——`network/` 只承载传输（HTTP 协议模型 / 路由 / 运行服务 / 安全响应头 / 静态资源 / listener
生命周期），装配在入口层 `cli_http.py`；`network/` 不构造 Agent，运行入口由入口层以可调用对象注入。

| 关注点 | 实现事实（Story 49-1/49-2/49-3 已交付部分） |
| --- | --- |
| 协议模型 | `network/http_protocol.py`：`HttpErrorCode` 封闭 22 码（含项目注册表稳定错误码）、`{"error":{"code","message"}}` 信封、`HealthResponse`（字段封闭：`status` / `service` / `version` / `schema_version`）；`sanitize_message` 是客户端文案唯一出口（折叠空白 + **掩码宿主绝对路径** + 截断到 `MAX_ERROR_MESSAGE_CHARS`），**不含** traceback / 异常类名 / 绝对路径——掩码是启发式（Windows 盘符与 UNC 全掩；POSIX 要求 ≥3 段，以免误伤 `/api/health`、`and/or`、URL），与 `safe_logging` 同一立场：**非安全边界**（2026-09-23 评审修复：此前上游 `HeAgentError.message` 里带的路径会原样透传）|
| 传输层 | `network/http_server.py`：`HttpServerConfig`（9 个有界字段，默认值与 `HTTP_*` 一致）+ `HttpServer`（`start` / `serve_forever` / `close`，与 `TcpServer` 同 API 形状）；`build_http_app` 组装健康检查 + 静态资源 + 安全头 |
| 可选依赖 | starlette / uvicorn 由 `pyproject.toml` 的 `http` extra **直接声明**，且只在真要服务时经 `importlib.import_module` 加载；缺依赖抛 `HttpDependencyError` → 命令给出 `pip install 'heagent[http]'`。可执行断言：`tests/test_architecture_contracts.py::test_optional_asgi_stack_is_only_imported_lazily`（源码中不存在顶层 starlette/uvicorn 导入） |
| 就绪门禁 | `start()` 只在「listener 已绑定**且**真实 TCP 打通一次 `/api/health`（200）」后返回；绑定失败（Uvicorn 在该路径上是 `sys.exit(STARTUP_FAILURE)`）与探测失败都转成 `HttpStartupError`，命令层给可读错误，**绝不**打印「已监听」。**通配绑定**（`0.0.0.0` / `::`）的探测改走回环地址（连 `0.0.0.0` 是未定义行为），故允许集对通配值额外接受 `127.0.0.1` / `localhost` / `[::1]`（探测的 Host 头按 authority 语法给 IPv6 加方括号）——通配绑定可从本机浏览器访问，但经其它网卡地址访问仍被 `origin_forbidden` 拒绝（非回环联网不受支持）。连接的 `limit_concurrency` 额外预留 1 条给就绪探测，否则 `HTTP_MAX_CONNECTIONS=1` 会让入口**永远起不来**（以上两项为 2026-09-23 评审修复）|
| 关闭 | `close()` 幂等且全程有界：设 `should_exit` → Uvicorn `shutdown()`（连接排空受 `timeout_graceful_shutdown` 约束）→ 等待 serve 循环退出（超时则取消），整体再包一层 `wait_for`。信号**不归 Uvicorn 管**（不调 `serve()` / `capture_signals`）：`KeyboardInterrupt` 由 CLI 接住并安静退出 |
| 静态资源 | `src/heagent/web/` 内 `index.html` / `app.js` / `styles.css`，经 `importlib.resources.files("heagent.web")` 读取（AD-11 唯一查找方式；wheel 里以 `zipimport` 加载已实测）；**白名单**路由同时挡掉路径穿越与「散落文件被意外发布」 |
| 安全响应头 | 每个响应带 `Content-Security-Policy: default-src 'none'; script-src 'self'; …; frame-ancestors 'none'`、`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy: no-referrer`；页面**不加载任何第三方脚本**（CSP 不允许内联；测试断言页面所有 `src` / `href` 都是同源绝对路径） |
| 渲染纪律 | 页面脚本只用 `textContent` / `createTextNode` 渲染提示词、回答与工具输出（**永不** `.innerHTML`）；HTML 里没有内联脚本或样式 |
| 输入与键盘 | 输入框是**多行** `<textarea>`（`rows=3`，`maxlength` = `MAX_PROMPT_CHARS`，有测试钉住「多行 + 有上限」）。**Enter 发送、Shift+Enter 换行**，Ctrl/Cmd+Enter 同样发送；**输入法组合态（`isComposing` / `keyCode 229`）一律不发送**——否则中文选词时敲回车会把半个词发出去。提交时前端 `trim()` 掉首尾空白（中间换行原样进 prompt），空内容静默忽略；行为由 `tests/test_http_web_ui.py` 的 node 探针（case E）钉住 |
| 默认 CLI 自启动 | `heagent` / `heagent "prompt"` / `heagent run ...` 在**同一个 asyncio 生命周期**内启动内嵌服务（`cli._embedded_http_service` + `cli_http.EmbeddedHttpService`）：交互模式与 REPL 共存、单次模式与那次 run 并存且 run 结束即关闭并释放端口。`gui` / `tcp-server` / `http-server` / `init` / `replay` 都不经过该路径（**不派生第二个实例**）。启动失败（端口冲突 / 缺 `heagent[http]`）转成命令级错误（exit 1），绝不出现「聊天正常但页面打不开」；serve 循环意外结束时交互模式如实报出并退出（AD-5 的假可用状态禁令）|
| 运行 API | `POST /api/runs`（请求体**只认** `prompt`，`extra="forbid"` ⇒ 塞 provider/model/system/沙箱/迭代预算一律 400；单运行约束：已有在途 run 时 409 `run_conflict`，**不排队不覆盖**）、`GET /api/runs/{run_id}/events`（SSE）、`DELETE /api/runs/{run_id}`（协作式取消，只作用于该 run，幂等）、`GET /api/session`（会话 id / 当前运行状态 / 已完成历史）。请求体按块读取，超过 `HTTP_MAX_REQUEST_BYTES` 立即中断（413 `request_too_large`），不用 ``request.body()`` 把大小交给客户端决定；该上限默认按「最大 prompt 的最坏 JSON 字节数」派生（见配置表），两者口径不一致时中文提示词会在远未到字符上限前就被 413 拒（2026-09-23 修复） |
| 事件与投影 | 事件类型 `text` / `tool_call` / `tool_result` / `done` / `error` / `cancelled` / `timed_out`；`id` 从 1 单调递增、`data` 是单行 JSON；文本字段入缓冲前截断到 16384 字符并显式标记；`done` 带**该次运行**的 model 与 usage。会话投影只有一条路径：仅 `COMPLETED` 的 run 投影 prompt + 最终回答，失败 / 取消 / 超时**绝不**把部分文本写进历史（AD-3）；运行记录按 `HTTP_RUN_HISTORY_SIZE` 保留，**只淘汰终态记录**（在途运行必须始终可按 id 取消 / 订阅，全部在途时宁可暂时超出上限——否则记录凭空消失而它仍占着名额），淘汰后按 id 订阅得 `unknown_run` |
| 取消、重连与终态 | 终态转换**首个获胜**（AD-10）：完成 / `DELETE` / 运行超时 / 关停竞争时只产生一个终态事件，名额在 done callback 里归还（**含「任务未被调度就被取消」的病态路径**——那时协程体不执行，靠 callback 兜底补写 `cancelled`）。`Last-Event-ID: N` 只重放**严格大于** N 的事件；游标早于缓冲窗口（`N < oldest_seq - 1`）返回 409 `resync_required`（不发看似连续的流），客户端据此拉 `/api/session` 快照；空闲流每 15 秒发一条 SSE 注释心跳（`yield None` → `: ping`，不占 ID）。**断线只释放订阅者、绝不取消运行**（取消只能走 `DELETE`）。订阅者队列与事件窗口**同界**：消费端被背压卡住（客户端不读）时**结束该订阅者的流**（客户端带游标重连 → ring buffer 补齐或 409 重新同步），既不无限堆积内存、也不静默跳过事件（2026-09-23 评审修复）|
| 限额与超时 | 运行时长 `HTTP_REQUEST_TIMEOUT`（超时 → `timed_out` 终态 + 事件 + 归还名额）；**超时是协作式的**（`asyncio.timeout` 只能请求取消）：executor 吞掉 `CancelledError` 时时限并未生效——终态按实际结果走，但服务端记 `event=timeout_ignored`；运行内部（provider / 网络）自己抛的 `TimeoutError` 按 **failed** 归因，不谎报「超过配置时限」（判据是 `deadline.expired()`，2026-09-23 评审修复）。在途运行数 `HTTP_MAX_INFLIGHT_RUNS`（非等待式，满即 409）；客户端连接数与每 run 的 SSE 订阅者数上限**复用同一个** `HTTP_MAX_CONNECTIONS`，客户端连接交给 Uvicorn `limit_concurrency`（见五、订阅者限额缺口）|
| 运行隔离 | 入口层 `cli_http.HttpAgentHandler`：**每次运行新建独立 `AgentLoop`**（loop 持跨 run 可变展示态），handler 自建 engine（`approval_handler=None` ⇒ 需要审批的调用维持既有 fail-safe 阻断，**绝不**读服务进程 stdin）、不自动连接 MCP；传输层只认注入的可调用对象，不认识 `AgentLoop`（AD-1 的接缝） |
| 来源校验 | 同源防线（AD-6；**defense-in-depth，不是认证**）：所有请求必须带**唯一**且匹配本 listener 的 `Host`（规范化小写、http 默认端口省略；**回环绑定时**接受 `127.0.0.1` / `localhost` / `[::1]` 三个等价写法，非回环只认配置的那个名字）；带 `Origin` 时必须等于 `http://<该 authority>`（拒绝 `null` 与跨站）；重复 `Host` 与任何 `forwarded` / `x-forwarded-*` / `x-real-ip` 头一律 403 `origin_forbidden`（**不信任代理**，Uvicorn 侧也已 `proxy_headers=False`）。被拒的**状态变更不产生任何副作用**（提交不建 run、取消不动 run，有测试钉住） |
| 可观测性 | 每条请求一条日志（`event=request`：不透明 `request_id` / method / path / status / `elapsed_ms`），并在响应头回 `x-request-id`；每次运行在启动与终态各一条（`event=run_started` / `event=run_finished`：`run_id` / status / `elapsed_ms`）。**日志不含** prompt、回答或工具输出正文（工具名与作用对象仍会出现——那是既有引擎 `LoggingObserver` 的行为，与 CLI/GUI 一致）；入口层插桩经 `_safe_log`，日志设施故障不影响协议行为；运行失败额外记一条 `event=run_failed`（含 traceback）——运行是后台任务，异常不会走 Uvicorn 的 traceback 通道，不记就等于丢掉真实缺陷的栈（2026-09-23 评审修复）|

⚠ **安全立场**：与 TCP 入口一致——本入口**无认证、无 TLS**，回环绑定不是认证边界，回环客户端同样
不可信；运行本入口须放在容器 / VM 等 OS 级隔离中（见五、已知缺口与 CLAUDE.md 安全声明）。

## 五、已知缺口

| 缺口 | 说明 |
|------|------|
| 流式 tool_calls 回退 | `run_stream()` 流式模式不返回 `tool_calls`，命中时回退 `send()` 重取（已知设计权衡） |
| MCP / engine sandbox 安全边界 | `SafetyGuard` / `PolicyEngine` / `FirejailBackend` / MCP 围栏均非真正安全边界，须 OS 级沙箱兜底（详见 CLAUDE.md 安全声明） |
| 用户可配置 MCP 签名入口 | 项目级 `.heagent/injection_signatures.json` 已接入并进程内缓存；全局级配置仍 deferred；签名围栏仍是非真正安全边界 |
| 凭证 deny 项目级配置入口 | `.heagent/path_deny.json`（2026-09-17）允许收紧（追加 deny 项）或放行显式列举项（精确路径 / basename 豁免；内部状态目录 deny 不接受豁免），无整体关闭入口、fail-safe 默认仍拒；非真正边界（见文件安全行） |
| Dreaming 联网注入围栏 | `web_fetch` 返回路径已接 `guard_content`（Epic 35，2026-08-19：命中内置注入签名即加 warning 标记透传，不阻断），与 MCP `bridge_result` 同语义；仍是非真正边界（标记仅 observable defense-in-depth），dreamer 须 OS 级沙箱兜底（见 4.6 dream.py） |
| HTTP 入口订阅者限额与连接额度同源 | 每 run 的 SSE 订阅者上限与 Uvicorn 的 `limit_concurrency` 复用同一个 `HTTP_MAX_CONNECTIONS`：超额连接由 Uvicorn 在进入 ASGI **之前**以 `text/plain` 503 拒绝（不经过本入口的错误信封、安全响应头与访问日志），因此 429 `rate_limited` 分支实际不可达；两个限额的独立配置属后续工作（2026-09-23 评审记录）|
| 交互式审批非安全边界 | 审批闭环（Epic 29）把「要不要执行」交给用户，**不是安全边界**——`PolicyEngine` 本就非真边界，须 OS 级沙箱兜底（见 4.12 approval.py） |
| 文件安全与凭证防护非边界 | `path_safety` 凭证 deny / `scrub_sensitive_env` 均为 defense-in-depth 启发式层（2026-08-24），非真正边界——shell 工具仍可 `cat .env` 绕过，须 OS 级沙箱兜底 |
| 沙箱会话目录非安全边界 | `sandbox_session_workspace`（FR-1，2026-08-26）只提供 per-run 目录约定：WinJob 仅把目录作为子进程 cwd（**零文件系统/网络隔离**），Firejail `--private` 亦非完美边界——须 OS 级沙箱兜底（见 4.4 sandbox.py） |
| 沙箱后端分级预留 | `SandboxTier`（FR-2，2026-08-26）`container` 档仅预留枚举、无实现后端；审批降级（`can_relax_approval`）未接入 `PolicyEngine` 裁决，弱后端一律维持原审批要求——分级不产生新安全边界 |
| 沙箱 env 豁免非安全边界 | `sandbox_env_allowlist`（FR-3，2026-08-26）仅豁免 `scrub_sensitive_env` 剥离，非真正边界——shell 工具仍可读任意环境变量，须 OS 级沙箱兜底 |
| SandboxSession 非安全边界 | `SandboxSession`（FR-4，2026-08-26）会话 cwd 保持仅「cd 前缀 + 尾捕获」约定，WinJob 无 FS 隔离、Firejail 非完美边界——须 OS 级沙箱兜底；crash 孤儿目录 GC/保留策略已于 2026-09-15（E40-D1）交付（`housekeeping.prune_sandbox_dirs` + `sandbox_dir_retention_days`），仍非安全边界 |
| TCP 入口非安全边界 | `heagent tcp-server`（Epic 48，实验性）**无认证、无 TLS**：回环判定（`network/exposure.py`）与启动告警只是提示，不构成认证或隔离；默认绑回环也**不**为客户端建立信任——须 OS 级沙箱兜底并限制出站网络（见 4.16） |
| TCP 入口不接 MCP | 网络入口**不连接** `.mcp.json` 声明的 server（48-5 决策）：入口无认证，而 MCP server 属不可信代码 / 端点，自动连接会把触达面暴露给任何能连上端口的人；需要 MCP 只能在可控交互式会话里显式启用 |
| TCP 入口不写 rollout | `EVENTS_ROLLOUT_ENABLED` 只作用于 CLI 单次模式：`JsonlSink` 唯一构造点在 `cli._build_event_sink`，TCP 入口不订阅 sink ⇒ 该开关在 `tcp-server` 下不产生 `.heagent/runs/<run_id>/rollout.jsonl`（48-5 评审 W-2 实测）。**接入前须先定并发语义**（2026-09-23 复核）：`JsonlSink` 的 `seq` 与 `_last_run_id` 是**sink 全局**的，而 TCP 入口共享一个 `EngineContainer`/`EventBus` 并发服务多请求——单共享 sink 会让多 run 的 seq 交错、`assistant_message` 归属错误；每请求一 sink 则互相收到对方的全部事件（`EventBus` 无 `unsubscribe`）。故接入需先给 sink 加 run 维度过滤或给总线加退订 |
| HTTP 入口非安全边界 | `heagent http-server` 与默认 CLI 的内嵌网页入口（Epic 49，实验性）**无认证、无 TLS**：回环绑定与启动告警同样只是提示。网页运行走的仍是既有治理链（`PolicyEngine` → `ToolExecutor` → `SafetyGuard` → handler），但入口本身不构成边界——须 OS 级沙箱兜底，且不要把端口暴露给不可信网络（见 4.17） |
| HTTP 入口不接 MCP | 网页入口**不连接** `.mcp.json` 声明的 server（与 TCP 入口同一决策）：入口无认证，自动拉起第三方 stdio 子进程 / 连远端端点等于把触达面暴露给任何能连上端口的人 |
| HTTP 会话/事件无持久化 | 网页入口的会话投影、运行记录与 SSE 事件缓冲都是**进程内状态**：进程退出即丢；事件缓冲按 `HTTP_EVENT_BUFFER_SIZE` 有界，越过窗口的重连只能得到 `resync_required` 并改拉 `/api/session` 快照。首版有意如此（持久化见 4.17 与架构脊柱的延后决策） |
| 运行栈日志的故障免疫（**已交付，2026-09-23**） | 入口层插桩经 `_safe_log`；运行栈任意 `logger.*` 由进程级守卫 `safe_logging.install_logging_fault_guard()` 兜底（包 `logging.Handler.handle`，失败仍走 stdlib `handleError` 诊断但不抛——CPython 的 `Handler.handle` 本不捕获 `emit` 异常，与 `raiseExceptions` 无关，48-5 评审 C-1 实测）。**残留**：宿主在守卫安装前打日志、或自行还原 `Handler.handle`（`safe_logging.ORIGINAL_HANDLER_HANDLE`）时不在此保证内 |
| 日志行的凭证脱敏（**启发式，非边界**；2026-09-23 交付） | `LoggingObserver` 打印前对 `target`/`details` 掩码：键值（`API_KEY=…`/`token: …`）、CLI 旗标、厂商前缀（`sk-`/`ghp_`/`AKIA`/`AIza`/JWT）、`Bearer`、URL userinfo，以及**凭证命名的键**（短值无形状可认）。**肯定漏网**：模式匹配非完备，`shell` target 仍不截断（审查需要原文），且 `logs/`、`.heagent/runs/`（快照/rollout）按设计保存完整 prompt 与消息——仍须 OS 级沙箱与「不要把凭证写进命令或路径」 |

---

## 六、目录结构

```
src/heagent/
├── __init__.py
├── __main__.py              # python -m heagent 入口
├── cli.py                   # Click CLI（单次/交互模式）
├── cli_init.py              # heagent init 子命令（全局配置/项目上下文模板生成，2026-09-17 自 cli.py 拆出）
├── cli_goal.py              # /goal 命令族（声明式工作流分发 + cron 自动推进）
├── cli_tcp.py               # tcp-server 子命令 + Agent 请求适配（入口层组合根；Epic 48）
├── cli_http.py              # http-server 子命令 + HTTP 服务装配（入口层组合根；Epic 49）
├── web/                     # 内置网页资源包（HTML/CSS/JS，随 wheel 分发；经 importlib.resources 读取）
├── wiring.py                # 入口层装配共享缝：provider 组合根 + ensure_runtime_config + build_cron_job_runner（CLI/GUI 共用，Phase 2 C3）
├── terminal.py              # 终端键盘监听（Esc 暂停 / Enter 恢复 / 双击 Esc 打断，CLI 交互模式）
├── config.py                # pydantic-settings 配置
├── exceptions.py            # 异常层级
├── types.py                 # 共享 Pydantic 模型
├── persist.py               # 原子写 + 容错读 + 跨进程文件锁 + prune 批量内核（底层共用）
├── roles.py                 # RoleSpec + 内置角色注册表（agent/tools/engine 共用）
├── frontmatter.py           # 共享 frontmatter 解析（零 heagent 依赖；六处手写解析器收敛，2026-09-17）
├── safe_logging.py           # 日志卫生（safe_log 容错 + 故障守卫 + 启发式脱敏；零 heagent 依赖，2026-09-23）
│
├── agent/                   # 顶层编排
│   ├── loop.py              # AgentLoop façade（依赖注入装配 + 公共入口委托，Phase 2）
│   ├── run_lifecycle.py     # run 生命周期策略（状态类 + 初始化/非流式循环体/终结/检查点）
│   ├── stream_runtime.py    # 流式循环体策略（run_stream）
│   ├── resume_runtime.py    # resume 快照重建策略
│   ├── context_runtime.py   # 迭代控制/消息追加/压缩/窗口重置策略
│   ├── message_ports.py     # steering/follow-up 端口 + 协作式暂停
│   ├── system_prompt.py     # _build_system 拼装（人格/上下文/技能/记忆/画像）
│   ├── tool_execution.py    # _execute_one 工具执行链（ledger → policy → executor）
│   ├── middleware.py        # 中间件组合 + make_retry_middleware
│   ├── delegation.py        # 子 Agent 委派回调（tools ↔ agent 依赖倒置）
│   └── sub.py               # 子 Agent（并行任务 + 角色化）
│
├── providers/               # LLM Provider（互不依赖）
│   ├── base.py              # BaseProvider Protocol
│   ├── openai.py            # OpenAI 兼容（含 DeepSeek）
│   ├── anthropic.py         # Anthropic（含提示词缓存 FR-3）
│   ├── chain.py             # ProviderChain 回退链（外层，FR-4 回退精度）
│   ├── key_rotation.py      # KeyRotatingProvider 密钥池轮换（中层）
│   ├── retry.py             # 错误分类 + make_retry_middleware（内层）
│   ├── responses.py         # OpenAI Responses API 兼容 Provider
│   ├── router.py            # RoutingProvider 智能路由（按任务特征选模型，主动选择层）
│   └── switchable.py        # SwitchableProvider 运行时多 vendor 切换（外层选择层）
│
├── tools/                   # 工具系统
│   ├── decorator.py         # @tool 装饰器
│   ├── registry.py          # ToolRegistry 单例
│   ├── safety.py            # SafetyGuard（shell 命令安全）
│   ├── path_safety.py       # 工作区路径校验（文件工具）
│   ├── edits.py             # 编辑原语：行尾/BOM 保真读写、diff 回执、落盘前快照
│   ├── sandbox/             # 沙箱包（contracts/process/firejail/winjob/session，Phase 4 C1）
│   ├── call_summary.py      # 工具调用「作用对象」摘要（展示层共用）
│   ├── runtime.py           # 工具运行态绑定（_runtime_scope）
│   ├── mcp/                 # MCP 适配层
│   │   ├── config.py        # MCPConfig + load_mcp_config（.mcp.json + ${ENV} 插值）
│   │   ├── mapping.py       # mcp_tool_to_schema + bridge_result
│   │   ├── session_api.py   # MCP SDK 会话字段兼容访问
│   │   ├── client.py        # TransportOpener Protocol + 默认实现（Phase 4 C2）
│   │   ├── registry_bridge.py  # 注册/注销单一入口（Phase 4 C2）
│   │   └── manager.py       # MCPClientManager（生命周期 façade + discovery_failures）
│   └── builtins/            # 内置工具（24 个）
│       ├── __init__.py      # 触发注册
│       ├── shell.py         # shell 命令执行
│       ├── file.py          # 文件读写
│       ├── search.py        # 文件/内容搜索
│       ├── skills.py        # 技能管理（create/update/list/delete/curate/archive）
│       ├── memory.py        # 记忆管理（fact_add/profile_update）
│       ├── cron.py          # Cron 管理（add/list/remove）
│       ├── subagent.py      # 子 Agent 委派工具（仅持可注入回调，不导入 agent/）
│       ├── web.py           # web_fetch（HTTP 抓取，read-only）
│       └── git.py           # Git 工具（status/diff/log/blame，read-only）
│
├── context/                 # 上下文管理
│   ├── loader.py            # 上下文文件分层扫描（仓库根 → cwd，CONTEXT.md > AGENTS.md > CLAUDE.md）
│   ├── tokens.py            # CJK 感知 Token 估算
│   ├── compressor.py        # 消息压缩
│   ├── window_reset.py      # 窗口重置 + checkpoint-resume（P3）
│   └── session.py           # 会话持久化
│
├── memory/                  # 记忆系统
│   ├── facts.py             # 事实存储 + 去重
│   ├── skills.py            # 技能存储兼容 shim（Phase 4 C4 拆四文件）
│   ├── skill_models.py      # 技能模型 + SKILL.md 解析 + 名称校验
│   ├── skill_rewrite.py     # 渲染 + frontmatter 就地改写（正文保真）
│   ├── skill_catalog.py     # 匹配 + 过期盘点（纯检索）
│   ├── skill_store.py       # SkillStore 门面（读经 open_text_under_root）
│   ├── skill_packages.py    # BMad 技能包与安全资源读取（工作流装配已迁 goal/workflow_loader.py）
│   ├── skill_importer.py    # 技能包导入与目录映射
│   ├── profile.py           # 用户画像
│   ├── soul.py              # 人格系统（全局/项目两级）
│   └── dream.py             # 离线记忆巩固调度器（Dreaming 模式）
│
├── engine/                  # 运行时引擎（P0）
│   ├── container.py         # EngineContainer（DI）
│   ├── context.py           # RunContext / RunStatus
│   ├── policy.py            # PolicyEngine 准入/审批/沙箱裁决
│   ├── executor.py          # ToolExecutor 策略分发
│   ├── store.py             # RunStore 运行快照（async I/O）
│   ├── ledger.py            # ExecutionLedger 幂等/租约（async I/O）
│   ├── checkpoint.py        # WorkflowCheckpointStore + GoalWorkflowState 运行时进度（2026-09-20 自 workflow.py 改名；load_state 恢复进度，与装载声明区分）
│   ├── workflow_resource.py # 工作流资源模型 WorkflowResource/Step（2026-09-20 自 memory.skill_packages 迁入）
│   ├── workflow_runner.py    # 声明式 workflow 单步执行器
│   ├── artifacts.py          # Goal/Epic/Story 产物契约校验
│   ├── approval.py           # 交互式审批协议与状态
│   ├── hooks.py              # 生命周期 Hook 调度
│   └── observability.py     # EventBus / 事件
├── events/                  # 事件传输层（JSONL 契约 / rollout 落盘 / replay）
│   ├── protocol.py          # RunEvent + EngineEvent → RunEvent 映射
│   └── sink.py              # JsonlSink（stdout/rollout）+ read_rollout / render_event
│
├── network/                 # 网络入口传输层（Epic 48 TCP / Epic 49 HTTP；协议/生命周期/暴露判定，不依赖运行栈）
│   ├── protocol.py          # JSON Lines 请求/响应模型 + 8 个稳定错误码 + 有界编解码
│   ├── tcp_server.py        # TcpServer（两档限额 / 三类超时 / 阶段日志；日志经 _safe_log 不影响协议）
│   ├── http_protocol.py     # HTTP 协议模型：14 个稳定错误码 + 错误信封 + HealthResponse + 运行/事件/会话模型（Epic 49）
│   ├── http_server.py       # HttpServer（就绪门禁/有界关闭/静态资源白名单/安全响应头）+ HttpRunService（单用户会话、运行记录与事件 ring buffer、SSE 订阅）
│   └── exposure.py          # 回环判定 + 「无认证 / 无 TLS / 非生产边界」告警文案（单点，不解析 DNS）
│
├── goal/                    # /goal 域层（入口层，供 cli_goal 使用，下层不得反向导入）
│   ├── application.py       # workflow use-case 确定性内核（校验/gate/story/checkpoint 推进；click-free，Phase 3）
│   ├── document.py          # brief.md 定位/命名规则/增量更新（存量回落 require.md/GOAL.md）
│   ├── naming.py            # /goal new 项目名 LLM 生成，失败显性回退 project（2026-09-21）
│   └── workflow_loader.py   # workflow.md 声明装配 read_workflow（frontmatter 策略/内嵌步骤/模板必需性）
├── slash.py                 # 交互模式斜杠命令注册与路由
├── gui/                     # 可选 Textual GUI（chat/screens/widgets/state）
└── cron/                    # 定时调度
    ├── jobs.py              # CronJob 模型 + JobStore 持久化
    └── scheduler.py         # CronScheduler 后台调度器
```

---

## 七、完整调用链

```
python -m heagent "your prompt"
  │
  ▼
__main__.py → cli.main()
  │
  ├── import heagent.tools.builtins → @tool 注册到 ToolRegistry（24 个工具）
  ├── get_settings() → 读取 DEEPSEEK_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY（+ OLLAMA_ENABLED 本地条目）
  ├── _build_provider() → OpenAIProvider（含本地 ollama）/ AnthropicProvider / ProviderChain
  │
  ▼
asyncio.run(_run_single())
  │
  ├── 初始化模块
  │     ├── SkillStore()          → 技能存储
  │     ├── FactStore()           → 事实记忆
  │     ├── ProfileStore()        → 用户画像
  │     ├── SoulStore()           → 人格加载器
  │     ├── ContextCompressor()   → 上下文压缩器
  │     ├── JobStore()            → Cron 任务存储
  │     └── make_retry_middleware() → 重试中间件
  │
  ▼
AgentLoop(provider, skills, facts, profile, compressor, soul, cron_store, ...).run(prompt)
  │
  ├── 构建 Message(USER, prompt) 加入 state.messages
  │
  ├── _build_system() → 按注入顺序构建系统提示词
  │     ├── <identity>            — SOUL.md 人格
  │     ├── 用户 system 字符串
  │     ├── <project-context>     — CONTEXT.md / AGENTS.md / CLAUDE.md
  │     ├── <shell-workspace>     — 本 run 的 shell 沙箱工作目录（真正生效时；E40-D2）
  │     ├── <skills>              — SkillStore.match() 自动匹配 ≤ skill_max_auto_invoke 个
  │     ├── <memory>              — 事实记忆列表
  │     ├── <memory-nudge>        — 记忆保存提醒（紧随 memory）
  │     └── <profile>             — 用户画像
  │
  ▼ 循环开始 ─────────────────────────────
  │
  ├── _call_provider(state)
  │     ├── count_tokens(state.messages)        # Token 估算（日志）
  │     ├── compose([retry_mw], provider.send)  # 中间件链
  │     ├── ProviderResponse(tool_calls=[...])
  │     └── 日志：估算 vs 实际 Token 对比
  │
  ├── 累计 TokenUsage 到 accumulated
  │
  ├── ContextCompressor.check()  # Token ≥ 阈值时压缩旧消息
  │
  ├── 有 tool_calls？
  │     ├── YES → _execute_tools(calls, state)   # asyncio.gather 并行
  │     │         └── _execute_one(call) per call:
  │     │             ├── ledger.acquire()        # 幂等/租约（COMPLETED 短路返回缓存，但 BLOCKED 复核 bypass；lease-active 跳过执行）
  │     │             ├── PolicyEngine.evaluate() # 准入/审批/沙箱裁决
  │     │             ├── ToolExecutor.execute()  # 按 verdict 分发
  │     │             │    └── SafetyGuard.check()# shell 命令模式黑名单（executor 内部串行）
  │     │             ├── handler(**arguments)    # 执行
  │     │             ├── ledger.complete()/fail()# 回写结果
  │     │             └── ToolResult → 追加到 messages
  │     │
  │     └── NO → 返回 response.content（最终答案）
  │
  ├── finally:
  │     ├── SessionStore.save()    # 持久化对话（有 session_id 时）
  │     └── self.last_usage = accumulated
  │
  └── iteration >= max_iterations → BudgetExceeded
  │
  ▼
click.echo(result)
_print_usage(loop.last_usage)  # [tokens: N in + M out = T total]
show_tool_activity(loop)       # [tools] N 次调用尝试：file_read → src/a.py …
```

**交互模式额外流程：**

```
python -m heagent
  │
  ├── _run_chat() 代替 _run_single()
  │     ├── SessionStore() → 生成 session_id
  │     ├── CronScheduler(job_store, provider, ...) → 后台调度
  │     │
  │     ├── scheduler.start()  → 后台 tick 循环
  │     │     └── 每 cron_tick_seconds 秒 → 检查到期 CronJob → 创建独立 AgentLoop 执行
  │     │
  │     └── REPL: while True
  │           ├── input("> ")
  │           ├── loop.run_stream(input, session_id=session_id, system=system)  # 流式 yield StreamEvent
  │           │     └── 命中 tool_calls 时回退 send() 重取该轮调用
  │           └── finally: scheduler.stop()
  │
  └── 一次性 Cron 任务成功后自动从 JobStore 删除
```

**TCP 入口流程（Epic 48，实验性）：**

```
python -m heagent tcp-server [--host H] [--port P] [--max-inflight N] ...
  │
  ├── _setup_logging() → get_settings() → _prune_runtime_artifacts()
  ├── load_agent_roles() → wiring._build_provider()        # 服务级共享 provider
  ├── TcpAgentHandler(...)                                  # 共享 engine + 4 个记忆存储（不装审批、不接 MCP）
  ├── build_server_config(settings, **overrides)            # CLI 覆盖不写回 Settings 单例
  ├── exposure_warning(config.host) → 非回环则 stderr 一行告警（logger 侧一条 event=exposed）
  └── asyncio.run(_serve_tcp(server))
        ├── await server.start()        # 绑定 + event=started
        ├── stderr: listening on <host>:<port> → serve_forever()
        │     └── 每条连接：_process_client
        │           ├── 读一行（idle_timeout；超限 → rejected reason=oversized_line）
        │           ├── decode_request（失败 → rejected reason=decode_failed + 稳定 code）
        │           ├── 非等待式在途名额（满 → rejected reason=inflight_limit，不排队）
        │           ├── TcpAgentHandler.__call__ → new_loop() → AgentLoop.run
        │           │     └── 与 CLI 同一条 Provider→Tool 执行链（PolicyEngine → ToolExecutor → SafetyGuard）
        │           └── 写回一条 JSON 行 + event=completed / event=failed（含 elapsed_ms，不记正文）
        └── finally: await server.close()   # 有界收尾并结算残留登记
```

**HTTP 网页入口流程（Epic 49，实验性；Story 49-1/49-2/49-3 已交付部分）：**

默认 CLI（`heagent` / `heagent "prompt"` / `heagent run ...`）会**内嵌**启动同一个服务——生命周期
包在 `cli._embedded_http_service`（`cli_http.EmbeddedHttpService`）里，与 CLI 共享一个
`asyncio.run`：交互模式与 REPL 共存，单次模式与那次 run 并存、run 结束即关闭并释放端口；
`gui` / `tcp-server` / `http-server` / `init` / `replay` 都不经过该路径（不派生第二实例）。

```
python -m heagent http-server [--host H] [--port P] [--max-inflight-runs N] ...
  │
  ├── _setup_logging() → get_settings() → _prune_runtime_artifacts()
  ├── load_agent_roles() → wiring._build_provider()          # 服务级共享 provider
  ├── HttpAgentHandler(...)                                   # 每次运行新建 AgentLoop（不装审批、不连 MCP）
  ├── HttpRunService(config, handler)                         # 单用户会话 + 运行记录/事件缓冲的唯一所有者
  ├── HttpServer(config, version=heagent.__version__, run_service=service)
  ├── exposure_warning(config.host) → 非回环则 stderr 一行告警（logger 侧一条 event=exposed）
  └── asyncio.run(_serve_http(server))
        ├── await server.start()
        │     ├── uvicorn Server.startup()（绑定；失败 → HttpStartupError，不打印「已监听」）
        │     └── 就绪门禁：真实 TCP 请求一次 /api/health，非 200/连不上 → 回滚并抛错
        ├── stderr: listening on http://<host>:<port>
        └── serve_forever() → Uvicorn main_loop
              └── 中间件（由外到内）：安全响应头 → 请求日志（x-request-id）→ 同源防线（Host/Origin）
                    └── 路由：
                        ├── GET  /api/health            → HealthResponse（字段封闭，不含密钥/路径/traceback）
                        ├── POST /api/runs              → 有界非空 prompt ⇒ 201 {run_id,status}；在途 ⇒ 409 run_conflict
                        │       └── start_run → 后台任务 `_execute` → handler(prompt, publisher) → AgentLoop.run_stream
                        │             └── 事件映射：text / tool_call / tool_result（seq 单调、文本截断、广播给订阅者）
                        │                  终态（首个 claim_terminal 获胜）：done（带 model/usage）/ error / cancelled / timed_out
                        ├── GET  /api/runs/{id}/events  → SSE：按 Last-Event-ID 重放（游标越窗 ⇒ 409 resync_required）
                        │                                    → 跟随实时事件；空闲 15s 发心跳；终态后立即结束
                        ├── DELETE /api/runs/{id}       → 协作式取消该 run（首个终态获胜；幂等；不触碰其它 run）
                        ├── GET  /api/session           → 会话 id / 当前状态 / 已完成历史（只有 completed 投影）
                        ├── GET  /                      → 包内 index.html；GET /{asset} → 白名单资源（app.js / styles.css）
                        └── 每个响应补 CSP / nosniff / 禁 framing；错误一律稳定信封
        └── finally: await server.close()   # service.close()（取消在途 run → cancelled 终态）→ Uvicorn shutdown（有界）
```

（浏览器体验、wheel 打包验收与文档收口在 Story 49-6。）

---

## 八、技术规范

| 规范 | 说明 |
|------|------|
| Python 版本 | 3.11+ |
| 异步模型 | 全 async/await，CLI 用 asyncio.run() 桥接 |
| 数据模型 | 统一 Pydantic BaseModel，禁止跨模块传 raw dict |
| 命名 | PEP 8 — snake_case 文件，PascalCase 类 |
| 日志 | `logging.getLogger(__name__)`，stdlib only |
| 行宽 | 120（ruff.toml） |
| 测试 | pytest + pytest-asyncio，`StubProvider` 模拟 |
| Provider 接口 | Protocol（结构化子类型），不强制继承 |

### 8.1 目标工作流质量收口

Epic 43-45 的目标级编排、checkpoint、恢复和 CLI 审计由确定性测试覆盖。`tests/test_goal_workflow_smoke.py` 使用无网络执行，验证两个 story 单元、workflow/checkpoint、ledger 与 EventBus 证据，并覆盖损坏状态显式失败（legacy 阶段状态机与其 route 门控已于 2026-09 删除）。

本地可运行 `python scripts/quality_gate.py` 串行执行冒烟、默认回归/覆盖率、ruff lint、ruff format 和 mypy；CI 另设无凭据的 `goal-smoke` job。真实 LLM 冒烟只能作为显式外部步骤，凭据缺失必须记录 blocked。当前声明式 `/goal` 的步骤权威是 `.heagent/skills/he-goal/workflow.md`；目标目录中的 `workflow.json` 只保存运行时元数据。SafetyGuard、path_safety 与 engine sandbox 仍是 defense-in-depth，非 OS 安全边界。

### 8.2 Goal/Epic/Story artifact contract

Declarative BMad workflow artifacts have three layers with fixed ownership. A goal artifact (`type: goal`) contains the Epic list only; `EPIC.md` contains Goal, Value, Scope, Dependencies, Acceptance Criteria, Stories, and Definition of Done; each Story document contains frontmatter, User Story, Given/When/Then acceptance criteria, Tasks, and Definition of Done. IDs and parent references are validated by `heagent.engine.artifacts.validate_hierarchy()`. The `/goal` CLI no longer writes a goal artifact: it persists the goal's requirement document `brief.md`, and the Epic/Story lists live in the workflow's own `02-epics.md`.

`parse_artifact()` fails loudly on missing or duplicate sections, unresolved `TBD`, invalid frontmatter type/status, and malformed parent metadata. Templates are in `.heagent/skills/he-goal/templates/`. Historical Epic/Story status is owned solely by `_bmad-output/sprint-status.yaml`; `workflow.json` stores runtime metadata and is never a second status board. `validate_sprint_status_path()` enforces this canonical, read-only target.

### 8.3 Declarative Agile Closure

`.heagent/skills/he-goal/workflow.md` is the required, self-contained `/goal` workflow. It declares initialization and the complete ordered steps; the CLI only maps supported declarations to deterministic operations. `WorkflowRunner` executes one declared step per invocation, persists zero-based completed-step checkpoints, and rejects missing inputs, invalid outputs, and mismatched workflow recovery state. `brief.md` is the goal's durable requirement document (the original request at creation, then the derived requirements step 01 writes after its initial analysis); goals created before the rename keep their own `require.md` (or older `GOAL.md`), resolved newest-name-first by `goal/document.py`, and its resolved filename is injected into the step prompt as `{goal_document}` so the workflow declarations never hardcode it; it replaces `goal.txt` and is deliberately not a `parse_artifact()` goal artifact. Goal documents and workflow.json remain under `_he-output/`. New goals record an absolute workspace in `checkpoint-workspace.txt` and store checkpoints under `<workspace>/.heagent/checkpoints/<goal_id>/`; goals without that marker retain their original goal-local `checkpoints/` directory. Invalid markers fail explicitly; a missing workflow is an explicit failure. The former imperative `goal.txt` story-board path has been removed, leaving the declarative runner as the sole `/goal` execution path. Transition policy remains owned by the active workflow and its deterministic runner. The workflow itself is addressed as a skill package (`he-goal`) resolved through `SkillCatalog`/`SkillResolver`, so per-run policy (`max_rounds`, `auto_schedule`, open-question wording) and the step prompt/gate wording are declarations inside the package (`workflow.md`, `templates/prompt-template.md`, `templates/gate-template.md`); template requiredness is itself declared in the workflow frontmatter (`required_resources`) — the loader fails the load explicitly when a declared template is missing or blank (entries are prefix-normalized and every entry is enforced: a typo'd name fails the load instead of being ignored), a blank-but-undeclared template fails loudly at prompt-render time instead of producing an empty step prompt/gate block, and the CLI carries no built-in template wording.

## 九、历史与迁移

参考实现来源和迁移索引已移至 [架构沿革](architecture-history.md)。本页保留当前行为、兼容约束和测试入口。

### 工作区状态路径（Story 50-1）

`WorkspacePaths` 从构造时解析的项目根派生运行状态路径；HTTP/TCP 装配与 CLI loop 优先使用已注入 engine 的根，不在每次请求时重读 cwd。GUI 继续保留 `context_dir=None` 的既有语义，本次不改变其上下文发现行为。路径围栏仍是 defense-in-depth，不是 OS 安全边界。
