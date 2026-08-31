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

## Deferred Follow-ups

- source_spec: `_bmad-output/epics/epic-41-目标驱动开发周期/spec-41-1-goal-skill-single-step.md`
  summary: 为 GUI `/goal` 定义输出转发、取消控制和 cron scheduler 生命周期，并添加端到端交互测试。
  evidence: GUI 直接调用 CLI runner，`click.echo` 的进度和失败信息不进入 RichLog，且 GUI 仅持有 JobStore、没有运行 CronScheduler；现有测试只覆盖 CLI registry。
- source_spec: `epic-41/spec-41-1-goal-skill-single-step.md`
  summary: Add an inter-process lock around goal pointer reads, sessions, and GOAL.md writes.
  evidence: The current asyncio lock only serializes tasks within one process; a second CLI process can execute the same story concurrently and lose progress.
- source_spec: `epic-41/spec-41-1-goal-skill-single-step.md`
  summary: Route CLI goal runner output into the Textual RichLog instead of process stdout/stderr.
  evidence: GUI goal commands currently invoke the shared runner, whose click.echo output is not captured by the chat log.

## References

- `spec-41-1-goal-skill-single-step.md`
- `spec-41-2-run-loop-run-metadata.md`
- `src/heagent/config.py`
- `src/heagent/cli.py`
- `src/heagent/gui/screens/chat.py`
