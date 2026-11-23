---
ticket: 2
ref: 76.2
code: E76-S02
epic: epic-76-remote-surface-closeout
risk: medium
hitl: false
covers: ["R1", "R2"]
status: built
---

# E76-S02 · 两项目并发不串味与名额分层：四判据不新增计数、不动参数

## Tasks & Acceptance

- [x] 新建 `tests/network/test_ws_project_admission.py`（316 行，四例 + 一节夹具），驱动**真实**集合级端点 `build_runs_collection_endpoint`，用桩端口替身 `RunWebSocketService` / `ConsoleHandler` 项目面。
- [x] ① 并发不串味 `test_two_projects_submitted_concurrently_do_not_cross_talk`：两条连接 `asyncio.gather` 同时提交 A、B ⇒ 控制台收到的 `(project_id, prompt)` 映射逐字等于 `{A: prompt_a, B: prompt_b}`、交叉计数 0、两个 ack 的 `run_id` 不同且跨连接 `run_id` 交集为空；出站帧里**没有** `project_id`（客户端靠 ack 的 run_id 认领，AD-6）；`service.start_run`（启动工作区路径）**0 次**。
- [x] ② 项目内上限 `test_second_submit_into_a_busy_project_is_project_busy_and_stops_at_the_precheck`：A 已有在途再提交 A ⇒ 错误帧 code 逐字 `project_busy`，且第二次**未触达** `start_project_run`（调用数 1、`submissions` 只有一条、slot 不叠加）。
- [x] ③ 全局上限 `test_global_limit_is_total_inflight_limit_and_distinguishable_from_run_conflict`：名额耗尽回 `total_inflight_limit`、项目内占用回 `run_conflict`，两码可分辨（`codes == {"total_inflight_limit", "run_conflict"}`），且两次拒绝都不占名额、都不关连接。
- [x] ④ 不占名额 `test_rejected_submit_never_reaches_the_submit_port`（三码参数化 `unknown_project` / `project_unavailable` / `project_registry_unreadable`）：`start_project_run` 0 次、slot 为空、错误帧之后 `ping` 仍拿到 ack（拒绝不改写连接状态）。
- [x] 写集严守票面：只新增 `tests/network/test_ws_project_admission.py` + 本 plan；`src/` **零改动**（未暴露适配器改写 / 吞码，无需最小修复）。
- [x] 未新增计数状态、未新增配置键、未改并发参数：`grep -rn "MAX_INFLIGHT\|Semaphore" src/heagent/network/ws_server.py` ⇒ **0 命中**（既有席位计数是 `_SubmissionSlots`，本 entry 未触碰）。

## Verification

| 命令 | 结果 |
|---|---|
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network/test_ws_project_admission.py -q` | **6 passed**（四例 + 三码参数化展开） |
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network -q` | **728 passed, 1 warning** |
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests -q -k http_console` | **128 passed, 5770 deselected** |
| `grep -rn "MAX_INFLIGHT\|Semaphore" src/heagent/network/ws_server.py` | **0 命中** |
| `.heagent/tmp/py311-venv-linux/bin/python -m ruff check src tests` / `ruff format --check src tests` / `mypy src` | 全绿（506 files / 240 source files） |
| `wc -l tests/network/test_ws_project_admission.py` | 316（单文件上限 1000） |

四条判据的逐条断言：

1. 交叉计数 0：`dict(console.submissions) == {A: prompt_a, B: prompt_b}` ∧ `_cross_count(...) == 0` ∧ `run_ids(ws_a) & run_ids(ws_b) == ∅`。
2. `project_busy`：`frames[2]["error"]["error"]["code"] == "project_busy"` ∧ `start_project_run_calls == 1` ∧ `inflight == {A: frames[1]["run_id"]}`。
3. 两码可分辨：`codes == {"total_inflight_limit", "run_conflict"}` ∧ `console.rejected == [TOTAL_INFLIGHT_LIMIT, RUN_CONFLICT]`。
4. 不占名额：`start_project_run_calls == 0` ∧ `console.inflight == {}` ∧ `service.start_run_calls == 0`；`project_registry_unreadable` 一路另断言 `console.calls == []`（健康守卫把控制台整个挡在外面）。

## Code Map

| 文件 | 改动 |
|---|---|
| `tests/network/test_ws_project_admission.py` | **新建**，316 行：`_FakeProjectConsole`（在途/上限/前置错三态 + 调用计数）、`_RunWebSocketServiceStub`（真 `start_run` 计数）、`_QueueWebSocket`（帧队列 + 关闭码）、`_cross_count` / `_run_ids` 投影 + 四例 |
| `docs/Goal-4/tickets/.../story-e76-s02-plan.md` | 本文件 |
| `src/heagent/cli/ws_project_adapter.py` | **无改动**（适配器未改写/吞掉任何 code，无需最小修复） |

## Design Notes

1. **哪些码由端口桩抛出、哪些生产链上真实可出**（票面要求写明）：
   - 桩抛：`project_busy`（生产里由**删项目端点**产生，WS 提交链上不产生）、`unknown_project` / `project_unavailable`（生产里由控制台的 `_runtime_for` 产生，本 entry 用 `ConsoleOperationError` 桩再现）。
   - 生产真实可出：`run_conflict`（会话级：同一项目已有在途 run）、`total_inflight_limit`（全局席位）、`project_registry_unreadable`（适配器 `_guard_registry`，E75 收口时落地）。
   - ⇒ 本 entry 的判据是「**转译与不占名额**」，不是「码的产量」。哪些码由谁抛已经逐条写在这里，避免后来者把桩当生产证据。
2. **并发不串味的证法**：用 `asyncio.gather` 同时跑两条端点的完整命令循环（每连接一帧 `run`），断言控制台看到的映射与两个 ack 的 `run_id` 归属。它证的是「帧 → 端口」的绑定不共享状态，而不是线程安全；真正的并发隔离由 E76-S05 的端到端五步承载。
3. **「不占名额」的判据不靠计数实现**：断言 `start_project_run_calls == 0` + `inflight` 集合形状（控制台侧），而不是给 `network/` 加可见计数——票面明令「不新增计数、不动参数」。这也让判据在实现重构后仍有意义。
4. **第三条（新项目 C）撞全局上限、第四条（已占用的 A）撞项目内上限**：用**同一条连接连发四帧**，检验「拒绝不断连」——错误帧之后命令循环仍继续收帧，收尾才按正常码关闭（`closed_code == 1000`）。
5. **`hello` 帧计入帧序**：端点 `version` 非空时首帧是 `hello`，因此帧序断言写成 `["hello", "ack", ...]`；`version=""` 的装配形态在 76.1 的用例里出现过，两种形态都覆盖到了。

## 宿主复核（2026-11-23，批末串行门禁）

- 实现子会话在 25 次迭代处超限退出（未回报），工作树留下 `tests/network/test_ws_project_admission.py`（316 行，四例 + 参数化）但**未写 plan**；宿主按实测补本 plan 并跑门禁。
- `pytest tests/network/test_ws_project_admission.py -q` → **6 passed**；`pytest tests/network -q` → **728 passed**；`pytest tests -q -k http_console` → **128 passed**。
- `grep -rn "MAX_INFLIGHT\|Semaphore" src/heagent/network/ws_server.py` → 0 命中（未新增计数状态）。
