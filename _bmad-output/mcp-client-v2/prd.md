---
title: "HeAgent MCP Client 集成 V2 — 写操作治理 + Resources/Prompts 原语"
status: final
cycle: mcp-client-v2
preceded_by: _bmad-output/mcp-client/（V1，Tools-only，已交付）
created: 2026-07-17
updated: 2026-07-17
---

# PRD: HeAgent MCP Client 集成 V2 — 写操作治理 + Resources/Prompts 原语

> **本文档的 FR 编号（`FR-A*` / `FR-B*` / `FR-C*`）独立于 MCP V1（`_bmad-output/mcp-client/`，FR-1~11）
> 与主线 baseline（FR-1~24）。** 下游 epics/stories 以本 PRD 的 `FR-*` 为准；字母前缀对应 brief
> 的 P5 结构（A=写操作治理 / B=Resources / C=Prompts）。

## 0. Document Purpose

本 PRD 面向**架构（`bmad-architecture`）与 epics/stories（`bmad-create-epics-and-stories`）两个下游工作流**，
以及作者 tan 自身的实现参照。它**建立在两份既有产物之上、不重复其内容**：

- **`brief.md`**（本周期，`status: draft`）：产品愿景、三处缺口、方案、受众、范围、技术约束、P3/P5 决策——
  本 PRD 的 §1/§2/§5/§6 是其结构化展开，P1/P2/P4 是本 PRD 的定稿对象。
- **V1 交付物**（`_bmad-output/mcp-client/` + `src/heagent/tools/mcp/` + `engine/policy.py`）：
  本 PRD 的所有 FR 落点均基于 V1 既有扩展点（`mcp_tool_to_schema` / `PolicyEngine` / `MCPClientManager`），
  **不重写 V1、不破坏既有不变量**。

结构约定：§3 术语表为全文唯一词汇源，FR/UJ/SM 一律 verbatim 引用；§4 每个 FR 带 testable Consequences；
凡作者未直接确认的推断打 `[ASSUMPTION: …]` 并汇总到 §9。

## 1. Vision

V1 让 HeAgent 接上了 MCP 的 **Tools 原语**——能像调内置工具一样调外部工具，GitHub 只读验收（列 issue / 搜代码）
已跑通，安全侧落地了 DP-4 两半（执行前工具名黑名单 + 返回内容注入启发式围栏）。但 V1 刻意冻结了三处缺口，
正是 V2 要补的：

1. **写操作无治理**——`call_tool` 闭包对只读 `search_code` 与 destructive `delete_repository` 一视同仁，
   LLM 选了就执行，无审批、无危险分级。这与 HeAgent「确定性逻辑交给代码、不交给概率模型」的硬约束直接冲突：
   「这个调用会不会造成不可逆副作用」不该由 LLM 判断。
2. **Resources / Prompts 两原语零消费**——server 暴露的可寻址资源（文件 / 配置 / 运行时状态）与可复用
   参数化模板（「代码审查」「生成 commit message」）HeAgent 完全拿不到。

V2 把这三处补齐，落在 V1 既有扩展点上。落点不是新机制，是**给既有 `call_tool` 路径加一道确定性闸门**，
并把 MCP 的另两个原语以最小侵入方式接进既有循环。一句话愿景：**让 HeAgent 从「能调只读 MCP 工具」
升级为「能安全调写工具 + 消费全部 MCP 原语」，且危险等级的判定始终在代码层、不在 LLM 层。**

安全立场延续 V1/DP-4：治理闸门 **非真正安全边界**——Tool annotations 是 server 自声明（恶意/错误 server
可谎报 `readOnlyHint`），与 DP-4 围栏同构，须 OS 级沙箱兜底。本 PRD 不制造「接了写操作更安全」的假象。

## 2. Target User

### 2.1 Jobs To Be Done

- **功能**：让 agent 不只能读 GitHub，还能**建 issue / 提 PR / 评论**，且 destructive 操作有审批闸门不裸跑。
- **功能**：让 agent 能按需取回 MCP server 暴露的可寻址资源（`read_resource`），而非零消费。
- **功能**：让我能从 CLI 一键渲染并注入 server 提供的参数化 prompt 模板（`/mcp-prompt`）。
- **情境**：自用提效——我既是这个 agent 的作者、也是它的主操作者；写操作的不可逆风险由我本人承担，
  故「destructive 前确认」对我有真实价值（防止 agent 误删 / 误建）。
- **情感**：我不想在「无脑确认每一个写操作」（吵）与「全部放行」（危险）之间二选一——我要的是
  **按工具自声明的危险等级智能放行/拦截**，让只读操作静默、destructive 操作显式确认。

### 2.2 Non-Users (V2)

- 需要 **OAuth 2.1 完整流**的企业远程 server 用户（继承 V1）。
- 需要 **MCP Registry / 目录**集成的用户（继承 V1）。
- 把 HeAgent 当 **MCP server** 暴露出去的人（继承 V1，V2 仍不做）。
- 需要在沙箱外裸跑 destructive MCP 工具、且信任 server 声明的人——立场冲突，非受众。

### 2.3 Key User Journeys

> 形态：dev tool / single-operator，UJ 取 light-to-medium。每个 UJ 锚定一个 FR 簇。

- **UJ-1. tan 让 agent 在沙箱 repo 建一个 issue，destructive 工具走审批。**
  tan 配好 GitHub MCP server，对 agent 说「在这个 repo 建一个 issue 标题 X 内容 Y」。agent 选调
  `github__create_issue`（该 server 在其 `Tool.annotations` 上声明了 `destructiveHint=true`）。
  `PolicyEngine` 读到 destructive annotation → 产出 `APPROVAL_REQUIRED` verdict → 执行被挡在闸门前，
  tan 确认授权 → 重放执行 → issue 建成。**Climax**：destructive 调用从不裸跑，确认前 0 副作用。
  Realizes FR-A3, FR-A5。

- **UJ-2. tan 问 agent「这个 server 有哪些资源」，agent on-demand 取回指定 URI。**
  agent 调内置工具 `list_resources` 拿到 server 暴露的资源清单（URI + 描述），再按需调 `read_resource`
  取回指定 URI 的内容塞进上下文。**全程不自动全量注入**——只有 tan 明确指向的 URI 才进上下文。
  Realizes FR-B1, FR-B2, FR-B3。

- **UJ-3. tan 用 `/mcp-prompt` 一键渲染代码审查模板。**
  tan 在 CLI 交互模式敲 `/mcp-prompt github code_review file=loop.py`。CLI 查 `list_prompts` 找到模板、
  渲染参数、把结果作为 user message 注入当前会话，agent 据此执行审查。Realizes FR-C1, FR-C2, FR-C3。

## 3. Glossary

> 下游工作流与全文必须 verbatim 使用以下术语，禁止引入同义词。

- **MCP 三原语** — Model Context Protocol 的三类 server 能力：**Tools**（model-controlled，LLM 自主调）、
  **Resources**（application-controlled，宿主决定注入、URI 寻址、幂等无副作用）、**Prompts**
  （user-controlled，用户触发的可复用参数化模板）。V1 仅消费 Tools；V2 补 Resources + Prompts。
- **Tool Annotations** — MCP（2026-03 引入）的 server 端工具风险词汇，位于 `Tool.annotations`，含四个 hint：
  `readOnlyHint` / `destructiveHint` / `idempotentHint` / `openWorldHint`。**server 自声明、不可信**
  （恶意/错误 server 可谎报）。V2 主消费 `readOnlyHint` 与 `destructiveHint`。
- **写操作治理** — 把 Tool Annotations 透传进 `ToolSchema.annotations` → 喂 `PolicyEngine`：`destructiveHint=true`
  触发审批，`readOnlyHint=true` 放行，缺省 fail-safe。确定性裁决、不交给 LLM。
- **PolicyVerdict** — `engine/policy.py` 中 `PolicyEngine.evaluate_tool_call` 的裁决产物，`mode` ∈
  {`DIRECT`, `APPROVAL_REQUIRED`, `SANDBOX_REQUIRED`, `BLOCKED`}。V1 已落地。
- **fail-safe 默认（P4）** — 当 Tool 缺 `annotations` 或 annotations 不可信时，按保守默认视为**非只读 → 需确认**，
  不因 server 未声明而放行 destructive。
- **on-demand（P1）** — Resources 的消费模型：不自动全量注入上下文，仅当 LLM/用户显式请求指定 URI 时才读取
  （规避 V1 已识别的 R3 上下文侵蚀）。
- **namespace** — MCP 工具的 LLM 可见名为 `<server>__<tool>`（双下划线，见 `mapping.normalize_server_name`）；
  `PolicyEngine._is_mcp_tool` 依此判定。
- **DP-4 围栏** — V1 落地的两半防御：执行前工具名黑名单（第一半）+ 返回内容 prompt-injection 启发式标记
  （第二半，`mapping.bridge_result`，标记透传、不阻断）。**非真正安全边界**。V2 的 Resources/Prompts 返回
  内容须复用同等围栏。
- **destructive 工具** — 其 `Tool.annotations.destructiveHint=true` 的工具（或 fail-safe 下缺 annotations 的工具）。

## 4. Features

### 4.1 写操作治理（annotations → PolicyEngine）〔Epic A，最先交付〕

**Description:** 给 V1 既有 `call_tool` 路径加一道确定性危险分级闸门。MCP（2026-03）的 `Tool.annotations`
是写操作治理的天然信号源：server 在每个工具上声明其风险等级。本 feature 把这条信号透传进 HeAgent 的
`ToolSchema`，再由既有 `PolicyEngine` 消费——`destructiveHint=true` → `APPROVAL_REQUIRED`，`readOnlyHint=true`
→ 放行自动调用，缺 annotations → fail-safe 视为需确认。**判定在代码层、不在 LLM 层**——「这个调用危不危险」
由确定性裁决给出（单测可证，见 FR-A6）。Realizes UJ-1。

立场：Tool annotations 是 server 自声明、不可信；治理闸门与 DP-4 围栏同构，**非真正安全边界**，须 OS 级沙箱兜底。

**Functional Requirements:**

#### FR-A1: ToolSchema 携带 annotations

`ToolSchema` 新增可选字段 `annotations`（默认缺省），承载工具的风险 hint（至少 `readOnlyHint` /
`destructiveHint`），不破坏 V1 既有 3 字段（`name`/`description`/`parameters`）映射。

**Consequences (testable):**
- 构造 `ToolSchema(...)` 不传 `annotations` 时，该字段为缺省默认值；V1 所有既有 `ToolSchema` 构造点零改动通过。
- `annotations` 字段类型为 HeAgent 自有 Pydantic 模型（`[ASSUMPTION: 不直接依赖 `mcp.types.ToolAnnotations`
  进 `types.py`，避免 `types` 层上浮 mcp 依赖——见 §8 OQ-2]`），字段集合覆盖四个 hint。

**Out of Scope:** 内置（非 MCP）工具的 annotations——V2 仅透传 MCP 工具 annotations；内置工具的危险分级
仍由既有 `approval_tools`/`sandbox_tools` 显式列表管。

#### FR-A2: mcp_tool_to_schema 透传 annotations

`mapping.mcp_tool_to_schema` 读取 `tool.annotations` 并填入 `ToolSchema.annotations`；`tool.annotations` 为 `None` 时留**保守标记**（对齐 FR-A5 fail-safe 语义，由下游按需确认裁决）。

**Consequences:**
- 给定一个 `tool.annotations.destructiveHint=True` 的 MCP `Tool`，映射出的 `ToolSchema.annotations`
  对应字段为真；`readOnlyHint=True` 同理。
- `tool.annotations` 为 `None` 时，`ToolSchema.annotations` 为缺省（由 FR-A5 fail-safe 消费）。

#### FR-A3: PolicyEngine 按 destructiveHint 触发审批

`PolicyEngine` 在裁决时读取目标工具的 annotations：`destructiveHint=true` → 产出
`PolicyVerdict(mode=APPROVAL_REQUIRED)`，挡在执行闸门前直到当前 run 授权。

**Consequences:**
- `PolicyEngine` 对一个 `destructiveHint=true` 的 MCP 工具调用，在未授权时返回 `mode=APPROVAL_REQUIRED`；
  授权后（`metadata.approved_tools` 含该工具 / `*` / `__mcp__`）放行至后续裁决。
- 该路径**不依赖 LLM 输出**：纯函数裁决，输入 `(ToolCall, annotations, context)` → 输出 `PolicyVerdict`。

**Out of Scope:** `openWorldHint`（连外部世界/网络）的裁决——V2 不据此自动判定（见 FR-A7）。

#### FR-A4: readOnlyHint 放行自动调用

`readOnlyHint=true` 的工具，在无其他阻断条件（黑名单/路径围栏等）时，不经审批直接放行（`DIRECT` 或既有
沙箱裁决），不因「是 MCP 工具」就强制确认。

**Consequences:**
- `readOnlyHint=true` 且不在任何阻断名单的工具 → 非 `APPROVAL_REQUIRED`。
- 与既有 `approval_mcp_tools`（全局 MCP 审批开关）的关系：**显式策略优先于 annotation**——显式
  `approval_tools` / `approval_mcp_tools` 命中即 `APPROVAL_REQUIRED`，覆盖 server 的 `readOnlyHint`
  声明（允许用户强制「所有 MCP 工具都要确认」）；反向不成立（annotation 不覆盖显式阻断/审批）。

#### FR-A5: 缺 annotations → fail-safe 需确认（P4 定稿）

当工具**缺 `annotations`**（或 annotations 字段不可信/无法判定）时，按保守默认视为**非只读 → 需确认**
（`APPROVAL_REQUIRED`），不因 server 未声明而放行潜在 destructive 调用。

**Consequences:**
- 一个未声明任何 annotation 的 MCP 工具调用 → `APPROVAL_REQUIRED`（不是 `DIRECT`）。
- 一个 `readOnlyHint=true` 的工具显式放行——fail-safe 仅作用于「缺信号」而非「有 readOnly 信号」。

> **P4 定稿**：fail-safe（缺 annotations → 需确认）而非放行——brief 的推荐提案，经 review 确认。
> 保守度取舍的备选增强（已知只读模式工具名白名单 / per-server 关闭 fail-safe）列为 V3 增强项，见 §8 OQ-1。

#### FR-A6: 治理确定性可单测

写操作治理的危险等级判定**完全在代码层**，存在一个不调用任何 LLM 的单元测试即可断言：
给定 `(ToolCall, annotations)` → 固定 `PolicyVerdict`。

**Consequences:**
- 存在单测：构造 destructive / readOnly / 缺省三种 annotations，断言对应 verdict 分别为
  `APPROVAL_REQUIRED` / 非 approval / `APPROVAL_REQUIRED`，全程无 LLM 调用。

#### FR-A7: idempotentHint / openWorldHint 暂存不裁决

`idempotentHint` 与 `openWorldHint` 在 `ToolSchema.annotations` 中**保留**（透传存储），但 V2 的
`PolicyEngine` **不据此改变裁决**（仅 `readOnly`/`destructive` 驱动闸门）。

**Consequences:**
- `idempotentHint=true` 不改变 verdict（既不额外放行也不额外审批）。
- 这两个 hint 对 LLM 可见（随 schema/描述透传），供其参考，但不进入确定性闸门。

**Feature-specific NFRs:**
- **安全/诚实立场**：`Tool.annotations` 是 server 自声明、不可信；恶意 server 可把 `delete_repository`
  谎报为 `readOnlyHint=true`。本闸门是 defense-in-depth 标记，非真正边界。须 OS 级沙箱兜底（见 §安全约束）。
- **确定性**：裁决纯函数化，无 LLM 参与（呼应硬约束「确定性逻辑交给代码」）。

**Notes:**
- `[NOTE FOR PM]`：接入点实现（`PolicyEngine.evaluate_tool_call` 当前只拿 `ToolCall`、不拿 `ToolSchema`，
  怎么拿到 annotations）是架构决策，不在本 PRD 锁死——候选见 §8 OQ-2。

### 4.2 Resources 消费（on-demand）〔Epic B〕

**Description:** 暴露 MCP 的 Resources 原语（`list_resources` / `read_resource`）为**内置工具**，
LLM 按需取指定 URI 的资源，**不自动全量注入上下文**（on-demand，规避 V1 已识别的 R3 上下文侵蚀）。
Resources 是 application-controlled 原语——URI 寻址、幂等无副作用、可订阅；V2 仅做发现 + on-demand 读取。
Realizes UJ-2。

**Functional Requirements:**

#### FR-B1: list_resources 内置工具

提供内置工具 `list_resources`（或 namespaced 等价物），返回已连 server 暴露的资源清单（URI + 名称 + 描述）。

**Consequences:**
- 调用 `list_resources` 返回一个可序列化的资源列表（每项含 `uri`、`name`、`description`）。
- 无任何 server 连接或 server 不暴露资源时，返回空列表（不抛错）。

#### FR-B2: read_resource 内置工具

提供内置工具 `read_resource`，按指定 server + URI 取回资源内容，经 `ToolResult` 桥接进既有循环。

**Consequences:**
- 调用 `read_resource(uri=...)` 返回该 URI 的资源内容（文本；非文本资源的降级表示见 Consequence 3）。
- 指定 URI 不存在 → `ToolError`（显式失败，不静默空返）。
- `[ASSUMPTION: 非文本资源（如二进制 blob resource）V1 `call_result_to_text` 已有降级（`[resource: uri]`），
  V2 沿用 text-first 降级，非文本内容以占位表示，不阻断。]`

#### FR-B3: on-demand，不自动注入（P1 定稿）

Resources **不**在会话启动时自动全量注入 system prompt / 上下文；只有显式 `read_resource` 请求的 URI 才进上下文。

**Consequences:**
- 会话启动 / server 连接成功后，system prompt 中**不**含各 server 全量 resources 文本。
- 资源内容仅在被 `read_resource` 调用后才出现在后续对话上下文。

> `[ASSUMPTION: P1 定稿为 on-demand 内置工具，而非自动注入。这是 brief 的推荐提案（规避 R3），本 PRD 定稿。]`

#### FR-B4: 返回内容同等不可信围栏

`read_resource` 返回的内容与 MCP 工具返回**同等不可信**，经与 `mapping.bridge_result` 同等的注入启发式围栏
（DP-4 第二半）标记后透传。

**Consequences:**
- `read_resource` 返回内容命中注入启发式签名时，被加 warning 标记后透传（不阻断、不截断），与工具返回一致。
- 围栏非真正边界——立场不变。

**Feature-specific NFRs:**
- **上下文预算**：on-demand 模型确保 resources 不侵蚀上下文窗口（R3 不回归）。
- **安全**：返回内容同等不可信（见 FR-B4）。

### 4.3 Prompts 消费（CLI slash）〔Epic C，最后交付〕

**Description:** 暴露 MCP 的 Prompts 原语（user-controlled，可复用参数化模板）经一个 **CLI 表面**
`/mcp-prompt <server> <name> [args]`：发现（`list_prompts`）+ 渲染（`get_prompt`）→ 注入为 user message。
Prompts 是最弱一条腿（与既有 context-files 自动加载 + 自学习记忆语义重叠），故 Epic C 最后交付。
Realizes UJ-3。

**Functional Requirements:**

#### FR-C1: list_prompts 发现

提供 `list_prompts` 发现能力（供 CLI 补全 / 列举已连 server 的可用模板）。

**Consequences:**
- 调用 `list_prompts` 返回模板清单（每项含 `name`、`description`、参数 schema）。
- 无模板时返回空列表（不抛错）。

#### FR-C2: /mcp-prompt 渲染注入

CLI 交互模式支持 `/mcp-prompt <server> <name> [key=value ...]`：渲染指定模板 → 作为 user message 注入当前会话。

**Consequences:**
- `/mcp-prompt github code_review file=loop.py` → 渲染出的模板文本作为 user message 进入会话。
- `[ASSUMPTION: CLI 交互模式当前为 click REPL；`/mcp-prompt` 表面需在该 REPL 加命令解析分支。具体接入
  （是否复用既有 slash 机制）见 §8 OQ-4。]`
- 模板不存在 → 显式错误（不静默注入空内容）。

#### FR-C3: 模板参数化

`/mcp-prompt` 支持模板声明的参数（`key=value` 形式），缺必填参数 → 显式错误。

**Consequences:**
- 模板声明必填参数 `file`，调用未提供 → 报错列出缺失参数；提供后正常渲染。

#### FR-C4: 渲染输出同等不可信

`get_prompt` 渲染出的文本与 MCP 返回内容**同等不可信**，经同等围栏标记后注入。

**Consequences:**
- 渲染输出命中注入启发式时加 warning 标记后注入（与 FR-B4 同构）。

**Feature-specific NFRs:**
- **语义重叠披露**：Prompts（注入预设指令）与既有 context-files 自动加载、自学习记忆在「注入预设上下文」
  上重叠；本 feature 不试图统一三者，仅补 MCP Prompts 这条腿。

**Notes:**
- `[NOTE FOR PM]`：Prompts 是最弱腿，价值/成本比最低；若预算吃紧，Epic C 是首选 defer 候选（见 §6.2）。

## 5. Non-Goals (Explicit)

继承 V1（`_bmad-output/mcp-client/brief.md`「V1 Out」）+ V2 新增，明确不做：

- **不做**：把 HeAgent 自身暴露为 MCP server（继承 V1）。
- **不做**：OAuth 2.1 完整流（继承 V1）。
- **不做**：MCP Registry / 目录集成（继承 V1）。
- **不做**：Resources 自动全量上下文注入（on-demand only，规避 R3）。`[NON-GOAL for MVP]`
- **不做**：Resources 订阅（`subscribe_resource`），除非架构评估确认 stateless 下仍可行（见 FR-B5/OQ-5）。
- **不做**：用户可配置注入签名入口（DP-4 围栏硬化项，正交于本周期，独立 spec 跟踪）。
- **不做**：`sampling` / `elicitation` 等 server→client 反向能力。
- **不做**：MCP 工具使用经验沉淀进自学习记忆（Vision，不绑本周期）。
- **不做**：内置（非 MCP）工具的 annotation 驱动治理（V2 仅 MCP 工具透传 annotations）。
- **不做**：据 `openWorldHint` / `idempotentHint` 改变确定性裁决（V2 仅消费 readOnly/destructive）。

## 6. MVP Scope

### 6.1 In Scope

- **Epic A**（最先）：写操作治理——`Tool.annotations` 透传 → `ToolSchema.annotations` → `PolicyEngine`
  消费（destructive 审批 / readOnly 放行 / 缺省 fail-safe / 确定性可单测）。
- **Epic B**：Resources on-demand——`list_resources` / `read_resource` 内置工具 + 同等不可信围栏。
- **Epic C**（最后）：Prompts——`list_prompts` + `/mcp-prompt` CLI 渲染注入 + 同等围栏。
- GitHub 写操作验收（沙箱 repo 建 issue，destructive 走审批）。
- 安全声明更新（`CLAUDE.md` / `docs/frame.md`）覆盖写操作治理 + Resources/Prompts 返回同等不可信。

### 6.2 Out of Scope for MVP

- Resources 订阅——待架构评估 stateless 可行性（OQ-5）；`[NOTE FOR PM]` 若预算吃紧，确认 defer。
- resource templates（`list_resource_templates`，参数化 URI 模板）——V2 仅消费具名 resources，templates 待架构评估（OQ-6）。
- `idempotentHint` / `openWorldHint` 的裁决消费——defer 到 V3 或按需。
- `[NOTE FOR PM]`：若单周期预算逼近上限，Epic C（Prompts，最弱腿）是首选 defer 候选——A+B 已让 V2
  达成核心价值（写操作治理 + Resources），Prompts 可独立 spec 后补。

## 7. Success Metrics

> 自用 dev tool——SM 偏可验证的行为目标而非 DAU/MAU；每个 SM 标注其验证的 FR。

**Primary**
- **SM-1**: 写工具受治理——`destructiveHint=true` 的 MCP 工具调用走 `APPROVAL_REQUIRED`，不裸调；
  `readOnlyHint=true` 放行；缺 annotations fail-safe。Validates FR-A3, FR-A4, FR-A5。
- **SM-2**: Resources 可发现 + 读取——`list_resources` / `read_resource` 经 `ToolResult` 桥接，E2E 可断言。
  Validates FR-B1, FR-B2。
- **SM-3**: Prompts 可列举 + 渲染——`list_prompts` + `/mcp-prompt` 渲染注入，E2E 可断言（Epic C）。
  Validates FR-C1, FR-C2。
- **SM-4**: 零回归——V1 全部 MCP 测试 + **既有 19 个**内置工具测试 + 既有测试全绿，覆盖率不低于基线
  （V2 新增的 `list_resources` / `read_resource` 等内置工具自身的测试不计入「既有」基线）。Validates 全部（回归护栏）。

**Secondary**
- **SM-5**: 治理确定性——annotations → PolicyEngine 路径不依赖 LLM 判断危险等级（FR-A6 单测可证）。
  Validates FR-A6。
- **SM-6**: 安全声明更新——`CLAUDE.md` / `docs/frame.md` 覆盖写操作治理 + Resources/Prompts 返回同等不可信。

**Counter-metrics (do not optimize)**
- **SM-C1**: **不过度审批只读工具**——`readOnlyHint=true` 的工具不应被强制确认。本指标制衡 SM-1 的保守倾向：
  fail-safe 须精准作用于「缺信号」而非「有 readOnly 信号」，否则治理闸门沦为「无脑确认每个写操作」的吵闹版本
  （UJ-1 的情感诉求正是避免这个）。Counterbalances SM-1, FR-A5。

## 8. Open Questions

- **OQ-1（fail-safe 保守度 → V3 增强，本周期已定稿）**：fail-safe 默认已**定稿为「缺 annotations → 需确认」**
  （见 FR-A5）。若日后实测发现「缺 annotations 全要确认」太吵，V3 可增强：已知只读模式工具名白名单放行、
  或 per-server 关闭 fail-safe。**本周期不做**，记录待 V3。
- **OQ-2（annotations 接入点）**：`PolicyEngine.evaluate_tool_call` 当前签名只拿 `ToolCall`、不拿 `ToolSchema`，
  怎么让裁决读到 annotations？候选：(a) `ToolCall` 携带 annotations 快照；(b) `PolicyEngine` 注入 registry
  按 name 查 schema；(c) `RunContext.metadata` 放 annotations 映射。**架构阶段定**，本 PRD 不锁死。
- **OQ-3（策略优先级，已定稿）**：✅ **已定稿**——显式策略（`approval_tools` / `approval_mcp_tools`）优先于
  annotation（见 FR-A4 Consequence 2）。保留编号供下游引用。
- **OQ-4（CLI slash 机制）**：`/mcp-prompt` 接入 CLI 交互模式的方式——是否已有 slash 命令解析机制可复用，
  还是需新建。架构/epic 阶段确认。
- **OQ-5（订阅 defer）**：`subscribe_resource` 在 2026-07-28 stateless RC 下是否可行——架构阶段评估，确认 defer 或纳入。
- **OQ-6（resource templates）**：MCP SDK 还暴露 `list_resource_templates`（参数化资源 URI 模板，如
  `file:///{path}`）。V2 的 FR-B 仅覆盖具名 `list_resources` / `read_resource`，**未消费 templates**。
  架构阶段确认 defer 或纳入（若纳入，`read_resource` 须支持 URI 模板展开）。

## 9. Assumptions Index

> 经 review（直接 finalize）确认的推断标注「✅ 已确认」；仍开放者指向 §8 OQ。

- §4.1 FR-A1 — `annotations` 用 HeAgent 自有 Pydantic 模型，不直接依赖 `mcp.types.ToolAnnotations` 进 `types.py`（避免 DAG 上浮 mcp 依赖）。（→ OQ-2，开放）
- §4.1 FR-A5 — ✅ **已确认**：P4 定稿 = 缺 annotations → fail-safe 需确认（保守），而非放行。（备选增强 → OQ-1）
- §4.2 FR-B2 — 非文本资源沿用 text-first 降级（占位表示），不阻断。
- §4.2 FR-B3 — ✅ **已确认**：P1 定稿 = Resources on-demand 内置工具，而非自动全量注入。
- §4.3 FR-C2 — CLI 交互模式可加 `/mcp-prompt` 命令解析分支。（→ OQ-4，开放）
- §4.2 / §6.2 — resource templates（`list_resource_templates`）V2 不消费，待架构评估。（→ OQ-6，开放）
