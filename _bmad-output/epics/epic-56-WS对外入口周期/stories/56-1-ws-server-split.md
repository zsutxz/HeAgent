---
title: '56-1 WS server 拆分与端点迁移'
type: 'feature'
created: '2026-10-24'
status: 'in-review'
route: 'dispatch'
review_loop_iteration: 1
baseline_commit: '38c0b8ee2cfc37a3ce4f8bd178610907a9eec5fc'
context: []
---

<!-- 交付物与验收边界 = epics.md 56-1 行；冻结决策 D1–D7 见同目录 brief.md。 -->

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 两条 WS 路由挂载在 HTTP 的 ASGI app 内、共用 8766 监听器与 HTTP 配置；对外入口（56-2 认证/TLS、56-3 经 WS 提交 run）无处安放，`ws_max_connections` 等旋钮与 HTTP 面混在一起。

**Approach:** 新建 `network/ws_host.py`：`WsServerConfig`（默认 `127.0.0.1:9001`）+ `build_ws_app`（只挂既有两条 WS 端点，零 HTTP 路由）+ `WsServer`（start/serve_forever/close 三件套，镜像 `HttpServer` 口径）；HTTP app 拆除 WS 路由与 `cli_hub` 缝；端点逻辑复用 `ws_server.py` 不重写；组合根（`heagent http-server` 命令 + 默认 CLI 内嵌服务）双 server 编排，关停顺序 HTTP 先（排空运行）→ WS 后（关残余连接）。

## Boundaries & Constraints

**Always:**
- 分离判据可执行测试（非文档句）：8766 上 WS 升级不可达（未 accept、非 101；用户裁定①A 钉实测，不钉字面 404）；9001 上无任何 HTTP API 面（REST/静态页/健康检查全 404）
- 本机语义逐字保持：订阅/续传（last_event_id）/cancel/ping + CLI 旁路跨轮，路径不变
- 端点与事件分发不重写：`ws_server.py` 复用；`_RunRecord`/`CliEventHub` 状态源不动
- 限额原子性不动：「检查 + 登记」同一无 `await` 同步方法（A9③）
- 错误信封单出口（`error_envelope`），`HttpErrorCode` 封闭不新增
- 断线只注销、绝不取消运行（既有立场）
- `network/` 依赖边界不变；跨模块数据一律 Pydantic

**Never:**
- 不做认证/TLS（56-2）、经 WS 提交 run（56-3）、`frame.md` 4.17/4.18 重写（56-4）
- 不新建 CLI 命令；不引入新错误码；不改 SSE/REST/控制台行为
- 不做双 WS 监听并存、多租户、反向代理（brief 冻结边界）

## I/O & Edge-Case Matrix

| 场景 | 输入/状态 | 预期行为 | 错误处理 |
|---|---|---|---|
| WS 升级打到 8766 | HTTP listener，任意 WS 路径 | 升级被拒：未 accept、非 101（Starlette 实测 HTTP 403 / close 1000） | 裁定①A：钉实测「不可达」，不钉字面 404（brief 措辞偏差经用户裁定） |
| HTTP 请求打到 9001 | GET /、/api/health、/api/runs | 全 404（Starlette 默认），无任何 API 面 | N/A |
| run 订阅限额满 | 第 limit+1 个订阅者 | `rate_limited` 错误帧 + close policy | 检查+登记同步原子 |
| 缺 `websockets` 包 | WsServer.start() | 照常绑定 + `ws_unavailable` 安装诊断；HTTP 不受影响 | 非致命 |
| WS 端口冲突 | auto-find 顺延；显式指定 fail-loud | 启动失败显性报错 | `WsStartupError` → 入口层 ClickException |
| CLI 旁路关闭 | `ws_cli_bypass_enabled=false`（默认） | 9001 不注册 `/api/cli/ws` | N/A |

</frozen-after-approval>

## Code Map

- `src/heagent/network/http_server.py` — 2172 行 HTTP 实现。拆点：`HttpServerConfig.ws_max_connections`(:200)；`build_http_app` 的 WS 路由与 cli_hub 缝(:1753-1915)；`_OriginGuardMiddleware`(:1126)；Origin 辅助 `:1032-1109`；uvicorn WS 参数(:2016-2018)；`HttpServer.close` 的 close_websockets/cli_hub(:2084-2101)；`_CLI_WS_PATH`(:132)
- `src/heagent/network/ws_server.py` — 端点适配器（复用不重写）：`build_ws_endpoint`（配额经 `service.config.ws_max_connections` :198 需参数化）；`build_cli_ws_endpoint`；`_supervise` 共用收尾
- `src/heagent/network/ws_protocol.py` — `WS_MAX_FRAME_BYTES`/`WS_PING_*` 常量（随迁到 ws_host 的 uvicorn 配置）
- `src/heagent/network/cli_event_hub.py` — `CliEventHub(max_connections=...)` 构造注入，不动
- `src/heagent/cli/http.py` — 组合根：`build_server_config`(:70)、`_serve_http`(:139)、`EmbeddedHttpService`(:156)、`build_http_service`(:254)、`http_server_cmd`(:404)、`_CLI_WS_PATH` 副本(:49)
- `src/heagent/cli/interactive.py:139-147` — 内嵌服务唯一调用方（签名不变则零改动）
- `src/heagent/config/__init__.py:393-409` — `http_ws_max_connections`/`http_cli_ws_enabled` 字段位
- `src/heagent/config/catalog.py:385-389` — listening 组 `HTTP_*` 模式行
- `tests/network/test_http_ws_config.py` — Settings/HttpServerConfig 同步测试（重构并入新文件后删除）
- `tests/network/test_http_ws_e2e.py` — WS 订阅 e2e（HttpServer 驱动 → 改 WsServer 驱动）
- `tests/network/test_http_cli_ws.py` — CLI 旁路 e2e（同上）
- `tests/test_cli_ws_publish.py`/`test_cli_ws_wiring.py`/`test_cli_http.py`/`test_cli_http_lifecycle.py` — 装配/生命周期面
- `tests/test_architecture_contracts.py:72-80` — network 禁入清单（验证，预计零改动）

## Tasks & Acceptance

**Execution:**
- [x] `src/heagent/network/origin.py` — 新建：自 http_server.py 纯搬移 Origin/Host 校验（_allowed_hosts/_allowed_ports/_split_authority/_request_origin_violation/_canonical_authority + 4 个头/通配常量），公开命名；http_server.py 改导入；测试 import 同步
- [x] `src/heagent/network/ws_host.py` — 新建：WsServerConfig + build_ws_app（两条 WebSocketRoute + Origin 防线，零 HTTP 路由）+ WsServer（三件套 + TCP 就绪探测 + uvicorn WS 参数 + ws_unavailable 诊断）+ WsStartupError
- [x] `src/heagent/network/http_server.py` — 拆除：WS 路由、cli_hub 参数/字段/reopen/close_websockets、HttpServerConfig.ws_max_connections、uvicorn WS 参数、_CLI_WS_PATH；Origin 辅助改从 origin.py 导入
- [x] `src/heagent/network/ws_server.py` — 两个 build_* 端点配额参数化（新增 max_connections 参数，删 service.config 读取）
- [x] `src/heagent/config/__init__.py` — Settings：删 http_ws_max_connections/http_cli_ws_enabled；增 ws_host/ws_port/ws_max_connections/ws_shutdown_timeout/ws_cli_bypass_enabled
- [x] `src/heagent/config/catalog.py` — listening 组 patterns 加 `WS_*`
- [x] `src/heagent/cli/http.py` — build_server_config 去 ws_max_connections；新增 build_ws_server_config（端口 auto-find 复用 http_port_auto_find_attempts）；EmbeddedHttpService 持双 server（HTTP 先 WS 后关停）；http_server_cmd 加 --ws-host/--ws-port
- [x] `.env.example` — 新增 WS_HOST/WS_PORT/WS_MAX_CONNECTIONS/WS_SHUTDOWN_TIMEOUT/WS_CLI_BYPASS_ENABLED；删 HTTP_WS_MAX_CONNECTIONS/HTTP_CLI_WS_ENABLED 行
- [x] `docs/frame.md` — 配置表增 WS_* 行（4.17/4.18 全量重写留 56-4）
- [x] `tests/network/test_ws_server.py` — 新建替身纯逻辑面：两条端点全语义（订阅/续传/cancel/ping/限额/shutting_down/Origin 拒）+ 配置同步 + 分离判据（8766 升级不可达 / 9001 全 404）+ ws_host 生命周期
- [x] `tests/network/test_http_ws_e2e.py` / `test_http_cli_ws.py` — 改 WsServer 驱动；`test_http_ws_config.py` 删除（并入 test_ws_server.py）
- [x] `tests/test_cli_ws_publish.py` / `test_cli_ws_wiring.py` / `test_cli_http.py` / `test_cli_http_lifecycle.py` — 双 server 装配/生命周期更新
- [x] `tests/network/test_http_server.py` — origin 辅助 import 路径同步

**Acceptance Criteria:**
- Given 默认配置双 server 运行，when WS 客户端升级 8766 任意路径，then 升级不可达（未 accept、非 101），且 SSE/REST/静态页行为零改动
- Given 默认配置，when HTTP 客户端请求 9001 的 /、/api/health、/api/runs，then 全 404
- Given 同一 run，when 订阅/续传/cancel/ping 经 9001，then 语义与迁移前逐字一致（事件 seq 单调、游标续传、命令 ack）
- Given `ws_cli_bypass_enabled=true`，when 经 9001 订阅 `/api/cli/ws`，then 跨轮次只读事件流语义保持
- Given 第 limit+1 个订阅者，when 订阅，then `rate_limited` 错误帧且检查+登记原子
- Given 缺 websockets，when 启动双 server，then WS server 绑定 + 安装诊断日志，HTTP 服务不受影响
- Given 既有 HTTP 全量测试，when pytest，then 全绿（零改动或仅 import/装配同步）

## Implementation Notes

<!-- Agent-owned. Append-only during implementation. -->

- 2026-10-24 实施完成，基线 `38c0b8e`。全部验证实测：`pytest -q` 3885 passed / 14 skipped；`pytest tests/test_architecture_contracts.py` 31 passed；`ruff check src tests` / `ruff format --check` / `mypy src` 全绿；`bandit -r src/ -ll` 退出码 0。
- 与 spec 的两处实施级偏离（不影响验收边界）：① `origin.py` 除 Origin/Host 校验外一并随迁 `probe_host`（它依赖同批搬移的通配常量，留在 http_server 会造成跨模块常量导入）；② 两份 e2e 按 epic-54 retro 遗留意图**更名**——`test_http_ws_e2e.py → test_ws_e2e.py`、`test_http_cli_ws.py → test_cli_ws_e2e.py`（驱动 = WsServer，原名已失真）；`test_http_ws_config.py` 删除、断言并入 `test_ws_server.py`。
- `tests/test_cli_ws_publish.py` 仅被 ruff format 触碰（格式化换行），无语义改动；其本就无 WS 耦合。
- 实测修正记录：分离判据测试初版在异步用例里调同步 `urllib` 造成事件循环自阻塞假超时——改用异步裸 HTTP 助手 `_raw_status`；`_resolve_listener_port` 首版把 WS 基准端口误用 `http_port`，冒烟即抓出并参数化为 `default_port`。
- brief 验收「8766 上 WS 升级 404」按裁定①A 钉实测：真实 Uvicorn 下未匹配升级回 HTTP 403（裸 socket 探测确认），ASGI 层为 WebSocketDisconnect(1000)；测试注释已注明。
- `WsServer.start()` 补了旧 `HttpServer.start()` 的 `cli_hub.reopen()` 语义（close→start 重开后 hub 重武装，AD-5），e2e reopen 用例钉住。

## Verification

**Commands:**
- `pytest tests/network/test_ws_server.py tests/network/test_http_ws_e2e.py tests/network/test_http_cli_ws.py -q` -- expected: 全绿
- `pytest tests/test_architecture_contracts.py -q` -- expected: 全绿（依赖边界零放宽）
- `pytest -q` -- expected: 全量绿（本机无 cov，见已知坑）
- `ruff check src tests && ruff format --check src tests && mypy src` -- expected: 全绿
- `bandit -r src/ -ll` -- expected: 无 HIGH/MEDIUM

## Spec Change Log

<!-- Append-only. step-04 填充。 -->

## Review Triage Log

<!-- 2026-10-24 step-04。运行时无子代理，经用户裁定由主会话自审（选项②）：三层指令（blind-hunter / edge-case-hunter / verification-gap）逐层执行，独立性弱化已如实注明。 -->

| # | 发现 | 判定 | 证据 / 路由 |
|---|---|---|---|
| 1 | `.env.example:332` AUTO_FIND 注释「默认 0 = 关闭」与 Settings 默认 10 矛盾，WS 复用该旋钮放大误导 | low（真） | 实测 grep 确认注释与 `config/__init__.py` 默认值冲突；影响用户对 WS 顺延行为的预期 → **patch**（已修：注释改为默认 10 + 修订出处） |
| 2 | cmd 级 WS_HOST/WS_PORT env → WsServer 配置的装配无测试（build_ws_server_config 有单测，命令层装配没钉） | low（真） | 读 test_cli_http.py：仅 ws_max_connections 有 cmd 级断言 → **patch**（已补 `test_ws_listener_env_reaches_ws_server_config`，44 passed） |
| 3 | `EmbeddedHttpService` 双 serve 循环之一意外死亡 → `failure` 传播无直接测试（现覆盖 = fake 单循环死亡 + 真实双 server 干净启停） | low（真） | 读 test_cli_http_lifecycle.py 确认；真实双 listener 故障注入测试中等复杂度 → **defer**（入 deferred-work.md） |
| 4 | `_serve_web` 的 gather：一侧 serve 循环异常时兄弟任务不被 gather 取消，close 后若异常收尾存在「exception never retrieved」窗口 | low（驳回） | 与旧行为同型（旧单 server 异常同样上抛 asyncio.run）；兄弟任务在 close 置 should_exit 后 0.1s 内自然退出，异常收尾窗口日常不可达；修复需重排任务管理，非直接修正 |
| 5 | `build_http_service(executor=None)` 且旁路关时，9001 绑定零端点 listener | false（驳回） | 生产唯一调用方 interactive.py 恒传 handler；49-1 形态是测试/程序化用法，回环空 listener 无害 |
| 6 | ws_host 从 http_server 私有导入 `_require_module`/`HttpDependencyError`（耦合味） | low（驳回） | 实施笔记已记录为接受；同包 mypy 钉住；修复需新共享模块（超直接修正），56-4 可收口 |
| 7 | frame.md 4.17 拓扑描述仍写 WS 挂 HTTP app（拆分前事实） | false（驳回） | spec「Never」冻结：4.17/4.18 全量重写归 56-4，intent 排除 |
| 8 | `_require_module` 文案「the HTTP entry point requires…」在 WS 路径触发时措辞不准 | false（驳回） | 可达性分析：WS 依赖集（starlette/uvicorn）与 HTTP 相同，能触发 WS 路径时 HTTP 必已先失败，文案在所有可达路径准确 |
| 9 | 无 `--ws-shutdown-timeout` CLI 选项 | false（驳回） | 与既有模式一致（`http_tool_inflight_timeout` 同样仅 env 可调），非本 story 引入的不一致 |
