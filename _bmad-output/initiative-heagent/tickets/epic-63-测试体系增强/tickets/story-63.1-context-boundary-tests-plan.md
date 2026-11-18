---
title: 'Story 63.1 增加大上下文窗口边界测试'
type: test
ticket: 1
created: '2026-11-18'
status: built
baseline_revision: 'd5e35879bc3f63264c61cac49119782c79510510'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
context:
  - 'src/heagent/context/compressor.py'
  - 'src/heagent/context/window_reset.py'
  - 'src/heagent/context/tokens.py'
  - 'src/heagent/agent/context_runtime.py'
  - 'tests/test_compressor.py'
  - 'tests/test_window_reset.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 票面要求「接近 512K tokens 的大上下文边界测试就位」。既有测试面
（test_compressor.py 149 行 / test_tokens.py 200 行 / test_window_reset.py）全部为小规模
单元测试，512K 窗口规模（`Settings.max_context_tokens` 默认 512000）下的行为全空缺。

**Verify 拆解：**
- 覆盖上下文压缩触发点 → compressor（80% 阈值）与 window_reset（60% 阈值）在 512K
  窗口下的阈值两侧边界 + `maybe_compress` 循环接线；
- token 估算准确性 → 512K 规模下启发式估算精确性（ASCII/CJK/混合）与 `count_tokens`
  线性缩放（含 tiktoken 路径）；
- 无内存泄漏 → 代理不变量：摘要请求本身有界（≤ `max_summary_tokens`，无论对话多大）、
  重复大压缩不增长模块级缓存（按模型键控）、原消息列表不被就地修改。

## Survey（baseline d5e3587）

- 512K 出处：`config/__init__.py:163` `max_context_tokens: int = Field(default=512000)`。
- 两条压缩路径：
  - `ContextCompressor.compress`（`context/compressor.py:109`）：`token_count/max_tokens >= 0.8`
    触发；切分点越过 recent 开头孤儿 TOOL；`_summarize` 输入上限
    `min(max_tokens, max_summary_tokens=4096)` − 安全边距 1024，从末尾向前保留。
  - `WindowReset.should_trigger`（`context/window_reset.py`）：`>= 0.6` 触发。
- 循环接线：`agent/context_runtime.py::maybe_compress` 以 `usage.total_tokens` 触发，
  `is` 判同替换 + `context_compressed` 事件（details: before/after）。
- 旁路记账：compressor 经 `sidecall.send_accounted` 调 provider，副作用
  `note_actual_usage` 写 `_CALIBRATION`（按模型键控）——conftest 已有
  `_reset_token_calibration` autouse 隔离。
- 既有小规模测试已覆盖：阈值触发语义、孤儿 TOOL、recent 全 TOOL 放弃、校准系数、
  后端选择——本 story 只补「512K 规模」维度，不重复小规模语义。

## Design

新文件 `tests/test_context_boundary.py`（15 测试 × 6 类）：

1. `TestCompressorTriggerAt512K`：409,599（差一点）不压缩且零摘要调用；
   409,600（恰 0.8）触发；600,000 超窗防御性触发。触发只看上报数与窗口比值——
   「差一点」用例的内容本身即 ~550K 规模，钉死「不看内容只看计数」。
2. `TestCompressIntegrityAtScale`：~550K 对话（220 轮 USER→ASSISTANT(tool_calls)→TOOL×2）
   压缩后：列表长度恰为 1+1+4、SYSTEM 保位、摘要 USER 角色、无孤儿 TOOL、
   最近 TOOL 结果逐字保留、原列表不就地修改。
3. `TestSummaryInputBounded`：~550K 对话的摘要请求估算 ≤ 4096；最新 old 轮标记在、
   前一轮与最早轮标记不在（末尾优先截断语义）。
4. `TestWindowResetBoundaryAt512K`：307,199 不触发 / 307,200（恰 0.6）触发 /
   满窗触发 / 窗口 0 永不触发。
5. `TestTokenEstimationAtScale`：ASCII/CJK/混合 512K 精确；`count_tokens` 同消息 ×6
   线性恒等式（每副本增量 = 主体 + 每条结构开销，对 tiktoken 路径同样成立）。
6. `TestBoundedStateAtScale` + `TestMaybeCompressAtScale`：3× 大压缩缓存不增长；
   `maybe_compress` 超阈替换+事件（details 逐字段断言）/低阈 identity/无 usage 跳过。

</frozen-after-approval>

## Outcome

- `tests/test_context_boundary.py` 15 测试全绿（0.37s）；连带 test_compressor /
  test_tokens / test_window_reset / test_tokenizer 76 passed。
- 全量回归 4437 passed / 5 failed / 16 skipped；5 失败经
  `scripts/verify_baseline.py` 判 **environmental**（干净 HEAD d5e3587 同样 16 passed
  5 failed——`test_setup_ws_external.py` 的 .env 换行参数化，Windows 检出环境产物，
  与本 story 无关）。
- ruff check / ruff format --check 干净。
