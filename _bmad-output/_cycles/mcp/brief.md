# Product Brief — HeAgent MCP Client 集成（三阶段整合）

> **2026-08-18 整合**：本文整合原 `mcp-client/brief.md` + `brief-addendum.md`（阶段一 V1）、`mcp-v2-upgrade/brief.md` + `addendum.md`（阶段二 升级准备）、`mcp-client-v2/brief.md`（阶段三 V2）。三阶段原始 brief 均保留 `status: draft`（规划产物，非最终承诺）；决策记录见 `decision-log.md`。
> 演进主线：**V1 接上 MCP Tools 原语 → 升级准备为协议 breaking 铺路 → V2 补写操作治理 + Resources/Prompts 原语**。

---

# 阶段一 · MCP V1 集成（通用 client，Tools 原语）— 2026-06-20

## 概述

HeAgent 已是功能完整的自学习 AI Agent 框架——provider 容错链、18 个内置工具、自学习记忆、子 agent 编排、cron 调度全部落地。本次迭代给它接上 **Model Context Protocol (MCP)**：在现有工具体系之上加一层「MCP client 适配器」，让 HeAgent 能连接任意 MCP server、动态发现并调用其工具，从「自带 18 个工具」升级为「接入生态里无限的外部工具」。第一版聚焦**通用 client 能力**（只消费 MCP 的 **Tools** 原语），以 **GitHub** 为首个验收场景。

## 问题

HeAgent 当前的工具是**内置且写死**的。要接外部能力——GitHub、数据库、浏览器、第三方 API——就得为每一个手写一个 `@tool` 模块，无法复用生态里已有的成熟实现。更现实的是：**MCP 已成为 agent 工具的事实标准**（Claude Desktop / Cursor / Pydantic AI / CrewAI / LangChain / OpenAI Agents SDK 均已支持）。不接入，HeAgent 在工具生态里就是一座孤岛。

## 方案

在现有 `ToolRegistry` 之上加一层 **MCP client 适配器**（基于官方 `mcp` SDK），提供四项产品级能力：

1. **工具桥接**：MCP server 工具映射为 `ToolSchema`，注册进 `ToolRegistry`——LLM 像调用内置工具一样调用外部工具。
2. **动态发现**：连上 server 即自动拉取工具清单，无需为每个 server 手写适配。
3. **声明式配置**：`mcpServers` 声明（`{command, args, env}` for stdio / `{url, headers}` for Streamable HTTP），对齐 Claude Code / Cursor。
4. **工具去歧义**：多 server 工具名加 server 前缀作 namespace，避免冲突。

## 差异化

「做一个 MCP client」本身**并非技术壁垒**。HeAgent 的机会在两点：

1. **与自学习记忆系统的潜在整合**（MCP 工具使用沉淀成技能——**Vision 探索方向，非 V1 承诺**）。
2. **诚实的安全定位**：外部 MCP server = 运行不可信代码 + 返回不可信输出进 LLM 上下文，与 `SafetyGuard` 局限**完全同构**，明确归入既有安全声明——不假装「接了 MCP 更安全」。

**不做**：不自建 MCP server 暴露 HeAgent；不重复造 SDK 能力。

## 受众

- **主要**：HeAgent 作者（自用提效）。
- **次要**：开源用户（声明式配置接入自己的 server）。
- **非受众（V1）**：需写操作的生产用户、企业级团队、不熟 MCP 的纯终端用户。

## 成功标准

- ✅ agent 能连接外部 MCP server、**动态发现并调用**其工具（链路打通）。
- ✅ **GitHub 只读验收**：≥1 个真实 repo 的 issue / 代码搜索 E2E 跑通。
- ✅ 开源用户能声明式配置接入**任意**自己的 server（文档 + 示例）。
- ✅ 现有 18 个内置工具 + 全部既有测试**零回归**（pytest 全绿，覆盖率不降）。
- ✅ MCP 工具受与内置工具**同等安全约束**，安全声明已更新覆盖。

## 范围

**V1 In**：通用 MCP client 适配层、Tools 原语发现与调用、stdio + Streamable HTTP 双 transport、声明式 `mcpServers` 配置、GitHub 只读验收、工具 namespace 去歧义、安全声明更新。

**V1 Out（明确不做，留给后续）**：**写操作**（建 issue/提 PR → 紧接下一步）；**Resources / Prompts** 原语（后由 V2 阶段补齐）；把 HeAgent **自身暴露为 MCP server**；OAuth 2.1 完整流；MCP Registry / 目录集成。

## 技术约束 / 兼容性窗口

- 依赖官方 Python SDK（`mcp` 包），pin `mcp>=1.27,<2`（后统一为 `>=1.28,<2`）。
- 协议握手等细节封装在 `MCPClientManager` 内部，不泄漏给 `AgentLoop`，为协议演进预留接口。
- ⚠️ **时间窗口**：当前 MCP 协议 stable 为 `2025-11-25`，但 `2026-07-28` RC 是 breaking（转向 stateless、删除 `initialize` 握手）。V1 落在 stable 版，适配层设计须为迁移留接口。

## 愿景

HeAgent 成为「**能连接任何 MCP server 的自学习 agent**」——内置工具 + 无限外接工具 + 记忆系统三合一。紧接 V1 的下一步是补 GitHub 写操作（「看 + 改」完整闭环），再往后：MCP 工具使用经验沉淀进自学习记忆（长期差异化价值）。

---

# 阶段二 · MCP v1→v2 升级准备（隔离层先行）— 2026-07-12

## 概述

HeAgent 的 MCP client（`tools/mcp/`，Epic 11-13 交付）现在能连任意 MCP server、消费 Tools 原语。但官方 Python SDK `mcp` 的 **v2.0.0 stable 目标 2026-07-27**、协议规范 **2026-07-28 RC（breaking，→final）**，将重塑 client 侧 API。

本周期不接新原语，而是**兑现 `mcp-client` brief 已埋的迁移预留**——把当前 client 里会被 v2 冲刷的调用点抽象成隔离层。v2 stable 落地时，切换将局限于该层内部，Epic 11-13 零回归。

## 问题（5 个 breaking 点）

对照官方 v2 迁移指南逐行核查 `tools/mcp/` 命中的 breaking 点，共 5 个：

**设计级（语义变化，需重新设计）——最痛：**
- `session.initialize()`（manager.py:215,226）**删除**——v2 转 stateless，握手改为每请求 `_meta` 协商 + `server/discover`。`_transport_and_session` 架构要重构。
- `session.send_ping()`（manager.py:290）**deprecated**——直接冲击 **FR-3 的「运行时 ping 监测断连、自动注销工具」机制**（2026-07-01 落地），断连探测在 v2 形态下要重新设计。

**机械级（改名/改签名，隔离层直接吸收）：**
- `from mcp.types import ...`（mapping.py:18）→ v2 拆独立 `mcp-types` 包。
- `session.list_tools()`（manager.py:234）→ 签名变 + `inputSchema`→`input_schema`。
- `session.call_tool()`（manager.py:256）→ 返回字段全 snake_case。

**未命中**（未接 Resources 原语，v2 这块 breaking 不影响 HeAgent）：`subscribe_resource`/`read_resource`/`AnyUrl`/`get_server_capabilities`/`McpError`/`cursor`。

不准备 = v2 stable 落地时 Epic 11-13 的 MCP 集成（连接 / 发现 / 调用 / 断连探测四条链）被冲刷、可能破损。

## 方案

1. **隔离层抽象**：在 `MCPClientManager` 内隔离上述 5 个调用点（initialize 握手 / send_ping 健康探测 / list_tools / call_tool / types 导入），暴露稳定内部接口；v2 差异（含 FR-3 断连探测等价机制）封装在层内。
2. **迁移测试基线**：Epic 11-13 的 MCP 测试（`tests/test_mcp_*.py`）是回归基线，本周期所有改动须全绿。
3. **切换路径设计（不执行）**：文档化 v2 stable 落地时的切换步骤（改隔离层内部实现，外部接口不动）。实际切换视 v2 stable 落地时点（2026-07-27）另开独立任务。

## 受众

- **主要**：HeAgent 作者（自用）——确保 MCP 集成在 v2 落地后不破损、断连探测不失效。
- **次要**：开源用户——升级路径平滑，不被 breaking 冲刷。
- **非受众**：需 Resources/Prompts/写操作的用户（见范围 Out）。

## 成功标准

- ✅ v1.28.1 落地，现有 MCP 测试零回归。
- ✅ `MCPClientManager` 的 5 个 v2-sensitive 调用点被隔离层封装；隔离层对外接口签名 v1→v2 切换前后 diff 为空。
- ✅ FR-3 断连探测在 v2 形态下有等价机制设计（architecture 定型，可不含实现）。
- ✅ 切换路径文档化：v2 stable 落地时改动局限于隔离层内部。

## 范围

**In**：pin floor 提到 `mcp>=1.28.1,<2`；`MCPClientManager` 隔离层抽象（封装 5 调用点）；FR-3 断连探测 v2 等价机制**设计**（可不含实现）；迁移测试基线；v2 stable 切换路径**文档化**（不执行）。

**Out（明确不做）**：Resources / Prompts 原语（research 证伪 ROI，暂挂，v2 stable 后重评——后由阶段三实际落地）；写操作（正交，独立 spec）；实际切 v2；把 HeAgent 暴露为 MCP server。

## 技术约束

- 依赖官方 SDK，pin floor 提到 `mcp>=1.28.1,<2`（v1 线最新 stable；v2 stable 落地后再评估 pin 上界）。
- 协议 stable `2025-11-25` 落地；`2026-07-28` 仅 RC（→final），仅作设计参照，不依赖。
- 隔离层不引入 v2 alpha 依赖——纯 v1 上做抽象，为 v2 留形。

## 愿景

HeAgent 成为「能跟随 MCP 协议演进、不被 breaking 冲刷的稳定 client」。v2 stable 后切换只动隔离层。

---

# 阶段三 · MCP Client V2（写操作治理 + Resources/Prompts）— 2026-07-17

## 概述

> **本周期 = V1（阶段一，Tools-only，已冻结交付）的延续。** 把 V1 刻意冻结的三处缺口补齐，落在既有 `MCPClientManager` 扩展点上，**不重写 V1、不破坏既有不变量**：从「能调只读 MCP 工具」升级为「能安全调写工具 + 消费全部 MCP 原语」。

## 问题（三处缺口）

1. **写操作无治理**：`call_tool` 机制对只读 `search_code` 与 destructive `delete_repository` 一视同仁，LLM 选了就执行，无审批、无 allow-list、无危险分级。这与「确定性逻辑交给代码、不交给概率模型」硬约束冲突。MCP 2026-03 引入 **tool annotations 风险词汇**（`readOnlyHint` / `destructiveHint` / `idempotentHint` / `openWorldHint`）→ 写操作治理 = **把 `Tool.annotations` 透传进 `ToolSchema` → 喂 `PolicyEngine`**（destructive→审批 / readOnly→放行 / 缺省 fail-safe）。
2. **Resources 原语未消费**：V1 defer 理由「主流框架也尚未接入」已过时（2026-07 Claude Desktop 与 Cursor 均已支持）。Resources 是 application-controlled 原语（URI 寻址、幂等无副作用、可订阅）。
3. **Prompts 原语未消费**：user-controlled 原语（Claude Desktop 表现为 slash command）。**最弱一条腿**（与 context-files 自动加载 + 自学习记忆语义重叠，且依赖 CLI 改动）。

## 方案（三条腿，全部复用 V1 `MCPClientManager` 扩展点）

1. **写操作治理（annotations → PolicyEngine）**：`mapping.mcp_tool_to_schema` 透传 `Tool.annotations` 进 `ToolSchema`（新增字段不破坏 V1 兼容）；`engine/PolicyEngine` 消费（destructive→审批复用既有 approval 路径、readOnly→放行、缺省 fail-safe）；立场延续——**治理闸门非真正安全边界**，须 OS 级沙箱兜底。
2. **Resources 消费**：`[DECISION PROPOSAL P1]` 暴露 `list_resources` / `read_resource` 为**内置工具**（on-demand：LLM 按需取指定 URI），**不自动全量注入上下文**（规避 R3 上下文侵蚀）。订阅（`subscribe_resource`）与 stateful 依赖 → defer。
3. **Prompts 消费**：`[DECISION PROPOSAL P2]` CLI slash 表面（`/mcp-prompt ...`）渲染模板 → 注入为 user message；`list_prompts` 供发现/补全。Epic C 最后交付（最弱腿）。

## 差异化

1. **写操作治理的确定性**：把「这个 MCP 调用危不危险」交给 annotations + `PolicyEngine` 确定性裁决，而非让 LLM 判断或对所有写工具一刀切确认。
2. **诚实安全立场的延续**：治理闸门不宣称「更安全」——annotations 是 server 自声明（可谎报），与 DP-4 围栏同构，defense-in-depth 标记，须 OS 级沙箱兜底。

**不做**：不把 HeAgent 暴露为 MCP server（继承 V1）；不重复造 SDK 能力；不做 Resources 自动全量上下文注入（on-demand only）。

## 受众

- **主要**：HeAgent 作者——让 agent 不只能读 GitHub，还能**建 issue / 提 PR**，且 destructive 操作有审批不裸跑。
- **次要**：开源用户——经 Resources/Prompts 消费自己 server 暴露的上下文与模板。
- **非受众（V2）**：需要 OAuth 2.1 完整流的企业远程 server 用户、需要 MCP Registry 目录的用户。

## 成功标准

- ✅ **写工具受治理**：`destructiveHint=true` 走 `PolicyEngine` 审批不裸调；`readOnlyHint=true` 放行；缺 annotations 保守默认。
- ✅ **Resources 可发现 + 读取**：`list_resources` / `read_resource` 经 `ToolResult` 桥接，E2E 可断言。
- ✅ **Prompts 可列举 + 渲染**：`list_prompts` + `/mcp-prompt` 渲染注入，E2E 可断言。
- ✅ **零回归**：V1 全部 MCP 测试 + 18/19 内置工具 + 既有测试全绿，覆盖率不低于基线。
- ✅ **治理确定性**：annotations → PolicyEngine 路径**不依赖 LLM 判断**（单测可证）。
- ✅ **安全声明更新**：覆盖写操作治理 + Resources/Prompts 返回内容同等不可信。

## 范围

**V2 In**：写操作治理（annotations 透传 → PolicyEngine 裁决）；Resources 原语（发现 + on-demand 读取）；Prompts 原语（列举 + CLI 渲染注入）；GitHub 写操作验收（沙箱 repo 建 issue 走审批）；安全声明更新。

**V2 Out（明确不做）**：HeAgent 暴露为 MCP server（继承 V1）；OAuth 2.1 完整流（继承 V1）；MCP Registry 集成（继承 V1）；Resources 自动全量上下文注入（on-demand only）；Resources 订阅（`subscribe_resource`，与 stateless 冲突则 defer）；用户可配置注入签名入口（DP-4 硬化项，**正交，独立 spec 跟踪**）；`sampling` / `elicitation` 等反向能力；MCP 工具使用经验沉淀进自学习记忆（Vision）。

## 技术约束 / 兼容性窗口

- **SDK**：沿用 `mcp>=1.27,<2`（V1 NFR-3 沿袭）；`ClientSession` 已暴露 `list_resources`/`read_resource`/`list_resource_templates`/`subscribe_resource`/`list_prompts`/`get_prompt`，且 `Tool.annotations: ToolAnnotations(readOnlyHint, destructiveHint, idempotentHint, openWorldHint)`。
- **协议窗口 ⚠️**：stable `2025-11-25`；`2026-07-28` RC 转 stateless。Resources 订阅（有状态）可能失效——architecture 评估是否纳入（后 defer）。
- **DAG**：仍属 `tools/` 层（+ `engine` 治理），**禁止从 `agent/` 导入**（V1 硬约束沿袭）。
- **schema 兼容**：`annotations` 作为 `ToolSchema` 新增字段，不破坏 V1 既有映射。
- **治理 fail-safe**：annotations 缺失/不可信时按保守默认（视为需确认），不因 server 未声明而放行 destructive。

## 关键决策状态

> 2026-07-17 checkpoint 已确认结构（P3/P5）；P1/P2/P4 为 PRD 阶段用强默认值定稿的设计细节（详见 `decision-log.md` 与 `prd.md`）。

- **P1 · Resources 消费模型**：提案 = on-demand 内置工具（`read_resource`/`list_resources`），不自动全量注入。备选 = 自动注入（context 膨胀风险，不推荐）。
- **P2 · Prompts 消费模型**：提案 = CLI slash 表面（`/mcp-prompt`）。备选 = 暴露为工具让 LLM 自调（语义怪异，不推荐）。
- **P3 · Prompts 是否纳入本周期**：✅ **已确认**：纳入，列为最弱腿、**Epic C 最后交付**。
- **P4 · 缺 annotations 的默认策略**：提案 = fail-safe（视为非只读 → 需确认）。备选 = 放行（危险，不推荐）。
- **P5 · 周期结构**：✅ **已确认**：**单周期、三 epic、分阶段交付**（Epic A 写操作治理最先 / Epic B Resources / Epic C Prompts），共用一份 architecture。

## 愿景

HeAgent 成为「**能安全连接任何 MCP server、消费全部原语的自学习 agent**」——内置工具 + 无限外接工具（含受治理的写操作）+ Resources 上下文 + Prompts 模板 + 记忆系统五合一。再往后：MCP 工具使用经验沉淀进自学习记忆（Vision，不绑本周期）。

---

# 技术速览（Addendum 整合）

> 三阶段 addendum 的技术深度合并如下，供下游 PRD / architecture 直接取用。MCP 规范 / SDK 在 2025-2026 变动剧烈，引用前建议复核最新版。

## 协议版本线（日期戳即版本号）

| 版本 | 要点 |
|---|---|
| 2024-11-05 | 初版（HTTP+SSE + stdio） |
| 2025-03-26 | 引入 Streamable HTTP |
| 2025-06-18 | 定稿 Streamable HTTP + OAuth 2.1 + structured output + elicitation；**废弃 HTTP+SSE** |
| **2025-11-25** | **当前 stable**（HeAgent 落点） |
| 2026-07-28 (RC→final) | **breaking**：转 stateless、删 `initialize` 握手与 `Mcp-Session-Id`（SEP-2575/2567，2026-05-21 locked）；Roots/Sampling/Logging 标注式 deprecated（SEP-2577，宽限 ≥12 个月）；资源未找到码 `-32002`→`-32602`（SEP-2164） |

## Transport

- **stdio**：本地子进程，client 管理生命周期，无 HTTP。
- **Streamable HTTP**：单端点 POST/GET，可选 SSE 流式响应，支持 stateful/stateless、resumability。
- 旧 HTTP+SSE：**已废弃**（2025-06-18）。

## 三原语语义边界

- **Tools**（model-controlled）：LLM 自主调用，有副作用（≈ POST）。`tools/list` 发现、`tools/call` 执行。← V1 只接这个；V2 补全后三原语全消费。
- **Resources**（application-controlled）：宿主决定注入上下文，幂等无副作用（≈ GET），URI 寻址，可订阅。
- **Prompts**（user-controlled）：用户触发的可复用模板。
- 可选 capability：`sampling` / `logging` / `roots` / `elicitation`。

## 官方 Python SDK（`mcp` 包）

- 仓库：modelcontextprotocol/python-sdk（23.4k★）；PyPI `mcp`，**stable v1.28.0（2026-06-16）**，v1 线最新 1.28.1；v2 仅 alpha（2.0.0a1，2026-06-11；b1 用于 POC），stable v2 目标 2026-07-27。
- **依赖建议**：`mcp>=1.28,<2`（v1 期）→ `mcp>=1.28.1,<2`（升级期 bump floor）。v2 + 协议 2026-07-28 双 breaking。
- 原生 asyncio，全异步。Client 核心 API：`mcp.ClientSession` / `StdioServerParameters` / `stdio_client` / `streamable_http_client`。
- **v1→v2 breaking 命中核查（升级周期 addendum §3）**：命中 5 项（manager.py 4 + mapping.py 1）：`list_*(cursor=)`→`params=PaginatedRequestParams`、`mcp_types` camelCase→snake_case（`inputSchema`→`input_schema` 等）、`mcp.types` 拆独立 `mcp-types` 包、`send_ping()` deprecated、`initialize`/`initialized` 握手删除。未命中：`read_resource/subscribe_resource`（AnyUrl→str）、`subscribe_resource`→`client.listen`、`get_server_capabilities` 删、`McpError→MCPError`、timeout 类型、`Client` 默认 `mode='auto'`、实验性 Tasks 全删。

## 各框架适配模式（可借鉴）

- **LangChain**：`langchain-mcp-adapters`，`MultiServerMCPClient` + `load_mcp_tools()`。
- **Pydantic AI**：`MCPServerStdio` / `MCPServerStreamableHTTP` 挂 `Agent(mcp_servers=[...])`。**只支持 Tools**（V1 决策 D2 的生态佐证）。
- **OpenAI Agents SDK**：`MCPServerStdio/StreamableHTTP/Sse`。
- **CrewAI**：`crewai-tools` 暴露 MCP server 为 tool。
- **Claude Code / Desktop**：`.mcp.json` / `claude mcp add` 声明 `mcpServers`。← **配置形态标杆**
- **通用可借鉴模式**：① ClientSession → 框架 ToolSchema 适配层；② 多 server namespacing；③ 生命周期与 agent run 绑定；④ 声明式 JSON 配置。

## 为何 Resources/Prompts 在升级周期暂挂（生态依据，阶段三落地前的存量证据）

**框架侧**：Pydantic AI / CrewAI 均 tools-only；OpenAI Agents SDK Resources 进行中（PR）；LangChain / FastMCP Client 双支持。**server 生态**：filesystem / postgres / memory 有 Resources；Prompts 基本只出现在 demo server（Everything）。两极分化且同向——tools 压倒性主导。后因 Claude Desktop / Cursor 均支持 Resources，阶段三将 Resources/Prompts 纳入落地。

## GitHub MCP server（首个验收）

- 官方：github.com/github/github-mcp-server（Go），remote（Streamable HTTP 托管）+ 本地 Docker 两种形态。
- 工具集：repos / issues / pull_requests / code_search / users 等（几十个）。
- 鉴权：GitHub Personal Access Token。

## FR-3 断连探测 v2 等价机制候选（供架构选型）

**现状（v1）**：`_watch`（manager.py:272）每 `_health_check_interval` 秒 race `stop.wait()` vs `session.send_ping()`；ping 失败/超时 → 注销该 server 全部工具（FR-3 收紧，2026-07-01 落地）。

**候选**：
- **A. call_tool 失败即注销（被动）**——下次调用时 `call_tool` 抛错 → 注销。延迟发现，但零额外开销、与 stateless 契合。
- **B. `server/discover` 周期探测（主动）**——v2 新方法，保持主动语义，但依赖 v2 API（v1 上只能设计）。
- **C. 过渡占位**——v1 隔离层保留 ping 调用，v2 切换时改实现。

→ 架构选型：**C 过渡占位（v1）+ v2 切 A 被动**（见 `architecture.md` 阶段二 AD-3）。

## 已知坑（须在 architecture 应对）

- **安全/信任**：MCP server = 不可信代码 + 不可信输出进 LLM 上下文，无隔离。→ 归入既有安全声明。
- **stdio 子进程生命周期**：spawn / 监控 / 优雅关闭、僵尸进程、env 泄漏。→ `AsyncExitStack` 托管。
- **工具数量爆炸**：每 server 10-50+ tools。→ 复用 `ContextCompressor` + lazy `list_tools` + namespace。
- **Resources vs Tools 边界模糊**：V1 只接 Tools（V2 按 on-demand 补齐）。
- **SDK breaking 风险**：握手/协议封装在 `MCPClientManager` 内部，迁移改动局部化。

## 关键链接

- 协议规范：https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle
- Python SDK：https://github.com/modelcontextprotocol/python-sdk · https://pypi.org/project/mcp/
- v2 迁移指南（权威 breaking 清单）：https://py.sdk.modelcontextprotocol.io/v2/migration/
- 协议 RC 博文：https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/
- Servers：https://github.com/modelcontextprotocol/servers
- Registry：https://modelcontextprotocol.io/registry/about
- LangChain 适配器：https://github.com/langchain-ai/langchain-mcp-adapters
- Pydantic AI：https://pydantic.dev/docs/ai/mcp/client/
- 安全最佳实践：https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices
