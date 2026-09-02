---
title: 'Goal 声明式工作流收敛与根目录迁移'
type: 'refactor'
epic: 47
status: 'done'
created: '2026-09-02'
source_specs:
  - 'spec-workflow-md-core.md'
  - 'spec-workflow-root-relocation.md'
---

# Goal 声明式工作流收敛与根目录迁移

## Intent

将 `/goal` 工作流从分散的外部 `step-*.md` 文件收敛为单一、自包含的 `workflow.md`，并将默认工作流及模板迁移到 `.heagent/workflows/` 根目录。Goal 初始化使用标准 `GOAL.md`，不再依赖 `goal.txt`；工作流步骤统一使用本地技能的 canonical `he-agent-*` 角色 ID。

## Scope

- `SkillPackage.read_workflow()` 支持 `workflow.md` 内嵌的 `## Step NN: name` 步骤契约，同时保留外部步骤文件兼容读取。
- `WorkflowResource` 暴露 `entrypoint`、`on_create`、`step_executor`；CLI 只接受受支持的声明，并对未知声明显式失败。
- `/goal` 默认读取 `.heagent/workflows/workflow.md`，创建并解析标准 `GOAL.md`。
- 工作流和四个模板位于 `.heagent/workflows/`；旧的 `bmad-development/` 副本已删除。
- 兼容名称仅保留在技能元数据的 `source_id` 和 `aliases` 中，不作为工作流主角色标识。

## Canonical role mapping

| Step | Role |
|------|------|
| 01 analyze-requirements | `he-agent-analyst` |
| 02 define-product-scope | `he-agent-pm` |
| 03 design-experience | `he-agent-ux` |
| 04 design-architecture | `he-agent-architect` |
| 05 clarify-and-route | `he-agent-analyst` |
| 06 implement-and-verify | `he-agent-dev` |

## Code Map

- `.heagent/workflows/workflow.md` -- 默认的六步自包含工作流定义。
- `.heagent/workflows/templates/` -- Goal、Epic、Phase、Story 模板。
- `src/heagent/memory/skill_packages.py` -- 内嵌步骤解析、声明字段和角色字段。
- `src/heagent/cli.py` -- 默认路径、声明校验、GoalArtifact 创建/读取和角色技能加载。
- `tests/test_workflow_resources.py` -- 工作流资源及内嵌步骤解析契约。
- `tests/test_goal_declarative_workflow.py` -- `/goal` 初始化、checkpoint、恢复和显式失败契约。
- `docs/frame.md` -- 架构权威文档中的工作流与模板路径。

## Acceptance Criteria

- Given `.heagent/workflows/workflow.md`，when `/goal` 加载默认工作流，then CLI 不访问 `bmad-development/workflow.md`。
- Given 自包含工作流，when 解析步骤，then 得到连续的六步及上表中的 canonical role 值、输入、输出、checkpoint 和 validation 约束。
- Given `/goal new <description>`，when 初始化成功，then 创建可由 `parse_artifact()` 解析的标准 `GOAL.md` 和 `current` 指针，不创建 `goal.txt`。
- Given 缺失或不支持的 workflow 声明，when 执行 `/goal`，then 显式失败，不回退到旧流程。
- Given `.heagent/workflows/templates/`，when 读取四个模板，then 内容与迁移前模板逐字一致。
- Given checkpoint、暂停或恢复，when 运行 focused workflow tests，then 已完成步骤不重复执行，缺失工作流时显式失败。

## Implementation status

- [x] 内嵌 workflow/step Pydantic 资源契约与顺序校验。
- [x] 默认 BMad 工作流收敛为单一 `workflow.md`。
- [x] Goal 元数据改用标准 `GOAL.md`。
- [x] 默认路径、测试和架构文档迁移到 `.heagent/workflows/`。
- [x] 旧 `bmad-development/` 目录及其副本文件删除。
- [x] 工作流角色统一为 `he-agent-*` canonical ID。

## Verification

- `pytest tests/test_goal_declarative_workflow.py tests/test_workflow_resources.py -q --basetemp .pytest_tmp_local` -- 12 passed。
- `ruff check src/heagent/cli.py tests/test_goal_declarative_workflow.py tests/test_workflow_resources.py` -- passed。
- 模板 SHA-256 逐文件比较通过。
- 根目录工作流解析得到六个 canonical role，顺序与上表一致。

## History

本 spec 合并并替代 implementation-artifacts 中的 `spec-workflow-md-core.md`（工作流自包含化）和 `spec-workflow-root-relocation.md`（根目录迁移）。两份来源 spec 的实现任务均已完成；本文件是 Epic 47 下唯一的合并归档。
