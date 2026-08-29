# Epic 40 Deferred Work

> Last reviewed: 2026-08-29
>
> Scope: follow-up work owned by Epic 40. These items are lifecycle, usability,
> or test-coverage work; sandbox backends still require OS-level containment.

## Status Summary

| ID | Area | Status | Next decision |
|---|---|---|---|
| E40-D1 | Crash orphan directory GC and retention | Open | Define retention policy and bounded cleanup |
| E40-D2 | Session workspace visibility to the LLM | Open | Choose prompt/tool exposure and test the contract |
| E40-D3 | WinJob cwd coverage on CI | Open | Add a portable test seam or Windows CI lane |
| E40-D4 | `SANDBOX_SESSION_WORKSPACE` CLI parity | Open | Decide whether an explicit CLI flag is required |
| E40-C1 | `--private` semantics documentation | Closed | Corrected in `docs/frame.md` and `AGENTS.md` |

## Open Items

### E40-D1: Crash Orphan Directory GC and Retention

- Source: `stories/40-1-session-workspace-directory.md` and `stories/40-4-sandbox-session-lifecycle.md`.
- Evidence: each run can create `.heagent/sandboxes/<run_id>/`; normal teardown is covered, but a process crash leaves the directory behind. No sandbox-directory retention policy corresponds to `ledger_retention_days`.
- Required outcome: define age/size selection, avoid deleting active runs, make cleanup bounded and observable, and test stale, active, malformed, and cleanup-failure cases.
- Boundary: this is lifecycle and disk-usage hygiene, not an OS security boundary.

### E40-D2: Make the Session Workspace Observable to the LLM

- Source: `stories/40-1-session-workspace-directory.md`.
- Evidence: shell/file paths can resolve under the per-run workspace, but the current goal/system prompt contract does not consistently tell the LLM where that workspace is. Shell writes can therefore diverge from file-tool assumptions.
- Required outcome: choose one authoritative exposure path (system prompt or tool schema/result), keep shell and file tools aligned, and add an end-to-end test proving the model-visible path is actually used.
- Boundary: do not expose credentials or treat metadata text as isolation.

### E40-D3: WinJob cwd Coverage on CI

- Source: `stories/40-1-session-workspace-directory.md`.
- Evidence: `WinJobBackend` passes the session directory as child-process cwd, but the relevant tests are Windows-only and skipped on Linux CI.
- Required outcome: introduce a test seam that asserts the `cwd` argument without Windows kernel APIs, or add a Windows CI lane for the existing integration assertions.
- Boundary: WinJob cwd is a directory convention only; it provides no filesystem or network isolation.

### E40-D4: CLI Parity for Session Workspace Configuration

- Source: `stories/40-1-session-workspace-directory.md`.
- Evidence: `SANDBOX_SESSION_WORKSPACE` is available through settings/env, while sibling `SANDBOX_BACKEND` has a `--sandbox` CLI entry point. Users cannot discover or override this switch from the CLI.
- Required outcome: decide whether to add a dedicated flag with help and precedence tests, or explicitly document env-only configuration as supported.
- Boundary: keep the default `False` and preserve existing argv/cwd behavior when disabled.

## Closed

### E40-C1: `--private` Semantics Documentation

The earlier review item described Firejail `--private` as if it were a complete filesystem replacement. The implementation and current documentation now state the actual semantics: Firejail uses `--private=<workspace_root>` as defense in depth, while WinJob only receives a child-process cwd. The limitation is documented in `docs/frame.md` and `AGENTS.md`; no further Epic 40 implementation is required for this item.
