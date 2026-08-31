- source_spec: `docs/bmad-heagent-plan.md`
  summary: 实现 WorkflowOrchestrator，负责目标级阶段路由、前置条件、人工闸门和失败状态。
  evidence: 该目标可独立定义阶段状态机、迁移校验和闸门行为，并可在技能包运行时完成后单独测试交付。
- source_spec: `docs/bmad-heagent-plan.md`
  summary: 实现目标级 workflow.json、checkpoint、暂停恢复和幂等持久化。
  evidence: 该目标拥有独立的持久化模型与恢复验收标准，依赖编排器但不必与技能包运行时同批交付。
- source_spec: `docs/bmad-heagent-plan.md`
  summary: 实现 TokenBudgetManager 的分段预算、自动 rollover 和恢复信封。
  evidence: Token 分段涉及独立的预算计数、事件和上下文重建逻辑，可在目标级恢复稳定后单独交付。
- source_spec: `docs/bmad-heagent-plan.md`
  summary: 完善目标级 CLI、审计、成本统计、测试覆盖和相关文档。
  evidence: 这些是面向运维和质量的收尾交付物，能够在核心运行时、编排和恢复功能完成后独立验收。
