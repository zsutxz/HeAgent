---
id: story-<unique-id>
type: story
goal_id: goal-<goal-id>
epic_id: epic-<epic-id>
status: ready-for-dev
title: <story title>
---
# <story title>

> `/goal` 运行时契约：story 的真源是 `_he-output/goals/<goal-id>/02-epics.md` 里的 `### S-N` 条目；
> 该文件按 Epic 分段（`## E<N> — <标题>`），同一 Epic 的 story 编号连续。step 07 逐条实现时把本模板
> 落到 `step-07-implement-story/epic-<eN>/s-<n>/story.md`，写出后即冻结（只有人能改验收标准）。

## User Story
As a <persona>, I want <capability>, so that <value>.

## Acceptance Criteria
- Given <context>, when <action>, then <observable result>.

## Tasks
- [ ] <implementation task>

## Code Map
<与该 story 相关的文件、符号 / 行锚点、可复用点与只读约束；让人和后续步骤不必盲搜代码>

## Boundaries
- **Always**: <必须遵守的边界>
- **Ask First**: <需先问再动的边界>
- **Never**: <禁止触碰的边界>

## I/O Matrix
<当该 story 有有意义的输入 / 状态场景时给出：场景 / 输入或状态 / 期望输出或行为 / 错误处理；
没有有意义的场景就整节删除，不要写 N/A>

## Verification
<确认自己工作的命令或人工检查项，写明确切命令行>

## Sizing
<证明它装得进一次「实现—测试—验证」会话；建议 900–1600 token 量级>

## Definition of Done
- <tests and evidence are complete>
