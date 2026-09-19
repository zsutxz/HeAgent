# HeAgent

> **实验性 Agent 框架。** HeAgent 用可读的 Python 代码拆解自主 Agent 的关键机制，适合学习、原型验证和按需扩展；它不是产品，也不是安全边界。

HeAgent 是一个单进程、异步的 Python Agent 运行时，同时提供 CLI 和可嵌入的库接口。它把多 Provider 调用、工具执行、策略裁决、会话与记忆、MCP、子 Agent 委派和声明式 `/goal` 工作流组合在一起。

如果目标是稳定完成日常编码任务，请优先使用 [Codex](https://github.com/openai/codex) 等产品级代理；如果目标是理解、替换或组合 Agent 的内部机制，HeAgent 提供了一套可直接阅读和改造的参考实现。详细比较见 [HeAgent 与 Codex 的对照](docs/codex-comparison.md)。

## 适用范围

| HeAgent 是 | HeAgent 不是 |
| --- | --- |
| 单进程异步 Python 库、CLI 和可选 Textual 终端 UI | HTTP 服务、多租户产品或稳定 SDK |
| 可阅读、可替换的 Agent 参考实现 | 无人值守地操作真实环境的安全方案 |
| 多 Provider、工具治理、记忆和工作流的实验场 | 生产就绪承诺、SLA 或大规模模型评测结果 |

## 快速开始

要求 Python 3.11+。

### 1. 安装

```bash
pip install -e ".[dev]"
```

只使用 CLI 或库时可安装发布包：

```bash
pip install heagent
```

### 2. 配置 Provider

复制配置模板后，至少填写一个 Provider 凭据。配置优先级是：系统环境变量 > 项目 `.env` > 用户 `~/.heagent/.env` > 默认值。

```bash
cp .env.example .env
```

```powershell
Copy-Item .env.example .env
```

```dotenv
DEEPSEEK_API_KEY=sk-...
# OPENAI_API_KEY=sk-...
# ANTHROPIC_API_KEY=...
```

本地 Ollama 不需要 API Key，但必须显式启用并指定模型：

```dotenv
OLLAMA_ENABLED=true
OLLAMA_MODEL=qwen3:8b
# OLLAMA_BASE_URL=http://127.0.0.1:11434/v1
```

本地模型的上下文窗口通常远小于默认 `MAX_CONTEXT_TOKENS=512000`；请按实际 `num_ctx` 下调该值。

### 3. 运行

```bash
# 单次执行
heagent "用 Python 写一个快速排序"

# 交互模式
heagent

# 显式子命令
heagent run --model deepseek-flash --system "你是 Python 专家" "写一个二分查找"

# 初始化用户级配置；--project 额外创建 .heagent/CONTEXT.md 模板
heagent init --project
```

## 核心能力

- **Provider**：DeepSeek、Kimi、GLM、OpenAI Chat Completions、OpenAI Responses、Anthropic 和显式启用的 Ollama；支持重试、密钥轮换、故障转移、手动切换与声明式路由池。
- **工具与治理**：`@tool` 注册、内置 shell／文件／搜索／记忆／技能／Cron／子 Agent／Web／Git 工具、MCP 桥接，以及 `PolicyEngine → ToolExecutor → SafetyGuard → handler` 执行链。
- **上下文与记忆**：会话持久化、分层上下文文件、token 计量、压缩或窗口重置；技能、事实记忆、用户画像和 `SOUL.md` 人格均可文件化管理。
- **工作流与审计**：Markdown 声明的 `/goal`、checkpoint、独立 SubAgent 步骤、事件总线、JSONL 输出、rollout 落盘和回放。

## 常用命令

| 命令 | 说明 |
| --- | --- |
| `heagent [PROMPT]` | 直接执行 prompt；无 prompt 时进入交互模式 |
| `heagent run [PROMPT]` | 显式运行入口 |
| `heagent init [--project]` | 初始化用户配置；可选创建项目上下文模板 |
| `heagent gui` | 启动终端 UI，需要 `pip install -e ".[gui]"` |
| `heagent replay FILE` | 回放 JSONL rollout 或事件文件 |

常用 `run` 选项：

| 选项 | 说明 |
| --- | --- |
| `--model NAME` | 覆盖当前 Provider 的模型；已启用路由池时请用 `/route` 选档 |
| `--system TEXT` | 设置本次运行的 system prompt |
| `--max-iterations N` | 主 Agent 最大迭代数 |
| `--continue` / `--resume ID` | 继续最近或指定会话 |
| `--plan` | 只读规划模式，禁止 shell 和写入类工具 |
| `--sandbox auto\|passthrough\|firejail\|winjob` | 选择 shell 执行后端 |
| `--json` | 单次执行时将 JSONL 事件流输出到 stdout |

交互模式支持 `/model`、`/route`、`/goal`、`/clear` 和 `/help`。自定义命令放在 `.heagent/commands/*.md`，自定义角色放在 `.heagent/agents/*.md`。

## Goal 工作流

`/goal` 的权威契约是 [`.heagent/skills/he-workflow/workflow.md`](.heagent/skills/he-workflow/workflow.md)：Markdown 定义步骤、产物和门禁，Python 负责解析、checkpoint、状态迁移和 SubAgent 调度。

```text
/goal <目标描述>      创建目标并启动首个步骤
/goal next            推进一步或一条 Story
/goal run             连续推进，直到 checkpoint 或阻塞
/goal status          查看状态和产物
/goal pause           保存并暂停
/goal resume [回复]   提交回复并继续
/goal auto [cron]     注册定时推进；off 注销
/goal audit           查看运行与事件审计摘要
```

运行时目标产物在 `_he-output/goals/<goal-id>/`；历史规划材料位于 [`_bmad-output/`](_bmad-output/README.md)，不作为当前运行时配置。

## 配置与运行时数据

完整配置、默认值和路由池示例见 [`.env.example`](.env.example)。以下是常见开关：

```dotenv
# 工具权限与 shell 后端；都只是纵深防御，不是 OS 级安全边界
PLAN_MODE=false
APPROVAL_TOOLS=shell,file_write
SANDBOX_MODE=workspace-write      # read-only | workspace-write | danger-full-access
SANDBOX_BACKEND=auto              # auto | passthrough | firejail | winjob
SANDBOX_NETWORK=false

# 上下文与路由
CONTEXT_STRATEGY=compressor       # compressor | reset
TOKENIZER=auto                    # auto | estimate | tiktoken
MAX_CONTEXT_TOKENS=512000
# ROUTING_POOLS={"deepseek":{"tiers":{"fast":"deepseek-flash","pro":"deepseek-v4-pro"}}}

# 可观测性与扩展
EVENTS_ROLLOUT_ENABLED=false
MCP_ENABLED=true
HOOKS_ENABLED=false
```

项目运行时状态写入 `.heagent/`，不应提交密钥或个人状态：

| 位置 | 内容 |
| --- | --- |
| `.heagent/skills/` | 本地技能包 |
| `.heagent/memory/`、`.heagent/user/` | 事实记忆与用户画像 |
| `.heagent/sessions/` | 会话历史 |
| `.heagent/runs/`、`.heagent/ledger/` | 运行快照、rollout 与工具幂等记录 |
| `.heagent/cron/` | Cron 状态 |
| `.heagent/CONTEXT.md` | 项目上下文，优先级高于 `AGENTS.md`、`CLAUDE.md` |

`SOUL.md` 可放在项目 `.heagent/SOUL.md` 或用户 `~/.heagent/SOUL.md`，项目级优先。会话、日志、编辑快照、run、ledger 和沙箱目录有保留期清理策略；技能、记忆与 Cron 不会自动删除。

## 安全说明

HeAgent 能执行 shell、读写文件、调用外部 API，并把工具返回内容再次送入模型上下文。请始终假定不可信网页、文件、MCP server 和工具输出可能含 prompt injection。

- `SafetyGuard`、路径校验、`PolicyEngine` 和内置 sandbox **不是完整安全边界**。
- 处理不可信任务时，请在容器、VM 或其他 OS 级隔离中运行，并限制文件系统和出站网络。
- `firejail` 仅适用于 Linux；不可用时回退到 `passthrough`。Windows `winjob` 仅做进程级约束，不隔离文件系统。
- Hooks 以当前用户权限执行本地命令，默认关闭；启用前必须确认仓库可信。

MCP 从 `.mcp.json` 加载，密钥应保存在环境变量中而非配置文件里。详细安全边界、工具链和已知缺口见 [架构参考](docs/frame.md) 与 [部署说明](deploy/README.md)。

## Python API

```python
import asyncio

from heagent import Agent, OpenAIProvider


async def main() -> None:
    agent = Agent(OpenAIProvider(api_key="sk-...", model="gpt-4o"))
    print(await agent.run("你好"))


asyncio.run(main())
```

## 开发

```bash
# 默认跳过 integration 与 benchmark
pytest

# 外部依赖集成测试
pytest -m integration

# 静态检查
ruff check src tests
ruff format --check src tests
mypy src
```

模块依赖、测试与安全约束见 [AGENTS.md](AGENTS.md)。测试、代码、配置与历史文档的权威关系见 [文档索引](docs/README.md)。

## 深入阅读

| 目标 | 文档 |
| --- | --- |
| 当前架构、数据流、工具与已知缺口 | [架构参考](docs/frame.md) |
| 项目定位、设计目标和非目标 | [设计说明](docs/design.md) |
| `/goal` 工作流、产物与维护规则 | [敏捷工作流](docs/workflow_intro.md) |
| HeAgent 与 Codex 的设计取向 | [对照说明](docs/codex-comparison.md) |
| 部署、Docker 与 Windows 可执行文件 | [部署说明](deploy/README.md) |
| 历史规划与验收证据 | [_bmad-output/README.md](_bmad-output/README.md) |

## 许可证

本项目采用 [MIT License](LICENSE)。使用时还应遵守依赖项及外部 Provider 的许可与服务条款。
