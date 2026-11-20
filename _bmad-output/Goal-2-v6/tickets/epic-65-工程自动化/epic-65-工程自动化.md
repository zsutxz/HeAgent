---
type: epic
parent: initiative-heagent
covers: ["R12", "R13"]
sources: []
companions: []
after: []
risk: low
---

# 工程自动化

## Description

建立 CI/CD 流程，优化开发体验，提升开发效率 > 40%。

## Outcome

质量门禁与 PR 全量测试全自动，版本、CHANGELOG、发布流程自动化，开发环境一键就绪。

## Requirements

- R12 (FR12): CI/CD 建设与自动化发布（勘误 2026-11-13：CI 已存在，收敛为勘差 + ratchet）
- R13 (FR13): 提供开发环境配置，增强日志

## Constraints

- 必须保持严格的 DAG 依赖关系
- network/ 模块不得导入运行栈
- 模块间数据传递必须使用 Pydantic 模型
- 所有代码改动必须有对应测试
- 架构契约测试 tests/test_architecture_contracts.py 必须通过
- 测试覆盖率不得低于 87%
- 大文件重构不得降低性能 > 5%
- 性能优化必须有基准测试对比
- 不得削弱现有安全机制
- 新增功能必须经过安全审查

## Done when

- quality_gate 入 CI 且阻止 merge
- PR 全量测试可视
- 版本/CHANGELOG/发布自动化按勘误口径收敛
- devcontainer、结构化日志、调试模式、性能分析就绪。

## Boundaries

无。

## References

- 归档的 v6 分解与勘误: _bmad-output/Goal-2-v6/epics.md
- PRD: _bmad-output/Goal-2-v6/prd-heagent/prd-heagent.md

## Notes

- 勘误（2026-11-13，见归档 epics.md）：ci.yml 8 job 与 codeql.yml 已存在，本 Epic 由建设降级为勘差 + ratchet；FR12 的 merge 自动发版验收标准按用户裁决 Q2 作废（现状 tag v* → OIDC Trusted Publisher）；FR12.4 收敛为载体与守卫已达。相关 entry 保留原文口径，动工前先 replan。
