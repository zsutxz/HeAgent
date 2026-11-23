---
ticket: 2
ref: 74.2
code: E74-S02
epic: epic-74-ws-frame-contract
status: done
baseline_revision: d6e705de2f05274e051cfa6d22c7fe2b233d53be
risk: medium
hitl: false
covers: ["R2", "R3"]
---

# E74-S02 · 项目通道端口与带项目提交的端点转译

## Tasks & Acceptance

- [x] `network/ws_server.py`：`_submit_run` 增加**仅关键字**参数 `project_id: str | None = None` 与 `project_service: ProjectChannelService | None = None`；不带 `project_id` 的旧分支逐字不动（仍 `service.start_run` + `WsAckFrame`）。
- [x] `_submit_run` 内的 `RunRequest` 校验两条路径共用：带 `project_id` 时同样先过 `RunRequest`，空 prompt 仍回 `empty_prompt` / 非法结构仍回 `invalid_request`。
- [x] 新增 `_start_project_run(websocket, project_service, project_id, prompt)`：`project_service is None` 的**唯一**护栏（`invalid_request` + `"project addressing is not available on this listener"`，逐字沿用 74.1），否则先 `await ensure_available(project_id)`（用其返回值作为下一步的 id）再 `await start_project_run(resolved, prompt)`。
- [x] 项目分支的 `HttpRunConflictError` 由 `_submit_run` 既有 `except` 捕获：`exc.code` 逐字落进错误帧、不 close 连接、不产生任何副作用。
- [x] `_handle_submit_commands` 删掉 74.1 放在循环里的第二道判定（与 helper 顶部重复），改为无条件转发 `project_id=frame.project_id, project_service=project_service`——护栏只留一处。
- [x] 新增 `tests/network/test_ws_project_submit.py`（5 例，全部经 `build_runs_collection_endpoint` 走真实端点）。

验收（对应 entry 的 `verify`）：
- 无 `project_id`：项目端口 `start_project_run` 0 次、`ensure_available` 0 次，`HttpRunService.start_run` 1 次，ack 来自 run 记录。
- 带 `project_id`：共享调用表恰为 `["ensure_available:p1234abcd", "start_project_run:p1234abcd"]`（次序可判），ack 来自 `SubmittedRun`，且 `"session_id" not in SubmittedRun.model_fields`。
- `ensure_available` 抛 `unknown_project`：错误帧 code 即该字面值，两个启动路径均 0 次，连接后续仍能处理下一帧（`ping` 拿到 ack）且未被 close。
- `start_project_run` 抛 `run_conflict`：错误帧 code 即该字面值，`start_run` 仍 0 次（半途失败不改走启动工作区）。
- `inspect.signature` 断言 `ProjectChannelService` 两方法参数名集合恰为 `{project_id, prompt}` / `{project_id}`。

## Verification

| 命令 | 结果 |
|---|---|
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network/test_ws_project_submit.py tests/network/test_ws_command_fields.py -q` | **10 passed**（新 5 例 + 74.1 的既有 5 例全绿） |
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network tests/test_architecture_contracts.py -q` | **668 passed, 1 warning** |
| `.heagent/tmp/py311-venv-linux/bin/ruff check src tests` | All checks passed |
| `.heagent/tmp/py311-venv-linux/bin/ruff format --check src tests` | 495 files already formatted |
| `.heagent/tmp/py311-venv-linux/bin/python -m mypy src` | Success: no issues found in 238 source files |
| `wc -l src/heagent/network/ws_server.py` | 988（≤ 1000 的单文件上限，余量 12 行） |

## Code Map

- `src/heagent/network/ws_server.py` —— `_start_project_run()`（新，护栏 + `ensure_available` → `start_project_run`）/ `_submit_run(..., *, project_id=None, project_service=None)`（旧分支原样 + 项目分支）/ `_handle_submit_commands()`（护栏搬走后只做转发）。
- `tests/network/test_ws_project_submit.py` —— 5 例：旧路径零触达 / 次序与 `SubmittedRun` 形状 / 前置校验失败 / 提交失败 / 端口签名。

## Design Notes

- **护栏单处**：74.1 把「未装配却带 `project_id`」的判定放在命令循环里；74.2 一旦把项目提交搬进 `_submit_run`，循环里那道判定就成了不可达的第二份真源（helper 也必须自己判，否则 `project_service=None` 会在 `ensure_available` 处 `AttributeError`）。故搬进 `_start_project_run` 顶部，message 与 code 逐字不变——74.1 的既有 5 例就是这个搬动的判据（它们仍全绿）。
- **`ensure_available` 的返回值才往下传**：端口签名让它返回 `str`，含义是「校验并归一后的 id」。丢掉返回值另存 `project_id` 会让将来适配器做的归一在传输层被静默弃用。
- **helper 返回 `SubmittedRun | None`**：`None` 只表示「已发过错误帧」，调用方据此跳过 ack。相比让 helper 自己发 ack，这样做把「成功回帧」的唯一出口留在 `_submit_run`，两条分支的 ack 形状自然一致。
- **`record is None` 判定放在 `except` 之后**：`HttpRunConflictError` 的两条来源（`ensure_available` / `start_project_run`）都落在同一个 `except`，错误码透传逻辑只有一份，没有第二条 `try`。
- **行数余量告警**：`ws_server.py` 现 988 行（上限 1000）。E75 若需要继续在本文件加代码（如 `list_projects` 相关端点逻辑），必须先拆模块而不是硬塞——这条留给 E75 的 entry 处理，本 entry 不动结构。

## Plan Change Log

- 2026-11-23：实现子会话在 26 次迭代处超限退出（未回报），留下 `ws_server.py` 的完整改动与 `tests/network/test_ws_project_submit.py` 全文（工作树可验收半成品）。宿主接手按 `## Verification` 逐条实测（含 74.1 既有 5 例回归）、核对 `verify` 的四个判据与 `wc -l` 行数上限后落盘本 plan。
