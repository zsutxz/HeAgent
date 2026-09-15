# HeAgent

HeAgent 是面向学习、实验和扩展的异步 Python AI Agent 框架。它提供 Provider 适配、工具调用、上下文与记忆管理、子 Agent 委派、MCP 集成，以及声明式的 Goal 工作流。

HeAgent 是 CLI 工具和 Python 库，不是现成的 HTTP 服务。仓库适合研究 Agent 架构、构建原型和扩展工具链；安全护栏属于 defense-in-depth，不能替代容器、虚拟机或其他 OS 级隔离。

## 快速开始

### 1. 安装

要求 Python 3.11+。

```bash
pip install -e ".[dev]"
```

只作为库或 CLI 使用时，也可安装发布包：

```bash
pip install heagent
```

### 2. 配置 Provider

从示例创建本地配置。环境变量优先级为：显式环境变量 > 项目 `.env` > 全局配置 > 默认值。

```bash
cp .env.example .env
```

```powershell
Copy-Item .env.example .env
```

至少配置一个云端 Provider：

```dotenv
DEEPSEEK_API_KEY=sk-...
# OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=...
# KIMI_API_KEY=...
# GLM_API_KEY=...
```

本地 Ollama 需要显式启用，不需要 API Key：

```dotenv
OLLAMA_ENABLED=true
OLLAMA_MODEL=qwen3:8b
# OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
```

本地模型的上下文窗口通常远小于默认的 `MAX_CONTEXT_TOKENS=512000`。请按模型的实际 `num_ctx` 调低该值；否则压缩或窗口重置可能来不及触发，先收到 Provider 的上下文超限错误。

### 3. 运行

```bash
# 单次执行
heagent "用 Python 写一个快速排序"

# 交互模式
heagent

# 显式子命令形式
heagent run --model deepseek-chat --system "你是 Python 专家" "写一个二分查找"
```

首次使用可初始化用户级默认配置：

```bash
heagent init
```

## 能力概览

- Provider：DeepSeek、OpenAI、Anthropic、Kimi、GLM、OpenAI Responses API 和显式启用的 Ollama；支持重试、密钥轮换、回退和运行时路由。
- 工具：声明式 `@tool` 注册，内置 shell、文件、搜索、记忆、技能、Cron、子 Agent、MCP、Web 抓取和 Git 只读工具。
- 运行时：`PolicyEngine`、`ToolExecutor`、`SafetyGuard`、`RunStore`、`ExecutionLedger` 和事件审计共同负责工具执行与恢复。
- 上下文：会话、事实记忆、用户画像、人格、技能和压缩/窗口重置策略。
- 工作流：`/goal` 从 Markdown 声明读取步骤、checkpoint 和验收门禁，以独立 SubAgent 会话推进 Goal、Epic 和 Story。

## CLI 与交互

根命令支持直接传入 prompt，也支持以下子命令：

| 命令 | 用途 |
| --- | --- |
| `heagent run [PROMPT]` | 单次执行；缺少 prompt 时进入交互模式 |
| `heagent init` | 创建 `~/.heagent` 全局配置目录 |
| `heagent gui` | 启动终端 UI，需安装 `.[gui]` |
| `heagent replay FILE` | 回放 JSONL 事件文件（人读格式；`--json` 原样回吐） |

`run` 和默认入口共享以下常用选项：

| 选项 | 用途 |
| --- | --- |
| `--model NAME` | 覆盖当前 Provider 的默认模型 |
| `--system TEXT` | 覆盖 system prompt |
| `--max-iterations N` | 设置主 Agent 的最大迭代数 |
| `--continue` / `--resume ID` | 在交互模式继续最近或指定会话 |
| `--plan` | 启用只读 Plan Mode，禁止 shell 和写入类工具 |
| `--sandbox passthrough|firejail` | 选择 shell 执行后端 |
| `--sandbox-session-workspace` / `--no-...` | 每个 run 是否使用独立 shell 工作目录（默认跟随 `SANDBOX_SESSION_WORKSPACE`；显式开关可双向覆盖 env） |
| `--sandbox-session-keep` / `--no-...` | run 结束后是否保留该目录（默认跟随 `SANDBOX_SESSION_KEEP`） |
| `--json` | 单次模式：**stdout 只输出 JSONL 事件流**（人读信息走 stderr），便于管道/CI 消费 |

**机器接口（JSONL 事件流）**：`heagent run "…" --json` 输出一行一事件（字段：`schema_version`/`seq`/`ts`/`run_id`/`iteration`/`kind`/`tool`/`target`/`details`），以 `run_started` 开头、`run_completed`/`run_failed` 收尾，最终答案以 `assistant_message` 交回。事件与工具原始输出**同等不可信**（含 MCP/远端内容），不得因结构化而提升信任。设 `EVENTS_ROLLOUT_ENABLED=true` 会把每个 run 的事件落盘到 `.heagent/runs/<run_id>/rollout.jsonl`（默认关闭），可 `heagent replay` 回放。

交互模式内可使用：

| 命令 | 用途 |
| --- | --- |
| `/model` | 查看或切换模型 |
| `/route [NAME|auto]` | 查看智能路由状态或强制路由 |
| `/mcp-prompt` | 调度 MCP Prompt |
| `/goal` | 创建、推进、暂停、恢复或审计声明式 Goal 工作流 |
| `/deferred` | 查看跨周期和 Goal 内的 deferred 台账 |
| `/clear` / `/help` | 清空会话上下文 / 查看可用命令 |

自定义命令放在 `.heagent/commands/*.md` 或 `~/.heagent/commands/*.md`；自定义角色放在 `.heagent/agents/*.md` 或 `~/.heagent/agents/*.md`。两者都使用 Markdown frontmatter 声明名称和描述。

## Goal 工作流

`/goal` 的可执行契约在 [`.heagent/workflows/workflow.md`](.heagent/workflows/workflow.md)，Python 代码只负责解析、checkpoint、状态迁移和 SubAgent 调度。

```text
/goal <目标描述>      创建 Goal 并启动首个步骤
/goal next            推进一个声明步骤或一条 Story
/goal run             连续推进，遇到 checkpoint 或阻塞时停止
/goal status          查看状态和产物
/goal pause            保存并暂停
/goal resume [回复]   提交回复并继续等待中的步骤
/goal auto [cron]     注册定时推进；off 注销
/goal audit           查看运行和事件审计摘要
```

运行时产物写入 `_he-output/goals/<goal-id>/`；其中 `GOAL.md` 保存目标身份，`checkpoints/` 保存可恢复状态。历史 Epic、Story、spec 和 retrospective 位于 [`_bmad-output/`](_bmad-output/README.md)，不作为当前运行时配置。

## 安全边界

HeAgent 可以执行 shell、读写文件、调用外部 API，并将工具返回内容放回模型上下文。因此：

- `SafetyGuard`、路径校验和 `PolicyEngine` 都不是完整安全边界。
- 不可信网页、文件、MCP server 和 MCP 返回内容必须按不可信输入处理。
- 处理不可信任务时，应在容器、VM 或其他 OS 级隔离中运行，并限制文件系统和出站网络权限。
- `firejail` 仅在 Linux 可用，且同样只是附加防护；不可用时会退回 `passthrough`，即没有 OS 级隔离。

启用 Firejail：

```bash
heagent --sandbox firejail "检查当前目录"
```

完整的工具链、安全立场和已知限制见 [架构参考](docs/frame.md) 与 [部署说明](deploy/README.md)。

## MCP 与配置

MCP 配置从 `.mcp.json` 加载。复制示例后，把密钥放在环境变量中，而不是提交到配置文件。

```bash
cp .mcp.json.example .mcp.json
MCP_ENABLED=false heagent
```

PowerShell：

```powershell
$env:MCP_ENABLED = "false"
heagent
```

常用可选配置：

```dotenv
# 只读规划与交互审批
PLAN_MODE=false
APPROVAL_TOOLS=shell,file_write

# 上下文与输出限制
CONTEXT_STRATEGY=compressor
MAX_CONTEXT_TOKENS=512000
MAX_OUTPUT_TOKENS=4096

# MCP、Hooks 和成本统计
MCP_ENABLED=true
HOOKS_ENABLED=false
MODEL_PRICING={"deepseek-v4-pro":{"input":0.27,"output":1.1}}
```

完整字段、默认值和路由池示例见 [`.env.example`](.env.example)。Hooks 会以当前用户权限执行本地命令，默认关闭；启用前应确认当前仓库可信。

## 运行时数据

项目运行时状态默认写入 `.heagent/`，应加入备份策略但不要提交密钥或个人状态：

| 位置 | 内容 |
| --- | --- |
| `.heagent/skills/` | 本地技能包 |
| `.heagent/memory/`、`.heagent/user/` | 事实记忆与用户画像 |
| `.heagent/sessions/` | 会话历史 |
| `.heagent/runs/`、`.heagent/ledger/` | 运行快照与工具幂等记录 |
| `.heagent/cron/` | Cron 任务状态 |
| `.heagent/CONTEXT.md` | 项目上下文；优先级高于 `AGENTS.md` 和 `CLAUDE.md` |

`SOUL.md` 可置于项目 `.heagent/SOUL.md` 或用户目录 `~/.heagent/SOUL.md`；项目级文件优先。

## Python API

```python
import asyncio

from heagent import Agent, OpenAIProvider


async def main() -> None:
    agent = Agent(OpenAIProvider(api_key="sk-...", model="gpt-4o"))
    print(await agent.run("你好"))


asyncio.run(main())
```

更多组合方式和运行时注入边界见 [架构参考](docs/frame.md)。

## 开发

```bash
# 默认跳过 integration 与 benchmark
pytest

# 外部依赖集成测试
pytest -m integration

# 静态检查
ruff check src tests
mypy src
```

新增或修改功能时，请遵守 [AGENTS.md](AGENTS.md) 中的模块依赖、测试和安全约束。测试、文档和运行配置的权威关系见 [文档索引](docs/README.md)。

## 文档

| 目标 | 文档 |
| --- | --- |
| 当前架构、数据流、工具与已知缺口 | [docs/frame.md](docs/frame.md) |
| `/goal` 工作流、产物和维护规则 | [docs/workflow_intro.md](docs/workflow_intro.md) |
| 设计目标与非目标 | [docs/design.md](docs/design.md) |
| 迭代过程与历史背景 | [docs/iteration.md](docs/iteration.md) |
| 部署、Docker 和 Windows 可执行文件 | [deploy/README.md](deploy/README.md) |
| 规划归档 | [_bmad-output/README.md](_bmad-output/README.md) |

## 许可证

本项目采用 [MIT License](LICENSE)。使用时还应遵守依赖项及外部 Provider 的许可与服务条款。
