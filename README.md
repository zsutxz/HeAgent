# HeAgent

![Python](https://img.shields.io/badge/python-3.11+-blue)
![Pydantic](https://img.shields.io/badge/pydantic-v2-green)
![Async](https://img.shields.io/badge/async-await-purple)
![Status](https://img.shields.io/badge/status-learning%20project-orange)

> 一个**自学习 AI Agent 核心框架**——把自主 Agent 的核心设计模式（学习循环、多模型适配、工具编排、记忆系统）用清晰、模块化的异步 Python 重新实现。受 [NousResearch Hermes Agent](https://github.com/NousResearch) 启发。

HeAgent 是一个**单进程、全异步**的 Agent 编排库：给它一个 LLM Provider 和一组工具，它驱动 `LLM ↔ 工具` 的迭代循环直到产出最终答案，过程中自动管理记忆、压缩上下文、隔离并发子任务。所有 I/O 都是 `async/await`，CLI 入口通过 `asyncio.run()` 桥接。

---

## 为什么是 HeAgent

| | |
|---|---|
| 🧩 **真正的模块化** | 清晰的依赖 DAG——新增 Provider 或工具无需触碰核心循环 |
| 🧠 **自学习闭环** | 技能自动提取与匹配、事实记忆（去重）、用户画像、两级人格系统 |
| 🛡️ **生产级容错** | Provider 降级链 + 同 Provider 多密钥轮换 + 瞬态错误重试中间件 |
| 🪄 **零样板工具** | `@tool` 装饰器从函数签名 + docstring 自动生成 JSON Schema |
| 🔒 **安全优先** | Shell 危险命令拦截 + 工作区路径逃逸校验 |
| ⚡ **并发执行** | `asyncio.gather` 并行调用独立工具与隔离子 Agent |

---

## 架构

### 核心数据流

```
User → CLI (click) → AgentLoop → Provider.send() → LLM API
                                              ↓
                                    ProviderResponse (含 tool_calls?)
                                              ↓ 是
                              SafetyGuard.check() → ToolRegistry handler
                                              ↓
                                    ToolResult → 回到 AgentLoop
                                              ↓ 无 tool_calls
                                    最终文本回答 → User
```

`AgentLoop` 是顶层编排器：每一轮调用 Provider → 若响应携带 `tool_calls`，经安全检查后并行执行工具，把结果追加回对话历史，再次调用 Provider；直到 LLM 产出不含工具调用的纯文本答案（或超出迭代预算抛出 `BudgetExceeded`）。

### 模块依赖

```
叶子层：exceptions.py · types.py · config.py        （无内部依赖）
         ↑            ↑           ↑
    providers       tools ──────→ memory            （builtins 的 memory/skills 工具依赖 memory）
         ↑            ↑                               subagent builtin 例外：依赖 agent/sub.py
         └── context ─┴──→ agent                     （顶层编排器，依赖所有模块）
```

### 系统提示词注入顺序

`AgentLoop._build_system()` 按以下顺序组装系统消息，让记忆/人格/技能都成为 LLM 可见上下文：

1. `<identity>` — SOUL.md 人格（最顶层）
2. 用户传入的 system 字符串
3. `<project-context>` — 扫描到的项目上下文文件
4. `<skills>` — 按关键词自动匹配到的技能
5. `<memory-nudge>` — 记忆保存提醒
6. `<memory>` — 跨会话事实记忆
7. `<profile>` — 用户画像

---

## 快速开始

### 安装

```bash
cd HeAgent
pip install -e ".[dev]"
```

### 配置

在项目根目录创建 `.env`，至少配置一个 Provider 密钥：

```bash
# DeepSeek（优先检测，走 OpenAI 兼容接口）
DEEPSEEK_API_KEY=sk-...
DEFAULT_MODEL=deepseek-chat

# 或 OpenAI / 兼容服务（智谱AI 等）
# OPENAI_API_KEY=sk-...
# OPENAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4

# 或 Anthropic
# ANTHROPIC_API_KEY=sk-ant-...
```

### Hello World

```bash
# 单次执行
python -m heagent "用 Python 写一个快速排序"

# 交互式聊天
python -m heagent

# 指定模型与系统提示
python -m heagent --model deepseek-chat --system "你是 Python 专家" "写一个二分查找"
```

Provider 按优先级自动检测：`DEEPSEEK_API_KEY` → `OPENAI_API_KEY` → `ANTHROPIC_API_KEY`；多 Provider 共存时用降级链回退，同一 Provider 多 Key 时自动轮换（429/401）。

---

## 使用

### 基础调用（Python API）

```python
import asyncio
from heagent import Agent, OpenAIProvider

async def main():
    provider = OpenAIProvider(api_key="sk-...", model="deepseek-chat")
    agent = Agent(provider)              # Agent 是 AgentLoop 的公开别名
    result = await agent.run("你好")      # 返回最终文本答案
    print(result)
    print(agent.last_usage)              # TokenUsage(prompt/completion/total)
    print(agent.last_iteration)          # 实际迭代轮数

asyncio.run(main())
```

### 流式输出

`run_stream()` 逐步 `yield` 事件，可在 CLI/前端实时渲染：

```python
async for event in agent.run_stream("帮我分析这段代码", system="你是资深工程师"):
    if event.type == "text":              # 文本增量
        print(event.text, end="", flush=True)
    elif event.type == "tool_call":       # 即将调用工具
        print(f"\n[calling {event.tool_name}...]", end="")
    elif event.type == "tool_result":     # 工具返回
        print(" [done]", end="")
    elif event.type == "done":            # 最终答案就绪
        print(f"\n\nFinal: {event.final_answer}")
```

### 声明式自定义工具

`@tool` 装饰器从类型提示 + docstring 自动生成 JSON Schema，无需手写字段描述：

```python
from heagent import tool

@tool
async def search_docs(query: str, top_k: int = 5) -> str:
    """搜索内部文档库，返回最相关的结果。

    Args:
        query: 搜索关键词
        top_k: 返回条目数量
    """
    return f"Found {top_k} results for: {query}"
```

注册后 LLM 即可自动调用。工具支持同步或异步函数，框架自动适配。

### 多 Provider 降级链

主 Provider 失败时自动切换下一个；客户端错误（400/422）立即抛出不回退：

```python
from heagent import Agent, ProviderChain, OpenAIProvider, AnthropicProvider

chain = ProviderChain([
    OpenAIProvider(api_key="sk-...", model="gpt-4o"),
    AnthropicProvider(api_key="sk-ant-...", model="claude-sonnet-4-6"),
])
agent = Agent(chain)
```

### 同 Provider 多密钥轮换

`KeyRotatingProvider` 在同一 Provider 的多个密钥间轮换——收到 429/401 自动切换下一个 Key，全部耗尽后交由上层 `ProviderChain` 回退到其他 Provider：

```python
from heagent.providers.key_rotation import KeyRotatingProvider
from heagent.providers.openai import OpenAIProvider

pool = KeyRotatingProvider([
    OpenAIProvider(api_key="sk-aaa", model="gpt-4o"),
    OpenAIProvider(api_key="sk-bbb", model="gpt-4o"),
    OpenAIProvider(api_key="sk-ccc", model="gpt-4o"),
])
```

> CLI 中配置 `OPENAI_API_KEYS=sk-aaa,sk-bbb,sk-ccc` 即自动启用密钥轮换，无需手写。

### 子 Agent 并行执行

`SubAgent` 拥有独立的对话上下文与迭代预算（与主循环隔离），`run_parallel()` 通过 `asyncio.gather` 真正并发：

```python
import asyncio
from heagent.agent.sub import SubAgent, run_parallel

async def main():
    agents = [SubAgent(provider) for _ in range(3)]
    results = await run_parallel(
        agents,
        ["调研话题 A", "调研话题 B", "调研话题 C"],
    )
    for r in results:          # SubAgentResult(task, output, success, iterations)
        print(r.task, r.success, r.iterations, r.output)

asyncio.run(main())
```

---

## 核心概念

### Provider 抽象

`BaseProvider` 是 `typing.Protocol`（结构化子类型，非继承）——任何实现了 `send()` / `stream()` / `get_metadata()` 的对象都是合法 Provider。内置实现：

- **`OpenAIProvider`** — OpenAI 及所有兼容接口（DeepSeek、智谱AI、Moonshot 等，自定义 `base_url`）
- **`AnthropicProvider`** — Anthropic Claude，按其 API 约定提取 system 消息，支持 prompt caching
- **`ProviderChain`** — 多 Provider 有序降级
- **`KeyRotatingProvider`** — 单 Provider 多密钥轮换
- **`retry_with_backoff`** — 错误分类（`RATE_LIMITED | AUTH_FAILED | TRANSIENT | NON_TRANSIENT`）+ 指数退避，仅对 `TRANSIENT` 重试

### 工具系统

- **`@tool` 装饰器** — 内省签名生成 `ToolSchema`，Python 类型 → JSON Schema
- **`ToolRegistry`** — 进程级单例，支持按工具启用/禁用
- **内置工具（7 个模块）** — `shell`、`file_read`/`file_write`、`file_search`/`content_search`、`cron_add`/`cron_list`/`cron_remove`、`fact_add`/`profile_update`、`skill_create`/`skill_list` 等、`task_delegate`/`task_parallel`

### 安全护栏

- **`SafetyGuard`** — Shell 命令黑名单/白名单，内置 12 个危险模式（`rm -rf`、fork bomb 等）
- **`path_safety.py`** — 文件类工具的工作区路径校验，禁止路径逃逸出工作区根

### 自学习记忆（四件套）

| 模块 | 存储 | 作用 |
|------|------|------|
| **技能** `memory/skills.py` | `.heagent/skills/<name>/SKILL.md` | HermesAgent 标准目录结构，按关键词自动匹配注入系统提示词 |
| **事实** `memory/facts.py` | `.heagent/memory/MEMORY.md` | 跨会话事实，70% 关键词重叠去重 |
| **画像** `memory/profile.py` | `.heagent/user/USER.md` | 用户偏好，按 section 更新 |
| **人格** `memory/soul.py` | 全局 `~/.heagent/SOUL.md` + 项目 `.heagent/SOUL.md` | 两级人格，项目级覆盖全局级 |

技能文件示例（`SKILL.md`）：

```markdown
---
name: code_review
description: 对代码进行结构化审查
tags: [review, quality]
---

## Pattern
code review 代码审查 审查

## Steps
1. 先通读整体结构
2. 逐函数检查正确性与边界
3. 给出分级改进建议
```

匹配算法：用户提示词词集 ∩ 技能 pattern+tags 词集 ÷ pattern 词集长度 ≥ `SKILL_MATCH_THRESHOLD`（默认 0.3），每轮最多注入 `SKILL_MAX_AUTO_INVOKE`（默认 3）个。

### 上下文压缩与会话

- **`ContextCompressor`** — token 用量超阈值时摘要旧消息，保留近期对话
- **`SessionStore`** — `.heagent/sessions/` 下 JSON 文件持久化对话历史

### 定时任务（Cron）

- **`CronScheduler`** — asyncio 后台任务，手写 5-field cron 解析
- **`CronJob` + `JobStore`** — `.heagent/cron/jobs.json` 持久化
- 通过 `cron_add` / `cron_list` / `cron_remove` 工具由 LLM 自主管理

---

## 项目结构

```
src/heagent/
├── __init__.py          # 公共 API: Agent, tool, Settings, Providers
├── __main__.py          # python -m heagent 入口
├── cli.py               # Click CLI（provider 自动检测 + 密钥池装配）
├── config.py            # pydantic-settings 配置
├── types.py             # 共享类型
├── exceptions.py        # 异常层级
├── providers/           # Provider 抽象层
│   ├── base.py          #   BaseProvider Protocol
│   ├── openai.py        #   OpenAI / 兼容接口
│   ├── anthropic.py     #   Anthropic Claude
│   ├── chain.py         #   ProviderChain provider 间兜底
│   ├── key_rotation.py  #   KeyRotatingProvider 同 provider 多密钥轮换
│   └── retry.py         #   错误分类 + 指数退避
├── tools/               # 工具系统
│   ├── registry.py      #   ToolRegistry 单例
│   ├── decorator.py     #   @tool 装饰器
│   ├── safety.py        #   安全护栏（shell 命令拦截）
│   ├── path_safety.py   #   工作区路径校验
│   └── builtins/        #   内置工具: shell, file, search, memory, skills, cron, subagent
├── memory/              # 自学习记忆
│   ├── skills.py        #   技能存储（HermesAgent 标准目录结构）
│   ├── facts.py         #   事实记忆（去重）
│   ├── profile.py       #   用户画像
│   └── soul.py          #   人格系统（全局 + 项目两级 SOUL.md）
├── context/             # 上下文管理
│   ├── session.py       #   会话持久化
│   ├── compressor.py    #   LLM 摘要压缩
│   ├── loader.py        #   项目上下文文件扫描
│   └── tokens.py        #   token 估算（CJK 感知）
├── cron/                # 定时任务
│   ├── jobs.py          #   CronJob 模型 + JobStore
│   └── scheduler.py     #   asyncio 后台调度器
└── agent/               # Agent 核心
    ├── loop.py          #   AgentLoop (LLM ↔ tool 循环)
    ├── middleware.py    #   中间件管道
    └── sub.py           #   子 Agent + 并行执行
```

---

## 配置参考

所有配置通过环境变量 / `.env` 加载（pydantic-settings）：

**API 密钥**

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `DEEPSEEK_API_KEY` | — | DeepSeek 密钥（优先检测） |
| `OPENAI_API_KEY` | — | OpenAI 密钥 |
| `ANTHROPIC_API_KEY` | — | Anthropic 密钥 |
| `OPENAI_API_KEYS` | — | OpenAI 多密钥池（逗号分隔） |
| `ANTHROPIC_API_KEYS` | — | Anthropic 多密钥池（逗号分隔） |

**端点 / 兼容服务**

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `DEEPSEEK_BASE_URL` | — | DeepSeek 端点（默认官方） |
| `OPENAI_BASE_URL` | — | OpenAI 兼容端点（智谱AI 等） |
| `ANTHROPIC_BASE_URL` | — | Anthropic 兼容端点 |
| `ANTHROPIC_PROMPT_CACHING` | `true` | system prompt 缓存断点（代理不支持时关闭） |

**运行参数**

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `DEFAULT_MODEL` | `gpt-4o` | 默认模型名 |
| `MAX_ITERATIONS` | `50` | Agent 最大循环次数 |
| `COMPRESSION_THRESHOLD` | `0.8` | 上下文压缩触发阈值 |
| `MAX_CONTEXT_TOKENS` | `128000` | 模型上下文窗口（压缩判断用） |
| `SHELL_TIMEOUT` | `120` | Shell 命令超时（秒） |

**重试策略**

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `RETRY_MAX_ATTEMPTS` | `3` | 瞬态错误最大重试次数 |
| `RETRY_BASE_DELAY` | `1.0` | 重试基础延迟（秒） |
| `RETRY_MAX_DELAY` | `30.0` | 重试最大延迟（秒） |

**技能 / 记忆 / 上下文**

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `SKILL_MATCH_THRESHOLD` | `0.3` | 技能自动匹配阈值 |
| `SKILL_MAX_AUTO_INVOKE` | `3` | 每轮最多自动注入技能数 |
| `SKILL_CURATOR_STALE_DAYS` | `30` | 技能过期天数 |
| `CONTEXT_FILES_ENABLED` | `true` | 是否加载项目上下文文件 |
| `MEMORY_NUDGE_ENABLED` | `true` | 是否注入记忆保存提醒 |

**Cron 调度**

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `CRON_ENABLED` | `true` | 是否启用 cron 调度 |
| `CRON_TICK_SECONDS` | `60` | 调度器检查间隔（秒） |

---

## 开发

```bash
pytest                    # 运行全部 336 个测试（pytest-asyncio auto 模式）
pytest tests/test_cli.py  # 仅 CLI 测试
ruff check src tests      # Lint
ruff format src tests     # 格式化
mypy src                  # 类型检查（strict 模式）
```

## 依赖

- Python >= 3.11
- pydantic >= 2.13 · pydantic-settings >= 2.0
- httpx >= 0.28 · openai >= 2.37 · anthropic >= 0.104 · click >= 8.0

---

## 项目状态与已知限制

全部 10 个 epic 已完成（24 个 FR 已实现），详见 [`docs/sprint-status.yaml`](docs/sprint-status.yaml)。已知限制：

- **Cron 表达式** V1 解析器不支持范围表达式（如 `1-5`，`scheduler.py` 中显式跳过）
- **子 Agent 并行** 共享同一 `SkillStore`，组装系统提示词时 `record_usage` 存在写竞态
- **密钥轮换** 仅在 `cli.py` 自动装配；库代码直接构造 `AgentLoop` 时需自行包装 `KeyRotatingProvider`
- **流式 tool_calls** 多数 Provider 在 stream 模式不返回 tool_calls，框架回退到非流式补取该轮

## 设计文档

- [架构设计](docs/architecture-HeAgent-2026-05-23/)
- [产品需求文档](docs/prd-HeAgent-2026-05-23)
- [冲刺状态](docs/sprint-status.yaml)

---

## 许可

本项目为学习项目，用于理解和实践自主 Agent 的核心架构设计。
