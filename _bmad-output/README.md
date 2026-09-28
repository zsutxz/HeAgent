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
│   ├── deferred-work-archive.md      23 条活动遗留项 + 勘察类闭合归档
│   └── arch-optimization-cycle/       Phase 0–5 架构优化档案
├── epics/                             按周期归档的规划与实现产物
│   ├── epic-01-10-主线规划周期/
│   ├── epic-11-18-MCP集成周期/
│   ├── epic-S1-S4-沙箱硬化周期/
│   └── …（共 16 个周期目录，覆盖 Epic 1–50 + S1–S4）
└── specs/                             quick-dev 本地工作件（通常 gitignored）
```

## 归档规则

- BMad 编号体系覆盖 18 个编号周期（Epic 1–50 + S1–S4）；文件系统按 16 个周期目录归档，MCP 三阶段合并在同一目录。
- 补丁 spec 按归属 Epic 放入 `epics/<周期>/<epic-NN-主题>/`；原 `patches/` 已于 2026-09-15 退役。
- 未闭合 deferred 只写入 `implementation-artifacts/deferred-work-archive.md`；闭合后，有明确归属的条目正文移入对应周期的 `deferred-work.md`，本文件保留 ID 索引。
- 不要把运行时状态、日志、密钥或 `.env` 写入并提交本目录。

## 当前状态（2026-09-28）

Epic 1–50 与 S1–S4 **全部已完成**（**Epic 50 于 2026-09-27 收口**：8 个 Story 全部 `done`、retrospective 已补做）；**Epic 48（TCP 网络接口）已于 2026-09-27 删除**（commit `4217b5d`，删除原因：使用率极低、维护成本高、HTTP 入口已充分覆盖需求）。完整状态以 [`sprint-status.yaml`](sprint-status.yaml) 为准。活动台账当前 **2 条**（2026-09-28 实测：同日第五轮校正为 7、第六轮按产品裁定闭合 A8 / A10 / A12 / A15 / A16 五条 ⇒ **2 条**；已无 OBSOLETE 条目——原那条 TCP 条目已归档为 Z-D18）；其中需要产品或架构决策的条目在正文内如实标注，不得在回顾文档中复制正文。
