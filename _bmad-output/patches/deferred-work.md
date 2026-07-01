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

## 2026-07-01 · FR-3 MCP auto-unregister code review — deferred

**Source:** step-04 review of `fr3-mcp-auto-unregister`（blind hunter + edge case hunter + acceptance auditor），6 项 classified `defer`。AC/约束全通过，1 项 patch（interval 校验）另记 spec。下列为 pre-existing / spec 显式排除 / 非阻塞项。

- **`__aexit__` 的 `gather(*tasks)` 无超时 [`manager.py:85-93,144-149`] — pre-existing。** `__aexit__` set stop 后 `await asyncio.gather(*tasks, return_exceptions=True)`，每 task finally `await cm.__aexit__`（transport 清理）；stdio 子进程忽略 SIGTERM / HTTP 远端不 FIN 时可挂死，进程退出无上界。该 `cm.__aexit__` 无超时在本次改动前就存在，非 FR-3 引入。**Severity:** LOW–MED（关停挂死，需 OS SIGKILL）。**Suggested fix:** 每 task 包 `asyncio.wait_for(..., timeout=N)`，或文档显式声明 `__aexit__` 可阻塞。
- **`_watch` 两个 `wait_for` 的 `TimeoutError` 同名异义 [`manager.py:235-245`]。** 第一个 `wait_for(stop.wait())` 超时 = "该 ping 了"；第二个 `wait_for(send_ping())` 超时 = "断连"。两者皆 `TimeoutError`，仅靠 try 块物理位置 + 内联注释区分。**Severity:** LOW（已有内联注释缓解，未来合并 try 块的重构会碎）。**Suggested fix:** 保持现状；若重构，用独立变量或显式分支消歧。
- **`_watch` `except Exception` 过宽 [`manager.py:242`]。** 任意 `send_ping` 异常（含 SDK 一次性内部错误）一律永久当断连 + 注销。spec Always 显式接受「ping 失败/超时即断连」的保守 fail-safe（无重连场景下，移除可疑工具比保留更安全）。**Severity:** LOW。**Suggested fix (future):** 若加 MCP 重连，收窄到连接类异常（`ConnectionError`/`httpx.*`/`asyncio.TimeoutError`），把编程错误另走诊断路径。
- **handler 未把 in-flight `call_tool` 底层异常封 `ToolError` [`manager.py:205-207`] — pre-existing。** 运行时断连期间已在 in-flight 的 `await session.call_tool(...)` 可能在被 finally 关闭的 session 上抛非 `ToolError` 的底层异常（`anyio.BrokenResourceError` 等），冒泡到 `AgentLoop._execute_one`。FR-3 声明「调用降级 `ToolError`」但 handler 边界未兜底。spec Never 显式排除反应式 on-call 封装（本次不融合第二模式）。**Severity:** LOW–MED。**Suggested fix (future story):** handler 内 `try: call_tool except Exception: raise ToolError(...)`，把所有调用路径异常统一为 `ToolError` 语义。
- **`_unregister_all` 迭代 `.values()` 后 `.clear()` [`manager.py:216-221`]。** 当前单线程 asyncio 下 `_unregister_all` 同步无 await、原子完成，与 `_unregister_server` 的 `pop` 无交错风险。**Severity:** LOW（仅未来若在 `_unregister_all` 中插 await 会破不变量）。**Suggested fix:** 先 `registered = self._registered; self._registered = {}` 快照再遍历，防御性。
- **测试未断言断连 server task done / transport 关闭 / 内置工具保留 [`tests/test_mcp_manager.py:252-273`]。** `test_disconnect_isolated_to_one_server` 仅轮询工具从 registry 消失，未断言：(a) 断连 server 的 `_server_loop` task 已 done；(b) transport context 已 `__aexit__`；(c) 内置工具保留（该测试用空 `ToolRegistry()`，无内置工具可断言）。AC1 的「内置工具保留」由 `_unregister_server` 只 `pop` 单 key 的实现逻辑等价保证。**Severity:** LOW（测试保真度，非生产 bug）。**Suggested fix:** 补 `assert all(t.done() for t in m._server_tasks)` 或断言 fake transport 的 `__aexit__` 被调用。
