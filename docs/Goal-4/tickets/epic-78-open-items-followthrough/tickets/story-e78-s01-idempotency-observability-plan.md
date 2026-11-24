---
ticket: 1
ref: 78.1
code: E78-S01
epic: epic-78-open-items-followthrough
risk: low
hitl: false
covers: ["R1"]
status: built
---

# E78-S01 · 幂等窗口可观测：容量淘汰与键移出各一条 debug 日志

## Intent

<frozen-after-approval>

E77 的幂等窗口**没有任何日志**：窗口满了静默淘汰最旧一条、失败静默移出键，线上只能靠
`run_conflict` 现象反推「同键是不是被重复提交了」。补两条 debug 事件即可定位是哪一类。

`request_id` 是客户端的不透明键，**不进日志**（与「ack 不回显、不落 `x-request-id`」同一立场）；
只记 `project_id` 与 reason。TTL 过期清理属正常回收，**不打日志**（否则每次提交都刷一条噪声）。

</frozen-after-approval>

## Boundaries & Constraints

**Always**

- 两条事件名固定：`ws event=idempotency_evicted`（容量淘汰，`reason=capacity`）、
  `ws event=idempotency_dropped`（键移出，`reason=failed` / `reason=cancelled`）。
- 日志里只有 `project_id` + `reason`（+ 淘汰时的 `entries` 计数）；**不含** `request_id`。
- 级别 DEBUG：这是逐请求的可观测面，不是告警。

**Never**

- 不加 `/api/status` 字段、不做指标导出、不改窗口语义与数字（60s / 256）。
- 不在 TTL 过期清理处打日志。
- 不改 ack 帧与错误码。

## Code Map

- `src/heagent/cli/ws_submission_cache.py`：`logger` + `reserve`（容量淘汰分支）与
  `drop(key, *, reason)`（新增关键字参数，默认 `"failed"`）。
- `src/heagent/cli/ws_project_adapter.py`：失败分支 `drop(key, reason="failed")`、
  owner 取消分支 `drop(key, reason="cancelled")`。
- `tests/test_ws_submission_cache.py`：`caplog` 两例（容量淘汰 / 不记 `request_id` / TTL 清理静默）。
- `tests/test_ws_project_adapter.py`：cancel 路径的 reason 断言。
- `docs/framework.md`：模块表行补两句事件名。

## Tasks & Acceptance

- [x] `SubmissionCache` 加 logger 与两条事件；`drop` 带 reason。
- [x] 适配器两处调用传对 reason。
- [x] 判据：容量淘汰恰一条且 `project_id` 正确、日志无 `request_id`、TTL 清理零条。
- [x] `docs/framework.md` 模块表行补事件名。

## Verification

| 命令 | 期望 |
|---|---|
| `pytest tests/test_ws_submission_cache.py tests/test_ws_project_adapter.py -q` | 全绿（含 3 例新断言） |
| `ruff check` / `mypy src` | 干净 |

## 实测结果（2026-11-24）

见 `docs/Goal-4/progress.md` 本轮决策日志（含注入反证：去掉 `caplog` 断言对应代码即红）。
