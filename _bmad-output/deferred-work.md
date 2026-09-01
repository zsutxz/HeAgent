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
- source_spec: `_bmad-output/epics/epic-42-BMad技能包运行时周期/stories/42-1-skill-package-model-resource-safety.md`
  summary: 评估技能包资源读取在并发文件替换下的 TOCTOU 防护策略。
  evidence: 当前路径校验与按路径读取之间存在文件系统竞态窗口；该问题需要 OS/文件描述符级设计，超出本 Story 的用户态路径围栏范围。
  resolution: Epic 46.1 assessment only 已完成。特征测试证明 resolve-then-read 与符号链接替换窗口；当前保留 resolve_under_root 语义，不声称 TOCTOU 完整防护。
  follow_up: 另立实现 Story 评估 descriptor-relative/目录句柄或可信导入 snapshot；OS sandbox 作为外部 defense-in-depth。
- source_spec: `_bmad-output/implementation-artifacts/spec-46-1-skill-resource-toctou-assessment.md`
  summary: 后续评估 descriptor-relative/目录句柄、可信导入 snapshot 或 OS sandbox 加固。
  evidence: Epic 46.1 仅形成 assessment-only 结论，未证明跨平台运行时方案可行，现有路径围栏仍保留竞态残余风险。
