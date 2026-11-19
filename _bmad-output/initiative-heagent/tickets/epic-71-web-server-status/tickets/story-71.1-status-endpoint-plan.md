---
title: 'Story 71.1 状态协议与聚合端点'
type: feature
ticket: 1
created: '2026-11-19'
status: done
baseline_revision: 'dadafc0e224141588c1bacb82e61767db8d676cf'
route: full
route_source: auto
risk: low
review: thorough
review_source: auto
lenses_ran: ['edge-case-hunter', 'verification-gap']
review_loop_iteration: 0
followup_review_recommended: true
context:
  - 'src/heagent/network/http_server/endpoints_tasks.py'
  - 'src/heagent/network/http_server/service.py'
  - 'src/heagent/cli/http.py'
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** 网页控制台只能从 `GET /api/health` 知道「服务活着 + 版本」，进程自身运行态（在途 run 数与上限、run 终态分布、三条 WS 流的连接数、后台任务条数）全部只存在于 Python 对象里，零出口——排障只能 `grep logs/heagent-*.log`。

**Approach:** 新开只读聚合端点 `GET /api/status`：协议层加 `StatusResponse`（字段封闭），网络层加 `StatusSource` Protocol + 端点闭包（注入方异常收敛 500 + 固定文案），入口层实现适配器并注入（照 `TaskProgressSource` / `RegistryTaskSource` 的既有接缝）。

## Boundaries & Constraints

**Always:**
- `network/` 不得 import 运行栈（agent/engine/providers/tools/memory/skills/context/cron/events）与 `config/`；所有数值经入口层注入的 source 送达。
- `StatusResponse` 一律 `extra="forbid"`；字段只有枚举 / 布尔 / 非负整数 / 有界文本，**不含**绝对路径、密钥、traceback。
- 端点异常一律收敛为 500 + 固定文案 `request failed`，诊断细节只进服务端日志（与 `endpoints_tasks` 同款）。
- 端点只在注入 source 非 None 时注册，否则 404（与 `/api/tasks` 同一条接缝）。
- 契约基线 `tests/fixtures/contract_baselines/transport_routes.json` 必须重生成（新增路由会改变快照）。

**Never:**
- 不在端点里扫盘、不读 `.env`、不做 psutil 采样（71.4 / 71.5 的范围）。
- 不改 `/api/health` 契约，不改 `web/` 任何资源（前端接入在 71.6）。
- 不引第三方依赖；不动 `network/ws_server.py ↔ http_server` 的隔离约束。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| HAPPY_PATH | 注入 source，无在途 run | 200；`active_runs=0`，`run_status` 全 0，字段集合与 `StatusResponse` 逐字一致 | 无 |
| RUNNING_RUN | 一个 run 在途（executor 阻塞在 Event 上） | `active_runs=1`、`run_status.running=1` | 无 |
| TERMINAL_RUN | 同一 run 完成 | `active_runs=0`、`run_status.completed=1` | 无 |
| WS_SUBSCRIBED | 一条 WS 连接登记进 run 服务 / cli hub / notification hub | 对应 `ws_connections.*` 计数 +1，断开 -1 | 无 |
| SOURCE_RAISES | source 抛异常 | 500 + `request failed`，日志有 `http event=status_failed` | 不吐 traceback |
| SOURCE_ABSENT | `status=None` 装配 | 路由不注册 ⇒ 404 `no such endpoint` | 与 `/api/tasks` 一致 |

</intent-contract>

## Code Map

- `src/heagent/network/http_protocol.py` -- 协议契约。既有 `extra="forbid"` + `Field(ge=0)` 风格；`HTTP_SERVICE_NAME` / `HTTP_SCHEMA_VERSION` 常量在文首；`__all__` 在文件尾（新增名必须登记，`tests/network/test_http_protocol.py` 钉字段封闭性）。
- `src/heagent/network/http_server/service.py` -- `HttpRunService`：`self._runs: OrderedDict[str, _RunRecord]`、`self._ws_registry = WsRegistry(...)`、既有 `active_runs` property（:109）。`_RunRecord.status` 是 `RunStatus`（running/completed/failed/cancelled/timed_out）。
- `src/heagent/network/http_server/endpoints_tasks.py` -- **照抄范式**：`TaskProgressSource` Protocol（:82）、`_build_task_endpoints(responses, source)`（:124）用 `safe_log(..., exc_info=True)` + `_json_error(..., SERVER_ERROR, "request failed", status_code=500)`。
- `src/heagent/network/http_server/app.py` -- 路径常量区（`_TASKS_PATH = "/api/tasks"` 附近）+ `build_http_app(..., tasks=None)` + `if tasks is not None:` 注册块；兜底 `/{asset}` 必须保持最后。
- `src/heagent/network/http_server/listener.py` -- `HttpServer.__init__(..., tasks, history)` 与 `app` property 里的 `build_http_app(...)` 调用，需成对加 `status=`。
- `src/heagent/network/http_server/__init__.py` -- `X as X` 再导出 + `__all__`（加 `StatusSource`）。
- `src/heagent/cli/http.py` -- **两处装配点**：内嵌服务（:355-381）与 `http_server` 命令（:665-700）。注意 `HttpServer(...)` 构造**早于** `build_ws_servers(...)` ⇒ WS 计数必须晚绑定。
- `src/heagent/cli/http_status.py` -- 新增入口层适配器（`HttpStatusSource`）：持有 version / run_service / max_inflight_runs / task registry，`bind_ws()` 晚绑定 WS listener 与两条 hub。禁止在此 import `AgentLoop`。
- `src/heagent/engine/tasks.py` -- `default_task_registry()`（进程内单例）+ `snapshot(limit=...)`；不要新增 count 方法，端点侧用既有 `snapshot` 长度。
- `src/heagent/network/event_stream_hub.py` -- `EventStreamHub.connection_count`（:174）与 `WsRegistry.connection_count`（:88）。
- `tests/test_architecture_contracts.py` -- `test_cli_package_layout_is_pinned` 的字母序模块白名单必须加 `http_status`。
- `tests/test_web_endpoint_coverage.py` -- `_WHITELIST` 需加 `"/api/status": "前端接入在 71.6（71.1 只交付端点骨架）"`，否则「新路由零消费」判红。
- `tests/network/test_endpoint_security.py` -- `_HTTP_CASES` 与基线路由集合**相等**断言；`_build_http_app()` 需注入空 status source，否则装配面断言失败。
- `tests/fixtures/contract_baselines/transport_routes.json` -- 由 `python scripts/contract_snapshot.py --write --only routes` 重生成；`--check` 是 CI 门。
- `docs/frame.md` -- 4.17 路由表加一行「状态 API」；cli 子模块表（:157-158 附近）与目录树（:1566 附近）加 `http_status.py`。

## Tasks & Acceptance

**Execution:**
- [ ] `src/heagent/network/http_protocol.py` -- 加 `RunStatusCounts`（running/completed/failed/cancelled/timed_out，全 `ge=0`）、`WsConnectionCounts`（runs/cli/notifications）、`StatusResponse`（service/version/schema_version/active_runs/max_inflight_runs/run_records/run_status/ws_connections/background_tasks），登记 `__all__` -- 协议是唯一跨层契约，入口层只做填充。
- [ ] `src/heagent/network/http_server/service.py` -- `HttpRunService` 加 `ws_connections` property 与 `run_status_counts()` -- 计数贴近数据源，避免入口层访问私有 `_runs`。
- [ ] `src/heagent/network/http_server/endpoints_status.py` -- 新增 `StatusSource` Protocol + `_build_status_endpoint`（成功 200、异常 500 固定文案 + `http event=status_failed`）-- 网络层只认注入契约。
- [ ] `src/heagent/network/http_server/app.py` / `listener.py` / `__init__.py` -- 加 `_STATUS_PATH`、`status` 参数、注册路由、再导出 `StatusSource` -- 保持「None 即不注册」既有口径。
- [ ] `src/heagent/cli/http_status.py` -- 新增 `HttpStatusSource`（含 `bind_ws(servers, cli_hub=…, notification_hub=…)` 晚绑定；notification hub 全局一份，只计一次）-- 入口层是唯一能同时看到 run 服务与 listener 的地方。
- [ ] `src/heagent/cli/http.py` -- 两处装配点构造并注入，`build_ws_servers` 之后调 `bind_ws` -- 覆盖内嵌与 `http-server` 两种入口。
- [ ] `tests/test_http_status_api.py` -- 新增：字段集合逐字相等、在途/终态计数、WS 计数增减、source 抛错 500、source 缺失 404、响应体无绝对路径 -- 覆盖 I/O Matrix 全部行。
- [ ] `tests/network/test_endpoint_security.py` / `tests/test_web_endpoint_coverage.py` / `tests/test_architecture_contracts.py` -- 补 `_HTTP_CASES` 一条与空 source、白名单条目、cli 模块名 -- 三处守卫都要求同批更新。
- [ ] `tests/fixtures/contract_baselines/transport_routes.json` -- `python scripts/contract_snapshot.py --write --only routes` -- 基线随路由同步。
- [ ] `docs/frame.md` -- 4.17 加「状态 API」行 + cli 子模块表与目录树加 `http_status.py` -- 文档不得落后于路由。

**Acceptance Criteria:**
- Given 装配了 status source 的 app, when `GET /api/status`, then 200 且 JSON 键集合等于 `StatusResponse` 字段集合（多/少即失败）。
- Given 无项目作用域的运行服务, when 一个 run 在途, then `active_runs == 1` 且 `run_status.running == 1`；运行终态后分别为 `0` 与 `run_status.completed == 1`。
- Given 三条流各登记一条连接, when 读 status, then `ws_connections.runs/cli/notifications` 全为 1；断开后各自回 0。
- Given source 抛异常, when 读 status, then 500、`error.code == server_error`、`error.message == "request failed"`，且响应体不含异常类名。
- Given `status=None`, when `GET /api/status`, then 404 `no such endpoint`。

## Implementation Notes

- 落地形态与计划一致：协议模型 → `HttpRunService` 计数访问器 → `endpoints_status.py` → app/listener/`__init__` 接线 → `cli/http_status.py` → 两处装配 → 测试与基线。
- **偏离 1（覆盖守卫）**：计划原本打算把 `/api/status` 进 `tests/test_web_endpoint_coverage.py` 白名单，实测发现另一条既有守卫 `tests/test_web_api_console.py::test_presets_cover_exactly_the_backend_routes` 要求**每条后端路由都有 API 探索器预置**。因此改为在 `web/api-console.js` 的 `PRESETS` 加一条 `GET /api/status` 并同步 `test_preset_count_is_pinned`（20 → 21）：路由因此立刻有真实消费点，白名单条目不再需要（已从 `_WHITELIST` 移除）。
- **偏离 2（复杂度）**：`cli/http.py::http_server_cmd` 加分支后撞 `ruff` 的 C901（16 > 15）。构造与绑定各自抽成 `cli/http_status.py::build_status_source` / `bind_status_source`（`enabled=False` 即返回 `None`，绑定对 `None` 是空操作），调用点因此零新分支。
- **偏离 3（基线范围）**：`contract_snapshot.py --write` 的 `--only` 只接受单值，需分三次（`routes` / `public` / `exceptions`）重生成；`public_exports.json` 因 `http_protocol.__all__` 扩名而变，`exception_types.json` 因新类（`StatusResponse` / `RunStatusCounts` / `WsConnectionCounts` / `HttpStatusSource`）入表而变 —— 均为预期。
- `HttpStatusSource.bind_ws` 的 `notification_hub` 显式传入优先、否则取第一个 listener 上那一份：通知中枢全局一份，按 listener 逐个相加会重复计数（有专项用例）。

## Plan Change Log

## Review Triage Log

### 2026-11-19 — Review pass
- verdicts: 9 findings — high 0, medium 2, low 4, false 3, maybe-false 0
- findings:
  - `[low]` `[patch]` `http_status.py:87-88` `active_runs`（服务级）与 `max_inflight_runs`（每项目级）作用域不同，被当成比率渲染会读成 `run 2/1` — 已在 `StatusResponse` 字段处写明作用域差异并禁止按比率渲染；面板形态归 71.6。
  - `[low]` `[patch]` `http_status.py:88` 无运行服务时 `max_inflight_runs` 仍报配置值（等于谎报空位）— 改为 `service is None` 时报 0，并在 `test_runs_are_zero_without_a_run_service` 加断言。
  - `[false]` `[reject]` `service.py:129-136` 「第六个 `RunStatus` 成员会被静默漏计」— 反证：`RunStatus` 当前恰为五个成员且 `RunStatusCounts` 与之一一对应，新增成员是要改两处的既有编辑；坏结果在当前代码上不发生（属未来编辑的假设）。
  - `[low]` `[patch]` `endpoints_status.py` 的 `model_dump` 在 try 之外，注入方交出不合契约对象时走全局异常处理、丢掉 `event=status_failed` 诊断 — 已把序列化移入 try（固定文案覆盖到底，诊断日志不丢）。
  - `[false]` `[reject]` claims：计划 Tasks 要求 `_WHITELIST` 加 `/api/status`，代码里没有 — 反证：该偏差已在 `## Implementation Notes`「偏离 1」逐条记录（路由改由 API 探索器预置消费，白名单条目因此不需要），计划的自我陈述与代码一致。
  - `[medium]` `[patch]` **verification gap**：整条装配链（`listener` 透传 + 两处 CLI 注入 + 晚绑定）无任何装配级用例，删任一处则真实入口恒 404 或 WS 计数恒 0 而全绿 — 已在 `tests/test_http_status_api.py::TestAssembly` 加 listener 透传 + 内嵌服务晚绑定两例、`tests/test_cli_http.py` 加 `http-server` 接线一例；三处均做变异验证（删接线 ⇒ 对应用例 RED）。
  - `[medium]` `[patch]` **verification gap**：`run_status_counts()` 的 cancelled/failed/timed_out 桶从未被产出过，桶间互换全绿 — 已加 `test_cancelled_run_lands_in_the_cancelled_bucket`（逐桶断言非零/零，不只查总和）；变异验证：互换 failed/cancelled ⇒ RED。
  - `[low]` `[patch]` `test_endpoint_security.py:368` docstring 仍写「文档里那 23 条」，实测 HTTP 路由为 24 条 — 注释已改 24。
  - `[false]` `[reject]` `cli/http.py` 在 `http_on=False` 时也调用 `default_task_registry()` — 反证：该调用只是懒建进程内单例（`engine/tasks.py` 的 `default_task_registry`），无可观察行为差异，未展示任何用户或开发者会遇到的坏结果。

## Auto Run Result

- **实现**：新增只读聚合端点 `GET /api/status`（字段封闭 `StatusResponse`），覆盖运行态（`active_runs` / `max_inflight_runs` / `run_records` / 五档 `run_status` / 三条 WS 流连接数 / 后台任务条数）与服务身份；网络层只认注入的 `StatusSource`，入口层由 `HttpStatusSource` 聚合，WS 计数经 `bind_status_source` 晚绑定。
- **文件**：
  - `src/heagent/network/http_protocol.py` — `RunStatusCounts` / `WsConnectionCounts` / `StatusResponse` + `__all__`
  - `src/heagent/network/http_server/service.py` — `run_records` / `ws_connections` / `run_status_counts()`
  - `src/heagent/network/http_server/endpoints_status.py`（新） — `StatusSource` Protocol + 端点闭包
  - `src/heagent/network/http_server/app.py` / `listener.py` / `__init__.py` — 路由与注入参数接线
  - `src/heagent/cli/http_status.py`（新） — 入口层聚合器 + `build_status_source` / `bind_status_source`
  - `src/heagent/cli/http.py` — 两处装配点注入与晚绑定
  - `src/heagent/web/api-console.js` — 预置端点加 `GET /api/status`（既有守卫要求每条路由都有预置）
  - `tests/test_http_status_api.py`（新）、`tests/test_cli_http.py`、`tests/network/test_endpoint_security.py`、`tests/test_web_api_console.py`、`tests/test_architecture_contracts.py` — 用例与三处守卫同步
  - `tests/fixtures/contract_baselines/{transport_routes,public_exports,exception_types}.json` — 契约基线重生成
  - `docs/frame.md` — 4.17「状态 API」行 + cli 子模块表与目录树
- **评审处置**：patch 5 条（含 2 条 medium 的验证缺口）、defer 0 条、reject 3 条（`false` 附反证）、intent_gap / bad_plan 0 条。
- **后续评审建议**：`true` —— 本次补的 5 个用例是评审后新写的，只经过自我变异验证（4 处接线/桶互换各 RED），未经第二双眼睛检查其强度；未验证风险 = 这些新用例是否在别的失败形态下仍然沉默。
- **验证**：
  - `python -m pytest`（全量，排除 `tests/network` 后 4744 passed / 51 skipped / 30 deselected；`tests/network` 与相关套件另跑 907 passed / 34 skipped）
  - `python scripts/contract_snapshot.py --check` → 四份快照全 `[OK]`
  - `ruff check src tests` / `ruff format --check src tests` / `mypy src` / `bandit -r src/ -ll` 全绿
  - `python -m mkdocs build --strict` 通过
  - 变异验证：删 `http-server` 的 `status=` / 删 listener 透传 / 删 `bind_status_source` / 互换 failed↔cancelled 桶 ⇒ 对应 4 条用例各 RED
- **残差**：本机无 `node`，`tests/test_http_web_ui.py` 的 node 探针仍 skip（Epic 70 既有残差，非本故事引入）；`http-server` 命令的 `bind_status_source` 在该命令下两个中枢恒为 `None`（`push_enabled=False`、无旁路），删掉它今天无可观察行为差异——已由内嵌入口那条例覆盖晚绑定本身。

## Design Notes

计数放 `HttpRunService`（`run_status_counts()` / `ws_connections`）而不是入口层遍历私有字段：入口层只做「多流求和 + 模型填充」，私有结构不外泄，71.2+ 增字段时也不必再碰访问器。

## Verification

**Commands:**
- `python -m pytest tests/test_http_status_api.py tests/network/test_endpoint_security.py tests/test_web_endpoint_coverage.py tests/test_architecture_contracts.py tests/test_contract_baselines.py -q` -- expected: 全绿
- `python scripts/contract_snapshot.py --check` -- expected: 与基线一致（先 `--write --only routes` 再 check）
- `python -m ruff check src tests` / `python -m ruff format --check src tests` / `python -m mypy src` -- expected: 无新增告警

## Code Review

### 2026-11-19（lenses: edge-case-hunter + verification-gap）

**Code review complete.** 0 `decision-needed`, 2 `patch`（已修）, 0 `defer`, 6 rejected。

- [x] [Review][Patch] 「序列化失败」与「取数失败」走同一条 500 文案 — `endpoints_status.py:51` 已把 `model_dump` 移进 `try`，但原用例的替身是在 `status()` 内抛错，两种失败不可区分。已补 `_NotStatusResponseSource`（`status()` 返回 `object()`）+ `test_serialization_failure_takes_the_same_fixed_500`。
- [x] [Review][Patch] `failed` / `timed_out` 两档从未被任何用例产出 — `service.py:131-135` 的桶映射错接时 `sum(...)` 断言天然看不出来。已补 `test_failed_run_lands_in_the_failed_bucket`（执行体抛错 → `failed=1`）。

Rejected:
- false：注入方返回非 `StatusResponse` 时端点不校验字段集 — 只有入口层手写适配器可能如此，`StatusSource` 是结构化 Protocol，`extra="forbid"` 已在模型层保证。
- false：状态未统计 WS「submit」连接 — 本仓没有 submit WS 端点（提交走 `POST /api/runs`），三条流已覆盖全部 WS。
- false：`status()` 同步执行会阻塞事件循环 — 这是 `StatusSource` 文档化的契约（只读内存计数）；磁盘读取已在来源侧 5 秒缓存内。
- false：`snapshot(limit=256)` 会少算后台任务 — 注册表终态保留上限 32 条，256 窗口恒覆盖整表。
- rejected(low)：协议计数字段带 `0` 默认值，漏填会静默成 0 — 影响面是装配写错；改成必填要动协议面，收益不成比例。
- false：`GET /api/status` 会触发 `TaskRegistry.prune()` 删条目 — 那是注册表读取路径的既有惰性 GC（`/api/tasks` 同样触发），不是本端点引入的写。
