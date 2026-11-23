---
ticket: 1
ref: 74.1
code: E74-S01
epic: epic-74-ws-frame-contract
status: done
baseline_revision: 7ba444cc80ee48713c9b1d3deb90d71fbd7ff2d5
risk: medium
hitl: false
covers: ["R1", "R2"]
---

# E74-S01 · 命令帧白名单单一映射表与可选 `project_id` 字段

## Tasks & Acceptance

- [x] `network/ws_protocol.py`：新增模块级 `_FRAME_FIELDS: dict[WsCommand, frozenset[str]]`（命令 → 允许出现的键）与 `_OPTIONAL_FRAME_FIELDS`（只有 `project_id`），派生 `required_frame_fields()` 与 `_unexpected_fields()`；`WsCommandFrame` 的校验器改名 `_validate_fields_per_command` 并改读该表；`parse_command_frame` 的 JSON 层字段判定改读同一张表。
- [x] `WsCommandFrame` 增加可选 `project_id: str | None = Field(default=None, min_length=1, max_length=16)`，**不做 strip**（注册表 id 是 `"p"+sha256[:8]` 或字面量 `"default"`，strip 会造出第二个合法拼写）。
- [x] `network/ws_server.py`：新增 `SubmittedRun`（`extra="forbid"`，`run_id` + `status`，**无 `session_id`**）与 `ProjectChannelService` Protocol（本 entry 只两方法：`start_project_run` / `ensure_available`；`list_projects` 由 75.3 追加）。
- [x] `build_runs_collection_endpoint` / `build_ws_endpoint` 各加关键字参数 `project_service: ProjectChannelService | None = None`（追加在既有参数之后，旧调用零改动）。
- [x] `_handle_submit_commands` 增加 `project_service` 参数：为 `None` 时带 `project_id` 的 `run` 帧回 `invalid_request`（`"project addressing is not available on this listener"`）且**不**调用 `service.start_run`；不带 `project_id` 的路径逐字不动。
- [x] 新增 `tests/network/test_ws_command_fields.py`（5 例）。

验收：`set(_FRAME_FIELDS) == set(WsCommand)`、`project_id` 原样保留、空串 `malformed`、未登记键仍 `malformed`、`project_service=None` 时回 `invalid_request` 且 `start_run` 零调用。

## Verification

| 命令 | 结果 |
|---|---|
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network/test_ws_command_fields.py tests/network/test_ws_protocol.py -q` | **26 passed**（新 5 例 + 既有 21 例） |
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network tests/test_architecture_contracts.py -q` | **658 passed**，无回归 |
| `.heagent/tmp/py311-venv-linux/bin/ruff check src tests` | All checks passed |
| `.heagent/tmp/py311-venv-linux/bin/ruff format --check src tests` | 494 files already formatted |
| `.heagent/tmp/py311-venv-linux/bin/python -m mypy src` | Success: no issues found in 238 source files |

## Code Map

- `src/heagent/network/ws_protocol.py` —— `_FRAME_FIELDS` / `_OPTIONAL_FRAME_FIELDS` / `required_frame_fields()` / `_unexpected_fields()` / `WsCommandFrame.project_id` / `WsCommandFrame._validate_fields_per_command()` / `parse_command_frame()`。
- `src/heagent/network/ws_server.py` —— `SubmittedRun` / `ProjectChannelService` / `_handle_submit_commands(project_service=...)` / 两个端点构造器的新关键字参数。
- `tests/network/test_ws_command_fields.py` —— 5 例（表覆盖 / 原样保留 / 空串 / 未知键 / 未装配护栏）。

## Design Notes

- **白名单单一真源**：`_FRAME_FIELDS` 一份表同时驱动「解析器 JSON 层」与「模型校验器」，避免二元 if/else 在新增命令时膨胀成四份手抄分支；`set(_FRAME_FIELDS) == set(WsCommand)` 是可执行判据。
- **可选字段单列**：`_OPTIONAL_FRAME_FIELDS` 只放 `project_id`，于是「必带」= 白名单 − 可选，不需要第二张「必带表」，也就没有两表漂移。
- **显式 null 与缺席同义**：模型校验用 `model_dump(exclude_none=True)`，`{"command":"run","prompt":null}` 按缺 prompt 处理。
- **`SubmittedRun` 无 `session_id`**：入口层的 `ProjectRunResponse` 带会话，帧面只需要客户端能操作的两项；收窄点放在端口契约上，任何实现方都无法顺手透传。
- **`None` 护栏而非默认回退**：静默按启动工作区执行会把「装配漏了」变成「跑错项目」，故显性 `invalid_request`。

## Plan Change Log

- 2026-11-23：实现子会话在 26 次迭代处超限退出，留下 `ws_protocol.py` / `ws_server.py` 的已落盘改动（工作树可验收半成品）。宿主接手补齐 `tests/network/test_ws_command_fields.py` 与 plan，并按 `## Verification` 逐条实测通过。
- 2026-11-23：修正测试替身类名（`_WebSocketDisconnect` → `WebSocketDisconnect`）——`_next_command` 按**类型名**判断开，带下划线的名字会被当异常上抛。
