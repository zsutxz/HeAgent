---
id: story-s-<n>-<story-slug>
type: story
goal_id: goal-<goal-slug>
epic_id: epic-<epic-slug>
status: ready-for-dev
title: <Story 标题>
---
# <Story 标题>

> `/goal` 运行时契约：story 的真源是 `_he-output/goals/<goal-id>/02-epics.md` 里的 `### S-N` 条目；
> 该文件按 Epic 分段（`## E<N> — <标题>`），同一 Epic 的 story 编号连续。step 07 逐条实现时把本模板
> 落到 `step-07-implement-story/epic-<eN>/s-<n>/story.md`，写出后即冻结（只有人能改验收标准）。

## User Story

作为 <角色>，我希望 <能力>，从而 <用户价值>。

## 运行时映射

- 父 Epic：E<n>
- Sprint：Sprint <n>
- 优先级：P0 | P1 | P2
- 依赖：S-<n> | none

`父 Epic` 必须与 `02-epics.md` 中包围该 Story 的 `## E<n> — <标题>` 段一致。`02-epics.md` 的
`### S-n <标题>` 是 Step 07 的唯一执行清单；本文件是该清单冻结后的层级产物与验收快照。

## Acceptance Criteria
- Given <上下文>, when <动作>, then <可观察结果>。

## Tasks
- [ ] <含具体文件或符号的实现任务>

## Code Map
<相关文件、符号或行锚点、可复用代码与只读约束>

## Boundaries
- **Always**：<必须保持的边界>
- **Ask First**：<修改前必须由人决定的边界>
- **Never**：<禁止触碰的边界>

## I/O Matrix
仅在存在有意义的输入或状态场景时保留本节；否则删除整个 `## I/O Matrix`，禁止填写 N/A。

| 场景 | 输入或状态 | 期望输出或行为 | 错误处理 |
| --- | --- | --- | --- |
| <场景> | <输入或状态> | <可观察结果> | <失败行为> |

## Verification
<确切测试命令或人工验证条件>

## Sizing
<为什么该 Story 能装入一次实现、测试和验证会话>

## Definition of Done
- <实现、测试、验收证据和残余风险检查均已完成>
