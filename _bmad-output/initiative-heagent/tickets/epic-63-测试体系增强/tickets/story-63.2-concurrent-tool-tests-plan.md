---
title: 'Story 63.2 增加并发工具调用极限测试'
type: test
ticket: 2
created: '2026-11-18'
status: built
baseline_revision: '249873d'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
context:
  - 'src/heagent/agent/tool_execution.py'
  - 'src/heagent/engine/executor.py'
  - 'src/heagent/engine/ledger.py'
  - 'tests/test_sandbox_mode.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 票面要求「10+ 并发工具调用极限场景测试就位」。`execute_tools` 的批次
并发语义（`asyncio.gather(return_exceptions=True)`、结果按调用顺序、批内隔离、
ledger 互斥、取消清理）此前无直接并发规模测试——test_window_reset 只有一条
in-flight 跳过断言，executor 层测试（test_sandbox_mode 等）均为单调用。

**Verify 拆解：**
- 覆盖并发安全性 → 并发性证明（barrier 会师）、批内隔离（handler/闸门异常不取消
  同批）、同 key 重复调用去重、共享 ledger 存储并发落账；
- 覆盖资源竞争 → 同 key TOCTOU 互斥（12 调用含重复 id 对）、12 个不同 key 并发抢占
  共享 ledger 后全部 COMPLETED；
- 无死锁 → barrier 等待带超时（串行退化 = 首个调用 2s 超时显性红，不挂死）；
  取消路径外部 `task.cancel()` 可达终态。

## Survey（baseline 249873d）

- 批次入口：`agent/tool_execution.py::execute_tools`——`gather(return_exceptions=True)`
  并发执行，结果**按调用顺序**返回；单调用异常转 error ToolResult 不取消同批；
  批前后 `tool_batch_started/completed` 事件（details: count/errors）；
  在途 `loop.active_tool` 聚合标签（finally 清空，取消同样清理）、
  `loop.tool_activity` 执行前登记全部标签。
- 单调用链：`_claim_ledger`（ledger acquire 幂等闸门 + 后台续租任务，所有权交
  `execute_tool_call` 的 finally 取消）→ policy 裁决 → 真执行
  `loop.engine.executor.execute`（`engine/executor.py::ToolExecutor._execute_direct`：
  guard.check → handler，handler 任意异常转 error 结果）→ ledger 回写。
- ledger 并发互斥：`ExecutionLedger._lock`（进程内 asyncio.Lock）串行化
  acquire/complete/fail/heartbeat 的读-改-写；同 key 并发第二次 acquire 得
  `lease active` → `tool_call_skipped_inflight` + "already in-flight" 错误结果。
- 假 loop 最小面：`_emit` / `tool_activity` / `active_tool` / `engine.{ledger,
  policy, executor, approval_handler, hooks}` / `registry.{get_schema, get_handler}`
  / `guard` / `_invoke_handler`——策略桩全放行 DIRECT，executor 用真 `ToolExecutor()`，
  ledger 用真 `ExecutionLedger`（真互斥语义），handler 按工具名注入行为表。

## Design

新文件 `tests/test_tool_concurrency.py`（7 测试 × 4 类，批次规模固定 12）：

1. `TestBatchConcurrency`：
   - barrier 会师 + 倒序延迟打乱完成顺序 → 返回仍按调用顺序、内容逐位对应、
     批次事件 details 精确（count=12/errors=0）；barrier 超时 2s——串行退化
     显性失败而非挂死；
   - 在途展示态：12 handler 停在测试控制的 `Event` 上（批次在途窗口可观察），
     `active_tool` = 「首标签 (+11)」聚合、`tool_activity` 全 12 条、放行后清空。
2. `TestBatchIsolation`：2 个 handler 异常 / 2 个闸门（policy）异常各自落在精确
   的调用上，其余 10 个正常完成，批次完成事件 errors 计数精确。
3. `TestResourceContention`：
   - 12 调用含重复 id 对（首尾同 id）：handler 恰执行 1 次；重复调用要么命中
     缓存（成功）要么 "already in-flight" 错误——两种调度结果都合法，
     「只执行一次」是不变量；
   - 12 个不同 key 并发抢占真 ledger：全部执行成功、逐 key 落账 COMPLETED
     且 metadata.result 正确。
4. `TestCancellation`：12 handler 永久阻塞（barrier 永不满）→ 外部取消批次 →
   CancelledError 上抛、`active_tool` 被 finally 清空、`tool_batch_completed`
   不再发出。

</frozen-after-approval>

## Outcome

- `tests/test_tool_concurrency.py` 7 测试全绿（0.63s），ruff check / format 干净。
- 全量回归结论见提交时附注（本 plan 提交前的全量结果为 63.1 时点的
  4437 passed + 5 environmental）。
