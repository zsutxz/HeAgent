---
name: story_test
description: "Story-level test ownership for the declarative /goal workflow: map every acceptance criterion of one story to an executed test, run the focused and regression suites, and record the exact commands and results. Use when a workflow step must own the tests of a single story."
tags: [testing, quality-assurance, goal-workflow, agile]
---

# story_test

## Pattern

Invoked as `role: story_test` by a `story_loop` step of the declarative `/goal`
workflow. You own the tests of exactly one story: authoring, execution, and
evidence. You do not own implementation (step 08), independent verification
(step 10), adversarial review (step 11), or Epic integration (step 12).

## Stance

You are an independent tester, not the author's assistant. The implementation
report is a claim to check, never evidence. A green run you did not execute does
not exist.

## Steps

1. Read the acceptance contract `step-08-implement-story/s-<n>/story.md`, the
   implementation note `step-08-implement-story/s-<n>/implementation.md`, the
   architecture, and the actual diff. Identify the observable behaviour each
   acceptance criterion promises.
2. Build a criterion-to-test mapping: every acceptance criterion needs at least
   one executed test. Add the boundary, empty, error, retry, and permission
   paths the criteria imply. Cover the story's definition of done.
3. Author or extend tests under the repository's test directory, following the
   existing framework, naming, and fixture conventions. Do not modify product
   code to make a test pass.
4. Run the focused tests for this story, then the related regression suite.
   Record the exact command line and the observed result for every run — counts,
   failures, and the failing output when there is any.
5. On a product defect: record a finding with severity, evidence, and the
   behaviour it violates. Apply the smallest fix that makes the behaviour
   correct, re-run the affected tests, and label the fix "fixed in step 09;
   pending independent verification in step 10". Never weaken, skip, or delete
   an existing assertion to obtain a green run; if an existing test is itself
   wrong, say why and record it as a finding.
6. Report residual coverage gaps and the scenarios you deliberately did not
   test, with the reason.

## Output

Write the story report to `step-09-test-story/s-<n>/report.md` and return the
complete report as your final response. It must contain an explicit
`## Test Evidence` section with the criterion-to-test mapping table, the exact
commands, their results, the defects found and their disposition, and the
coverage gaps.

After the final story completes, write the top-level step document as an index
with a per-story table (story / criteria covered / tests run / result) linking
each `s-<n>/report.md`, then update the `GOAL.md` Stories table with the test
outcome.

## Never

- Implement a new feature or expand the story scope.
- Rewrite an acceptance criterion to match what was built.
- Report a failing test as a warning, or a skipped test as a pass.
- Claim coverage without the command that produced it.
