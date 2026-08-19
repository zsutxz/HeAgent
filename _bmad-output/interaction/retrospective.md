# 交互与可扩展层周期 · Retrospective（Epic 29-35）

> 日期：2026-08-19
> 范围：`_bmad-output/interaction/` 周期，7 个 Epic（29-35）、28 个 story、7 次提交
> 动机：对照 Claude Code 补齐「面向使用者的交互与可扩展层」

## 一、做了什么

| Epic | 主题 | 核心交付 |
|------|------|----------|
| 29 | 运行时审批闭环 | `engine/approval.py`：`ApprovalHandler` 协议 + `APPROVAL_REQUIRED` 从「死判决」变为可交互授权 |
| 30 | 会话恢复入口 | CLI `--continue` / `--resume <session_id>` 复用已有会话 |
| 31 | 斜杠命令系统 | `slash.py` 注册表 + 用户自定义命令（`.heagent/commands/*.md`） |
| 32 | Hooks 系统 | `engine/hooks.py`：`PreToolUse`（可阻断）/`PostToolUse`/`SessionStart`/`SessionEnd` |
| 33 | Plan Mode / 只读模式 | 内置只读工具补 `readOnlyHint`，`PolicyEngine.allowed_tools` 白名单收敛 |
| 34 | 配置文件驱动角色 + 成本估算 | `.heagent/agents/*.md` 加载 `RoleSpec` + `model_pricing` 成本展示 |
| 35 | CLI 体验 + 技术债收尾 | `web_fetch` 接 `guard_content`、cron expr 诊断、`init --project`、readline 历史 |

累计新增约 70 个测试，全量 1052 通过，`ruff`/`mypy` 零错误。

## 二、做对的

1. **复用既有基础设施，`AgentLoop` 核心零侵入**。审批复用 `PolicyEngine.approval_tools` + `metadata["approved_tools"]`；Plan Mode 复用 `allowed_tools`；Hooks 复用 `EventBus` 事件语义；角色复用 `RoleSpec`/`register_role`。7 个 Epic 无一改动 `loop.py` 的主循环结构——只在 `tool_execution.py` 执行链和装配层（`cli.py`/`EngineContainer`）插入扩展点。这验证了 `design.md`「新增能力不改 `AgentLoop`」的成功标准。
2. **fail-safe 方向的一致性**。审批 handler 异常 → DENY；hook 命令崩溃/超时 → 非 0 退出码（block 阻断）；Plan Mode 排除 MCP 工具（`readOnlyHint` 不可信）；`model_pricing` 无效 JSON → 空表不崩溃。每个扩展点都默认「不给更多能力」，而非「放宽」。
3. **声明式扩展点优先于硬编码**。斜杠命令注册表、`.heagent/commands/*.md`、`.heagent/agents/*.md`、`.heagent/hooks.json` 都用文件/注册表声明，用户无需改代码。frontmatter 解析器在 `slash.py` 与 `roles.py` 各自独立实现但同构——轻重复换来零耦合。
4. **安全立场诚实**。审批、Hook、Plan Mode 的 docstring 都明确标注「非真正安全边界，须 OS 级沙箱兜底」，未制造「审批=安全」「Hook=沙箱」的假象。

## 三、可改进的

1. **成本估算的价格表是全局 JSON 字符串**（`Settings.model_pricing`）。per-model 价格表用 JSON 字符串承载，`model_pricing_map` 解析逻辑内联在 config。若价格表复杂化，宜抽独立数据模型 + 校验（如负价、非数字容错）。
2. **`guard_content` 标记文案写死「MCP 返回」**。`web_fetch` 复用后，注入标记仍显示「⚠ MCP 返回命中注入启发式」——对 web 内容措辞不精确。可给 `guard_content` 加 `source` 参数（默认 `"MCP"`），`web_fetch` 传 `"web"`（本次为保持零回归直接复用）。
3. **readline 历史在 Windows 上静默失效**。Python 3.11 Windows 无 `readline`，历史功能不可用。若需跨平台历史，可评估 `prompt_toolkit`（重依赖）或 Python 3.13+ 的 `_pyrepl`。
4. **Hook 事件集不完整**。仅 `PreToolUse`/`PostToolUse`/`SessionStart`/`SessionEnd`，Claude Code 还有 `UserPromptSubmit`/`Stop`/`SubagentStop`/`PreCompact`。用户输入提交点（`UserPromptSubmit`）在 `cli.py` 主循环，需额外集成。

## 四、教训（跨周期课纲补充）

1. **EventBus 观察者「同步不得阻塞」决定了 Hook 的架构**。初版设想「HookManager 作为 EventObserver」，但 `EventObserver.handle` 是同步派发、禁止 I/O——异步 hook 命令放进去会拖死主循环。**教训**：可扩展点的「异步 vs 同步」约束要先读清，再决定是「订阅」还是「显式 await」；阻断语义（PreToolUse block）天然要求同步返回结果，只能用显式 await，不能用 fire-and-forget 观察者。
2. **「缓存/幂等层」与「新增扩展点」的顺序要理清**。PreToolUse 阻断若直接 `return` 会跳过 `ledger` 回写，留下 RUNNING 状态的租约记录。本次用「构造 error ToolResult → 走正常 ledger 回写路径」规避。**教训**：在 `execute_tool_call` 的幂等/账本链路中插新分支时，须确认新分支仍走 `ledger.complete()/fail()` 收尾，否则埋下 lease 泄漏。
3. **技术债收尾要连带修「同构的兄弟缺口」**。`web_fetch` 接 `guard_content` 与 MCP `bridge_result` 是对齐；cron expr 畸形诊断是 deferred-work 的独立条目——本周期一并收尾，避免「已知缺口」长期悬挂。**教训**：deferred-work 里写了 suggested fix 的条目，在相关能力迭代时应顺带关闭，而非等专门 spec。

## 五、结论

「交互与可扩展层」周期把 HeAgent 从「架构实验场」推进为「可日常使用的 agent 工具」：审批、会话恢复、斜杠命令、Hooks、Plan Mode、自定义角色、成本追踪七大能力全部落地，且每一项都复用既有基础设施、`AgentLoop` 核心零侵入、fail-safe 方向一致。这印证了 `design.md` 的定位——「新增工具或 Provider 时不需要重写 `AgentLoop`」不再是口号，而是被 7 个 Epic 反复验证的事实。
