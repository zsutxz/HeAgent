# Deferred Work — HeAgent

Findings deferred during quick-dev (out of the originating story's frozen scope, recorded for later focused attention).

## 2026-06-18 · SubAgent 共享 SkillStore 写竞态

**Source:** step-04 review of `spec-5-1-subagent-context-injection` (edge case hunter), classified `defer`.
**Trigger:** `task_parallel` runs multiple SubAgents sharing the same injected `SkillStore`. Each child loop's `_build_system()` calls `SkillStore.record_usage(skill_name)` → `save()` → `write_text()` to the same `SKILL.md`. Under `asyncio.gather`, concurrent parse→+1→save on one file → lost updates or interleaved partial writes.
**Exposed by:** spec-5-1 (sub-agents previously had no skills, so this path never ran for children).
**Severity:** real but narrow — requires ≥2 parallel sub-agents matching the SAME skill in the same tick.
**Frozen scope note:** spec-5-1 explicitly excludes solving this (`Never: 不解决并行子 Agent 共享 store 写并发竞态`). The docstring previously mislabeled injection as "只读"; corrected to flag the `record_usage` write.
**Suggested fix (future story):** wrap `SkillStore.record_usage`/`save` in an `asyncio.Lock`, OR make skill matching in child loops skip `record_usage` writes (read-only match). Same concern applies to any other store whose load path triggers writes.
