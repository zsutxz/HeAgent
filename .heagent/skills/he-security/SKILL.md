---
canonical_id: he-security
name: he-security
description: 安全评估类目标走 /goal 的三步声明式工作流（攻击面收集→风险评估→处置方案）
tags: [goal, workflow, security]
aliases: [security]
created: 2026-09-30
---

# he-security（安全评估工作流）

## 边界

- 本包只承载 `/goal` 的声明式契约：`workflow.md` 声明步骤顺序、输入输出与门禁，
  `templates/` 携带步骤提示词与门禁文案；代码零流程知识，`src/` 不出现本包名。
- 本工作流是**评估与方案**流程：只做只读收集与书面处置，不执行利用、不改动防御设施。
- 单点改动、一次性问答不要启动工作流；判据同 `/goal` 默认引导。

## Pattern

安全评估类目标（梳理攻击面、评估风险并给出处置方案）用
`/goal new <描述> --workflow he-security`（或别名 `security`）启动。共 3 步：
攻击面收集 → 风险评估 → 处置方案。命令族与推进语义同 `/goal` 默认工作流；
workflow 包与 revision 在创建时冻结，运行中改配置不换流程。

## Steps

1. 用 `/goal new <描述> --workflow he-security` 创建 goal；步骤语义以包内 `workflow.md` 为唯一权威。
2. 推进与恢复用 `/goal next` / `/goal resume`；进度用 `/goal status`；预检用 `/goal doctor`。
3. 全程只读：不执行利用代码、不关闭或绕过任何防御机制；处置只落方案，实施另行立项。
