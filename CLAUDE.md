# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> 本文件只放**常驻必备**（安全声明 / 命令 / 规范 / 架构骨架 / 硬约束）。**架构详解（数据流、模块详解、调用链、容错分层等）见 [`docs/frame.md`](docs/frame.md)，按需查阅。**

## ⚠️ 安全声明

HeAgent 执行 shell / 读写文件 / 调外部 API，并可连接**外部 MCP server**（其进程、命令、HTTP transport 均由 `.mcp.json` 声明，可能来自任意第三方）。`SafetyGuard` **不是真正的安全边界**（命令黑名单可绕过、工具返回内容无围栏进入上下文、prompt injection 无隔离）。**不可在不可信内容或不可信 LLM 输出下裸跑**——必须配 OS 级沙箱（容器/firejail）。修改安全相关代码时勿将其当作有效边界。

**引擎执行层（`engine/`）同样非安全边界**：`ToolExecutor` 的 `SANDBOX_REQUIRED` 模式默认 `execute_in_sandbox()` 为**透传**（未接真实后端），`PolicyEngine` 的审批/沙箱裁决仅产出 `PolicyVerdict`，不强制 OS 级隔离。与 `SafetyGuard` 一视同仁——不可作为有效边界。

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

## 文档布局

**架构权威 = `docs/frame.md`**（活的中文总览，随代码更新；含数据流 / 模块依赖 DAG / 核心模块详解 4.1–4.12 / 已知缺口 / 完整调用链 / 技术规范）。

| 路径 | 用途 |
|------|------|
| `docs/frame.md` | **架构权威**——改架构 / 数据流 / 模块内部前先读此 |
| `docs/stock/` | 运行时股票报告输出，已 gitignore |
| `_bmad-output/baseline/` | 主线规划周期（epics 1-10，冻结决策）：`architecture.md`·`brief.md`·`prd.md`·`epics.md`·`epics-self-learning.md`·`sprint-status.yaml` + `stories/` |
| `_bmad-output/mcp-client/` | MCP 集成周期（epics 11-13） |
| `_bmad-output/patches/` | 计划外补丁与技术债，跨周期扁平 |

> 进度：全部 10 个 epic 已完成（24 个 FR），详见 `_bmad-output/baseline/sprint-status.yaml`；`engine/` 为 epic 外 P0 增量（见 frame.md 4.12）。

## 架构骨架

HeAgent 是一个自学习 AI Agent 框架——单进程异步 Python 库，编排 LLM ↔ 工具执行循环；CLI 入口经 `asyncio.run()` 桥接。**完整数据流、模块详解、调用链见 `docs/frame.md`。**

模块依赖 DAG：

```
exceptions  types  config
    ↑          ↑       ↑
    └─ providers ─┴── tools ─┴── context ── engine ── agent
                            ↑              ↑
                        memory ─────────────┘
```

模块一句话清单：

- `agent/` — 顶层编排（`AgentLoop` 主循环 + `middleware` + `sub` 子 Agent）
- `providers/` — LLM provider（OpenAI 兼容 / Anthropic）+ 三层容错（`chain` 跨 provider 回退 / `key_rotation` 多密钥轮换 / `retry` 指数退避）
- `tools/` — `@tool` 注册（`registry`）+ `SafetyGuard`（shell 黑名单）+ `path_safety` + `builtins/`（18 工具）+ `mcp/` 桥接
- `engine/` — 运行时治理（`PolicyEngine` 准入/审批/沙箱裁决 + `ToolExecutor` 分发 + `store`/`ledger`/`observability`），经 `EngineContainer` 注入 `AgentLoop`
- `context/` — 上下文压缩 / 会话持久化 / 上下文文件加载 / token 估算
- `memory/` — 自学习闭环（`skills`/`facts`/`profile`/`soul`）
- `cron/` — 后台定时调度

硬约束（违反即架构错误）：

- 新增 provider / tool **禁止**从 `agent/` 导入；`tools/mcp/` 同（`AgentLoop` 零改动，仅经 `ToolRegistry` 注入工具）。
- `engine/` 依赖 `types`/`exceptions`/`tools.safety`，被 `agent/` 依赖。
- 跨模块数据用 Pydantic 模型（`types.py`），**禁止**原始 dict。
- 工具执行链固定为 **`PolicyEngine.evaluate()` → `ToolExecutor` → `SafetyGuard.check()` → handler**。

**何时读 `docs/frame.md`（按需，不常驻）：** 改 `agent`/`providers`/`tools`/`engine` 行为、查数据流或模块内部、查 Provider 容错分层（FR-4）、技能匹配算法、系统提示词注入顺序（`_build_system()`）、完整调用链时。源码是最终权威。

## 测试

- 测试平铺在 `tests/`（provider 测试在 `tests/providers/`）；agent loop 测试用 `StubProvider`；每个测试用 `reset_settings()` 重置 `Settings` 单例。

## 代码规范

- **命名**：PEP 8——`snake_case.py`、`PascalCase` 类名，不加 `Protocol`/`Interface` 后缀，async 方法不加 `_async` 后缀。
- **数据模型**：一律使用 Pydantic `BaseModel`，不用 `dataclass` 或原始 `dict`。（例外：内部状态对象 `AgentState` 和 `SubAgentResult` 使用 `dataclass`。）
- **异步**：全部异步。库代码中不出现同步 I/O。`click` CLI 通过 `asyncio.run()` 桥接。
- **日志**：每个模块 `logging.getLogger(__name__)`，仅使用标准库。
- **行宽**：120（ruff.toml）。
- **Python 版本**：3.11+。

## 已知缺口

- `SafetyGuard` / `path_safety` / `engine` sandbox 均非真正安全边界——须 OS 级沙箱兜底（见文首声明）。
- **工作区路径双重围栏（冲突，非折中）**：`PolicyEngine._validate_paths()`（executor 前，基于 `RunContext.workspace_root`）与 `tools/path_safety.py`（`resolve_workspace_path()`，各 file 工具内部）两套并存——改其一须同步评估另一处。
- `ToolExecutor.execute_in_sandbox()` 默认透传（未接真实沙箱后端），`SANDBOX_REQUIRED` 裁决不产生 OS 级隔离效果。
- MCP V1 边界：`SafetyGuard` 未覆盖 MCP 工具（deferred DP-4）；运行时断连工具不自动 unregister（降级 `ToolError`，FR-3）；仅接 Tools 原语。
- 完整缺口表见 `docs/frame.md` 五。
