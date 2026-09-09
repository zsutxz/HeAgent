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
requirements, PRDs, UX specifications, architecture records, reviews, and
verification reports, must be written under the project output root
`_he-output/`. Source code remains in its established repository location.

Step 01 is read-only research and step 02 is read-only ideation: neither may
modify project implementation artifacts. Steps 08 to 11 run once per story in
that order and own disjoint work: step 08 implements, step 09 owns the tests,
step 10 verifies independently, and step 11 reviews adversarially. Step 08 is
the only step allowed to create implementation artifacts; step 09 is the only
step allowed to add or change test files, except for a minimal defect fix it
must record as a finding; steps 10 and 11 may change code only to fix the
Critical findings they report. Step 12 is the Epic-level integration gate and
the final acceptance step. Every step that changes code must re-run the affected
tests and state the exact commands and results.

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
Write the ordered Epic proposal to `02-epics.md` in the goal directory, listing each
story as a numbered heading (`### S-1 ...`, `### S-2 ...`) so the implementation
step can expand them into per-story increments.

## Step 05: design-experience
role: bmad-agent-ux-designer
input: requirements brief, validated PRD
output: UX specification, user flow
checkpoint: true
validation: primary, empty, error, retry, permission, and accessibility states are specified

Define user flows, state transitions, interaction details, and accessibility
requirements that implementation can verify.

## Step 06: design-architecture
role: bmad-agent-architect
input: validated PRD, UX specification
output: architecture, implementation constraints
checkpoint: true
validation: boundaries, interfaces, dependencies, invariants, and failure handling are explicit

Produce the lean technical architecture and decision records. Preserve module
ownership and document security, reliability, migration, and verification paths.

## Step 07: clarify-and-route
role: bmad-agent-analyst
input: architecture, implementation constraints
output: clarified implementation scope
checkpoint: true
validation: intent is actionable and single-goal

Confirm the requested change, inspect relevant context, and record the
implementation scope. Do not implement the change in this step. Leave a clear
scope and acceptance direction for the next step.

## Step 08: implement-story
role: bmad-agent-dev
input: clarified implementation scope, architecture, UX specification
output: story implementation, story definition
checkpoint: true
story_loop: 02-epics.md
validation: section: Implementation Summary; the scoped change is implemented and the touched scope passes lint and type checks

Implement exactly one story per increment: the active story injected by the CLI.
Do not implement other stories, do not pre-build later stories, and do not write
or modify test files; test authoring belongs to step 09.

Before changing code, write the active story definition verbatim — id, title,
parent Epic, priority, dependencies, acceptance criteria, and definition of done
— to `step-08-implement-story/s-<n>/story.md`. The test and verification steps
read that file as the acceptance contract, so it must not drift from
`02-epics.md`.

Then implement the change against the architecture and the UX specification.
Keep it minimal, follow existing module boundaries and conventions, and leave
the repository importing and linting cleanly.

Write `step-08-implement-story/s-<n>/implementation.md` with the changed files,
the decisions you made, and anything you could not finish. Do not claim that
acceptance criteria pass and do not claim test evidence; testing and
verification are separate steps and must not depend on your report.

Return the complete implementation summary as your final response, with an
explicit `## Implementation Summary` section listing the changed files, how to
exercise the change, and the residual risks. After the final story completes,
write the top-level step document as an index with an Epic overview and a
per-story table (story / owning Epic / changed files / status) linking each
`story.md` and `implementation.md`, then update `GOAL.md` Epics and Stories
sections to match.

## Step 09: test-story
role: story_test
input: story implementation, story definition, architecture
output: story test evidence
checkpoint: true
story_loop: 02-epics.md
validation: section: Test Evidence; every acceptance criterion of the active story maps to at least one executed test and the exact commands with their results are recorded

Own the tests for the active story. Read
`step-08-implement-story/s-<n>/story.md` (the acceptance contract),
`step-08-implement-story/s-<n>/implementation.md`, and the actual diff; treat the
implementation report as a claim to check, never as evidence.

Design tests that cover every acceptance criterion plus the boundary, error, and
retry paths those criteria imply. Add or extend test files under the
repository's test directory; do not modify product code to make a test pass. Run
the focused tests for this story, then the related regression suite, and record
the exact command line and the observed result for each run.

If a test exposes a product defect, record it as a finding with a severity, then
apply the smallest fix that makes the behaviour correct, re-run the affected
tests, and label the fix explicitly as "fixed in step 09; pending independent
verification in step 10". Never weaken or delete an existing assertion to obtain
a green run; if an existing test is itself wrong, say why and record it.

Write `step-09-test-story/s-<n>/report.md` with the criterion-to-test mapping,
the commands and their results, the defects found and their disposition, and the
residual coverage gaps. Return the complete report as your final response with
an explicit `## Test Evidence` section. After the final story completes, write
the top-level step document as an index with a per-story table (story / criteria
covered / tests run / result) linking each `s-<n>/report.md`, then update the
`GOAL.md` Stories table with the test outcome.

## Step 10: verify-story
role: story_verify
input: story test evidence, story implementation, story definition, requirements brief
output: story verification report
checkpoint: true
story_loop: 02-epics.md
validation: section: Verification Verdict; every acceptance criterion is independently re-checked against evidence and any criterion without evidence is reported as failed

Verify the active story as an independent verifier. Do not trust the
implementation report or the test report: read the actual diff, read the test
files, and re-run the commands yourself before judging.

Judge each acceptance criterion of `step-08-implement-story/s-<n>/story.md`
separately and record pass, fail, or not-verifiable with concrete evidence
(command output, file and line, observed behaviour). Check the definition of
done, check that the change stayed inside the story scope, and check for
regressions in behaviour the story did not intend to change.

A criterion you cannot evidence is a fail, not an assumption. When you find a
Critical defect, apply the smallest fix, re-run the affected tests, and record
the fix as "fixed in step 10; re-verified by the same commands". Do not redesign
the implementation.

Write `step-10-verify-story/s-<n>/report.md` with the per-criterion verdict table
and its evidence. Return the complete report as your final response with an
explicit `## Verification Verdict` section. After the final story completes,
write the top-level step document as an index with a per-story table (story /
criteria passed / criteria failed / verdict) linking each `s-<n>/report.md`, and
update the `GOAL.md` Stories table with the verification outcome.

## Step 11: code-review
role: code_review
input: story verification report, story implementation, architecture, UX specification
output: review report, remediation status
checkpoint: true
story_loop: 02-epics.md
validation: section: Findings; every finding carries severity, evidence, and a resolution (fixed / accepted / deferred with reason)

Review one story at a time through the three review lenses (adversarial, edge case, verification gap) defined by the role contract. For the active story, read its implementation
artifacts `step-08-implement-story/s-<n>/story.md` and
`step-08-implement-story/s-<n>/implementation.md`, its test report
`step-09-test-story/s-<n>/report.md`, and its verification report
`step-10-verify-story/s-<n>/report.md` before judging, and verify every claim
against the actual diff and test runs rather than those reports. Review the
change that story made; note a cross-story regression you observe, but leave it
to the story that owns it unless it is Critical.

Fix Critical findings in place and re-run the affected tests; record each
Warning and Suggestion as accepted or deferred with a reason. Story-loop artifact
layout: write each story's review to `s-<n>/report.md` under this step's
directory. After the final story completes, write the top-level step document as
an index with a per-story table (story / findings by severity / remediation
status) linking each `s-<n>/report.md`, and update the `GOAL.md` Stories table
with the review outcome.

## Step 12: epic-integration-test
role: epic_integration_test
input: review report, story test evidence, story verification report, validated PRD
output: epic integration report
checkpoint: true
validation: section: Integration Verdict; every Epic in the story list has an integration report recording the executed commands, their results, and an explicit pass or fail verdict

Run the Epic-level integration gate. This step is the final acceptance step of
the workflow: it decides whether each Epic is demonstrably integrated, not just
whether its stories were implemented one by one.

Group the stories of `02-epics.md` — together with their
`step-08-implement-story/s-<n>/story.md` definitions — by parent Epic. For each
Epic, in the order the Epics appear:

1. Confirm every story of that Epic has all of its artifacts:
   `step-08-implement-story/s-<n>/story.md` and `s-<n>/implementation.md`,
   `step-09-test-story/s-<n>/report.md`, `step-10-verify-story/s-<n>/report.md`,
   and `step-11-code-review/s-<n>/report.md`; and that no Critical finding is
   left unresolved. A missing artifact or an unresolved Critical finding fails
   that Epic — report it instead of continuing past it.
2. Design the integration scenarios that only become real when the Epic's
   stories are combined: cross-story flows, module boundaries, the real entry
   point (CLI, API, or public interface), and the data crossing them. Prefer
   executing the shipped code end to end over re-testing story internals.
3. Run the integration scenarios, the full test suite, and the project quality
   gates (lint, format, type check). Record the exact commands and the observed
   results, including failures and their output.
4. Decide pass or fail for that Epic, with the evidence, the scenarios not
   covered, and the residual risk. Do not soften a failure into a warning.

Write each Epic's report to
`step-12-epic-integration-test/epic-<id>/integration-report.md`. Return the
complete integration report as your final response with an explicit
`## Integration Verdict` section listing every Epic with its verdict and the
commands that produced it. Finally, write the top-level step document as an
index with a per-Epic table (Epic / stories / scenarios / verdict) linking each
`integration-report.md`, and update the `GOAL.md` Epics table with the
integration outcome.
