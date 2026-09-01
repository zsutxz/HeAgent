---
title: 'Declarative BMad Agile Goal Workflow'
type: 'feature'
created: '2026-09-01'
status: 'draft'
review_loop_iteration: 0
context:
  - 'E:/AI/HeAgent/docs/frame.md'
  - 'E:/AI/HeAgent/docs/bmad-heagent-plan.md'
  - 'E:/AI/HeAgent/AGENTS.md'
---

<frozen-after-approval reason="human-owned intent - do not modify unless human renegotiates">

## Intent

**Problem:** 当前 `/goal` 主要是 Goal→Story 的轻量循环，缺少 BMad 敏捷开发所需的 Epic 层、规范化阶段产物、角色 Agent 和可声明的 step-file 工作流，导致流程规则容易漂移到 CLI 分支或会话记忆中。

**Approach:** 增加一个 Markdown 声明的 BMad 工作流包和通用 step Runner，将 Goal→Epic→Story 的层级、产物契约、Ready/Done gate、Sprint、Review、Retrospective 固化为文件协议；迁移并定制 PM、Analyst、Architect、UX、Dev 关键 Agent；接入 `/goal`，保留没有新 workflow 配置时的现有 GOAL.md Story 模式。

## Boundaries & Constraints

**Always:** GOAL.md 只维护 Goal/Epic 看板；`_bmad-output/sprint-status.yaml` 继续是 Epic/Story 状态唯一写目标；Epic 和 Story 必须有唯一 ID、固定 Markdown 章节和可验证验收标准；一个 Story 一个执行会话且 WIP=1；step 只能按声明顺序推进；产物缺失、格式非法、验收失败、review 问题或人工 checkpoint 必须显式停止；所有工具执行仍经过现有 Engine/Policy/Safety 链；资源读取复用 `SkillPackage` 的根目录围栏。

**Ask First:** 若实现中需要改变旧 `/goal` 命令输出、移动现有 `_bmad-output` 产物路径、改变 `sprint-status.yaml` 状态语义，必须先停下请求确认。

**Never:** 不删除或覆盖旧 Goal 目录；不复制一套与 sprint-status 冲突的 Story 状态；不把具体 BMad 流程分支重新硬编码进 CLI；不让 LLM 自行跳过 Epic/Sprint/Review gate；不直接修改 `_bmad/render` 生成快照作为源文件；不迁移全部 BMad 技能作为本功能的前置条件。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|----------------------------|----------------|
| New declarative goal | description + workflow package | Goal/Epic board and workflow state initialized; first step selected | Missing/invalid package fails loudly; no fake completion |
| Missing artifact | step requires absent file | Workflow remains at current step and reports missing artifact | Persist blocked reason and checkpoint |
| Invalid artifact | output lacks required frontmatter/sections/AC | Step is not completed | Report exact contract violation |
| Story review failure | implementation reaches review with findings | Story remains in review/in-progress and routes back to implementation | Preserve findings and next action |
| Human checkpoint | step declares checkpoint | State is persisted as waiting_user; no next step execution | Resume only after explicit command |
| Legacy goal | Goal has no declarative workflow | Existing GOAL.md Story behavior remains unchanged | Existing errors and tests remain valid |

</frozen-after-approval>

## Code Map

- `src/heagent/cli.py:922-1545` -- slash registration, current Goal creation/Story advancement, pause/resume/audit/cron; preserve legacy path and add declarative routing at this boundary.
- `src/heagent/engine/workflow.py:347-620` -- Pydantic workflow state, phase transitions, route gates, checkpoint persistence, token/recovery primitives; reuse rather than duplicating state logic.
- `src/heagent/memory/skill_packages.py:70-240` -- root-fenced lazy package/resource reads; extend only where needed for workflow and step resources.
- `src/heagent/engine/__init__.py:1-90` -- public engine exports for new Runner/contracts.
- `.heagent/skills/goal/SKILL.md:19-74` -- current Goal/Story Markdown contract; preserve legacy semantics and update only for the new hierarchy boundary.
- `_bmad/_config/skill-manifest.csv` -- canonical BMad skill IDs, agent roles, phases, dependencies and output types.
- `_bmad/render/bmad-build/heagent-50877a51e192/a46101117e1533447fcf/workflow.md` -- generated step-file workflow reference; do not edit generated snapshot.
- `tests/test_goal_command.py`, `tests/test_goal_workflow_smoke.py`, `tests/test_engine_workflow.py` -- existing command, smoke, transition and checkpoint contracts.

## Tasks & Acceptance

**Execution:**
- [ ] Add declarative workflow/step Pydantic contracts and a generic one-step Runner; validate frontmatter, required inputs, outputs, gates, next-step references, and checkpoint persistence.
- [ ] Extend package/resource loading for workflow.md, ordered step files, templates, references and copied agent skill packages with root-fenced reads.
- [ ] Add a sample `feature-development` workflow with Goal→Epic→Story, BMad phases, artifact templates, Ready/Done gates and PM/Analyst/Architect/UX/Dev roles.
- [ ] Integrate `/goal new|next|run|status|pause|resume|audit` with declarative workflow when configured; retain and test the legacy GOAL.md-only path.
- [ ] Add tests for hierarchy, artifact contract failures, gates, review rollback, checkpoint/resume, legacy compatibility, and the complete two-Story sample Epic.
- [ ] Update architecture and usage docs with artifact ownership, BMad phase flow, and migration rules.

**Acceptance Criteria:**
- Given a valid declarative workflow and goal description, when `/goal new` runs, then Goal, Epic/Story planning outputs and runtime state are created with stable IDs and no implementation step is started before planning gates pass.
- Given a ready Epic with at least one Ready-for-Development Story, when `/goal next` runs, then exactly one Story session executes and its status changes only after all acceptance evidence and Definition of Done checks pass.
- Given a missing or malformed required artifact, when a step is attempted, then the workflow remains at that step, records a deterministic blocked reason, and does not advance.
- Given a review finding, when review completes, then the workflow routes back to implementation and preserves the finding as an actionable artifact.
- Given a human checkpoint or process interruption, when `/goal resume` runs, then execution restarts from the last persisted unfinished step without repeating completed Story work.
- Given a Goal without a declarative workflow, when existing `/goal` commands run, then current GOAL.md Story behavior and existing tests remain compatible.

## Design Notes

Markdown owns process definitions and artifact contracts; structured `workflow.json` owns machine runtime metadata. This avoids duplicating status in free-form Markdown while keeping the workflow itself editable and reviewable. The first migrated package is one vertical `feature-development` workflow; additional BMad skills can be imported after its end-to-end path is proven.

## Verification

**Commands:**
- `pytest tests/test_goal_command.py tests/test_goal_workflow_smoke.py tests/test_engine_workflow.py -q` -- expected: all existing and new goal/workflow tests pass.
- `pytest -q` -- expected: full regression suite passes.
- `ruff check src tests` -- expected: no diagnostics.
- `mypy src` -- expected: no errors.
