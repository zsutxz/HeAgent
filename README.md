# HeAgent

自学习 AI Agent 核心框架。受 NousResearch Hermes Agent 启发，提取自主 Agent 的核心设计模式——学习循环、多模型适配、工具编排、记忆系统——用清晰、模块化的代码重新实现。

## ⚠️ 安全声明（运行前务必阅读）

HeAgent 会**执行 shell 命令、读写文件、调用外部 API**。当前的 `SafetyGuard`（黑名单/白名单命令过滤）**不是真正的安全边界**——它无法可靠抵御 prompt injection 与工具滥用：命令黑名单可被轻易绕过、工具返回内容会无围栏地进入 LLM 上下文。因此：

- **不可在不可信内容或不可信 LLM 输出下裸跑** HeAgent。若需处理外部文件、网页、用户上传或第三方模型响应，**必须配套 OS 级隔离**（容器 / firejail / 沙箱虚拟机），并收紧文件系统与网络权限。
- 不要在宿主机家目录、生产服务器或多租户环境中以默认配置直接运行未沙箱化的实例。

此声明是诚实的使用边界，而非 `SafetyGuard` 已被加固的承诺。

## 特性

- **多模型支持** — OpenAI、Anthropic、DeepSeek、智谱AI 等 OpenAI/Anthropic 兼容接口
- **Provider 兜底链** — 自动故障转移，多 key 轮换
- **声明式工具注册** — `@tool` 装饰器零样板注册，自动生成 JSON Schema
- **并行工具执行** — `asyncio.gather` 并发调用独立工具
- **安全护栏** — 危险命令拦截，黑名单/白名单模式
- **自学习记忆** — 技能提取与自动匹配、事实记忆（去重）、用户画像
- **SOUL.md 人格系统** — 全局 + 项目两级人格加载，注入系统提示词最顶层
- **Cron 定时调度** — asyncio 后台调度器，支持一次性与循环任务，交互模式自动启用
- **上下文压缩** — 超阈值自动摘要，保留近期对话
- **子 Agent 并行** — 隔离上下文的子任务委派与并发执行
- **CLI + Python API** — 命令行和编程两种使用方式

## 安装

```bash
cd HeAgent
pip install -e ".[dev]"
```

## 配置

在项目根目录创建 `.env` 文件，至少配置一家 Provider 的密钥：

```bash
# DeepSeek（CLI 优先检测，走 OpenAI 兼容接口）
DEEPSEEK_API_KEY=sk-...
DEFAULT_MODEL=deepseek-chat                     # 可选，默认 gpt-4o

# OpenAI 或其它兼容接口（智谱AI 等）
# OPENAI_API_KEY=sk-...
# OPENAI_BASE_URL=https://open.bigmodel.cn/api/paas/v4   # 可选，默认 OpenAI 官方

# Anthropic 或兼容接口（智谱AI Anthropic 兼容）
# ANTHROPIC_API_KEY=...
# ANTHROPIC_BASE_URL=https://open.bigmodel.cn/api/anthropic

# 多 key 轮换（逗号分隔）—— 同一 Provider 配多个 key，限流/认证错误时自动切换
# OPENAI_API_KEYS=sk-aaa,sk-bbb,sk-ccc
```

全部配置项：

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `DEEPSEEK_API_KEY` | — | DeepSeek 密钥（CLI 优先检测） |
| `OPENAI_API_KEY` | — | OpenAI / 兼容接口密钥 |
| `ANTHROPIC_API_KEY` | — | Anthropic 密钥 |
| `OPENAI_API_KEYS` | — | OpenAI 多 key 池，逗号分隔 |
| `ANTHROPIC_API_KEYS` | — | Anthropic 多 key 池，逗号分隔 |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | DeepSeek 端点 |
| `OPENAI_BASE_URL` | OpenAI 官方 | 自定义 OpenAI 兼容端点 |
| `ANTHROPIC_BASE_URL` | Anthropic 官方 | 自定义 Anthropic 端点 |
| `DEFAULT_MODEL` | `gpt-4o` | 默认模型名 |
| `MAX_ITERATIONS` | `50` | Agent 最大循环次数 |
| `COMPRESSION_THRESHOLD` | `0.8` | 上下文压缩触发阈值 |
| `SHELL_TIMEOUT` | `120` | Shell 命令超时（秒） |
| `RETRY_MAX_ATTEMPTS` | `3` | 瞬态错误最大重试次数 |
| `MCP_ENABLED` | `true` | 是否启用 MCP server 连接（门控，置 `false` 完全跳过） |
| `MCP_CONFIG_PATH` | `.mcp.json` | 声明式 MCP server 配置路径（项目根） |

## 使用

### CLI

```bash
# 单次执行
python -m heagent "用Python写一个快速排序"

# 交互模式
python -m heagent

# 指定模型和系统提示
python -m heagent --model deepseek-chat --system "你是Python专家" "写一个二分查找"
```

### Python API

```python
import asyncio
from heagent import Agent, OpenAIProvider

async def main():
    provider = OpenAIProvider(api_key="sk-...", model="deepseek-chat")
    agent = Agent(provider)
    result = await agent.run("你好")
    print(result)

asyncio.run(main())
```

### 自定义工具

```python
from heagent import tool

@tool
async def search_docs(query: str) -> str:
    """搜索文档，返回匹配结果。"""
    return f"Found: {query}"
```

### 多 Provider 兜底

```python
from heagent import Agent, ProviderChain, OpenAIProvider, AnthropicProvider

chain = ProviderChain([
    OpenAIProvider(api_key="sk-...", model="gpt-4o"),
    AnthropicProvider(api_key="sk-ant-...", model="claude-sonnet-4-6"),
])
agent = Agent(chain)
```

### 子 Agent 并行执行

```python
from heagent.agent.sub import SubAgent, run_parallel

agents = [SubAgent(provider) for _ in range(3)]
results = await run_parallel(agents, ["任务1", "任务2", "任务3"])
for r in results:
    print(r.task, r.success, r.output)
```

### MCP 工具接入

HeAgent 可连接任意 [MCP server](https://modelcontextprotocol.io)，把其工具自动发现并注册为与内置工具等价的工具（命名空间化为 `<server>__<tool>`，如 `github__list_issues`）。支持 **stdio**（本地子进程）与 **Streamable HTTP**（远程）两种 transport。

**启用方式：**

1. 在项目根放一份 `.mcp.json`（可从 `.mcp.json.example` 复制改）。无此文件或 `mcpServers` 为空时，以纯内置工具模式运行（不报错、不阻断）。
2. 鉴权凭据走**环境变量**，配置中用 `${VAR}` 引用——加载时一次性插值，密钥绝不落明文；引用未设变量会 fail-fast。例如 `${GITHUB_TOKEN}`。
3. 默认 `MCP_ENABLED=true`；想完全关闭连接可设 `MCP_ENABLED=false`（即使存在 `.mcp.json` 也跳过）。

```bash
# 从示例复制（含 GitHub 远程 + stdio filesystem 两个样例）
cp .mcp.json.example .mcp.json
export GITHUB_TOKEN=ghp_xxx        # 走环境变量，不要写进 .mcp.json
python -m heagent "这个 repo 有哪些 open issue"
```

> ⚠️ **沙箱警示：** 外部 MCP server 是**不可信代码**（stdio 会拉起任意子进程、HTTP 会连任意端点），其工具返回内容无隔离地进入 LLM 上下文。连接 MCP server 时同样必须在 OS 级沙箱（容器 / firejail）内运行，并收紧子进程与出站网络权限。V1 的 `SafetyGuard` **不**覆盖 MCP 工具——详见上方「安全声明」与 `CLAUDE.md`。

## 项目结构

```
src/heagent/
├── __init__.py          # 公共 API: Agent (=AgentLoop 别名), tool, Settings, Providers
├── __main__.py          # python -m heagent 入口
├── cli.py               # Click CLI
├── config.py            # pydantic-settings 配置
├── types.py             # 共享类型
├── exceptions.py        # 异常层级
├── providers/           # Provider 抽象层
│   ├── base.py          #   BaseProvider Protocol
│   ├── openai.py        #   OpenAI / 兼容接口
│   ├── anthropic.py     #   Anthropic Claude
│   ├── chain.py         #   ProviderChain 跨 Provider 兜底
│   ├── key_rotation.py  #   KeyRotatingProvider 同 Provider 多 key 轮换
│   └── retry.py         #   错误分类 + 指数退避
├── tools/               # 工具系统
│   ├── registry.py      #   ToolRegistry 单例
│   ├── decorator.py     #   @tool 装饰器
│   ├── safety.py        #   命令安全护栏
│   ├── path_safety.py   #   工作区路径围栏
│   ├── mcp/             #   MCP 适配层: config / mapping / manager (外部 MCP server)
│   └── builtins/        #   内置工具: shell, file, search, cron, memory, skills, subagent
├── memory/              # 自学习记忆
│   ├── skills.py        #   技能存储（HermesAgent 标准目录结构）
│   ├── facts.py         #   事实记忆（去重）
│   ├── profile.py       #   用户画像
│   └── soul.py          #   人格（SOUL.md，全局+项目两级）
├── context/             # 上下文管理
│   ├── session.py       #   会话持久化
│   ├── compressor.py    #   LLM 摘要压缩
│   ├── loader.py        #   上下文文件扫描
│   └── tokens.py        #   token 估算
├── cron/                # 定时任务
│   ├── jobs.py          #   JobStore 持久化
│   └── scheduler.py     #   asyncio 后台调度
└── agent/               # Agent 核心
    ├── loop.py          #   AgentLoop (LLM ↔ tool 循环)
    ├── middleware.py     #   中间件管道（重试等）
    └── sub.py           #   子 Agent + 并行执行
```

## 测试

```bash
pytest                    # 运行全部测试
pytest tests/test_cli.py  # 仅 CLI 测试
```

## 依赖

- Python >= 3.11
- pydantic >= 2.13
- pydantic-settings >= 2.0
- httpx >= 0.28
- openai >= 2.37
- anthropic >= 0.104
- click >= 8.0
- mcp >= 1.28, < 2

## 许可

本项目为学习项目，用于理解自主 Agent 的核心架构设计。
