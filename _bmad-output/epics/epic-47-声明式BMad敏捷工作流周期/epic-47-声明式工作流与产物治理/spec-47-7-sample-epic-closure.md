---
title: 'Sample Epic End-to-End Validation and Documentation Closure'
type: 'feature'
created: '2026-09-01'
status: 'done'
review_loop_iteration: 0
baseline_commit: '1d098e232ac18b01adaeaa22d55fe06453804274'
context:
  - 'E:/AI/HeAgent/AGENTS.md'
  - 'E:/AI/HeAgent/src/heagent/cli.py'
  - 'E:/AI/HeAgent/src/heagent/engine/artifacts.py'
  - 'E:/AI/HeAgent/src/heagent/engine/workflow_runner.py'
  - 'E:/AI/HeAgent/src/heagent/engine/agile.py'
---

<frozen-after-approval reason="human-owned intent - do not modify unless human renegotiates">

## Intent

**Problem:** Epic 47 的组件已有独立测试，但还没有一个将 Goal、Epic、两条 Story、workflow checkpoint、review rollback 和 retrospective 串成一条无网络证据链的验收样例，项目文档也未完整呈现声明式敏捷流程。

**Approach:** 增加一个 deterministic sample Epic smoke test，使用现有 typed artifacts、Runner、closure records 和 stub goal session 从规划推进两条 Story 并验证恢复、review 回退和 retrospective；同步架构文档与 Epic 总览。

## Boundaries & Constraints

**Always:** 样例仅使用临时目录、stub provider 和现有 public API；两个 Story 都必须有 Artifact Contract、完成证据和 sprint 状态语义；测试不访问网络、不使用真实凭据；文档必须保留现有安全边界声明。

**Ask First:** 若样例需要改变 production workflow 的默认配置或全量测试失败来自本 Story 以外的代码，停止并报告。

**Never:** 不新增真实 LLM smoke、不修改已有 Goal/Story 历史目录、不把测试样例当作生产 Epic、不掩盖全量回归失败。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|----------------------------|----------------|
| Two-Story Epic | valid Goal/Epic/Story artifacts | both Stories complete with evidence and retrospective | invalid hierarchy fails before run |
| Checkpoint recovery | first Story checkpoint | resumed run executes only remaining work | repeated resume does not duplicate completion |
| Review rollback | blocking finding in review | workflow returns to implementation with finding preserved | invalid review phase fails loudly |
| Legacy command | no workflow file | existing GOAL.md path remains valid | no declarative fallback is inferred |

</frozen-after-approval>

## Code Map

- `tests/test_goal_declarative_workflow.py` -- existing two-step CLI/checkpoint/legacy regression fixture to extend or compose.
- `tests/test_artifact_contracts.py` -- Goal/Epic/Story hierarchy contract examples.
- `tests/test_agile_closure.py` -- review rollback and retrospective evidence examples.
- `docs/frame.md` -- authoritative architecture documentation for goal workflow additions.
- `_bmad-output/consolidated-overview.md` -- Epic inventory and final status narrative.

## Tasks & Acceptance

**Execution:**
- [ ] `tests/test_goal_epic_story_smoke.py` -- build a two-Story artifact hierarchy, run deterministic workflow/checkpoint recovery, apply review rollback and produce retrospective evidence.
- [ ] `docs/frame.md` -- document declarative Goal→Epic→Story workflow and artifact/closure ownership.
- [ ] `_bmad-output/consolidated-overview.md` -- add Epic 47 scope/status summary.
- [ ] `_bmad-output/epics/.../47-7-sample-epic-regression-docs.md` -- record verification and final Story status.

**Acceptance Criteria:**
- Given the sample Goal/Epic/two Story artifacts, when hierarchy and workflow run, then both Stories reach done with acceptance evidence and an Epic retrospective is constructible.
- Given a checkpoint after the first Story, when resumed repeatedly, then the second Story runs once and no completed Story is duplicated.
- Given a blocking review finding, when its verdict is applied, then implementation is re-entered and its evidence is retained.
- Given no declarative workflow configuration, when legacy goal tests run, then existing GOAL.md behavior remains unchanged.

## Verification

**Commands:**
- `pytest tests/test_goal_epic_story_smoke.py tests/test_goal_declarative_workflow.py tests/test_artifact_contracts.py tests/test_agile_closure.py -q --basetemp E:/AI/HeAgent/workflow_test_tmp47_7` -- expected: all sample and regression tests pass.
- `pytest -q --basetemp E:/AI/HeAgent/workflow_test_tmp47_full` -- expected: full suite passes or unrelated failures are explicitly recorded.
- `ruff check src tests` -- expected: no diagnostics.

## Suggested Review Order

- Two-Story Goal/Epic/Story recovery smoke
  [`test_goal_epic_story_smoke.py:1`](../../tests/test_goal_epic_story_smoke.py#L1)
- Declarative workflow ownership and closure boundary
  [`frame.md:885`](../../docs/frame.md#L885)
- Epic 47 delivery index
  [`consolidated-overview.md:73`](../consolidated-overview.md#L73)
