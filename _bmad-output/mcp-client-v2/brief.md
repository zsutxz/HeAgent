---
title: "HeAgent MCP Client 集成 V2 — 写操作治理 + Resources/Prompts 原语"
status: draft
cycle: mcp-client-v2
preceded_by: _bmad-output/mcp-client/（V1，epics 11-13，Tools-only，已冻结交付）
created: 2026-07-17
updated: 2026-07-17
---

# Product Brief: HeAgent MCP Client 集成 V2

> **本周期 = V1（`_bmad-output/mcp-client/`，Tools-only，已交付）的延续。** V1 把 HeAgent
> 接上了 MCP 的 **Tools 原语**（只读验收：GitHub 列 issue / 搜代码）。V2 把 MCP 消费面补全：
> 让 HeAgent **安全地调用写工具**（建 issue / 提 PR / 评论）+ **消费 Resources / Prompts 两原语**。
> 从「能调只读 MCP 工具」升级为「能安全调写工具 + 消费全部 MCP 原语」。

## 概述

V1 的 `MCPClientManager` 已稳定承载 Tools 原语：连接 server、`list_tools` 发现、`call_tool` 桥接进
`ToolRegistry`，LLM 像调内置工具一样调外部工具，结果回 `AgentLoop` 既有循环。安全侧已落 DP-4 两半
（执行前工具名黑名单 + 返回内容注入启发式围栏，均标记透传、非真正边界）。

但 V1 有三处刻意冻结的缺口（见 V1 brief「V1 Out」与 CLAUDE.md「后续 deferred」）：

1. **写操作无治理**：`call_tool` 机制本身对写无关——它已能调 GitHub 的 `create_issue`/`create_pull_request`。
   但 V1 验收只覆盖只读、安全立场把 MCP server 当不可信代码。**当前没有任何写工具的治理闸门**：
   LLM 可直接调 destructive 工具（删 repo / 建 issue / push），无审批、无 allow-list、无危险分级。
2. **Resources 原语未消费**：`list_resources` / `read_resource` 未接。server 暴露的可寻址资源
   （文件、数据库行、配置、运行时状态）HeAgent 完全拿不到。
3. **Prompts 原语未消费**：`list_prompts` / `get_prompt` 未接。server 提供的可复用参数化模板
   （如「代码审查」「生成 commit message」prompt）HeAgent 用不上。

V2 把这三处补齐，落在 V1 既有的 `MCPClientManager` 扩展点上，**不重写 V1、不破坏既有不变量**。

## 问题

### 写操作：机制已有，治理缺失

V1 把 MCP server 当不可信代码 + 不可信输出（DP-4）。但写工具还多一层维度——**不可信/危险的副作用动作**。
当前 `call_tool` 闭包（`manager.py:_make_handler`）对所有工具一视同仁：只读 `search_code` 与 destructive
`delete_repository` 走完全相同路径，LLM 选了就执行。这与 HeAgent「确定性逻辑交给代码、不交给概率模型」
的硬约束冲突——「这个调用会不会造成不可逆副作用」不应由 LLM 判断，应由确定性闸门裁决。

MCP 在 2026-03 引入 **tool annotations 作为风险词汇**（`readOnlyHint` / `destructiveHint` /
`idempotentHint` / `openWorldHint`，见 [官方博客](https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/)
与 [spec 2025-11-25](https://modelcontextprotocol.io/specification/2025-11-25/server/tools)）。server
在 `Tool.annotations` 上声明每个工具的风险等级——这正是写操作治理的天然信号源。HeAgent 的 `engine/PolicyEngine`
（FR 外 P0 增量，已落地：准入/审批/沙箱裁决产出 `PolicyVerdict`）是天然消费方。

→ **写操作治理 = 把 `Tool.annotations` 透传进 `ToolSchema` → 喂 `PolicyEngine`：`destructiveHint=true`
触发审批/确认，`readOnlyHint=true` 放行自动调用。** 不是新机制，是给既有 `call_tool` 路径加确定性闸门。

### Resources：V1 defer 理由已弱化

V1 brief 把 Resources defer 的理由是「语义与 Tools 重叠边界不清，主流框架也尚未接入」。**后者已过时**：
2026-07，[Claude Desktop 与 Cursor 均已支持 Resources](https://cursor.com/docs/mcp)（Cursor 在 project /
global 两级）。Resources 是 MCP 的 application-controlled 原语（宿主决定注入上下文、幂等无副作用、URI 寻址、
可订阅）——与 model-controlled 的 Tools 是不同的消费模型，HeAgent 当前对它零消费。

### Prompts：原语存在，但价值/成本比最低

Prompts 是 user-controlled 原语（用户触发的可复用模板）。在 Claude Desktop 里表现为 slash command。
HeAgent 要消费它需一个 CLI 表面（`/mcp-prompt <server> <name> [args]`）把模板渲染成 message 注入会话。
**这条腿最弱**：与 HeAgent 既有的 context-files 自动加载 + 自学习记忆系统语义重叠（都是「注入预设上下文/指令」），
且依赖 CLI 改动。是否纳入本周期是开放问题（见「关键决策提案」P3）。

## 方案

三条腿，**全部复用 V1 `MCPClientManager` 扩展点**（`_discover_and_register` / `_make_handler` / mapping），
不引入新 transport / 不改 `AgentLoop`：

1. **写操作治理（annotations → PolicyEngine）**：
   - `mapping.mcp_tool_to_schema` 透传 `Tool.annotations`（readOnlyHint/destructiveHint/...）进 `ToolSchema`
     （新增字段，不破坏 V1 schema 兼容）；
   - `engine/PolicyEngine` 消费 annotations：`destructiveHint=true` → 走审批/确认（复用既有 approval 路径），
     `readOnlyHint=true` → 放行；缺 annotations 时按保守默认（视为非只读 → 需确认，fail-safe）；
   - 立场延续：**仍是不可信代码，治理闸门非真正安全边界**，须 OS 级沙箱兜底（与 DP-4 同构）。
2. **Resources 消费**：`[DECISION PROPOSAL P1]` 暴露 `list_resources` / `read_resource` 为**内置工具**
   （on-demand：LLM 按需取指定 URI 的资源），**不自动全量注入上下文**（避免 V1 已识别的 R3 上下文侵蚀回归）。
   订阅（`subscribe_resource`）与 stateful 依赖 → 见技术约束（stateless RC 风险）。
3. **Prompts 消费**：`[DECISION PROPOSAL P2]` CLI slash 表面（`/mcp-prompt ...`）渲染模板 → 注入为
   user message；`list_prompts` 供发现/补全。Epic C 最后交付（最弱一条腿）。

## 差异化

「补全 MCP 原语消费」本身**并非壁垒**——各大 client 都在做。HeAgent 的真正机会在两点（延续 V1 立场）：

1. **写操作治理的确定性**：把「这个 MCP 调用危不危险」交给 annotations + `PolicyEngine` 的确定性裁决，
   而非让 LLM 自己判断或对所有写工具一刀切确认。这是 HeAgent「确定性逻辑交给代码」硬约束在 MCP 写操作上的
   直接体现，也是区别于「无脑确认每个写操作」的朴素实现的关键。
2. **诚实安全立场的延续**：治理闸门不宣称「接了写操作就更安全」——annotations 是 server 自声明
   （恶意/错误 server 可谎报 `readOnlyHint=true`），与 DP-4 围栏一样是 defense-in-depth 标记，非真正边界。
   须 OS 级沙箱兜底（立场不变）。

**不做的事**：不把 HeAgent 自身暴露为 MCP server（继承 V1）；不重复造 SDK 能力；不做 Resources 自动全量
上下文注入（on-demand only，规避 R3）。

## 受众

- **主要**：HeAgent 作者（自用提效）——让 agent 不只能读 GitHub，还能**建 issue / 提 PR**，且 destructive
  操作有审批不裸跑。
- **次要**：开源用户——经 Resources/Prompts 消费自己 MCP server 暴露的上下文与模板。
- **非受众（V2）**：需要 OAuth 2.1 完整流的企业远程 server 用户、需要 MCP Registry 目录的用户。
- **成功画像**：用户配好 GitHub MCP server 后，让 agent「在这个 repo 建一个 issue 标题 X 内容 Y」→
  agent 调 `create_issue`，destructiveHint 触发**审批**，用户确认后执行；或问「这个 server 有哪些资源」→
  agent 调 `list_resources` / `read_resource` 取回。

## 成功标准

- ✅ **写工具受治理**：`destructiveHint=true` 的 MCP 工具调用走 `PolicyEngine` 审批，不裸调；
  `readOnlyHint=true` 放行自动调用；缺 annotations 按保守默认。
- ✅ **Resources 可发现 + 读取**：`list_resources` / `read_resource` 经 `ToolResult` 桥接，E2E 可断言。
- ✅ **Prompts 可列举 + 渲染**：`list_prompts` + `/mcp-prompt` 渲染注入，E2E 可断言（Epic C）。
- ✅ **零回归**：V1 全部 MCP 测试 + 18 内置工具 + 既有测试全绿，覆盖率不低于基线。
- ✅ **治理确定性**：annotations → PolicyEngine 路径**不依赖 LLM 判断**危险等级（单测可证）。
- ✅ **安全声明更新**：覆盖写操作治理 + Resources/Prompts 返回内容同等不可信（与内置工具/DP-4 同立场）。

## 范围

**V2 In：**
- 写操作治理：`Tool.annotations` 透传 → `PolicyEngine` 裁决（destructive 审批 / readOnly 放行 / 缺省保守）
- Resources 原语：发现 + on-demand 读取（内置工具形态）
- Prompts 原语：列举 + CLI 渲染注入（Epic C）
- GitHub 写操作验收（如：在沙箱 repo 建 issue，destructive 走审批）
- 安全声明更新（CLAUDE.md / frame.md）

**V2 Out（明确不做）：**
- HeAgent 自身暴露为 MCP server（继承 V1）
- OAuth 2.1 完整流（继承 V1）
- MCP Registry / 目录集成（继承 V1）
- Resources 自动全量上下文注入（on-demand only，规避 R3 上下文侵蚀）
- Resources 订阅（`subscribe_resource`）若与 stateless 迁移冲突则 defer（见技术约束）
- 用户可配置注入签名入口（DP-4 围栏的硬化项，**正交于本周期**，独立 spec 跟踪）
- `sampling` / `elicitation` 等 server→client 反向能力
- MCP 工具使用经验沉淀进自学习记忆（Vision，不绑本周期）

## 技术约束 / 兼容性窗口

- **SDK**：沿用 `mcp>=1.27,<2`（V1 NFR-3 沿袭）。已核实 SDK 暴露 `list_resources`/`read_resource`/
  `list_resource_templates`/`subscribe_resource`/`list_prompts`/`get_prompt`，且 `Tool.annotations:
  ToolAnnotations(readOnlyHint, destructiveHint, idempotentHint, openWorldHint)`。
- **协议窗口 ⚠️**：stable `2025-11-25`；`2026-07-28` RC 转 stateless（删 `initialize` 握手）。**Resources
  订阅（`subscribe_resource`）依赖 stateful session**，stateless 迁移后可能失效——architecture 须评估
  订阅是否纳入 V2（V1 握手封装内部、pin stable 的立场沿袭，迁移改动限于 `MCPClientManager`）。
- **DAG**：仍属 `tools/` 层（+ `engine` 治理），**禁止从 `agent/` 导入**（V1 硬约束沿袭）。
- **schema 兼容**：`annotations` 作为 `ToolSchema` 新增字段，不破坏 V1 既有映射（`inputSchema` passthrough 不变）。
- **治理 fail-safe**：annotations 缺失/不可信时按保守默认（视为需确认），不因 server 未声明而放行 destructive。

## 关键决策状态

> 2026-07-17 checkpoint 已确认结构（P3/P5）；P1/P2/P4 为 PRD 阶段用强默认值定稿的设计细节。

- **P1 · Resources 消费模型**：提案 = on-demand 内置工具（`read_resource`/`list_resources`），不自动全量注入。
  备选 = 自动注入全部 resources 进 system prompt（context 膨胀风险，不推荐）。
- **P2 · Prompts 消费模型**：提案 = CLI slash 表面（`/mcp-prompt`）。备选 = 暴露为工具让 LLM 自调（语义怪异，不推荐）。
- **P3 · Prompts 是否纳入本周期**：✅ **已确认（2026-07-17）**：纳入本周期，列为最弱腿、**Epic C 最后交付**。
- **P4 · 缺 annotations 的默认策略**：提案 = fail-safe（视为非只读 → 需确认）。备选 = 放行（危险，不推荐）。
- **P5 · 周期结构**：✅ **已确认（2026-07-17）**：**单周期、三 epic、分阶段交付**（Epic A 写操作治理最先 /
  Epic B Resources / Epic C Prompts），共用一份 architecture。

## 愿景

HeAgent 成为「**能安全连接任何 MCP server、消费全部原语的自学习 agent**」——内置工具 + 无限外接工具
（含受治理的写操作）+ Resources 上下文 + Prompts 模板 + 记忆系统五合一。再往后：MCP 工具的使用经验
（哪个任务该调哪个外部工具、写操作何时该审批）沉淀进自学习记忆——这才是 HeAgent 区别于普通 MCP client
的长期价值（Vision，不绑本周期）。

---

## 下游

- PRD（`bmad-prd`）：把本 brief 展开为 FR/NFR，定稿 P1–P5 决策。
- 架构（`bmad-architecture`）：`MCPClientManager` 扩展（annotations 透传 / Resources / Prompts）、
  `PolicyEngine` 消费 annotations 的接入点、stateless 订阅评估。
- Epics（`bmad-create-epics-and-stories`）：按 P5 结构拆 epic。
