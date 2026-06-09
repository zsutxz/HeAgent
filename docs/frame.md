# HeAgent 项目架构与工作流程

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
│         SafetyGuard.check()  ── 拦截危险命令
│              │                           │
│              ▼                           │
│         ToolRegistry 查找 handler        │
│              │                           │
│              ▼                           │
│         asyncio.gather() 并行执行        │
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

---

## 三、模块依赖关系 (DAG)

```
exceptions  types  config
    ↑          ↑       ↑
    └─ providers ─┴── tools ─┴── context ── agent
                            ↑              ↑
                        memory ───── cron ──┘
```

**依赖规则：**
- `agent/` 是顶层编排器，依赖所有其他模块
- `providers/` 和 `tools/` 互不依赖
- `exceptions.py` 和 `types.py` 是叶子模块，无内部依赖
- 新增 Provider 或 Tool **禁止**从 `agent/` 导入

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
| `_build_system()` | 构建系统提示词（含人格/上下文/技能/记忆注入，见下方注入顺序） |
| `_call_provider()` | 通过 Middleware 链调用 Provider，含 Token 估算对比 |
| `_execute_tools()` | `asyncio.gather()` 并行执行所有 tool_calls |
| `_execute_one()` | 安全检查 → Registry 查找 → 执行 handler |
| `last_usage` | 最近一次 `run()` 的累计 `TokenUsage` |

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
| `compressor` | `ContextCompressor` | 上下文压缩器 |
| `context_dir` | `str` | 上下文文件扫描目录 |
| `soul` | `SoulStore` | 人格加载器 |
| `cron_store` | `JobStore` | Cron 任务存储（激活 Cron 工具） |

**系统提示词注入顺序（`_build_system()`）：**

```
1. <identity>        — SOUL.md 人格（最顶层）
2. 用户 system 字符串
3. <project-context> — 上下文文件（CONTEXT.md > AGENTS.md > CLAUDE.md）
4. <skills>          — 自动匹配的技能
5. <memory-nudge>    — 记忆保存提醒
6. <memory>          — 事实记忆
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
| `SubAgent` | 隔离的 Agent 实例，独立的 Loop + Context |
| `SubAgentResult` | 子任务结果（task, output, success, iterations） |
| `run_parallel()` | `asyncio.gather()` 并行运行多个子 Agent |

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

- 提取系统消息（Anthropic API 约定）
- 消息/工具调用格式转换：HeAgent ↔ Anthropic API

#### chain.py — Provider 回退链

```
ProviderChain([deepseek, openai, anthropic])
  │
  ├── 尝试 deepseek → 成功？返回
  ├── 失败 → 尝试 openai → 成功？返回
  └── 失败 → 尝试 anthropic → 成功？返回 / 全部失败则重置索引
```

#### retry.py — 重试策略

```
错误分类：
  RATE_LIMITED (429) → 不重试
  AUTH_FAILED (401/403) → 不重试
  TRANSIENT (5xx, 网络错误) → 指数退避 + 随机抖动重试
  NON_TRANSIENT (其他) → 不重试

通过 make_retry_middleware() 作为 Middleware 接入 AgentLoop
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
| `enabled_schemas()` | 返回所有已启用的 ToolSchema |

#### safety.py — 安全防护

```
SafetyGuard
  ├── BLACKLIST 模式：拦截 12 种危险模式（rm -rf, fork bomb, format, dd...）
  └── WHITELIST 模式：仅允许白名单命令
```

仅对 `shell` 工具生效，违反时抛出 `SafetyViolation`。

#### builtins/ — 14 个内置工具

**基础工具（5 个）：**

| 工具 | 文件 | 功能 |
|------|------|------|
| `shell` | `shell.py` | 执行 shell 命令 |
| `file_read` | `file.py` | 读取文件内容 |
| `file_write` | `file.py` | 写入文件 |
| `file_search` | `search.py` | 按文件名搜索 |
| `content_search` | `search.py` | 按内容搜索文件 |

**技能管理工具（4 个，`skills.py`）：**

| 工具 | 功能 |
|------|------|
| `skill_create` | 创建新技能（SKILL.md + 目录结构） |
| `skill_update` | 更新已有技能内容 |
| `skill_list` | 列出所有已注册技能 |
| `skill_delete` | 删除指定技能 |

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

技能工具在 `AgentLoop` 接收 `SkillStore` 时激活；记忆工具在接收 `FactStore`/`ProfileStore` 时激活；Cron 工具在接收 `JobStore` 时激活。

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

#### session.py — 会话持久化

`.heagent/sessions/` 下的 JSON 文件存储/恢复对话历史。交互模式下通过 `session_id` 自动保存/恢复。

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
  └── BudgetExceeded     — 迭代/Token 预算超限
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

---

## 五、已知缺口

| 缺口 | 说明 |
|------|------|
| 密钥轮换 | `Settings` 支持多密钥池（`openai_key_pool`、`anthropic_key_pool`），但 `ProviderChain` 仅在 provider 间切换，不做密钥轮换 |
| Cron 范围表达式 | V1 解析器不支持范围表达式（如 `1-5`） |

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
│   └── sub.py               # 子 Agent（并行任务）
│
├── providers/               # LLM Provider（互不依赖）
│   ├── base.py              # BaseProvider Protocol
│   ├── openai.py            # OpenAI 兼容（含 DeepSeek）
│   ├── anthropic.py         # Anthropic
│   ├── chain.py             # ProviderChain 回退链
│   └── retry.py             # 重试策略 + make_retry_middleware
│
├── tools/                   # 工具系统
│   ├── decorator.py         # @tool 装饰器
│   ├── registry.py          # ToolRegistry 单例
│   ├── safety.py            # SafetyGuard 安全防护
│   └── builtins/            # 内置工具（14 个）
│       ├── __init__.py      # 触发注册
│       ├── shell.py         # shell 命令执行
│       ├── file.py          # 文件读写
│       ├── search.py        # 文件/内容搜索
│       ├── skills.py        # 技能管理（create/update/list/delete）
│       ├── memory.py        # 记忆管理（fact_add/profile_update）
│       └── cron.py          # Cron 管理（add/list/remove）
│
├── context/                 # 上下文管理
│   ├── loader.py            # 上下文文件扫描（CONTEXT.md > AGENTS.md > CLAUDE.md）
│   ├── tokens.py            # CJK 感知 Token 估算
│   ├── compressor.py        # 消息压缩
│   └── session.py           # 会话持久化
│
├── memory/                  # 记忆系统
│   ├── facts.py             # 事实存储 + 去重
│   ├── skills.py            # 技能存储（HermesAgent 目录结构）
│   ├── profile.py           # 用户画像
│   └── soul.py              # 人格系统（全局/项目两级）
│
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
  ├── import heagent.tools.builtins → @tool 注册到 ToolRegistry（14 个工具）
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
  │           ├── loop.run(input, session_id=session_id)  # 会话自动保存/恢复
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
