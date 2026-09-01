---
stepsCompleted: [step-01-validate-prerequisites, step-02-design-epics, step-03-create-stories]
status: planning
---

# HeAgent - Epic 47: 声明式 BMad 敏捷工作流

## Epic Goal

将 HeAgent 的 `/goal` 从 Goal→Story 轻量循环扩展为 Goal→Epic→Story 的 BMad 敏捷开发流程。工作流规则、阶段顺序和产物契约由 Markdown 文件声明，通用 Runner 负责解释执行；PM、Analyst、Architect、UX、Dev 角色以可修改的本地 Agent skill 包提供。

## Agile Contract

- Goal 管理目标和 Epic 看板；Epic 管理产品能力；Story 管理可交付增量。
- `_bmad-output/sprint-status.yaml` 是 Epic/Story 状态唯一写目标。
- Story 进入开发前必须通过 Definition of Ready；完成前必须满足 Definition of Done。
- 一个 Story 一个执行会话，WIP 限制为 1；Review 失败回到实现；Epic 完成后执行 Retrospective。
- 产物缺失、格式非法、验收失败、冲突或人工 checkpoint 必须显式停止。

## Stories

- 47-1：Goal/Epic/Story 产物层级与 Artifact Contract
- 47-2：关键 BMad Agent 迁移与 HeAgent 定制
- 47-3：Markdown workflow/step 资源加载
- 47-4：通用 WorkflowRunner 与阶段 Gate
- 47-5：`/goal` 接入 Epic、Story、Sprint 工作流
- 47-6：Review、Retrospective、Correct Course 闭环
- 47-7：完整样例 Epic、回归测试和文档收口

## Dependency Order

47-1 → (47-2, 47-3) → 47-4 → 47-5 → 47-6 → 47-7

## Epic Acceptance

- 至少一个 Goal 可以包含多个 Epic，每个 Epic 可以包含多个 Story。
- 每个阶段都有固定输入、输出、章节和验证规则。
- 一个样例 Epic 可以从规划经过 Sprint、两个 Story、Review 和 Retrospective 完成。
- 旧版没有 declarative workflow 的 `/goal` 行为保持兼容。
