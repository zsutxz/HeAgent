---
title: 'DP-4 SafetyGuard 扩展到 MCP 工具（执行前确认/拦截）'
type: 'feature'
created: '2026-07-08'
status: 'done'  # 2026-07-08 交付：pytest 472 绿 / mypy 干净 / ruff 零新增（执行前工具名拦截 half 落地）
baseline_commit: '762e25c78516ad575c1837eb83db99c666c0cfb7'
review_loop_iteration: 0
context:
  - '{project-root}/docs/frame.md'
  - '{project-root}/CLAUDE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `SafetyGuard.check()` 首行 `if call.name != "shell": return`（`tools/safety.py:79`）——MCP 工具（`<server>__<tool>`）虽经执行链的 `guard.check()`（`engine/executor.py:99/156`），但对非 shell 工具直接 return，零拦截。这是 DP-4 deferred 项，FR-11「MCP 工具受同等安全约束」在执行前准入层未落实。

**Approach:** 给 `SafetyGuard` 加**工具名 blacklist**（`blocked_tools`，正则列表），`check()` 对所有工具先匹配工具名、命中转 `SafetyViolation`（经 `ToolExecutor` 转 `is_error=True` `ToolResult`，与 shell 防护同构）。补 `Settings.safety_blocked_tools` 配置入口 + `AgentLoop`/`SubAgent` 构造注入。默认空列表 = 零回归。

## Boundaries & Constraints

**Always:**
- 工具执行链固定不变：`PolicyEngine.evaluate() → ToolExecutor → SafetyGuard.check() → handler`。扩展只在 `check()` 内部加一段，不动链路。
- 默认 `blocked_tools=[]` 保持零回归：现有 19 内置工具 + MCP 工具行为不变（空列表不命中任何工具名）。
- `SafetyViolation` 语义与 shell 防护完全一致——`ToolExecutor` 已捕获转 `is_error=True` `ToolResult`，不向上抛、不中断循环。
- 工具名 blacklist 对**所有**工具生效（MCP + 内置 + shell），按 `call.name` 正则匹配（`re.IGNORECASE`），与现有 `BLACKLIST/WHITELIST` 编译方式同构。
- 立场不变：`SafetyGuard` 仍**非真正安全边界**，扩展不可制造「接 MCP 更安全」假象；`CLAUDE.md` 安全声明去 deferred 标记但保留「须 OS 级沙箱兜底」。
- 数据走 Pydantic：`Settings.safety_blocked_tools: list[str]`，不引入原始 dict。

**Ask First:**
- 是否同时加 **whitelist 语义**（仅允许 `allowed_tools` 中的工具名）？默认 defer——whitelist 会破坏「内置工具默认放行」语义（非空即拦内置），需独立设计，V1 先 blacklist。
- 是否需要 **CLI flag** 暴露 `safety_blocked_tools`？默认只 `Settings`（.env / config 文件），CLI flag defer。
- 实现期若发现 `SubAgent` 自建默认 `SafetyGuard()`（`agent/sub.py:82`）未继承父配置，HALT 确认注入路径（父传入 vs 子自建读 Settings）。

**Never:**
- 不做返回内容复核 / prompt injection 围栏（已拆出 defer 到 `deferred-work.md` 2026-07-08 条）。
- 不改 `PolicyEngine.block_mcp_tools`/`approval_mcp_tools`/`sandbox_mcp_tools`——那是 engine 治理层全量开关（粗粒度），与本 spec 的细粒度工具名拦截是两层纵深防御，不融合（CLAUDE.md 原则5）。
- 不内置「危险 MCP 工具名」硬编码列表——完全由用户配置驱动（避免维护成本 + 误判）。
- 不接真实 OS 沙箱、不做 interactive approval 后端（V1 `APPROVAL_REQUIRED` 仍等同阻断）。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 默认零回归 | `blocked_tools=[]`，任一 MCP 工具 `github__list_issues` | `check()` 不抛，正常执行 | N/A |
| 命中 blacklist 拦截 | `blocked_tools=["github__delete_.*"]`，MCP 工具 `github__delete_issue` | `check()` 抛 `SafetyViolation` | `ToolExecutor` 转 `is_error=True` `ToolResult`（content="Blocked tool by name: ..."） |
| 不命中放行 | `blocked_tools=["github__delete_.*"]`，MCP 工具 `github__list_issues` | `check()` 不抛，正常执行 | N/A |
| 工具名匹配也覆盖内置/shell | `blocked_tools=["shell"]`，shell 工具调用 | `check()` 抛 `SafetyViolation`（工具名段命中，先于 command 检查） | 同上 |
| shell 命令防护不变 | 任意 `blocked_tools`，shell 工具 + 危险命令 | 工具名段不命中→进入 shell 段→危险模式拦截照旧 | 现有 `SafetyViolation` |

</frozen-after-approval>

## Code Map

- `src/heagent/tools/safety.py` — `SafetyGuard.__init__` 加 `blocked_tools` 参数 + compiled；`check()` 开头加工具名匹配段（shell 早退之前）
- `src/heagent/config.py` — `Settings` 加 `safety_blocked_tools: list[str] = []`
- `src/heagent/agent/loop.py:132` — `self.guard = guard or SafetyGuard(blocked_tools=settings.safety_blocked_tools)`（从 Settings 注入）
- `src/heagent/agent/sub.py:82` — 确认子 Agent 继承父 guard 或同步从 Settings 注入
- `tests/test_safety.py` — 加 `TestBlockedTools`：MCP 名命中/不命中、默认空零回归、工具名覆盖 shell
- `CLAUDE.md` — 安全声明：DP-4 从 deferred → 已落地（立场不变）
- `docs/frame.md` — 4.11（line 506）+ 第五章已知缺口表（line 548）：更新 SafetyGuard MCP 覆盖状态
- `_bmad-output/baseline/sprint-status.yaml` — `action_items` DP-4 项 status `open → closed`

## Tasks & Acceptance

**Execution:**
- [x] `src/heagent/tools/safety.py` -- `SafetyGuard.__init__` 加 `blocked_tools: list[str] | None = None` + `self._blocked_tools_compiled`（`re.IGNORECASE`，仿 `_blocked_compiled`）；`check()` 在 shell 早退前加工具名匹配段，命中调 `_block(f"Blocked tool by name: {call.name}")` -- 核心扩展
- [x] `src/heagent/config.py` -- `Settings` 加 `safety_blocked_tools: list[str] = []`（Pydantic 字段，env 前缀对齐既有约定）-- 配置入口
- [x] `src/heagent/agent/loop.py` + `src/heagent/agent/sub.py` -- SafetyGuard 构造从 `get_settings().safety_blocked_tools` 注入（`guard or SafetyGuard(...)`）；子 Agent 优先继承父 guard -- 启用通路
- [x] `tests/test_safety.py` -- 加 `TestBlockedTools` 覆盖 I/O Matrix 四场景；构造用 `ToolCall(id="1", name="github__delete_issue", arguments={...})` 仿 `_shell_call` -- 验证意图
- [x] `CLAUDE.md` -- 安全声明段去 DP-4 deferred 标记，改述为已落地但立场不变 -- 诚实边界
- [x] `docs/frame.md` + `_bmad-output/baseline/sprint-status.yaml` -- 更新已知缺口 + action_items DP-4 关闭 -- 同步架构权威

**Acceptance Criteria:**
- Given `blocked_tools=["github__delete_.*"]`，when MCP 工具 `github__delete_issue` 经 `check()`，then 抛 `SafetyViolation` 且 `ToolExecutor` 返回 `is_error=True` `ToolResult`。
- Given 默认 `SafetyGuard()`（`blocked_tools=[]`），when 任一现有 MCP/内置工具经 `check()`，then 不抛（与改动前行为逐字节一致）。
- Given `blocked_tools=["shell"]`，when shell 工具调用经 `check()`，then 抛 `SafetyViolation`（工具名段命中，证明对所有工具生效）。
- Given `pytest` 全量，then 全绿（零回归）；`ruff check` / `mypy src` 无新增问题。

## Design Notes

**为何选 SafetyGuard 层而非启用 PolicyEngine 已有的 `block_mcp_tools`：** DP-4 原文（`architecture.md:571`、`prd-decision-log` DP-4）明确指「SafetyGuard 扩展」，且「敏感工具确认」语义是**按工具名细粒度**——`PolicyEngine.block_mcp_tools` 是全量 MCP 开关（粗粒度，整 server 级），不符。两者是两层纵深防御（policy 管 run 级准入，guard 管 单调用危险模式），不融合（CLAUDE.md 原则5）。policy 开关缺 Settings 入口是独立 deferred 项，不纳入。

**为何只 blacklist、V1 不做 whitelist：** whitelist 语义（仅允许 `allowed_tools` 中的工具）非空时会拦截所有未列出的内置工具，破坏「内置工具默认放行」现状，需独立设计白名单作用域（仅 MCP？全局？）。V1 先落最直接的拦截层，whitelist defer。

**check() 扩展结构（5 行）：**
```python
def check(self, call: ToolCall) -> None:
    for pat in self._blocked_tools_compiled:          # 新增：工具名 blacklist，对所有工具
        if pat.search(call.name):
            self._block(f"Blocked tool by name: {call.name}")
    if call.name != "shell":                          # 现有 shell 早退不变
        return
    ...（现有 12 危险模式 + BLACKLIST/WHITELIST）
```

## Verification

**Commands:**
- `pytest tests/test_safety.py -v` -- expected: 新 `TestBlockedTools` 全绿 + 既有 shell 测试零回归
- `pytest` -- expected: 全量绿（19 内置工具 + MCP + engine 零回归）
- `ruff check src tests` -- expected: 无新增问题
- `mypy src` -- expected: 无新增类型错误
