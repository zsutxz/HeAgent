# HeAgent

自学习 AI Agent 核心框架。受 NousResearch Hermes Agent 启发，提取自主 Agent 的核心设计模式——学习循环、多模型适配、工具编排、记忆系统——用清晰、模块化的代码重新实现。

## 特性

- **多模型支持** — OpenAI、Anthropic、DeepSeek、智谱AI 等 OpenAI/Anthropic 兼容接口
- **Provider 兜底链** — 自动故障转移，多 key 轮换
- **声明式工具注册** — `@tool` 装饰器零样板注册，自动生成 JSON Schema
- **并行工具执行** — `asyncio.gather` 并发调用独立工具
- **安全护栏** — 危险命令拦截，黑名单/白名单模式
- **自学习记忆** — 技能提取、事实记忆（去重）、用户画像
- **上下文压缩** — 超阈值自动摘要，保留近期对话
- **子 Agent 并行** — 隔离上下文的子任务委派与并发执行
- **CLI + Python API** — 命令行和编程两种使用方式

## 安装

```bash
cd HeAgent
pip install -e ".[dev]"
```

## 配置

在项目根目录创建 `.env` 文件：

```bash
# OpenAI 或兼容接口（DeepSeek、智谱AI 等）
OPENAI_API_KEY=sk-...
OPENAI_BASE_URL=https://api.deepseek.com/v1   # 可选，默认 OpenAI 官方
DEFAULT_MODEL=deepseek-chat                     # 可选，默认 gpt-4o

# Anthropic 或兼容接口（智谱AI Anthropic 兼容）
# ANTHROPIC_API_KEY=...
# ANTHROPIC_BASE_URL=https://open.bigmodel.cn/api/anthropic

# 多 key 轮换（逗号分隔）
# OPENAI_API_KEYS=sk-aaa,sk-bbb,sk-ccc
```

全部配置项：

| 环境变量 | 默认值 | 说明 |
|---------|--------|------|
| `OPENAI_API_KEY` | — | OpenAI API 密钥 |
| `ANTHROPIC_API_KEY` | — | Anthropic API 密钥 |
| `OPENAI_BASE_URL` | — | 自定义 OpenAI 兼容端点 |
| `ANTHROPIC_BASE_URL` | — | 自定义 Anthropic 端点 |
| `DEFAULT_MODEL` | `gpt-4o` | 默认模型名 |
| `MAX_ITERATIONS` | `50` | Agent 最大循环次数 |
| `COMPRESSION_THRESHOLD` | `0.8` | 上下文压缩触发阈值 |
| `SHELL_TIMEOUT` | `120` | Shell 命令超时（秒） |
| `RETRY_MAX_ATTEMPTS` | `3` | 瞬态错误最大重试次数 |

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

## 项目结构

```
src/heagent/
├── __init__.py          # 公共 API: Agent, tool, Settings, Providers
├── __main__.py          # python -m heagent 入口
├── cli.py               # Click CLI
├── config.py            # pydantic-settings 配置
├── types.py             # 共享类型
├── exceptions.py        # 异常层级
├── providers/           # Provider 抽象层
│   ├── base.py          #   BaseProvider Protocol
│   ├── openai.py        #   OpenAI / 兼容接口
│   ├── anthropic.py     #   Anthropic Claude
│   ├── chain.py         #   ProviderChain 兜底链
│   └── retry.py         #   错误分类 + 指数退避
├── tools/               # 工具系统
│   ├── registry.py      #   ToolRegistry 单例
│   ├── decorator.py     #   @tool 装饰器
│   ├── safety.py        #   安全护栏
│   └── builtins/        #   内置工具: shell, file, search
├── memory/              # 自学习记忆
│   ├── skills.py        #   技能提取
│   ├── facts.py         #   事实记忆（去重）
│   └── profile.py       #   用户画像
├── context/             # 上下文管理
│   ├── session.py       #   会话持久化
│   └── compressor.py    #   LLM 摘要压缩
└── agent/               # Agent 核心
    ├── loop.py          #   AgentLoop (LLM ↔ tool 循环)
    ├── middleware.py     #   中间件管道
    └── sub.py           #   子 Agent + 并行执行
```

## 测试

```bash
pytest                    # 运行全部 203 个测试
pytest tests/test_cli.py  # 仅 CLI 测试
```

## 依赖

- Python >= 3.11
- pydantic >= 2.13
- openai >= 2.37
- anthropic >= 0.104
- click >= 8.0

## 许可

本项目为学习项目，用于理解自主 Agent 的核心架构设计。
