---
id: epic-<epic-slug>
type: epic
goal_id: goal-<goal-slug>
status: planning
title: <Epic 标题>
---
# <Epic 标题>

> goal 层级产物模板：Epic 层级的提案/记录快照。运行时 story 清单唯一写入
> `_he-output/goals_new/<goal-id>/epics.md`（`## E<N> — <标题>` 分段 + `### S-N <标题>` 条目），
> 执行顺序由 `S-N` 编号决定，不在此维护另一套状态。

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

> 本节的键是 Story 层级产物的 `id`；冒号后的 `S-N` 是 `epics.md` 中 Story 条目的派生引用。

## Definition of Done

- <该 Epic 完成前必须具备的证据与验证>
