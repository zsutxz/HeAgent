---
name: bmad-development
entrypoint: goal
on_create: persist_goal_identity
step_executor: subagent
---

# BMad development workflow

This file is the complete executable contract for the declarative `/goal`
workflow. The CLI reads this file, persists the goal identity declared by
`on_create`, and invokes one fresh SubAgent for each declared step. Completed
steps are recorded in the goal checkpoint store; no step may be skipped.

## Step 01: analyze-requirements
role: he-agent-analyst
input: user intent and existing project context
output: requirements brief and story breakdown
checkpoint: true
validation: requirements are evidence-backed and testable

Analyze the intent, distinguish facts from assumptions, identify stakeholders,
and produce a requirements brief with acceptance criteria and story-sized work.
Stop for user input when competing interpretations remain.

## Step 02: define-product-scope
role: he-agent-pm
input: requirements brief
output: validated PRD and ordered Epic proposal
checkpoint: true
validation: product value, scope, non-goals, and decisions are explicit

Turn the requirements brief into a validated PRD and ordered Epic proposal.
Record assumptions, priorities, non-goals, and unresolved product decisions.

## Step 03: design-experience
role: he-agent-ux
input: requirements brief and validated PRD
output: UX specification and user flow
checkpoint: true
validation: primary, empty, error, retry, permission, and accessibility states are specified

Define user flows, state transitions, interaction details, and accessibility
requirements that implementation can verify.

## Step 04: design-architecture
role: he-agent-architect
input: validated PRD and UX specification
output: architecture and implementation constraints
checkpoint: true
validation: boundaries, interfaces, dependencies, invariants, and failure handling are explicit

Produce the lean technical architecture and decision records. Preserve module
ownership and document security, reliability, migration, and verification paths.

## Step 05: clarify-and-route
role: he-agent-analyst
input: architecture and implementation constraints
output: clarified implementation scope
checkpoint: true
validation: intent is actionable and single-goal

Confirm the requested change, inspect relevant context, and record the
implementation scope. Do not implement the change in this step. Leave a clear
scope and acceptance direction for the next step.

## Step 06: implement-and-verify
role: he-agent-dev
input: clarified implementation scope and architecture and UX specification
output: tested code change
checkpoint: true
validation: acceptance criteria and focused tests pass

Make the scoped change, run focused verification, and report residual risk.
Only this step may modify project implementation artifacts. When its acceptance
criteria pass, the workflow is complete.
