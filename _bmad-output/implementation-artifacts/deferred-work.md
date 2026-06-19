# Deferred Work — HeAgent

Findings deferred during quick-dev (out of the originating story's frozen scope, recorded for later focused attention).

## 2026-06-18 · SubAgent 共享 SkillStore 写竞态

**Source:** step-04 review of `spec-5-1-subagent-context-injection` (edge case hunter), classified `defer`.
**Trigger:** `task_parallel` runs multiple SubAgents sharing the same injected `SkillStore`. Each child loop's `_build_system()` calls `SkillStore.record_usage(skill_name)` → `save()` → `write_text()` to the same `SKILL.md`. Under `asyncio.gather`, concurrent parse→+1→save on one file → lost updates or interleaved partial writes.
**Exposed by:** spec-5-1 (sub-agents previously had no skills, so this path never ran for children).
**Severity:** real but narrow — requires ≥2 parallel sub-agents matching the SAME skill in the same tick.
**Frozen scope note:** spec-5-1 explicitly excludes solving this (`Never: 不解决并行子 Agent 共享 store 写并发竞态`). The docstring previously mislabeled injection as "只读"; corrected to flag the `record_usage` write.
**Suggested fix (future story):** wrap `SkillStore.record_usage`/`save` in an `asyncio.Lock`, OR make skill matching in child loops skip `record_usage` writes (read-only match). Same concern applies to any other store whose load path triggers writes.

## 2026-06-19 · ProviderChain 对已包装 ProviderError 双层重包

**Source:** step-04 review of `spec-p0-provider-hardening`（blind hunter + edge case hunter），classified `defer`。
**Trigger:** P0-2 让 provider 源头把 SDK 异常包装为 `ProviderError` 后，`ProviderChain.send/stream` 的 `except Exception` 仍对内层抛出的 `ProviderError` 再调 `_wrap_error(e) from e`，形成 `ProviderError → __cause__ → ProviderError → __cause__ → 原始 SDK 异常` 的双层包装。分类 / status_code 仍正确（duck-type 透过提取），仅 traceback 多一层、组合层 `__cause__` 不再是原始 SDK 异常。
**Exposed by:** spec-p0-2（此前内层抛原始 SDK 异常，chain 只包一次；现内层已是 ProviderError）。
**Severity:** LOW — 纯展示层，不影响回退 / 重试 / 分类决策。
**Frozen scope note:** spec-p0-2 边界聚焦「provider 源头包装」，未覆盖 chain 重包优化（属 P2 架构演进）。
**Suggested fix (future story):** `chain._wrap_error`（或各 `except` 点）加守卫 `if isinstance(e, ProviderError): raise`，避免对已是 HeAgent 体系的异常二次包装。
