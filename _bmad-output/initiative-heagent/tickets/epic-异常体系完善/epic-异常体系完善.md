---
type: epic
parent: initiative-heagent
covers: ["R2"]
sources: []
companions: []
after: []
risk: low
---

# 异常体系完善

## Description

建立统一的异常层次结构与错误码体系，确保每个核心模块至少有 3 个专用异常。

## Outcome

统一异常层次与错误码体系覆盖全部核心模块，错误可程序化处理。

## Requirements

- R2 (FR2): 建立完整的异常层次结构，为每个模块定义专用异常，统一错误码体系

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

- provider/tool/engine/agent 各至少 3 个专用异常，层次继承清晰，错误码文档与解析完整。

## Boundaries

无。

## References

- 归档的 v6 分解与勘误: _bmad-output/initiative-heagent/archive-v6/epics.md
- PRD: _bmad-output/initiative-heagent/prd-heagent/prd-heagent.md
