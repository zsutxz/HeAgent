# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

> 本文件只放**常驻必备**（安全声明 / 命令 / 规范 / 架构骨架 / 硬约束）。**架构详解（数据流、模块详解、调用链、容错分层等）见 [`docs/frame.md`](docs/frame.md)，按需查阅。**

## ⚠️ 安全声明

HeAgent 执行 shell / 读写文件 / 调外部 API，并可连接**外部 MCP server**（其进程、命令、HTTP transport 均由 `.mcp.json` 声明，可能来自任意第三方）。`SafetyGuard` **不是真正的安全边界**（命令黑名单可绕过、工具返回内容无围栏进入上下文、prompt injection 无隔离）。**不可在不可信内容或不可信 LLM 输出下裸跑**——必须配 OS 级沙箱（容器/firejail）。修改安全相关代码时勿将其当作有效边界。

**引擎执行层（`engine/`）同样非安全边界**：`ToolExecutor` 的 `SANDBOX_REQUIRED` 模式 `execute_in_sandbox()` 默认 Passthrough **透传**，可经 `EngineContainer(command_runner=FirejailBackend())` 注入 OS 级后端（仅隔离 `shell` 子进程、Linux-only、非完美边界，见 `tools/sandbox.py`）；`PolicyEngine` 的审批/沙箱裁决仅产出 `PolicyVerdict`，不强制 OS 级隔离。与 `SafetyGuard` 一视同仁——不可作为有效边界。

**MCP 特定风险（FR-10/11，与上述立场同构，不制造「接 MCP 更安全」假象）：**

- **外部 MCP server = 不可信代码**：stdio server 会拉起任意本地子进程，HTTP server 会连任意远程端点；`SafetyGuard` 工具名黑名单已覆盖 MCP 工具（执行前拦截，DP-4 第一半 2026-07-08 落地），返回内容亦经启发式围栏（标记透传，DP-4 第二半 2026-07-10 落地）——但两者均非真正边界，立场不变。
- **Tool.annotations 是 server 自声明、不可信**：MCP `Tool.annotations`（`destructiveHint`/`readOnlyHint`/etc.）由 server 自行声明，恶意/错误 server 可把 `delete_repository` 谎报为 `readOnlyHint=true`。`PolicyEngine` 的写操作治理闸门（destructive→审批 / readOnly→放行 / 缺省→fail-safe）仅 defense-in-depth 确定性标记，**非真正安全边界**，不改变「须 OS 级沙箱兜底」的核心立场。
- **MCP 工具输出进入 LLM 上下文有启发式围栏但非隔离**：server 返回内容（含远端响应）经 `mapping.bridge_result` 启发式扫描，命中注入签名则加 warning 标记后透传（不阻断）；标记仅 observable defense-in-depth，prompt injection 仍无可靠围栏——视为与内置工具返回**同等不可信**，须 OS 级沙箱兜底。
- **同等约束**：MCP 工具走与内置工具一致的 `ToolError` 语义，享受同等的工具名黑名单预校验（DP-4 第一半 2026-07-08）与返回内容启发式标记（DP-4 第二半 2026-07-10），但**两者均非真正安全边界**。
- **须 OS 级沙箱兜底**：连 MCP server 时同样必须在沙箱内运行，并对子进程 / 出站网络施加最小权限。

**后续（deferred / future，V2 未做）：** Resources/Prompts 原语、返回内容围栏的用户可配置签名入口（V1/V2 仅内置启发式集）。（写操作治理已交付 V2 2026-07-17：annotations 感知 `PolicyEngine` 闸门，见 `engine/policy.py`、`tools/mcp/mapping.py`；执行前工具名拦截已交付 DP-4 第一半 2026-07-08；返回内容启发式围栏已交付 DP-4 第二半 2026-07-10；运行时断连主动 unregister 已交付：`tools/mcp/manager.py` `_watch` 持有期 `send_ping` 健康探测，ping 失败即注销该 server 工具。）

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
| `docs/design.md` | 功能设计与愿景——项目要做什么 / 为什么（产品视角，区别于 frame.md 的代码实现） |
| `docs/iteration.md` | 迭代开发指南与历程——怎么迭代过来的 / 怎么继续迭代（BMad 周期 / epic / 技术债 / 路线图） |
| `docs/stock/` | 运行时股票报告输出，已 gitignore |
| `_bmad-output/baseline/` | 主线规划周期（epics 1-10，冻结决策）：`architecture.md`·`brief.md`·`prd.md`·`epics.md`·`epics-self-learning.md`·`sprint-status.yaml` + `stories/` |
| `_bmad-output/mcp-client/` | MCP 集成周期（epics 11-13） |
| `_bmad-output/patches/` | 计划外补丁与技术债，跨周期扁平 |

> 进度：全部 10 个 epic 已完成（24 个 FR），详见 `_bmad-output/baseline/sprint-status.yaml`；`engine/` 为 epic 外 P0 增量（见 frame.md 4.12）。

## 参考实现

[hermes-agent](https://github.com/NousResearch/hermes-agent.git)（NousResearch）——同源自学习 agent 架构（skills/facts/profile/soul 记忆、MCP、cron、多 provider 容错），设计与约定可作参考。注意 hermes 为**同步单文件巨型架构**（`run_agent.py`/`cli.py` 各逾万行、多平台 gateway/TUI），HeAgent 为**异步模块化单库**——**不可直接照搬**，须按 HeAgent 栈（Pydantic / asyncio / pytest-asyncio）改造适配；CLAUDE.md 仅采纳硬约束级条目，细节去 `docs/frame.md`。

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
- `tools/` — `@tool` 注册（`registry`）+ `SafetyGuard`（shell 黑名单）+ `path_safety` + `builtins/`（19 工具）+ `mcp/` 桥接
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
- 工作区路径围栏已收敛：policy 预检（`_validate_paths`）与 file 工具 handler 守卫（`resolve_workspace_path`）共用同一算法 `resolve_under_root`（`tools/path_safety.py`），两层有意纵深防御，不再有两份可漂移副本。
- `ToolExecutor.execute_in_sandbox()` 默认 Passthrough 透传；可注入 `FirejailBackend`（仅隔离 `shell` 子进程、Linux-only、非完美边界），file/memory 等宿主进程内 I/O 工具不 spawn 子进程、不受覆盖——须整体 OS 级沙箱兜底（`tools/sandbox.py`）。
- MCP V1 边界：`SafetyGuard` 执行前工具名拦截已覆盖 MCP（DP-4 第一半 2026-07-08），返回内容启发式围栏已落地（DP-4 第二半 2026-07-10，标记透传、非真正边界）；仅接 Tools 原语。
- **MCP 写操作治理 annotations 不可信**：`Tool.annotations`（`destructiveHint`/`readOnlyHint`/etc.）是 server 自声明，恶意 server 可谎报读写属性。`PolicyEngine` 的注解闸门（destructive→审批 / readOnly→放行 / 缺省→fail-safe）仅 defense-in-depth，非真正安全边界——须 OS 级沙箱兜底（参见 `engine/policy.py`、`tools/mcp/mapping.py`）。
- 完整缺口表见 `docs/frame.md` 五。
