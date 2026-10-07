# Implementation Artifacts

本目录保存实现阶段的历史方案、验收记录和遗留项证据。它不是运行时配置目录；当前代码行为以 `src/`、`docs/frame.md` 和专题文档为准。

## 文档分工

| 路径 | 用途 | 当前状态 |
| --- | --- | --- |
| `deferred-work-archive.md` | 跨周期 deferred 的唯一总账；活动区和闭合索引以此为准 | 活动项 0 条（2026-10-07） |
| `deferred-work.md` | 2026-09-29/30 code review 的精简摘要，包含已闭合索引和仍需裁定的观察项 | 历史审查附件，不是活动总账 |
| `arch-optimization-cycle/` | 架构优化周期的计划与 Phase 0–5 执行记录 | 全部 `done`，仅供追溯 |

## 维护规则

- 新增未闭合遗留项写入 `deferred-work-archive.md`，不要重新创建本目录级活动台账。
- 已有明确 Epic 归属的闭合项，正文归档到对应 `_bmad-output/epics/<cycle>/deferred-work.md`，总账保留索引。
- 历史审查记录只补充事实和证据，不把“观察项”改写成已解决状态；当前状态以总账、`sprint-status.yaml` 和源码测试为准。
- 新的架构方案应在实施完成后转为专题文档或架构文档，避免在本目录产生第二份当前事实源。
