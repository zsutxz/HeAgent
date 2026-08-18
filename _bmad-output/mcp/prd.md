# PRD — HeAgent MCP Client 集成（三阶段整合）

> **2026-08-18 整合**：本文整合原 `mcp-client/prd.md`（阶段一 V1，FR-1~11 / NFR-1~7）、`mcp-v2-upgrade/prd.md`（阶段二 升级准备，FR-1~5 / NFR-1~6）、`mcp-client-v2/prd.md`（阶段三 V2，FR-A1~A7 / FR-B1~B4 / FR-C1~C4 + NFR-1~7）。FR 编号在三阶段间独立，**跨阶段引用须写全限定**（如「V1 FR-3」「升级 FR-3」「V2 FR-A3」）。三阶段 PRD 原始 `status` 均为 `final`。

---

# 阶段一 · MCP V1 集成（FR-1~11 / NFR-1~7）

> 输入：brief（`brief.md` §一）。技术实现细节见 `brief.md` 技术速览（原 addendum）。

## 背景与目标

HeAgent 工具体系基于 `@tool` 装饰器 + `ToolRegistry` 进程单例，内置 18 个工具，当前工具写死内置。**目标**：接入 MCP，连接任意 server、动态消费其 **Tools** 原语，桥接进 `ToolRegistry`。首个验收场景：**GitHub 只读**。

**非目标（V1）**：MCP 写操作；Resources/Prompts 原语；HeAgent 暴露为 server；OAuth 2.1 完整流；MCP Registry 集成。

**示例会话**：tan 配好 GitHub MCP server 后问「HeAgent 这个 repo 最近有哪些 open issue？」→ agent 调 `list_issues` 返回并总结；「搜一下 retry 是怎么实现的」→ agent 调 `search_code` → 返回命中文件与片段。全程无需手写工具代码。

## 功能需求

### 3.1 MCP Server 连接与生命周期

- **FR-1**：根据声明式配置连接外部 MCP server，支持 **stdio**（本地子进程）与 **Streamable HTTP**（远程）双 transport。
- **FR-2**：连接生命周期与 `AgentLoop` 绑定（启动建立、退出优雅回收、崩溃可观测）。**工具发现须在 AgentLoop 首次构建工具列表（注入 system prompt）前完成，或提供 lazy 回退**（时序影响 NFR-4 与 R3，架构定 eager/lazy）。
- **FR-3**：连接失败按既有异常层级降级不崩溃；失败 server 工具不注入。区分**连接建立阶段失败**（工具从未注入）与**运行时已注册工具因断连失效**（调用降级为错误结果不崩溃）。

### 3.2 工具发现与桥接

- **FR-4**：连接后**动态发现** Tools → 映射 `ToolSchema`（name/description/JSON Schema inputSchema）→ 注册进 `ToolRegistry`。
- **FR-5**：调用结果桥接为 `ToolResult`，回 `AgentLoop` 既有循环，与内置工具执行路径一致（含并行 `asyncio.gather`）。
- **FR-6**：多 server 工具命名去歧义（server 名前缀 namespace）。

### 3.3 声明式配置

- **FR-7**：项目根 **`.mcp.json`** 声明 `mcpServers`（stdio: `{command, args, env}` / http: `{url, headers}`，对齐 Claude Code/Cursor）。**无配置或空列表 → 纯内置工具模式启动，不报错不阻断**。
- **FR-8**：`${ENV}` 插值（如 `${GITHUB_TOKEN}`）；鉴权凭据走环境变量，不写配置明文。

### 3.4 GitHub 只读验收

- **FR-9**：以官方 `github/github-mcp-server` 为验收场景，完成**两类只读操作**：「列出指定 repo 的 open issue」与「代码搜索」。结果经 `ToolResult` 桥接，**E2E 可断言关键字段**（issue 列表项 / 搜索命中文件路径）。V1 验收范围限于上述两类。

### 3.5 安全

- **FR-10**：外部 MCP server 明确归入既有安全声明（不可信代码 + 不可信输出进 LLM 上下文）；CLAUDE.md 安全声明更新覆盖。
- **FR-11**：MCP 工具调用受与内置工具同等的安全约束，**工具返回内容同样视为不可信**（prompt injection 无隔离）。`SafetyGuard` 扩展作为架构探索项，V1 以安全声明 + 边界声明为主（→ DP-4，后两半落地）。

## 非功能需求

- **NFR-1（异步）**：全异步实现，库代码无同步 I/O。
- **NFR-2（零回归）**：18 内置工具 + 全部既有测试零回归（pytest 全绿）；覆盖率以实现时基线不下降。
- **NFR-3（版本可控）**：`mcp>=1.27,<2`（后统一 `>=1.28,<2`）；握手等封装在 `MCPClientManager` 内部。**成功标准**：v2/stateless 迁移时改动限于 manager 内部，不波及 `AgentLoop`。
- **NFR-4（启动性能）**：多 server 连接与发现不显著拖慢启动；实现时测量记录基线。
- **NFR-5（可观测）**：连接状态/发现数量/调用结果有日志（stdlib logging）。
- **NFR-6（错误隔离）**：单 server 失败不影响其他 server 与内置工具。
- **NFR-7（代码规范）**：PEP8 / Pydantic / 120 行宽 / 3.11+；tool 层禁从 `agent/` 导入（DAG）。

## 成功指标

| 指标 | 目标 | 反指标 |
|---|---|---|
| MCP 链路打通 | agent 能发现 + 调用外部 MCP 工具 | server 连接失败率 |
| GitHub 只读验收 | ≥1 个真实 repo 的 issue / 代码搜索 E2E 通过 | — |
| 开源可用 | 声明式配置 + 文档示例可让他人接入 | 配置上手成本 |
| 零回归 | 既有测试全绿、覆盖率不降 | 新增 bug 数 |
| 安全边界清晰 | 安全声明更新、MCP 受同等约束 | 误以为「接 MCP 更安全」 |
| 协议可迁移 | 握手封装内部、迁移改动局部化 | 与 SDK v2 强耦合面 |

## 约束与依赖

- **协议窗口**：stable `2025-11-25`；`2026-07-28` RC stateless breaking。
- **SDK**：官方 `mcp`（v1.28.0 stable，原生 async）。
- **架构 DAG**：MCP 适配属 `tools/` 层，禁从 `agent/` 导入；复用 `ToolRegistry`/`ToolSchema`/`ToolResult`/`SafetyGuard`。
- **配置形态**：声明式 `mcpServers`。
- **安全**：受 CLAUDE.md 文首安全声明约束，不可在无 OS 沙箱下裸跑外部 server。

## 风险

- **R1（安全）**：外部 server = 不可信代码 + 不可信输出。缓解：安全声明 + 文档警示 + 建议沙箱。
- **R2（stdio 子进程生命周期）**：崩溃/僵尸/env 泄漏。缓解：`AsyncExitStack` 托管 + 优雅关闭。
- **R3（工具数量爆炸）**：多 server 叠加侵蚀上下文。缓解：lazy 发现 + `ContextCompressor` + namespace。
- **R4（SDK breaking）**：v2 + 协议 stateless 双 breaking。缓解：握手封装内部 + pin `<2`。
- **R5（GitHub server 形态）**：缓解：双 transport 都支持；**验收采用官方远程 server**（只读 + 官方维护）。

## 决策定稿

全部 `[ASSUMPTION]` 已定稿（见 `decision-log.md` DP-1~6）：配置落点项目根 `.mcp.json`；鉴权 `${GITHUB_TOKEN}`；验收清单两类 E2E；SafetyGuard 声明为主；验收用官方远程 server；记忆整合 Vision。→ 无 phase-blocker。

---

# 阶段二 · MCP v1→v2 升级准备（FR-1~5 / NFR-1~6）

> 输入：brief（`brief.md` §二）+ 技术速览（`brief.md` 技术速览）。**承接**：兑现 V1 NFR-3 成功标准——「v2/stateless 迁移时改动限于 `MCPClientManager` 内部，不波及 `AgentLoop`」。**周期**：Epic 14。

## 背景与目标

HeAgent 的 MCP client 现消费 Tools 原语。官方 SDK `mcp` v2.0.0 stable（目标 2026-07-27）+ 协议 2026-07-28 RC（breaking）将重塑 client API。逐行核查命中 5 个调用点（`brief.md` 技术速览），其中 `initialize` 删除 + `send_ping` deprecated 为设计级冲击。

**目标**：兑现 V1 NFR-3 已埋迁移预留，把 5 个 v2-sensitive 调用点抽象成隔离层，使 v2 stable 落地时切换局部化、Epic 11-13 零回归。

**非目标**：Resources/Prompts 原语、写操作、实际切 v2、HeAgent 暴露为 server。

## 功能需求

> 独立 FR 编号空间（FR-1~5），引用 V1 周期 FR/NFR/DP 时写全限定（如 V1 FR-3、V1 NFR-3、V1 DP-4）。

### 2.1 依赖与隔离层

- **FR-1**：SDK pin floor 从 `mcp>=1.28,<2` 提到 `mcp>=1.28.1,<2`（对齐 v1 线最新 stable 1.28.1）。
- **FR-2**：在 `MCPClientManager` 内建隔离层，封装 5 个 v2-sensitive 调用点，对外暴露稳定内部接口：
  - (a) 握手（现 `session.initialize()`，v2 删除）
  - (b) 健康探测（现 `session.send_ping()`，v2 deprecated）
  - (c) 工具发现（`session.list_tools()`，签名 + snake_case 变）
  - (d) 工具调用（`session.call_tool()`，返回 snake_case）
  - (e) 类型导入（`from mcp.types`，v2 拆 `mcp-types` 包）
  - v1 过渡形态：健康探测保留 ping 占位（候选 C），v2 切换时改实现。

### 2.2 断连探测 v2 等价机制

- **FR-3**：文档化 V1 FR-3（运行时 ping-watch 断连 auto-unregister）在 v2 stateless 下的等价机制选型（候选 A/B/C）。本周期只产出**设计决策**，不含实现。**安全立场不可退化**：v2 形态下断连的工具仍须主动或被动注销，不得滞留 LLM 工具列表。

### 2.3 回归与切换准备

- **FR-4**：迁移测试基线——V1 的 MCP 测试（`tests/test_mcp_*.py`）在本周期所有改动后全绿。
- **FR-5**：文档化 v2 stable 落地时的切换路径（改隔离层内部实现、外部接口不动；FR-3 等价机制从候选 C 过渡到选定方案的实现步骤）。只产出**路径文档**，不含实际切换执行。

## 非功能需求

- **NFR-1（零回归）**：V1 MCP 集成测试全绿，以 FR-4 基线为零回归上限。
- **NFR-2（封装局部化）**：隔离层对外接口签名 v1→v2 切换前后保持不变（diff 为空）——兑现 V1 NFR-3 成功标准。
- **NFR-3（不可信边界立场延续）**：V1 DP-4 两半（执行前工具名拦截 + 返回内容启发式围栏）不因升级退化。
- **NFR-4（纯 v1 准备）**：不引入 v2 alpha 依赖；隔离层在 v1 上做抽象，为 v2 留形。
- **NFR-5（继承约束）**：异步 + DAG（tool 层禁从 `agent/` 导入）。
- **NFR-6（可观测）**：隔离层调用、握手、健康探测有日志。

## 成功指标

| 指标 | 目标 | 反指标 |
|---|---|---|
| 零回归 | `tests/test_mcp_*.py` 全绿（含 V1 DP-4 用例） | 新增 bug / 既有用例红 |
| 封装局部化 | 隔离层对外接口 v1→v2 diff 为空 | 切换波及 `AgentLoop` |
| FR-3 等价机制就绪 | v2 形态断连探测有等价设计 | 工具滞留 LLM 列表 |
| 切换就绪 | 切换路径文档化 | 实际切 v2（反指标） |

## 约束与依赖

- SDK pin `mcp>=1.28.1,<2`（v2 stable 后评估上界）。
- **【订正 2026-07-12】** 原 research 误断「v1 最新 stable = 1.27.2」，实际 1.28.0 早在 2026-06-20 已被本仓库安装（V1 Story 1.1），1.28.1 为当前最新——V1 prd §6「v1.28.0 stable」**非笔误、正确**。
- 协议 stable `2025-11-25`；RC `2026-07-28` 仅设计参照。
- 架构 DAG：MCP 隔离层属 `tools/mcp/`，禁从 `agent/` 导入。
- 安全：受 CLAUDE.md 文首声明约束（继承 V1 立场）。

## 风险

- **R1（隔离层过度抽象）**：为预见 v2 形态而抽象过深。缓解：只隔离已命中的 5 个点。
- **R2（FR-3 选型悬空）**：只设计不实现，若 architecture 选型拖延，切换时 FR-3 最痛。缓解：architecture 阶段必须定选型。
- **R3（v2 stable 跳票）**：若 2026-07-27 未如期，本周期「准备」仍有效（纯 v1 隔离层不依赖 v2），切换延后。

## 决策定稿

`[ASSUMPTION]` 留 architecture：隔离层抽象形态（protocol/adapter）、FR-3 选型（A/B/C）。已定稿：FR 编号独立空间 FR-1~5 + 全限定引用；V1 prd §6「v1.28.0」原判笔误——**已订正：1.28.0 真实存在，非笔误**。

---

# 阶段三 · MCP Client V2（FR-A1~A7 / FR-B1~B4 / FR-C1~C4）

> 输入：brief（`brief.md` §三）。**FR 编号独立于 V1（FR-1~11）与主线 baseline（FR-1~24）**；字母前缀对应 brief P5 结构（A=写操作治理 / B=Resources / C=Prompts）。建立在两份既有产物之上：本周期 brief + V1 交付物（`tools/mcp/` + `engine/policy.py`）——**不重写 V1、不破坏既有不变量**。

## 1. Vision

V1 让 HeAgent 接上了 Tools 原语（GitHub 只读验收跑通，DP-4 两半落地）。V1 刻意冻结三处缺口，正是 V2 要补的：① **写操作无治理**（`call_tool` 闭包对只读 `search_code` 与 destructive `delete_repository` 一视同仁，无审批/危险分级）；② **Resources/Prompts 两原语零消费**。

一句话愿景：**让 HeAgent 从「能调只读 MCP 工具」升级为「能安全调写工具 + 消费全部 MCP 原语」，且危险等级的判定始终在代码层、不在 LLM 层。**

安全立场延续 V1/DP-4：治理闸门 **非真正安全边界**——annotations 是 server 自声明（可谎报），与 DP-4 围栏同构，须 OS 级沙箱兜底。

## 2. Target User

**JTBD**：让 agent 能建 issue / 提 PR / 评论且 destructive 有审批闸门；能按需取回可寻址资源；能从 CLI 一键渲染注入参数化 prompt 模板。**情感**：不要在「无脑确认每一个写操作」（吵）与「全部放行」（危险）之间二选一——要按工具自声明危险等级智能放行/拦截。

**Non-Users (V2)**：OAuth 2.1 完整流企业用户；MCP Registry 用户；把 HeAgent 当 server 暴露的人；在沙箱外裸跑 destructive 工具且信任 server 声明的人。

**Key User Journeys**：
- **UJ-1**（Realizes FR-A3/A5）：tan 让 agent 在沙箱 repo 建 issue → agent 调 `github__create_issue`（`destructiveHint=true`）→ `PolicyEngine` 产出 `APPROVAL_REQUIRED` → 挡在闸门前 → 确认授权 → 重放执行。**Climax**：destructive 调用从不裸跑，确认前 0 副作用。
- **UJ-2**（Realizes FR-B1/B2/B3）：tan 问「这个 server 有哪些资源」→ agent 调 `list_resources` 拿清单 → 按需 `read_resource` 取回指定 URI。**全程不自动全量注入**。
- **UJ-3**（Realizes FR-C1/C2/C3）：tan 敲 `/mcp-prompt github code_review file=loop.py` → CLI 查 `list_prompts` 找到模板、渲染参数、作为 user message 注入会话。

## 3. Glossary（全文唯一词汇源）

- **MCP 三原语** — Tools（model-controlled，LLM 自主调）/ Resources（application-controlled，宿主决定注入、URI 寻址、幂等无副作用）/ Prompts（user-controlled，用户触发的可复用参数化模板）。V1 仅消费 Tools；V2 补 Resources + Prompts。
- **Tool Annotations** — MCP（2026-03）server 端工具风险词汇，位于 `Tool.annotations`，四 hint：`readOnlyHint` / `destructiveHint` / `idempotentHint` / `openWorldHint`。**server 自声明、不可信**。V2 主消费 `readOnlyHint` 与 `destructiveHint`。
- **写操作治理** — annotations 透传进 `ToolSchema.annotations` → 喂 `PolicyEngine`：destructive 触发审批、readOnly 放行、缺省 fail-safe。确定性裁决、不交给 LLM。
- **PolicyVerdict** — `engine/policy.py` 裁决产物，`mode` ∈ {`DIRECT`, `APPROVAL_REQUIRED`, `SANDBOX_REQUIRED`, `BLOCKED`}。
- **fail-safe 默认（P4）** — 缺 annotations 或不可信时按保守默认视为**非只读 → 需确认**。
- **on-demand（P1）** — Resources 消费模型：不自动全量注入，仅显式请求指定 URI 时读取。
- **namespace** — MCP 工具 LLM 可见名 `<server>__<tool>`（双下划线）；`PolicyEngine._is_mcp_tool` 依此判定。
- **DP-4 围栏** — V1 两半防御：执行前工具名黑名单 + 返回内容注入启发式标记（`mapping.bridge_result`，标记透传不阻断）。**非真正安全边界**。
- **destructive 工具** — `Tool.annotations.destructiveHint=true`（或 fail-safe 下缺 annotations 的工具）。

## 4. Features

### 4.1 写操作治理（annotations → PolicyEngine）〔Epic A，最先交付〕

**Description:** 给 V1 既有 `call_tool` 路径加确定性危险分级闸门。`Tool.annotations` 是天然信号源——destructive→`APPROVAL_REQUIRED`、readOnly→放行、缺省 fail-safe。**判定在代码层、不在 LLM 层**（单测可证，FR-A6）。Realizes UJ-1。立场：annotations 不可信；闸门非真正安全边界，须 OS 级沙箱兜底。

- **FR-A1: ToolSchema 携带 annotations** — `ToolSchema` 新增可选字段 `annotations`（默认缺省），不破坏 V1 既有 3 字段（name/description/parameters）。字段类型为 HeAgent 自有 Pydantic 模型（`[ASSUMPTION: 不直接依赖 mcp.types.ToolAnnotations 进 types.py，避免 types 层上浮 mcp 依赖]`）。Out of Scope: 内置工具 annotations（V2 仅 MCP）。
- **FR-A2: mcp_tool_to_schema 透传 annotations** — `mapping.mcp_tool_to_schema` 读取 `tool.annotations` 填入 `ToolSchema.annotations`；`tool.annotations` 为 None 时留**保守标记**（对齐 FR-A5 fail-safe）。
- **FR-A3: PolicyEngine 按 destructiveHint 触发审批** — `destructiveHint=true` → `PolicyVerdict(mode=APPROVAL_REQUIRED)`，挡在闸门前直到授权（`metadata.approved_tools` 含该工具/`*`/`__mcp__`）。路径**不依赖 LLM 输出**：纯函数 `(ToolCall, annotations, context)` → `PolicyVerdict`。
- **FR-A4: readOnlyHint 放行自动调用** — 无其他阻断条件时不经审批直接放行（DIRECT 或既有沙箱裁决）。**显式策略优先于 annotation**（`approval_tools`/`approval_mcp_tools` 命中即审批，覆盖 server readOnly 声明）；反向不成立。
- **FR-A5: 缺 annotations → fail-safe 需确认（P4 定稿）** — 缺 annotations（或不可信/无法判定）→ 按保守默认视为**非只读 → 需确认**（`APPROVAL_REQUIRED`）。fail-safe 仅作用于「缺信号」而非「有 readOnly 信号」。
- **FR-A6: 治理确定性可单测** — 存在不调用任何 LLM 的单元测试断言：(ToolCall, annotations) → 固定 PolicyVerdict（destructive→APPROVAL_REQUIRED / readOnly→非 approval / 缺省→APPROVAL_REQUIRED）。
- **FR-A7: idempotentHint / openWorldHint 暂存不裁决** — 两字段透传存储（LLM 可见），但 V2 `PolicyEngine` 不据此改变裁决。

**Feature-specific NFRs**：安全/诚实立场（annotations 不可信，闸门 defense-in-depth）；确定性（纯函数无 LLM）。

### 4.2 Resources 消费（on-demand）〔Epic B〕

**Description:** 暴露 `list_resources` / `read_resource` 为**内置工具**（on-demand，规避 R3 上下文侵蚀）。Realizes UJ-2。

- **FR-B1: list_resources 内置工具** — 返回已连 server 暴露的资源清单（URI + 名称 + 描述）；无连接/不暴露 → 空列表（不抛错）。
- **FR-B2: read_resource 内置工具** — 按指定 server + URI 取回资源内容经 `ToolResult` 桥接；URI 不存在 → `ToolError`（显式失败）；非文本资源沿用 text-first 降级（`[resource: uri]` 占位）。`[ASSUMPTION: 非文本降级沿用 V1 call_result_to_text]`（**架构 AD-5 收紧：签名 `read_resource(server, uri)`，server 必填**）。
- **FR-B3: on-demand，不自动注入（P1 定稿）** — Resources **不**在会话启动/连接成功后自动全量注入 system prompt；仅显式 `read_resource` 请求的 URI 进上下文。
- **FR-B4: 返回内容同等不可信围栏** — `read_resource` 返回内容经与 `mapping.bridge_result` 同等的注入启发式围栏（DP-4 第二半）标记后透传（不阻断不截断）。

**Feature-specific NFRs**：上下文预算（on-demand 确保 R3 不回归）；安全（返回同等不可信）。

### 4.3 Prompts 消费（CLI slash）〔Epic C，最后交付〕

**Description:** 暴露 Prompts 原语经 CLI 表面 `/mcp-prompt <server> <name> [args]`：发现 + 渲染 → 注入为 user message。最弱腿（与 context-files 自动加载 + 自学习记忆语义重叠），Epic C 最后交付。Realizes UJ-3。

- **FR-C1: list_prompts 发现** — 返回模板清单（name/description/参数 schema）；无模板 → 空列表（不抛错）。
- **FR-C2: /mcp-prompt 渲染注入** — CLI 交互模式 `/mcp-prompt <server> <name> [key=value ...]` 渲染模板 → 作为 user message 注入当前会话；模板不存在 → 显式错误（不静默注入空内容）。`[ASSUMPTION: 接入方式见 §8 OQ-4，架构定稿为最小 slash 分发器]`
- **FR-C3: 模板参数化** — 支持 `key=value` 参数；缺必填参数 → 显式错误列出缺失参数。
- **FR-C4: 渲染输出同等不可信** — `get_prompt` 渲染文本经同等围栏标记后注入（与 FR-B4 同构）。

**Feature-specific NFRs**：语义重叠披露（Prompts 与 context-files/自学习记忆在「注入预设上下文」重叠；不统一三者，仅补 MCP 这条腿）。

## 5. Non-Goals (Explicit)

继承 V1 + V2 新增：HeAgent 暴露为 server；OAuth 2.1 完整流；MCP Registry；**Resources 自动全量注入**（on-demand only）；**Resources 订阅**（除非 stateless 下可行）；**用户可配置注入签名入口**（DP-4 硬化项，正交独立 spec）；`sampling`/`elicitation`；MCP 工具经验沉淀进自学习记忆（Vision）；**内置工具 annotation 驱动治理**（V2 仅 MCP）；据 `openWorldHint`/`idempotentHint` 改变裁决。

## 6. MVP Scope

**In**：Epic A（写操作治理，最先）；Epic B（Resources on-demand）；Epic C（Prompts，最后）；GitHub 写操作验收（沙箱 repo 建 issue 走审批）；安全声明更新。

**Out of Scope for MVP**：Resources 订阅（待架构评估 stateless 可行性，OQ-5）；resource templates（`list_resource_templates`，OQ-6）；`idempotentHint`/`openWorldHint` 裁决消费（defer V3）；`[NOTE FOR PM]` 预算吃紧时 Epic C 是首选 defer 候选（A+B 已达成核心价值）。

## 7. Success Metrics

**Primary**：SM-1 写工具受治理（FR-A3/A4/A5）；SM-2 Resources 可发现+读取（FR-B1/B2）；SM-3 Prompts 可列举+渲染（FR-C1/C2）；SM-4 零回归——V1 全部 MCP 测试 + **既有 19 个**内置工具测试 + 既有测试全绿、覆盖率不低于基线。

**Secondary**：SM-5 治理确定性（FR-A6 单测可证）；SM-6 安全声明更新（CLAUDE.md/frame.md 覆盖写操作治理 + Resources/Prompts 同等不可信）。

**Counter-metrics**：**SM-C1 不过度审批只读工具** — `readOnlyHint=true` 不应被强制确认；fail-safe 须精准作用于「缺信号」而非「有 readOnly 信号」，否则沦为「无脑确认每个写操作」的吵闹版本（制衡 SM-1/FR-A5）。

## 8. Open Questions

- **OQ-1（fail-safe 保守度 → V3 增强，本周期已定稿）**：已定稿「缺 annotations → 需确认」。若日后实测太吵，V3 增强：已知只读工具名白名单 / per-server 关闭 fail-safe。本周期不做。
- **OQ-2（annotations 接入点）**：`PolicyEngine.evaluate_tool_call` 怎么读到 annotations？候选 (a) ToolCall 携带快照 / (b) PolicyEngine 注入 registry 按 name 查 / (c) RunContext.metadata 放映射。**架构定稿 = (b) 变体：evaluate 增 `schema` kwarg**（见 `architecture.md` 阶段三 AD-1）。
- **OQ-3（策略优先级，已定稿）**：显式策略优先于 annotation（FR-A4 Consequence 2）。
- **OQ-4（CLI slash 机制）**：是否复用既有 slash。架构定稿：无既有机制，新增最小分发器（AD-7）。
- **OQ-5（订阅 defer）**：`subscribe_resource` 在 stateless RC 下可行性。架构定稿：defer。
- **OQ-6（resource templates）**：`list_resource_templates` 是否纳入。架构定稿：defer（边际价值低）。

## 9. Assumptions Index

- FR-A1 — `annotations` 用 HeAgent 自有 Pydantic 模型，不上浮 mcp 依赖。（→ OQ-2，定稿）
- FR-A5 — ✅ **已确认**：P4 定稿 = fail-safe 需确认（保守）。（备选增强 → OQ-1）
- FR-B2 — 非文本资源沿用 text-first 降级，不阻断。
- FR-B3 — ✅ **已确认**：P1 定稿 = Resources on-demand 内置工具。
- FR-C2 — CLI 交互模式可加 `/mcp-prompt` 分支。（→ OQ-4，定稿）
- FR-B2/§6.2 — resource templates V2 不消费。（→ OQ-6，定稿）

---

# 阶段间关系备忘

| 维度 | 阶段一 V1 | 阶段二 升级 | 阶段三 V2 |
|------|----------|------------|-----------|
| 时间 | 2026-06-20 | 2026-07-12 | 2026-07-17 |
| 主线 Epic | 11-13 | 14 | 15-18 |
| 意图 | 接上 MCP Tools | 为 v2 breaking 铺路（隔离层） | 写操作治理 + Resources/Prompts |
| FR | FR-1~11 + NFR-1~7 | FR-1~5 + NFR-1~6 | FR-A1~A7/B1~B4/C1~C4 + NFR-1~7 |
| 关键决策锚点 | DP-1~6（DP-4 = SafetyGuard deferred） | AD-1~6（session_api 隔离层） | AD-1~8（annotations 闸门 / _sessions / guard_content） |
| 安全立场 | 不可信边界声明 | DP-4 不退化 | annotations 不可信，闸门 defense-in-depth |
| 相互关系 | 阶段二兑现 V1 NFR-3 迁移预留；阶段三实际落地阶段二 Out 中的 Resources/Prompts | | |
