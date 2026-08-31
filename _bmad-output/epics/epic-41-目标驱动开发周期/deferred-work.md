# Epic 41 Deferred Work

> Review: 2026-08-29. Items are updated against the current implementation.

## Resolved

### 41-D1 Goal session iteration budget

**Status: resolved.** `Settings.goal_max_iterations` defaults to `20`, and
`cli._goal_session()` passes it explicitly to `SubAgent`. The default remains
independent from the main AgentLoop and dreamer budgets.

### 41-D2 TUI `/goal` routing

**Status: resolved in code; tests pending.** `InputArea` now offers `/goal` for
completion and `ChatScreen` routes it to the shared CLI goal runner instead of
submitting the literal command to the LLM. A GUI interaction test should still
be added when the Textual test harness is extended.

### 41-D3 Interactive REPL slash-command exception fence

**Status: resolved.** The interactive loop catches ordinary exceptions around
slash dispatch, echoes the original error, and continues the REPL without
silently hiding failures. Cancellation is re-raised so shutdown remains clean;
the behavior is covered by `tests/test_cli.py`.

## Open Decisions

### 41-D4 `RoleSpec.metadata` lifecycle

**Status: resolved.** Role metadata is observable in the child run snapshot.
`SubAgent` merges role metadata first, then caller metadata (caller wins), and
filters framework-owned keys using the same reserved-key policy already used
for caller metadata. No role metadata is merged into policy-owned state.

Do not merge it into `RunContext.metadata` by default: policy and window-reset
keys are framework-owned and must not be user-overridable.

## Follow-up Test Work

- Add a Textual test proving `/goal next` and `/goal status` are handled by the
  goal runner and never reach `AgentBridge.submit()` as ordinary prompts.

## References

- `spec-41-1-goal-skill-single-step.md`
- `spec-41-2-run-loop-run-metadata.md`
- `src/heagent/config.py`
- `src/heagent/cli.py`
- `src/heagent/gui/screens/chat.py`
