---
title: 'Review Retrospective and Correct Course Closure'
type: 'feature'
created: '2026-09-01'
status: 'done'
review_loop_iteration: 0
baseline_commit: '1acd7a3aeca40b936b3fb1223ab682b4ace64a44'
context:
  - 'E:/AI/HeAgent/AGENTS.md'
  - 'E:/AI/HeAgent/src/heagent/engine/workflow.py'
  - 'E:/AI/HeAgent/src/heagent/engine/workflow_runner.py'
  - 'E:/AI/HeAgent/src/heagent/engine/artifacts.py'
---

<frozen-after-approval reason="human-owned intent - do not modify unless human renegotiates">

## Intent

**Problem:** 声明式 Goal 工作流已经可以推进和恢复，但尚不能把 Review 发现规范地退回实现，也没有 Epic 级 retrospective 或可审计的 correct-course 记录。

**Approach:** 在 engine 增加通用的 Review verdict、Retrospective 与 CorrectCourse Pydantic 产物和确定性状态操作；由 Markdown workflow/后续 CLI 调用这些通用能力，不让角色 Agent 自行改写 Goal phase。

## Boundaries & Constraints

**Always:** Review 必须保留 findings 和证据；只有无阻塞 finding 的 verdict 才允许确认完成；退回 implementation 不能丢失已完成 Story 或 checkpoint 证据；retrospective 必须引用完成 Story/验收证据；correct-course 必须写明原阶段、目标阶段、原因和影响；所有状态迁移仍经 `WorkflowOrchestrator`。

**Ask First:** 若要改变 `sprint-status.yaml` 既有状态值或新增远程/自动提交行为，先停止并请求确认。

**Never:** 不在此 Story 实现完整 `/goal` UI、样例 Epic 或自动重写 Epic/Story Markdown；不删除 review 发现；不让 LLM 直接绕过 Gate 改状态。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|----------------------------|----------------|
| Review passes | implementation evidence + zero blocking findings | review verdict permits completion | missing evidence blocks verdict |
| Review fails | one or more blocking findings | workflow returns to implementation with findings preserved | invalid return target fails loudly |
| Epic retrospective | completed Story evidence | retrospective has outcomes, evidence, lessons and actions | incomplete Story list blocks artifact |
| Correct course | material scope/design change | record explains from/to phase and impact | blank reason or illegal transition fails |

</frozen-after-approval>

## Code Map

- `src/heagent/engine/workflow.py` -- legal phase transitions, block/fail/wait semantics; extension must reuse these.
- `src/heagent/engine/workflow_runner.py` -- persisted declarative step state and evidence boundary; no BMad-specific branch belongs here.
- `src/heagent/engine/artifacts.py` -- typed artifact/frontmatter conventions and explicit validation errors.
- `src/heagent/cli.py` -- declarative `/goal` route already delegates to engine; direct CLI feature expansion is out of this Story.
- `tests/test_engine_workflow.py` and `tests/test_workflow_runner.py` -- existing transition and recovery contracts.

## Tasks & Acceptance

**Execution:**
- [x] `src/heagent/engine/agile.py` -- add typed review verdict, retrospective and correct-course records with deterministic validation and state helpers.
- [x] `src/heagent/engine/__init__.py` -- export the new public engine API.
- [x] `tests/test_agile_closure.py` -- cover review pass/fail, evidence requirements, retrospective completeness, legal/illegal correction transitions and immutable source state.
- [x] `docs/frame.md` -- document closure artifact ownership and the review-to-implementation loop.

**Acceptance Criteria:**
- Given review evidence and blocking findings, when a verdict is applied, then the returned state is implementation/running, findings remain attached to the verdict, and the input state is unchanged.
- Given review evidence with no blocking finding, when a verdict is applied, then no false implementation rollback occurs and completion eligibility is explicit.
- Given an Epic retrospective, when any listed Story lacks done status or acceptance evidence, then construction fails loudly.
- Given a correct-course record, when its target phase is not legal from the source phase, then it fails without altering source state.

## Verification

**Commands:**
- `pytest tests/test_agile_closure.py tests/test_engine_workflow.py tests/test_workflow_runner.py -q --basetemp E:/AI/HeAgent/workflow_test_tmp47_6` -- expected: all closure and existing state tests pass.
- `ruff check src tests` -- expected: no diagnostics.
- `mypy src` -- expected: no errors outside known environment-owned third-party stub failures.

## Suggested Review Order

- Review verdict and legal phase rollback
  [`agile.py:1`](../../src/heagent/engine/agile.py#L1)
- Closure record coverage
  [`test_agile_closure.py:1`](../../tests/test_agile_closure.py#L1)
