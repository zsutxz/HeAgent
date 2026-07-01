# `_bmad-output/` 导航

本目录是 HeAgent 用 **BMad Method** 驱动迭代留下的**规划产物**（brief / prd / architecture / epics / stories / 补丁 / 回顾）。它是迭代历程的事实来源之一，**不是当前代码事实**——当代码与本文档冲突时，以 `src/` 实现为准（参见 `docs/frame.md`、`docs/iteration.md`）。

## 目录结构（按周期）

```
_bmad-output/
├── baseline/      主线周期（Epic 1-10，FR-1~24）
├── mcp-client/    MCP 集成周期（Epic 11-13，独立 FR-1~11）
└── patches/       补丁周期（计划外技术债 / 缺陷，跨周期扁平）
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
- **deferred-work.md**：原 3 条（SubAgent 写竞态 / ProviderChain 双层重包 / 流式 backstop）均已关闭；2026-07-01 FR-3 评审另增 6 项 `defer`（pre-existing / spec 显式排除 / 非阻塞），未关闭。
- **action_items**：FR-3 auto-unregister 已于 2026-07-01 交付（closed）；DP-4（SafetyGuard 扩展到 MCP）、MCP 返回内容隔离两项仍 `open`。
- **epic 外增量**：`engine/` 运行时治理层（P0-P5）不挂 Epic 编号，进度记入 `docs/frame.md` 4.12。

## 阅读建议

第一次进入：`docs/iteration.md`（迭代历程总览）→ 本文件（产物地图）→ 按需查具体周期的 brief/prd/epics。
