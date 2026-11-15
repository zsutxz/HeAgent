---
type: epic
parent: initiative-heagent
covers: ["R5", "R6"]
sources: []
companions: []
after: []
risk: low
---

# 测试体系增强

## Description

增强边界条件测试、错误路径测试、性能基准测试，提升测试可维护性，确保测试覆盖率 ≥ 87%。

## Outcome

边界、错误路径与性能基准测试补齐，fixture 与测试数据集中管理，参数化消除重复。

## Requirements

- R5 (FR5): 增强边界条件测试、错误路径测试、性能基准测试
- R6 (FR6): 提取常用 fixture，建立测试数据管理机制

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

- 大上下文/并发/Provider 失败/沙箱降级测试就位
- ≥5 条性能基线入 CI
- conftest fixture ≥10、tests/fixtures/ 建立、参数化 >30%。

## Boundaries

无。

## References

- 归档的 v6 分解与勘误: _bmad-output/initiative-heagent/archive-v6/epics.md
- PRD: _bmad-output/initiative-heagent/prd-heagent/prd-heagent.md
