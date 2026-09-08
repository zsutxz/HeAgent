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

## Step 01: analyze-requirements
role: bmad-agent-analyst
input: user intent, existing project context
output: requirements brief, story breakdown
checkpoint: true
validation: requirements are evidence-backed and testable

Analyze the intent, distinguish facts from assumptions, identify stakeholders,
and produce a requirements brief with acceptance criteria and story-sized work.
Stop for user input when competing interpretations remain.

## Step 02: define-product-scope
role: bmad-agent-pm
input: requirements brief
output: validated PRD, ordered Epic proposal
checkpoint: true
validation: product value, scope, non-goals, and decisions are explicit

Turn the requirements brief into a validated PRD and ordered Epic proposal.
Record assumptions, priorities, non-goals, and unresolved product decisions.
Write the ordered Epic proposal to `epics.md` in the goal directory, listing each
story as a numbered heading (`### S-1 ...`, `### S-2 ...`) so the implementation
step can expand them into per-story increments.

## Step 03: design-experience
role: bmad-agent-ux-designer
input: requirements brief, validated PRD
output: UX specification, user flow
checkpoint: true
validation: primary, empty, error, retry, permission, and accessibility states are specified

Define user flows, state transitions, interaction details, and accessibility
requirements that implementation can verify.

## Step 04: design-architecture
role: bmad-agent-architect
input: validated PRD, UX specification
output: architecture, implementation constraints
checkpoint: true
validation: boundaries, interfaces, dependencies, invariants, and failure handling are explicit

Produce the lean technical architecture and decision records. Preserve module
ownership and document security, reliability, migration, and verification paths.

## Step 05: clarify-and-route
role: bmad-agent-analyst
input: architecture, implementation constraints
output: clarified implementation scope
checkpoint: true
validation: intent is actionable and single-goal

Confirm the requested change, inspect relevant context, and record the
implementation scope. Do not implement the change in this step. Leave a clear
scope and acceptance direction for the next step.

## Step 06: implement-and-verify
role: bmad-agent-dev
input: clarified implementation scope, architecture, UX specification
output: tested code change
checkpoint: true
story_loop: epics.md
validation: acceptance criteria and focused tests pass

Make the scoped change, run focused verification, and report residual risk.
Only this step may modify project implementation artifacts. When its acceptance
criteria pass, the workflow is complete.
