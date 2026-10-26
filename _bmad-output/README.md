# `_bmad-output/` 导航

本目录保存 HeAgent 使用 BMad Method 产生的规划、实现、评审和回顾产物。它记录开发过程，不取代当前代码事实；代码与规划冲突时，以 `src/`、[`docs/frame.md`](../docs/frame.md) 和根目录 [`sprint-status.yaml`](sprint-status.yaml) 为准。

## 先看什么

| 目标 | 文档 |
|------|------|
| 了解全周期与编号 | [`consolidated-overview.md`](consolidated-overview.md) |
| 阅读跨周期经验 | [`retrospective-all-cycles.md`](retrospective-all-cycles.md) |
| 查看未闭合遗留项 | [`implementation-artifacts/deferred-work-archive.md`](implementation-artifacts/deferred-work-archive.md) |
| 查看单一状态来源 | [`sprint-status.yaml`](sprint-status.yaml) |
| 深入某个周期 | `epics/<周期>/` 下的 `brief.md`、`prd.md`、`architecture.md`、`epics.md` 和 `stories/` |

## 目录结构

```text
_bmad-output/
├── consolidated-overview.md          全周期导航、摘要、状态和指标
├── retrospective-all-cycles.md       全周期回顾与跨周期教训
├── sprint-status.yaml                 Epic/Story 状态唯一写目标
├── implementation-artifacts/
│   ├── README.md                     实现产物目录索引与台账维护规则
│   ├── deferred-work-archive.md      活动遗留项总账 + 勘察类闭合归档
│   └── arch-optimization-cycle/       Phase 0–5 架构优化档案
├── epics/                             活跃周期的规划与实现产物
│   ├── epic-11-18-MCP集成周期/
│   ├── epic-51-goal-workflow优化周期/
│   └── …（共 14 个活跃周期目录，覆盖 Epic 11–18、19–24、29–47、49–52）
├── archive/                           已归档周期产物（保持原相对目录结构）
│   └── epics/（epic-01-10、epic-25-28、epic-48、epic-S1-S4 整目录；epic-11-18 的 reviews；epic-50 的 stories 与 reviews；epic-47 的 story 过程报告）
└── specs/                             quick-dev 本地工作件（通常 gitignored）
```

## 归档规则

- BMad 编号体系覆盖 20 个编号周期（Epic 1–52 + S1–S4）；文件系统按 `epics/` 14 个活跃周期目录 + `archive/epics/` 已归档周期组织，MCP 三阶段合并在同一目录。
- 补丁 spec 按归属 Epic 放入 `epics/<周期>/<epic-NN-主题>/`；原 `patches/` 已于 2026-09-15 退役。
- 未闭合 deferred 只写入 `implementation-artifacts/deferred-work-archive.md`；闭合后，有明确归属的条目正文移入对应周期的 `deferred-work.md`，本文件保留 ID 索引。
- 不要把运行时状态、日志、密钥或 `.env` 写入并提交本目录。

## 当前状态（2026-10-23）

Epic 1–52 与 S1–S4 均已交付（Epic 53 容器沙箱档在途：3 story 在 `review`；Epic 48 TCP 网络接口已于 2026-09-27 从代码删除，commit `4217b5d`，历史文档见 `archive/epics/epic-48-TCP网络接口周期/`）。完整状态以 [`sprint-status.yaml`](sprint-status.yaml) 为准；活动台账当前 **9 条**（A34–A36 + A40–A44 + A49；2026-10-23 登记的 A37–A39 已当日实施并归档 Epic 51；2026-10-26 S-6 四态归一），未闭合遗留项见 [`implementation-artifacts/deferred-work-archive.md`](implementation-artifacts/deferred-work-archive.md)。
