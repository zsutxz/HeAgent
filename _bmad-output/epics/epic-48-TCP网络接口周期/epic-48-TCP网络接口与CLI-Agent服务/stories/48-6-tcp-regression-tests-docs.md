---
id: 48-6
title: TCP 回归测试与开发文档
status: done
parent_epic: E48
priority: P1
depends_on: [48-5]
created: '2026-09-22'
---

# Story 48-6：TCP 回归测试与开发文档

## 用户故事

作为维护者，我希望 TCP 能力具备完整的跨层回归证据和可复制文档，以便确认协议、生命周期、Agent 接线和原有功能均未回归，并让使用者可以安全启动和调用。

## 范围

- 收口协议、TCP Server、CLI、AgentLoop 适配的测试矩阵。
- 增加真实 loopback 进程内 E2E，不调用真实外部 Provider。
- 验证跨平台、覆盖率、ruff、format、mypy。
- 完成 README、文档索引、frame 和 `.env.example` 一致性检查。
- 不新增第二套实现功能。

## 回归矩阵

| 层 | 必测项 |
|---|---|
| Protocol | 字段、错误码、UTF-8、CRLF、超限、黄金 JSONL |
| TCP lifecycle | 启停、半包、断开、idle、drain、shutdown |
| Resources | 连接上限、inflight、request timeout、permit 回收 |
| Agent integration | StubProvider 成功、异常、取消、并发隔离 |
| CLI | help、默认值、覆盖值、普通模式不监听、非 loopback 告警 |
| Compatibility | 原 CLI/GUI/goal 构造路径与架构契约 |
| Docs | 命令/配置/安全说明与实现一致 |

## 任务

- [x] 审计 48-1~48-5 的 AC 是否各有自动化测试，补遗漏而不复制测试。（逐条审计表见 Verification；**补 3 处真缺口、新增 4 条测试**：协议黄金字段集 + 黄金报文（48-1 AC5 的强化 / 48-6 任务 5）、48-2 AC4 客户端中途断开、48-2 AC6 绑定失败原始异常；其余 AC 复用既有测试，未复制）
- [x] 增加端到端 loopback 测试：启动 server→发送 JSONL→StubProvider→接收响应→关闭。（48-3 已交付 `test_serve_tcp_listens_serves_and_closes`，本 Story 未复制；48-6 新增项只补真实缺口）
- [x] 增加并发两个请求的隔离测试。（48-3 已交付两条：结果/用量隔离 + 路由档位不串味）
- [x] 增加客户端断开和服务 shutdown 后 pending task 检查。（shutdown 侧 48-4 已覆盖；**客户端中途断开为本 Story 新增**：`test_client_disconnect_before_response_reclaims_resources`，断言连接/在途/`_request_tasks` 全回收且下一连接仍可用）
- [x] 增加协议黄金响应测试，防字段漂移。（本 Story 新增：`test_golden_response_field_sets_are_frozen` + `test_golden_wire_lines_are_byte_stable`——逐字节钉住字段名/顺序/`exclude_none` 省略规则与转义）
- [x] 运行默认全量测试与 coverage gate。（见 Verification：全量 + `--cov-fail-under=87`）
- [x] 运行 Linux 平台语义 mypy；必要时使用现有 CI 等价方法复核。（`mypy src --platform linux` + 干净 Linux 检出复跑，见 Verification）
- [x] 更新 README 快速示例、配置、限制和安全声明。（48-5 已写「TCP 入口（实验性）」章节；本 Story 审计确认字段/端口/错误码/安全声明与代码一致，并把 `docs/README.md` 导航补上）
- [x] 更新 `docs/README.md` 导航和 `docs/frame.md` 架构事实。（`docs/README.md`：阅读路径加「TCP 入口（4.16）」+ 快速定位表加一行；`frame.md` 由 48-5 完成，本 Story 复核 §4.16/五/六/七 与实现一致）
- [x] 回读 `.env.example`，确保每个 TCP Settings 字段都有说明且名称一致。（脚本审计：8/8 `tcp_*` 字段在 `.env.example` 有同名键；另有既有测试 `tests/test_config.py::test_every_settings_field_is_documented_in_env_example` 兜底全字段）
- [x] 在 Epic 文档中记录实际验证结果，不伪造未运行命令。（`sprint-plan.md` 新增「实测结果」表 + `architecture.md` §7.2 记录 `TCP_ENABLED` 冻结决策、`当前状态` 改为已交付；story 的 Verification 逐条列命令与结果）

## 验收标准

- Given 干净测试环境和 StubProvider，when 运行 TCP E2E，then 完成一条真实 socket 请求响应且不需凭据。
- Given 48-1~48-5 的每条关键 AC，when 审计测试矩阵，then 都有至少一个意图级测试证据。
- Given 全量默认测试，when 执行，then 无新增失败且 coverage >=87%。
- Given ruff、format 和 mypy Linux 语义检查，when 执行，then 全绿。
- Given README 示例，when 用户按示例启动和发送请求，then 字段、端口和响应格式与代码一致。
- Given安全文档，when 检查，then 明确无认证/TLS、默认 localhost、非生产边界和 OS/网络隔离要求。

## Definition of Done

- 所有已执行验证命令和结果写入 Story 验证段。
- 全量质量门禁通过或显式记录非本变更阻塞证据。
- 文档没有旧路径、旧字段名或与代码冲突的默认值。
- Epic 48 所有 Story 完成后才可把 `epic-48` 标为 done。
- 不自动 git commit；等待用户确认。

## 代码地图

- `tests/network/test_protocol.py`
- `tests/network/test_tcp_server.py`
- `tests/test_tcp_agent_integration.py`
- `tests/test_cli_tcp.py`
- `tests/test_architecture_contracts.py`
- `README.md`
- `.env.example`
- `docs/README.md`
- `docs/frame.md`
- `_bmad-output/sprint-status.yaml`

## 验证命令

```text
pytest tests/network tests/test_tcp_agent_integration.py tests/test_cli_tcp.py -q
pytest --cov=heagent --cov-fail-under=87
ruff check src tests scripts
ruff format --check src tests scripts
mypy src --platform linux
```

## Verification

**Commands and results（2026-09-22 本机 UTC+8 + 干净 Linux 检出）：**

- 定向：`pytest tests/network tests/test_tcp_agent_integration.py tests/test_cli_tcp.py -q` → **119 passed**（本 Story 新增 4 条）
- 回归矩阵+契约+事件：`pytest tests/network tests/test_tcp_agent_integration.py tests/test_cli_tcp.py tests/test_architecture_contracts.py tests/test_events_jsonl.py -q` → **165 passed**
- 全量 `pytest -q --cov=heagent --cov-fail-under=87` → **2214 passed / 9 skipped / 18 deselected，覆盖率 90.97%**（门限 87%）
- 干净 Linux 检出（`git clone --depth 1` + `git apply` 在途补丁 + `uv venv --python 3.12` + `pip install -e ".[dev]"`，无 `.env`）→ **2201 passed / 17 skipped / 18 deselected / 0 failed**
- `ruff check src tests scripts` → All checks passed；`ruff format --check src tests scripts` → 247 files already formatted；`mypy src --platform linux` → Success: no issues found in 135 source files
- 文档一致性审计脚本（`.heagent/tmp/audit_docs_48_6.py`）→ **PROBLEMS: none**：Settings 8/8 `tcp_*` ↔ `.env.example` 同名键（另有 `test_every_settings_field_is_documented_in_env_example` 兜底全字段）↔ frame 配置表默认值逐项一致；README 覆盖 8/8 错误码 + 默认监听地址 + 命令名；运行时文档无 `TCP_ENABLED` 残留
- 反向验证（本 Story 新增护栏，3 个变异体全部精确红、跑完按 sha256 还原）：①`encode_response` 去掉 `exclude_none` → 黄金报文红；②`start()` 吞掉绑定失败 → 原始异常红；③`_process_client` 不归还在途名额 → 客户端断开回收红

**48-1~48-5 验收标准 → 测试证据审计表**（GAP = 本 Story 新增；其余为复用既有测试，未复制）

| Story | 验收标准（要点） | 意图级证据 |
| --- | --- | --- |
| 48-1 | 合法 UTF-8 JSONL → 严格类型 `TcpRequest` | `test_decode_request_accepts_utf8_jsonl_and_preserves_whitespace` |
| 48-1 | 拆包后只解析一次且字段无损 | `test_decode_request_is_independent_of_tcp_fragmentation` |
| 48-1 | 未知字段 / 空 prompt / 非法 JSON / 非法 UTF-8 → 稳定错误 | `test_decode_request_rejects_invalid_payloads[...]`（含 `system` 未知字段、空 prompt）、`test_decode_request_rejects_invalid_utf8` |
| 48-1 | 超限 → `request_too_large` 且不构造模型 | `test_decode_request_rejects_oversized_payload_before_parsing` |
| 48-1 | result 含换行 / 非 ASCII → 单条 JSONL 以 LF 结束 | `test_encode_success_response_is_one_utf8_json_line` + **GAP** `test_golden_wire_lines_are_byte_stable` |
| 48-1 | （字段漂移防线） | **GAP** `test_golden_response_field_sets_are_frozen` |
| 48-2 | fake handler 一段请求 → 一条响应 + 连接关闭 | `test_server_handles_one_request_and_closes_connection` |
| 48-2 | 拆分发送 → handler 只调用一次 | `test_server_handles_split_request` |
| 48-2 | 非法 / 超长 → 稳定错误且服务继续 | `test_invalid_request_does_not_stop_server`、`test_oversized_line_returns_request_too_large`、`test_oversized_requests_share_one_reason` |
| 48-2 | **客户端响应前断开 → 不崩溃 + 任务回收** | **GAP** `test_client_disconnect_before_response_reclaims_resources` |
| 48-2 | 关闭 + shutdown timeout → 取消任务 / 关 writer / `close()` 返回 | `test_close_returns_after_timeout_when_handler_suppresses_cancellation`、`test_close_cancels_long_running_handler` |
| 48-2 | **绑定失败 → 调用方收到原始可诊断异常** | **GAP** `test_start_propagates_the_original_bind_error`（+ CLI 侧 `test_startup_failure_is_reported_without_a_listening_banner`） |
| 48-3 | StubProvider 合法 prompt → id/result 正确 | `test_tcp_request_runs_agent_and_returns_result_with_metadata` |
| 48-3 | 工具调用仍走 Engine 执行链 | `test_tool_calls_run_through_the_engine_execution_chain` |
| 48-3 | 已知异常 → `agent_error` 且服务继续 | `test_known_agent_error_is_reported_and_service_survives`、`test_unknown_agent_failure_is_sanitized` |
| 48-3 | 取消不被包装成 `agent_error` | `test_handler_cancellation_is_not_converted_to_agent_error`、`test_server_shutdown_cancels_in_flight_request_without_agent_error` |
| 48-3 | 普通 CLI 不创建 listener | `test_plain_cli_never_creates_a_tcp_listener` |
| 48-3 | 并发请求互不污染（结果/用量/模型） | `test_concurrent_requests_keep_their_own_result_and_usage`、`test_concurrent_routed_requests_report_their_own_model` |
| 48-4 | inflight=1 时第二个立即 `rate_limited` 不排队 | `test_inflight_limit_rejects_immediately_without_queueing` |
| 48-4 | 不发完整行 → idle timeout 释放连接 | `test_idle_timeout_returns_timeout`、`test_idle_timeout_releases_the_connection` |
| 48-4 | request timeout → 取消 + `timeout` + permit 释放 | `test_request_timeout_returns_timeout`、`test_request_timeout_releases_the_inflight_slot` |
| 48-4 | 关闭超时 → 残留取消 + 服务可退出 | `test_close_timeout_settles_accounting_and_the_instance_can_restart` |
| 48-4 | env 非法值 → 显式校验失败 | `tests/test_config.py::TestTcpSettings`（13 例，含 inf/nan） |
| 48-4 | CLI 覆盖生效且不改 Settings 默认 | `test_cli_overrides_reach_the_config_without_mutating_settings`、`test_invalid_limits_are_rejected_before_serving[...]`（12 例） |
| 48-5 | 默认 host → 回环且无暴露告警 | `test_default_loopback_binding_prints_no_exposure_warning`、`test_loopback_binding_logs_no_exposure_warning`、`tests/network/test_exposure.py`（22 例） |
| 48-5 | 非回环 → stderr/log 明确告警 | `test_non_loopback_host_prints_one_exposure_warning`、`test_non_loopback_binding_logs_exactly_one_exposure_warning`、`test_hostname_binding_is_warned_about_conservatively` |
| 48-5 | 成功请求可由 request id 串联并含耗时 | `test_request_stages_are_correlatable_by_request_id` |
| 48-5 | 失败含稳定错误码；客户端无 traceback/密钥/路径 | `test_decode_rejection_logs_reason_and_stable_code`、`test_inflight_rejection_logs_reason_and_stable_code`、`test_idle_timeout_rejection_logs_reason`、`test_handler_error_isolated_to_request`、`test_unknown_agent_failure_is_sanitized` |
| 48-5 | logger/事件 sink 抛异常不改写响应 | `test_broken_logging_cannot_change_a_successful_response`、`test_broken_logging_keeps_the_failure_mapping_intact`、`test_logging_failure_does_not_rewrite_the_agent_error_code`（**边界**：运行栈日志记入 frame 五） |
| 48-5 | `EVENTS_ROLLOUT_ENABLED` 任一状态响应不混 rollout | `test_socket_channel_carries_exactly_one_response_line`、`test_tcp_response_is_one_line_regardless_of_rollout_setting[False/True]` |
| 48-6 | 干净环境 E2E（真实 socket + StubProvider，无凭据） | `test_serve_tcp_listens_serves_and_closes` |
| 48-6 | README 示例与代码一致 | 文档审计脚本（错误码 8/8、host:port、命令名）+ `test_help_lists_connection_options` |
| 48-6 | 安全文档要素完整（无认证/TLS、默认 localhost、非生产、OS 隔离） | README「TCP 入口（实验性）」+ frame 4.16 ⚠ 段；断言侧 `test_warning_states_the_three_risk_facts_and_stays_bounded`、`test_non_loopback_host_prints_one_exposure_warning` |

**Implemented：**

- `tests/network/test_protocol.py`：黄金字段集 + 逐字节黄金报文（2 条）。
- `tests/network/test_tcp_server.py`：绑定失败原始异常、客户端中途断开资源回收（2 条）。
- `docs/README.md`：阅读路径与快速定位表补 TCP 入口（frame 4.16）。
- `_bmad-output/.../sprint-plan.md`：新增「实测结果」表（验收项 → 证据）。
- `_bmad-output/.../architecture.md`：§7.2 记录 `TCP_ENABLED` 冻结决策；`当前状态` 改为已交付摘要。

**Deviation / 已知边界：**

- **未新增功能**：本 Story 只补测试与文档（符合「不新增第二套实现功能」）；48-5 遗留的四条边界（运行栈日志、工具摘要入日志、TCP 不写 rollout、无认证/TLS）原样保留并已在 frame 五登记。
- **48-2 AC6 用「不可绑定地址」而非「端口被占」**：后者在开启 `SO_REUSEADDR` 的平台可能绑定成功，会让断言变成平台相关的假绿（测试 docstring 已写明理由）。
- **Linux 复跑的 skip 差异（17 vs 9）**：平台标记导致，非失败；两次复跑均 0 failed。

## Review Status

实现与验证完成：AC 审计逐条落到测试（补 3 处真缺口、新增 4 条测试），文档一致性脚本 0 问题，质量门禁与 Linux 复跑全绿。**未提交 Git**；状态 `done`。评审方式说明：本 Story 为收口型（测试 + 文档），未再派对抗式子代理——48-5 的评审已覆盖实现面；本 Story 的审计结论可复跑（`audit_docs_48_6.py` + 上表所列测试名）。

