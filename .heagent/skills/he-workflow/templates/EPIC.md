---
id: epic-<epic-slug>
type: epic
goal_id: goal-<goal-slug>
status: planning
title: <Epic 标题>
---
# <Epic 标题>

> 本模板是 `artifacts.py` 校验的 Epic 层级产物，不是 Step 07 的 Story 运行时清单。
> 运行时清单唯一写入 `02-epics.md`，使用 `## E<N> — <标题>` 与 `### S-N <标题>` 格式。

> `/goal` 运行时契约：Epic 在 `_he-output/goals/<goal-id>/02-epics.md` 里以 `## E<N> — <标题>` 分段
> （`N` 从 1 起连续，与产品范围定义步骤的有序 Epic 提案同序同号）；属于该 Epic 的 story 全部列在这
> 一段内，编号连续。step 07 据此把 story 产物写进 `step-07-implement-story/epic-<eN>/s-<n>/`，Epic
> 收口评审写入 `epic-<eN>/review-report.md`。

## Goal
<本 Epic 要达成的目标>
## Value
<受益对象及可观察的交付价值>
## Scope
<范围内行为与明确的范围外边界>
## Dependencies
<前置 Epic、系统或决策；无依赖时写 None>
## Acceptance Criteria
- <可观察的 Epic 级验收标准>
## Stories
- story-s-<n>-<story-id>: S-<n> <Story 标题>

> 本节的键是 Story artifact 的完整 `id`；冒号后的 `S-N` 是 `02-epics.md` 中 Story 条目的派生引用。
> 执行顺序仍由 `02-epics.md` 中的 `S-N` 编号决定，不在此维护另一套状态或顺序。
## Definition of Done
- <该 Epic 完成前必须具备的证据与验证>
