---
title: '58-1 通知中枢与 /api/notifications/ws 端点（network 层）'
type: 'feature'
created: '2026-10-28'
status: 'review'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: 'a372f2b80ce308b81426be82c361827c12912676'
context: []
---

<!-- 交付物与验收边界 = epic-58 epics.md 的 D1/D2/D3/D7；本 story 只动 network/ 与契约测试，不碰 cli/。 -->

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** cron 执行完只把 `cron_job_completed` 发进进程内 `EventBus`（`cron/scheduler.py`），
`network/` 侧没有任何订阅者、也没有「非 run 产物」的推送通道 ⇒ 已连接的客户端永远收不到结果
（2026-10-28 实测：三轮 hello 触发、零帧到达）。

**Approach:** 在 `network/` 里加一条**只读通知流**：`NotificationHub`（跨轮次 seq + 环形缓冲 256 +
游标重放 + 背压踢人 + 有界关停）+ 端点 `WS /api/notifications/ws`。发布侧由 58-2 接进 cron runner，
本 story 只提供中枢、帧模型与端点，**不含任何配置开关**（开关在 58-2 的装配层，本层拿不到 `Settings`）。

同时把 `CliEventHub` 的「seq / 缓冲 / 游标 / 背压 / 关停」提炼成通用核 `EventStreamHub`，两个 hub
都变成薄适配——**不复制第二份实现**（Epic 58 D3）。

## Boundaries & Constraints

**Always:**
- `network/` 的依赖边界不变：只允许 stdlib + pydantic + `network/` 同层协议模型；**不得** import
  `agent/engine/providers/tools/memory/skills/context/cron/events/config`
- `CliEventHub` 的公共面**逐字不变**：`max_connections` / `closing` / `active_run_id` /
  `subscriber_count` / `connection_count` / `oldest_seq` / `published_events` / `needs_resync` /
  `begin_run` / `end_run` / `publish_text` / `publish_tool_call` / `publish_tool_result` /
  `publish_done` / `publish_error` / `publish_cancelled` / `open_subscription` / `remove_subscriber` /
  `register_ws` / `unregister_ws` / `close` / `reopen` / `close_websockets`
- 既有 41 例（`test_cli_event_hub.py` 15 / `test_cli_ws_e2e.py` 13 / `test_cli_ws_publish.py` 8 /
  `test_cli_ws_wiring.py` 5）**一行不改**，作为重构的验收线
- 通知帧的 `seq` 是**整条流**单调（跨 job、跨执行），客户端只用它做游标
- `publish_*` 对通知同样「绝不抛」：字段校验失败 / 扇出异常 → 一条 warning 后丢弃
- 端点命令面与 CLI 旁路同口径：`ping` 回 ack；`cancel` 与 `run` 一律回 `invalid_request` 且**不断连**
- 关停：`close()` 置标记（新连接直接收 `shutting_down`），`close_websockets()` 有界关闭并登记回收

**Never:**
- 不新增 Settings 字段、不读环境变量、不碰 `config/`
- 不改 `/api/runs/ws`、`/api/runs/{run_id}/ws`、`/api/cli/ws` 三条既有端点的任何行为
- 不让通知流具备写能力（不能提交 run、不能取消、不接受除 `ping` 外的命令）
- 不用魔法字符串传递「这是 cron」：走 `NotificationKind` / `CronResultStatus` 枚举

</frozen-after-approval>

## I/O & Edge-Case Matrix

| 场景 | 输入/状态 | 预期行为 | 错误处理 |
|---|---|---|---|
| 首连 | `CRON_PUSH` 中枢存在，无 `last_event_id` | accept → 重放缓冲全部 → 实时推送 | N/A |
| 带游标重连 | `?last_event_id=<seq>` 在窗口内 | 只补 `seq > cursor` 的条目 | N/A |
| 游标已淘汰 | `last_event_id < oldest_seq - 1` | `resync_required` 错误帧 + 关闭（1008） | 客户端不带走游标重连 |
| 非法游标 | `?last_event_id=abc` / 超 19 位 | `invalid_request` 错误帧 + 关闭 | 同 `_parse_cursor` 既有判据 |
| 中枢缺席 | `notification_hub is None` | `WS /api/notifications/ws` **路由不注册** ⇒ 客户端拿 403 | 不注册 ≠ 应用层 404 |
| 限额 | 已满 `ws_max_connections` 条订阅 | `rate_limited` 错误帧 + 关闭 | 与 CLI 旁路同口径 |
| 订阅者落后 | 队列满（落后整整一窗口） | 踢掉该订阅（队列塞 `None` 哨兵）并 warning | 客户端带游标重连 |
| `ping` | `{"command":"ping"}` | `WsCliAckFrame`（`run_id` 空串） | 复用既有 ack 模型，不新造 |
| `cancel` / `run` | 任意 | `invalid_request` 错误帧，**连接不断** | 明确拒绝而非静默忽略 |
| 超长 / 残缺命令帧 | > `WS_MAX_COMMAND_CHARS` / 非 JSON / 未知命令 | 1009 关闭 / 1008 关闭 | 与既有端点同判据 |
| 关闭中 | `hub.closing == True` | 新连接收 `shutting_down` + 1001 | 不崩 |
| 重复 `close()` / `reopen()` | 两次调用 | 幂等；reopen 后新连接正常 | N/A |
| 发布时机无订阅者 | 有 `publish_*`、无订阅者 | 只进缓冲，无异常 | N/A |

## Code Map

- **新增** `src/heagent/network/event_stream_hub.py` —— 通用核（`EventStreamHub`）：stream 分配、
  seq 分配、环形缓冲、`needs_resync`、`open_subscription`（重放 + 登记原子完成）、背压踢人、
  WS 连接登记与有界关停。载荷由子类构造（`make_payload(seq) -> PayloadT`）。
- **改** `src/heagent/network/cli_event_hub.py` —— 变薄适配：`CliEventHub(EventStreamHub[CliBufferedEvent])`，
  公共面逐字不变，模块文档串改述「两条流共用一个核，语义差异只在发布方法」。
- **新增** `src/heagent/network/notification_hub.py` —— `NotificationHub`：
  `publish_cron_result(*, job_id: str, status: CronResultStatus, text: str, cron: str = "") -> None`；
  缓冲区上限沿用 `CLI_EVENT_BUFFER_SIZE` 同量级（256）。
- **改** `src/heagent/network/http_protocol.py` —— 新增 `NotificationKind`（`CRON_RESULT`）、
  `CronResultStatus`（`COMPLETED` / `FAILED`）、`NotificationPayload`（`extra="forbid"`：
  `kind` / `seq` ≥1 / `job_id` / `status` / `text` / `cron`），文本字段入缓冲前过 `clip_text`。
- **改** `src/heagent/network/ws_protocol.py` —— `WsFrameType` 增 `NOTIFICATION`；
  新增 `WsNotificationFrame`（`type=notification`、`notification: NotificationPayload`）。
- **改** `src/heagent/network/ws_server.py` —— 新增 `build_notification_ws_endpoint(hub, *, origin_violation, authorize=None)`：
  复用 `_parse_cursor` / `_send_error` / `_reject_*` / `parse_command_frame`；命令面只放行 `ping`。
- **改** `src/heagent/network/ws_host.py` —— 新增 `NOTIFICATIONS_WS_PATH = "/api/notifications/ws"`
  常量；`build_ws_app(..., notification_hub=None)` 注册路由（D2：本地 / 对外 / readonly 都注册，
  不按 `mode` 收窄）；`WsServer(..., notification_hub=...)` 保存并参与 `start/stop/close_websockets/reopen`。
- **改** `tests/test_architecture_contracts.py` —— 两条契约判据同步：
  - `test_ws_endpoints_and_commands_stay_closed`：路径集合 3 → 4（新增 `/api/notifications/ws`），
    `WsCommand` 集合**不变**（仍是 `{run, cancel, ping}`）。
  - `test_external_ws_listener_never_exposes_the_cli_bypass_surface`：本地 4 条 / 对外 3 条 /
    只读 2 条（只读仍只有订阅 + 通知？→ 见下方「待冻结」第 2 条）。
- **新增** 测试 `tests/network/test_event_stream_hub.py` / `test_notification_hub.py` /
  `test_notification_ws_e2e.py`（真实 TCP，`port=0`）。

## 待评审确认（写进 Spec Change Log 后即可开工）

1. `WsNotificationFrame` 是否需要携带 `stream_id`：**当前取「不需要」**，客户端按
   `notification.job_id` + `seq` 定位；`stream_id` 只在 hub 内部用于日志与关停。
2. 只读 listener（`readonly=True`）是否注册通知端点：**当前取「注册」**（本端点天然只读，
   与「提交端点在 readonly 下不注册」不冲突）。
3. 通知端点是否要独立的连接限额键：**当前取「复用 `WS_MAX_CONNECTIONS`」**，不新增配置键。

## Tasks & Acceptance

**Execution:**
- [ ] `network/event_stream_hub.py` —— 通用核（从 `cli_event_hub.py` 提炼，行为等价）
- [ ] `network/cli_event_hub.py` —— 薄适配；既有 41 例零改动全绿
- [ ] `network/notification_hub.py` + `http_protocol.py` 载荷模型
- [ ] `network/ws_protocol.py` —— `NOTIFICATION` 帧类型与帧模型
- [ ] `network/ws_server.py` —— `build_notification_ws_endpoint`
- [ ] `network/ws_host.py` —— 路径常量 + 注册 + 生命周期接线
- [ ] 契约测试两条判据同步；新增三份测试文件
- [ ] `docs/frame.md` 的 network 模块表与端点表补 `notification_hub` / `/api/notifications/ws`

**Acceptance Criteria:**
- Given `NotificationHub` 已发布 3 条（job A、job B、job A），when 订阅者首连，then 收到 3 条、
  `seq` 为 1/2/3 且**跨 job 单调**
- Given 订阅者带着 `last_event_id=1` 重连，when 缓冲仍含 2/3，then 只收到 2/3
- Given 游标已淘汰，when 升级，then 收 `resync_required` 且连接关闭（1008）
- Given `notification_hub=None`，when 连接该路径，then 403（路由未注册）
- Given `cancel` / `run` 命令，when 发送，then 收 `invalid_request` 帧且连接**仍可用**（随后 `ping` 有 ack）
- Given 队列被灌满，when 背压触发，then 订阅被踢、warning 一次、hub 的 `subscriber_count` 减一
- Given `close()` 后新连接，when 升级，then `shutting_down` + 1001
- Given 全量 `pytest`，then 全绿且 `test_cli_event_hub.py` / `test_cli_ws_e2e.py` /
  `test_cli_ws_publish.py` / `test_cli_ws_wiring.py` **文件内容零改动**
- Given `pytest tests/test_architecture_contracts.py -q`，then 全绿（含两条端点集判据的新期望值）

## Verification

**Commands（实现后逐条实跑并回填实测数字；未跑不得填）:**
- `pytest tests/network/test_event_stream_hub.py tests/network/test_notification_hub.py -q`
- `pytest tests/network/test_cli_event_hub.py tests/network/test_cli_ws_e2e.py tests/network/test_ws_server.py tests/network/test_ws_e2e.py -q`
- `pytest tests/test_architecture_contracts.py -q`
- `pytest -q`
- `ruff check src tests && ruff format --check src tests && mypy src && bandit -r src/ -ll`

**基线（2026-10-28 实测，改动前）:**
- `test_cli_event_hub.py` 15 例 / `test_cli_ws_e2e.py` 13 例 / `test_cli_ws_publish.py` 8 例 /
  `test_cli_ws_wiring.py` 5 例 / `test_ws_server.py` 39 例 / `test_ws_e2e.py` 24 例 /
  `test_ws_protocol.py` 14 例（`grep -c 'def test_'` 口径）
- 取证 venv：`.heagent/tmp/py311-venv-linux`（python 3.11.17 + pytest 9.1.1 + websockets 17.3）

**实测结果（2026-10-28，容器沙箱 + `.heagent/tmp/py311-venv-linux`）:**
- `pytest tests/network -q` → **480 passed**（32.90s）
- `pytest tests/test_architecture_contracts.py -q` → **37 passed**（36 + 新增 1 条通知流可见性判据）
- `pytest -q`（全量）→ **4067 passed, 50 skipped, 25 deselected**（341.83s）
- `scripts/quality_gate.py` → 前两门绿（goal 冒烟 + 回归/覆盖率：**92.38%** ≥ 87%，4067 passed）；
  第三门 `ruff lint` 报 `[Errno 2] No such file or directory: 'ruff'`（容器 PATH 里没有 bare `ruff`，
  环境产物而非代码问题，见 Implementation Notes 第 4 条）
- `python -m ruff check src tests scripts` → All checks passed
- `python -m ruff format --check src tests scripts` → 364 files already formatted
- `python -m mypy src` → 176 source files, no issues
- `python -m bandit -r src/ -ll` → Medium 0 / High 0
- **零改动证明**：`git status --porcelain` 里没有 `tests/network/test_cli_event_hub.py` /
  `test_cli_ws_e2e.py` / `tests/test_cli_ws_publish.py` / `tests/test_cli_ws_wiring.py`
  ——41 例既有判据文件内容逐字未改，仍全绿（D3 的硬约束达成）

## Spec Change Log

<!-- Append-only. -->

## Implementation Notes

<!-- Agent-owned. Append-only during implementation. -->

- 2026-10-28 实施完成（代码未提交）。落点：新增 `network/event_stream_hub.py`(251) /
  `network/notification_hub.py`(79)，`cli_event_hub.py` 由 272 行缩到 148 行薄适配；
  `ws_server.py` 增 3 个通知流函数（send / commands / endpoint）。
- **重构等价性怎么保证的**：先跑基线（`test_cli_event_hub.py` 15 / `test_cli_ws_e2e.py` 13 /
  `test_cli_ws_publish.py` 8 / `test_cli_ws_wiring.py` 5 = 41 例）确认绿，再改实现、再复跑同一批
  且**不修改这 4 个文件**。`git status` 无这 4 个文件即证据。
- 一处**刻意的行为细节变化**（已评估，影响为零）：订阅队列上界从模块常量 256 改为
  `buffer_size`（通用核只有这一个窗口参数）。默认 `buffer_size=256` 时逐字等价；既有测试传小
  窗口（3 / 8）时队列随之变小，但它们都在「订阅后才灌满」的路径之外，41 例全绿即判据。
- `scripts/quality_gate.py` 直接调 bare `ruff` / `mypy`（`subprocess` 取 PATH），容器里这两个
  可执行文件只在 `.heagent/tmp/py311-venv-linux/bin`。本轮改用 `python -m ruff` / `-m mypy` 复跑
  同一批参数全绿；**这是取证环境的 PATH 问题，不是仓库缺陷**（宿主 Windows 上 bare 命令可用）。
- `docs/frame.md` 顺带修正一处既有文档漂移：4.17.1.1 的判据行此前引用 `test_http_cli_ws.py`(9) /
  `test_http_ws_config.py`，两个文件早已不存在（Epic 56 期一迁入 WS server 时更名）——改成实际的
  4 个文件与例数。

## Review Triage Log

<!-- 三层自审（blind-hunter / edge-case-hunter / verification-gap）逐层执行后追加。 -->

| # | 发现 | 判定 | 证据 / 路由 |
|---|---|---|---|
| 1 | 通用核把订阅队列上界绑到 `buffer_size`，与 CLI 原来固定的 256 不等价（小窗口调用方队列变小） | low（接受，已记录） | 默认路径逐字等价；41 例零改动全绿；语义上「队列=一个窗口」比「队列恒 256」更自洽（见 Implementation Notes 第 3 条） |
| 2 | 通知端点注册在**所有** listener（含对外），旁路的 D9 判据会不会被顺手放宽？ | false（驳回） | `test_notification_stream_is_registered_on_every_listener_but_never_carries_the_terminal_bypass` 同时钉住两件事：对外/只读 listener 的路由集**不含** `/api/cli/ws`，而含通知流 |
| 3 | `_emit` 的 `build` 抛异常时 seq 不前进——若实现写错会让游标出现空洞导致客户端误判 resync | 已覆盖 | `test_a_failed_build_does_not_consume_a_seq` 直接钉住 |
| 4 | 关停时单条坏 socket 会不会拖住整批收尾？ | 已覆盖 | `test_a_socket_that_raises_does_not_block_the_others` |
| 5 | 客户端能否把 cron 通知误当成「一条可订阅/可取消的 run」？ | 已消除 | 帧模型分离（`WsNotificationFrame` vs `WsEventFrame`）、载荷无 `run_id` / 无 `RunStatus`、`cancel` 明确回 `invalid_request` 并给出 `read-only` 文案 |
| 6 | `notification_hub` 未注入时客户端拿到 403 而不是 404，文档/测试口径容易写错 | 已覆盖 | `test_notification_ws_route_does_not_exist_without_a_hub` + 契约测试的「中枢缺席」分支 |
