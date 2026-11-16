# `_bmad-output/` 导航

本目录保存 HeAgent 使用 BMad Method 产生的规划、实现、评审和回顾产物。它记录开发过程，不取代当前代码事实；代码与规划冲突时，以 `src/`、[`docs/frame.md`](../docs/frame.md) 和根目录 [`sprint-status.yaml`](initiative-heagent/archive-v6/sprint-status.yaml)（已归档）为准。

## 先看什么

| 目标 | 文档 |
| ------ | ------ |
| 了解全周期与编号 + 活动台账 | [`open-items.md`](open-items.md)（2026-11-15 由 consolidated-overview.md 并入活动台账后定名） |
| 查历史记录与跨周期教训 | [`retrospective-all-cycles.md`](retrospective-all-cycles.md) |
| 查看未闭合遗留项 | [`open-items.md`](open-items.md) 的「活动（未闭合）条目」节 |
| 查看单一状态来源 | [`sprint-status.yaml`](initiative-heagent/archive-v6/sprint-status.yaml)（已归档） |
| 深入某个周期 | `epics/<周期>/` 下的 `brief.md`、`prd.md`、`architecture.md`、`epics.md` 和 `stories/` |

## 目录结构

```text
_bmad-output/
├── open-items.md                     当前状态、路线图、文档地图 + **唯一活动台账**（2026-11-15 由 consolidated-overview.md 与 implementation-artifacts/open-items.md 合并定名）
├── retrospective-all-cycles.md       **历史记录唯一载体**（周期回顾/详解 + deferred 闭合台账 + review 闭合索引）
├── initiative-heagent/                v7 initiative：规划四件套 + 票树；sprint-status.yaml 归档于 archive-v6/
├── implementation-artifacts/
│   ├── README.md                     实现产物目录索引（活动台账已上移根目录 open-items.md）
│   └── arch-optimization-cycle/       Phase 0–5 架构优化档案
├── epics/                             周期产物（活跃与已归档同目录混排）
│   ├── epic-11-18-MCP集成周期/
│   ├── epic-51-goal-workflow优化周期/
│   └── …（共 27 个周期目录，Epic 01–61 + S1–S4——2026-11-15 archive/ 已并入）
└── specs/                             quick-dev 本地工作件（通常 gitignored）
```

## 归档规则

- BMad 编号体系覆盖 24 个编号周期（Epic 1–57 + S1–S4）；文件系统统一按 `epics/` 27 个周期目录组织（2026-11-15 `archive/epics/` 已并入，归档周期与活跃周期同目录混排、无独立归档区），MCP 三阶段合并在同一目录。
- 补丁 spec 按归属 Epic 放入 `epics/<周期>/<epic-NN-主题>/`；原 `patches/` 已于 2026-09-15 退役。
- 未闭合 deferred 只写入根目录 `open-items.md` 的「活动（未闭合）条目」节（2026-11-15 起）；闭合后，有明确归属的条目正文移入对应周期的 `deferred-work.md`，其余迁入 `retrospective-all-cycles.md`（§三 台账 / §四 编号索引）。
- 不要把运行时状态、日志、密钥或 `.env` 写入并提交本目录。

## 当前状态（2026-10-27）

Epic 1–56 与 S1–S4 均已交付（Epic 53 于 2026-10-24 walkthrough 收口；54/55/56 随 `98ef6d8` 入库并随 0.8.2 发布）；**Epic 57 retro 遗留清理在途**（2026-10-26 立项，4 story 已 done）。Epic 48 已于 2026-09-27 从代码删除（`4217b5d`），历史见 `epics/epic-48-TCP网络接口周期/`。完整状态以 [`sprint-status.yaml`](initiative-heagent/archive-v6/sprint-status.yaml)（已归档）为准；活动台账条数与 ID 以 [`open-items.md`](open-items.md)「活动（未闭合）条目」节为准（活动 7 条：A34/A35/A36/A41/A53/A54/A55）。

2026-11-13：立项 Epic 61 Web 检索工具周期（backlog，spec 见 `epics/epic-61-Web检索周期/`）；同批复盘的 ② 多模态图像输入经用户裁定不做，③ 用户可配置 hooks 经核 Epic 32 已交付、撤销立项（残差转台账 A52/A53）。
