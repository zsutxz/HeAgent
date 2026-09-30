---
canonical_id: he-migration
name: he-migration
description: 迁移类目标走 /goal 的四步声明式工作流（盘点→映射→迁移→回滚预案）
tags: [goal, workflow, migration]
aliases: [migration]
created: 2026-09-30
---

# he-migration（迁移工作流）

## 边界

- 本包只承载 `/goal` 的声明式契约：`workflow.md` 声明步骤顺序、输入输出与门禁，
  `templates/` 携带步骤提示词与门禁文案；代码零流程知识，`src/` 不出现本包名。
- 单点改动、一次性问答不要启动工作流；判据同 `/goal` 默认引导。

## Pattern

迁移类目标（数据 / 配置 / 系统的受控搬迁）用 `/goal new <描述> --workflow he-migration`
（或别名 `migration`）启动。共 4 步：盘点 → 映射 → 迁移 → 回滚预案。命令族与推进语义同
`/goal` 默认工作流；workflow 包与 revision 在创建时冻结，运行中改配置不换流程。

## Steps

1. 用 `/goal new <描述> --workflow he-migration` 创建 goal；步骤语义以包内 `workflow.md` 为唯一权威。
2. 推进与恢复用 `/goal next` / `/goal resume`；进度用 `/goal status`；预检用 `/goal doctor`。
3. 盘点与映射是只读步骤，不得改动源系统；回滚预案冻结前不得执行任何不可逆操作。
