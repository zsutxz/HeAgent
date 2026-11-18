---
type: epic
parent: initiative-heagent
covers: ["R7", "R9", "R10", "R11"]
sources: []
companions: []
after: []
risk: low
---

# 用户体验优化

## Description

改进错误提示，增强进度反馈，提供交互式帮助，降低配置错误率 > 50%。

## Outcome

FAQ、错误索引、调优指南、示例库齐备，错误信息友好、进度可见、帮助上下文化。

## Requirements

- R7 (FR7): 增加 FAQ、错误信息解释索引、性能调优指南、示例库
- R9 (FR9): 提供友好的错误信息，包含可用选项、文档链接、建议操作
- R10 (FR10): 为长时间操作提供进度提示
- R11 (FR11): 在 REPL 中提供上下文帮助

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

- docs/faq.md、docs/errors.md、docs/performance.md、examples/ 达标
  - as-built（2026-11-18）：FAQ 36 条（票面 >=20）；`docs/errors.md` 传输层 35 码 + 框架 9 类 + CLI 12 条 + 关键词表；`docs/performance.md` 五节；`examples/` 5 示例实跑通过（票面 >=5）。
- 错误格式统一含建议
  - as-built：三段块（描述 + `Try:` + `Docs:`）+ 可选 `Try these commands:`；10 场景 / 25 条目 / 15 条去重命令，接入 console / http / wiring 的真实出口（判据 `tests/test_cli_error_format.py`、`tests/test_cli_suggestions.py`）。
- 工具/文件/后台进度可见
  - as-built：`>3s` 工具耗时行（交互 + 单次两个入口）、`>10MB` 真分块读写进度、`GET /api/tasks` 与 `/api/tasks/{task_id}`、`heagent cron status`。
  - 边界：进度注册表是**进程内**单例 ⇒ 跨进程不可见（登记 A56，不构成缺陷，口径已写进 `docs/frame.md`）。
- /help、命令建议、配置向导可用。
  - as-built：`/help <command>` 四段详情（未知命令给近似建议）、错误场景建议命令、`heagent init --interactive` 45 项 / 11 个配置面（非 tty 显性拒绝 + 生成后三重校验 + 原子写）。

## Boundaries

无。

## References

- 归档的 v6 分解与勘误: _bmad-output/initiative-heagent/archive-v6/epics.md
- PRD: _bmad-output/initiative-heagent/prd-heagent/prd-heagent.md
