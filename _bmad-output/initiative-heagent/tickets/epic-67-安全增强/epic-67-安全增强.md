---
type: epic
parent: initiative-heagent
covers: ["R14", "R15", "R16"]
sources: []
companions: []
after: []
risk: low
---

# 安全增强

## Description

加固安全机制，增强安全测试，确保无高危漏洞，审计完整。

## Outcome

输入验证统一，审计与敏感操作留痕完整，密钥管理增强，端点与沙箱逃逸测试覆盖，依赖精简并锁定。

## Requirements

- R14 (FR14): 统一输入验证，增强审计
- R15 (FR15): 安全扫描与渗透测试
- R16 (FR16): 依赖精简与锁定（勘误 2026-11-13：FR16.2 并入 FR15.1）

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

- 验证框架/审计日志/留痕/轮换提醒/keyring 达标
- 漏洞扫描入 CI
- 端点与沙箱逃逸测试通过
- 依赖减 >10% 并锁定。

## Boundaries

无。

## References

- 归档的 v6 分解与勘误: _bmad-output/initiative-heagent/archive-v6/epics.md
- PRD: _bmad-output/initiative-heagent/prd-heagent/prd-heagent.md
