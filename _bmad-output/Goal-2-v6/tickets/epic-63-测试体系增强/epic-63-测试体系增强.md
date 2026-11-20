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
  - as-built（2026-11-18）：前三项为新增测试面（`test_context_boundary` / `test_tool_concurrency` / `test_provider_all_fail`）；沙箱降级由既有 `tests/test_sandbox_docker.py` 49 判据覆盖，63.4 裁定 dropped（`4aaef8f`）。
- ≥5 条性能基线入 CI
  - as-built：基线本体（`tests/test_benchmarks.py`，14 条 `-m benchmark`）早于本 epic 存在；63.5 实际交付为 CI `--benchmark-compare-fail=mean:10%` 强制门禁与嵌套 glob 死分支修复（`cab4552`）。
- conftest fixture ≥10、tests/fixtures/ 建立、参数化 >30%。
  - as-built：4 个 canonical fixture + 21 处重复定义收敛（`0df59ad`）；`tests/fixtures/` 三域 + 三条可执行判据（`b75075a`）；参数化口径 = touched-scope 78%（`abf96d9`）。

## Boundaries

无。

## References

- 归档的 v6 分解与勘误: _bmad-output/Goal-2-v6/epics.md
- PRD: _bmad-output/Goal-2-v6/prd-heagent/prd-heagent.md
