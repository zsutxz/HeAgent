---
title: '56-3 经 WS 提交 run'
type: 'feature'
created: '2026-10-24'
status: 'done'
route: 'dispatch'
review_loop_iteration: 1
baseline_commit: '67554d9ecd2405ac688cc6671d0701d977be80fc'
context: []
---

<!-- 交付物与验收边界 = epics.md 56-3 行；冻结决策 D2（能力边界）/ D6（单用户共享）见 brief.md。 -->

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Epic 54 D2 显式不做「经 WS 提交 run」，WS 只能旁观已有 run；对外客户端（IDE 插件、桌面端）
连上来却无法发起一次运行——只读订阅对远程客户端没有生产价值。

**Approach:** 新增**集合级** WS 端点 `WS /api/runs/ws`（与既有 `/api/runs/{run_id}/ws` 段数不同，无路由
冲突）承载 `run` 命令帧：语义**等价** `POST /api/runs`（名额满 `run_conflict` 不排队、`shutting_down` 拒绝、
空/全空白 prompt 回 `empty_prompt`、超长 prompt 回 `invalid_request`），回 `ack` 带 `run_id` + 初始 status。
期一交互形状：**提交连接不转事件流**——客户端拿 `run_id` 后经既有单 run 端点订阅（保持单 run 端点形状）。
D2 边界不变：配置 / 项目 / 会话 / 对话框**只走本机 HTTP**，WS 命令集封闭为 `{run, cancel, ping}`。

## Boundaries & Constraints

**Always:**
- 提交语义与 `POST /api/runs` **同一实现**：复用 `HttpRunService.start_run`（名额判定/记录/任务一处生成），
  不另写一套名额逻辑
- 校验复用 `RunRequest`（`extra="forbid"`、非空白、`MAX_PROMPT_CHARS`）——WS 不另立校验口径
- 错误信封单出口 `error_envelope` + `sanitize_message`；`HttpErrorCode` **封闭不新增**
- `run_conflict` / `total_inflight_limit` / `shutting_down` 走 `HttpRunConflictError.code`（单一映射点）
- 提交连接**不转**事件流；ack 后连接保持，可再提交（再提交撞名额即 `run_conflict`）或 `ping`
- 集合端点上的 `cancel` ⇒ `invalid_request` 错误帧且**不断连接**（没有 run 绑定就没有可取消对象）
- 帧上限：`run` 帧必须容纳协议允许的最大 prompt（HTTP 侧 `MAX_REQUEST_BYTES_FOR_MAX_PROMPT` 同源），
  非 `run` 帧仍守小上限（最小面原则）
- 断线不取消运行；提交成功后的运行属于 `HttpRunService`，WS 连接关闭只影响该连接

**Never:**
- 不做「一条连接多路复用多个 run 的事件流」（单 run 端点形状保持）
- 不做队列/等待（名额满即拒绝）、不做多租户/会话隔离（D6 单用户共享同一状态机）
- 不给集合端点附赠配置 / 项目 / 会话 / 对话框命令（D2 边界）
- 不改 HTTP `POST /api/runs` 行为，不改本机订阅语义

</frozen-after-approval>

## I/O & Edge-Case Matrix

| 场景 | 输入/状态 | 预期行为 | 错误处理 |
|---|---|---|---|
| 提交成功 | `{"command":"run","prompt":"hi"}` | `ack{command:run, run_id, status:running}` | N/A |
| 已有在途运行 | 同名项目第二个提交 | `run_conflict` 错误帧（409 语义），连接保持 | 不排队 |
| 服务级总额满 | `HTTP_MAX_TOTAL_INFLIGHT` 已满 | `total_inflight_limit` 错误帧 | 同上 |
| 服务正在关闭 | `_closing` | `shutting_down` 错误帧（连接保持，客户端可重试/断开） | N/A |
| 空 prompt | `""` / 缺失 / 非字符串 | `empty_prompt`（空白）或 `invalid_request`（缺失/类型错） | 连接保持 |
| 超长 prompt | > `MAX_PROMPT_CHARS` | `invalid_request`（与 HTTP 400 同码） | 连接保持 |
| 帧超上限 | > `WS_MAX_INBOUND_CHARS`（`run`）/ `WS_MAX_COMMAND_CHARS`（其它） | close(1009) | 不解析超限输入 |
| 未知命令 | `{"command":"shell"}` | `invalid_request` 错误帧 + close(1008)（既有口径） | 封闭集合 |
| 集合端点 `cancel` | `{"command":"cancel"}` | `invalid_request` 错误帧、**不断连** | 与 CLI 旁路同一处理 |
| 其它端点收 `run` | 单 run 端点 / CLI 旁路 | `invalid_request` 错误帧、不断连 | 提交能力只在集合端点 |
| 提交连接上的 `ping` | `{"command":"ping"}` | ack（`run_id=""`，此刻无绑定） | N/A |
| 断线 | 客户端关闭 | 运行继续；订阅者可继续看事件 | 断线不取消运行 |

## Code Map

- `src/heagent/network/ws_protocol.py` — `WsCommand.RUN`；`WsCommandFrame.prompt`（可选 + 互斥校验）；
  `WS_MAX_INBOUND_CHARS` / 新增 `WS_MAX_COMMAND_CHARS` / `WS_MAX_FRAME_BYTES` 三上限调整；`WsSubmitAckFrame`？
  （结论见实现笔记：复用 `WsAckFrame`，`status` 取提交瞬间的运行状态）
- `src/heagent/network/http_protocol.py` — `HttpRunConflictError` **迁入**（协议层单一来源，`http_server`
  保留 re-export 以免既有导入漂移）
- `src/heagent/network/ws_server.py` — 新增 `build_runs_collection_endpoint`（提交门 + ping + 拒绝 cancel）；
  `RunWebSocketService` 协议扩 `start_run`
- `src/heagent/network/ws_host.py` — 注册第三条路由 `RUNS_WS_COLLECTION_PATH = "/api/runs/ws"`（仅在注入
  `run_service` 时）；认证门同样覆盖
- `src/heagent/config/__init__.py` — 无新字段（提交面复用 `http_max_inflight_runs` / `http_max_total_inflight`）
- `docs/frame.md` — 4.17 端点表补一行（全量重写在 56-4）
- `tests/network/test_ws_protocol.py` — 帧解析矩阵（run/prompt 互斥、三上限、未知命令）
- `tests/network/test_ws_server.py` — 集合端点路由注册矩阵（无 run_service ⇒ 403）
- `tests/network/test_ws_e2e.py` — 真实 listener：提交 → ack → 订阅 → 事件 seq 单调 → cancel 等价 DELETE；
  名额满 `run_conflict`；空 prompt `empty_prompt`

## Tasks & Acceptance

**Execution:**
- [ ] `src/heagent/network/ws_protocol.py` — `RUN` 命令 + `prompt` 字段 + 三条上限（含测试同步）
- [ ] `src/heagent/network/http_protocol.py` — `HttpRunConflictError` 迁入 + `http_server` re-export
- [ ] `src/heagent/network/ws_server.py` — 集合端点（提交 / ping / 拒绝 cancel）
- [ ] `src/heagent/network/ws_host.py` — 注册集合路由
- [ ] `tests/network/test_ws_protocol.py` / `test_ws_server.py` / `test_ws_e2e.py` — 判据落地
- [ ] `docs/frame.md` — 端点表补行

**Acceptance Criteria:**
- Given 空在途，when `{"command":"run","prompt":"hi"}`，then `ack` 含非空 `run_id` 与 `running` 状态；
  经该 `run_id` 订阅得事件且 `seq` 从 1 单调递增
- Given 已有在途运行，when 第二个提交，then `run_conflict` 错误帧且首个运行不受影响
- Given 提交成功后，when 对该 `run_id` 发 `cancel`（单 run 端点），then 运行进入 `cancelled`（等价 `DELETE`）
- Given 空 / 全空白 prompt，when 提交，then `empty_prompt` 且不创建运行（`active_runs` 不变）
- Given 最大长度 prompt（`"中" * MAX_PROMPT_CHARS`），when 提交，then 成功（帧上限容纳协议允许的最大值）
- Given 集合端点上 `{"command":"cancel"}`，when 发送，then `invalid_request` 且连接仍可继续命令
- Given 9001 上非 WS 请求，when 任意 HTTP 路径，then 仍全 404（D2 边界，56-1 判据保持）
- Given 全量 `pytest` / ruff / mypy / bandit / 架构契约，then 全绿

## Verification

**Commands:**
- `pytest tests/network/test_ws_protocol.py tests/network/test_ws_server.py tests/network/test_ws_e2e.py -q` -- expected: 全绿
- `pytest tests/network -q` -- expected: 全绿
- `pytest -q` -- expected: 全量绿
- `ruff check src tests && ruff format --check src tests && mypy src && bandit -r src/ -ll` -- expected: 全绿

**实测结果（2026-10-24）:**
- `pytest tests/network -q` → **431 passed**
- `pytest -q --ignore=tests/test_cli_http_lifecycle.py` → **3906 passed / 50 skipped / 25 deselected**
- `ruff check src tests` / `ruff format --check src tests` / `mypy src` / `mypy src --platform linux` /
  `bandit -r src/ -ll` → 全绿（bandit Medium 0 / High 0）
- `scripts/quality_gate.py` → 覆盖率 **92.33%**（门限 87%），静态门全绿；唯一失败 = 「已知非回归」

## Spec Change Log

<!-- Append-only. -->

- 2026-10-24（实施期，静默偏离前先报告）：`WS_MAX_INBOUND_CHARS` 的初版取值是
  `MAX_PROMPT_CHARS + 1024`（按原始字符数）。e2e 实测发现：**合法的**最大 prompt 若用
  `json.dumps` 默认的 `ensure_ascii=True` 发送（每个 CJK 字符变成 `\uXXXX`，约 197 K 字符），会先撞
  协议层的 TOO_LARGE 被 `close(1009)`，而 HTTP 侧同一 prompt 完全可用。已按最坏转义重算为
  `6 × MAX_PROMPT_CHARS + JSON_ENVELOPE_ALLOWANCE_BYTES`，并补「最大 prompt 经 WS 可提交」的 e2e 判据。
  这是**取值的修正**，不改变交付物与验收边界（「帧上限必须容得下协议允许的最大 prompt」自始至终是判据）。

## Implementation Notes

<!-- Agent-owned. Append-only during implementation. -->

- 2026-10-24 实施完成，基线 `67554d9`。新增集合级端点 `WS /api/runs/ws`（`RUNS_SUBMIT_PATH`，与
  `/api/runs/{run_id}/ws` 段数不同，Starlette 精确匹配、互不遮蔽）；`build_runs_collection_endpoint`
  在 `accept()` 后占一个**提交席位**（`_SubmissionSlots`：检查 + 登记同一同步方法，A9③ 口径，随连接归还）。
- 帧协议：`WsCommand.RUN`；`WsCommandFrame` 增 `prompt` 字段 + `model_validator` 绑定「`run` ⇔ `prompt`」；
  `parse_command_frame` 两级上限（`WS_MAX_INBOUND_CHARS` 总闸 → `WS_MAX_COMMAND_CHARS` 再把非 run 帧钉回
  小上限；大小判定先于字段集判定）。`WS_MAX_FRAME_BYTES` 改为与 HTTP 请求体上限同源。
- 复用面：校验 `RunRequest`（`extra="forbid"` / 非空白 / `MAX_PROMPT_CHARS`），创建
  `HttpRunService.start_run`（名额判定、记录、任务生成只有一处）；`HttpRunConflictError` 自 `http_server`
  迁入 `http_protocol`（`http_server` 保留 re-export），`ws_server` 因此不必反向导入 `http_server`。
- ack 形状：`run` 回既有 `WsAckFrame{command:run, run_id, status}`；集合连接的 `ping` 回
  `WsCliAckFrame{run_id:""}`（连接级 ack，无 run 绑定，**不**新造第三个 ack 模型）。
- `run` 在非集合端点（单 run / CLI 旁路）一律 `invalid_request` 且**不断连**；集合端点上的 `cancel`
  同形拒绝（没有绑定对象）。
- 实测：见上方 Verification（与本周期 56-2 同一轮门禁，数字为同一份运行结果）。

## Review Triage Log

<!-- 2026-10-24 step-04。运行时无子代理，经用户裁定由主会话自审（选项②）：三层指令
（blind-hunter / edge-case-hunter / verification-gap）逐层执行，独立性弱化已如实注明。
提交端点相关发现记在本 story（文件归属 = ws_server / ws_protocol），认证与配置面记 56-2。 -->

| # | 发现 | 判定 | 证据 / 路由 |
|---|---|---|---|
| 1 | **提交端点没有任何连接额度**：`limit_concurrency` 不约束 WS（Epic 54 实测），而 run 端点有「按 run」的订阅额度、CLI 旁路有 hub 总额——只有新端点裸奔；对外模式下等于「拿着 token 就能开无限条空闲连接」 | medium（真） | 读 `build_runs_collection_endpoint` 初版确认零额度 → **patch**（`_SubmissionSlots`：检查 + 登记同一同步方法、随连接 `finally` 归还、额度取 `ws_max_connections`；e2e `test_submit_connections_have_their_own_atomic_slot_pool` 钉住「满额回 rate_limited」与「关闭后归还」） |
| 2 | 初版 `WS_MAX_INBOUND_CHARS = MAX_PROMPT_CHARS + 1024` 把**合法**的最大 prompt 挡在协议层之外（`ensure_ascii=True` 下 32 K 汉字 ≈ 197 K 字符 → 1009） | medium（真·实测踩到） | e2e 实测 1009 → **patch**（按最坏转义重算 + 常量注释 + `test_protocol_limits_and_close_codes_match_contract` 与「最大 prompt 可提交」判据；Spec Change Log 已登记） |
| 3 | `HttpRunConflictError` 若留在 `http_server`，`ws_server` 就得反向导入传输层实现模块（同层互相依赖） | medium（真） | 读 import 图 → **patch**（迁入 `http_protocol`，`http_server` re-export 保持既有导入点零改动；`tests/network/test_http_run_service.py` 既有 21 例照常绿） |
| 4 | 集合端点若接受 `cancel`（没有 run 绑定）却静默成功，客户端会误以为取消了 | low（真） | → **patch**（显式 `invalid_request` 错误帧、**不断连**，与 CLI 旁路的「不支持必须说出来」同形；e2e 判据断言后续 `ping` 仍可用） |
| 5 | 若单 run 端点也接受 `run`，会绕开「提交连接不转事件流」的期一形状，等于在已绑定 run 的连接上再起一个 run | low（真） | → **patch**（两个非集合端点都回 `invalid_request`；e2e `test_single_run_endpoint_rejects_the_run_command` 断言「未额外创建运行」） |
| 6 | 空闲提交连接在关停时是否被有界关闭，无判据 | low（真） | → **patch**（`test_idle_submit_connection_is_closed_by_server_shutdown_within_budget`：实测由 uvicorn shutdown 关闭，耗时 ≤ 2×`shutdown_timeout`+2） |
| 7 | 集合端点与单 run 端点的路由是否会互相遮蔽（`/api/runs/ws` vs `/api/runs/{run_id}/ws`） | false（驳回） | 段数不同（3 vs 4），Starlette 按精确路径匹配；`test_ws_app_registers_the_submit_route_only_with_a_run_service` 直接断言三条路由表与路径常量 |
| 8 | 空串 prompt 归 `invalid_request` 而不是 `empty_prompt` | false（驳回） | 与 `POST /api/runs` 现状逐字一致（`min_length=1` 先于 field validator 触发）；WS 侧刻意不改，否则两条入口分叉。判据注释已写明理由（`test_submit_validates_prompt_like_the_http_endpoint`） |
| 9 | 提交端点没有「每连接提交节流」，客户端可高频触发 `run_conflict` | low（接受） | 每次拒绝只是一次同步名额检查 + 一帧错误，不建记录、不起任务；真正的资源消耗（运行）受 `HTTP_MAX_INFLIGHT_RUNS` / `HTTP_MAX_TOTAL_INFLIGHT` 约束。若将来出现滥用证据，属「限额策略」变更（配置面），不在本期冻结范围 |
| 10 | `WS_MAX_FRAME_BYTES` 抬到 ~394 KB 会不会连带放大出站帧 | false（驳回） | uvicorn 的 `ws_max_size` 只约束**入站**消息；服务端事件帧受 `MAX_EVENT_TEXT_CHARS` 截断（既有契约） |
