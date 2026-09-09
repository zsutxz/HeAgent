---
name: workflow
entrypoint: goal
on_create: persist_goal_identity
step_executor: subagent
checkpoint_mode: auto
open_question_mode: default
---

# development workflow

This file is the complete executable contract for the declarative `/goal`
workflow. The CLI reads this file, persists the goal identity declared by
`on_create`, and invokes one fresh SubAgent for each declared step. Completed
steps are recorded in the goal checkpoint store; no step may be skipped.

All durable non-code project artifacts produced by this workflow, including
requirements, PRDs, architecture records, reviews, and verification reports,
must be written under the project output root `_he-output/`. Source code remains
in its established repository location.

Step 01 is read-only research and step 02 is read-only ideation: neither may
modify project implementation artifacts. Step 06 is the planning step: it splits
the validated scope into stories, orders the work items, assigns every story to a
sprint, and fixes each story's acceptance criteria; it plans, and never
implements. Step 07 is the heavy per-story step: a single session implements,
tests, and verifies one story, and it is the only step allowed to create
implementation artifacts or to add and change test files.
Steps 07 and 08 run once per story in that order: step 07 delivers the story,
step 08 reviews it adversarially and may change code only to fix the Critical
findings it reports. Step 08 is also the final acceptance step: after the final
story it runs the Epic-level integration gate. Every step that changes code must
re-run the affected tests and state the exact commands and results.

Step 07 carries its role contract inline in this file: it declares no `role:`
and depends on no external skill package. Every other step delegates its
methodology to the `.heagent/skills/<role>/SKILL.md` package named by its
`role:`.

## Step 01: market-research
role: bmad-agent-analyst
input: user intent, existing project context
output: market digest, decision drivers, evidence gaps
checkpoint: true
validation: every claim carries source, publication date, and access date; absent evidence is reported as a gap

Research the market, competitors, substitutes, and user-voice evidence that
bear on this goal. Work headless: do not greet, do not ask questions, do not
wait for a user.

Gather evidence with `web_fetch` on URLs you are given or can derive; no web
search tool exists, so unanswered questions are recorded as gaps rather than
closed from training data. A claim you cannot evidence is stated as an
unverified belief or as an open gap, and thin public data is reported as thin.

Deliverable: a market digest (segments, competitors, substitutes, pricing and
positioning evidence), the decision drivers this goal actually depends on, and
an explicit list of evidence gaps with the sources or queries that would close
them. Return the complete digest as your final response.

## Step 02: brainstorm-options
role: bmad-brainstorming
input: user intent, market digest
output: option space, ranked candidate directions
checkpoint: true
validation: at least three materially different directions, each with risks and the evidence it still needs

Facilitate an ideation session over the goal and the market digest. Work
headless in the "ideate for me" stance: do not greet, do not run the composer
page, do not wait for a user, and never stop with waiting_user. Push past the
obvious, shift technique at least twice, then converge on a ranked shortlist.

Keep the session memlog under `.heagent/tmp/brainstorm-<goal-id>/`; it is
scratch state, not a durable artifact. Deliverable: the option space, a ranked
shortlist with trade-offs, and for each direction the risk it carries and the
evidence it would still need. Return the complete session output as your final
response.

## Step 03: analyze-requirements
role: bmad-agent-analyst
input: user intent, market digest, option space, existing project context
output: requirements brief, story breakdown
checkpoint: true
validation: requirements are evidence-backed and testable

Analyze the intent, distinguish facts from assumptions, identify stakeholders,
and produce a requirements brief with acceptance criteria and story-sized work.
Stop for user input when competing interpretations remain.

## Step 04: define-product-scope
role: bmad-agent-pm
input: requirements brief, market digest
output: validated PRD, ordered Epic proposal
checkpoint: true
validation: product value, scope, non-goals, and decisions are explicit

Turn the requirements brief into a validated PRD and ordered Epic proposal.
Record assumptions, priorities, non-goals, and unresolved product decisions.
Order the Epics by value and dependency, and describe each Epic's goal and scope
at the Epic level. Do not split into stories here: the per-story breakdown
(`### S-1 ...`) happens in step 06 once the architecture is known. Return the PRD
and the ordered Epic proposal as your final response.

## Step 05: design-architecture
role: bmad-agent-architect
input: validated PRD
output: architecture, implementation constraints
checkpoint: true
validation: boundaries, interfaces, dependencies, invariants, and failure handling are explicit

Produce the lean technical architecture and decision records. Preserve module
ownership and document security, reliability, migration, and verification paths.

## Step 06: refine-stories
role: bmad-agent-analyst
input: validated PRD, ordered Epic proposal, architecture, implementation constraints
output: clarified implementation scope, sprint plan, story breakdown
checkpoint: true
validation: section: Story Breakdown; section: Sprint Plan; the scope is split into a story list numbered contiguously from S-1 in execution order, each story single-goal, acceptance-criteria-complete, dependency-ordered, and assigned to exactly one sprint

This is the planning step: it turns the validated scope into a sprint-refined,
dependency-ordered story backlog with fixed acceptance criteria. Its four
deliverables are the story split, the sprint refinement, the work-item order, and
the acceptance criteria. Do not implement the change in this step.

Confirm the requested change, inspect relevant context, and subdivide the work
into stories.

Read the validated PRD and the ordered Epic proposal, then the architecture and
its implementation constraints. Confirm the change is still what the PRD asks and
resolve any scope ambiguity into a single goal. The Epic-level split is already
settled in step 04: do not re-plan the Epics.

Split the work into stories. Use exactly one `### S-1 <title>` heading per story:
that heading form is the story list steps 07 and 08 read, so keep the canonical
list plain — no bullets, no tables, no extra decoration. Each story states its
parent Epic, priority, dependencies (story ids or none), its acceptance criteria
as verifiable Given/When/Then conditions — or an equally testable form for
criteria that are not behavioural — its definition of done, and a size note
showing it fits one implement-test-verify session. A story is single-goal,
independently buildable, testable, and verifiable, and it leaves the repository
working when it is done.

Order the work items by their numbering. Story numbering is the execution order:
the runner reads the `### S-N` list and executes strictly by numeric suffix, so
number the stories S-1..S-N in the order they will be built, with no gaps and no
reused numbers. Order by dependency first and value second: no story may depend
on a later story, and every dependency you declare must already exist or be
delivered by a lower-numbered story.

Refine the sprints. Group the ordered stories into sprints — short increments
whose end can be demonstrated. Each sprint states its goal, the stories it
contains, its entry criteria, its exit criteria, the end-to-end slice that can be
demonstrated when it closes, and the risk it retires. Sprint membership must be
contiguous and monotonic with story numbering: sprint 1 holds the lowest-numbered
stories, sprint 2 the next, and so on, because execution order is strictly
numeric. Every story belongs to exactly one sprint, and the sprints together
cover every story.

Write the result to `02-epics.md` in the goal directory: the Epic sections with
the canonical `### S-N` story headings first, then a `## Sprint Plan` section.
`02-epics.md` is the story-list source of truth for every later step; steps 07
and 08 read it and must not modify it. Do not write
`_bmad-output/sprint-status.yaml`: it is the historical planning status record
and stays read-only.

Return the complete plan as your final response with two explicit sections:
`## Story Breakdown` (the clarified scope plus the per-story list with acceptance
criteria and definition of done) and `## Sprint Plan` (each sprint's goal, story
set, entry criteria, exit criteria, and demonstrable slice). A missing section
blocks this step.

Never: implement the change; re-plan the Epics; produce a story list with gaps,
duplicate numbers, or numbering that contradicts execution order; state
acceptance criteria that cannot be verified; leave a story without a sprint, a
sprint without exit criteria, or a sprint spanning non-contiguous story numbers;
write to `_bmad-output/sprint-status.yaml`.

## Step 07: implement-story
input: clarified implementation scope, architecture
output: story implementation, story definition, story test evidence, story verification report
checkpoint: true
story_loop: 02-epics.md
validation: section: Implementation Summary; section: Test Evidence; section: Verification Verdict; the active story is implemented, tested, and verified inside this one step and the exact commands with their results are recorded

This is the heavy per-story step: one session implements the active story, owns
its tests, and verifies it against its own acceptance contract. It is the only
step allowed to create implementation artifacts or to add and change test files.
Step 08 reviews the result adversarially and, after the final story, runs the
Epic-level gate.

Implement exactly one story per increment: the active story injected by the CLI.
Do not implement other stories and do not pre-build later stories.

Stance: you are the implementer, the tester, and the first verifier of this one
story. The three phases are not optional and must not be collapsed into one
another: a phase whose evidence you did not produce yourself does not exist, and
a phase you skipped is a failure of this step, not a shortcut.

Before changing code, write the active story definition verbatim — id, title,
parent Epic, sprint, priority, dependencies, acceptance criteria, and definition
of done — to `step-07-implement-story/s-<n>/story.md`. It is the acceptance
contract that every later phase and every later step reads, so it must not drift
from `02-epics.md`.

Phase 1 — implement. Build the change against the architecture and the validated
PRD. Keep it minimal, follow existing module boundaries and conventions, and
leave the repository importing and linting cleanly. Write
`step-07-implement-story/s-<n>/implementation.md` with the changed files, the
decisions you made, and anything you could not finish.

Phase 2 — test. Map every acceptance criterion of `story.md` to at least one
executed test, plus the boundary, empty, error, retry, and permission paths the
criteria imply, and cover the definition of done. Author or extend tests under
the repository's test directory following the existing framework, naming, and
fixture conventions; do not modify product code to make a test pass. Run the
focused tests for this story, then the related regression suite, and record the
exact command line and the observed result for every run — counts, failures, and
the failing output when there is any. Never weaken, skip, or delete an existing
assertion to obtain a green run; if an existing test is itself wrong, say why and
record it. Write `step-07-implement-story/s-<n>/test-report.md` with the
criterion-to-test mapping, the commands and their results, and the residual
coverage gaps.

Phase 3 — verify. Re-read the actual diff and the test files you just wrote,
re-run the commands yourself, and judge each acceptance criterion separately as
pass, fail, or not-verifiable with concrete evidence: command output, file and
line, or observed behaviour. Also judge the definition of done, confirm the
change stayed inside the story scope, and check for regressions in behaviour the
story did not intend to change. A criterion you cannot evidence is a fail, not an
assumption. Apply the smallest fix for any Critical defect you find, re-run the
affected tests, and record it. Write `step-07-implement-story/s-<n>/verify-report.md`
with the per-criterion verdict table (criterion / verdict / evidence), the
commands you re-ran, and the residual risk.

Return the complete per-story report as your final response with three explicit
sections: `## Implementation Summary` (changed files, how to exercise the
change, residual risks), `## Test Evidence` (criterion-to-test mapping, exact
commands and their results, coverage gaps), and `## Verification Verdict`
(per-criterion verdict table and overall verdict). A missing section blocks this
step.

Never: claim a phase passed without the command that produced it; rewrite an
acceptance criterion to match what was built; report a failing test as a warning
or a skipped test as a pass; declare your own work verified without re-running
the commands; implement another story, expand the story scope, or modify
`02-epics.md`.

After the final story completes, write the top-level step document as an index
with an Epic overview and a per-story table (story / owning Epic / changed files
/ criteria passed / verdict) linking each `story.md`, `implementation.md`,
`test-report.md`, and `verify-report.md`, then update the `GOAL.md` Epics section
to match. `GOAL.md` manages Epics only; story status lives in the per-story
artifacts, and `02-epics.md` stays read-only once step 06 wrote it.

## Step 08: code-review
role: code_review
input: story verification report, story implementation, story test evidence, architecture, validated PRD
output: review report, epic integration report
checkpoint: true
story_loop: 02-epics.md
validation: section: Findings; every finding carries severity, evidence, and a resolution (fixed / accepted / deferred with reason)

Review exactly one story per increment: the active story injected by the CLI.
Do not review other stories in this increment; leave them for their own
increments.

For the active story, read its artifacts
`step-07-implement-story/s-<n>/story.md`,
`step-07-implement-story/s-<n>/implementation.md`,
`step-07-implement-story/s-<n>/test-report.md`, and
`step-07-implement-story/s-<n>/verify-report.md` before judging, and verify every
claim against the actual diff and test runs rather than those reports. Step 07
implemented, tested, and verified the story in a single session, so its own
verdicts carry no independent weight: re-run the commands yourself.

Review the change that story made through the three review lenses (adversarial,
edge case, verification gap) defined by the role contract. Note a cross-story
regression you observe, but leave it to the story that owns it unless it is
Critical. Fix Critical findings in place and re-run the affected tests; record
each Warning and Suggestion as accepted or deferred with a reason. Write the
story's review to `s-<n>/report.md` under this step's directory.

If the active story is the last story of a sprint in `02-epics.md`, also verify
that sprint before closing the story: run the sprint's demonstrable slice, check
its exit criteria, and record the result in the story's review report. A sprint
whose exit criteria fail is a Critical finding of its last story.

After the final story completes, run the Epic-level integration gate — this step
is the final acceptance step of the workflow. Group the stories of `02-epics.md`
by parent Epic, keeping the order the Epics appear, and for each Epic:

1. Check the entry evidence: `step-07-implement-story/s-<n>/story.md`,
   `s-<n>/implementation.md`, `s-<n>/test-report.md`, `s-<n>/verify-report.md`,
   and this step's `s-<n>/report.md`; and that no Critical finding is left
   unresolved. A missing artifact or an unresolved Critical finding fails that
   Epic — report it instead of continuing past it.
2. Design and run the integration scenarios that only become real when the
   Epic's stories are combined: cross-story flows, module boundaries, the real
   entry point (CLI, API, or public interface), and the data crossing them.
   Prefer executing the shipped code end to end over re-testing story internals.
3. Run the full test suite and the project quality gates (lint, format, type
   check). Record the exact commands and the observed results, including
   failures and their output.
4. On a Critical integration defect: apply the smallest fix, re-run the affected
   tests, re-run the Epic's integration scenarios, and record it as "fixed in
   step 08; integration re-run". Do not redesign the implementation.
5. Decide pass or fail for that Epic, with the evidence, the scenarios not
   covered, and the residual risk. Do not soften a failure into a warning.

Write each Epic's report to `epic-<id>/integration-report.md` under this step's
directory, then write the top-level step document as an index with a per-story
table (story / findings by severity / remediation status) and a per-Epic table
(Epic / stories / scenarios / verdict) linking each report, and update the
`GOAL.md` Epics section with the review and integration outcome. `GOAL.md`
manages Epics only, and `02-epics.md` stays read-only during the story loop.

Return the complete report as your final response with an explicit
`## Findings` section (for the active story) and, for the final story, an
explicit `## Integration Verdict` section listing every Epic with its verdict
and the commands that produced it.

Never: trust the step 07 reports without re-running the commands; fix only
Critical findings during review; declare an Epic integrated because its stories
each passed in isolation; skip an Epic, or stop after the first failing Epic,
without reporting the remaining ones; treat an untested integration path as a
pass; weaken a scenario or a gate to obtain a green verdict; modify
`02-epics.md`.
