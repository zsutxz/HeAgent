# Story 54-3 · WS 端点：订阅、续传、命令与防线

状态：**planned**

## 范围

按 `epics.md` Story 列表行交付；冻结决策见 `../brief.md` D2 / D3 / D5 / D6 / D7 / D8。**安全判据（Origin /
限额）与端点同批落地**——不得先合入一个不设防的 WS 端点（`epics.md` 实施约束 1）。

## 交付物

### 1. 事件面（复用，不重写）

- `_RunRecord`（`http_server.py:267`）：
  - 增 `ws_subscribers: set[asyncio.Queue[RunEventPayload | None]]`；
  - 增 `try_add_ws_subscriber(queue, limit) -> bool`：**检查与登记同一个无 `await` 的同步方法**（对标
    `try_add_subscriber` 的 A9③ 修复；D6）；
  - `append()` 的广播扇出扩展到两个集合（SSE 池 + WS 池）；`_drop_lagging_subscriber` 同样适用
    （跟不上 ⇒ 队列满 ⇒ 结束该流，客户端带游标重连）；
  - `close_subscribers()` 终态时给两个集合都投 `None` 哨兵（顺序：终态事件 → 哨兵，既有不变量不变）；
  - 增 `ws_connection_count`（测试/诊断用）；`subscriber_count` 语义**不变**（只数 SSE）。
- `stream_events(...)`（`:872`）：追加可选参数 `heartbeat_seconds: float | None = SSE_HEARTBEAT_SECONDS`；
  传 `None` 表示「不做心跳超时」（WS 有协议级 ping，D7）。**SSE 默认路径逐字不变**。

### 2. 端点（`network/ws_server.py`，新模块）

- 依赖方向：`http_server` **单向**导入 `ws_server`；`ws_server` 运行时**不 import starlette**（保持 `network/`
  可选依赖口径），类型用 `TYPE_CHECKING` + 本地 `Protocol`；不 import `http_server`（避免环）。
- `http_server` 侧（`build_http_app`，`:1750` 一带）：
  - 常量 `_RUN_WS_PATH = "/api/runs/{run_id}/ws"`；`run_service is not None` 时注册
    `routing.WebSocketRoute(_RUN_WS_PATH, endpoint=build_ws_endpoint(...))`，位置在 `/{asset}` 兜底路由**之前**；
  - 把两样东西**注入**给 `ws_server`（单源原则）：
    ① Origin 判据 —— 直接传 `_request_origin_violation`（`:998`）绑好 `hosts` / `ports` 的可调用；
    ② 游标 —— 从 `websocket.query_params` 解 `last_event_id`，解析失败给 `HttpErrorCode.INVALID_REQUEST`。
- `ws_server` 侧握手顺序（严格）：
  1. **Origin 校验（未 accept）**：违规 ⇒ `close()` 直接关（客户端见 HTTP 403，无 body，D8）+ WARNING
     日志（原因只进服务端，不透露允许的 host 集合）；
  2. `accept()`；
  3. `_closing` ⇒ `error` 帧 `shutting_down` + `close(1001)`；
  4. 解析 `run_id`：未知 ⇒ `error` 帧 `unknown_run` + `close(1008)`；
  5. 游标非法 ⇒ `error` 帧 `invalid_request`；越窗（`needs_resync`）⇒ `error` 帧 `resync_required`；
  6. 限额登记（同一步）：满 ⇒ `error` 帧 `rate_limited` + `close(1008)`；
  7. 读/写双任务，`asyncio.wait(FIRST_COMPLETED)`，收尾时取消另一路并注销（队列 + 连接登记）。
- 写任务：先按游标重放 ring buffer（`seq > cursor`），终态则发完即 `close(1000)`；随后跟随队列，`None`
  哨兵 ⇒ `close(1000)`；每条事件发 `WsEventFrame`（文本帧，`model_dump_json()`）。
- 读任务：`receive_text()` 循环 → `parse_command_frame` →
  - `ping` ⇒ `ack`（`status` 取当前 run 状态）；
  - `cancel` ⇒ `await service.cancel_run(run_id)`（既有有界取消，首个终态获胜、幂等）⇒ `ack`；
  - 超长 ⇒ `close(1009)`；畸形 / 未知命令 ⇒ `error` 帧 `invalid_request` + `close(1008)`；
  - `WebSocketDisconnect` ⇒ 正常退出（**不取消 run**）。
- 关停：`HttpRunService` 增 WS 连接登记（`register_ws` / `unregister_ws`）；`close()`（`:672`）顺序改为
  「停止接收 → 取消在途 run（既有，有界）→ 给仍开着的 WS 发 `shutting_down` 错误帧并 `close(1001)`
  （有界）」——总上界 2 × `shutdown_timeout`，幂等性沿用既有 `_lifecycle_lock` 口径。
- 观测：`ws_open` / `ws_close` 两条结构化日志（run_id / 不透明连接 id / 关闭码 / 耗时），**不记**帧内容；
  违规拒绝沿用 `origin_rejected` 事件名与字段口径。

## 验收标准（每条都要有判据）

1. **事件下发**：真 listener + stub provider，一次 run 产出 text / tool_call / tool_result / 终态四类事件；
   WS 收到的 `seq` 单调递增、`kind` 序列与 SSE 同一 run 的快照一致，文本截断长度与 SSE 逐字相同
   （同一 `clip_text` 口径，断言两路长度相等）。
2. **续传**：`?last_event_id=N` 只补 `seq > N`；`N = 最新` ⇒ 无重放、只跟随后续；越窗（`N < oldest-1`）⇒
   `resync_required` 错误帧 + 关闭；`last_event_id=abc` / 负数 ⇒ `invalid_request`。
3. **cancel**：`{"command":"cancel"}` ⇒ run 进 `CANCELLED` + `ack`；再发一次 ⇒ 仍 `ack`、无错误（幂等）；
   同一服务下另一次 run 状态**不受影响**（判据直接比对另一 record 的状态与事件数）。
4. **断线不取消**：客户端主动关闭 ⇒ run 继续跑并最终 `COMPLETED`（或既有终态）；`ws_connection_count` 归零；
   没有任何 `cancel` 调用（替身计数为 0）。
5. **Origin 四态**（D8，安全关键）：
   ① 跨源 `Origin: http://evil.example` ⇒ 客户端握手失败、HTTP 403（`InvalidStatus`），服务端不 accept；
   ② 伪造 `Host` ⇒ 同上；③ 端口不符 ⇒ 同上；④ **无 Origin ⇒ 正常连上**（正面判据，防「把无 Origin 判违规」
   让非浏览器客户端全挂）。
6. **限额原子性**：`ws_max_connections=N` 下，`asyncio.gather` 并发建 N+1 个连接，恰好 N 个成功、第 N+1 个
   收 `rate_limited` 错误帧（不是裸断连）；SSE 订阅面**不受影响**（同 run 仍可建 `max_subscribers` 个 SSE）。
7. **关停**：`server.close()` 期间所有 WS 连接收到 `shutting_down` 错误帧 + `close(1001)`；在途 run 终态
   `cancelled`；`close()` 总耗时 ≤ 2 × `shutdown_timeout` + 余量；重复调用幂等。
8. **缺依赖**：`websockets` 缺席时 WS 升级 404、HTTP 全绿（用 subprocess + 屏蔽 import 的探针，标
   `integration` 或 `skipif`，不进常规全绿基线；口径见 brief 探针 4）。
9. **SSE 零回归**：`tests/network/test_http_server.py` / `test_http_run_service.py` 全绿；`stream_events`
   在 `heartbeat_seconds=None` 下不发心跳帧（单元判据：超时窗口内无 `yield None`），默认参数下仍 15s 发。
10. **慢消费者**：WS 端不读、事件灌满队列 ⇒ 该连接被结束（`None` 哨兵）且**不静默丢事件**；客户端带游标
    重连能补齐（判据：重连后收到的 seq 集合 == 该 run 全量 seq）。
11. **变异体精确变红**（脚本 `.heagent/tmp/epic54/neg_54_3.py`，至少 8 个）：
    ① 去掉 Origin 校验；② 把「无 Origin」判违规；③ accept 之后再校验 Origin（应导致判据 5① 红）；
    ④ WS 与 SSE 共享订阅池；⑤ 限额「先查后加」拆成两步（判据 6 红）；⑥ 断线时顺手 cancel run（判据 4 红）；
    ⑦ 续传忽略游标全量重放（判据 2 红）；⑧ 关停不关 WS（判据 7 红）；⑨ 越窗时静默继续发（判据 2 红）。

## 任务

- [ ] 54-1 / 54-2 合入后再动（依赖）
- [ ] `tests/network/test_ws_server.py`（替身 websocket + 替身 service，判据 2/3/4/9/10 的纯逻辑面）
- [ ] `tests/network/test_http_ws_e2e.py`（真 listener + 真 uvicorn + `websockets` 客户端，判据 1/5/6/7）
- [ ] 实现 `ws_server.py` + `http_server.py` 接线
- [ ] 变异体脚本实跑，记录「N/N 精确变红 + 还原复绿」

## 验证命令（规划，执行时亲跑并登记实测）

```bash
pytest tests/network/test_ws_server.py tests/network/test_http_ws_e2e.py -q
pytest tests/network -q
ruff check src tests && ruff format --check src tests
mypy src
```

## 风险与口径

- **不要给 WS 加应用层心跳帧**（D7）：`stream_events(heartbeat_seconds=None)` 是唯一允许的「无心跳」形态，
  SSE 默认路径不得改。
- **不要复用 `record.subscribers`**（D6）：共享池会让 WS 吃掉 SSE 额度，且 `subscriber_count` 语义被污染。
- 关闭码是**契约**：`1000` 正常结束 / `1001` 服务关停 / `1008` 策略或协议违规 / `1009` 帧过大 /
  `1011` 内部错误；客户端据此决定「重连」还是「放弃」。
- 队列与 ring buffer 同界：WS 跟不上时的行为与 SSE 一致（结束该流、客户端重连补齐），**不**无限堆积。
