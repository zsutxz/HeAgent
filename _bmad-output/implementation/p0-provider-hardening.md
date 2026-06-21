---
title: 'P0 Provider 异常边界加固与安全声明'
type: 'bugfix'
created: '2026-06-19'
status: 'done'
baseline_commit: '8680b9d'
context:
  - '{project-root}/CLAUDE.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Provider 层（`OpenAIProvider`/`AnthropicProvider`）的 `send`/`stream` 不包装 SDK 异常——真实的 `openai.RateLimitError`/`anthropic.RateLimitError`/连接超时异常原样上抛。后果三连：(a) `KeyRotatingProvider._is_rotation_error`（key_rotation.py:58）因 `isinstance(error, ProviderError)` 为 False 而立即 re-raise，密钥轮换在生产路径下是死代码；(b) 单 provider 配置下 `retry_with_backoff`（retry.py:108 `except ProviderError`）接不到原始 SDK 异常，重试静默失效（cli.py:97 单 key 返回裸 provider）；(c) 原始 SDK 异常穿透 `HeAgentError` 层级，在 `asyncio.run` 处以非框架异常崩溃。测试全绿仅因 stub 直接抛 `ProviderError`，与真实 SDK 行为脱节。

**Approach:** 在 provider 源头（`openai.py`/`anthropic.py` 的 `send`+`stream`）用统一的 `wrap_provider_error` 把任意 SDK 异常包装成 `ProviderError(status_code=...)`，保留原始 cause。一处改动同时打通密钥轮换、retry、异常层级三项。配套：README/CLAUDE 顶部加安全边界声明（P0-1，零代码止损），并补「真实 SDK 异常」的集成测试锁定行为（含 P0-3 流式 tool_calls 回归）。

## Boundaries & Constraints

**Always:**
- 包装时保留原始异常：`raise wrap_provider_error(e) from e`，不丢堆栈。
- 用 `except Exception`（Python 3.11+ 下不捕获 `CancelledError`/`KeyboardInterrupt`，安全）。
- 包装逻辑单一来源（DRY）：当前 `chain._wrap_error` 与 `retry._extract_status_message` 重复同一套 duck-type（status_code/status/message），合并为 `retry.py` 中一个共享 `wrap_provider_error`，openai/anthropic/chain 共用。
- `ProviderError.status_code` 从异常 duck-type 提取（`status_code` → `status` → None）。
- 测试用「模拟真实 SDK 异常」类（带 `status_code`+`message`，**非** `ProviderError`）断言包装/轮换/重试生效。

**Ask First:** 无。

**Never:**
- 不改 `retry_with_backoff` 的 `except ProviderError` 签名（让 provider 源头包装，而非让 retry 吃任意异常——保持职责单一）。
- 不改 `KeyRotatingProvider._is_rotation_error` 的 `isinstance` 判定（同上理由）。
- 不重新实现 P0-3（Anthropic 流式 `get_final_message` 已由 commit `5a3bfda` 完成，本次仅加回归测试）。
- 不引入新依赖；不动 DAG（subagent 反向依赖属 P2，不在本次范围）。
- P0-1 安全声明不夸大、不改写 SafetyGuard 代码——仅诚实声明边界。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 429 限流 | `OpenAIProvider.send`，mock client 抛 SDK 风格异常(status=429) | `send` 抛 `ProviderError(status_code=429)` | 保留 cause；`KeyRotatingProvider` 据此轮换下一 key |
| 401 认证 | 同上，status=401 | `ProviderError(status_code=401)` | 触发轮换 |
| 5xx/超时（TRANSIENT） | 同上，status=503 或连接超时异常 | `ProviderError(status_code=503 或 None+timeout 消息)` | retry 中间件据此重试 |
| 客户端错误 400/422 | status=400/422 | `ProviderError(status_code=400)` | NON_TRANSIENT，不轮换不重试，立即抛出 |
| Anthropic 流式工具调用 | stream 模式 LLM 返回 tool_use | 逐块 yield 文本 + 最终 chunk 携带 tool_calls/usage/finish_reason | 回归：无需 `send()` 回退即拿到 tool_calls |
| 流式异常 | stream 中 SDK 抛异常 | 包装成 `ProviderError` 抛出 | 已交付 chunk 后不回退（chain 现有语义） |

</frozen-after-approval>

## Code Map

- `src/heagent/providers/retry.py` -- 新增共享 `wrap_provider_error(error) -> ProviderError`，复用现有 `_extract_status_message`
- `src/heagent/providers/chain.py` -- `_wrap_error` 委托 `retry.wrap_provider_error`，消除重复 duck-type
- `src/heagent/providers/openai.py` -- `send`(97)/`stream`(132) 包 `try/except Exception` 包装 SDK 异常
- `src/heagent/providers/anthropic.py` -- `send`(158)/`stream`(194) 同上包装
- `README.md` -- 顶部加「安全声明」小节
- `CLAUDE.md` -- 顶部加同等声明（或指向 README）
- `tests/providers/test_openai.py` -- 补 send/stream 抛真实 SDK 异常 → 断言包装为 ProviderError
- `tests/providers/test_anthropic.py` -- 同上 + 流式最终 chunk tool_calls 回归
- `tests/providers/test_key_rotation.py` -- 真实 OpenAIProvider(mock 抛 SDK 429) 包进 KeyRotatingProvider → 断言轮换
- `tests/providers/test_retry.py` -- `retry_with_backoff` 的 fn 抛 SDK 风格 503 → 断言重试

## Tasks & Acceptance

**Execution:**
- [x] `src/heagent/providers/retry.py` -- 新增 `wrap_provider_error(error)`（复用 `_extract_status_message`，返回 `ProviderError(message, status_code=status)`） -- DRY 单一包装源
- [x] `src/heagent/providers/chain.py` -- `_wrap_error` 委托 `retry.wrap_provider_error`（或替换调用点） -- 消除重复 duck-type
- [x] `src/heagent/providers/openai.py` -- `send` 与 `stream` 体包 `try: ... except Exception as e: raise wrap_provider_error(e) from e` -- 源头包装，打通轮换/retry/层级
- [x] `src/heagent/providers/anthropic.py` -- `send` 与 `stream` 同上 -- 同上
- [x] `README.md` -- 顶部「安全声明」：HeAgent 不适合在不可信内容/不可信 LLM 输出下运行，须配 OS 级沙箱（容器/firejail），SafetyGuard 非真正安全边界 -- P0-1 止损
- [x] `CLAUDE.md` -- 顶部同等声明或指向 README -- 与 README 一致
- [x] `tests/providers/test_openai.py` -- 新增：mock `create` 抛带 `status_code` 的 SDK 风格异常，断言 send/stream 抛 `ProviderError` 且 status_code 正确 -- 锁定包装
- [x] `tests/providers/test_anthropic.py` -- 新增同上 + 流式最终 chunk tool_calls 回归 -- 锁定包装与 P0-3
- [x] `tests/providers/test_key_rotation.py` -- 新增：真实 OpenAIProvider(mock 抛 SDK 429) 包进 KeyRotatingProvider，断言轮换到第二 key -- 证明死代码已修复
- [x] `tests/providers/test_retry.py` -- 新增：`retry_with_backoff` 的 fn 抛 SDK 风格 TRANSIENT(503)，断言重试到成功 -- 证明单 provider retry 已生效

**Acceptance Criteria:**
- Given `OpenAIProvider.send` 的 mock client 抛 status=429 的 SDK 异常，when 调用 send，then 抛 `ProviderError` 且 `status_code==429`，且 `__cause__` 为原始异常。
- Given 真实 OpenAIProvider（mock 抛 SDK 429）包进 `KeyRotatingProvider([keyA, keyB])`，when 调用 send，then 返回 keyB 的响应（轮换发生）——修复前此用例直接抛出。
- Given `retry_with_backoff` 包裹一个抛 SDK 风格 503 两次后成功的 provider 调用，when 执行，then 重试并返回成功——修复前不重试直接抛。
- Given 任意 provider 异常上抛到 `asyncio.run`，then 异常类型为 `HeAgentError` 子类（`ProviderError`），不再是裸 SDK 异常。
- Given `README.md`/`CLAUDE.md`，then 顶部存在「安全声明」段落，明确不可信环境须配 OS 沙箱。

## Spec Change Log

- 2026-06-19：调查发现 P0-3（Anthropic 流式 `get_final_message`）已由 commit `5a3bfda` 完成，本次仅保留回归测试，不再重写实现。范围由「P0 三项」收窄为「P0-1 文档声明 + P0-2 异常包装（含真实 SDK 异常测试）+ P0-3 回归锁定」。
- 2026-06-19（验证）：实现完成。`pytest tests/providers/` 88 全绿（含 7 个新增「真实 SDK 异常」用例，已显式确认 PASSED）；全量 pytest 342 passed / 1 failed——唯一失败 `test_config::test_default_max_iterations` 为**既有环境耦合**（`.env` 设 `MAX_ITERATIONS=20`、测试未 `reset_settings()`，与本次无关，留待 P3）。ruff/mypy 对改动文件均 **0 新增错误**（既有 TC003/UP042/E501 基线问题不变，mypy providers 基线 2 错 == 改后 2 错）。P0-3 回归由既有 `test_anthropic::test_stream_yields_text` 覆盖（最终 chunk 携带 tool_calls/usage/finish_reason），无需新增。
- 2026-06-19（评审）：3 路并行评审（盲审 / 边界 / 验收）。**验收审计**：5 AC + 5 Never-rule 全 MET、DRY MET → PASS。**边界 hunter** 发现 HIGH：OpenAI `APITimeoutError`/`APIConnectionError` 经包装后 `_classify` 因 `"timeout"` 不匹配 `"timed out"` 误判 NON_TRANSIENT → 单 provider 超时仍不重试（违反已冻结 I/O 矩阵「连接超时→retry 据此重试」）→ 已 **patch**：`_classify` 加 `"timed out"`/`"connection"` 关键词 + 2 个分类测试（test_retry 21 全绿）。其余 **reject**（盲审 B1/B2/B3/B5/B6/B7 + 边界 E3，均实测/核验为误报或既有惯例）。1 项 **defer**：Chain 对已包装 ProviderError 双层重包（见 deferred-work.md，LOW，P2 范围）。无 intent_gap/bad_spec → 不触发 loopback。

## Design Notes

包装点示意（`openai.py` send）：

```python
try:
    resp = await self._client.chat.completions.create(**kwargs)
except Exception as e:
    raise wrap_provider_error(e) from e
```

`wrap_provider_error`（`retry.py`）复用 `_extract_status_message`：

```python
def wrap_provider_error(error: Exception) -> ProviderError:
    status, message = _extract_status_message(error)
    return ProviderError(message, status_code=status)
```

为何在 provider 源头包装、而不放宽 retry/key_rotation 的 except：保持「分类/轮换/重试逻辑只认 HeAgent 体系异常」的职责边界，单一改动点（provider 层）使三条链路同时生效，且避免 retry 吞掉非 provider 的意外异常。

## Verification

**Commands:**
- `pytest tests/providers/` -- expected: 全绿，含新增真实 SDK 异常用例
- `pytest` -- expected: 全套绿
- `ruff check src tests` -- expected: 无新增错误
- `mypy src/heagent/providers` -- expected: 无新增错误（关注 `wrap_provider_error` 返回类型）

**Manual checks:**
- 检查 `README.md`/`CLAUDE.md` 顶部「安全声明」段落存在且措辞诚实（不夸大 SafetyGuard）。

## Suggested Review Order

**核心抽象：异常包装单一来源**

- 共享包装函数——DRY 单一来源，复用 `_extract_status_message` 的 duck-type。
  [`retry.py:74`](../../src/heagent/providers/retry.py#L74)

- 错误分类纯函数；评审 patch 行——补 `"timed out"`/`"connection"` 让 OpenAI 超时/连接错误归 TRANSIENT。
  [`retry.py:51`](../../src/heagent/providers/retry.py#L51)

- chain 的包装现委托共享函数，消除重复 duck-type。
  [`chain.py:20`](../../src/heagent/providers/chain.py#L20)

**provider 源头包装（P0-2 修复面）**

- OpenAI `send` 包 `try/except Exception`→`ProviderError`，保留 cause。
  [`openai.py:117`](../../src/heagent/providers/openai.py#L117)

- OpenAI `stream` 同样包装（create + 迭代整体入 try）。
  [`openai.py:172`](../../src/heagent/providers/openai.py#L172)

- Anthropic `send` 包装；流式 `async with` 整体入 try 后于此抛包装异常。
  [`anthropic.py:184`](../../src/heagent/providers/anthropic.py#L184)

- Anthropic `stream` 把 `async with`+`get_final_message` 整体包入 try。
  [`anthropic.py:221`](../../src/heagent/providers/anthropic.py#L221)

**安全声明（P0-1 零代码止损）**

- README 顶部「安全声明」——不可信环境须配 OS 沙箱，SafetyGuard 非真正边界。
  [`README.md:5`](../../README.md#L5)

- CLAUDE.md 同等声明（SafetyGuard 非真正边界，须 OS 级沙箱）。
  [`CLAUDE.md:5`](../../CLAUDE.md#L5)

**测试：真实 SDK 异常证明死代码已修**

- 杀手用例——真实 OpenAIProvider(mock 抛 SDK 429) 包进 KeyRotatingProvider 断言轮换。
  [`test_key_rotation.py:179`](../../tests/providers/test_key_rotation.py#L179)

- 证明单 provider retry 经包装后对 SDK 瞬时错误重试。
  [`test_openai.py:169`](../../tests/providers/test_openai.py#L169)

- 证明 send 把 SDK 异常包装为 ProviderError 且保留 `__cause__`。
  [`test_openai.py:141`](../../tests/providers/test_openai.py#L141)

- patch 回归——OpenAI 超时短语现判为 TRANSIENT。
  [`test_retry.py:73`](../../tests/providers/test_retry.py#L73)
