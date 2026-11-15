---
type: epic
parent: initiative-heagent
covers: ["R1", "R3"]
sources: []
companions: []
after: []
risk: low
---

# 代码架构重构

## Description

拆分大文件，降低代码复杂度，提升可维护性。

## Outcome

超过 800 行的大文件全部拆分完成，复杂热点消除，单文件均低于 1000 行。

## Requirements

- R1 (FR1): 拆分超过 800 行的大文件，降低单文件复杂度，提升可维护性
- R3 (FR3): 提取重复逻辑，简化深层嵌套，消除魔法数字

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

- http_server/goal/workflow_runner/catalog 拆分到位
- 会话管理共享、嵌套重构、魔法数字消除完成
- 全量测试与架构契约测试通过。

## Boundaries

无。

## References

- 归档的 v6 分解与勘误: _bmad-output/initiative-heagent/archive-v6/epics.md
- PRD: _bmad-output/initiative-heagent/prd-heagent/prd-heagent.md
