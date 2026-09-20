# `_bmad-output/epics/epic-11-18-MCP集成周期/` — MCP Client 集成周期（统一目录）

> **2026-08-18 整合**：原三个独立目录 `mcp-client/`（Epic 11-13，MCP V1 集成）、`mcp-v2-upgrade/`（Epic 14，v1→v2 升级准备）、`mcp-client-v2/`（Epic 15-18，MCP Client V2）合并为本目录。核心文档（brief/prd/architecture/epics/decision-log）按类型整合为单文件（内部分阶段），执行产物（stories/reviews/retrospective/poc）原样保留。

本目录是 HeAgent **MCP Client 集成三周期**的规划产物。三个周期共享一条演进主线：**接上 MCP → 为协议演进做准备 → 补全原语与治理**。

## 三阶段总览

| 阶段 | 主线 Epic | 目录原名称 | 时间 | 主题 | 核心产物（整合后） |
|------|----------|-----------|------|------|---------------------|
| **一 · MCP V1 集成** | Epic 11-13 | `mcp-client/` | 2026-06-20 | 通用 MCP client：Tools 原语桥接（stdio + Streamable HTTP）、GitHub 只读验收、安全边界声明 | `brief.md` §一、`prd.md` §一、`architecture.md` §一、`epics.md` §一 |
| **二 · v1→v2 升级准备** | Epic 14 | `mcp-v2-upgrade/` | 2026-07-12 | 兑现迁移预留：`session_api.py` 隔离层收敛 5 个 v2-sensitive 调用点、FR-3 断连机制选型、切换路径文档化 | `brief.md` §二、`prd.md` §二、`architecture.md` §二、`epics.md` §二 |
| **三 · MCP Client V2** | Epic 15-18 | `mcp-client-v2/` | 2026-07-17 | 写操作治理（annotations → PolicyEngine）、Resources/Prompts 原语、内置 git 工具扩展 | `brief.md` §三、`prd.md` §三、`architecture.md` §三、`epics.md` §三 |

> **编号对照（重要）**：本目录内 V2 各 epic 子目录与 story 文件前缀沿用**移出前的旧编号 14–17**，与主线统一编号存在 **+1 偏移**——写操作治理 / Resources / Prompts / 内置工具扩展的权威编号是 **Epic 15/16/17/18**（顶层 [`sprint-status.yaml`](../../sprint-status.yaml)）。即磁盘 `epic-14-MCP升级准备/stories/14-x` = 权威 15-x（写操作治理）、`epic-15-写操作治理/stories/15-x` = 权威 16-x（Resources）、`epic-16-Resources发现与读取/stories/16-x` = 权威 17-x（Prompts）；Epic 17-4 与 18-x 的 story 文件未随迁移归档（仅存 git 历史）。引用一律以 sprint-status 权威编号为准。

## 文件索引

| 文件 | 用途 |
|------|------|
| `brief.md` | 产品简报（整合）：V1 通用 client 意图 / 升级准备意图 / V2 治理与原语意图 |
| `prd.md` | 产品需求（整合）：FR-1~11（V1）+ FR-1~5（升级）+ FR-A1~A7/B1~B4/C1~C4（V2）+ 全部 NFR/SM/UJ |
| `architecture.md` | 架构决策（整合）：决策 A-H（V1）+ AD-1~6（升级隔离层）+ AD-1~8（V2 治理与桥接） |
| `epics.md` | Epic/Story 拆分（整合）：Epic 11-13（8 stories）+ Epic 14（3 stories）+ Epic A/B/C（11 stories） |
| `decision-log.md` | 决策记录（整合）：brief D1-D7 / PRD DP-1~6 / V2 P1-P5 与 OQ 定稿 |
| `retrospective-epic-13.md` | Epic 13 回顾（V1 周期收尾，2026-06-29） |
| `poc-readiness-report.md` | 升级周期 POC 就绪度报告（实装 mcp 2.0.0b1 验证隔离层） |
| `sprint-status.yaml` | 旧 sprint-status 归档（mcp-client-v2 版；全周期状态以顶层 [`../../sprint-status.yaml`](../../sprint-status.yaml) 为权威） |
| `epics-integration.md` | **历史归档**：2026-06-03 的「Epic 6: AgentLoop 全模块集成」（INT-1~5），非 MCP 周期内容，编号已被占用，仅保留作历史 |
| `stories/` | Story 文件（V2 周期 9 个：A.1~A.4 / B.1~B.3 / C.1~C.3 对应原 14-x/15-x/16-x 命名） |
| `reviews/_v1/` | V1 PRD 评审 rubric |
| `reviews/_upgrade/` | 升级周期对抗评审（review-adversarial / review-rubric-facts） |
| `reviews/_v2/` | V2 周期评审（prd-review-rubric / review-adversary / review-reality-check / review-rubric） |

## 编号体系对照

| 周期 | FR 编号 | 架构决策 | Epic 编号 |
|------|---------|----------|-----------|
| V1（阶段一） | FR-1~11（独立）+ NFR-1~7 | 决策 A-H | 主线 Epic 11-13（内部 Epic 1-3） |
| 升级准备（阶段二） | FR-1~5（独立）+ NFR-1~6 | AD-1~6 | 主线 Epic 14 |
| V2（阶段三） | FR-A1~A7 / FR-B1~B4 / FR-C1~C4 + NFR-1~7 | AD-1~8（+ AR-1~10） | 主线 Epic 15-18（内部 Epic A/B/C） |

> **引用约定**：FR/AD 编号在三个阶段间存在局部重复（如 FR-1、AD-1 出现多次），跨阶段引用须写全限定，如「V1 FR-3」「升级 AD-3」「V2 FR-A3」「V2 AD-1」。各阶段内部引用可直写编号。

## 安全立场（贯穿三阶段，不随整合改变）

- 外部 MCP server = **不可信代码**（stdio 拉任意子进程 / HTTP 连任意端点），工具返回内容无围栏进 LLM 上下文（prompt injection 无隔离）——与 `SafetyGuard` 局限同构，**非真正安全边界，须 OS 级沙箱兜底**。
- MCP `Tool.annotations` 是 **server 自声明、不可信**（恶意 server 可把 `delete_repository` 谎报 `readOnlyHint=true`）；`PolicyEngine` 注解闸门仅 defense-in-depth 确定性标记。
- DP-4 两半（执行前工具名拦截 2026-07-08 + 返回内容启发式围栏 2026-07-10）已落地；返回内容经 `mapping.bridge_result`/`guard_content` 启发式扫描、命中加 warning 标记后**透传不阻断**。
- MCP 工具走与内置工具一致的 `ToolError` 语义 + 工具名黑名单预校验。

## 历史注记

- **mcp-client-v2 stories 编号偏移**：`stories/` 内文件名为原内部编号（14-1~16-3，对应内部 Epic A/B/C），与 `../../sprint-status.yaml` 的统一主线编号（15-x/16-x/17-x）存在 +1 偏移——story 文件为历史快照，编号以 sprint-status.yaml 为权威。
- **升级周期 vs V2 周期的 Epic 14 冲突**：曾有两份 Epic 14（升级准备 vs V2 内部编号），2026-07-23 整合后升级准备 = 主线 Epic 14、V2 = 主线 Epic 15-18（见 `../../sprint-status.yaml` 合并说明）。
