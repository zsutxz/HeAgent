---
title: "HeAgent MCP v1→v2 升级准备 — PRD"
status: final
created: 2026-07-12
updated: 2026-07-12
---

# HeAgent MCP v1→v2 升级准备 — 产品需求文档（PRD）

> 输入：产品 brief（`brief.md`）+ 技术速览（`addendum.md`）。本文把 brief 展开为可被架构 / epics 消费的需求。技术实现细节见 addendum。
> **承接**：兑现 `mcp-client` 周期 NFR-3（版本可控）的成功标准——「v2/stateless 迁移时改动限于 `MCPClientManager` 内部，不波及 `AgentLoop`」。
> **周期**：`mcp-v2-upgrade`（集成周期，Epic 14+）。

## 1. 背景与目标

HeAgent 的 MCP client（`tools/mcp/`，mcp-client 周期 Epic 11-13 交付）现消费 Tools 原语。官方 SDK `mcp` v2.0.0 stable（目标 2026-07-27）+ 协议 2026-07-28 RC（breaking，→final）将重塑 client API。逐行核查命中 5 个调用点（addendum §3），其中 `initialize` 删除 + `send_ping` deprecated 为设计级冲击。

**目标**：兑现 mcp-client 周期 NFR-3 已埋的迁移预留，把 5 个 v2-sensitive 调用点抽象成隔离层，使 v2 stable 落地时切换局部化、Epic 11-13 零回归。

**非目标**：Resources/Prompts 原语、写操作、实际切 v2、HeAgent 暴露为 server（见 brief 范围-Out）。

## 2. 功能需求（FR）

> 本周期独立 FR 编号空间（FR-1~5），与 mcp-client 周期 FR 独立。引用 mcp-client 周期 FR/NFR/DP 时写全限定（如 mcp-client FR-3、mcp-client NFR-3、mcp-client DP-4）。

### 2.1 依赖与隔离层

- **FR-1**：收紧 SDK pin 到 `mcp>=1.27.2,<2`（补当前 `mcp>=1.27,<2` 落后的小档；1.27.2 为 v1 线最新 stable，2026-05-29）。
- **FR-2**：在 `MCPClientManager` 内建隔离层，封装 5 个 v2-sensitive 调用点，对外暴露稳定的内部接口：
  - (a) 握手（现 `session.initialize()`，v2 删除）
  - (b) 健康探测（现 `session.send_ping()`，v2 deprecated）
  - (c) 工具发现（`session.list_tools()`，签名 + snake_case 变）
  - (d) 工具调用（`session.call_tool()`，返回 snake_case）
  - (e) 类型导入（`from mcp.types`，v2 拆 `mcp-types` 包）
  - v1 过渡形态：健康探测保留 ping 占位（对应 addendum §5 候选 C），v2 切换时改实现。

  `[ASSUMPTION: 隔离层抽象形态（protocol/adapter）留 architecture]`

### 2.2 断连探测 v2 等价机制

- **FR-3**：文档化 mcp-client FR-3（运行时 ping-watch 断连 auto-unregister）在 v2 stateless 下的等价机制选型（候选 A/B/C 见 addendum §5）。本周期只产出**设计决策**，不含实现。**安全立场不可退化**：v2 形态下断连的工具仍须主动或被动注销，不得滞留 LLM 工具列表。

### 2.3 回归与切换准备

- **FR-4**：迁移测试基线——Epic 11-13 的 MCP 测试（`tests/test_mcp_*.py`）在本周期所有改动后全绿，作为隔离层不破现有的验证。
- **FR-5**：文档化 v2 stable 落地时的切换路径（改隔离层内部实现、外部接口不动；FR-3 等价机制从候选 C 过渡到选定方案的实现步骤）。本周期只产出**路径文档**，不含实际切换执行。

## 3. 非功能需求（NFR）

- **NFR-1（零回归）**：Epic 11-13 MCP 集成测试全绿，以 FR-4 基线为零回归上限；既有功能不破坏。
- **NFR-2（封装局部化）**：隔离层对外接口签名在 v1→v2 切换前后保持不变（diff 为空）——兑现 mcp-client NFR-3 成功标准。
- **NFR-3（不可信边界立场延续）**：mcp-client DP-4 两半（执行前工具名拦截 + 返回内容启发式围栏）不因升级退化；CLAUDE.md 安全声明无需为升级削弱。
- **NFR-4（纯 v1 准备）**：不引入 v2 alpha 依赖；隔离层在 v1 上做抽象，为 v2 留形。
- **NFR-5（继承约束）**：异步（库代码无同步 I/O）+ DAG（tool 层禁从 `agent/` 导入），见 CLAUDE.md 与 §5。
- **NFR-6（可观测）**：隔离层调用、握手、健康探测有日志（标准库 logging）。

## 4. 成功指标

| 指标 | 目标 | 反指标 |
|---|---|---|
| 零回归 | `tests/test_mcp_*.py` 全绿（含 mcp-client DP-4 用例） | 新增 bug / 既有用例红 |
| 封装局部化 | 隔离层对外接口 v1→v2 diff 为空 | 切换波及 `AgentLoop` |
| FR-3 等价机制就绪 | v2 形态断连探测有等价设计 | 工具滞留 LLM 列表 |
| 切换就绪 | 切换路径文档化 | 实际切 v2（本周期不做，反指标） |

> NFR-3（DP-4 不退化）由「零回归」行覆盖——DP-4 相关测试在 `tests/test_mcp_*.py` 内，全绿即不退化。

## 5. 约束与依赖

- SDK pin `mcp>=1.27.2,<2`（v2 stable 后评估上界）。1.27.2 依据 research（PyPI history，v1 线最新 stable 2026-05-29）；注：mcp-client prd §6 写「v1.28.0 stable」为笔误（无此版本），本周期以 research 为准。
- 协议 stable `2025-11-25`；RC `2026-07-28` 仅设计参照。
- 架构 DAG：MCP 隔离层属 `tools/mcp/`，禁从 `agent/` 导入。
- 安全：受 CLAUDE.md 文首声明约束（继承 mcp-client 立场）。

## 6. 风险

- **R1（隔离层过度抽象）**：为预见 v2 形态而抽象过深，增加当前复杂度。缓解：只隔离已命中的 5 个点，不为未命中的 breaking 预抽象。
- **R2（FR-3 选型悬空）**：v2 等价机制只设计不实现，若 architecture 选型拖延，切换时 FR-3 是最痛的点。缓解：architecture 阶段必须定选型。
- **R3（v2 stable 跳票）**：若 2026-07-27 v2 stable 未如期，本周期「准备」仍有效（v1 隔离层不依赖 v2），但切换延后。缓解：纯 v1 准备边界使本周期交付不依赖 v2 时点。

## 7. 决策定稿记录

> `[ASSUMPTION]` 待 architecture 定稿：

1. ⏳ 隔离层抽象形态（protocol/adapter）——留 architecture。
2. ⏳ FR-3 等价机制选型（A/B/C）——留 architecture。

> 已定稿：FR 编号独立空间 FR-1~5 + 全限定引用（见 §2 header note）；mcp-client prd §6 的「v1.28.0」笔误不改原文，本周期 prd §5 留注为准。

## 8. 下游

- 架构（`bmad-architecture`）：隔离层抽象形态、FR-3 选型、迁移路径细化。
- Epics & Stories（`bmad-create-epics-and-stories`）：按 FR 拆 Epic 14+。
