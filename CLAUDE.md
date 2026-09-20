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

**后续（deferred / future，V2 未做）：** Resources 原语、返回内容围栏的全局级用户可配置签名入口（项目级 `.heagent/injection_signatures.json` 已交付；仍属 defense-in-depth，非真正安全边界）。（Prompts 原语已完成：Story 17-1/2/3/4 2026-07-20，story 归档文件沿用旧前缀 16-x、+1 偏移对照见该周期 README；写操作治理已交付 V2 2026-07-17：annotations 感知 `PolicyEngine` 闸门，见 `engine/policy.py`、`tools/mcp/mapping.py`；执行前工具名拦截已交付 DP-4 第一半 2026-07-08；返回内容启发式围栏已交付 DP-4 第二半 2026-07-10；运行时断连主动 unregister 已交付：`tools/mcp/manager.py` `_watch` 持有期 `send_ping` 健康探测，ping 失败即注销该 server 工具。）

## 文档布局

**架构权威 = `docs/frame.md`**（活的中文总览，随代码更新；含数据流 / 模块依赖 DAG / 核心模块详解 4.1–4.12 / 已知缺口 / 完整调用链 / 技术规范）。

| 路径 | 用途 |
|------|------|
| `docs/frame.md` | **架构权威**——改架构 / 数据流 / 模块内部前先读此 |
| `docs/design.md` | 功能设计与理念——项目要做什么 / 为什么（产品视角，区别于 frame.md 的代码实现） |
| `docs/iteration.md` | 迭代开发指南与历程——怎么迭代过来的 / 怎么继续迭代（BMad 周期 / epic / 技术债 / 路线图） |
| `docs/stock/` | 运行时股票报告输出，已 gitignore |
| `_bmad-output/implementation-artifacts/deferred-work-archive.md` | **架构/代码优化台账**（活动遗留项 + 勘察类闭合归档）——被要求「优化项目」时先读此：条目含触发条件/严重度/冻结边界，闭合按归属 epic 归档（原 `deferred-work.md` 已于 2026-09-17 并入） |
| `_bmad-output/consolidated-overview.md` | **统一整合总览（含 epic 总目录）**——全周期摘要 + 全 epic（1-47 + S1-S4）主题/状态/story/patch 映射（原 EPICS-INDEX.md 已并入） |
| `_bmad-output/epics/epic-区间-周期/epic-NN-主题/stories/` | 按 epic 归档的 story 文件，嵌套在所属周期目录内（仅建有 story 的 epic） |
| `_bmad-output/epics/epic-01-10-主线规划周期/` | 主线规划周期（epics 1-10，冻结决策）：`architecture.md`·`brief.md`·`prd.md`·`epics.md`·`epics-self-learning.md`（story 已移至 epic 目录；sprint-status 权威在顶层 `_bmad-output/sprint-status.yaml`） |
| `_bmad-output/epics/epic-11-18-MCP集成周期/` | MCP Client 集成周期（epics 11-18，三阶段，2026-08-18 合并） |
| `_bmad-output/epics/`（其余周期目录） | epic-S1-S4-沙箱硬化周期 / epic-19-20-健壮性硬化周期 / epic-21-24-质量工程周期 / epic-25-28-GUI界面周期 / epic-29-35-交互扩展周期 / epic-36-39-文件安全防护周期 / epic-40-沙箱会话化周期 / epic-41-目标驱动开发周期 / epic-42-BMad技能包运行时周期 / epic-43-46-目标级工作流周期 / epic-47-声明式BMad敏捷工作流周期 |
| `_bmad-output/epics/<周期>/<epic-NN-主题>/` | 补丁 spec 与 story 同目录归档——原 `_bmad-output/patches/`（按领域分子目录）已于 2026-09-15 解散，映射见 consolidated-overview.md 十三 |

> 进度：全部 10 个 epic 已完成（24 个 FR），详见顶层 `_bmad-output/sprint-status.yaml`；`engine/` 为 epic 外 P0 增量（见 frame.md 4.12）。

## 架构骨架

HeAgent 是一个自学习 AI Agent 框架——单进程异步 Python 库，编排 LLM ↔ 工具执行循环；CLI 入口经 `asyncio.run()` 桥接，`heagent gui` 子命令懒加载 Textual TUI。**完整数据流、模块详解、调用链见 `docs/frame.md`。**

模块依赖 DAG：

```
exceptions  types  config  persist  roles  frontmatter
    ↑          ↑       ↑
    └─ providers ─┴── tools ─┴── context ── engine ── agent ── gui
                            ↑              ↑
                        memory ─────────────┘
```

模块一句话清单：

- `agent/` — 顶层编排（`AgentLoop` 主循环 + `middleware` + `sub` 子 Agent）
- `providers/` — LLM provider（OpenAI 兼容：DeepSeek / Kimi / GLM 等 + Anthropic 原生）+ 智能路由（`router` RoutingProvider）+ 多层容错（`chain` 跨 provider 回退 / `key_rotation` 多密钥轮换 / `retry` 指数退避 / `switchable` 运行时 vendor 切换）
- `tools/` — `@tool` 注册（`registry`）+ `SafetyGuard`（shell 黑名单）+ `path_safety` + `edits`/`sandbox` + `builtins/`（25 工具）+ `mcp/` 桥接
- `engine/` — 运行时治理（`PolicyEngine` 准入/审批/沙箱裁决 + `ToolExecutor` 分发 + `store`/`ledger`/`observability`），经 `EngineContainer` 注入 `AgentLoop`
- `persist.py` / `roles.py` / `frontmatter.py` — 顶层底层共用模块：原子写/容错读/跨进程文件锁/prune 批量内核；`RoleSpec` 角色注册表（2026-09 自 `engine/` 迁出）；共享 frontmatter 解析（两个分隔符变体 + 严/宽两档键值 + 标量 coercion，收敛原六处手写解析器，2026-09-17）
- `context/` — 上下文压缩 / 会话持久化 / 上下文文件加载 / token 估算
- `events/` — 事件传输层（`RunEvent` JSONL 对外契约 + `JsonlSink` 落盘 + `replay` 回放），运行时零 `engine/` 依赖
- `memory/` — 自学习闭环（`skills`/`facts`/`profile`/`soul`）
- `cron/` — 后台定时调度
- `gui/` — Textual TUI（`app`/`bridge`/`screens`/`widgets`），经 `AgentBridge` 持有并观察 `AgentLoop`
- `cli.py` / `cli_init.py` / `cli_goal.py` / `slash.py` / `terminal.py` — CLI 入口（单次 + 交互模式）；`cli_init` 为 `heagent init` 子命令（2026-09-17 自 cli.py 拆出）；`cli_goal` 为 /goal 命令族（声明式工作流分发 + cron 自动推进；需求文档 require.md 与命名层在 `goal/document.py`，经 re-export 保持原命名空间）；`slash` 为注册表驱动斜杠命令 + 用户自定义命令（`.heagent/commands/*.md`），仅依赖 pydantic + 零依赖顶层模块 `heagent.frontmatter`

硬约束（违反即架构错误）：

- 新增 provider / tool **禁止**从 `agent/` 导入；`tools/mcp/` 同（`AgentLoop` 零改动，仅经 `ToolRegistry` 注入工具）。
- `engine/` 依赖 `types`/`exceptions` + `tools.call_summary`/`tools.sandbox`/`tools.path_safety` + `memory.skill_packages`（container 另有 lazy `config`），被 `agent/` 依赖；`persist.py`/`roles.py`/`frontmatter.py` 为顶层底层模块，任何模块可依赖。memory 运行期不反向依赖 `engine/`（`DreamScheduler` 的 engine 由入口层注入，仅 TYPE_CHECKING 引用）。
- 跨模块数据用 Pydantic 模型（`types.py`），**禁止**原始 dict。
- 工具执行链固定为 **`PolicyEngine.evaluate()` → `ToolExecutor` → `SafetyGuard.check()` → handler**。

**何时读 `docs/frame.md`（按需，不常驻）：** 改 `agent`/`providers`/`tools`/`engine` 行为、查数据流或模块内部、查 Provider 容错分层（FR-4）、技能匹配算法、系统提示词注入顺序（`_build_system()`）、完整调用链时。源码是最终权威。

## 测试

- 测试平铺在 `tests/`（provider 测试在 `tests/providers/`）；agent loop 测试用 `StubProvider`；每个测试用 `reset_settings()` 重置 `Settings` 单例。
- **架构契约测试** `tests/test_architecture_contracts.py`（FORBIDDEN_RUNTIME_IMPORTS 反向依赖断言、frontmatter 正则只允许存在于 `frontmatter.py` 等）——改包间依赖或新增解析器时**必须同步维护**，其职责是把只写在文档里的硬约束钉成可执行断言、拒绝「明天的静默漂移」。
- **monkeypatch 模块路径缝是拆分/搬移红线**：测试大量 patch 字符串路径（`heagent.cli._run_prompt`、`heagent.cli_goal._goal_session`、`heagent.cli_goal._GOAL_LOCK_TIMEOUT`、`cli_goal._goal_auto_lock` 等）——被 patch 的目标函数**及其调用方**必须留在原模块（Python 模块全局查找语义）；`test_goal_declarative_workflow.py::test_cli_reexports_goal_runner_but_not_monkeypatch_seams` 钉死了 cli 的 re-export 面。搬代码前先 grep 缝。
- GUI 测试经 `pytest.importorskip("textual")` 守卫（CI 只装 `.[dev]` 无 textual，自动跳过）；pilot 交互测试模板见 `tests/test_gui_goal.py`。

## 代码规范

- **命名**：PEP 8——`snake_case.py`、`PascalCase` 类名，不加 `Protocol`/`Interface` 后缀，async 方法不加 `_async` 后缀。
- **数据模型**：一律使用 Pydantic `BaseModel`，不用 `dataclass` 或原始 `dict`。（例外：内部状态对象 `AgentState` 和 `SubAgentResult` 使用 `dataclass`。）
- **异步**：全部异步。库代码中不出现同步 I/O。`click` CLI 通过 `asyncio.run()` 桥接。
- **日志**：每个模块 `logging.getLogger(__name__)`，仅使用标准库。

## 已知缺口

> 完整缺口表见 `docs/frame.md` 五；沙箱/文件安全机制与硬化履历见 frame.md 4.4、配置面见 `.env.example`。

**核心立场（全部 defense-in-depth，非真正安全边界，须 OS 级沙箱兜底——机制细节见文首安全声明）：**
`SafetyGuard` 黑名单、`path_safety` 凭证 deny、`PolicyEngine`（围栏 / 审批 / 注解闸门 / 沙箱裁决）、
sandbox 后端（Firejail 仅隔离 shell 子进程且非完美边界；WinJob 无文件系统/网络隔离；会话目录仅目录约定；
file/memory 等宿主进程内工具不受覆盖）、MCP 工具拦截与返回内容围栏（标记透传不阻断）。

**活动缺口**（触发条件/严重度/冻结边界见 `_bmad-output/implementation-artifacts/deferred-work-archive.md`）：
MCP stdio server 子进程不经沙箱（中-高）；技能资源 TOCTOU 残余竞态（专项评估）；沙箱进程数限额未做、
`RoleSpec.sandbox_profile` 死字段（低）。
