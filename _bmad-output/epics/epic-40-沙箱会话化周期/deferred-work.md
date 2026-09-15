# Epic 40 Deferred Work

> Last reviewed: 2026-09-15 (E40-D1..D4 全部关闭)
>
> Scope: follow-up work owned by Epic 40. These items are lifecycle, usability,
> or test-coverage work; sandbox backends still require OS-level containment.

## Status Summary

| ID | Area | Status | Next decision |
|---|---|---|---|
| E40-D1 | Crash orphan directory GC and retention | Closed (2026-09-15) | — |
| E40-D2 | Session workspace visibility to the LLM | Closed (2026-09-15) | — |
| E40-D3 | WinJob cwd coverage on CI | Closed (2026-09-15) | — |
| E40-D4 | `SANDBOX_SESSION_WORKSPACE` CLI parity | Closed (2026-09-15) | — |
| E40-C1 | `--private` semantics documentation | Closed | Corrected in `docs/frame.md` and `AGENTS.md` |

## Closed (2026-09-15)

### E40-D1: Crash Orphan Directory GC and Retention

- Delivered: `housekeeping.prune_sandbox_dirs(workspace, retention_days)` +
  `Settings.sandbox_dir_retention_days` (`SANDBOX_DIR_RETENTION_DAYS`, default `7`, `0` disables),
  wired into `run_housekeeping` as a fourth target (`sandboxes`) so both CLI and GUI startup paths
  reclaim on launch.
- Selection: age by the newest mtime of **the directory and its direct children** (one bounded
  level), so a run that is still writing files is never reclaimed; a directory idle past the
  retention window is by definition not active. Non-directory entries are left untouched, symlinks
  are never traversed (warning logged). Deletions are capped per pass (`_SANDBOX_PRUNE_MAX_PER_PASS`)
  with a warning when the cap is hit, and per-directory failures log a warning and are retried on a
  later startup.
- Root convention now has a single expression (`tools.sandbox.sandbox_sessions_root`) shared by the
  creator (`EngineContainer.create_run_context`) and the reclaimer, so the two cannot drift.
- Tests: `tests/test_housekeeping.py` (stale deleted / active kept / fresh kept, disabled at `0`,
  malformed file untouched, symlink never followed, per-pass cap, failure tolerated + warning,
  throttle, symlink branch on platforms that cannot create links) and
  `tests/test_sandbox.py::TestSandboxSessionDir::test_default_root_matches_convention_root`.
- Boundary unchanged: this is disk hygiene, not an OS security boundary.

### E40-D2: Make the Session Workspace Observable to the LLM

- Delivered: single authoritative exposure path = system prompt. `build_system_prompt(...,
  sandbox_workspace=...)` appends a `<shell-workspace>` block (step 4 of the documented injection
  order) stating the absolute directory, that the shell keeps its working directory across commands,
  and that file tools resolve relative paths against the workspace root instead (use an absolute path
  when both must touch the same file).
- Honesty gate: the block is injected **only when the directory is actually in effect** —
  `AgentLoop._bound_sandbox_workspace` requires a real backend (`executor.sandbox_runner is not None`)
  in addition to `metadata["sandbox_workspace"]`. With the switch on but no backend (passthrough) no
  path is reported, because a prompt that disagrees with the real cwd is worse than no prompt.
- Tests: `tests/test_agent_loop.py::TestSandboxWorkspaceVisibility` — block present with the path,
  absent for `None`/`""`, absent when the backend is missing, and an end-to-end run proving the path
  reported to the model equals the workspace the shell tool actually receives (`get_sandbox_workspace()`
  inside a recording runner).

### E40-D3: WinJob cwd Coverage on CI

- Delivered: child-process startup collapsed into the module-level `_winjob_spawn(command, workspace)`
  seam (no Windows kernel APIs), which is now the **only** place that decides whether `cwd` is passed
  (`workspace is None` → no `cwd`, byte-identical to the previous behaviour). `WinJobBackend.run`
  calls it via `asyncio.to_thread`.
- Tests: `tests/test_winjob_backend.py::TestWinJobSpawnSeam` runs on every platform by replacing
  `subprocess.Popen` and asserting `cwd` presence/absence plus argv — previously this decision lived in
  two `Popen` branches whose tests skipped off Windows. The Windows-only
  `TestWinJobSessionWorkspace` integration assertions remain (now driving the seam).

### E40-D4: CLI Parity for Session Workspace Configuration

- Delivered: `--sandbox-session-workspace/--no-sandbox-session-workspace` and
  `--sandbox-session-keep/--no-sandbox-session-keep` on both `heagent run` and `heagent gui`.
  Tri-state (`None` = follow `Settings`, explicit `True/False` = override), so `--no-...` can turn the
  switch off even when the env var enables it; `EngineContainer.default(...)` forwards the values and
  the container resolves precedence once (`_session_workspace_enabled` / `_session_keep_enabled`).
- Defaults unchanged: with no flag, behaviour is byte-identical to before (env only).
- Tests: `tests/test_cli.py` (options reach `_run_cli_impl` tri-state; help lists them),
  `tests/test_engine_p0.py::TestSandboxSessionSwitchPrecedence` (explicit `True`/`False` override env
  both ways, `None` follows env, keep parity, `default()` forwarding).

## Closed (earlier review)

### E40-C1: `--private` Semantics Documentation

The earlier review item described Firejail `--private` as if it were a complete filesystem replacement. The implementation and current documentation now state the actual semantics: Firejail uses `--private=<workspace_root>` as defense in depth, while WinJob only receives a child-process cwd. The limitation is documented in `docs/frame.md` and `AGENTS.md`; no further Epic 40 implementation is required for this item.
