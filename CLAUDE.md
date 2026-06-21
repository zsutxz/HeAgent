# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## ⚠️ 安全声明

HeAgent 执行 shell / 读写文件 / 调外部 API，并可连接**外部 MCP server**（其进程、命令、HTTP transport 均由 `.mcp.json` 声明，可能来自任意第三方）。`SafetyGuard` **不是真正的安全边界**（命令黑名单可绕过、工具返回内容无围栏进入上下文、prompt injection 无隔离）。**不可在不可信内容或不可信 LLM 输出下裸跑**——必须配 OS 级沙箱（容器/firejail）。修改安全相关代码时勿将其当作有效边界。

**MCP 特定风险（FR-10/11，与上述立场同构，不制造「接 MCP 更安全」假象）：**

- **外部 MCP server = 不可信代码**：stdio server 会拉起任意本地子进程，HTTP server 会连任意远程端点；V1 `SafetyGuard` **不**扩展到 MCP 工具调用（架构决策 deferred，见 architecture DP-4）。
- **MCP 工具输出无隔离进入 LLM 上下文**：server 返回内容（含远端响应）直接并入对话，prompt injection 无围栏——视为与内置工具返回**同等不可信**。
- **同等约束**：MCP 工具走与内置工具一致的 `ToolError` 语义，但**不**享受额外的预校验或返回内容复核。
- **须 OS 级沙箱兜底**：连 MCP server 时同样必须在沙箱内运行，并对子进程 / 出站网络施加最小权限。

**后续（deferred / future，V1 未做）：** 运行时断连工具的自动 unregister（当前仅调用降级 `ToolError`，见 architecture FR-3）、`SafetyGuard` 扩展到 MCP（敏感工具确认 / 返回内容复核）、Resources/Prompts 原语、写操作。

## 构建与测试命令

```bash
# 安装（可编辑模式，含开发依赖）
pip install -e ".[dev]"

# 运行全部测试（pytest-asyncio auto 模式）
pytest

# 运行单个测试文件 / 单个测试
pytest tests/test_config.py
pytest tests/test_config.py::test_default_settings -v

# Lint
ruff check src tests

# 格式化
ruff format src tests

# 类型检查
mypy src

# 运行 CLI（单次执行模式）
python -m heagent "你的提示词"

# 运行 CLI（交互式聊天模式）
python -m heagent
```

## 架构

HeAgent 是一个自学习 AI Agent 框架——单进程异步 Python 库，编排 LLM ↔ 工具执行循环。所有 I/O 都是 `async/await`；CLI 入口通过 `asyncio.run()` 桥接。

### 数据流

```
User → CLI (click) → AgentLoop → Provider.send() → LLM API
                                              ↓
                                    ProviderResponse (有 tool_calls?)
                                              ↓ 是
                              SafetyGuard.check() → ToolRegistry handler
                                              ↓
                                    ToolResult → 回到 AgentLoop
                                              ↓ 无 tool_calls
                                    最终文本回答 → User
```

### 模块依赖 DAG

```
exceptions  types  config
    ↑          ↑       ↑
    └─ providers ─┴── tools ─┴── context ── agent
                            ↑              ↑
                        memory ─────────────┘
```

- `agent/` 是顶层编排器——依赖所有其他模块。
- `providers/` 和 `tools/` 相互独立。
- `exceptions.py` 和 `types.py` 是叶子模块，无内部依赖。
- 新增 provider 或 tool 禁止从 `agent/` 导入。
- `tools/mcp/` 是 `tools/` 下的 MCP 适配子层：依赖 `types`（`ToolSchema`）/ `exceptions`（`ToolError`）/ `tools.registry`（`ToolRegistry.register()`），**禁止**从 `agent/` 导入（`AgentLoop` 零改动，仅经 registry 注入工具）。

### 关键设计决策

1. **Provider 抽象**：`BaseProvider` 是 `typing.Protocol`（结构化子类型，非继承）。所有 provider 实现 `send()`、`stream()`、`get_metadata()`。`ProviderChain` 包装有序列表，失败时自动切换到下一个 provider。
2. **工具注册**：`@tool` 装饰器提取函数签名 + 类型提示 + docstring → `ToolSchema`。`ToolRegistry` 是进程级单例。工具并行执行通过 `asyncio.gather`。
3. **中间件管道**：`(Request, NextFn) -> Response` 链式组合，在 `middleware.py` 中实现。注入到 `AgentLoop._call_provider` 的调用路径中。
4. **异常层级**：所有异常继承 `HeAgentError` → `ProviderError` / `ToolError` / `SafetyViolation` / `BudgetExceeded`。禁止抛出裸 `Exception`。
5. **配置**：`pydantic-settings` 的 `Settings` 类，从 `.env` + 环境变量加载。通过 `get_settings()` 获取单例。测试中用 `reset_settings()` 重置。
6. **记忆持久化**：`.heagent/` 目录（skills/、memory/、user/）以 Markdown 文件存储。V1 使用关键词匹配去重。技能采用 HermesAgent 标准目录结构：`skills/<name>/SKILL.md`（必需）+ 可选的 `templates/`、`references/` 子目录。SKILL.md 使用 YAML frontmatter + 扁平编号步骤（`## Steps` 下每步单行）。
7. **重试机制**：`providers/retry.py` 中的 `retry_with_backoff()` 将错误分类为 `RATE_LIMITED | AUTH_FAILED | TRANSIENT | NON_TRANSIENT`。仅对 `TRANSIENT` 错误进行指数退避 + 抖动重试。通过 `middleware.make_retry_middleware()` 包装，在 `cli.py` 注入为 `AgentLoop.middlewares`。

### 模块速查

| 模块 | 用途 | 关键类/函数 |
|------|------|------------|
| `types.py` | 所有跨模块 Pydantic 模型 | `Message`、`ToolCall`、`ToolResult`、`ProviderResponse`、`ToolSchema`、`TokenUsage` |
| `config.py` | 配置单例 | `Settings`、`get_settings()`、`reset_settings()` |
| `exceptions.py` | 异常层级根 | `HeAgentError` → `ProviderError` / `ToolError` / `SafetyViolation` / `BudgetExceeded` |
| `providers/base.py` | Provider 协议 | `BaseProvider(Protocol)` — `send()`、`stream()`、`get_metadata()` |
| `providers/openai.py` | OpenAI 兼容 provider | `OpenAIProvider` — 支持自定义 `base_url`（DeepSeek、zhipu 等） |
| `providers/anthropic.py` | Anthropic provider | `AnthropicProvider` — 按 Anthropic API 约定提取 system 消息 |
| `providers/chain.py` | 降级链 | `ProviderChain` — 失败时切换下一个 provider，用尽后重置 |
| `tools/decorator.py` | `@tool` 装饰器 | 内省签名 + docstring → `ToolSchema`，Python 类型 → JSON Schema 映射 |
| `tools/registry.py` | 进程级工具注册表 | `ToolRegistry.get()` 单例，支持按工具启用/禁用 |
| `tools/safety.py` | Shell 命令安全守卫 | `SafetyGuard` — BLACKLIST/WHITELIST 模式，12 个危险模式（rm -rf、fork bomb 等） |
| `tools/builtins/` | 内置工具（7 模块 / 18 工具） | `shell`、`file_read`、`file_write`、`file_search`、`content_search`（基础 5）+ `cron_*`、`fact_add`/`profile_update`、`skill_*`、`task_delegate`/`task_parallel` |
| `tools/path_safety.py` | 工作区路径围栏 | `resolve_workspace_path()` — 阻止 file 工具路径逃逸出 CWD（非真正安全边界，见文首声明） |
| `tools/mcp/config.py` | 声明式 MCP server 配置 | `MCPConfig`、`StdioServerConfig`、`HttpServerConfig`、`load_mcp_config()` — `.mcp.json` + `${ENV}` 插值（fail-fast） |
| `tools/mcp/mapping.py` | MCP 工具映射/桥接 | `mcp_tool_to_schema()`（namespace `<server>__<tool>`）、`bridge_result()`（`isError`→`ToolError`） |
| `tools/mcp/manager.py` | MCP server 连接生命周期 | `MCPClientManager` — async ctx mgr，并发连接+发现+注册、失败/超时隔离、`AsyncExitStack` 退出清理 |
| `providers/key_rotation.py` | 同 Provider 多密钥轮换 | `KeyRotatingProvider` — 429/401/403 时切换下一个密钥，密钥池耗尽才向上抛出 |
| `agent/loop.py` | 核心 Agent 循环 | `AgentLoop` — 迭代 provider→tool_calls→execute→loop 直到文本回答 |
| `agent/middleware.py` | 中间件组合 | `compose()` 构建递归 `(Request, NextFn) → Response` 链 |
| `agent/sub.py` | 子 Agent 隔离 | `SubAgent` — 独立 loop+上下文，`run_parallel()` 通过 `asyncio.gather` 并行 |
| `context/compressor.py` | 上下文窗口压缩 | `ContextCompressor` — token 使用率 ≥ 阈值时摘要旧消息 |
| `context/session.py` | 会话持久化 | `SessionStore` — `.heagent/sessions/` 下的 JSON 文件 |
| `memory/skills.py` | 技能存储 | `SkillStore` — `.heagent/skills/<name>/SKILL.md`，HermesAgent 标准目录结构（可选 templates/、references/） |
| `memory/facts.py` | 事实存储（含去重） | `FactStore` — `.heagent/memory/MEMORY.md`，70% 关键词重叠去重 |
| `memory/profile.py` | 用户档案分区 | `ProfileStore` — `.heagent/user/USER.md`，按 section 更新 |
| `memory/soul.py` | 人格系统 | `SoulStore` — 全局 `~/.heagent/SOUL.md` + 项目 `.heagent/SOUL.md` |
| `context/loader.py` | 上下文文件扫描 | `load_context_files()` — 按 .heagent/CONTEXT.md > AGENTS.md > CLAUDE.md 优先级 |
| `context/tokens.py` | Token 估算 | `count_tokens()` — CJK 感知启发式估算器 |
| `cron/jobs.py` | 定时任务模型 | `CronJob(BaseModel)` + `JobStore` — `.heagent/cron/jobs.json` |
| `cron/scheduler.py` | 后台调度器 | `CronScheduler` — asyncio 后台，手写 cron 解析，构造函数注入 provider+stores |

### 共享类型（`types.py`）

所有跨模块数据流通过 Pydantic 模型传递：`Message`、`ToolCall`、`ToolResult`、`ProviderResponse`、`ToolSchema`、`TokenUsage`。模块间禁止传递原始 dict。

### 测试结构

测试主要平铺在 `tests/` 目录下（不镜像 `src/` 子目录结构）。例外是 provider 测试：`tests/providers/`。Agent loop 测试使用 `StubProvider`，provider 测试 mock SDK 调用。测试中需要通过 `reset_settings()` 重置 `Settings` 单例。

### CLI 入口

`cli.py` 按优先级 **DeepSeek (`DEEPSEEK_API_KEY`) → OpenAI → Anthropic** 自动检测 provider。模块级导入 `heagent.tools.builtins` 触发 `@tool` 注册。单次执行模式（带 PROMPT 参数）和交互式聊天模式（无参数），均通过 `asyncio.run()` 桥接。CLI 创建 `SkillStore` / `FactStore` / `ProfileStore` / `SoulStore` 并传入 `AgentLoop`，注入 `make_retry_middleware()` 到 `middlewares`，并通过 `configure_subagent_tools()` 装配子 Agent 工具。

Provider 装配见 `cli._build_provider()`：DeepSeek 用 OpenAI 兼容接口（`base_url=api.deepseek.com/v1`）；同一 provider 的主 key + `*_key_pool` 合并去重后，多于 1 个时用 `KeyRotatingProvider` 包装；多个 provider 用 `ProviderChain` 包装。

### 技能系统

技能存储在 `.heagent/skills/<name>/SKILL.md`，遵循 HermesAgent 标准目录结构：
- `SKILL.md` — 必需，YAML frontmatter（name/description/created/tags）+ Markdown 正文（`## Pattern` 触发关键词 + `## Steps` 扁平编号步骤）
- `templates/` — 可选，输出模板文件
- `references/` — 可选，参考文档

匹配算法：用户提示词词集 ∩ 技能 pattern+tags 词集 / pattern 词集长度 ≥ `skill_match_threshold`（默认 0.3）。匹配的技能内容注入系统提示词，最多 `skill_max_auto_invoke`（默认 3）个。

## 代码规范

- **命名**：PEP 8——`snake_case.py`、`PascalCase` 类名，不加 `Protocol`/`Interface` 后缀，async 方法不加 `_async` 后缀。
- **数据模型**：一律使用 Pydantic `BaseModel`，不用 `dataclass` 或原始 `dict`。（例外：内部状态对象 `AgentState` 和 `SubAgentResult` 使用 `dataclass`。）
- **异步**：全部异步。库代码中不出现同步 I/O。`click` CLI 通过 `asyncio.run()` 桥接。
- **日志**：每个模块 `logging.getLogger(__name__)`，仅使用标准库。
- **行宽**：120（ruff.toml）。
- **Python 版本**：3.11+。

## 项目状态

全部 10 个 epic 已完成（24 个 FR 已实现）。详见 `docs/sprint-status.yaml`。

### 自学习闭环（Epic 6-10，新增）

| 模块 | 用途 | 关键类/函数 |
|------|------|------------|
| `context/loader.py` | 上下文文件扫描 | `load_context_files()` — 扫描 .heagent/CONTEXT.md、AGENTS.md、CLAUDE.md |
| `memory/soul.py` | 人格系统 | `SoulStore` — 全局+项目两级 SOUL.md，项目级覆盖全局级 |
| `cron/jobs.py` | 定时任务模型 | `CronJob(BaseModel)` + `JobStore` — `.heagent/cron/jobs.json` 持久化 |
| `cron/scheduler.py` | 后台调度器 | `CronScheduler` — asyncio 后台任务，手写 5-field cron 解析 |
| `tools/builtins/cron.py` | Cron 工具 | `cron_add`、`cron_list`、`cron_remove` |

### 系统提示词注入顺序

`_build_system()` 按以下顺序组装系统提示词：
1. `<identity>` — SOUL.md 人格（最顶层，`insert(0, ...)`）
2. 用户 system 字符串
3. `<project-context>` — 上下文文件
4. `<skills>` — 自动匹配的技能
5. `<memory>` — 事实记忆
6. `<memory-nudge>` — 记忆保存提醒
7. `<profile>` — 用户画像

### Provider 容错分层（FR-4）

三层独立容错，由 `cli.py` 组装，从内到外依次触发：
1. **重试（同一次调用内）**：`retry_with_backoff` 中间件仅对 `TRANSIENT`（5xx/超时/连接）做指数退避重试。
2. **密钥轮换（同一 Provider）**：`KeyRotatingProvider` 在 429/401/403 时切换同类型的下一个密钥；密钥池耗尽才向上抛出。
3. **跨 Provider 回退**：`ProviderChain` 在不同 provider 间切换。回退精度——仅 `RATE_LIMITED`/`AUTH_FAILED`/`TRANSIENT` 回退；`NON_TRANSIENT`（400/422 等客户端错误）立即抛出不回退。成功后复位到主 Provider（不粘性旁路）。流式版多一条约束：一旦已向下游交付过 chunk，后续异常不再回退（避免重放导致重复前缀）。

### 已知缺口

- Cron 表达式解析器 V1 不支持范围表达式（如 `1-5`）。
- `SafetyGuard` 与 `path_safety` 均非真正安全边界——见文首安全声明。
- MCP V1 边界与范围：`SafetyGuard` 未覆盖 MCP 工具（deferred，DP-4）；运行时断连工具不自动 unregister（仅调用降级 `ToolError`，FR-3）；仅接 Tools 原语（Resources/Prompts、写操作 deferred）。
