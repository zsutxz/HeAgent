# `_bmad-output/` 导航

本目录是 HeAgent 用 **BMad Method** 驱动迭代留下的**规划产物**（brief / prd / architecture / epics / stories / 补丁 / 回顾）。它是迭代历程的事实来源之一，**不是当前代码事实**——当代码与本文档冲突时，以 `src/` 实现为准（参见 `docs/frame.md`、`docs/iteration.md`）。

> **BMad config 对齐说明：** `_bmad/config.toml [modules.bmm]` 与 `_bmad/bmm/config.yaml`（installer 托管）声明 `planning_artifacts` / `implementation_artifacts` 指向 `_bmad-output/{planning,implementation}-artifacts/`——**这两个目录在本仓不存在**。HeAgent 刻意按周期而非按产物类型组织（见下方目录结构）。这两个 key 维持 installer 默认、不在 `_bmad/custom/config.toml` 覆盖：同类路径 override 经验证不生效（同 `output_folder` 上游 bug，见 commit `01fbe13`），且 quick-dev 假设的「扁平 `implementation_artifacts`」与本仓 cycle 布局结构不兼容（`sprint-status.yaml` 在 `baseline/`、`deferred-work.md` 在 `patches/`、spec 在 `specs/`，无单一目录可满足）。**实际产物位置以本文件为权威。**

## 目录结构（按周期）

```
_bmad-output/
├── baseline/      主线周期（Epic 1-10，FR-1~24）
├── mcp-client/    MCP 集成周期（Epic 11-13，独立 FR-1~11）
├── patches/       补丁周期（计划外技术债 / 缺陷，跨周期扁平）
└── specs/         quick-dev / spec 产物（本地工作件，gitignored）
```

## baseline/ — 主线周期（Epic 1-10）

| 文件 | 用途 |
|------|------|
| `brief.md` / `brief-decision-log.md` | 产品意图与边界、brief 阶段决策记录 |
| `prd.md` / `prd-decision-log.md` | 功能需求（FR/NFR）、prd 阶段决策记录 |
| `architecture.md` | 技术架构与冻结决策（交叉引用 frame.md） |
| `epics.md` | Epic 1-5（MVP，FR-1~19）拆分 + 覆盖矩阵 |
| `epics-self-learning.md` | Epic 6-10（自学习闭环，FR-20~24）拆分 |
| `sprint-status.yaml` | **story/epic 状态流转与 action_items 跟踪**（事实来源） |
| `stories/1-1 ~ 1-5` | Epic 1 的可执行 story（含 AC） |

## mcp-client/ — MCP 集成周期（Epic 11-13）

| 文件 | 用途 |
|------|------|
| `brief.md` / `brief-addendum.md` / `brief-decision-log.md` | MCP 周期产品意图（含增补） |
| `prd.md` / `prd-decision-log.md` / `prd-review-rubric.md` | MCP 功能需求 + 评审 rubric |
| `architecture.md` | MCP 集成架构与冻结决策 |
| `epics-mcp-client.md` | MCP 周期内部 Epic 1-3（= 主线 Epic 11-13） |
| `epics-integration.md` | 集成验收 epic |
| `retrospective-epic-13.md` | Epic 13 回顾（已完成） |

> 编号映射：sprint-status 的 Epic 11-13 = `epics-mcp-client.md` 内部的 Epic 1-3（MCP 周期自称 Epic 1-3 会撞主线编号，故延续主线递增）。

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

## 当前状态摘要

- **Epic 1-13 全部 `done`**（详见 `baseline/sprint-status.yaml`）。
- **deferred-work.md**：原 3 条（SubAgent 写竞态 / ProviderChain 双层重包 / 流式 backstop）均已关闭；2026-07-01 FR-3 评审另增 6 项 `defer`（pre-existing / spec 显式排除 / 非阻塞）—— 4 项已 Resolution 关闭，余 2 项保持现状（`_watch` 两个 `wait_for` 同名异义 / `except Exception` 过宽，待 MCP 重连场景收窄）。
- **action_items**：三项全 `closed` —— FR-3 auto-unregister（2026-07-01）、DP-4 第一半 SafetyGuard 执行前拦截（2026-07-08）、DP-4 第二半 MCP 返回内容启发式围栏（2026-07-10）。
- **epic 外增量**：`engine/` 运行时治理层（P0-P5）不挂 Epic 编号，进度记入 `docs/frame.md` 4.12。

## 阅读建议

第一次进入：`docs/iteration.md`（迭代历程总览）→ 本文件（产物地图）→ 按需查具体周期的 brief/prd/epics。
