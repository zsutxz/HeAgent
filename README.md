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

- 多 Provider 接入：OpenAI、Anthropic、DeepSeek，以及兼容 OpenAI/Anthropic 协议的服务；交互模式经 `/model` 在多 vendor 间运行时切换。
- 多层容错：重试、中间层 key 轮换、外层跨 Provider 回退，叠加运行时 vendor 切换的自动回退。
- 声明式工具注册：`@tool` 自动生成 schema 并接入工具注册中心。
- 内置工具集：shell、文件读写、文件搜索、技能管理、记忆、Cron、子 Agent 委派、Web 抓取（`web_fetch`）、Git 只读工具（`git_status`/`git_diff`/`git_log`/`git_blame`）。
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
| `--sandbox` | 沙箱后端（`passthrough` 默认 / `firejail`） |

安装脚本后也可以直接使用：

```bash
heagent "你好"
```

## 沙箱执行（Firejail）

HeAgent 的 `shell` 工具可以直接在系统上执行 LLM 生成的任意命令——这是一把双刃剑。
Firejail 沙箱后端在 OS 层面圈住 shell 子进程，降低误删文件、出站泄数据、fork bomb 等风险。

> ⚠️ **Firejail 仅支持 Linux，且非完美安全边界**（可被绕过）。它提供的是 defense-in-depth，
> 不能替代整体 OS 级沙箱（容器/VM）。Windows/macOS 上会自动降级为 passthrough（零隔离）。

### 安装 Firejail

```bash
# Debian/Ubuntu
sudo apt install firejail

# Fedora
sudo dnf install firejail

# Arch
sudo pacman -S firejail
```

### 启用

```bash
# 方式一：CLI flag（一次性）
heagent --sandbox firejail "帮我运行一个命令"

# 方式二：.env 持久化（所有 run 都生效）
# 在 .env 中添加：
SANDBOX_BACKEND=firejail
```

### 配置隔离级别（profile）

不同角色可以有不同的隔离强度。在代码中声明：

```python
from heagent.engine.roles import RoleSpec, register_role
from heagent.engine import EngineContainer
from heagent.tools.sandbox import FirejailBackend

# 声明角色——coder 不能上网
register_role(RoleSpec(
    name="coder",
    system="你是编程角色...",
    sandbox_profile="network-isolated",
))

# 启动时装配 profile 映射
engine = EngineContainer(
    command_runner=FirejailBackend(
        profiles={
            "default": ("--private-tmp",),                         # 仅隔离 /tmp
            "network-isolated": ("--net=none", "--private-tmp"),   # 断网 + 隔离 /tmp
        },
        workspace_root="/path/to/project",
    ),
)
```

当 agent 以 coder 角色调 `shell` 时，firejail 自动收到 `--net=none`——命令无法出站。

### workspace 文件系统隔离

当通过 `EngineContainer.default(workspace_root="...")` 或 CLI 启动时（自动取当前工作目录），
FirejailBackend 会自动添加 `--private=<workspace_root>`：

- 子进程**只能看到** workspace 目录下的文件
- 系统其他路径（`/etc`、`/home` 等）全部不可见

### 进程组 killing（Linux）

超时或取消时，`sh -c "cmd1 & cmd2"` 的后台子孙全部被杀，不留孤儿进程。
仅 Linux 生效。

### 没装 firejail？

不会崩溃。启动时会看到：

```
WARNING firejail not found at 'firejail', sandbox disabled — falling back to passthrough
```

shell 照常运行，只是没有 OS 级隔离。装上 firejail 后重启 agent 即可生效。

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
