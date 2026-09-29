---
stepsCompleted: [step-01-validate-prerequisites, step-02-design-epics, step-03-create-stories, step-04-final-validation]
status: final
inputDocuments:
  - docs/goal-optimization-plan.md
  - docs/frame.md
  - _bmad-output/epics/epic-51-goal-workflow优化周期/brief.md
  - _bmad-output/epics/epic-51-goal-workflow优化周期/ARCHITECTURE-SPINE.md
---

# HeAgent - Epic Breakdown（Epic 51：`/goal` 与 workflow 可信交付优化）

## Epic 51

把现有声明式 `/goal` 工作流升级为可预检、可审计、可验证、可审批、可安全扩展的交付系统，同时保持 `WorkflowRunner`、checkpoint 与旧 Goal 的兼容性。

## Story 列表

| Story | 名称 | 依赖 | 状态 |
|---|---|---|---|
| 51-1 | Goal 预检与统一状态视图 | 无 | ready-for-dev（已有未提交初版） |
| 51-2 | 显式 Workflow 事件与转换表 | 51-1 | in-progress（已有未提交初版） |
| 51-3 | 结构化执行证据模型 | 51-2 | ready-for-dev |
| 51-4 | 真实质量 Gate 与 `/goal verify` | 51-3 | ready-for-dev |
| 51-5 | 步骤级审批与决策记录 | 51-2 | ready-for-dev |
| 51-6 | 多 workflow 模板与创建时冻结 | 51-4, 51-5 | ready-for-dev |
| 51-7 | 受控 GoalScript 与 ScriptRuntime | 51-6 | ready-for-dev |
| 51-8 | Story 依赖图、安全并行、集成验收与文档收口 | 51-3, 51-4, 51-5, 51-6, 51-7 | ready-for-dev |

## FR 覆盖

- FR-1 → 51-1
- FR-2 → 51-2
- FR-3 → 51-3
- FR-4 → 51-4
- FR-5 → 51-5
- FR-6 → 51-6
- FR-7 → 51-7
- FR-8/FR-9 → 51-8

## 实施约束

1. Story 51-1/51-2 开工前先审查并吸收当前工作区未提交实现，不得覆盖用户已有改动。
2. 每个 Story 的验证命令是规划口径，执行后才能登记实测结果。
3. `WorkflowRunner`、checkpoint、工具治理链和 Git 提交授权纪律不可被 Story 局部方案改写。
4. 若 51-7 的宿主解释器脚本模式无法满足安全裁决，则允许只交付可信本地包模式，并把隔离 worker 明确递延；不得伪称已隔离。
