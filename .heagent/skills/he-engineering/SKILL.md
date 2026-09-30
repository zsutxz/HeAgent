---
canonical_id: he-engineering
name: he-engineering
description: 工程实现类目标走 /goal 的三步声明式工作流（方案→实现→验证）
tags: [goal, workflow, engineering]
aliases: [engineering]
created: 2026-09-30
---

# he-engineering（工程实现工作流）

## 边界

- 本包只承载 `/goal` 的声明式契约：`workflow.md` 声明步骤顺序、输入输出与门禁，
  `templates/` 携带步骤提示词与门禁文案；代码零流程知识，`src/` 不出现本包名。
- 单点改动、一次性问答不要启动工作流；判据同 `/goal` 默认引导。

## Pattern

工程实现类目标（方案设计 → 代码实现 → 测试验证的完整交付）用
`/goal new <描述> --workflow he-engineering`（或别名 `engineering`）启动。共 3 步：
方案 → 实现 → 验证。本包 frontmatter 显式声明 `revision: "1"`（声明 revision 的演示路径）：
包内容改动不触发派生漂移，推进 revision 由声明方负责；其余行为同 `/goal` 默认工作流。

## Steps

1. 用 `/goal new <描述> --workflow he-engineering` 创建 goal；步骤语义以包内 `workflow.md` 为唯一权威。
2. 推进与恢复用 `/goal next` / `/goal resume`；进度用 `/goal status`；预检用 `/goal doctor`。
3. 实现步骤只改方案声明的写集；验证步骤必须记录确切命令与结果，不以 Markdown 声称代替证据。
