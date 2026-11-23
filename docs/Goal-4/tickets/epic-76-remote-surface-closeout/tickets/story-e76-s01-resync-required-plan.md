---
ticket: 1
ref: 76.1
code: E76-S01
epic: epic-76-remote-surface-closeout
risk: medium
hitl: false
covers: ["R3", "R4"]
status: built
---

# E76-S01 · 断连续流三判据：无空洞 / 窗口不足必须 resync_required / 重复可见可去重

## Tasks & Acceptance

- [x] **取证先行**：确认既有订阅实现对「run 记录已不存在」的口径（结论见 Design Notes 第 1 条：**已是具名错误帧**，故 `src/heagent/network/ws_server.py` 零改动）。
- [x] 新建 `tests/network/test_ws_resume.py`（225 行，四例），用 fake `RunWebSocketService` 驱动**真实**端点 `build_ws_endpoint`，不跑真 run。
- [x] ① 无空洞 `test_reconnect_from_the_last_event_id_leaves_no_hole`：连收 5 帧后断开，以第 5 帧事件 id 作 `last_event_id` 重连 ⇒ 续到首帧 `<= last_event_id + 1`、此后连续递增、末帧 == 服务端缓冲尾部且是取消终态；两次会话拼接是无空洞序列。
- [x] ② 窗口不足必须响 `test_a_cursor_behind_the_ring_window_must_fail_loudly_before_any_event`：`buffer_size=1` + 3 条事件（`oldest_seq=3`）、cursor=1 ⇒ 帧类型序列**恰为** `["error"]`（顺序断言：没有任何 event 帧先于 `resync_required`），并按 `WS_CLOSE_POLICY` 关闭；同例附反向控制 cursor=`oldest_seq-1` **不得**误判 resync。
- [x] ③ 重复可见可去重 `test_overlapping_replay_is_visible_and_dedupes_by_event_id`：cursor 回退到 2 ⇒ 重放 `3..6` 与本地 `1..4` 重叠 2 条，`len(merged) - len(set(merged)) == 2`，去重后恰为服务端事件全集。
- [x] ④ run 已清理 `test_a_cleaned_up_run_returns_a_named_error_frame_not_an_empty_stream`：`run()` 恒回 `None` ⇒ 非空帧序列且恰一条 `error`，code == `unknown_run`，`WS_CLOSE_POLICY` 关闭 —— **不是静默空流**。
- [x] 记录与游标判据复用生产实现（`http_server.records._RunRecord` 的真实有界 ring buffer + `http_protocol.cursor_out_of_window` 的算术单源），fake 只替身服务端口，不重写语义。
- [x] 写集严守票面：只新增 `tests/network/test_ws_resume.py` + 本 plan；`src/` 零改动。

## Verification

| 命令 | 结果 |
|---|---|
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network/test_ws_resume.py -q` | **4 passed**（1.75s） |
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network -q` | **711 passed, 1 warning**（24.26s；warning 是 starlette `TestClient` 的既有 `BlockingPortal` DeprecationWarning） |
| `.heagent/tmp/py311-venv-linux/bin/python -m ruff check src tests` | All checks passed! |
| `.heagent/tmp/py311-venv-linux/bin/python -m ruff format --check src tests` | 505 files already formatted |
| `.heagent/tmp/py311-venv-linux/bin/python -m mypy src` | Success: no issues found in 240 source files |
| `git -c safe.directory=/workspace diff --stat src/heagent/network/ws_server.py` | **空（0 行）**——取证显示既是具名错误，票面允许的「0 行 diff」分支 |
| `wc -l tests/network/test_ws_resume.py` | 225（单文件上限 1000） |

四条断言清单（逐条可核）：

1. 无空洞：`resumed[0] <= received[-1] + 1` ∧ `resumed == range(resumed[0], resumed[-1] + 1)` ∧ `resumed[-1] == record.events[-1].seq` ∧ `received + resumed == range(1, N + len(resumed) + 1)` ∧ 末帧 `kind == cancelled`。
2. 窗口不足：`[frame["type"] for frame in frames] == ["error"]` ∧ `code == resync_required` ∧ `WS_CLOSE_POLICY in close_codes`；反向控制 `_event_seqs(boundary) == [3]` ∧ 无 `error` 帧。
3. 重复可见可去重：`replay == [3, 4, 5, 6]` ∧ `len(merged) - len(set(merged)) == 2` ∧ `sorted(set(merged)) == [payload.seq for payload in record.events]`。
4. run 已清理：`frames` 非空 ∧ 帧类型序列 == `["error"]` ∧ `code == unknown_run` ∧ `WS_CLOSE_POLICY in close_codes`。

## Code Map

| 文件 | 改动 |
|---|---|
| `tests/network/test_ws_resume.py` | **新建**，225 行：`_ResumeWebSocket`（按 `stop_after` 模拟断线、`close_codes` 全记）、`_ResumeService`（端口替身，`needs_resync` 直调 `cursor_out_of_window`）、`_subscribe()` 会话驱动、`_event_seqs()` 帧投影 + 四例 |
| `docs/Goal-4/tickets/.../story-e76-s01-resync-required-plan.md` | 本文件 |
| `src/heagent/network/ws_server.py` | **无改动**（取证结论；见下） |

## Design Notes

1. **取证结论：订阅「run 记录已不存在」**已是具名错误帧，**不是空流** ——
   `_prepare_subscription()`（`src/heagent/network/ws_server.py:326-329`）在 `service.run(run_id) is None` 时
   直接 `_send_error(websocket, HttpErrorCode.UNKNOWN_RUN, "no such run", close_code=WS_CLOSE_POLICY)` 后返回，
   `session()` 随即结束、骨架收尾关连接。实证探针（`.heagent/tmp/probe_resume.py`，一次性）输出：
   `frames: [{"type": "error", "error": {"error": {"code": "unknown_run", "message": "no such run"}}}]`、`closed_code: 1000`。
   ⇒ 票面「仅当是空流才做最小修复」不触发，`ws_server.py` 保持 0 行 diff。用例 ④ 把这条既有行为钉住。

2. **窗口不足与「订阅成功后再报 resync」互斥**（AD-5 不变量）：`needs_resync` 判在 `try_add_ws_subscriber`
   **之前**（`ws_server.py:334-343`：`needs_resync` 在 :334，`try_add_ws_subscriber` 在 :343），且 `_send_error` 是同步两连（错误帧 → close），故帧序必然
   `error` 单帧、不可能出现「先来一条事件」。用例 ② 用**帧类型序列相等**（而非「存在 error 帧」）表达
   这个顺序不变量 —— 任何「先发后判」的重构都会红。

3. **重复的来源是游标回退，不是服务端重传**：`replay_then_follow` 只发**严格大于** cursor 的部分，
   并把 `replayed_upto = max(cursor, 快照最大 seq)` 当水位去重（`http_protocol.py:594-641`，水位在 :617-620）。因此
   「同一条 id 收到两次」只能来自客户端把 cursor 报小了（失忆重连），这正是 at-least-once 的语义面；
   用例 ③ 显式制造这次重叠并断言**重复可见**（`len(merged) - len(set(merged)) == 2`），而不是断言
   服务端替客户端去重 —— 后者会把「协议诚实性」测成「实现偷偷兜底」。

4. **fake 的边界只到端口**：`_ResumeService` 只实现 `RunWebSocketService` 协议（`run` / `needs_resync` /
   `register_ws` / `unregister_ws` / `_closing`），记录用生产的 `_RunRecord`（真 `deque(maxlen=…)`、
   `try_add_ws_subscriber`、`close_subscribers`、`oldest_seq`），游标判据用生产的 `cursor_out_of_window`。
   这样测的是**端点接线**（Cursor 解析 → resync 判定 → 重放/跟随 → 终态收尾），不是本文件自己写的算术。

5. **`version=""` 装配**：`_subscribe()` 传空版本 ⇒ 无 `hello` 帧，`sent` 里只有事件/错误帧，
   「帧类型序列」断言不必跳首帧（`hello` 由 `tests/network/test_ws_event_contract.py` 与既有端点用例覆盖）。

6. **断线模型**：`_ResumeWebSocket.receive_text()` 阻塞在 `asyncio.Event` 上，发满 `stop_after` 帧才置位并抛
   `WebSocketDisconnect`（与 Starlette 同名，`_next_command` 按类型名判对端断开）—— 于是「收满 N 帧后断开」
   是确定性的，不靠 sleep 抢时序；`_supervise` 的 FIRST_COMPLETED 收尾语义因此也被顺带覆盖。

7. **`close_codes` 记全序**：端点会 close 两次（错误帧的 `WS_CLOSE_POLICY` + `_ws_session` 收尾的默认 1000），
   真实 Starlette 上第二次是 no-op。断言写成「策略码**在**列表里」而非「== 1008」，避免把替身的记账顺序
   当契约。

## Plan Change Log

- 2026-11-23：实现子会话一次成稿（取证 → 四例 → 门禁），无返工。取证结论使 `src/` 进入 0 行 diff 分支，
  写集从票面的两条收敛为一条（仅新增测试）+ 本 plan。

## 宿主复核（2026-11-23，批末串行门禁）

- 实现子会话在 25 次迭代处超限退出（未回报），工作树留下 `tests/network/test_ws_resume.py`（225 行，四例）与本 plan；宿主接手核验并跑门禁。
- `pytest tests/network/test_ws_resume.py -q` → **4 passed**；批内合成 `pytest tests/network/test_ws_resume.py tests/network/test_ws_project_admission.py tests/network/test_ws_protocol.py -q` → **57 passed**。
- 写集审计：本批三条只出现各自 `write_set` 内的改动（`git status --porcelain` 仅三个测试文件 + 三份 plan），无 src 越集写。
- 取证结论复核：`src/heagent/network/ws_server.py:326-329` 确为具名 `unknown_run` 错误帧 + `WS_CLOSE_POLICY`，`git diff --stat src/heagent/network/ws_server.py` 为空。
