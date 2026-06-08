# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

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

### 关键设计决策

1. **Provider 抽象**：`BaseProvider` 是 `typing.Protocol`（结构化子类型，非继承）。所有 provider 实现 `send()`、`stream()`、`get_metadata()`。`ProviderChain` 包装有序列表，失败时自动切换到下一个 provider。
2. **工具注册**：`@tool` 装饰器提取函数签名 + 类型提示 + docstring → `ToolSchema`。`ToolRegistry` 是进程级单例。工具并行执行通过 `asyncio.gather`。
3. **中间件管道**：`(Request, NextFn) -> Response` 链式组合，在 `middleware.py` 中实现。注入到 `AgentLoop._call_provider` 的调用路径中。
4. **异常层级**：所有异常继承 `HeAgentError` → `ProviderError` / `ToolError` / `SafetyViolation` / `BudgetExceeded`。禁止抛出裸 `Exception`。
5. **配置**：`pydantic-settings` 的 `Settings` 类，从 `.env` + 环境变量加载。通过 `get_settings()` 获取单例。测试中用 `reset_settings()` 重置。
6. **记忆持久化**：`.heagent/` 目录（skills/、memory/、user/）以 Markdown 文件存储。V1 使用关键词匹配去重。技能采用 HermesAgent 标准目录结构：`skills/<name>/SKILL.md`（必需）+ 可选的 `templates/`、`references/` 子目录。SKILL.md 使用 YAML frontmatter + 扁平编号步骤（`## Steps` 下每步单行）。
7. **重试机制**：`providers/retry.py` 中的 `retry_with_backoff()` 将错误分类为 `RATE_LIMITED | AUTH_FAILED | TRANSIENT | NON_TRANSIENT`。仅对 `TRANSIENT` 错误进行指数退避 + 抖动重试。

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
| `tools/builtins/` | 5 个内置工具 | `shell`、`file_read`、`file_write`、`file_search`、`content_search` |
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

`cli.py` 根据可用 API Key（`OPENAI_API_KEY` / `ANTHROPIC_API_KEY`）自动检测 provider。模块级导入 `heagent.tools.builtins` 触发 `@tool` 注册。单次执行模式（带 PROMPT 参数）和交互式聊天模式（无参数），均通过 `asyncio.run()` 桥接。CLI 创建 `SkillStore` 并传入 `AgentLoop`，启动技能自动匹配。

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
1. `<identity>` — SOUL.md 人格（最顶层）
2. 用户 system 字符串
3. `<project-context>` — 上下文文件
4. `<skills>` — 自动匹配的技能
5. `<memory-nudge>` — 记忆保存提醒
6. `<memory>` — 事实记忆
7. `<profile>` — 用户画像

### 已知缺口

- `Settings` 支持多密钥池（`openai_key_pool`、`anthropic_key_pool`），但 `ProviderChain` 仅在 provider 间切换，不做密钥轮换。
- `providers/retry.py` 中的 `retry_with_backoff()` 已作为中间件接入（通过 `make_retry_middleware()`）。
- Cron 表达式解析器 V1 不支持范围表达式（如 `1-5`）。
