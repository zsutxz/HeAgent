---
ticket: 2
ref: 75.2
code: E75-S02
epic: epic-75-project-channel-runtime
status: done
baseline_revision: 604b4fb4cfebc7a47f8cfe8a2d342c50dbbd1de4
risk: high
hitl: false
covers: ["R6", "R7"]
---

# E75-S02 · network 侧项目通道端口与 `project_id` 提交分支

本 entry 在 74.1（`ProjectChannelService` / `SubmittedRun` / `WsCommandFrame.project_id`）与 74.2
（`_start_project_run` + `_submit_run(project_id=...)`）的地基上，补齐 R6 里**尚不存在**的那条
命令（`projects`），并把 R7 的码表覆盖、I9 的 ack 出站键集补成可执行判据。适配器实现与装配
（75.3 列表投影、75.5 注入）不在本 entry。

## Tasks & Acceptance

### 三段对账表（票面条目 → 现状）

| 票面要求 | 现状 | 落点 / 判据 |
|---|---|---|
| `_submit_run` 新增 `project_id` 分支：先 `ensure_available` 再 `start_project_run`，成功回 ack | **已由 74.2 交付** | `ws_commands._start_project_run` + `_submit_run`；`test_submit_with_project_id_calls_ensure_then_start_in_order` |
| `HttpRunConflictError.code` 逐字透传、连接不断 | **已由 74.2 交付**，本轮补 R7 码表覆盖 | `test_every_project_side_code_passes_through_both_phases_verbatim`（2 阶段 × 7 码 = 14 例） |
| 缺省 `project_id` 路径（`service.start_run(prompt)`）逐字不动（I6） | **已由 74.2 交付** | `test_submit_without_project_id_keeps_the_startup_workspace_path`（`start_run` 1 次 / 项目端口 0 次） |
| 带 `project_id` ⇒ console 1 次且 `ProjectRunRequest.session_id is None`（I9） | **部分已交付**；本轮补 ack 键集判据 | 出站键集：`test_project_ack_carries_exactly_the_four_ack_keys`；`session_id` 不在端口：`test_submit_with_project_id_…` 的 `"session_id" not in SubmittedRun.model_fields` |
| `inspect.signature` 参数名集合断言（I5） | **已由 74.2 交付**，本轮扩到新端口 | `test_project_channel_port_takes_only_opaque_id_and_prompt` + `test_projects_port_takes_no_arguments` |
| `project_service is None` 时 `run`（带 id）回 `invalid_request`，不静默按 default | **已由 74.1 交付** | `test_ws_command_fields.py::test_project_id_without_project_service_is_rejected_without_starting_run` |
| `project_service is None` 时 **`projects`** 回 `invalid_request`（R6） | **本轮补**（命令此前不存在） | `ws_protocol.WsCommand.PROJECTS` + `ws_commands._send_projects_frame` 护栏；`test_projects_without_project_service_is_rejected_and_keeps_the_connection` |
| `project_service is None` 时 **`cancel_run`** 回 `invalid_request`（R6） | **本轮按裁定不实现（`bad_spec`）** | 见 `## Design Notes` 的 bad_spec 记录；实现保持 74.3 行为 |
| `HttpRunConflictError(code="project_busy")` 原样出现在错误帧 | **已由 74.2 交付**，本轮纳入参数化 | 14 例参数化含 `project_busy` |
| `grep -rn "is_dir" src/heagent/network/` 0 命中 | **成立**（本轮新增代码也不碰盘） | 实测 0 行 |

### 本轮新增的验收点

- [x] `WsCommand` 加 `PROJECTS = "projects"`，`_FRAME_FIELDS` 单一映射表登记 `{command}`（只允许
      `command`；带 `project_id` 即 `malformed`）。
- [x] 新增 `WsFrameType.PROJECTS` 帧类型与两个响应模型：`ProjectChannelEntry`
      （恰 `id` / `name` / `available`，`extra="forbid"`）与 `WsProjectsFrame`
      （`type` / `projects` / `registry_state ∈ {ok, unreadable}`，`extra="forbid"`）。
- [x] `ProjectChannelService` 增 `async def list_projects(self) -> WsProjectsFrame`；`__all__` 补两个名字。
- [x] 集合级端点加 `projects` 分支：装配时把帧发出，未装配时 `invalid_request` 且**不断连**；
      端口抛 `HttpRunConflictError` 时 `code` 逐字透传。
- [x] 单 run 端点 / CLI 旁路 / 通知流对 `projects` 一律 `invalid_request`（各用既有句式，不断连），
      不再落进「ping ⇒ ack」的兜底分支。
- [x] `ProjectChannelService` docstring 补**三条实现方义务**（超时是实现方义务 / 提交失败不做
      原子性保证、无幂等键 / 错误消息不含路径），并配一条可 grep 的判据
      （`test_project_channel_port_documents_its_three_obligations`，同时断言签名里没有 `timeout`）。
- [x] 同步三处因命令面扩张而转红的封闭集守卫：`test_architecture_contracts.py`（命令集 4 → 5）、
      `test_ws_event_contract.py`（帧类型 5 → 6 与命令集）。
- [x] 新增 `tests/network/test_ws_project_commands.py`（10 例）+ 扩写
      `tests/network/test_ws_project_submit.py`（6 → 23 例，+17）。

## Design Notes

### 本文件的沿革

本文件此前以 `status: blocked` 落盘（结论：本 entry 的代码交付已由 74.2 完成、残余项落在原`write_set` 之外）。宿主本轮裁定**收窄为「把 `projects` 命令接进网络侧」重跑**，`write_set` 同时扩到 `ws_protocol.py` / `ws_commands.py` / 两个 WS 守卫测试，因此文件按新口径重写；`cancel_run` 子句按裁定不实现（见下方 `bad_spec`）。

### 为什么新增 `WsFrameType.PROJECTS` 而不是借道 `event`

事件面被两条逐字节判据钉死：`WsEventFrame` 字段集合恰 `{type, event}` 与 golden 信封逐字相等。
项目列表既不是 run 事件、也没有 `run_id` / `seq`，塞进 `event` 会同时破坏这两条（客户端按字节
兼容）。新增一档的代价只是客户端多认一个可跳过的类型；`notification` 已是同档先例（一问一答的
非流式结果）。因此 `test_frame_type_set_stays_closed` 从「五档」改为「六档」，并保留它真正的
判据价值：帧类型集合仍然**封闭**，多一档必须走 review 并同步这条断言。

### 为什么端口返回 `WsProjectsFrame` 而不是 `(entries, registry_state)` 元组

返回值选帧模型：`pub.projects` 的 `ProjectEntry` / `ProjectRegistryHealth` → 帧模型的翻译因此全部
留在实现方（入口层适配器），网络层既不 import 注册表（`tests/test_architecture_contracts.py` 明令
禁止）、也不持有第二份投影逻辑。返回元组会把「组装帧」这半步留在 `ws_commands`，与 75.3 的项目
投影职责一分为二。

### `registry_state` 为什么是两值，而不是注册表不可读时回错误帧

注册表读不出来时客户端能做的只有一件事：提示「项目列表可能不完整、显示为禁用」。此时把
`projects` 当空表/部分表发出去并显式给出 `unreadable`，比回一条错误帧更有用（客户端仍能操作
`default`）。两值刻意不复用 HTTP 的细分码（`project_registry_unreadable` 等）——细化归错误面，
帧面只需要「完整 / 不完整」。

### 未装配为什么回 `invalid_request` 而不是空表

`project_service is None` 时回一张空列表，客户端会读成「这个服务上一个项目都没有」；回
`invalid_request` 才是「这条 listener 不提供项目寻址」。与带 `project_id` 的提交同一个护栏口径
（`_start_project_run` 的那条），两处文案逐字相同。

### `bad_spec` 记录：R6 的 `cancel_run` 子句

- **触发发现**：实现 R6 的「`project_service is None` 时拒绝」分支时，逐条核对三个命令的语义，
  发现 `cancel_run` 与项目寻址**毫无关系**。
- **应改的规格条目**：R6 的「`project_service is None` 时 `run`（带 id）/ `projects` / `cancel_run`
  回 `invalid_request`」——第三个子句过宽。
- **避免的已知坏态**：`cancel_run` 在 74.3 已定为「按帧里的 `run_id` 取消，与 `cancel` 同源
  （同一个 `service.cancel_run` 端口）」，它不需要项目寻址。若按票面拒它，那么在
  `project_service=None` 的 listener（即 75.5 装配之前的**全部** listener）上，取消能力会被
  装配状态连坐打断——单 run 端点与集合级端点永久失去 `cancel_run`，而这两条路径本来与项目无关。
- **KEEP 指令**：实现保持 74.3 行为（`project_service` 不参与 `cancel_run` 的任何判定）；**不回改
  epic Requirements**，本记录即裁定载体；`projects` 子句照票面实现。

### 四端点的拒绝落点

| 端点 | 落点 | 形态 |
|---|---|---|
| 集合级 `/api/runs/ws` | `ws_commands._handle_submit_commands` | 装配则回 `projects` 帧，否则 `invalid_request` |
| 单 run `/api/runs/{run_id}/ws` | `ws_commands._handle_commands` | `invalid_request`，与 `run` 分支并列 |
| CLI 旁路 `/api/cli/ws` | `ws_server._cli_handle_commands` | `invalid_request` |
| 通知流 `/api/notifications/ws` | `ws_server._notification_handle_commands` | `invalid_request` |

四处都**不关闭**连接：错的是这一帧的命令，不是这条连接。

## Code Map

| 文件 | 改动 |
|---|---|
| `src/heagent/network/ws_protocol.py` | `WsFrameType.PROJECTS`；`WsCommand.PROJECTS` + `_FRAME_FIELDS` 登记；`ProjectChannelEntry` / `WsProjectsFrame` 两个模型；`ProjectChannelService.list_projects()`；`ProjectChannelService` docstring 补三条实现方义务；`__all__` 补两名字；`parse_command_frame` 与 `WsCommandFrame` 注释同步 |
| `src/heagent/network/ws_commands.py` | 新增 `_send_projects_frame()`（未装配护栏 + 码透传）；`_handle_submit_commands` 加 `projects` 分派；`_handle_commands` 加 `projects` 拒绝分支 |
| `src/heagent/network/ws_server.py` | `_cli_handle_commands` / `_notification_handle_commands` 各加 `projects` 拒绝分支（否则会落进 ping 兜底回 ack） |
| `tests/network/test_ws_project_submit.py` | 补 I9（ack 键集）与 R7（2 阶段 × 7 码参数化 + `project_unavailable` 专项 + 码表自身守卫） |
| `tests/network/test_ws_project_commands.py` | **新建**（10 例）：`projects` 四端点行为、端口异常透传、命令帧与响应帧封闭性、端口签名 |
| `tests/test_architecture_contracts.py` | 封闭命令集 4 → 5 值（含注释口径） |
| `tests/network/test_ws_event_contract.py` | 帧类型封闭集 5 → 6 值、命令集补 `projects`、docstring 口径改为「事件面不变、新增响应帧」 |

## Verification

| 命令 | 结果 |
|---|---|
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network -q -k "ws_project_submit or ws_server"` | **62 passed, 644 deselected**（5.79s） |
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network -q` | **706 passed, 1 warning**（24.33s；唯一 warning 是 starlette TestClient 的 `BlockingPortal` DeprecationWarning） |
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network/test_ws_project_commands.py tests/network/test_ws_project_submit.py -q` | **33 passed**（1.69s；10 + 23） |
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/test_architecture_contracts.py -q` | **40 passed**（15.70s） |
| `.heagent/tmp/py311-venv-linux/bin/python -m ruff check src tests` | All checks passed! |
| `.heagent/tmp/py311-venv-linux/bin/python -m ruff format --check src tests` | 501 files already formatted |
| `.heagent/tmp/py311-venv-linux/bin/python -m mypy src` | Success: no issues found in 239 source files |
| `grep -rn "is_dir" src/heagent/network/` | **0 行**（网络层仍不碰盘；项目可用性由实现方投影成 `available`） |
| `grep -rn "heagent.pub.projects\|heagent.config\|from heagent.agent\|heagent.engine" src/heagent/network/*.py` | 4 命中，**全部是 `http_console_protocol.py` 的注释/docstring**（既有，非 import） |
| `wc -l`（改动文件） | `ws_protocol.py` 486 / `ws_commands.py` 295 / `ws_server.py` 715 / 两个测试文件 392 + 338（单文件 ≤1000 全部达标） |

### 已知红（本 entry 之外，非本轮可修）

- `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/test_contract_baselines.py -q` ⇒
  **2 failed**（`test_snapshot_check_passes` / `test_snapshot_check_is_idempotent`），
  `scripts/contract_snapshot.py --check` 报
  `[FAIL] exceptions (exception_types.json): 首个差异 @ .classes[129].bases[0]: 'Protocol' != 'BaseModel'`。
- 用 `collect_exceptions()` 对拍确认漂移**只有**新增的两条，无增删改其它项：
  - added = `[("heagent.network.ws_protocol", "ProjectChannelEntry"), ("heagent.network.ws_protocol", "WsProjectsFrame")]`
  - removed = `[]` / changed = `[]` / `http_error_codes` 逐字不变。
- 处置：需 `python scripts/contract_snapshot.py --write --only exceptions` 重生成
  `tests/fixtures/contract_baselines/exception_types.json`。该文件不在本 entry 的 write_set（且工作树里
  已有 75.1 的同文件未提交改动），因此**未动**，留 orchestrator 在两条 lane 合流后一次重生成。

## Gaps

1. 契约基线 `exception_types.json` 待重生成（见上，精确 delta 已列出）。
2. 列表投影（`ProjectEntry` → `ProjectChannelEntry`、`ProjectRegistryHealth` → `registry_state`）属 75.3；
   本轮端口只声明「实现方返回已投影帧」。
3. 装配注入（`build_runs_collection_endpoint(project_service=…)` 的真实实现）属 75.5；本轮所有
   `projects` 用例都用替身端口。
4. R6 的 `cancel_run` 子句按 `bad_spec` 裁定未实现（记录在 Design Notes）。

## 宿主复核（2026-11-23，批末串行门禁）

- 上一轮并行批中本 entry 的产物被同批另一条 lane 的整文件写覆盖（工作树零残留），本轮按串行重跑并落盘；**E75 的并行授权自此撤销**（越集写），余下 entry 一律串行。
- `pytest tests/network -q -k "ws_project_submit or ws_server"` → 62 passed
- `pytest tests/network -q` → 706 passed；`pytest tests/test_architecture_contracts.py -q` → 40 passed
- 宿主合成复跑 `pytest tests/network tests/test_architecture_contracts.py tests/test_project_registry_health.py tests/test_projects.py tests/test_contract_baselines.py tests/network/test_http_protocol.py -q` → **772 passed, 1 warning**
- `ruff check` / `ruff format --check`（501 files）/ `mypy src`（239 files）/ `bandit -r src/ -ll`（No issues identified）全绿
- 契约基线：`--only exceptions` 由宿主重生成，`--check` 五份全 `[OK]`（新增 `ProjectChannelEntry` / `WsProjectsFrame` 为预期新增）
