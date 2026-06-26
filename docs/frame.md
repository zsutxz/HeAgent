# HeAgent 项目架构与工作流程

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

---

## 三、模块依赖关系 (DAG)

```
exceptions  types  config
    ↑          ↑       ↑
    └─ providers ─┴── tools ─┴── context ── engine ── agent
                            ↑              ↑
                        memory ───── cron ──┘
```

**依赖规则：**
- `agent/` 是顶层编排器，依赖所有其他模块
- `providers/` 和 `tools/` 互不依赖
- `exceptions.py` 和 `types.py` 是叶子模块，无内部依赖
- 新增 Provider 或 Tool **禁止**从 `agent/` 导入
- `engine/` 是运行时治理层（policy/executor/store/ledger/observability），依赖 `types`/`exceptions`/`tools.safety`；被 `agent/` 依赖（`AgentLoop` 经 `EngineContainer` 注入）

---

## 四、核心模块详解

### 4.1 CLI 入口 (`cli.py`)

| 功能 | 说明 |
|------|------|
| 入口命令 | `python -m heagent [PROMPT]` |
| 单次模式 | 传入 PROMPT 参数，执行后退出 |
| 交互模式 | 不传参数，进入 REPL 聊天循环 |
| Provider 构建 | 自动检测 `DEEPSEEK_API_KEY` → `OPENAI_API_KEY` → `ANTHROPIC_API_KEY` |
| 工具注册 | 导入 `heagent.tools.builtins` 触发 `@tool` 注册 |
| 模块初始化 | 自动创建 SkillStore、FactStore、ProfileStore、SoulStore、SessionStore、ContextCompressor、JobStore |
| Cron 调度 | 交互模式下启动 CronScheduler 后台任务 |
| 重试中间件 | 通过 `make_retry_middleware()` 接入 AgentLoop |
| Token 统计 | 每次回答后显示 `[tokens: N in + M out = T total]` |

### 4.2 Agent 核心 (`agent/`)

#### loop.py — 主循环

| 组件 | 说明 |
|------|------|
| `AgentState` | 单次运行的可变状态（消息列表、迭代计数、结果） |
| `AgentLoop` | 核心编排器，循环调用 Provider → 执行 Tool → 直到获得文本回答 |
| `run(prompt)` | 入口方法，构建初始消息后进入循环 |
| `run_stream(prompt)` | 流式入口，逐步 yield `StreamEvent`（`text`/`tool_call`/`tool_result`/`done`）；命中 `tool_calls` 时回退 `send()` 重取该轮调用 |
| `resume(run_id)` | 从 `RunStore` 加载快照续跑（P3）：COMPLETED 直接返回 `final_answer`，否则用 `metadata['progress_summary']` 重建窗口续跑，同 `run_id` 跨多段 context window；内部经 `_resume` 注入 `run()` 的初始化分支 |
| `resume_stream(run_id)` | `resume` 的流式版（P5-5）：COMPLETED 产出单个携带缓存答案的 `done` 事件；否则同上重建窗口后经 `_resume` 注入 `run_stream()` 流式续跑 |
| `_build_system()` | 构建系统提示词（含人格/上下文/技能/记忆注入，见下方注入顺序） |
| `_call_provider()` | 通过 Middleware 链调用 Provider，含 Token 估算对比 |
| `_execute_tools()` | `asyncio.gather()` 并行执行所有 tool_calls |
| `_execute_one()` | `ExecutionLedger` 幂等（key=`run_id:call.id`，COMPLETED 短路返回缓存）→ `PolicyEngine.evaluate()` → `ToolExecutor` 分发（内部 `SafetyGuard.check()`）→ handler；防 window_reset 后模型重发相同 `tool_call.id`（P4，见 4.12） |
| `last_usage` | 最近一次 `run()` 的累计 `TokenUsage` |
| `last_iteration` | 最近一次 `run()`/`run_stream()` 的迭代次数 |
| `last_run_context` | 最近一次 `run()` 的 `RunContext`（run_id / 迭代 / 审批·沙箱授权元数据） |

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
4. <skills>          — 自动匹配的技能
5. <memory>          — 事实记忆
6. <memory-nudge>    — 记忆保存提醒
7. <profile>         — 用户画像
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

子 Agent 默认带 `ContextCompressor`（D4：不开 window_reset，短任务走原位压缩）。角色化时由父 `engine` 经 `dataclasses.replace` 换角色专属 `PolicyEngine`（allowed_tools/blocked_tools），其余运行时服务（store/ledger/events）复用。

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
  ├── BLACKLIST 模式：拦截 12 种危险模式（rm -rf, fork bomb, format, dd...）
  └── WHITELIST 模式：仅允许白名单命令
```

仅对 `shell` 工具生效，违反时抛出 `SafetyViolation`。

#### path_safety.py — 工作区路径校验（文件工具）

文件类工具（`file_read` / `file_write` / `file_search` / `content_search`）写入前调用
`resolve_workspace_path(path)`，解析后若逃逸出当前工作区根（含 `../` 越界、绝对路径指向外部），
抛出 `WorkspacePathError`。`workspace_root()` 默认取 `Path.cwd()`，`set_workspace_root()`
提供测试可注入的覆盖入口（无需 monkeypatch cwd）。

#### builtins/ — 19 个内置工具

**基础工具（5 个）：**

| 工具 | 文件 | 功能 |
|------|------|------|
| `shell` | `shell.py` | 执行 shell 命令 |
| `file_read` | `file.py` | 读取文件内容 |
| `file_write` | `file.py` | 写入文件 |
| `file_search` | `search.py` | 按文件名搜索 |
| `content_search` | `search.py` | 按内容搜索文件 |

**技能管理工具（6 个，`skills.py`）：**

| 工具 | 功能 |
|------|------|
| `skill_create` | 创建新技能（SKILL.md + 目录结构） |
| `skill_update` | 更新已有技能内容（仅改非空字段） |
| `skill_list` | 列出所有已注册技能 |
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

技能工具在 `AgentLoop` 接收 `SkillStore` 时激活；记忆工具在接收 `FactStore`/`ProfileStore` 时激活；
Cron 工具在接收 `JobStore` 时激活；子 Agent 工具由 cli.py 调用 `configure_subagent_tools(provider)`
注入 Provider/Registry/Guard 激活（单次与交互模式均激活）。委派结果经 `_record_step()` 写入 supervisor 的 `metadata['completed_steps']`（含 iterations/run_id，跨窗口重置存活）。未注入时工具返回 `status=error` 结构化错误，不抛异常。

### 4.5 上下文管理 (`context/`)

#### loader.py — 上下文文件扫描

| 函数 | 说明 |
|------|------|
| `load_context_files(cwd)` | 扫描 `.heagent/CONTEXT.md` > `AGENTS.md` > `CLAUDE.md`，按优先级合并 |

#### tokens.py — Token 估算

| 函数 | 说明 |
|------|------|
| `count_tokens(messages)` | CJK 感知启发式估算，无需外部依赖（tiktoken 等） |

估算策略：CJK 字符 ~1 token/字符，其他 ~4 字符/token，每条消息 +3 结构开销。

#### compressor.py — 上下文压缩

Token 用量 ≥ `compression_threshold` 时，通过 LLM 摘要旧消息，防止上下文窗口溢出。

#### window_reset.py — 上下文窗口重置（checkpoint-resume）

Token 用量 ≥ 阈值（默认 0.6）时**清窗重建**：把整段对话压成一条进度摘要 + 原始 task + 续跑提示，
写入 `RunContext.metadata['progress_summary']/['segment']`（跨清窗存活），配合 `AgentLoop.resume()`
同 `run_id` 跨多段 context window 续跑。与 `compressor` **互斥**（运行期二选一，`AgentLoop.__init__`
断言，D3）——compressor 原位摘要保留 recent 消息，window_reset 更激进地整窗重置；摘要提示词与
compressor 一致。reset 不重置 iteration/accumulated（防绕预算）。`run`/`run_stream` 在工具消息追加后检查触发。

#### session.py — 会话持久化

`.heagent/sessions/<session_id>.json` 存储/恢复**对话历史**（消息列表）。交互模式下通过 `session_id` 自动保存/恢复。

> 注意：另有一套 `engine/store.py` 的 `RunStore`（`.heagent/runs/<run_id>.json`）保存**单次运行快照**（含上下文 / 结果 / 最终答案），见 4.12。两者用途不同——session 是跨轮对话历史，RunStore 是单次 run 的可恢复快照。

### 4.6 记忆系统 (`memory/`)

#### facts.py — 事实存储

`.heagent/memory/MEMORY.md`，70% 关键词重叠去重。通过 `fact_add` 工具由 LLM 自主保存。

#### skills.py — 技能存储

`.heagent/skills/<name>/SKILL.md`，HermesAgent 标准目录结构（可选 `templates/`、`references/`）。匹配算法：用户提示词词集 ∩ 技能 pattern+tags 词集 / pattern 词集长度 ≥ `skill_match_threshold`。

#### profile.py — 用户画像

`.heagent/user/USER.md`，按 section 更新。通过 `profile_update` 工具由 LLM 自主维护。

#### soul.py — 人格系统

两级 SOUL.md 加载：全局 `~/.heagent/SOUL.md` + 项目 `.heagent/SOUL.md`。项目级存在时覆盖全局级，不做合并。

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
| 手写 cron 解析 | 5-field（分 时 日 月 星期），支持 `*`、`*/N`、具体值、逗号列表 |
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
- `get_settings()` 单例访问，`reset_settings()` 用于测试重置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `deepseek_api_key` | None | DeepSeek API Key（优先） |
| `openai_api_key` | None | OpenAI API Key |
| `anthropic_api_key` | None | Anthropic API Key |
| `deepseek_base_url` | None | DeepSeek API 基础 URL |
| `openai_base_url` | None | OpenAI 兼容服务 URL |
| `anthropic_base_url` | None | Anthropic 代理地址 |
| `anthropic_prompt_caching` | True | Anthropic 提示词缓存（注入 cache_control 断点，FR-3；不兼容代理时关闭） |
| `openai_api_keys` | "" | OpenAI 多密钥池（逗号分隔） |
| `anthropic_api_keys` | "" | Anthropic 多密钥池（逗号分隔） |
| `default_model` | `gpt-4o` | 默认模型 |
| `max_iterations` | 50 | Agent 循环最大迭代次数 |
| `max_context_tokens` | 128000 | 模型上下文窗口大小 |
| `compression_threshold` | 0.8 | 上下文压缩触发阈值 |
| `shell_timeout` | 120 | Shell 命令超时（秒） |
| `retry_max_attempts` | 3 | 最大重试次数 |
| `retry_base_delay` | 1.0 | 重试基础延迟（秒） |
| `retry_max_delay` | 30.0 | 重试最大延迟（秒） |
| `skill_match_threshold` | 0.3 | 技能关键词匹配阈值（0.0–1.0） |
| `skill_max_auto_invoke` | 3 | 最多自动注入技能数 |
| `context_files_enabled` | True | 是否自动加载项目上下文文件 |
| `memory_nudge_enabled` | True | 是否注入记忆保存提醒 |
| `skill_curator_stale_days` | 30 | 技能过期天数 |
| `cron_enabled` | True | 是否启用 cron 调度 |
| `cron_tick_seconds` | 60 | 调度器检查间隔（秒） |
| `mcp_enabled` | True | 是否启用 MCP server 连接（门控，False 则跳过加载） |
| `mcp_config_path` | `.mcp.json` | MCP server 声明式配置文件路径 |

---

### 4.11 MCP 集成 (`tools/mcp/`)

**架构：** async ctx mgr 生命周期，连接时发现+注册到 ToolRegistry，退出时 unregister+优雅关闭。

| 模块 | 说明 |
|------|------|
| `config.py` | `MCPConfig`、`StdioServerConfig`、`HttpServerConfig` + `load_mcp_config()`（`.mcp.json` + `${ENV}` 插值，fail-fast） |
| `mapping.py` | `mcp_tool_to_schema()`（namespace `<server>__<tool>`）、`bridge_result()`（`isError`→`ToolError`） |
| `manager.py` | `MCPClientManager` — 并发连接+发现+注册，单 server 失败/超时隔离（工具不注入，不崩溃 agent） |

**V1 边界：**
- `SafetyGuard` 未覆盖 MCP 工具（deferred DP-4）
- MCP 工具返回内容直接进入 LLM 上下文，prompt injection 无隔离
- 仅接 Tools 原语，Resources/Prompts、写操作 deferred
- 运行时断连后工具不自动 unregister，调用降级为 `ToolError`

---

### 4.12 运行时引擎 (`engine/`)

epic 收尾后引入的 P0 loop engine runtime——围绕 `AgentLoop` 的运行时治理层，经 `EngineContainer`（DI 容器）注入。工具执行改为**策略门控**：先 `PolicyEngine` 裁决，再 `ToolExecutor` 分发。

| 模块 | 说明 |
|------|------|
| `container.py` | `EngineContainer` — DI 容器，`default(workspace_root=)` 装配全部服务；`create_run_context()` 产出单次运行上下文 |
| `context.py` | `RunContext`（run_id/session_id/parent_run_id/workspace_root/iteration/metadata）、`RunStatus`（running/completed/failed） |
| `policy.py` | `PolicyEngine.evaluate_tool_call()` → `PolicyVerdict`（`DIRECT`/`APPROVAL_REQUIRED`/`SANDBOX_REQUIRED`/`BLOCKED`）：准入 allowlist/blocklist、MCP 门控、工作区路径围栏、审批/沙箱裁决 |
| `roles.py` | `RoleSpec`（name/system/allowed_tools/blocked_tools/max_iterations/sandbox_profile）+ 内置角色（planner/coder/tester/supervisor）+ `get_role`/`register_role`；`SubAgent` 用其构建角色专属 `PolicyEngine`（P1/P2） |
| `executor.py` | `ToolExecutor.execute()` 按 verdict 模式分发；内部串行调 `SafetyGuard.check()`；`SANDBOX_REQUIRED` 默认 `execute_in_sandbox()` **透传**（未接真实后端，非安全边界） |
| `store.py` | `RunStore` — `.heagent/runs/<run_id>.json` 运行快照 checkpoint（start/checkpoint/load）；`RunNode` + `build_run_tree(root_id=None)` 按 `parent_run_id` 聚合成树/森林（确定性、sorted；P5-4） |
| `ledger.py` | `ExecutionLedger` — `.heagent/ledger/` 幂等与租约（acquire/complete/fail/heartbeat）；**接入 `AgentLoop._execute_one`**（key=`run_id:call.id`，COMPLETED 短路返回缓存，防 window_reset 后重发相同 tool_call.id，P4）+ 供 cron 等长任务用 |
| `observability.py` | `EventBus`/`EngineEvent`/`LoggingObserver` — `_emit()` 发布运行时事件，有界保留 |

**与 `SafetyGuard` 的关系：** `PolicyEngine`（准入/工作区/审批/沙箱裁决）与 `SafetyGuard`（shell 命令模式黑名单）职责分离、**串行执行**——policy 先裁决、executor 内再过 guard。`AgentLoop` 每次 `run()` 用 `RunContext` 跟踪 run_id/迭代，`_runtime_scope()` 绑定 skill/memory/cron/subagent 工具运行态，`_emit()` 发事件、`run_store.checkpoint()` 持久化。子 Agent 经 `parent_run_id` 继承父 `engine`。

**多 Agent 角色化 + checkpoint-resume（P1–P5）：** `roles.py` 定义 planner/coder/tester/supervisor 等角色（执行级 allowlist，D1），supervisor 经 `task_delegate`/`task_parallel` 委派角色化 `SubAgent`（D2），结果以结构化 JSON（`SubTaskOutcome`，含 run_id/iterations）写 `metadata['completed_steps']`（P5-3）；token≥阈值时 `window_reset` 清窗重建、`AgentLoop.resume(run_id)` / `resume_stream(run_id)` 同 run_id 跨多段窗口续跑（D3，见 4.2/4.5；流式版 P5-5）；子 agent 不开 resume、默认带 compressor（D4）。`RunStore.build_run_tree()` 按 `parent_run_id` 把 supervisor/子 agent 的 run 聚合成树（P5-4）。

> **P5 范围说明：** 已实现干净增量三件套——结构化子任务结果（P5-3）、`parent_run_id` 树形 checkpoint 聚合（P5-4）、resume 流式版（P5-5）。原 deferred 项经 2026-06-26 评估**暂不反转，维持 D1/D4 冻结**：
> - **P5-1 Schema 级工具隐藏（反转 D1）**：plan 触发条件"误调率高才做"。现状 `roles.py` 每个 prompt 逐字内嵌工具清单且与 `allowed_tools` 逐一对齐（措辞"仅这些，调用其他工具会被拦截"）+ 执行级拦截 `policy.py:88` 兜底，误调率基线极低。**D1 反转成本被原 plan 高估**——`registry.py` 已有 `_disabled`/`enabled_schemas()` schema 级隐藏设施，真要做只需在 `loop.py:304/623` 取 schema 时叠加一行 `allowed_tools` 过滤，不必重构单例为 per-agent；待观测到真实高误调率再启动。
> - **P5-2 子 agent resume（反转 D4）**：plan 触发条件"实测需要才开放"。子 agent 短任务（`max_iterations` 15–25 + 默认 compressor in-place 摘要）量级远不到需清窗重建；反转代价是 `.heagent/runs/` checkpoint 文件爆炸（`task_parallel` 并行放大）+ 嵌套 resume 级联 + 与互斥断言冲突，收益/成本比差。
> （评估基于静态代码分析，未跑真实 LLM 实测；依据详见 memory `heagent-loop-engine-expansion`。）

---

## 五、已知缺口

| 缺口 | 说明 |
|------|------|
| 流式 tool_calls 回退 | `run_stream()` 多数 Provider 在流式模式不返回 `tool_calls`，命中 `finish_reason=tool_calls` 时回退 `send()` 重取该轮调用（已知设计权衡） |
| Cron 范围表达式 | V1 解析器不支持范围表达式（如 `1-5`） |
| MCP SafetyGuard 覆盖 | V1 `SafetyGuard` 未覆盖 MCP 工具调用（deferred DP-4） |
| MCP 运行时断连 | 运行时断连的工具不自动 unregister，调用降级为 `ToolError` |
| CLI 事件循环阻塞 | 交互模式 `input()` 为同步调用，阻塞 asyncio 事件循环（单用户 CLI 影响可接受） |
| 工作区路径双重围栏 | `PolicyEngine._validate_paths()`（executor 前，基于 `RunContext.workspace_root`，针对 file_read/file_write/file_search/content_search）与 `tools/path_safety.py`（`resolve_workspace_path()`，各 file 工具内部）两套并存、语义重叠——改其一须同步评估另一处 |
| engine sandbox 透传 | `ToolExecutor.execute_in_sandbox()` 默认透传（未接真实沙箱后端），`SANDBOX_REQUIRED` 裁决不产生 OS 级隔离效果——须 OS 级沙箱兜底 |

---

## 六、目录结构

```
src/heagent/
├── __init__.py
├── __main__.py              # python -m heagent 入口
├── cli.py                   # Click CLI（单次/交互模式）
├── config.py                # pydantic-settings 配置
├── exceptions.py            # 异常层级
├── types.py                 # 共享 Pydantic 模型
│
├── agent/                   # 顶层编排
│   ├── loop.py              # AgentLoop 核心循环
│   ├── middleware.py        # 中间件组合 + make_retry_middleware
│   └── sub.py               # 子 Agent（并行任务 + 角色化）
│
├── providers/               # LLM Provider（互不依赖）
│   ├── base.py              # BaseProvider Protocol
│   ├── openai.py            # OpenAI 兼容（含 DeepSeek）
│   ├── anthropic.py         # Anthropic（含提示词缓存 FR-3）
│   ├── chain.py             # ProviderChain 回退链（外层，FR-4 回退精度）
│   ├── key_rotation.py      # KeyRotatingProvider 密钥池轮换（中层）
│   └── retry.py             # 错误分类 + make_retry_middleware（内层）
│
├── tools/                   # 工具系统
│   ├── decorator.py         # @tool 装饰器
│   ├── registry.py          # ToolRegistry 单例
│   ├── safety.py            # SafetyGuard（shell 命令安全）
│   ├── path_safety.py       # 工作区路径校验（文件工具）
│   ├── mcp/                 # MCP 适配层
│   │   ├── config.py        # MCPConfig + load_mcp_config（.mcp.json + ${ENV} 插值）
│   │   ├── mapping.py       # mcp_tool_to_schema + bridge_result
│   │   └── manager.py       # MCPClientManager（连接生命周期 + 工具注册）
│   └── builtins/            # 内置工具（19 个）
│       ├── __init__.py      # 触发注册
│       ├── shell.py         # shell 命令执行
│       ├── file.py          # 文件读写
│       ├── search.py        # 文件/内容搜索
│       ├── skills.py        # 技能管理（create/update/list/delete/curate/archive）
│       ├── memory.py        # 记忆管理（fact_add/profile_update）
│       ├── cron.py          # Cron 管理（add/list/remove）
│       └── subagent.py      # 子 Agent 委派（task_delegate/task_parallel/task_status）
│
├── context/                 # 上下文管理
│   ├── loader.py            # 上下文文件扫描（CONTEXT.md > AGENTS.md > CLAUDE.md）
│   ├── tokens.py            # CJK 感知 Token 估算
│   ├── compressor.py        # 消息压缩
│   ├── window_reset.py      # 窗口重置 + checkpoint-resume（P3）
│   └── session.py           # 会话持久化
│
├── memory/                  # 记忆系统
│   ├── facts.py             # 事实存储 + 去重
│   ├── skills.py            # 技能存储（HermesAgent 目录结构）
│   ├── profile.py           # 用户画像
│   └── soul.py              # 人格系统（全局/项目两级）
│
├── engine/                  # 运行时引擎（P0）
│   ├── container.py         # EngineContainer（DI）
│   ├── context.py           # RunContext / RunStatus
│   ├── policy.py            # PolicyEngine 准入/审批/沙箱裁决
│   ├── roles.py             # RoleSpec + 内置角色（P1/P2）
│   ├── executor.py          # ToolExecutor 策略分发
│   ├── store.py             # RunStore 运行快照
│   ├── ledger.py            # ExecutionLedger 幂等/租约
│   └── observability.py     # EventBus / 事件
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
  ├── import heagent.tools.builtins → @tool 注册到 ToolRegistry（19 个工具）
  ├── get_settings() → 读取 DEEPSEEK_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY
  ├── _build_provider() → OpenAIProvider / AnthropicProvider / ProviderChain
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
  │     ├── <skills>              — SkillStore.match() 自动匹配 ≤ skill_max_auto_invoke 个
  │     ├── <memory-nudge>        — 记忆保存提醒
  │     ├── <memory>              — 事实记忆列表
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
  │     ├── YES → _execute_tools(calls, state)
  │     │         ├── SafetyGuard.check(call)    # 安全检查
  │     │         ├── ToolRegistry.get_handler() # 查找 handler
  │     │         ├── handler(**arguments)        # 执行
  │     │         └── ToolResult → 追加到 messages
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
