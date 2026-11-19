---
title: 'Story 71.5 请求计数与延迟'
type: feature
ticket: 5
created: '2026-11-19'
status: done
baseline_revision: '2c0f0f1'
route: full
route_source: auto
risk: medium
review: thorough
review_source: auto
lenses_ran: ['edge-case-hunter(inline)', 'verification-gap(inline)']
review_loop_iteration: 0
followup_review_recommended: false
context:
  - 'src/heagent/network/http_server/middleware.py'
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** 没有任何请求级观测的**结构化出口**——每条请求只打一行日志，想知道「错了多少次、慢到什么程度」只能翻日志做文本统计。

**Approach:** 新增 `http_server/metrics.py` 的 `RequestMetrics`（整数计数 + 有界延迟窗口），由 `_AccessLogMiddleware` 在**收尾路径**就地记账；`build_http_app` 持有实例并挂到状态来源上，`/api/status` 的 `requests` 字段只读快照。

## Boundaries & Constraints

**Always:**
- 热路径只做整数自增与一次 `deque` 追加：无锁、无 I/O、无格式化。
- 错误码只从**非 2xx 且 ≤1KB 的 JSON 信封**里读；正常响应（SSE / 静态资源 / 大 JSON）从不进该路径。
- 窗口有界（常量 256），中位数/最大值是对窗口的近似。
- 计数在响应发出**之后**记账（读状态那次自身不计入本次快照）。

**Never:**
- 不采集请求体 / 头 / 提示词；不做持久化；不引第三方分位数库；不改变既有访问日志格式。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| CLASSES | 3×2xx + 1×404 | total=4，2xx=3，4xx=1 | 无 |
| BOUNDED | 灌 10× 窗口 | 窗口长度=容量，p50/max 可算 | 无 |
| ERROR_CODE | 405 JSON 信封 | `error_codes` 含 `method_not_allowed: 1` | 无 |
| NON_JSON | 纯文本 / 超大 / 无 error 键 | 不计错误码 | 不抛错 |
| IDEMPOTENT | 连读两次 status | 第二次 total = 第一次 + 1（只有本次请求） | 无 |

</intent-contract>

## Code Map

- `src/heagent/network/http_server/metrics.py`（新）-- `RequestMetrics`（total / 四桶 / 窗口 / 错误码）+ `error_code_from_body`。
- `src/heagent/network/http_server/middleware.py` -- `_AccessLogMiddleware(app, metrics)`：非 2xx 攒一小段 body，`finally` 里记账。
- `src/heagent/network/http_server/app.py` -- `_attach_metrics(source)` 建载体并挂到来源（鸭子契约，不加必填 Protocol 方法）。
- `src/heagent/network/http_protocol.py` -- `RequestMetricsSummary` / `ErrorCodeCount` + `StatusResponse.requests`。
- `src/heagent/cli/http_status.py` -- `attach_metrics` 与快照映射。
- `tests/test_http_status_api.py::TestRequestMetrics` -- 覆盖 I/O Matrix。

## Tasks & Acceptance

**Execution:**
- [x] `metrics.py` -- 计数 + 窗口 + 错误码解析 -- 热路径最小动作。
- [x] `middleware.py` / `app.py` -- 记账与挂载 -- 不改日志格式、不加必填方法。
- [x] 协议与来源映射 -- 快照封闭、错误码上限 16。
- [x] 测试与 `docs/frame.md` -- 判据与文档。

**Acceptance Criteria:**
- Given 3 个 2xx + 1 个 404, then total=4 且 4xx=1。
- Given 灌入 10 倍窗口容量, then 窗口长度等于容量且 p50 < max。
- Given 一次 405, then `error_codes` 含 `method_not_allowed`。
- Given 连读两次 status, then 计数只增 1（快照自身不计入）。

## Implementation Notes

- 挂载方式是**鸭子契约**（`getattr(source, "attach_metrics", None)`）：`StatusSource` Protocol 因此不必新增必填方法，既有测试替身（`_EmptyStatusSource`）零改动。
- `build_http_app` 曾因多出的 if 撞 C901（17 > 15），建筑体抽成 `_attach_metrics()` 后回到阈值内。
- 新模块会进路由快照的 `path_constants`（快照按子包 glob），故 `transport_routes.json` 需重生成。

## Plan Change Log

## Review Triage Log

### 2026-11-19 — Review pass（内联自查）
- verdicts: 3 findings — high 0, medium 1, low 2, false 0, maybe-false 0
- findings:
  - `[medium]` `[patch]` 「读状态是否会重复计量」原先无判据（可能一次读取算两次）— 加「连读两次只增 1」用例；语义写进模型 docstring（计数在响应之后记账）。
  - `[low]` `[patch]` 计数与错误码只断言存在、不断言具体值 — 改为断言 `method_not_allowed: 1` 落在 `error_codes` 里；变异验证：关掉记账 / 分桶写死 / 去掉挂载 ⇒ 三条各 RED。
  - `[low]` `[patch]` 新增模块使路由快照的 `path_constants` 变化 — 重生成 `transport_routes.json` 并 `--check` 全绿。

## Auto Run Result

- **实现**：`requests`（total / 四桶 / p50 / max / 错误码频次）进 `/api/status`，由中间件就地记账。
- **文件**：`src/heagent/network/http_server/metrics.py`（新）、`middleware.py`、`app.py`、`src/heagent/network/http_protocol.py`、`src/heagent/cli/http_status.py`、`tests/test_http_status_api.py`、三份契约基线、`docs/frame.md`。
- **评审处置**：patch 3 条（medium 1 / low 2），无 defer / reject。
- **后续评审建议**：`false`。
- **验证**：`pytest`（`tests/network` + 相关套件 **925 passed / 34 skipped**）；四份契约快照 `[OK]`；`ruff` / `format` / `mypy` 全绿；变异 3/3 RED。
- **残差**：延迟窗口 256 条（近似 p50，非分位数库）；错误码上限 16 条（超出按次数截断）；不跨进程、不持久化。

## Code Review

### 2026-11-19（lenses: edge-case-hunter + verification-gap）

**Code review complete.** 1 `decision-needed`, 5 `patch`（已修）, 1 `defer`, 6 rejected。

- [x] [Review][Decision→Resolved] 流式响应（SSE）的延迟按「整条连接时长」计入窗口 — `middleware.py` 在 `finally` 里算 elapsed，一条运行期订阅（可长达数分钟）会独占 `latency_max_ms` 并把 p50 拉偏，而面板把它标成「延迟」。Options: (a) 记 TTFB（`http.response.start` 时刻），(b) 多 chunk 响应不计入延迟窗口（只计总数与错误码），(c) 维持现状但在 docstring 与面板注明「含流式连接时长」。Recommended: (b) — 该指标意在「请求有多慢」，流式连接寿命不是请求延迟。**裁定 2026-11-19（用户「按推荐」）= 采纳 (b)**：`metrics.is_event_stream()` 判 `text/event-stream`，`RequestMetrics.record(streamed=True)` 只计总数与错误码、不进延迟窗口（按 content-type 判定，避免把分块 JSON 误当流式）；判据 `test_streaming_response_is_counted_but_kept_out_of_the_latency_window`，`docs/frame.md` 状态 API 行同步。
- [x] [Review][Patch] p50 取值无钉死（改成 `ordered[0]` 也满足 `max > p50 > 0`）— 已补 `test_percentile_is_the_window_median_not_the_minimum`（3 / 4 / 单样本 / 空窗口）。
- [x] [Review][Patch] 16 条错误码截断从未被越界（删掉切片会让 `/api/status` 校验失败变 500）— 已补 `test_error_codes_are_truncated_with_the_loudest_kept`（20 码 + 高频码排首）。
- [x] [Review][Patch] `status=0`（应用在 `response.start` 前抛错）分支无用例 — 中间件若在此抛错会替换原异常。已补 middleware 级用例（原异常穿透 + 只计总数、四桶为 0）。
- [x] [Review][Patch] `metrics.py` 注释写「512 条」而常量是 256 — 已更正。
- [x] [Review][Defer] 端点计数用例用的是**复刻映射**的替身（`_CountingStatusSource`），真实 `HttpStatusSource._request_metrics` 的数值无断言 — deferred: A74

Rejected:
- false：`metrics.record` 抛错会替换已服务的响应 — 分桶有 `if bucket in self._classes` 守卫，`record` 无其它可抛路径。
- rejected(low)：非 2xx body 单块可超 1024 上限 — 单块体积由错误信封决定（KB 级），`error_code_from_body` 侧另有上限。
- false：`total` 与四个分桶之和不等 — 刻意如此（status 0 / 1xx 只计总数），代码注释与面板分列已说明。
- rejected(low)：样本少时 p50 == max — 中位数定义使然，docstring 已写「样本少时就是真实值」。
- rejected(low)：`build_http_app` 二次调用会覆盖 `source._metrics` — 仓内无「一个 source 建两个 app」的调用点（`HttpServer.app` 缓存）。
- rejected(low)：热路径里有 f-string — 每请求一次字符串拼接，与「无格式化」的措辞不符但不构成开销问题。
