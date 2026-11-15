---
id: goal-<goal-slug>
type: goal
status: planning
title: <目标标题>
---
# <目标标题>

> goal 需求文档模板。`## 原始需求` 段逐字冻结；`## 总结的需求（Derived Requirements）` 段由
> Step 01 写入；`## 用户补充` 段记录后续用户回答。文件落 `_he-output/works/<goal-id>/brief.md`。
> `## Initiative` 一行由 Step 04 写定，是全流程定位票树的锚点；epic/story 清单**不写在这里**，
> 它们住 initiative 的 `tickets/` 票树。

## 原始需求（Original Request）

```
<用户的原始需求>
```

## 总结的需求（Derived Requirements）

<Step 01 写入的总结需求：明确、可验证、无内部矛盾；区分事实与假设，标出开放问题>

## 用户补充（User Responses）

<工作流中记录的补充决策或用户回答>

## Initiative

- initiative-<slug>（`_bmad-output/initiative-<slug>/`；PRD 在 `prd-<slug>/`，epic 与 entry 在
  `tickets/`）

