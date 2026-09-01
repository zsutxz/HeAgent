---
title: 'Goal Epic Story artifact hierarchy and contract'
type: 'feature'
status: 'done'
epic: 47
story: 1
baseline_commit: '8018be0489a7dab1bb2d293ed8a0b25722fd1143'
context:
  - 'E:/AI/HeAgent/docs/frame.md'
  - 'E:/AI/HeAgent/AGENTS.md'
---

# Story 47-1: Goal/Epic/Story 产物层级与契约

## Story

作为框架维护者，我希望 Goal、Epic、Story 和阶段产物有稳定的 Markdown 格式、状态归属和验收契约，以便后续 Agent 和 Runner 能可靠推进敏捷流程。

## Acceptance Criteria

- Given 一个 Goal，when 初始化产物，then `GOAL.md` 只管理 Epic，且每个 Epic 有唯一 ID。
- Given 一个 Epic，when 创建 Epic 产物，then `EPIC.md` 包含目标、价值、范围、依赖、验收标准、Story 列表和 Definition of Done。
- Given 一个 Story，when 创建 Story 产物，then frontmatter、User Story、Given/When/Then 验收标准、Tasks 和 Definition of Done 均存在。
- Given 任意 Epic/Story 状态更新，when 保存状态，then `_bmad-output/sprint-status.yaml` 是唯一写目标，不产生冲突副本。
- Given 缺少必需章节或存在 TBD，when 执行契约校验，then 显式失败且不允许进入下一阶段。

## Tasks

- [x] `src/heagent/engine/artifacts.py` -- 定义 Pydantic 产物契约、frontmatter 解析和 Goal/Epic/Story 层级引用校验。
- [x] `.heagent/workflows/bmad-development/templates/` -- 增加 Goal、Epic、Story 和阶段产物 Markdown 模板，固定章节与状态值。
- [x] `tests/test_artifact_contracts.py` -- 覆盖合法产物、缺失章节、TBD、重复 ID、错误层级引用和 sprint-status 唯一权威。
- [x] `docs/frame.md` -- 记录 Goal→Epic→Story 产物层级、状态所有权和验证边界。

## Definition Of Done

- [x] 测试通过
- [x] 产物模板已落盘
- [x] sprint-status 兼容性已验证
- [x] Review 证据已记录

## Code Map

- `src/heagent/engine/workflow.py` -- 现有 GoalWorkflowState 和 checkpoint 模型；新契约不能复制其运行时状态字段。
- `src/heagent/memory/skill_packages.py` -- 现有 Pydantic skill/package 读取和路径围栏模式，可复用其解析风格。
- `src/heagent/cli.py` -- 当前 `_scan_goal_md` 只支持 Goal→Story；本 Story 不改变 CLI 推进逻辑。
- `_bmad-output/sprint-status.yaml` -- Epic/Story 状态唯一写目标，契约校验必须只读它。

## Verification

- `pytest tests/test_artifact_contracts.py -q` -- expected: all contract and edge-case tests pass.
- `ruff check src tests` -- expected: no diagnostics.
- `mypy src` -- expected: no errors.

## Dev Agent Record

### Completion Notes

- Added typed Goal/Epic/Story Markdown contracts with strict frontmatter, required sections, Given/When/Then validation, unresolved-TBD rejection, and deterministic parent/ID checks.
- Added fixed-heading artifact templates and documented ownership: `_bmad-output/sprint-status.yaml` is the only Epic/Story status authority.
- Verification: `pytest tests/test_artifact_contracts.py -q --basetemp workflow_test_tmp47-1` (4 passed); Ruff and mypy passed for changed Python files.

## File List

- `src/heagent/engine/artifacts.py`
- `src/heagent/engine/__init__.py`
- `.heagent/workflows/bmad-development/templates/GOAL.md`
- `.heagent/workflows/bmad-development/templates/EPIC.md`
- `.heagent/workflows/bmad-development/templates/STORY.md`
- `.heagent/workflows/bmad-development/templates/PHASE.md`
- `tests/test_artifact_contracts.py`
- `docs/frame.md`

## Change Log

- 2026-09-01: Implemented Story 47-1 artifact hierarchy contracts, templates, validation tests, and architecture documentation.
- 2026-09-01: Review patch added Goal-to-Story goal_id consistency validation and regression coverage.

## Suggested Review Order

**Artifact validation**

- 先看契约模型与解析边界
  [`artifacts.py:1`](../../../../../src/heagent/engine/artifacts.py#L1)

- 再看层级与状态权威测试
  [`test_artifact_contracts.py:1`](../../../../../tests/test_artifact_contracts.py#L1)

**Integration and documentation**

- 检查 engine 公共导出
  [`__init__.py:15`](../../../../../src/heagent/engine/__init__.py#L15)

- 检查架构契约说明
  [`frame.md:875`](../../../../../docs/frame.md#L875)
