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
modify project implementation artifacts. Step 08 is the only step that creates
implementation artifacts; step 09 may change code only to fix Critical review
findings, and must re-run the affected tests for every such fix.

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

## Step 08: implement-and-verify
role: bmad-agent-dev
input: clarified implementation scope, architecture, UX specification
output: tested code change
checkpoint: true
story_loop: 02-epics.md
validation: acceptance criteria and focused tests pass

Make the scoped change, run focused verification, and report residual risk.
This step owns implementation; step 09 may only change code to fix the Critical
findings it reports. Story-loop artifact layout: for each story, write its
definition verbatim from the story list (including parent Epic, priority, and
dependencies) to `s-<n>/story.md`, and the implementation report to
`s-<n>/report.md`. After the final story completes, write the top-level step
document as an index with an Epic overview, milestone table, and a per-story
table (title / owning Epic / status) linking each `story.md` and `report.md`;
then update `GOAL.md` Epics and Stories sections to match.

## Step 09: code-review
role: code_review
input: tested code change, clarified implementation scope, architecture, UX specification
output: review report, findings by severity, remediation status
checkpoint: true
story_loop: 02-epics.md
validation: every finding carries severity, evidence, and a resolution (fixed / accepted / deferred with reason)

Review one story at a time. For the active story, read its implementation
artifacts `step-08-implement-and-verify/s-<n>/story.md` and
`step-08-implement-and-verify/s-<n>/report.md` before judging, and verify every
claim against the actual diff and test runs rather than the implementation
report. Review the change that story made; note a cross-story regression you
observe, but leave it to the story that owns it unless it is Critical.

Fix Critical findings in place and re-run the affected tests; record each
Warning and Suggestion as accepted or deferred with a reason. Story-loop
artifact layout: write each story's review to `s-<n>/report.md` under this
step's directory. After the final story completes, write the top-level step
document as an index with a per-story table (story / findings by severity /
remediation status) linking each `s-<n>/report.md`, and update the `GOAL.md`
Stories table with the review outcome.
