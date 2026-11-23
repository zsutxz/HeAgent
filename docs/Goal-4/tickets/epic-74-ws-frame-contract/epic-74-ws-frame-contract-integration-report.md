---
type: integration-report
code: E74-INT
epic: epic-74-ws-frame-contract
generated_at: 2026-11-23
step: step-08-system-integration-test
head: f42ab032
---

# E74 集成报告 · WS 帧契约（Step 08）

## 集成场景（跨 story）

| # | 场景目标 | 验证的 Done when / 不变量 | 判据命令 | 观察结果 |
|---|---|---|---|---|
| 1 | 缺省提交逐字不变：`run` 帧不带 `project_id` 仍走启动工作区 | Done when 1 + AD-2 I6 | `pytest tests/network/test_ws_project_submit.py -q` | passed（含 `test_submit_without_project_id_keeps_the_startup_workspace_path`） |
| 2 | `project_id` 解析语义：不 strip / 空串·超长·未知键 ⇒ `malformed` | R1 + AD-4 | `pytest tests/network/test_ws_command_fields.py tests/network/test_ws_protocol.py -q` | passed（含本轮新增的 1–16 界值三例） |
| 3 | 白名单单调：`set(_FRAME_FIELDS) == set(WsCommand)` | AD-4 不变量 | 同上 | passed |
| 4 | 端口形状无语义泄漏（只有不透明 id 与 prompt） | AD-1 I5 | `pytest tests/network/test_ws_project_submit.py -q` | passed |
| 5 | 未装配项目通道不静默降级：带 `project_id` ⇒ `invalid_request` 且 `start_run` 0 次 | R2 + §5 末条 | `pytest tests/network/test_ws_command_fields.py -q` | passed |
| 6 | 提交次序与零副作用：先 `ensure_available` 后 `start_project_run` | R3 | `pytest tests/network/test_ws_project_submit.py -q` | passed |
| 7 | 取消只作用于目标 run（另一 run 活到终态） | R5 + Done when 3 | `pytest tests/network/test_ws_cancel_run.py -q` | passed |
| 8 | 取消的权限/幂等/未知 id 口径 | R5 + §5 | 同上 | passed |
| 9 | 事件面零漂移：golden 信封逐字相等 + 帧类型封闭集 | R6 + AD-3 | `pytest tests/network/test_ws_event_contract.py -q` | passed |
| 10 | 码面不新增 + 已登记 + 依赖边界（`network/` 不导入运行栈/配置） | R4 / R7 + Done when 5 | `pytest tests/network/test_ws_error_codes.py tests/test_architecture_contracts.py -q` | passed |

- 场景 1–10 合并命令：`pytest tests/network/test_ws_event_contract.py tests/network/test_ws_error_codes.py tests/network/test_ws_protocol.py tests/test_architecture_contracts.py -q` = **116 passed in 12.44s**。

## 质量门禁

- 仓库一键门 `python scripts/quality_gate.py`：**all gates passed**（本 epic 场景在其中的 default regression 门内一次性跑过）。
- 契约快照 `python scripts/contract_snapshot.py --check`：五份 `[OK]`（`public` / `routes` / `exceptions` / `transport_errors` / `error_codes`）。
- `mkdocs build --strict`：0 warning。

## 系统集成结论

**通过**。E74 的五条 entry 在真实端点上互相咬合：帧面冻结（五命令 / 六帧类型）、`project_id` 解析语义、零副作用提交次序、取消的分层权限、码面与依赖边界全部有可复跑判据，无未决 Critical。
