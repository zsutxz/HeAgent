# Epic 54 · WebSocket 入口周期 · Brief

> 立项：2026-10-23（需求勘察 + 草案）。同日第二轮完成接缝复核与四支真链路探针，**D1–D9 已由用户拍板冻结**。
> 本文是唯一决策记录；story 拆分见 `epics.md` 与 `stories/`，任一决策变更须经用户并回写本文。

## 背景

网络入口层现有 HTTP + SSE（Epic 49–50 交付）：SSE 是单向服务器推送，客户端取消须另发 `DELETE`，双向交互（cancel、后续可能的控制命令）要走两条通道。外部客户端（IDE 插件、桌面客户端等）需要单连接双向、低延迟的入口；WebSocket 为业界标准、客户端生态成熟。本 epic 在 `network/` 层新增 WS 入口，与 SSE 并存。

## 冻结决策（2026-10-23 用户拍板，变更须经用户）

| # | 决策 | 冻结值 |
|---|------|--------|
| D1 | 与 SSE 关系 | **并存**：SSE 为控制台前端既有契约不动；WS 面向新客户端 |
| D2 | 首期能力 | server→client 事件帧 + client→server 最小命令集 `{cancel, ping}`，命令有 `ack` 应答帧；错误一律 `error` 帧。**不经 WS 提交新 run、不做审批通道**（复用 `POST /api/runs` 与既有审批立场） |
| D3 | 连接粒度 | **单 run 订阅**，端点 `GET /api/runs/{run_id}/ws`（镜像 SSE 端点形状）；不做多路复用总连接 |
| D4 | 依赖 | `http` extra 显式追加 `websockets>=13.0,<18`（下界取 uvicorn `standard` extra 自身 floor；不依赖传递依赖，AD-11 同口径）。**不得依赖 ASGI denial response 发错误信封**（实测该实现有 bug，见接缝事实 4-②） |
| D5 | 续传语义 | 复用 ring buffer / 事件 seq / `resync_required` 口径；游标经**查询参数 `?last_event_id=N`**（比首帧更简，且与 SSE 的 `Last-Event-ID` 同源语义）；越窗 = accept 后发 `resync_required` 错误帧再关 |
| D6 | 连接限额 | WS **独立计数**（不与 `record.subscribers` 共享 SSE 池），新增 `http_ws_max_connections`（**per-run，默认 16**，`ge=1`）；限额检查与登记**同一步**完成 |
| D7 | 心跳 | **纯协议级** ping：`ws_ping_interval=15`（对齐 `SSE_HEARTBEAT_SECONDS=15.0`）、`ws_ping_timeout=20`；**不发应用层心跳帧** |
| D8 | 错误分布 | Origin 违规 = 未 accept 前 `close()`（客户端见 HTTP 403，无 body）；其余全部错误（`unknown_run` / `resync_required` / `rate_limited` / `invalid_request` / 服务关停）= accept 后发 `error` 帧再关 |
| D9 | 入站上界 | uvicorn `ws_max_size=64 KiB`（替代默认 16 MiB）+ 应用层命令帧文本 ≤ 4 KiB，超限 `close(1009)` |

## 接缝事实（2026-10-23 勘察 + 探针实测）

- 订阅机制现成：`_RunRecord.try_add_subscriber`（`network/http_server.py:368`，检查与登记同一步）+ ring buffer 重放 + 背压踢除 + `needs_resync`（`:654`）/ `stream_events`（`:872`）——WS 只换传输，不重写事件分发
- ⚠ **CSWSH 缺口**：三个中间件（`:1066` / `:1099` / `:1141`）对 `scope["type"] != "http"` 直接放行 ⇒ WS 升级请求绕过 Origin 同源防线。WS 层必须单独执行同口径 Origin 校验，拒绝即关闭（安全关键项，story 判据必含变异体）
- `_request_origin_violation`（`:998`）只读 `scope["headers"]`、不判 `scope["type"]` ⇒ WS scope **可直接复用同一判据**（不复制文案、不另写一套规则）
- **缺少 `Origin` = 非浏览器客户端（curl / 脚本），放行**（`:1010-1013` 注释与实现一致）；只有 `Origin: null` / 空 / 跨源才拒。WS 同口径
- 「断线只释放订阅者、绝不取消运行」既有立场（`frame.md` 4.17）——WS 关闭语义同口径
- 关停：`HttpRunService.close()`（`:672`）有界关停现成，WS 连接须纳入其关闭范围
- 错误文案单出口 `sanitize_message` / 错误信封 / 暴露告警（`exposure.py` 回环判定）均直接复用
- `http` extra 仅 starlette + uvicorn（`pyproject.toml:64-67`）；配置面 http_* 字段模式在 `config/__init__.py:394+`，`HTTP_*` 由 `catalog.py:388` 的 `listening_surface` 模式行分类（不进可写白名单 ⇒ 不进 `RESOURCE_CEILINGS`）；CLI 传参缝在 `cli/http.py:71-120`
- 硬约束不变：`network/` 不导入运行栈与配置；跨模块数据用 Pydantic 模型禁原始 dict

### 探针实测（2026-10-23，脚本存 `.heagent/tmp/epic54/`，已 gitignore）

1. `ws_smoke.py`：uvicorn 0.50.2 + `websockets` 17.3，`ws=auto` 选中 `WebSocketsSansIOProtocol`；在 `HttpServer` 同款 uvicorn 配置（`log_config=None` / `proxy_headers=False` / `lifespan="on"`）下握手、收发帧均正常。
2. `ws_denial2.py`：**ASGI denial response 在 sansio 实现下有 bug**——`send_denial_response()` 后 uvicorn 报 `ASGI callable returned without completing handshake.` 并补发 500，客户端得到 `InvalidMessage: did not receive a valid HTTP response`。legacy `ws="websockets"` 下正常回 `403` + JSON body，但该实现已 `UvicornDeprecationWarning` ⇒ **不钉 deprecated 实现、不把信封寄托在握手拒绝上**（D4/D8）。
3. `ws_denial2.py` 另一档：未 accept 直接 `close()` ⇒ 客户端稳定拿到 `InvalidStatus … HTTP 403`（无 body）⇒ 可作 Origin 拒绝的可执行判据。
4. `ws_nodep.py`：`websockets` 缺席（http extra 未装全）时 WS 升级回 **404**，uvicorn 日志明确给出 `No supported WebSocket library detected …`；`/api/health` 照常 200 ⇒ 缺依赖不拖死 HTTP，但入口层须自给安装诊断（story 判据）。
5. uvicorn `limit_concurrency` 只作用于 HTTP 协议（`protocols/http/h11_impl.py:225`、`httptools_impl.py`），WS 协议只把连接计入 `server_state.connections` **从不判额** ⇒ `http_max_connections` 管不到 WS，不设限就是「每连接一个 512 事件队列」的无界内存放大（D6 依据）。
6. uvicorn 默认 `ws_max_size=16 MiB` / `ws_ping_interval=20s` / `ws_ping_timeout=20s`（`config.py:201-204`）⇒ D7/D9 是显式收紧，不是新增机制。

## 期一范围（story 映射见 `epics.md`）

1. `network/ws_protocol.py`：Pydantic 消息封套（事件帧 / 命令帧 / 应答帧 / 错误帧）+ 帧上界常量，错误码复用 `HttpErrorCode` 封闭枚举 → 54-1
2. 依赖与配置：`websockets` 进 http extra；`http_ws_max_connections` 等旋钮进 Settings / `HttpServerConfig` / CLI → 54-2
3. WS 端点：单 run 事件订阅（实时 + 按游标续传）+ `cancel`（等价 DELETE 语义：首个终态获胜、幂等）+ `ping` → 54-3
4. CSWSH 防线：WS 升级请求 Origin 校验（与 `_request_origin_violation` 同口径）→ 54-3
5. 测试与文档：订阅/续传/取消/Origin 拒绝/限额/断线不取消 run；契约测试；`frame.md` 4.17/4.18 与 AGENTS.md network 行同步 → 54-3（判据）+ 54-4（文档与质量门）

## 非功能需求

- **安全**：Origin 校验覆盖 WS 升级；错误信封与 `sanitize_message` 口径不变；无认证/回环告警立场与 HTTP 一致（复用 `exposure.py` 单点，不复制文案）
- **限额**：WS 连接上限的检查与登记在同一步完成（吸取 2026-09-27 SSE 订阅者并发穿透修复教训）；超额按 D8 口径回稳定错误码 `rate_limited`
- **生命周期**：`close()` 有界关闭所有 WS；断线不取消 run；心跳 = 协议级 ping/pong（D7），**不发应用层心跳帧**
- **内存上界**：单 WS 连接入站帧 ≤ 4 KiB（应用层）+ 64 KiB（协议层 `ws_max_size`），事件出站沿用既有截断口径（D9）
- **兼容**：SSE 行为零改动；`network/` 依赖方向约束零放宽

## 验收标准

1. 客户端经 WS 收到 run 事件（text / tool_call / tool_result / 终态），seq 单调、文本截断口径与 SSE 一致
2. 断线重连续传：游标在窗口内补齐缺失事件；越窗收 `resync_required` 错误帧（D5）
3. `cancel` 命令与 `DELETE /api/runs/{id}` 语义等价（首个终态获胜、幂等、不触碰其它 run）
4. 跨源 Origin 的 WS 握手被拒（HTTP 403，无 body）；**缺少 Origin 则放行**（非浏览器客户端口径，与 HTTP 逐字一致）。变异体测试须证明：伪造跨源 Origin / 伪造 Host / 端口不符三种都被拒；而「把无 Origin 判违规」会让合法客户端全挂 ⇒ 无 Origin 放行必须有正面判据
5. 服务关停时所有 WS 连接有界关闭，在途 run 走既有 cancelled 终态
6. 超限连接第 N+1 个收到 `rate_limited` 错误帧（不是裸断连）；`websockets` 缺依赖时 WS 升级 404 且 HTTP 不受影响
7. `pytest` 全绿（本地不带 cov）、`ruff check` / `ruff format --check` / `mypy` / `bandit -ll` 干净、`test_architecture_contracts.py` 通过

## 冻结边界

- 不做（期三另裁）：经 WS 提交 run、审批通道、多 run 复用连接、控制台前端切换 WS
- 不改 SSE 既有行为与契约
- 不放宽 AGENTS.md 依赖方向与安全声明立场（WS 同样非安全边界，OS 沙箱兜底立场不变）
