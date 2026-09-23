---
id: 49-4
title: 运行取消、SSE 重连与资源限制
status: done
parent_epic: E49
priority: P0
depends_on: [49-3]
created: '2026-09-23'
---

# Story 49-4：运行取消、SSE 重连与资源限制

## 用户故事

作为网页用户，我希望能停止卡住或不再需要的运行，并在浏览器短暂断线后继续接收进度，以便网页操作不会留下失控任务或错误状态。

## 范围

- 实现 `DELETE /api/runs/{run_id}` 的协作式取消。
- 为每个 run 维护有界事件 ring buffer 和单调事件序号。
- 支持 SSE `Last-Event-ID` 续读与缓存窗口外的明确重同步错误。
- 实施 HTTP 请求体、连接、SSE 订阅、在途运行、事件缓存和运行时长限制。
- 处理客户端断线、取消竞态、运行超时和服务关闭的任务清理。

## 边界与约束

**Always**

- 取消只作用于指定 run；不得取消其他 run 或关闭整个服务。
- 客户端断开 SSE 不自动取消 Agent；取消必须通过 DELETE 或服务 shutdown。
- 所有限制在协议边界和运行时边界均有校验，满额时明确失败，不无限排队。
- 事件丢失时显式要求 session 重同步，不发送不连续的伪完整流。

**Never**

- 不用无界队列、无限缓存或无限等待来“保证”事件送达。
- 不吞掉 `CancelledError`，不把取消误报为普通 Agent 成功。
- 不让迟到的任务重新占用已释放的并发名额。
- 不改变 TCP server 已有的限额和关闭语义。

## 任务

- [x] 定义 run 终态和取消/超时状态转换。
- [x] 实现有界事件缓存、事件 id 和 Last-Event-ID 解析。
- [x] 实现 DELETE 取消、运行 timeout 和 SSE 断线清理。
- [x] 实现 HTTP 连接、请求体、订阅、并发和事件大小限制。
- [x] 增加取消、断线重连、缓存淘汰、超限和 shutdown 测试。
- [x] 在网页 UI 中显示取消中、已取消、重连中和需重新同步状态。

## 验收标准

- Given 一个运行正在执行，When 客户端请求 `DELETE /api/runs/{run_id}`，Then Agent task 收到取消信号，SSE 最终发送 `cancelled`，并释放在途运行名额。
- Given 客户端已收到事件序号 N 后断线，When 客户端带 `Last-Event-ID: N` 重新订阅，Then 服务从 N 之后的有界缓存继续发送，事件不重复且顺序稳定。
- Given 客户端请求的序号早于已淘汰的缓存窗口，When 客户端重新订阅，Then 服务返回明确的 `resync_required`，客户端可以通过 session 快照恢复，不伪造完整事件流。
- Given 请求体、连接数、SSE 订阅数、在途运行数或单次运行超过配置上限，When 客户端发起请求或运行持续，Then 服务返回稳定限流/超时错误或取消运行，不无限排队、不耗尽进程资源。
- Given SSE 客户端断线、取消竞态或服务关闭，When 清理逻辑执行，Then 订阅者、任务和并发登记最终释放，后续运行可正常开始。

## Definition of Done

- run 状态机明确区分 running、completed、failed、cancelled、timed_out。
- 事件 buffer 有界且事件 id 单调递增；Last-Event-ID 处理有覆盖测试。
- DELETE 取消、SSE 断线、超时和 shutdown 的 task ownership 不产生 orphan task。
- 资源限制和稳定错误码在 API 测试中覆盖，现有 TCP 限额行为不受影响。

## 代码地图

- `src/heagent/network/http_server.py`：取消、超时、订阅和关闭生命周期。
- `src/heagent/network/http_protocol.py`：终态事件、错误码和重同步响应。
- `src/heagent/cli_http.py`：run task factory 与服务级限额注入。
- `src/heagent/web/`：SSE 重连、取消和重同步 UI 状态。
- `tests/test_http_run_lifecycle.py`：取消、断线、重连、超时和清理测试。

## Review Status

**已实现并验证（2026-09-23）。** 实现期间发现并修复一个**真实缺陷**（见下「关键缺陷」）。

### 实现记录

| 变更 | 说明 |
| --- | --- |
| `src/heagent/network/http_protocol.py` | `RunCreatedResponse` 改名 `RunStatusResponse`（创建与取消共用）；新增 `SSE_HEARTBEAT_SECONDS=15.0` 与 `SSE_HEARTBEAT_FRAME`（注释帧） |
| `src/heagent/network/http_server.py` | `_RunRecord.oldest_seq`（resync 下界）；`HttpRunService.cancel_run`（只取消指定 run、等待有界、幂等）、`needs_resync`（严格语义 `cursor < oldest-1`）、`subscriber_count`、`stream_events(..., heartbeat_seconds=)`（`yield None` = 心跳）、`_execute` 包 `asyncio.timeout(request_timeout)` → `timed_out` 终态；`_finalize`（done callback：注销任务 + 归还名额 + 兜底补写终态，见「关键缺陷」）；`_run_tasks` 由 set 改为 `run_id → task` 映射；`_parse_last_event_id`（畸形头按「无游标」处理）；`DELETE /api/runs/{id}` 端点；事件流端点的 resync 判定（409）与订阅上限（429）；`_sse_stream` 把 `None` 转成心跳帧 |
| `src/heagent/web/app.js` | 停止按钮接线 `DELETE`（成功不在前端宣布结果，等 SSE 的 `cancelled`）；`reconnecting` 状态 + `resyncFromSession()`（断线时拉一次会话快照：若服务端已终结或运行记录已变，收敛到真实状态并提示「可能有事件未送达」）；`cancelling` 状态；忙态集合扩展 |
| `tests/network/test_http_run_service.py` | 新增 `TestCancellation`（5 例）、`TestReconnect`（8 例：Last-Event-ID 严格语义、越窗 409、边界值放行、畸形头、心跳、订阅上限、断线释放订阅者）、`TestRunTimeout`（3 例：超时终态、超时后关停不改写、超时不投影） |
| `tests/test_http_agent_api.py` | 新增 `test_delete_cancels_a_real_run`（真实 loop 被取消）与 `test_disconnect_does_not_cancel_the_run`（断线只释放订阅者） |
| `docs/frame.md` | 4.17 新增「取消、重连与终态」「限额与超时」两行；调用链补 SSE 语义与 DELETE；已知缺口新增 3 条（HTTP 入口非安全边界 / 不接 MCP / 会话与事件无持久化） |

### 关键缺陷（实现测试时发现并修复）

**症状**：`DELETE /api/runs/{id}` 返回 200 但 `status=running`；随后订阅事件流**永久挂住**（等不到终态事件）；在途名额也不归还。

**根因**：`asyncio.create_task()` 之后若在**该任务被首次调度之前**就 `cancel()`，协程体**根本不会执行**——`_execute` 的 `except CancelledError` 与 `finally` 都不跑，于是记录永远停在 `running`、`_active` 永远占着名额。HTTP 路径（POST 立即返回 → 客户端紧接着 DELETE）正好命中这个窗口，而直接调用 `service.cancel_run()` 的单元路径命中不了（已有事件循环让出的机会）——第一版测试因此只覆盖了后者。

**修复**：把「注销任务 + 归还名额 + 终态兜底」放进任务的 done callback（`_finalize`），任何结束路径都覆盖；正常路径下 `claim_terminal` 是 no-op，不会改写既有终态。修复后有真实 HTTP 复现脚本（`.heagent/tmp/repro_cancel.py`）与三条覆盖该路径的测试钉住。

### 验证证据（本机 2026-09-23）

| 项 | 命令 | 结果 |
| --- | --- | --- |
| 定向测试 | `pytest tests/network tests/test_http_agent_api.py tests/test_cli_http.py tests/test_cli_http_lifecycle.py` | **223 passed** |
| 全量回归 + 覆盖率 | `pytest --cov=heagent --cov-fail-under=85`（实际 `--cov-fail-under=87`） | **2417 passed, 9 skipped, 18 deselected；91.07%** |
| Lint / 格式 / 类型 | `ruff check`；`ruff format --check`（260 files）；`mypy src --platform linux` | 全部通过（140 source files） |
| 取消路径复现 | `.heagent/tmp/repro_cancel.py`（POST → DELETE → GET events → GET session） | DELETE 0.00s 返回 `cancelled`；事件流含 `cancelled` 终态；session `messages=[]` |

### 偏差与边界（如实记录）

1. **订阅者上限复用 `HTTP_MAX_CONNECTIONS`**（不新增配置项）：SSE 订阅本质就是一条 HTTP 连接，单独造旋钮只会多一处要同步的默认值；超出返回 429 `rate_limited`。
2. **心跳间隔是内部常量 + 参数**（`SSE_HEARTBEAT_SECONDS=15.0`），未开设置项：它是协议层保活语义（AD-4 固定 15s），而测试需要小间隔，故做成 `stream_events(..., heartbeat_seconds=)` 参数（端点用默认值）。
3. **`resync_required` 是 409 + JSON 信封**（不是 SSE 流内事件）：浏览器的 `EventSource` 读不到错误响应体，所以页面的 `onerror` 统一「显示重连中 + 拉一次会话快照」，由快照给出真实状态（不会假装还在跑）。
4. **取消是协作式的**：忽略取消的运行会在 `shutdown_timeout` 后如实返回 `running`，由运行超时或关停兜底（`asyncio` 无法强杀）。
5. **`max_connections` 与订阅上限的交叉**：连接级仍由 Uvicorn `limit_concurrency` 承担，应用层只在每 run 维度把关。

## Requirement Traceability

FR6–FR9; NFR5, NFR8; UX-DR3, UX-DR4, UX-DR6。
