---
type: epic
parent: initiative-heagent
covers: ["R4"]
sources: []
companions: []
after: []
risk: low
---

# 性能优化

## Description

引入缓存机制、批量操作优化、懒加载，提升系统性能，冷启动时间降低 > 20%。

## Outcome

元数据与技能匹配缓存、批量预计算与懒加载全部落地，冷启动显著降低。

## Requirements

- R4 (FR4): 引入缓存机制、批量操作优化、懒加载，提升系统性能

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

- Provider 元数据缓存命中 >80%
- 技能匹配缓存与批量预计算提速 >30%
- 懒加载使冷启动降低 >20%。

## Boundaries

无。

## References

- 归档的 v6 分解与勘误: _bmad-output/initiative-heagent/archive-v6/epics.md
- PRD: _bmad-output/initiative-heagent/prd-heagent/prd-heagent.md
