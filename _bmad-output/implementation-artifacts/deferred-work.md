# Deferred Work — HeAgent

Findings deferred during quick-dev (out of the originating story's frozen scope, recorded for later focused attention).

## 2026-06-18 · SubAgent 共享 SkillStore 写竞态

**Source:** step-04 review of `spec-5-1-subagent-context-injection` (edge case hunter), classified `defer`.
**Trigger:** `task_parallel` runs multiple SubAgents sharing the same injected `SkillStore`. Each child loop's `_build_system()` calls `SkillStore.record_usage(skill_name)` → `save()` → `write_text()` to the same `SKILL.md`. Under `asyncio.gather`, concurrent parse→+1→save on one file → lost updates or interleaved partial writes.
**Exposed by:** spec-5-1 (sub-agents previously had no skills, so this path never ran for children).
**Severity:** real but narrow — requires ≥2 parallel sub-agents matching the SAME skill in the same tick.
**Frozen scope note:** spec-5-1 explicitly excludes solving this (`Never: 不解决并行子 Agent 共享 store 写并发竞态`). The docstring previously mislabeled injection as "只读"; corrected to flag the `record_usage` write.
**Suggested fix (future story):** wrap `SkillStore.record_usage`/`save` in an `asyncio.Lock`, OR make skill matching in child loops skip `record_usage` writes (read-only match). Same concern applies to any other store whose load path triggers writes.

**Resolution (2026-06-19, P0 技术债收尾):** 经核实，此竞态在当前实现下**不成立**，此项关闭。`SkillStore.record_usage`/`save` 是无 `await` 的同步方法（`write_text` 同步 I/O），`_build_system`（`loop.py:338`）整段同步——单线程 asyncio 下两个 SubAgent 的 `record_usage` 调用必然串行执行（A 完整写完后才轮到 B），不存在丢失更新/交错写入。原 review 把「多协程访问共享对象」误判为竞态，忽略了 record_usage 是无 await 的原子同步段。**未引入 asyncio.Lock**——`asyncio.Lock.acquire` 是 awaitable，同步方法内无法使用；`threading.Lock` 在单线程无意义。已加回归测试 `tests/test_sub_agent.py::TestParallel::test_parallel_shared_skillstore_no_lost_usage_update` 锁定「并发不丢更新」不变量：若未来 SkillStore 方法 async 化（CLAUDE.md 规定库代码无同步 I/O，届时 `read_text`/`write_text` 须 async 化）引入真正 await 交错，该测试将变红提醒重新评估并发安全。

## 2026-06-19 · ProviderChain 对已包装 ProviderError 双层重包

**Source:** step-04 review of `spec-p0-provider-hardening`（blind hunter + edge case hunter），classified `defer`。
**Trigger:** P0-2 让 provider 源头把 SDK 异常包装为 `ProviderError` 后，`ProviderChain.send/stream` 的 `except Exception` 仍对内层抛出的 `ProviderError` 再调 `_wrap_error(e) from e`，形成 `ProviderError → __cause__ → ProviderError → __cause__ → 原始 SDK 异常` 的双层包装。分类 / status_code 仍正确（duck-type 透过提取），仅 traceback 多一层、组合层 `__cause__` 不再是原始 SDK 异常。
**Exposed by:** spec-p0-2（此前内层抛原始 SDK 异常，chain 只包一次；现内层已是 ProviderError）。
**Severity:** LOW — 纯展示层，不影响回退 / 重试 / 分类决策。
**Frozen scope note:** spec-p0-2 边界聚焦「provider 源头包装」，未覆盖 chain 重包优化（属 P2 架构演进）。
**Suggested fix (future story):** `chain._wrap_error`（或各 `except` 点）加守卫 `if isinstance(e, ProviderError): raise`，避免对已是 HeAgent 体系的异常二次包装。

**Resolution (2026-06-19, P0 技术债收尾):** 已修复。`chain.py` 以 `_raise_provider_error(error) -> NoReturn` 取代 `_wrap_error`：已是 `ProviderError` 则原样 `raise`（保留既有 cause 链），否则 `raise wrap_provider_error(error) from error`。4 个调用点（send NON_TRANSIENT、send all-fail、stream delivered、stream NON_TRANSIENT）统一替换；send 的死代码 backstop 也由裸 `RuntimeError` 改为 `ProviderError` 以遵守「禁止裸 Exception」契约。回归测试 `tests/providers/test_chain.py::test_send_no_double_wrap_on_inner_provider_error` 与 `test_stream_no_double_wrap_on_inner_provider_error` 断言抛出异常的 `__cause__` 不再是另一个 `ProviderError`。此项关闭。

## 2026-06-19 · ProviderChain 流式 backstop 丢失最后错误上下文

**Source:** step-04 code review of「P0 技术债收尾」（ecc:python-reviewer），classified `defer`。
**Trigger:** `ProviderChain.stream` 末尾的兜底 `raise ProviderError("All providers failed for stream")`（chain.py:143）不跟踪 `last_error`——流式路径在可回退错误时仅 `break`，未累积最后一次异常。结果：所有 provider 流式均失败时抛出的 ProviderError 无 `status_code`、无 `__cause__`，上层 `classify_exception`/`status_code` 读取得到通用值。`send()` 版 backstop 已正确委托 `_raise_provider_error(last_error)`，流式版本未对称实现。
**Exposed by:** 双层重包修复评审中发现（同一 backstop 区域）。
**Severity:** LOW — 仅影响「所有 provider 流式全失败」这一罕见路径的错误信息精度，不影响回退/重试/正常流式。
**Frozen scope note:** 本次「P0 技术债收尾」范围聚焦双层重包与测试耦合，未覆盖流式 backstop 的 last_error 跟踪（涉及 stream 循环行为改动 + 需回归测试）。
**Suggested fix (future story):** 在 `stream` 循环中跟踪 `last_error`（仿 `send`），末尾 `if last_error is not None: _raise_provider_error(last_error)`，使流式 backstop 与 send 对称、保留状态码与 cause。

**Resolution (2026-06-20):** 已修复。`stream` 循环现跟踪 `last_error`，末尾 `if last_error is not None: _raise_provider_error(last_error)`，与 `send` 对称，保留状态码与 cause。回归测试 `tests/providers/test_chain.py::test_stream_all_fail_preserves_last_error_status` 断言全失败时末次错误的 status_code 保留。此项关闭。
