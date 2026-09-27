# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## ⚠️ 安全声明

HeAgent 执行 shell / 读写文件 / 调外部 API，并可连接**外部 MCP server**。`SafetyGuard`、`PolicyEngine`、`ToolExecutor` 和 sandbox 后端**均非真正安全边界**（命令黑名单可绕过、工具返回内容无围栏进入上下文、prompt injection 无隔离）。

**不可在不可信内容或不可信 LLM 输出下裸跑**——必须配 OS 级沙箱（容器/firejail）。修改安全相关代码时勿将其当作有效边界。

MCP 特定风险：stdio server 拉起任意本地子进程、HTTP server 连任意远程端点、`Tool.annotations` 是 server 自声明不可信、工具输出启发式围栏不阻断——须 OS 级沙箱兜底。

## 文档布局

**架构权威 = `docs/frame.md`**（数据流 / 模块依赖 DAG / 核心模块详解 / 调用链 / 技术规范）

| 路径 | 用途 |
|------|------|
| `docs/frame.md` | 架构权威——改架构/数据流/模块内部前先读此 |
| `docs/design.md` | 功能设计与理念 |
| `_bmad-output/implementation-artifacts/deferred-work-archive.md` | 架构/代码优化台账（触发条件/严重度/冻结边界） |
| `_bmad-output/consolidated-overview.md` | 统一整合总览（Epic 1-50 + S1-S4 主题/状态/story 映射） |

## 架构骨架

HeAgent 是单进程异步 Python 库，编排 LLM ↔ 工具执行循环。**完整数据流、模块详解、调用链见 `docs/frame.md`。**

### 模块依赖 DAG

```
公共层 pub/（零 heagent 依赖）：exceptions · types · safe_logging · persist · frontmatter · roles · workspace · task_shutdown · projects
配置面 config/（依赖 pub/）：Settings · catalog · write · envfile

主脊：  providers ─┐
        tools ─────┼─→ engine ─→ agent ─→ 入口层（cli/ · gui · goal/）
        context ───┘

旁支：  memory（对 engine 仅 TYPE_CHECKING）
        events（运行期仅依赖 pub.exceptions）
        network/（仅 stdlib + pydantic + pub.safe_logging，被入口层单向使用）
```

### 核心模块

- `agent/` — `AgentLoop` 主循环 + middleware + 子 Agent
- `providers/` — LLM provider + 智能路由 + 多层容错（chain / key_rotation / retry / switchable）
- `tools/` — `@tool` 注册 + `SafetyGuard` + `path_safety` + `builtins/` + `mcp/` 桥接
- `engine/` — 运行时治理（`PolicyEngine` + `ToolExecutor` + store/ledger/observability）
- `pub/` — 公共层（异常/类型/日志/持久化/frontmatter/角色/工作区/任务关停/项目）
- `config/` — 配置面（Settings / catalog / write / envfile）
- `context/` — 上下文压缩/会话持久化/token 估算
- `memory/` — 自学习闭环（skills / facts / profile / soul）
- `network/` — 入口传输层（HTTP + SSE；TCP 入口已于 2026-09-27 删除，勿按旧文档恢复）
- `cli/` — 入口层包（console / composition / interactive / goal / http / http_console / dialogs / init / display / slash / terminal / wiring / housekeeping / port_finder）

### 硬约束

- 新增 provider / tool **禁止**从 `agent/` 导入
- `engine/` 依赖 `pub` + `tools` 部分 + `events.protocol`，被 `agent/` 依赖
- `network/` 不得导入运行栈（agent/engine/providers/tools/memory/context/cron/events）与配置（config/pub.projects/pub.workspace）
- 跨模块数据用 Pydantic 模型（`pub/types.py`），**禁止**原始 dict
- 工具执行链固定为 **`PolicyEngine.evaluate()` → `ToolExecutor` → `SafetyGuard.check()` → handler**

## 常用命令

```bash
# 开发环境安装
pip install -e ".[dev]"

# 运行测试（跳过 integration/benchmark）
pytest

# 单个测试文件/用例
pytest tests/test_agent_loop.py
pytest tests/test_agent_loop.py::test_basic_run

# 覆盖率（门限 87%）
pytest --cov --cov-report=term-missing

# 集成测试/性能基准
pytest -m integration
pytest -m benchmark

# 静态检查
ruff check src tests
ruff format --check src tests
mypy src

# 自动修复格式
ruff format src tests

# 运行 HeAgent
heagent "写一个快速排序"           # 单次执行
heagent                            # 交互模式
heagent init --project             # 初始化项目配置
heagent gui                        # TUI（需 pip install -e ".[gui]"）
heagent http-server                # HTTP 网页入口（127.0.0.1:8766，需 pip install "heagent[http]"）
```

## 代码规范

- **命名**：PEP 8——`snake_case.py`、`PascalCase` 类名，不加后缀
- **数据模型**：一律 Pydantic `BaseModel`（例外：`AgentState`/`SubAgentResult` 用 `dataclass`）
- **异步**：全部异步，库代码无同步 I/O，CLI 通过 `asyncio.run()` 桥接
- **日志**：`logging.getLogger(__name__)`，仅标准库
- **Git 提交**：执行 `git commit` 前必须先向用户呈报提交信息与文件清单，获得明确同意后才执行

## 测试约束

- `tests/test_architecture_contracts.py` **必须同步维护**——改包间依赖或新增解析器时更新 `FORBIDDEN_RUNTIME_IMPORTS`
- **monkeypatch 缝是搬移红线**——搬代码前先 `grep` patch 字符串路径（如 `heagent.cli.console._run_prompt`）
- `heagent/cli/__init__.py` 永不放 import（`test_cli_package_shell_stays_thin`）
- 子模块延迟导入必须指向实模块，不能指回包壳

## 已知缺口

完整清单见 `docs/frame.md` 五与 `_bmad-output/implementation-artifacts/deferred-work-archive.md`。

核心立场：`SafetyGuard`/`PolicyEngine`/sandbox 均非真正安全边界，须 OS 级沙箱兜底。

活动缺口：MCP stdio server 子进程不经沙箱（中-高）；同一会话文件的两个写者整份覆盖对方历史（中）；技能资源 TOCTOU 残余竞态（专项评估）。
