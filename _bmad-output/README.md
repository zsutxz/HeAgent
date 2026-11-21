# `_bmad-output/` 导航

本目录保存 HeAgent 使用 BMad Method 产生的规划、实现、评审和回顾产物。它记录开发过程，不取代当前代码事实；代码与规划冲突时，以 `src/` 与 [`docs/framework.md`](../docs/framework.md) 为准，Epic/Story 状态查 [`Goal-3/tickets/`](Goal-3/tickets/) 活动票树（[`sprint-status.yaml`](Goal-2-v6/sprint-status.yaml) 已归档，不再是状态权威）。

## 先看什么

| 目标 | 文档 |
| ------ | ------ |
| 了解全周期与编号 + 活动台账 | [`open-items.md`](open-items.md)（2026-11-15 由 consolidated-overview.md 并入活动台账后定名） |
| 查历史记录与跨周期教训 | [`retrospective-all-cycles.md`](retrospective-all-cycles.md) |
| 查已定型的系统决策（ADR） | [`decisions/`](../decisions/)（仓库根，2026-11-18 起；2026-11-20 上移） |
| 查看未闭合遗留项 | [`open-items.md`](open-items.md) 的「活动（未闭合）条目」节（**活动项 18 条**：A34/A41/A65/A68 `frozen`；A54/A55/A56/A59/A62/A66/A67/A69–A73、A75/A76 `active`） |
| 查看单一状态来源 | [`sprint-status.yaml`](Goal-2-v6/sprint-status.yaml)（已归档） |
| 深入某个周期 | `epics/<周期>/` 下的 `brief.md`、`prd.md`、`architecture.md`、`epics.md` 和 `stories/` |

## 目录结构

```text
_bmad-output/
├── open-items.md                     **唯一活动台账** + 当前状态入口（2026-11-15 定名）
├── retrospective-all-cycles.md       **历史记录唯一载体**（周期详解 §一 + deferred 闭合台账 §三 + review 索引 §五）
├── epic-overview.md                  当前状态总览 + epic 总目录 + 文档地图
├── migration-v6-v7.md                v6→v7 迁移记录（2026-11-15）
├── epics/                            第一代：最早周期产物（27 个周期目录，Epic 01–61 + S1–S4，活跃与已归档混排）
├── Goal-2-v6/                        第二代：BMad v6 时代归档（规划四件套 + 信封 + sprint-status.yaml + 票树 Epic 61–69 含 retrospective；只读）
└── Goal-3/                           第三代：goal-3 活跃票树（Epic 70–73 + 根 tickets.toml）
```
（ADR 决策记录在仓库根 `decisions/`，不属本目录。）

## 归档规则

- BMad 编号体系覆盖 24 个编号周期（Epic 1–57 + S1–S4）；文件系统统一按 `epics/` 27 个周期目录组织（2026-11-15 `archive/epics/` 已并入，归档周期与活跃周期同目录混排、无独立归档区），MCP 三阶段合并在同一目录。
- 补丁 spec 按归属 Epic 放入 `epics/<周期>/<epic-NN-主题>/`；原 `patches/` 已于 2026-09-15 退役。
- 未闭合 deferred 只写入根目录 `open-items.md` 的「活动（未闭合）条目」节（2026-11-15 起）；闭合后，有明确归属的条目正文移入对应周期的 `deferred-work.md`，其余迁入 `retrospective-all-cycles.md`（§三 台账 / §四 编号索引）。
- 不要把运行时状态、日志、密钥或 `.env` 写入并提交本目录。

## 历史状态快照（2026-10-27，仅供存档）

> 当前状态见 [`epic-overview.md`](epic-overview.md)；活动项条数与 ID 的真值见 [`open-items.md`](open-items.md)
> 「活动（未闭合）条目」节（上表与本节之外，本文不再另行声明计数——旧快照里的数字不作为现值）。

Epic 1–56 与 S1–S4 均已交付（Epic 53 于 2026-10-24 walkthrough 收口；54/55/56 随 `98ef6d8` 入库并随 0.8.2 发布）；**Epic 57 retro 遗留清理在途**（2026-10-26 立项，4 story 已 done）。Epic 48 已于 2026-09-27 从代码删除（`4217b5d`），历史见 `epics/epic-48-TCP网络接口周期/`。当时的完整状态以 [`sprint-status.yaml`](Goal-2-v6/sprint-status.yaml)（v6，已归档）为准。

2026-11-13：立项 Epic 61 Web 检索工具周期（backlog，spec 见 `epics/epic-61-Web检索周期/`）；同批复盘的 ② 多模态图像输入经用户裁定不做，③ 用户可配置 hooks 经核 Epic 32 已交付、撤销立项（残差转台账 A52/A53）。
