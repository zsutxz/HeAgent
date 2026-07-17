---
stepsCompleted: ["step-01-requirements-extraction", "step-02-design-epics", "step-03-create-stories", "step-04-final-validation"]
inputDocuments:
  - _bmad-output/mcp-client-v2/brief.md
  - _bmad-output/mcp-client-v2/prd.md
  - _bmad-output/mcp-client-v2/ARCHITECTURE-SPINE.md
cycle: mcp-client-v2
project: HeAgent
---

# HeAgent MCP Client V2 - Epic Breakdown

> 本文档把 MCP Client V2 周期（写操作治理 + Resources/Prompts）的 PRD FR、NFR 与架构承重决策（AD）分解为可实现的 story。FR 编号与 PRD `FR-A*/B*/C*` 对齐；AD 编号与 `ARCHITECTURE-SPINE.md` 对齐。

## Overview

This document provides the complete epic and story breakdown for HeAgent MCP Client V2, decomposing the requirements from the PRD and Architecture requirements into implementable stories.

## Requirements Inventory

### Functional Requirements

> verbatim 自 `prd.md` §4，字母前缀对应 brief P5 结构（A=写操作治理 / B=Resources / C=Prompts）。

- **FR-A1: ToolSchema 携带 annotations** — `ToolSchema` 新增可选字段 `annotations`（默认缺省），承载工具的风险 hint（至少 `readOnlyHint` / `destructiveHint`），不破坏 V1 既有 3 字段（`name`/`description`/`parameters`）映射。
- **FR-A2: mcp_tool_to_schema 透传 annotations** — `mapping.mcp_tool_to_schema` 读取 `tool.annotations` 并填入 `ToolSchema.annotations`；`tool.annotations` 为 `None` 时留保守标记（对齐 FR-A5 fail-safe）。
- **FR-A3: PolicyEngine 按 destructiveHint 触发审批** — `destructiveHint=true` → 产出 `PolicyVerdict(mode=APPROVAL_REQUIRED)`，挡在执行闸门前直到当前 run 授权；授权语义沿用既有 `metadata.approved_tools`（含 `*` / MCP `__mcp__`）。
- **FR-A4: readOnlyHint 放行自动调用** — `readOnlyHint=true` 的工具，在无其他阻断条件时不经审批直接放行；显式策略（`approval_tools`/`approval_mcp_tools`）优先于 annotation（反向不成立）。
- **FR-A5: 缺 annotations → fail-safe 需确认（P4 定稿）** — 工具缺 annotations 时按保守默认视为非只读 → 需确认（`APPROVAL_REQUIRED`），不因 server 未声明而放行潜在 destructive 调用。
- **FR-A6: 治理确定性可单测** — 危险等级判定完全在代码层，存在不调用任何 LLM 的单元测试断言：给定 `(ToolCall, annotations)` → 固定 `PolicyVerdict`。
- **FR-A7: idempotentHint / openWorldHint 暂存不裁决** — 两字段在 `ToolSchema.annotations` 中保留（透传存储），但 V2 `PolicyEngine` 不据此改变裁决（仅 readOnly/destructive 驱动闸门）。
- **FR-B1: list_resources 内置工具** — 提供内置工具 `list_resources`，返回已连 server 暴露的资源清单（URI + 名称 + 描述）；无连接 / 不暴露资源时返回空列表（不抛错）。
- **FR-B2: read_resource 内置工具** — 提供内置工具 `read_resource`，按指定 server + URI 取回资源内容，经 `ToolResult` 桥接进既有循环。（架构 AD-5 收紧：签名 `read_resource(server, uri)`，`server` 必填）
- **FR-B3: on-demand，不自动注入（P1 定稿）** — Resources 不在会话启动 / server 连接成功后自动全量注入 system prompt；只有显式 `read_resource` 请求的 URI 才进上下文。
- **FR-B4: 返回内容同等不可信围栏** — `read_resource` 返回内容经与 `mapping.bridge_result` 同等的注入启发式围栏（DP-4 第二半）标记后透传，不阻断不截断。
- **FR-C1: list_prompts 发现** — 提供 `list_prompts` 发现能力，返回模板清单（每项含 `name`、`description`、参数 schema）；无模板时返回空列表。
- **FR-C2: /mcp-prompt 渲染注入** — CLI 交互模式支持 `/mcp-prompt <server> <name> [key=value ...]`：渲染指定模板作为 user message 注入当前会话；模板不存在 → 显式错误。
- **FR-C3: 模板参数化** — `/mcp-prompt` 支持模板声明的参数（`key=value` 形式），缺必填参数 → 显式错误列出缺失参数。
- **FR-C4: 渲染输出同等不可信** — `get_prompt` 渲染文本经同等围栏标记后注入（与 FR-B4 同构）。

### NonFunctional Requirements

> 自 `prd.md` 各 feature NFR + §7 SM 凝练。

- **NFR-1 安全/诚实立场（写操作治理）** — `Tool.annotations` 是 server 自声明、不可信；恶意/错误 server 可把 `delete_repository` 谎报为 `readOnlyHint=true`。治理闸门仅 defense-in-depth 标记，**非真正安全边界**，须 OS 级沙箱兜底（延续 DP-4）。
- **NFR-2 确定性（写操作治理）** — annotations → `PolicyVerdict` 裁决纯函数化，无 LLM 参与（呼应项目硬约束「确定性逻辑交给代码」）。
- **NFR-3 上下文预算（Resources）** — on-demand 模型确保 resources 不侵蚀上下文窗口（V1 已识别的 R3 不回归）。
- **NFR-4 安全（Resources/Prompts）** — Resources/Prompts 返回内容与 MCP 工具返回**同等不可信**，经同等注入启发式围栏标记后透传。
- **NFR-5 语义重叠披露（Prompts）** — Prompts（注入预设指令）与既有 context-files 自动加载、自学习记忆在「注入预设上下文」上重叠；本周期不试图统一三者，仅补 MCP Prompts 这条腿。
- **NFR-6 零回归护栏（SM-4）** — 既有 V1 MCP 测试 + **19 个**内置工具测试 + 既有测试全绿，覆盖率不低于基线（V2 新增工具自身测试不计入「既有」基线）。
- **NFR-7 不过度审批（SM-C1 counter-metric）** — `readOnlyHint=true` 的工具不应被强制确认；fail-safe 须精准作用于「缺信号」而非「有 readOnly 信号」。

### Additional Requirements

> 自 `ARCHITECTURE-SPINE.md` 承重决策 AD-1~AD-8 + SM，影响实现的硬约束（非新机制，落既有扩展点）。brownfield 扩展，无 starter template。

- **AR-1（AD-1，FR-A1/A2/A3/A4）** — `PolicyEngine.evaluate_tool_call(call, *, context=None, schema=None)` 增可选 kwarg `schema`，读 `schema.annotations` 裁决；`agent/tool_execution.execute_tool_call` 两处 evaluate 调用点（正常路径 + ledger 缓存命中复核）传 schema。`ToolCall`/`RunContext` 结构不变。
- **AR-2（AD-2，FR-A3/A4/A5，SM-1/4/C1）** — fail-safe **仅 MCP 工具**触发：步 0 前置闸门 `schema=None`（V1 内置工具 / 未知工具）→ 跳过注解裁决回既有路径，杜绝 19 内置工具被误伤（SM-4 零回归）。固定优先级（前者短路）：显式策略命中 → destructive → readOnly → fail-safe（MCP 缺 annotations）。
- **AR-3（AD-3，FR-A6，SM-5）** — annotations→verdict 纯函数不触达 provider；单测覆盖 destructive/readOnly/缺省三种 annotations 断言对应 verdict。
- **AR-4（AD-4，FR-B1/B2/C1）** — `MCPClientManager` 增 `self._sessions: dict[str, ClientSession]`（B/C 前置）；session 唯一属主仍是 `_server_loop` task，`_sessions` 是只读查找表；断连 flag-before-pop 先摘键再退 transport；桥接调用见键移除 → 规范化 `ToolError("MCP server '%s' disconnected")`，禁裸 KeyError/None。
- **AR-5（AD-5，FR-B1/B2/B3/B4）** — Resources 走 manager 注册的聚合桥接工具 `mcp__list_resources`/`mcp__read_resource`（`mcp` 聚合 token → `_is_mcp_tool` 识别 → 继承全量 V1 MCP 门控：`block_mcp_tools`/`approval_mcp_tools`/`sandbox_mcp_tools`/`__mcp__`）；自声明 `readOnlyHint=True`；`read_resource(server, uri)` `server` 必填；无 MCP 配置时不注册。
- **AR-6（AD-6，FR-B3/B4/C4）** — 注入围栏提升为 `mapping.py` 公共函数 `guard_content(text) -> str`（`bridge_result`/`mcp__read_resource`/slash 共用单一实现，不复制签名）；Resources 不自动注入；Prompts 渲染文本走 `run_stream` 不绕过消息管道。
- **AR-7（AD-7，FR-C1/C2/C3）** — `_run_chat` REPL 在 `input()` 与 `run_stream()` 之间加最小 slash 分发器；推荐接入 (i) `_mcp_lifecycle` 返回 manager，`_run_chat` 绑定变量经 `as` 取实例进 REPL 作用域；slash 渲染文本先经 `guard_content` 标记再注入；缺必填参数 / 模板不存在 → 显式错误不静默空注入。
- **AR-8（AD-8，SM-6）** — `CLAUDE.md` / `docs/frame.md` 安全声明更新覆盖：写操作治理（annotation 不可信）+ Resources/Prompts 返回同等不可信；须 OS 级沙箱兜底。
- **AR-9（SM-4）** — 零回归护栏覆盖既有 V1 MCP + 19 内置工具测试 + annotations/桥接工具新单测。
- **AR-10（Stack）** — 不新增运行时依赖（`mcp` SDK 已由 V1 引入，>=1.28,<2；`ClientSession` 已暴露 list_resources/read_resource/list_prompts/get_prompt）；Python 3.11+；Pydantic v2。

### UX Design Requirements

本周期**无 UI/UX 表面**——HeAgent 是后端库 + CLI REPL slash（`/mcp-prompt`），无 bmad-ux spine 设计契约。Prompts 的「渲染注入」是 user message 文本注入，非图形 UI。故无 UX 设计需求（UX-DR 留空）。

### FR Coverage Map

> 16 个 FR 全覆盖。字母前缀与 epic 一一对应（FR-A*→Epic A / FR-B*→Epic B / FR-C*→Epic C），保证可追溯。

- **FR-A1**（ToolSchema 携带 annotations）→ Epic A
- **FR-A2**（mcp_tool_to_schema 透传 annotations）→ Epic A
- **FR-A3**（destructiveHint 触发审批）→ Epic A
- **FR-A4**（readOnlyHint 放行 + 显式策略优先）→ Epic A
- **FR-A5**（缺 annotations fail-safe 需确认）→ Epic A
- **FR-A6**（治理确定性可单测）→ Epic A
- **FR-A7**（idempotent/openWorld 暂存不裁决）→ Epic A
- **FR-B1**（list_resources 桥接工具）→ Epic B
- **FR-B2**（read_resource(server, uri) 桥接工具）→ Epic B
- **FR-B3**（on-demand 不自动注入）→ Epic B
- **FR-B4**（返回内容同等不可信围栏）→ Epic B
- **FR-C1**（list_prompts 发现）→ Epic C
- **FR-C2**（/mcp-prompt 渲染注入）→ Epic C
- **FR-C3**（模板参数化 + 缺参数显式错误）→ Epic C
- **FR-C4**（渲染输出同等不可信围栏）→ Epic C
- **SM-6 / AR-8**（安全声明更新）→ 拆进三 epic 各自收尾 story（write-op 治理→A / Resources→B / Prompts→C），每个 epic 自包含其引入的新信任面文档。

## Epic List

### Epic A: 写操作治理 — MCP 工具危险分级的确定性闸门

tan 让 agent 调 MCP 写工具（建 issue / 提 PR / 评论）时，destructive 工具走审批不裸跑，readOnly 工具静默放行，缺 annotations 的工具 fail-safe 需确认——危险等级判定在代码层、不在 LLM 层（纯函数可单测），且既有 19 个内置工具零回归。完成后 V2 的**核心价值**（安全调写工具）即达成，可独立交付。

**FRs covered:** FR-A1, FR-A2, FR-A3, FR-A4, FR-A5, FR-A6, FR-A7
**实现落点:** AD-1（`evaluate_tool_call` +`schema` kwarg）/ AD-2（fail-safe 仅 MCP 工具——步 0 前置闸门 `schema=None` 回既有路径）/ AD-3（确定性纯函数）。改 `types.py`（ToolSchema.annotations 自有模型）+ `tools/mcp/mapping.py`（`mcp_tool_to_schema` 透传）+ `engine/policy.py`（注解裁决步）+ `agent/tool_execution.py`（两处 evaluate 调用点传 schema）。
**独立性:** ✅ 无前置依赖。**无 B/C 依赖**——Epic A 完整自包含。

### Epic B: Resources on-demand 发现与读取

tan 问 agent「这个 server 有哪些资源」，agent 调 `mcp__list_resources` 拿清单（server-tagged），再按需 `mcp__read_resource(server, uri)` 取回指定 URI 内容塞进上下文——全程不自动全量注入（V1 已识别的 R3 上下文侵蚀不回归），返回内容与工具返回同等不可信、经公共注入围栏标记透传。

**FRs covered:** FR-B1, FR-B2, FR-B3, FR-B4
**实现落点:** AR-4（`MCPClientManager._sessions` 映射——B/C 前置，flag-before-pop 断连语义）+ AR-5（`mcp__` 聚合桥接工具，自声明 `readOnlyHint=True`，继承全量 V1 MCP 门控）+ AR-6（注入围栏提升为 `mapping.guard_content` 公共函数，`bridge_result` 改调用它）。改 `tools/mcp/manager.py`（_sessions + 注册桥接工具）+ `tools/mcp/mapping.py`（guard_content 提取）。MCP 活跃时注册、无 MCP 配置时不注册。
**独立性:** ✅ 自引入 `_sessions` 与 `guard_content`。完成后 Resources 消费面可用；Epic C 在其上构建。

### Epic C: Prompts CLI slash 渲染注入

tan 在 CLI 交互模式敲 `/mcp-prompt <server> <name> [key=value ...]`，CLI 查 `list_prompts` 找到模板、渲染参数、把结果作为 user message 注入当前会话——缺必填参数 / 模板不存在显式报错（不静默空注入），渲染输出同等不可信经公共围栏标记。最弱一条腿（与既有 context-files / 自学习记忆语义重叠），**预算吃紧时首选 defer 候选**（A+B 已达成核心价值）。

**FRs covered:** FR-C1, FR-C2, FR-C3, FR-C4
**实现落点:** AR-7（`_run_chat` REPL 在 `input()` 与 `run_stream()` 间加最小 slash 分发器；推荐接入 (i) `_mcp_lifecycle` 返回 manager，`_run_chat` 绑定变量经 `as` 取实例进 REPL 作用域）+ 复用 AR-4 `_sessions` + AR-6 `guard_content`。改 `cli.py`（slash 分发器 + /mcp-prompt）+ `tools/mcp/manager.py`（prompts 读取入口）。
**独立性:** ✅ 依赖 Epic B 引入的 `_sessions` + `guard_content`（不重复引入）。完成后全三原语消费面补齐。

---

## Epic A: 写操作治理 — MCP 工具危险分级的确定性闸门

给 V1 既有 `call_tool` 路径加一道确定性危险分级闸门：MCP `Tool.annotations` 透传进 `ToolSchema` → `PolicyEngine` 消费（destructive 审批 / readOnly 放行 / 缺省 fail-safe）。判定在代码层、不在 LLM 层，且既有 19 个内置工具零回归。Realizes UJ-1。依赖：无（核心价值，可独立交付）。

### Story A.1: annotations 数据管线（ToolAnnotations 模型 + ToolSchema.annotations + mapping 透传）

As a HeAgent 开发者,
I want ToolSchema 携带 MCP Tool 的 annotations 风险 hint 并经 mapping 自动透传,
So that 下游 PolicyEngine 能从数据而非 LLM 输出读出工具危险等级。

**Acceptance Criteria:**

**Given** `types.py` 中新增 HeAgent 自有 Pydantic 模型 `ToolAnnotations`（字段 `readOnlyHint`/`destructiveHint`/`idempotentHint`/`openWorldHint`，均默认 False；**不透传** `mcp.types` 第 5 字段 `title`）
**When** 构造 `ToolSchema(name=..., description=..., parameters=...)` 不传 `annotations`
**Then** `ToolSchema.annotations` 为 `None`（缺省），V1 所有既有 `ToolSchema` 构造点零改动通过（FR-A1）
**And** `ToolAnnotations` 不依赖 `mcp.types`（types 层不上浮 mcp 依赖，保 DAG）

**Given** 一个 MCP `Tool` 其 `tool.annotations.destructiveHint=True`
**When** `mapping.mcp_tool_to_schema(tool)` 映射
**Then** 产出的 `ToolSchema.annotations.destructiveHint` 为 True（`readOnlyHint=True` 同理）（FR-A2）
**And** `tool.annotations` 为 `None` 时，`ToolSchema.annotations` 为 `None`（缺省保守标记，交由 FR-A5 fail-safe 消费）

**Given** 一个 MCP `Tool` 声明了 `idempotentHint`/`openWorldHint`
**When** 经 mapping 透传
**Then** 两字段保留在 `ToolSchema.annotations` 中（透传存储，供 LLM 参考）（FR-A7 存储）

### Story A.2: PolicyEngine 注解裁决闸门（schema kwarg + 固定优先级 + fail-safe 仅 MCP）

As a HeAgent 操作者,
I want destructive MCP 工具调用走审批、readOnly 工具静默放行、缺 annotations 的 MCP 工具 fail-safe 需确认,
So that 写操作不裸跑（防 agent 误删/误建），只读操作不被无脑确认打扰，且危险判定在代码层。

**Acceptance Criteria:**

**Given** `PolicyEngine.evaluate_tool_call` 签名为 `evaluate_tool_call(call, *, context=None, schema=None)`
**When** `agent/tool_execution.execute_tool_call` 在裁决前 `schema = loop.registry.get_schema(call.name)` 并传入
**Then** 两个 evaluate 调用点（正常路径 + ledger 缓存命中复核）都传 schema kwarg（AD-1）
**And** `ToolCall`/`RunContext` 结构不变

**Given** 一个 `destructiveHint=true` 的 MCP 工具调用且未授权
**When** PolicyEngine 裁决
**Then** 返回 `PolicyVerdict(mode=APPROVAL_REQUIRED)`，挡在执行闸门前（FR-A3）
**And** 授权后（`metadata.approved_tools` 含该工具名 / `*` / `__mcp__`）放行至后续裁决

**Given** 一个 `readOnlyHint=true` 的 MCP 工具调用且无其他阻断条件
**When** PolicyEngine 裁决
**Then** 返回非 `APPROVAL_REQUIRED`（落 DIRECT / 既有沙箱裁决），不因「是 MCP 工具」强制确认（FR-A4）

**Given** 显式策略 `approval_mcp_tools=True`（或 `approval_tools` 命中）而工具声明 `readOnlyHint=true`
**When** PolicyEngine 裁决
**Then** 显式策略优先 → `APPROVAL_REQUIRED`（覆盖 server 的 readOnly 声明，允许用户强制「全 MCP 需确认」）（FR-A4）

**Given** 一个 MCP 工具缺 annotations（`schema.annotations` 为 None）
**When** PolicyEngine 裁决
**Then** 按 fail-safe 返回 `APPROVAL_REQUIRED`（不因 server 未声明而放行潜在 destructive）（FR-A5）

**Given** 一个 V1 内置工具调用（`schema=None`）
**When** PolicyEngine 裁决
**Then** 步 0 前置闸门触发：跳过注解裁决，回到既有路径（DIRECT / 既有 `approval_tools`·`sandbox_tools` 列表），**绝不**对内置工具触发 fail-safe（AD-2，SM-4 零回归生命线）

**Given** 一个 MCP 工具声明 `idempotentHint=true` 或 `openWorldHint=true`
**When** PolicyEngine 裁决
**Then** verdict 不因此改变（两 hint 不进裁决，仅 readOnly/destructive 驱动闸门）（FR-A7 不裁决）

### Story A.3: 零回归护栏 + 治理确定性验证

As a HeAgent 开发者,
I want annotations→verdict 路径存在不触达任何 LLM 的单元测试，且既有 V1 MCP + 19 个内置工具测试全绿,
So that 治理确定性可证（硬约束「确定性逻辑交给代码」），且 V2 不破坏既有行为（SM-4）。

**Acceptance Criteria:**

**Given** 一个不依赖任何 provider 的单元测试
**When** 构造 destructive / readOnly / 缺省三种 annotations 调用 PolicyEngine
**Then** 断言 verdict 分别为 `APPROVAL_REQUIRED` / 非 approval / `APPROVAL_REQUIRED`，全程无 LLM 调用（FR-A6, AD-3, SM-5）

**Given** 既有 19 个内置工具测试套件 + V1 MCP 测试套件
**When** 运行全量测试
**Then** 全绿，覆盖率不低于基线（SM-4, AR-9）

**Given** 一个针对步 0 前置闸门的对抗测试（内置工具 `schema=None`）
**When** 断言其 verdict
**Then** 不为 `APPROVAL_REQUIRED`（除非被既有显式 `approval_tools` 命中），证明 fail-safe 未误伤内置工具（AD-2）

### Story A.4: 安全声明更新（写操作治理）

As a HeAgent 操作者,
I want CLAUDE.md / docs/frame.md 的安全声明覆盖写操作治理的诚实立场,
So that 不制造「接了 annotations 治理就更安全」的假象——annotation 不可信，须 OS 级沙箱兜底。

**Acceptance Criteria:**

**Given** CLAUDE.md 安全声明章节
**When** 审查写操作治理部分
**Then** 明确陈述：`Tool.annotations` 是 server 自声明、不可信（恶意 server 可谎报 `readOnlyHint`）；治理闸门是 defense-in-depth 标记，非真正安全边界；须 OS 级沙箱兜底（AD-8, SM-6）
**And** `docs/frame.md` 同步更新（章节五已知缺口 / 安全声明）

---

## Epic B: Resources on-demand 发现与读取

把 MCP Resources 原语经 manager 注册的聚合桥接工具接入既有循环：`mcp__list_resources` 发现、`mcp__read_resource(server, uri)` 按需读取。不自动全量注入（R3 不回归），返回内容同等不可信围栏。Realizes UJ-2。依赖：自引入 `_sessions` + `guard_content`（B/C 共享前置）。

### Story B.1: MCPClientManager._sessions 映射（B/C 前置 + flag-before-pop 断连语义）

As a HeAgent 开发者,
I want MCPClientManager 持有 server→session 的只读查找表,
So that Resources/Prompts 桥接代码能经统一映射取 session，且断连有规范化错误语义。

**Acceptance Criteria:**

**Given** `MCPClientManager` 新增 `self._sessions: dict[str, ClientSession]`
**When** `_server_loop` 中 `session.initialize()` 成功
**Then** 把 session 登记进 `_sessions[normalized_name]`（AD-4）

**Given** server 断连或 `__aexit__` 关停
**When** `_unregister_server` / `_unregister_all` 执行
**Then** 按 flag-before-pop 顺序：先从 `_sessions` 移除该键，再让 transport context 退出（AD-4）
**And** session 的唯一属主始终是其 `_server_loop` task（负责 enter/exit transport），`_sessions` 是只读查找表非第二属主

**Given** 一个 in-flight 桥接调用（read_resource/list_prompts）观察其 server 键已被移除（断连竞态）
**When** 桥接代码取 session
**Then** 抛规范化 `ToolError("MCP server '%s' disconnected")`，由 `_execute_one` 转 `is_error=True` 进 LLM 上下文（与既有 MCP 工具断连语义一致）
**And** 不得裸抛 `KeyError`/`AttributeError`/None 访问（AD-4）

### Story B.2: mcp__list_resources 聚合桥接工具（继承 V1 门控 + on-demand 不注入）

As a HeAgent 操作者,
I want 调用 mcp__list_resources 列出已连 server 暴露的资源清单,
So that agent 能发现可寻址资源而不被自动全量塞进上下文。

**Acceptance Criteria:**

**Given** MCP 活跃（有 server 连接）
**When** MCPClientManager 注册聚合桥接工具 `mcp__list_resources`
**Then** 其命名含 `mcp__` 聚合 token（`mcp` 作聚合 server token），被 `_is_mcp_tool` 识别为 MCP 工具，继承全量 V1 MCP 门控（`block_mcp_tools`/`approval_mcp_tools`/`sandbox_mcp_tools`/`__mcp__` 授权）（AR-5）
**And** 自声明 `readOnlyHint=True`（默认不审批，用户可 `approval_mcp_tools=True` 强制确认覆盖）

**Given** 一个已连 server 暴露多个资源
**When** 调用 `mcp__list_resources()`
**Then** 返回 server-tagged 列表，每项含 `{server, uri, name, description}`（FR-B1）

**Given** 无任何 server 连接或 server 不暴露资源
**When** 调用 `mcp__list_resources()`
**Then** 返回空列表，不抛错（FR-B1）

**Given** 无 MCP 配置（纯内置模式）
**When** manager 初始化
**Then** 不注册 `mcp__list_resources`/`mcp__read_resource`（与 V1 一致）（AR-5）

**Given** 会话启动 / server 连接成功后
**When** 检查 system prompt
**Then** 不含各 server 全量 resources 文本（on-demand，FR-B3）；资源内容仅在被 `mcp__read_resource` 调用后才进上下文

### Story B.3: mcp__read_resource 桥接工具 + guard_content 公共围栏提取

As a HeAgent 操作者,
I want 调用 mcp__read_resource(server, uri) 取回指定资源内容并经注入围栏标记,
So that agent 能按需读取资源进上下文，且返回内容与工具返回同等不可信。

**Acceptance Criteria:**

**Given** MCP 活跃且 server 暴露某 URI 资源
**When** 调用 `mcp__read_resource(server="github", uri="repo://x/config")`
**Then** 经 `self._sessions[server]` 取回该 URI 资源内容，经 `ToolResult` 桥接进既有循环（FR-B2）

**Given** read_resource 的 LLM 可见签名
**When** 审查参数
**Then** 钉死 `read_resource(server: str, uri: str)`，`server` 必填（消解跨 server 同 URI 歧义，AD-5 收紧 PRD FR-B2）

**Given** 指定 server 不在 `_sessions` 或 URI 不存在
**When** 调用 read_resource
**Then** 抛 `ToolError`（显式失败，不静默空返）（FR-B2, AR-5）

**Given** `mapping.py` 中既有模块私有注入围栏（`_guard_injection`/`_INJECTION_PATTERNS`）
**When** 提升为公共函数 `guard_content(text) -> str`
**Then** `bridge_result`、`mcp__read_resource`、（后续）slash 分发器三者调用同一公共实现，单一签名不复制（AR-6）

**Given** read_resource 返回内容命中注入启发式签名
**When** 桥接进上下文
**Then** 加 warning 标记后透传（不阻断、不截断），与 MCP 工具返回同等不可信（FR-B4, AD-6）
**And** `bridge_result` 改调用 `guard_content` 后，既有 MCP 工具返回围栏行为不变（回归测试通过）

### Story B.4: 安全声明更新（Resources 同等不可信）

As a HeAgent 操作者,
I want 安全声明覆盖 Resources 返回内容的同等不可信立场,
So that 不误以为 read_resource 的返回比工具返回更可信。

**Acceptance Criteria:**

**Given** CLAUDE.md MCP 特定风险章节
**When** 审查 Resources 部分
**Then** 明确陈述：`mcp__read_resource` 返回内容（含远端响应）经启发式围栏标记后透传，与内置工具返回同等不可信，须 OS 级沙箱兜底（AD-8, SM-6）
**And** `docs/frame.md` 同步

---

## Epic C: Prompts CLI slash 渲染注入

把 MCP Prompts 原语（user-controlled 参数化模板）经最小 CLI slash 分发器 `/mcp-prompt <server> <name> [key=value ...]` 接入：发现（list_prompts）+ 渲染（get_prompt）→ 经围栏标记作为 user message 注入。Realizes UJ-3。最弱腿，预算吃紧 defer 候选。依赖：Epic B 的 `_sessions` + `guard_content`。

### Story C.1: manager prompts 读取入口（经 _sessions）

As a HeAgent 开发者,
I want MCPClientManager 暴露 list_prompts/get_prompt 读取能力（非 LLM 工具）,
So that CLI slash 分发器能发现并渲染 server 提供的参数化模板。

**Acceptance Criteria:**

**Given** MCPClientManager 持有 `_sessions`（B.1 引入）
**When** 调用 manager 的 `list_prompts(server)` / `get_prompt(server, name, args)`
**Then** 经 `self._sessions[server]` 调 ClientSession 的 `list_prompts`/`get_prompt`（AR-7, FR-C1）
**And** prompts 读取不注册为 LLM 工具（Prompts 是 user-controlled，不该 LLM 自主调）

**Given** 调用 `list_prompts(server)`
**When** server 有模板
**Then** 返回模板清单，每项含 `name`、`description`、参数 schema（FR-C1）

**Given** server 无模板
**When** 调用 list_prompts
**Then** 返回空列表，不抛错（FR-C1）

### Story C.2: slash 分发器 + /mcp-prompt 渲染注入（含参数化）

As a HeAgent 操作者,
I want 在 CLI 敲 /mcp-prompt 渲染 server 模板并注入会话,
So that 一键复用参数化模板（如代码审查），缺参数或模板不存在时显式报错。

**Acceptance Criteria:**

**Given** `_run_chat` REPL 当前以 `input()` 直送 `run_stream()`
**When** 在 `input()` 与 `run_stream()` 间加最小 slash 分发器
**Then** `user_input.startswith("/")` → 查命令表分发，否则原样送 run_stream（AR-7）

**Given** `_mcp_lifecycle` 返回 manager（接入方式 (i)），`_run_chat` 以 `mgr = _mcp_lifecycle(...)` 绑定变量经 `as` 取实例进 REPL 作用域
**When** 用户敲 `/mcp-prompt github code_review file=loop.py`
**Then** 分发器持 `mgr` 调 `get_prompt` 渲染模板，渲染文本作为 user message 走 `run_stream`（复用既有循环，非旁路）（FR-C2, AD-7）

**Given** 模板声明必填参数 `file`
**When** 调用未提供该参数
**Then** 报错列出缺失参数，不注入空内容（FR-C3）

**Given** 指定模板名不存在
**When** 调用 /mcp-prompt
**Then** 显式错误回显到 REPL，不静默注入空内容，不中断循环（FR-C2, AD-7）

**Given** /mcp-prompt 支持 `key=value` 参数
**When** 调用带完整参数
**Then** 模板正常渲染注入（FR-C3）

### Story C.3: 渲染输出同等不可信围栏 + 安全声明更新

As a HeAgent 操作者,
I want /mcp-prompt 渲染输出经注入围栏标记后再注入,
So that server 渲染的模板文本与工具返回同等不可信，且安全声明披露 Prompts 这条腿。

**Acceptance Criteria:**

**Given** get_prompt 渲染出的文本
**When** slash 分发器注入前
**Then** 先经公共 `guard_content` 标记（B.3 提取），命中注入启发式加 warning 后再作 user message 注入（FR-C4, AD-6/7）

**Given** CLAUDE.md / docs/frame.md 安全声明
**When** 审查 Prompts 部分
**Then** 覆盖：Prompts 渲染输出同等不可信 + 语义重叠披露（Prompts 与 context-files/自学习记忆在「注入预设上下文」重叠，本周期不统一三者）（SM-6, NFR-5, AD-8）

---

## FR → Story 覆盖核对

| FR | Story | 说明 |
| --- | --- | --- |
| FR-A1 | A.1 | ToolSchema.annotations 模型 |
| FR-A2 | A.1 | mcp_tool_to_schema 透传 |
| FR-A3 | A.2 | destructive→审批 |
| FR-A4 | A.2 | readOnly 放行 + 显式策略优先 |
| FR-A5 | A.2 | 缺 annotations fail-safe |
| FR-A6 | A.3（+A.2 测试） | 确定性可单测 |
| FR-A7 | A.1（存储）+ A.2（不裁决） | idempotent/openWorld 透传不裁决 |
| FR-B1 | B.2 | list_resources |
| FR-B2 | B.3 | read_resource(server, uri) |
| FR-B3 | B.2 | on-demand 不注入 |
| FR-B4 | B.3 | 返回同等不可信围栏 |
| FR-C1 | C.1 | list_prompts 发现 |
| FR-C2 | C.2 | /mcp-prompt 渲染注入 |
| FR-C3 | C.2 | 模板参数化 |
| FR-C4 | C.3 | 渲染输出同等不可信 |

16/16 FR 全覆盖。
