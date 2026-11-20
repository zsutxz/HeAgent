---
title: 'Story 63.3 增加 Provider 全部失败场景测试'
type: test
ticket: 3
created: '2026-11-18'
status: done
baseline_revision: '249873d'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
context:
  - 'src/heagent/providers/chain.py'
  - 'src/heagent/providers/fallback_base.py'
  - 'src/heagent/agent/middleware.py'
  - 'src/heagent/agent/stream_runtime.py'
  - 'src/heagent/agent/run_lifecycle.py'
  - 'tests/providers/test_chain.py'
  - 'tests/providers/test_retry.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 票面要求「Provider 全部失败场景的容错测试就位」。勘测发现 provider
**单元**层覆盖已充分（test_chain.py 19 测试：全失败抛错/回退/限流回退/auth 回退/
客户端错不回退/流式变体/双包防重；test_retry.py：分类矩阵 + retry_with_backoff
六路径）；**缺口在组合层与 loop 层**——重试中间件 × ProviderChain 两层容错全耗尽、
以及 AgentLoop 端到端「全失败 → 显性上抛 + run_failed 结构化事件」无测试。

**Verify 拆解：**
- 覆盖重试与回退逻辑 → 组合层：瞬时末端错误触发整链重入（每 provider 打满
  max_attempts）、客户端错末端即时抛出不重入；
- 系统返回友好错误且不崩溃 → 库层面「友好」= 显性失败（原 ProviderError 带消息与
  status_code 上抛，入口层负责展示）+ run_failed 事件结构化分类
  （error_kind 封闭映射 / 原始错误保留 / duration_ms）+ 失败不毒化后续 run。

## Survey（baseline 249873d）

- 容错两层拓扑：`make_retry_middleware`（agent/middleware.py）包在 `ProviderChain`
  （providers/chain.py）之外；chain 回退判据 `FallbackPolicy.should_fallback_chain`
  （NON_TRANSIENT 不回退），链尾 `raise_as_provider_error(last_error)` 原样上抛
  （ProviderError 已包装则不二次包，保 cause 链）。
- loop 非流式：`_call_provider`（agent/loop.py:477）经中间件链调 provider.send；
  失败经 `run()` except → `on_run_failed`（run_lifecycle.py:376）：FAILED 终态 +
  error checkpoint + `run_failed` 事件（details: error / error_kind / duration_ms）
  → **re-raise 留在调用方 except 末尾**（显性失败）。
- loop 流式：`stream_runtime.py:103` **直调 `loop.provider.stream`，不经重试中间件**
  ——容错只剩 chain 内部回退。这是勘测发现的现状契约（非本票修复项），测试钉死。
- `error_kind_for`（events/protocol.py:104）：ProviderError 不在封闭映射内 →
  归类 `exception`。
- run_failed 事件断言基建：`loop.engine.events.recent_events`
  （test_agent_loop.py:130 同款）。

## Design

新文件 `tests/test_provider_all_fail.py`（5 测试 × 3 类）：

1. `TestRetryFallbackExhaustion`（组合层，compose + make_retry_middleware 直拼）：
   - 全瞬时链（503×2）：重试重入整链 → 每 provider 恰 2 次调用 → 链尾错误原样
     浮出（message + status_code = 链尾 provider 的）；
   - 客户端错末端（503→400）：链回退耗尽即抛 400，重试层不重入（每 provider 1 次）。
2. `TestLoopRunAllFail`（非流式端到端）：
   - 3×503 链 + 重试中间件：run() 显性上抛；每 provider 2 次；`run_failed` 恰 1 条，
     details 原始消息 / error_kind==exception / duration_ms>=0；
   - 失败不毒化：全失败 run 后换可用链再跑 → 正常完成，run_completed 恰 1 条。
3. `TestLoopStreamAllFail`：流式同场景——显性上抛 + run_failed 事件同契约；
   每 provider 恰 1 次 stream 调用（钉「流式不经重试中间件」现状契约）。

</frozen-after-approval>

## Outcome

- `tests/test_provider_all_fail.py` 5 测试全绿（0.61s），ruff check / format 干净。
- 全量回归终态见提交时附注。
- 勘测副产物登记：流式路径无重试中间件属现状契约，测试已钉死；如需补齐属行为
  变更，归 open-items 由用户裁定。
