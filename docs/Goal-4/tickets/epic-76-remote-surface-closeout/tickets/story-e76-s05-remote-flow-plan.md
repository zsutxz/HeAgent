---
ticket: 5
ref: 76.5
code: E76-S05
epic: epic-76-remote-surface-closeout
risk: medium
hitl: false
covers: ["R1", "R3", "R4"]
status: done
---

# E76-S05 · ADR-005 五步验收串跑：列项目 → 两项目各 1 run → 事件流完整 → 取消其一 → cursor 续流

## Tasks & Acceptance

- [x] 新建 `tests/network/test_ws_remote_flow.py`（419 行）：**单条用例** `test_adr_005_acceptance_baseline_runs_end_to_end` 内按 ①→⑤ 顺序断言，任一步失败即整体红。
- [x] ① 列项目：`projects` 帧帧类型序列 == `["hello","projects"]`、帧键集合 `{type,projects,registry_state}`、`registry_state == "ok"`、条目 id 顺序 == `[A,B]`、每条键集合恰 `{id,name,available}`（`path` 不出入口层）。
- [x] ② 两项目各 1 run：两条集合级连接 `asyncio.gather` 并发提交 ⇒ 两个 ack 都是 `ack/run/RUNNING`、`run_id` 不同且各自的连接上只有自己的 `run_id`；控制台收到的 `(project_id, prompt)` 逐字对位；每条 run 记录的 `project_id` 归位。
- [x] ③ 事件流完整不串味：两条订阅连接同时在线，各写入 3 条事件 ⇒ 文本逐条对位、`seq` 从 1 起连续、事件帧不带 `run_id`（AD-6）故用**归属**判交叉：对端事件出现次数 0。
- [x] ④ 取消其一：`cancel_run(run_a)` ⇒ ack 逐字 `{"type":"ack","command":"cancel_run","run_id":run_a,"status":"cancelled"}`、`service.cancel_calls == [run_a]`；A 的流以 `cancelled` 终态收尾且全程无空洞；**B 仍 `RUNNING`**、仍收到新事件（`B#4`）、交叉计数 0。
- [x] ⑤ cursor 续流：B 连接 `disconnect()`（收满 4 帧后断），断线期间产生 `B#5`；以 `last_event_id=4` 重连 ⇒ 首帧 `<= last_event_id + 1`、其后连续递增到缓冲尾部（`seq == 7`）、末帧是 `DONE` 终态；`received + resumed == range(1, 8)`（两段拼接无空洞）。
- [x] 收尾回看：两路各自完整到自己的终态、两条连接的登记都注销（`service.registrations == {}`）、取消连接按正常码关闭。
- [x] 写集严守票面：只新增本测试文件 + 本 plan；**`src/` 零改动**。

## Verification

| 命令 | 结果 |
|---|---|
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network/test_ws_remote_flow.py -q` | **1 passed**（单例五步串跑） |
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network -q` | **729 passed, 1 warning** |
| `git -c safe.directory=/workspace diff --stat src/` | **空**（纯测试增量，逐字符合票面要求） |
| `.heagent/tmp/py311-venv-linux/bin/python -m ruff check src tests` / `ruff format --check src tests` | 全绿（507 files） |
| `wc -l tests/network/test_ws_remote_flow.py` | 419（单文件上限 1000） |

## Code Map

| 文件 | 改动 |
|---|---|
| `tests/network/test_ws_remote_flow.py` | **新建**，419 行：`_RunServiceStub`（真 `_RunRecord` + 订阅登记表）、`_FakeProjectConsole`（projects 投影 + 提交）、`_collection_endpoint` / `_run_endpoint` 装配、`_CommandWebSocket` / `_SubscriptionWebSocket`（可 `disconnect()`、记 `close_codes`）、`_await_subscribed` / `_await_events` / `_seqs` / `_events` / `_cross_count` 投影 + 单例五步 |
| `docs/Goal-4/tickets/.../story-e76-s05-remote-flow-plan.md` | 本文件 |
| `src/` | **无改动** |

## Design Notes

1. **为什么复用生产记录而不是再造一个**:`_RunRecord`（`network/http_server/records.py`）自带真实有界 ring buffer、`claim_terminal`、`close_subscribers` 与 `oldest_seq`；fake 只替身**端口**（`RunWebSocketService` / `ConsoleHandler`），端点接线与游标算术用生产实现。这样「续流无空洞」测的是端点行为，不是测试自己写的数列。
2. **五步必须在同一条用例内**：跨用例会各自重建 world，「取消 A 后 B 仍活」「断线期间的事件靠续流补齐」这类**时相**断言就没法成立。这是票面明确要求，也让失败信息直接指向「串到第几步断了」。
3. **交叉计数的口径**：事件帧按 AD-6 不带 `run_id`，因此「不串味」不能靠 `run_id` 集合求交，改用**归属**判据——拿到 `record` 的 `events` 文本集合，断言对端前缀（`A#` / `B#`）在本连接上出现次数为 0。ack 面则仍按 `run_id` 集合断言。
4. **断线模型**：`_SubscriptionWebSocket.disconnect()` 让 `receive_text()` 抛 `WebSocketDisconnect`（与 Starlette 同名），端点随即注销订阅并收尾；`_await_events` 用轮询 + 上限等待事件写入，避免 sleep 竞态。
5. **`hello` 帧**：`projects` / `run` 的集合级端点装配时带版本 ⇒ 帧序首帧是 `hello`，断言里显式计入（不跳首帧，避免「hello 消失」这类回归被判绿）。

## Plan Change Log

- 2026-11-23 首版（实现子会话在 25 次迭代处超限退出、未回报；工作树留下完整测试文件，宿主接手核验、补本 plan 并跑门禁）。
