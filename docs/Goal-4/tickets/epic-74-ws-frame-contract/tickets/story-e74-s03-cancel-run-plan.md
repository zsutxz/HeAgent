---
ticket: 3
ref: 74.3
code: E74-S03
epic: epic-74-ws-frame-contract
status: built
baseline_revision: eeb7fee9a0c25b3965686085b0c7ca34ca5fe3f1
risk: medium
hitl: false
covers: ["R5"]
---

# E74-S03 · cancel_run 帧与只读口径

## Tasks & Acceptance

- [x] `network/ws_protocol.py`：`WsCommand` 增 `CANCEL_RUN = "cancel_run"`；`_FRAME_FIELDS` 增 `{command, run_id}`；`WsCommandFrame` 增 `run_id: str | None = Field(default=None, min_length=1, max_length=64)`（**不进** `_OPTIONAL_FRAME_FIELDS` ⇒ 对 `cancel_run` 必带，对 `run` / `cancel` / `ping` 一律 `malformed`）。
- [x] **模块拆分（单文件上限倒逼）**：`ws_server.py` 拆前 988 行、距 1000 行硬上限只剩 12 行，故本 entry 先拆再改：
  - 四个端口契约（`WebSocketLike` / `RunWebSocketService` / `SubmittedRun` / `ProjectChannelService`）迁入 `network/ws_protocol.py`（同属「传输层纯契约，不执行 I/O」），并由 `ws_server.__all__` 继续导出，对外可用名不减；
  - 新建 `network/ws_commands.py`，原样搬入 `_send_error_frame` / `_send_error` / `_next_command` / `_handle_commands` / `_is_blank_prompt` / `_start_project_run` / `_submit_run` / `_handle_submit_commands`；
  - 依赖方向单向 `ws_server → ws_commands → ws_protocol`，无反向导入、无 `network/http_server` 引用。
- [x] 单 run 端点命令循环（`_handle_commands`）：`cancel_run` 与 `cancel` 共用同一个 `service.cancel_run(run_id)` 端口；`readonly=True` 回 `invalid_request` 且不断连；`frame.run_id != 绑定 run` 回 `invalid_request` 且不断连；相等时取消并以 `WsAckFrame(command=CANCEL_RUN, run_id=绑定 run, status=记录 status)` 回终态（已终止经 `HttpRunService.cancel_run` 幂等返回）。
- [x] 集合级端点命令循环（`_handle_submit_commands`）：`cancel_run` 按 `frame.run_id` 调同一个端口；`record is None` ⇒ `unknown_run` 错误帧 + `continue`（**不断连**）；否则 ack 用帧里的 `run_id` 与记录 `status`。既有 `cancel`（显式不支持）与 `ping` 分支逐字不动。
- [x] CLI 旁路与通知流：`cancel_run` 与 `cancel` 同档拒绝（旁路 = 终端才拥有运行；通知流 = 无可取消对象），文案沿用各自既有句。
- [x] 新增 `tests/network/test_ws_cancel_run.py`（6 例）；`tests/network/test_ws_protocol.py` 增 3 例帧面判据（含参数化 9 组 `run_id` 排他性）；`tests/test_architecture_contracts.py` 的封闭命令集断言扩为含 `cancel_run`。

验收（对应 entry 的 `verify`）：
- 集合级 `cancel_run` 只动目标 run：目标 `cancelled`、同服务里另一 run 仍 `running`、调用表恰 `["run-a"]`。
- 已终止 run 再取消 ⇒ ack 带终态 `status=cancelled`，连接未关。
- 未知 id ⇒ 错误帧 `code=unknown_run`，随后 `ping` 仍拿到 ack（连接活着）。
- 单 run 端点 `run_id` ≠ 绑定 ⇒ `invalid_request`、`cancel_run` 调用 0 次、下一条 `ping` 仍 ack。
- `readonly=True` ⇒ `invalid_request`、调用 0 次、目标仍 `running`、连接未关。
- 帧面：缺 `run_id` / `run_id=null` / 空串 / 超 64 字符 / 带 `project_id` / 未知键 / `cancel`·`ping`·`run` 带 `run_id` 全 `malformed`；超 `WS_MAX_COMMAND_CHARS` ⇒ `too_large`。

## Verification

| 命令 | 结果 |
|---|---|
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network/test_ws_cancel_run.py tests/network/test_ws_protocol.py -q` | **38 passed**（新 6 例 + 协议面 32 例，含 3 组新判据） |
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network tests/test_architecture_contracts.py -q` | **685 passed, 1 warning** |
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/test_cli_http.py tests/test_cli_http_lifecycle.py tests/test_http_web_ui.py -q` | **171 passed, 34 skipped**（skip 为本机无 node 的前端探针） |
| `.heagent/tmp/py311-venv-linux/bin/ruff check src tests` | All checks passed |
| `.heagent/tmp/py311-venv-linux/bin/ruff format --check src tests` | 497 files already formatted |
| `.heagent/tmp/py311-venv-linux/bin/python -m mypy src` | Success: no issues found in 239 source files |
| `.heagent/tmp/py311-venv-linux/bin/bandit -r src/ -ll` | No issues identified（exit 0） |
| `wc -l src/heagent/network/{ws_server,ws_commands,ws_protocol}.py` | 698 / 253 / 425（全部 ≤ 1000） |

## Code Map

- `src/heagent/network/ws_protocol.py` —— 帧模型 + 命令白名单 + 四个注入端口契约（`WebSocketLike` / `RunWebSocketService` / `SubmittedRun` / `ProjectChannelService`）。
- `src/heagent/network/ws_commands.py`（新）—— 命令循环簇：`_next_command`（四条 listener 共用前导）、`_handle_commands`（单 run：cancel / cancel_run / ping + 只读口径）、`_handle_submit_commands`（集合级：run / cancel_run / cancel 拒绝 / ping）、`_submit_run` / `_start_project_run` / `_is_blank_prompt`（74.2 的提交分支原样）。
- `src/heagent/network/ws_server.py` —— 端点装配与会话骨架（`_ws_session` / `_supervise` / 订阅 / CLI 旁路 / 通知流），从 `ws_commands` 导入命令循环与错误帧发送。
- `tests/network/test_ws_cancel_run.py`（新）—— 集合级 3 例 + 单 run 2 例 + 同源 1 例。
- `tests/network/test_ws_protocol.py` —— `cancel_run` 帧形状、`run_id` 排他性、字符上限三档。
- `tests/test_architecture_contracts.py` —— 封闭命令集断言扩为 `{run, cancel, cancel_run, ping}`。

## Design Notes

- **`run_id` 不进 `_OPTIONAL_FRAME_FIELDS`**：那张表是「允许缺席」的全局集合，`run_id` 只对 `cancel_run` 必带——它的必带性由 `_FRAME_FIELDS[CANCEL_RUN]` 减去全局可选集自然推出，因此不需要第二张表，也没有「命令级必带表」的漂移余地。
- **取消实现仍只有一份**：`cancel_run` 与 `cancel` 都调 `service.cancel_run(run_id)`，差别仅在目标来源（帧字段 vs 连接绑定）。集合级端点的 `cancel` 仍显式拒绝（没有绑定就没有默认目标），`cancel_run` 才是无绑定连接的取消形态——三条命令的语义边界因此可读。
- **「不断连」是刻意的分层**：错误帧只否定这一帧的请求（未知 id / 目标不符 / 只读），不否定这条连接。只有 `unknown_run` 在**单 run 端点**上沿既有 `_send_error(close_code=POLICY)` 处置（那条连接的唯一目标都不存在，继续留着没有意义）——与集合级端点的 `unknown_run` 不断连是刻意的差异，不是漏改。
- **拆分是硬约束倒逼，不是重构偏好**：`ws_server.py` 拆前 988 行，本 entry 至少要加 40+ 行命令分支，不拆必然越 1000 行上限。拆法取「命令循环簇下移」而不是「端点再拆一层」：`ws_server` 仍需 `_send_error` / 命令循环，搬到同层新模块后依赖方向仍单向，且 `ws_server.__all__` 与既有 `from heagent.network.ws_server import ...` 的对外名一个不少（`WebSocketLike` 等四个名字改为从 `ws_protocol` 导入后继续导出）。
- **write_set 扩展登记**：entry 的 `write_set` 只列了 4 条，实际另需 2 条——`src/heagent/network/ws_commands.py`（拆分产物）与 `tests/test_architecture_contracts.py`（封闭命令集断言必须随新命令同步，否则该断言永远红）。两条都是不可回避的必要扩展；本 entry 串行执行（无 `parallel_group`），不参与并行批，因此不存在写集相交风险。

## Plan Change Log

- 2026-11-23：实现子会话在 25 次迭代处超限退出（未回报），留下完整模块拆分（`ws_commands.py` 新建、协议契约迁入 `ws_protocol.py`、两个命令循环的 `cancel_run` 分支）与 `ws_protocol.py` 的帧字段改动，但**未写任何测试、未落 plan**。宿主接手：补 `tests/network/test_ws_cancel_run.py`（6 例）、`test_ws_protocol.py` 的 3 组帧面判据与 `typing` 导入白名单、`tests/test_architecture_contracts.py` 的封闭命令集断言，逐条实测后落盘本 plan。
