# `_bmad-output/` 导航

本目录是 HeAgent 用 **BMad Method** 驱动迭代留下的**规划产物**（brief / prd / architecture / epics / stories / 补丁 / 回顾）。它是迭代历程的事实来源之一，**不是当前代码事实**——当代码与本文档冲突时，以 `src/` 实现为准（参见 `docs/frame.md`、`docs/iteration.md`）。

> **BMad config 对齐说明：** `_bmad/config.toml [modules.bmm]` 与 `_bmad/bmm/config.yaml`（installer 托管）声明 `planning_artifacts` / `implementation_artifacts` 指向 `_bmad-output/{planning,implementation}-artifacts/`——**这两个目录在本仓不存在**。HeAgent 刻意按周期而非按产物类型组织（见下方目录结构）。这两个 key 维持 installer 默认、不在 `_bmad/custom/config.toml` 覆盖：同类路径 override 经验证不生效（同 `output_folder` 上游 bug，见 commit `01fbe13`），且 quick-dev 假设的「扁平 `implementation_artifacts`」与本仓 cycle 布局结构不兼容（`sprint-status.yaml` 在 `baseline/`、`deferred-work.md` 在 `patches/`、spec 在 `specs/`，无单一目录可满足）。**实际产物位置以本文件为权威。**

## 目录结构（按周期）

```
_bmad-output/
├── baseline/               主线周期（Epic 1–10，FR-1~24）
├── mcp-client/             MCP 集成周期一（Epic 11–13，独立 FR-1~11）
├── mcp-v2-upgrade/         MCP v1→v2 升级准备（Epic 14）
├── mcp-client-v2/          MCP Client V2 集成周期二（Epic 15–18）
├── sandbox-hardening/      Sandbox 硬化周期（Epic S1–S4）
├── robustness-hardening/   健壮性与质量硬化周期（Epic 19–20）
├── quality-engineering/    质量工程深化周期（Epic 21–24）
├── gui/                    GUI 终端界面周期（Epic 25–28，当前进行中）
├── patches/                补丁周期（计划外技术债 / 缺陷，跨周期扁平）
└── specs/                  quick-dev / spec 产物（本地工作件，gitignored）
```

## sprint-status 单一权威

**全周期 sprint 状态统一在 `_bmad-output/baseline/sprint-status.yaml`。**

2026-07-23 整合：此前 sprint-status 分散在 6 个文件（`baseline/`、`mcp-client-v2/`、`sandbox-hardening/`、`robustness-hardening/`、`quality-engineering/`、`gui/`），存在 Epic 14 编号冲突。合并后的编号规则：

| 起始编号 | 周期 | 说明 |
|---------|------|------|
| Epic 1–10 | baseline | 主线 MVP + 自学习闭环 |
| Epic 11–13 | mcp-client | MCP 工具桥接 + GitHub E2E + 安全声明 |
| Epic 14 | mcp-v2-upgrade | MCP v1→v2 升级准备（pin / 隔离层 / 测试基线） |
| Epic 15–18 | mcp-client-v2 | 写操作治理 / Resources / Prompts / 内置工具扩展 |
| Epic S1–S4 | sandbox-hardening | Sandbox profile 映射 / 降级 / 配置入口 / 进程组 kill / workspace 隔离 |
| Epic 19–20 | robustness-hardening | 文件锁 / Cron 范围 / WinJobBackend / 覆盖率 90% |
| Epic 21–24 | quality-engineering | Coverage 工程化 / Benchmark / Docker 硬化 / CI 安全 |
| Epic 25–28 | gui | GUI 终端界面（流式聊天 / 工具可视化 / 管理面板 / 可观测性） |

各自周期目录下的旧 sprint-status 保留作为只读归档；后续状态更新以 `baseline/sprint-status.yaml` 为唯一写目标。

## baseline/ — 主线周期（Epic 1–10，FR-1~24）

| 文件 | 用途 |
|------|------|
| `brief.md` / `brief-decision-log.md` | 产品意图与边界、brief 阶段决策记录 |
| `prd.md` / `prd-decision-log.md` | 功能需求（FR/NFR）、prd 阶段决策记录 |
| `architecture.md` | 技术架构与冻结决策（交叉引用 frame.md） |
| `epics.md` | Epic 1-5（MVP，FR-1~19）拆分 + 覆盖矩阵 |
| `epics-self-learning.md` | Epic 6-10（自学习闭环，FR-20~24）拆分 |
| `sprint-status.yaml` | **全周期 story/epic 状态流转与 action_items 跟踪**（事实来源，含 8 个周期） |
| `stories/1-1 ~ 1-5` | Epic 1 的可执行 story（含 AC） |

## mcp-client/ — MCP 集成周期一（Epic 11–13，独立 FR-1~11）

| 文件 | 用途 |
|------|------|
| `brief.md` / `brief-addendum.md` / `brief-decision-log.md` | MCP 周期产品意图（含增补） |
| `prd.md` / `prd-decision-log.md` / `prd-review-rubric.md` | MCP 功能需求 + 评审 rubric |
| `architecture.md` | MCP 集成架构与冻结决策 |
| `epics-mcp-client.md` | MCP 周期内部 Epic 1-3（= 主线 Epic 11-13） |
| `epics-integration.md` | 集成验收 epic |
| `retrospective-epic-13.md` | Epic 13 回顾（已完成） |

## mcp-v2-upgrade/ — MCP v1→v2 升级准备（Epic 14）

| 文件 | 用途 |
|------|------|
| `brief.md` / `addendum.md` | 升级准备意图 |
| `prd.md` / `prd-decision-log.md` | FR-1~5 / NFR-1~6 |
| `architecture.md` | 隔离层设计 + 切换路径 |
| `epics-mcp-v2-upgrade.md` | Epic 14 拆分（3 stories） |

## mcp-client-v2/ — MCP Client V2 集成周期二（Epic 15–18）

| 文件 | 用途 |
|------|------|
| `brief.md` | V2 集成意图 |
| `prd.md` | FR-A~C / AD-1~9 |
| `ARCHITECTURE-SPINE.md` | V2 架构脊架 |
| `epics.md` | Epic 15–18 拆分（原内部编号 14–17） |
| `sprint-status.yaml` | 已归档 — 见 `baseline/sprint-status.yaml` |

## sandbox-hardening/ — Sandbox 硬化周期（Epic S1–S4）

| 文件 | 用途 |
|------|------|
| `ARCHITECTURE-SPINE.md` | 硬化架构脊架 |
| `epics.md` | Epic S1–S4 拆分 |
| `sprint-status.yaml` | 已归档 — 见 `baseline/sprint-status.yaml` |

## robustness-hardening/ — 健壮性与质量硬化周期（Epic 19–20）

| 文件 | 用途 |
|------|------|
| `ARCHITECTURE-SPINE.md` | 架构脊架 |
| `epics.md` | Epic 19–20 拆分（原内部编号 18–19） |
| `sprint-status.yaml` | 已归档 — 见 `baseline/sprint-status.yaml` |

## quality-engineering/ — 质量工程深化周期（Epic 21–24）

| 文件 | 用途 |
|------|------|
| `architecture.md` | 架构设计 |
| `epics.md` | Epic 21–24 拆分（原内部编号 20–23） |
| `sprint-status.yaml` | 已归档 — 见 `baseline/sprint-status.yaml` |

## gui/ — GUI 终端界面周期（Epic 25–28，当前进行中）

| 文件 | 用途 |
|------|------|
| `brief.md` | GUI 产品意图 |
| `prd.md` | FR-G1~G24 |
| `architecture.md` | GUI 架构（Textual + bridge + 状态管理） |
| `epics.md` | Epic 25–28 拆分（原内部编号 24–27） |
| `sprint-status.yaml` | 已归档 — 见 `baseline/sprint-status.yaml` |

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

## 当前状态摘要

- **Epic 1–24 + S1–S4 全部 `done`**（详见 `baseline/sprint-status.yaml`）。
- **Epic 25–28（GUI）当前 `in-progress`——Epic 25 流式聊天已启动，stories 已就绪待开发**。
- **deferred-work.md**：原 3 条（SubAgent 写竞态 / ProviderChain 双层重包 / 流式 backstop）均已关闭；2026-07-01 FR-3 评审另增 6 项 `defer`（pre-existing / spec 显式排除 / 非阻塞）—— 4 项已 Resolution 关闭，余 2 项保持现状（`_watch` 两个 `wait_for` 同名异义 / `except Exception` 过宽，待 MCP 重连场景收窄）。
- **action_items**：三项全 `closed` —— FR-3 auto-unregister（2026-07-01）、DP-4 第一半 SafetyGuard 执行前拦截（2026-07-08）、DP-4 第二半 MCP 返回内容启发式围栏（2026-07-10）。
- **补丁系列**：sandbox 健壮性系列（timeout 正整数校验 / CancelledError 不吞取消信号 / reap 鲁棒性）、关停硬上界三件套（MCP `__aexit__` / `CronScheduler.stop` / sandbox reap）、compressor 孤儿 TOOL 消息修复均已交付。
- **epic 外增量**：`engine/` 运行时治理层（P0-P5）不挂 Epic 编号，进度记入 `docs/frame.md` 4.12。

## 阅读建议

第一次进入：`docs/iteration.md`（迭代历程总览）→ 本文件（产物地图）→ 按需查具体周期的 brief/prd/epics。
