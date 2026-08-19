# `_bmad-output/` 导航

本目录是 HeAgent 用 **BMad Method** 驱动迭代留下的**规划产物**（brief / prd / architecture / epics / stories / 补丁 / 回顾）。它是迭代历程的事实来源之一，**不是当前代码事实**——当代码与本文档冲突时，以 `src/` 实现为准（参见 `docs/frame.md`、`docs/iteration.md`）。

> **BMad config 对齐说明：** `_bmad/config.toml [modules.bmm]` 与 `_bmad/bmm/config.yaml`（installer 托管）声明 `planning_artifacts` / `implementation_artifacts` 指向 `_bmad-output/{planning,implementation}-artifacts/`——**这两个目录在本仓不存在**。HeAgent 刻意按周期而非按产物类型组织（见下方目录结构）。这两个 key 维持 installer 默认、不在 `_bmad/custom/config.toml` 覆盖：同类路径 override 经验证不生效（同 `output_folder` 上游 bug，见 commit `01fbe13`），且 quick-dev 假设的「扁平 `implementation_artifacts`」与本仓 cycle 布局结构不兼容（`sprint-status.yaml` 在 `baseline/`、`deferred-work.md` 在 `patches/`、spec 在 `specs/`，无单一目录可满足）。**实际产物位置以本文件为权威。**

## 目录结构（按周期）

```
_bmad-output/
├── EPICS-INDEX.md          Epic 总目录（2026-08-19 重组：全 epic 主题/状态/story/patch 映射）
├── consolidated-overview.md  统一整合总览（全周期综合摘要，2026-08-18）
├── retrospective-all-cycles.md  全周期综合回顾（2026-07-22，Epic 1-23 + S1-S4）
├── epic-01-…/epic-14-…/…   按 epic 归档的 story 目录（epic-NN-主题/stories/，仅建有 story 的 epic）
├── _cycles/                周期级规划文档（prd / brief / architecture / epics / sprint-status / reviews）
│   ├── baseline/           主线周期（Epic 1–10，FR-1~24）
│   ├── mcp/                MCP Client 集成周期（三阶段：Epic 11-13 / 14 / 15-18，2026-08-18 合并）
│   ├── sandbox-hardening/  Sandbox 硬化周期（Epic S1–S4）
│   ├── robustness-hardening/ 健壮性与质量硬化周期（Epic 19–20）
│   ├── quality-engineering/ 质量工程深化周期（Epic 21–24）
│   ├── gui/                GUI 终端界面周期（Epic 25–28）
│   └── interaction/        交互与可扩展层周期（Epic 29–35）
├── patches/                补丁周期（计划外技术债 / 缺陷，跨周期扁平；epic 映射见 EPICS-INDEX.md）
└── specs/                  quick-dev / spec 产物（本地工作件，gitignored；2026-08-18 已清空，目录暂不存在）
```

> **2026-08-19 重组**：原顶层周期目录（baseline/ 等）移入 `_cycles/`，story 文件按 epic 移入 `epic-NN-主题/stories/`。各 epic 的文档与 patch 映射见 [`EPICS-INDEX.md`](EPICS-INDEX.md)。

## sprint-status 单一权威

**全周期 sprint 状态统一在 `_bmad-output/_cycles/baseline/sprint-status.yaml`。**

2026-07-23 整合：此前 sprint-status 分散在 6 个文件（`baseline/`、`mcp-client-v2/`、`sandbox-hardening/`、`robustness-hardening/`、`quality-engineering/`、`gui/`），存在 Epic 14 编号冲突。合并后的编号规则（2026-08-18 MCP 三目录合并后，周期列更新为 `mcp/`）：

| 起始编号 | 周期 | 说明 |
|---------|------|------|
| Epic 1–10 | baseline | 主线 MVP + 自学习闭环 |
| Epic 11–13 | mcp（阶段一） | MCP 工具桥接 + GitHub E2E + 安全声明 |
| Epic 14 | mcp（阶段二） | MCP v1→v2 升级准备（pin / 隔离层 / 测试基线） |
| Epic 15–18 | mcp（阶段三） | 写操作治理 / Resources / Prompts / 内置工具扩展 |
| Epic S1–S4 | sandbox-hardening | Sandbox profile 映射 / 降级 / 配置入口 / 进程组 kill / workspace 隔离 |
| Epic 19–20 | robustness-hardening | 文件锁 / Cron 范围 / WinJobBackend / 覆盖率 90% |
| Epic 21–24 | quality-engineering | Coverage 工程化 / Benchmark / Docker 硬化 / CI 安全 |
| Epic 25–28 | gui | GUI 终端界面（流式聊天 / 工具可视化 / 管理面板 / 可观测性） |

各自周期目录下的旧 sprint-status 保留作为只读归档；后续状态更新以 `_cycles/baseline/sprint-status.yaml` 为唯一写目标。

## _cycles/baseline/ — 主线周期（Epic 1–10，FR-1~24）

| 文件 | 用途 |
|------|------|
| `brief.md` / `brief-decision-log.md` | 产品意图与边界、brief 阶段决策记录 |
| `prd.md` / `prd-decision-log.md` | 功能需求（FR/NFR）、prd 阶段决策记录 |
| `architecture.md` | 技术架构与冻结决策（交叉引用 frame.md） |
| `epics.md` | Epic 1-5（MVP，FR-1~19）拆分 + 覆盖矩阵 |
| `epics-self-learning.md` | Epic 6-10（自学习闭环，FR-20~24）拆分 |
| `sprint-status.yaml` | **全周期 story/epic 状态流转与 action_items 跟踪**（事实来源，含 8 个周期） |
| `epic-01-基础设施与LLM通信/stories/`（1-1~1-5） | Epic 1 的可执行 story（含 AC，2026-08-19 移出） |

## _cycles/mcp/ — MCP Client 集成周期（三阶段统一，2026-08-18 合并）

> 原三个目录 `mcp-client/`（Epic 11-13）、`mcp-v2-upgrade/`（Epic 14）、`mcp-client-v2/`（Epic 15-18）已于 2026-08-18 合并为 `mcp/`，核心文档按类型整合、执行产物原样保留。导航与编号对照见 `_cycles/mcp/README.md`。

| 文件 | 用途 |
|------|------|
| `README.md` | MCP 周期导航（三阶段总览 + 编号体系对照 + 安全立场） |
| `brief.md` | 产品简报（整合）：V1 通用 client / v2 升级准备 / V2 治理与原语 + 技术 addendum |
| `prd.md` | 产品需求（整合）：FR-1~11（V1）+ FR-1~5（升级）+ FR-A~C（V2）+ 全部 NFR/SM/UJ/OQ |
| `architecture.md` | 架构决策（整合）：决策 A-H（V1）+ AD-1~6（升级隔离层）+ AD-1~8（V2 治理桥接） |
| `epics.md` | Epic/Story 拆分（整合）：Epic 11-13 / 14 / A-C（15-18）+ 覆盖矩阵 |
| `decision-log.md` | 决策记录（整合）：D1-7 / DP-1~6 / P1-P5 / OQ-1~6 |
| `retrospective-epic-13.md` | Epic 13 回顾（已完成） |
| `poc-readiness-report.md` | 升级周期 POC 就绪度报告（v2 b1 实装验证） |
| `sprint-status.yaml` | 已归档 — 见 `_cycles/baseline/sprint-status.yaml` |
| `epics-integration.md` | 历史归档（2026-06-03 Epic 6 集成补丁，非 MCP 内容，编号已被占用） |
| `epic-14/15/16-*/stories/` | V2 周期 story 文件（14-x/15-x/16-x，2026-08-19 移出至按 epic 目录） |
| `reviews/_v1/` `reviews/_upgrade/` `reviews/_v2/` | 三阶段评审产物（PRD rubric / 对抗评审 / 事实核查） |

## _cycles/sandbox-hardening/ — Sandbox 硬化周期（Epic S1–S4）

| 文件 | 用途 |
|------|------|
| `ARCHITECTURE-SPINE.md` | 硬化架构脊架 |
| `epics.md` | Epic S1–S4 拆分 |
| `sprint-status.yaml` | 已归档 — 见 `_cycles/baseline/sprint-status.yaml` |

## _cycles/robustness-hardening/ — 健壮性与质量硬化周期（Epic 19–20）

| 文件 | 用途 |
|------|------|
| `ARCHITECTURE-SPINE.md` | 架构脊架 |
| `epics.md` | Epic 19–20 拆分（原内部编号 18–19） |
| `sprint-status.yaml` | 已归档 — 见 `_cycles/baseline/sprint-status.yaml` |

## _cycles/quality-engineering/ — 质量工程深化周期（Epic 21–24）

| 文件 | 用途 |
|------|------|
| `architecture.md` | 架构设计 |
| `epics.md` | Epic 21–24 拆分（原内部编号 20–23） |
| `sprint-status.yaml` | 已归档 — 见 `_cycles/baseline/sprint-status.yaml` |

## _cycles/gui/ — GUI 终端界面周期（Epic 25–28）

| 文件 | 用途 |
|------|------|
| `brief.md` | GUI 产品意图 |
| `prd.md` | FR-G1~G24 |
| `architecture.md` | GUI 架构（Textual + bridge + 状态管理） |
| `epics.md` | Epic 25–28 拆分（原内部编号 24–27） |
| `sprint-status.yaml` | 已归档 — 见 `_cycles/baseline/sprint-status.yaml` |

## patches/ — 补丁周期（跨周期扁平）

| 文件 | 用途 |
|------|------|
| `deferred-work.md` | **跨周期技术债登记**：spec 边界外的 defer 项 + Resolution 收尾记录 |
| `p0-provider-hardening.md` | P0 Provider 加固 spec（异常分类/包装/容错） |
| `p0-hardening-review-diff.txt` | P0 加固的评审 diff（过程产物） |
| `3-3-token-counter.md` | token 计数器补丁 spec |
| `5-1-subagent-context-injection.md` | 子 Agent 上下文注入补丁 spec |
| `epic-5-context.md` | Epic 5 上下文相关补丁 |
| `fr3-mcp-auto-unregister.md` | FR-3 MCP 运行时断连 auto-unregister spec（2026-07-01 交付） |
| `retrospective-engine-p5.md` | engine P5 轻量回顾 |
| `retrospective-p0-tech-debt.md` | P0 技术债收尾回顾 |
| `spec-cron-stop-timeout.md` | CronScheduler.stop 关停硬上界 spec |
| `spec-deferred-low-cleanup.md` | deferred-work 低优先级清理 spec |
| `spec-dp4-mcp-result-guard.md` | DP-4 第二半 — MCP 返回内容启发式围栏 spec |
| `spec-dp4-mcp-safety-guard.md` | DP-4 第一半 — 执行前工具名拦截 spec |
| `spec-engine-sandbox-backend.md` | engine sandbox 后端抽象 spec |
| `spec-mcp-shutdown-timeout.md` | MCP `__aexit__` 关停硬上界 spec |
| `spec-sandbox-cancel-signal-preservation.md` | CancelledError 不吞取消信号 spec |
| `spec-sandbox-reap-robustness.md` | sandbox reap 鲁棒性 spec |
| `spec-sandbox-timeout-validation.md` | sandbox timeout 正整数校验 spec |
| `cli-status-bar.md` | CLI 状态栏补丁 spec |
| `code-review-2026-07-20.md` | 2026-07-20 全面代码审查记录 |
| `spec-business-data-integration.md` | 业务数据集成 spec |
| `spec-dreaming-defer-cleanup.md` | dreaming defer 项清理 spec |
| `spec-dreaming-memory-consolidation.md` | Dreaming 模式（离线记忆巩固）实现 spec |
| `spec-mcp-user-injection-signatures.md` | MCP 返回内容围栏用户可配置签名入口 spec（deferred） |
| `spec-steering-followup.md` | 方向选择 follow-up spec |

## 当前状态摘要

- **Epic 1–24 + S1–S4 全部 `done`**（详见 `_cycles/baseline/sprint-status.yaml`）。
- **Epic 25–28（GUI）`done`**（12 stories，见 `_cycles/baseline/sprint-status.yaml`；周期目录旧状态为规划期快照）。
- **MCP 三目录已合并**（2026-08-18）：`mcp-client/` + `mcp-v2-upgrade/` + `mcp-client-v2/` → `mcp/`，核心文档整合为 6 份，执行产物保留。
- **deferred-work.md**：原 3 条（SubAgent 写竞态 / ProviderChain 双层重包 / 流式 backstop）均已关闭；2026-07-01 FR-3 评审另增 6 项 `defer`（pre-existing / spec 显式排除 / 非阻塞）—— 4 项已 Resolution 关闭，余 2 项保持现状（`_watch` 两个 `wait_for` 同名异义 / `except Exception` 过宽，待 MCP 重连场景收窄）。
- **action_items**：三项全 `closed` —— FR-3 auto-unregister（2026-07-01）、DP-4 第一半 SafetyGuard 执行前拦截（2026-07-08）、DP-4 第二半 MCP 返回内容启发式围栏（2026-07-10）。
- **补丁系列**：sandbox 健壮性系列（timeout 正整数校验 / CancelledError 不吞取消信号 / reap 鲁棒性）、关停硬上界三件套（MCP `__aexit__` / `CronScheduler.stop` / sandbox reap）、compressor 孤儿 TOOL 消息修复均已交付。
- **epic 外增量**：`engine/` 运行时治理层（P0-P5）不挂 Epic 编号，进度记入 `docs/frame.md` 4.12。

## 阅读建议

第一次进入：`docs/iteration.md`（迭代历程总览）→ [`consolidated-overview.md`](consolidated-overview.md)（全周期统一整合总览）→ 本文件（产物地图）→ 按需查具体周期的 brief/prd/epics。
