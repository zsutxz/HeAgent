---
type: initiative
title: "HeAgent 项目改进计划"
sources: ["_bmad-output/initiative-heagent/prd-heagent/prd-heagent.md"]
companions: []
risk: low
---

# HeAgent 项目改进计划

## Description

HeAgent 是一个架构清晰、文档完善的实验性 AI Agent 框架（v0.8.4）。经系统性审查，项目在架构设计、测试覆盖、文档完整性方面表现优秀，但在大文件重构、用户体验、性能优化、工程自动化等方面存在改进空间（来源：project-improvement-report，2026-11-11）。

## Outcome

- 提升代码可维护性（降低 30% 单文件复杂度）
- 优化用户体验（降低 50% 配置错误率）
- 提升开发效率（增加 40% CI 自动化覆盖）
- 增强系统性能（缓存与批量操作优化）

## Requirements

- R1 (FR1): 拆分超过 800 行的大文件，降低单文件复杂度，提升可维护性
- R2 (FR2): 建立完整的异常层次结构，为每个模块定义专用异常，统一错误码体系
- R3 (FR3): 提取重复逻辑，简化深层嵌套，消除魔法数字
- R4 (FR4): 引入缓存机制、批量操作优化、懒加载，提升系统性能
- R5 (FR5): 增强边界条件测试、错误路径测试、性能基准测试
- R6 (FR6): 提取常用 fixture，建立测试数据管理机制
- R7 (FR7): 增加 FAQ、错误信息解释索引、性能调优指南、示例库
- R8 (FR8): 使用 MkDocs 生成 API 文档，从 docstring 自动生成（勘误 2026-11-13：已定 MkDocs）
- R9 (FR9): 提供友好的错误信息，包含可用选项、文档链接、建议操作
- R10 (FR10): 为长时间操作提供进度提示
- R11 (FR11): 在 REPL 中提供上下文帮助
- R12 (FR12): CI/CD 建设与自动化发布（勘误 2026-11-13：CI 已存在，收敛为勘差 + ratchet）
- R13 (FR13): 提供开发环境配置，增强日志
- R14 (FR14): 统一输入验证，增强审计
- R15 (FR15): 安全扫描与渗透测试
- R16 (FR16): 依赖精简与锁定（勘误 2026-11-13：FR16.2 并入 FR15.1）
- R17 (NFR1): 代码质量：测试覆盖率 ≥ 87%，零 lint 错误，类型注解完整
- R18 (NFR2): 性能：冷启动 < 2s，Provider 调用 < 100ms，内存 < 500MB
- R19 (NFR3): 可维护性：单文件 < 1000 行，函数 < 50 行，圈复杂度 < 10
- R20 (NFR4): 可扩展性：新 Provider/Tool 无需修改核心代码
- R21 (NFR5): 安全性：无高危漏洞，敏感数据加密，审计完整
- R22 (NFR6): 兼容性：Python 3.11+，跨平台支持
- R23 (NFR7): 文档完整性：所有公开 API 有文档，配置项有说明

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

- 代码质量：测试覆盖率 ≥ 87%，ruff / mypy / bandit 全过，单文件 < 1000 行
- 性能指标：冷启动降低 > 20%，技能匹配提升 > 30%，元数据缓存命中 > 80%
- 用户体验：配置错误率降低 > 50%，错误含可操作建议 > 80%，示例 ≥ 5 个
- 工程自动化：CI 自动化覆盖 > 90%，PR 全量测试，发布流程自动化
- 文档完整性：API 文档全覆盖，FAQ ≥ 20 条，错误索引 > 80%

## Boundaries

- 分布式支持（多进程架构探索）、插件系统形式化、远程工具执行为低优先级（6 个月后考虑），不入本 initiative 范围。

## References

- prd-heagent/（PRD，含 2026-11-13 勘误）
- project-improvement-report/（改进审查报告）
- story-estimates/（Story 工作量估算）
- archive-v6/epics.md（v6 原始分解与勘误，2026-11-13）
- archive-v6/sprint-status.yaml（v6 全周期 Epic/Story 状态，2026-05~11）
- _bmad-output/migration-v6-v7.md（迁移计划与验证记录，2026-11-15 status: done）

## Notes

- Action item: epic-52-retro-item-1 真实 LLM 全链冒烟（用一个小 goal 走完 /goal new → next → run，含并行批授权与审计事件观察，顺带验证绑旧 revision 的 goal 在 resume 时的漂移处置）；owner: tan；epic: 52。源自归档 sprint-status.yaml action_items，属历史 Epic 52 的 provenance，非本计划 8 epic。
- 本 initiative 由 v6 planning-artifacts/ 迁移而来（migration-1，2026-11-15），Story 1.4 按勘误记 done，其余 58 entry 为 backlog。
- 票树之外的**使能改动**：`70f1484`（`.heagent/skills/loop/` 的 v7 工作流重写，2026-11-15）**不建追认票**、也不立 ADR。理由：① 它只改 skill 正文与三份模板（`SKILL.md` / `workflow.md` / `templates/`），无 `src/` 代码、无可执行判据，追认票会造出「有票无 verify 无 build 记录」的假凭据（Epic 62 retro V4 正在批评票态凭据不对称）；② ADR 写入门槛是「仓库内无既有记录」，而 v7 口径本体已记在 `AGENTS.md` / `CLAUDE.md` 的「BMAD v7 产物体系」节与该提交的 message 里。溯源入口 = 本行（票树根文件即达）。登记理由见 `_bmad-output/open-items.md` 的 A57 ②。
