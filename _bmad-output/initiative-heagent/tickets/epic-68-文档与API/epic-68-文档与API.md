---
type: epic
parent: initiative-heagent
covers: ["R8"]
sources: []
companions: []
after: []
risk: low
---

# 文档与 API

## Description

生成 API 文档，完善用户文档，确保所有公开 API 有文档。

## Outcome

MkDocs API 文档覆盖全部公开 API 并自动部署。

## Requirements

- R8 (FR8): 使用 MkDocs 生成 API 文档，从 docstring 自动生成（勘误 2026-11-13：已定 MkDocs）

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

- docstring 全覆盖、自动化生成与部署流程配置完成、文档与代码版本一致。

## Boundaries

无。

## References

- 归档的 v6 分解与勘误: _bmad-output/initiative-heagent/archive-v6/epics.md
- PRD: _bmad-output/initiative-heagent/prd-heagent/prd-heagent.md
