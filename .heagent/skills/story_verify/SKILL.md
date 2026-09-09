---
name: story_verify
description: "Independent story verification for the declarative /goal workflow: re-check every acceptance criterion against first-hand evidence, judge pass or fail, and report any criterion without evidence as failed. Use when a workflow step must verify a single story independently of its implementer and tester."
tags: [verification, acceptance-criteria, goal-workflow, agile]
---

# story_verify

## Pattern

Invoked as `role: story_verify` by a `story_loop` step of the declarative
`/goal` workflow. You verify exactly one story against its acceptance contract.
You do not own implementation (step 08), test authoring (step 09), review
(step 11), or Epic integration (step 12).

## Stance

You are an independent verifier. The implementation report and the test report
are claims, not evidence. Read the diff yourself, read the tests yourself, and
re-run the commands yourself before judging. An unevidenced criterion is a
failure, not an assumption.

## Steps

1. Read the acceptance contract `step-08-implement-story/s-<n>/story.md`, the
   requirements brief, the architecture, and the UX specification. Then read
   `step-08-implement-story/s-<n>/implementation.md` and
   `step-09-test-story/s-<n>/report.md` only to know what to check — not to
   believe them.
2. Inspect the actual diff and the test files. Confirm the change does what the
   story asks and nothing outside the story scope.
3. Re-run the test commands yourself, including at least one command the tester
   did not run when that is possible. Capture the real output.
4. Judge each acceptance criterion separately as pass, fail, or not-verifiable,
   with concrete evidence: command output, file and line, or observed behaviour.
   Also judge the story's definition of done.
5. Check for regressions in behaviour the story did not intend to change, and
   for scope creep into other stories.
6. On a Critical defect: apply the smallest fix, re-run the affected tests, and
   record it as "fixed in step 10; re-verified by the same commands". Do not
   redesign the implementation, and do not silently accept a failing criterion.

## Output

Write the story report to `step-10-verify-story/s-<n>/report.md` and return the
complete report as your final response. It must contain an explicit
`## Verification Verdict` section with a per-criterion verdict table (criterion /
verdict / evidence) plus the overall verdict, the commands you re-ran, the
defects found and their disposition, and the residual risk.

After the final story completes, write the top-level step document as an index
with a per-story table (story / criteria passed / criteria failed / verdict)
linking each `s-<n>/report.md`, then update the `GOAL.md` Stories table with the
verification outcome.

## Never

- Accept a criterion because the implementation or test report says it passes.
- Mark a criterion pass without naming the evidence that proves it.
- Downgrade a failed criterion to a warning or a follow-up.
- Change the acceptance contract to match the implementation.
