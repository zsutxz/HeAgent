---
ticket: 2
ref: 77.2
code: E77-S02
epic: epic-77-remote-contract-hardening
risk: low
hitl: false
covers: ["R2"]
status: done
---

# E77-S02 · 具名码 project_channel_unavailable：未装配与帧拼错可凭 code 分流

## Intent

<frozen-after-approval>

「这个 listener 没装配项目通道」是**环境/装配**问题，重试无用；「帧字段拼错」是**客户端**问题，
改代码即可。两者现在都回 `invalid_request`，客户端只能读文案（或依赖「是否断连」这种脆弱信号）。
新增 `project_channel_unavailable` 只给前者用，后者保持 `invalid_request`。

这是纯增量：`HttpErrorCode` 只增不减（INV-8），`transport_errors` 基线重生成后 diff 只含一条。

</frozen-after-approval>

## Boundaries & Constraints

**Always**

- 新码只用于「`project_service is None`」两条路径（带 `project_id` 的 `run`、`projects`）。
- 两条路径仍**不断连**（与既有护栏口径一致），`message` 文案逐字不变。
- 帧解析失败（`WsFrameError`）仍是 `invalid_request` + `WS_CLOSE_POLICY`，语义不动。
- 文档给客户端一句可执行口径：见到本码 = 这条 listener 没有项目通道，重试无用。

**Never**

- 不改既有 36 个码的名字或归属；不把新码塞进 HTTP 控制台路径。
- 不给 ack / 错误帧模型加字段（`HttpErrorEnvelope` 两格冻结）。
- 不顺手拆其它「共用 invalid_request」的场景（超出裁决范围）。

## Code Map

- `src/heagent/network/http_protocol.py`
  - `HttpErrorCode`（`:59`）加 `PROJECT_CHANNEL_UNAVAILABLE = "project_channel_unavailable"`，
    分组注释归「项目与会话类」；类 docstring 的码表同步。
- `src/heagent/network/ws_commands.py`
  - `_start_project_run`（`:163` 的 `HttpErrorCode.INVALID_REQUEST`）与 `_send_projects_frame`（`:183`）
    改新码；两处 docstring 同步。
- `tests/network/test_ws_project_commands.py`：两例改断言新码，新增一例「帧拼错仍 `invalid_request` 且关连接」。
- `tests/fixtures/contract_baselines/transport_errors.json`：`--write --only transport_errors` 重生成。
- `docs/framework.md`（错误码表 / 项目通道行）、`docs/errors.md`（传输错误表）各一行。

## Tasks & Acceptance

- [x] `HttpErrorCode` 加成员并同步类 docstring 分组说明。
- [x] 两条未装配路径改码；`message` 与「不断连」保持。
- [x] 基线重生成并 review diff（只多一条 `project_channel_unavailable`，`status: null` /
      `status_source: "unmapped"`）。
- [x] `docs/framework.md` 项目通道行的 `HttpErrorCode` 计数 36 → 37 并点名新码语义；
      `docs/errors.md` 传输错误表加一行（处置：换 listener / 换环境，重试无用）。
- [x] 测试三例（run 路径 / `projects` 路径 / 帧拼错对照）。

## Verification

| 命令 | 期望 |
|---|---|
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network -q` | 全绿，含三例新断言 |
| `.heagent/tmp/py311-venv-linux/bin/python scripts/contract_snapshot.py --write --only transport_errors` 后 `--check` | 五份 `[OK]` |
| `git -c safe.directory=/workspace diff --stat tests/fixtures/contract_baselines/` | 只有 `transport_errors.json`，且 diff 仅一条 entry |
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/test_contract_baselines.py tests/network/test_ws_error_codes.py -q` | 全绿 |

## 实测结果（2026-11-24）

| 命令 | 结果 |
|---|---|
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network tests/test_architecture_contracts.py -q` | **782 passed** |
| `python scripts/contract_snapshot.py --write --only transport_errors` 后 `--check` | 五份全 `[OK]` |
| `git diff --stat tests/fixtures/contract_baselines/` | `transport_errors.json` +12/-1（新增一条 entry + 计数行）；`exception_types.json` +6（S01 的 `SubmissionCache` 新类，见下） |
| `pytest tests/test_docs_links.py tests/test_contract_baselines.py tests/network/test_ws_error_codes.py tests/network/test_http_protocol.py -q` | 61 passed |
| `ruff check` / `ruff format --check`（src + tests） | 干净 |
| `mypy src` | no issues（242 files） |

## Implementation Notes

- **`transport_errors.json` 期望 diff = 一条 entry**：`{code: project_channel_unavailable, status: null,
  status_source: "unmapped"}`——WS 专用码不经 HTTP 响应，与既有 5 个 unmapped 码同档。`console_status_map`
  计数不变，`status_sources` 只动总数。
- **`exception_types.json` 也被 S01 推动了**：契约快照把**所有类**（不只是异常）按 `{module, name, bases}`
  收进去，所以 S01 新增的 `cli/ws_submission_cache.SubmissionCache`（`bases: []`）必须一并重生成。review
  结论 = 纯增量（204 条、只多一条、无改归属），符合「只增不减」。
- **对照用例踩到一次替身语义**：`_ws_session` 在 `session` 返回后会补一次默认 `close(1000)`，而替身只记
  「最后一次」close ⇒ 断言从 `== WS_CLOSE_POLICY` 改成 `is not None` + 一行「两档 code 确实不同」的
  自证断言，避免把替身的记法当成协议事实（`test_endpoint_security.py:649` 另有真 WebSocket 的 1008 判据）。
- **文档计数**：`docs/errors.md` 从「35 个稳定码 / 合计 76 条」改 36 / 77；`docs/framework.md` 项目通道行
  同时把「未注入 ⇒ `invalid_request`」改成新码并写明与「帧写错」的分流口径。
- **追加（全量门禁暴露的一处遗漏）**：`tests/test_http_web_ui.py::test_every_console_error_code_has_a_readable_text`
  以 `HttpErrorCode` 枚举为参数源，要求**每个**码在 `src/heagent/web/app.js` 的错误文案表里有中文文案 ⇒
  新码必须在同批补一行，否则全量红（单跑 `tests/network` 不会发现）。已补：
  `project_channel_unavailable: "这条 WS 连接所在的服务没有装配项目通道：重试无用…"`。这条义务不属于
  `docs/`，属**控制台 UX 面**，后续加码时务必连 `app.js` 一起想。
