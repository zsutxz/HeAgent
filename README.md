# HeAgent

HeAgent 是一个面向学习和实验的自学习 AI Agent 框架。项目聚焦自主 Agent 的几个核心机制：Provider 适配、工具调用、记忆、上下文管理、子 Agent 委派，以及 MCP 工具接入。

## 项目状态

- 当前主要使用方式是 CLI 和 Python API，不是现成的 HTTP 服务。
- 代码库适合研究架构、做原型、扩展工具链，不应直接视为已加固的生产代理。
- 文档与代码以当前仓库实现为准；`_bmad-output/` 下的规划材料仅作历史参考。

## 安全边界

HeAgent 会执行 shell、读写文件、访问外部 API，并且会把工具返回内容直接放回模型上下文。

- `SafetyGuard` 只是命令级护栏，不是可靠的安全沙箱。
- 外部 MCP server 和不可信文件/网页内容都应视为不可信输入。
- 处理不可信内容时，必须配合容器、虚拟机或其他 OS 级隔离，并收紧文件系统和网络权限。

## 文档地图

- [文档索引](docs/README.md)
- [设计说明](docs/design.md)
- [架构参考](docs/frame.md)
- [部署说明](deploy/README.md)
- [仓库协作约定](CLAUDE.md)

建议阅读顺序：`README` -> `docs/design.md` -> `docs/frame.md`。

## 核心能力

- 多 Provider 接入：OpenAI、Anthropic、DeepSeek，以及兼容 OpenAI/Anthropic 协议的服务。
- 三层容错：重试、中间层 key 轮换、外层跨 Provider 回退。
- 声明式工具注册：`@tool` 自动生成 schema 并接入工具注册中心。
- 内置工具集：shell、文件读写、文件搜索、技能管理、记忆、Cron、子 Agent 委派。
- 运行时治理：`PolicyEngine`、`RunStore`、`ExecutionLedger`、事件总线。
- 记忆与人格：`SKILL.md`、`MEMORY.md`、`USER.md`、`SOUL.md`。
- 子 Agent 角色化：内置 `planner`、`coder`、`tester`、`supervisor`。
- MCP 集成：从 `.mcp.json` 发现并注册外部工具。

## 快速开始

### 1. 安装

```bash
pip install -e ".[dev]"
```

要求：

- Python 3.11+

### 2. 配置 `.env`

复制示例文件：

```bash
cp .env.example .env
```

Windows PowerShell:

```powershell
Copy-Item .env.example .env
```

至少配置一家 Provider：

```bash
DEEPSEEK_API_KEY=sk-...
# 或
OPENAI_API_KEY=sk-...
# 或
ANTHROPIC_API_KEY=...
```

CLI 默认按 `DeepSeek -> OpenAI -> Anthropic` 的顺序构建可用 Provider。

### 3. 运行

单次执行：

```bash
python -m heagent "用 Python 写一个快速排序"
```

交互模式：

```bash
python -m heagent
```

指定模型和 system prompt：

```bash
python -m heagent --model deepseek-chat --system "你是 Python 专家" "写一个二分查找"
```

常用 CLI 选项：

| 选项 | 说明 |
|------|------|
| `--model` | 模型名（默认取 `settings.default_model`） |
| `--system` | 自定义 system prompt |
| `--max-iterations` | Agent 循环最大迭代数（默认 50） |
| `--soul` | 自定义 `SOUL.md` 人格文件路径 |

安装脚本后也可以直接使用：

```bash
heagent "你好"
```

## Python API

```python
import asyncio

from heagent import Agent, OpenAIProvider


async def main() -> None:
    provider = OpenAIProvider(api_key="sk-...", model="gpt-4o")
    agent = Agent(provider)
    result = await agent.run("你好")
    print(result)


asyncio.run(main())
```

## MCP 快速接入

1. 复制 `.mcp.json.example` 为 `.mcp.json`。
2. 把鉴权信息放进环境变量，而不是写死在 `.mcp.json`。
3. 运行 HeAgent，MCP 工具会在启动时被发现并注册。

示例：

```bash
cp .mcp.json.example .mcp.json
export GITHUB_TOKEN=ghp_xxx
python -m heagent "这个仓库有哪些 open issue"
```

完全禁用 MCP：

```bash
MCP_ENABLED=false python -m heagent
```

PowerShell:

```powershell
$env:MCP_ENABLED="false"
python -m heagent
```

MCP server 与其返回内容同样不可信，安全要求与 shell / 文件工具一致。

## 运行时数据

默认会在项目目录下写入 `.heagent/`：

- `.heagent/skills/`：技能目录，入口文件为 `SKILL.md`
- `.heagent/memory/MEMORY.md`：事实记忆
- `.heagent/user/USER.md`：用户画像
- `.heagent/sessions/`：会话历史
- `.heagent/cron/jobs.json`：Cron 任务
- `.heagent/runs/`：运行快照
- `.heagent/ledger/`：工具执行幂等记录
- `~/.heagent/SOUL.md`：全局人格（用户默认）；`.heagent/SOUL.md`：项目级人格，存在时覆盖全局

上下文文件加载优先级：

```text
.heagent/CONTEXT.md > AGENTS.md > CLAUDE.md
```

## 开发与测试

运行测试：

```bash
pytest
```

默认会跳过真实外部依赖的集成测试；需要时显式执行：

```bash
pytest -m integration
```

常用检查：

```bash
ruff check src tests
mypy src
```

## 许可证

仓库当前没有附带 `LICENSE` 文件。若要在团队或外部场景使用，先明确授权边界。
