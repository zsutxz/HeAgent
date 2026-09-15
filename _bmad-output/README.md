# `_bmad-output/` 导航

本目录是 HeAgent 用 **BMad Method** 驱动迭代留下的**规划产物**（brief / prd / architecture / epics / stories / 补丁 / 回顾）。它是迭代历程的事实来源之一，**不是当前代码事实**——当代码与本文档冲突时，以 `src/` 实现为准（参见 `docs/frame.md`、`docs/iteration.md`）。

> **BMad config 对齐说明：** `_bmad/config.toml [modules.bmm]` 与 `_bmad/bmm/config.yaml`（installer 托管）声明 `planning_artifacts` / `implementation_artifacts` 指向 `_bmad-output/{planning,implementation}-artifacts/`。本仓没有 `planning-artifacts/`；`implementation-artifacts/` 仅保留工作流的**活动**台账 [`deferred-work.md`](implementation-artifacts/deferred-work.md)（未闭合项），已闭合项按归属 epic 归档到各周期目录的 `deferred-work.md`，已完成的实现 spec 按所属 Epic 归档。全周期状态唯一写目标是根目录 [`sprint-status.yaml`](sprint-status.yaml)，不是某个周期子目录。部分旧周期保留只读状态快照，新增周期不保证含独立 `sprint-status.yaml`。HeAgent 刻意按周期而非按产物类型组织（见下方目录结构）。

## 目录结构（按周期）

```
_bmad-output/
├── consolidated-overview.md  统一整合总览（全周期综合摘要 + epic 总目录；原 EPICS-INDEX.md 已并入，2026-08-19）
├── retrospective-all-cycles.md  全周期综合回顾（2026-07-22 生成 / 2026-09-15 扩充至 Epic 1-47 + S1-S4）
├── implementation-artifacts/ 活动件：未闭合 deferred 台账（deferred-work.md）+ 未启动的母规划 spec（spec-business-data-integration.md）
├── epics/                  按周期组织（2026-08-19）：周期目录（epic-区间-周期/）内含周期文档 + 各 epic 的 story 子目录（epic-NN-主题/stories/，仅建有 story 的 epic）+ 已闭合遗留项台账（各周期 deferred-work.md）
│   ├── epic-01-10-主线规划周期/   baseline 周期文档（Epic 1–10，FR-1~24）+ epic-01-基础设施与LLM通信/
│   ├── epic-11-18-MCP集成周期/    mcp（三阶段：11-13 / 14 / 15-18，2026-08-18 合并）
│   ├── epic-S1-S4-沙箱硬化周期/   sandbox-hardening（Epic S1–S4）
│   ├── epic-19-20-健壮性硬化周期/ robustness-hardening（Epic 19–20）
│   ├── epic-21-24-质量工程周期/   quality-engineering（Epic 21–24）
│   ├── epic-25-28-GUI界面周期/    gui（Epic 25–28）
│   ├── epic-29-35-交互扩展周期/   interaction（Epic 29–35）
│   ├── epic-36-39-文件安全防护周期/ credential and file safety（Epic 36–39）
│   ├── epic-40-沙箱会话化周期/     sandbox sessions（Epic 40）
│   ├── epic-41-目标驱动开发周期/   goal-driven development（Epic 41）
│   ├── epic-42-BMad技能包运行时周期/ skill package runtime（Epic 42）
│   ├── epic-43-46-目标级工作流周期/ goal workflow continuation（Epic 43–46）
│   └── epic-47-声明式BMad敏捷工作流周期/ declarative BMad workflow（Epic 47）
└── specs/                  quick-dev / spec 产物（本地工作件，gitignored；2026-08-18 已清空，目录暂不存在）
```

> **2026-08-19 起持续重组**：`epics/` 按周期组织；当前共有 13 个周期目录（`epic-区间-周期/`），收纳周期级 prd/brief/architecture/epics/sprint-status，**各 epic 的 story 子目录（`epic-NN-主题/stories/`）嵌套在所属周期目录内**；**补丁 spec 按归属 epic 归档进 `epic-NN-主题/`**（原 `patches/` 按领域分子目录于 2026-09-15 解散，映射见本文件「补丁 spec」节）。各 epic 的状态矩阵与文档地图见 [`consolidated-overview.md`](consolidated-overview.md)（原 EPICS-INDEX.md 已并入其导航层）。

## sprint-status 单一权威

**全周期 sprint 状态统一在 `_bmad-output/sprint-status.yaml`。**

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
| Epic 29–35 | interaction | 交互与可扩展层（审批 / 会话恢复 / 斜杠命令 / Hooks / Plan Mode / 角色配置 / CLI 收尾） |
| Epic 36–39 | file-safety | 文件与凭证安全防护 |
| Epic 40 | sandbox-session | 沙箱会话目录与生命周期 |
| Epic 41 | goal | 目标驱动开发入口与产物 |
| Epic 42 | skill-runtime | BMad 技能包运行时 |
| Epic 43–46 | goal-workflow | 目标工作流连续执行与资源安全 |
| Epic 47 | declarative-workflow | 声明式 BMad 工作流与产物治理 |

各自周期目录下的旧 sprint-status 保留作为只读归档；后续状态更新以 `_bmad-output/sprint-status.yaml` 为唯一写目标。

## epics/epic-01-10-主线规划周期/ — 主线周期（Epic 1–10，FR-1~24）

| 文件 | 用途 |
|------|------|
| `brief.md` / `brief-decision-log.md` | 产品意图与边界、brief 阶段决策记录 |
| `prd.md` / `prd-decision-log.md` | 功能需求（FR/NFR）、prd 阶段决策记录 |
| `architecture.md` | 技术架构与冻结决策（交叉引用 frame.md） |
| `epics.md` | Epic 1-5（MVP，FR-1~19）拆分 + 覆盖矩阵 |
| `epics-self-learning.md` | Epic 6-10（自学习闭环，FR-20~24）拆分 |
| `sprint-status.yaml` | **全周期 story/epic 状态流转**（事实来源，覆盖当前全部周期；`action_items` 块 2026-09-15 移除，三条均 `closed`） |
| `epics/epic-01-10-主线规划周期/epic-01-基础设施与LLM通信/stories/`（1-1~1-5） | Epic 1 的可执行 story（含 AC，2026-08-19 移出） |

## epics/epic-11-18-MCP集成周期/ — MCP Client 集成周期（三阶段统一，2026-08-18 合并）

> 原三个目录 `mcp-client/`（Epic 11-13）、`mcp-v2-upgrade/`（Epic 14）、`mcp-client-v2/`（Epic 15-18）已于 2026-08-18 合并为 `mcp/`，核心文档按类型整合、执行产物原样保留。导航与编号对照见 `epics/epic-11-18-MCP集成周期/README.md`。

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
| `sprint-status.yaml` | 已归档 — 见 `_bmad-output/sprint-status.yaml` |
| `epics-integration.md` | 历史归档（2026-06-03 Epic 6 集成补丁，非 MCP 内容，编号已被占用） |
| `epic-14/15/16-*/stories/` | V2 周期 story 文件（14-x/15-x/16-x，2026-08-19 移出至按 epic 目录） |
| `reviews/_v1/` `reviews/_upgrade/` `reviews/_v2/` | 三阶段评审产物（PRD rubric / 对抗评审 / 事实核查） |

## epics/epic-S1-S4-沙箱硬化周期/ — Sandbox 硬化周期（Epic S1–S4）

| 文件 | 用途 |
|------|------|
| `architecture.md` | 硬化架构脊架（原 ARCHITECTURE-SPINE.md） |
| `epics.md` | Epic S1–S4 拆分 |
| `sprint-status.yaml` | 已归档 — 见 `_bmad-output/sprint-status.yaml` |

## epics/epic-19-20-健壮性硬化周期/ — 健壮性与质量硬化周期（Epic 19–20）

| 文件 | 用途 |
|------|------|
| `architecture.md` | 架构脊架（原 ARCHITECTURE-SPINE.md） |
| `epics.md` | Epic 19–20 拆分（原内部编号 18–19） |
| `sprint-status.yaml` | 已归档 — 见 `_bmad-output/sprint-status.yaml` |

## epics/epic-21-24-质量工程周期/ — 质量工程深化周期（Epic 21–24）

| 文件 | 用途 |
|------|------|
| `architecture.md` | 架构设计 |
| `epics.md` | Epic 21–24 拆分（原内部编号 20–23） |
| `sprint-status.yaml` | 已归档 — 见 `_bmad-output/sprint-status.yaml` |

## epics/epic-25-28-GUI界面周期/ — GUI 终端界面周期（Epic 25–28）

| 文件 | 用途 |
|------|------|
| `brief.md` | GUI 产品意图 |
| `prd.md` | FR-G1~G24 |
| `architecture.md` | GUI 架构（Textual + bridge + 状态管理） |
| `epics.md` | Epic 25–28 拆分（原内部编号 24–27） |
| `sprint-status.yaml` | 已归档 — 见 `_bmad-output/sprint-status.yaml` |

## epics/epic-36-39-文件安全防护周期/ — 文件与凭证安全周期（Epic 36–39）

包含凭证文件读写拒绝、内部状态读拒绝、环境变量清理和安全声明同步。周期级 `prd.md`、`architecture.md`、`epics.md` 及各 Story 均为历史规划/交付记录，状态以根目录 `sprint-status.yaml` 为准。

## epics/epic-40-沙箱会话化周期/ — 沙箱会话周期（Epic 40）

记录 per-run workspace、后端强度分级、环境变量白名单、会话生命周期及 shell 输出上限的设计与实现；已完成的补充 spec 为 `spec-shell-output-limit.md`。

## epics/epic-41-目标驱动开发周期/ — 目标驱动开发周期（Epic 41）

记录 `/goal` 入口、目标产物和单步推进契约；目标运行时产物不应与 `_bmad-output/` 历史规划混淆。

## epics/epic-42-BMad技能包运行时周期/ — BMad 技能包运行时周期（Epic 42）

记录技能包模型、资源安全读取、技能导入和运行时兼容性验证。

## epics/epic-43-46-目标级工作流周期/ — 目标级工作流周期（Epic 43–46）

记录工作流状态转换、checkpoint/resume、Token 分段、质量收口及技能资源 TOCTOU 评估与加固。

## epics/epic-47-声明式BMad敏捷工作流周期/ — 声明式工作流周期（Epic 47）

记录 Goal/Epic/Story 产物契约、工作流执行闸门、审查/回顾闭环和示例回归文档。补充归档包括 checkpoint 恢复、运行时持久化治理、子代理依赖反转和仓库贡献指南（均位于 `epic-47-声明式工作流与产物治理/`）。

## 补丁 spec（原 `patches/`，2026-09-15 解散）

计划外补丁 / 缺陷 spec 不再集中在 `patches/<领域>/`，而是**按归属 epic 与 story 同目录归档**（`epic-NN-主题/` 下；story 级 spec 进 `stories/`）：

| 归档位置 | 补丁 spec（按原文件名） |
|----------|------------------------|
| `epics/epic-01-10-主线规划周期/epic-01-基础设施与LLM通信/` | `p0-provider-hardening.md`（P0 异常包装）、`retrospective-p0-tech-debt.md`（P0 债回顾） |
| `epics/epic-01-10-主线规划周期/epic-02-自主Agent核心循环/` | `spec-steering-followup.md`（steering / follow-up 双层循环） |
| `epics/epic-01-10-主线规划周期/epic-04-自学习记忆系统/` | `spec-dreaming-memory-consolidation.md`（Dreaming 规划 spec）、`spec-dreaming-memory-consolidation-frozen.md`（冻结实现版，原在周期根、随原始 spec 归位）、`spec-dreaming-defer-cleanup.md`（3 个 LOW defer 收口） |
| `epics/epic-01-10-主线规划周期/epic-05-多Agent并行编排/` | `epic-5-context.md`（Epic 5 上下文编译件）、`stories/5-1-subagent-context-injection.md`（SubAgent 上下文注入） |
| `epics/epic-01-10-主线规划周期/epic-10-Cron定时调度/` | `spec-cron-stop-timeout.md`（`CronScheduler.stop` 关停硬上界） |
| `epics/epic-11-18-MCP集成周期/epic-11-MCP工具桥接/` | `fr3-mcp-auto-unregister.md`（FR-3 断连自动注销）、`spec-mcp-shutdown-timeout.md`（`__aexit__` 关停硬上界） |
| `epics/epic-11-18-MCP集成周期/epic-13-安全边界与开源可用/` | `spec-dp4-mcp-safety-guard.md`（DP-4 第一半·执行前拦截）、`spec-dp4-mcp-result-guard.md`（DP-4 第二半·返回内容围栏）、`spec-mcp-user-injection-signatures.md`（用户可配置注入签名入口） |
| `epics/epic-29-35-交互扩展周期/epic-35-CLI体验优化/` | `cli-status-bar.md`（交互模式状态栏） |
| `epics/epic-43-46-目标级工作流周期/epic-46-技能资源并发替换安全评估/` | `spec-skill-resource-toctou-assessment.md`（技能资源 TOCTOU 评估） |
| `epics/epic-47-声明式BMad敏捷工作流周期/epic-47-声明式工作流与产物治理/` | `retrospective-engine-p5.md`（engine P5 回顾；engine 运行时治理增量与 `spec-runtime-hygiene.md` 同域） |
| `epics/epic-S1-S4-沙箱硬化周期/` | `spec-engine-sandbox-backend.md`（`CommandRunner` 后端抽象）、`spec-sandbox-timeout-validation.md`（timeout 正整数校验）、`spec-sandbox-cancel-signal-preservation.md`（取消信号保留）、`spec-sandbox-reap-robustness.md`（reap 鲁棒性） |
| `implementation-artifacts/` | `spec-business-data-integration.md`（业务数据整合母规划 spec，未实现，跨周期路线；**2026-09-15 已删除**，见下「已失效删除」） |

**已失效删除**（内容被 epic 侧台账 / 代码+测试覆盖，仅存于 git 历史）：`3-3-token-counter.md`（2026-09-15）、`p0-hardening-review-diff.txt`（2026-09-15，过程产物）、`code-review-2026-07-20.md`（2026-09-15）、`deferred-work.md`（2026-09-15 退役）、`spec-deferred-low-cleanup.md`（2026-09-15，条目已并入 `epic-11-18-MCP集成周期` 与 `epic-S1-S4-沙箱硬化周期` 的 `deferred-work.md`）、`spec-business-data-integration.md`（2026-09-15；**未启动**的母规划 spec——未衍生实现 spec 或 epic，正文仅存 git 历史）。

> 归档原则：**「谁交付它，就放进谁的 epic 目录」**——补丁 spec 与它服务的 epic/story 同目录，避免 `patches/` 与 `epics/` 两处漂移。

### 各周期 deferred-work.md — 已闭合遗留项归档（2026-09-15）

原跨周期台账 `patches/_meta/deferred-work.md`（2026-09-15 退役并删除）的条目**已全部闭合**，按**归属 epic** 归并进各周期目录；原始长文历史不再保留，结论与证据指向代码、测试与 commit。

| 归档文件 | 覆盖条目 |
|----------|----------|
| `epics/epic-01-10-主线规划周期/deferred-work.md` | E1-D1/D2（ProviderChain 双层重包、流式 backstop）、E4-D1/D2（Dreaming AC6 端到端、对抗审查 3 个 LOW）、E5-D1（SkillStore 写竞态，核实不成立）、E10-D1/D2（cron 关停硬上界、cron expr 诊断） |
| `epics/epic-11-18-MCP集成周期/deferred-work.md` | E11-D1（FR-3 评审 6 项）、E11-D2（DP-4 返回内容围栏）、E11-D3（注入签名全局级，决策关闭） |
| `epics/epic-S1-S4-沙箱硬化周期/deferred-work.md` | S-D1（engine sandbox 后端评审 4 项，含进程组 kill 勘误）、S-D2（取消信号保留）、S-D3（reap 鲁棒性 3 项） |
| `epics/epic-40-沙箱会话化周期/deferred-work.md` | E40-D1..D4 + E40-C1 |
| `epics/epic-41-目标驱动开发周期/deferred-work.md` | 41-D1..D4 |
| `epics/epic-47-声明式BMad敏捷工作流周期/deferred-work.md` | E47-D1（ledger 记录在途被删；engine 运行时治理增量，同域 `epic-47-声明式工作流与产物治理/spec-runtime-hygiene.md`） |

活动（未闭合）遗留项仍在 `implementation-artifacts/deferred-work.md`。

## 当前状态摘要

- **Epic 1–24 + S1–S4 全部 `done`**（详见 `_bmad-output/sprint-status.yaml`）。
- **Epic 25–28（GUI）`done`**（12 stories，见 `_bmad-output/sprint-status.yaml`；周期目录旧状态为规划期快照）。
- **MCP 三目录已合并**（2026-08-18）：`mcp-client/` + `mcp-v2-upgrade/` + `mcp-client-v2/` → `mcp/`，核心文档整合为 6 份，执行产物保留。
- **deferred-work.md**：**活动台账**路径为 `implementation-artifacts/deferred-work.md`（未闭合项）；**已闭合项**按归属 epic 归档到各周期 `deferred-work.md`（2026-09-15 整理，原 `patches/_meta/deferred-work.md` 全部条目已闭合后退役并删除）。早期 3 条（SubAgent 写竞态 / ProviderChain 双层重包 / 流式 backstop）与 2026-07-01 FR-3 评审 6 项 `defer` 均已收尾——4 项修复（含 `__aexit__` 关停硬上界）、1 项核实不成立、2 项决策关闭（`_watch` `wait_for` 同名异义已修，`except Exception` 过宽经实测证明「收窄会更坏」故保持现状）。
- **action_items（2026-09-15 移除）**：三项全 `closed` 后删除根 `sprint-status.yaml` 的 `action_items` 块 —— FR-3 auto-unregister（2026-07-01）、DP-4 第一半 SafetyGuard 执行前拦截（2026-07-08）、DP-4 第二半 MCP 返回内容启发式围栏（2026-07-10）；条目均已闭合，原始记录仅存 git 历史。
- **补丁系列**：sandbox 健壮性系列（timeout 正整数校验 / CancelledError 不吞取消信号 / reap 鲁棒性）、关停硬上界三件套（MCP `__aexit__` / `CronScheduler.stop` / sandbox reap）、compressor 孤儿 TOOL 消息修复均已交付。
- **epic 外增量**：`engine/` 运行时治理层（P0-P5）不挂 Epic 编号，进度记入 `docs/frame.md` 4.12。

## 阅读建议

第一次进入：`docs/iteration.md`（迭代历程总览）→ [`consolidated-overview.md`](consolidated-overview.md)（全周期统一整合总览）→ 本文件（产物地图）→ 按需查具体周期的 brief/prd/epics。
