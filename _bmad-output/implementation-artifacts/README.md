# Implementation Artifacts

本目录保存实现期专题档案（活动台账已于 2026-11-15 上移 [`../open-items.md`](../open-items.md)）。它不是运行时配置目录；当前代码行为以 `src/`、`docs/frame.md` 和专题文档为准。

## 文档分工

| 路径 | 用途 | 当前状态 |
| --- | --- | --- |
| ~~`open-items.md`~~（2026-11-15 已上移 [`../open-items.md`](../open-items.md)） | 活动台账现住根目录 `open-items.md`「活动（未闭合）条目」节 | 活动项 16 条（A34/A41/A65/A68 `frozen`；A54/A55/A56/A59/A62/A66/A67/A69–A73 `active`；A55 = Epic 61 真实冒烟残差，等用户 key；A56 = Epic 64 收口残差；A59–A66 = Epic 66-68 评审残差（A60/A61/A63 于 2026-11-19 闭合、A64 同日闭合、A65 用户裁定暂停）；A67–A73 = 各 epic retro open questions 于 2026-11-19 升台账；A35 / A36 / A53 / A57 / A58 已于 2026-11-18 闭合，归档见 `../retrospective-all-cycles.md` §三） |
| `arch-optimization-cycle/` | 架构优化周期的计划与 Phase 0–5 执行记录 | 全部 `done`，仅供追溯 |

> 2026-11-15 四并二重组：本目录原 `deferred-work.md`（review 附件）与 `deferred-work-archive.md`（闭合台账）
> 已迁入 [`../retrospective-all-cycles.md`](../retrospective-all-cycles.md)（§五 review 索引 / §三 台账），正文以该文件为准。

## 维护规则

- 新增未闭合遗留项**只写 [`../open-items.md`](../open-items.md) 的「活动（未闭合）条目」节**（唯一活动台账）；不要另建活动清单。
- 闭合后正文迁入 `../retrospective-all-cycles.md` §三（台账）或按归属 Epic 进对应周期的 `deferred-work.md`，并从 `../open-items.md` 活动表移除；显式退役按历史记录的 `retired` 5 字段规范。
- 历史审查记录只补充事实和证据，不把“观察项”改写成已解决状态；当前状态以 `../open-items.md`、`../sprint-status.yaml` 和源码测试为准。
- 新的架构方案应在实施完成后转为专题文档或架构文档，避免在本目录产生第二份当前事实源。
