---
stepsCompleted: []
status: draft
inputDocuments:
  - docs/frame.md
  - _bmad-output/epics/epic-54-WebSocket入口周期/brief.md
---

# HeAgent - Epic Breakdown（Epic 54：WebSocket 入口）

在 `network/` 层新增 WebSocket 入口：单 run 订阅（实时 + 按游标续传）+ `{cancel, ping}` 最小命令集，
与既有 HTTP + SSE 并存、SSE 零改动。WS 补齐 SSE 缺的双向能力（单连接内取消），并**单独补齐 CSWSH
防线**——既有三个 ASGI 中间件对 `scope["type"] != "http"` 直接放行，WS 升级拿不到 Origin 校验。

**立场口径**：WS 与 HTTP/SSE 同样是**入口面，不是安全边界**；无认证 / 无 TLS / 回环不等于可信的既有
声明逐字适用。OS 级沙箱兜底立场不变（`AGENTS.md` 安全声明）。

## Story 列表

| Story | 名称 | 依赖 | 状态 | 交付物 | 验收要点 |
|---|---|---|---|---|---|
| 54-1 | WS 帧契约与协议封套 | 无 | done | `network/ws_protocol.py`：`WsFrameType` / `WsCommand` 封闭枚举，`WsEventFrame` / `WsAckFrame` / `WsErrorFrame` / `WsCommandFrame` 四个 Pydantic 封套；帧上界常量（`WS_MAX_INBOUND_CHARS=4096`、D9 相关关闭码）；`RunEventPayload` / `ErrorEnvelope` / `HttpErrorCode` 一律**复用不复制** | 帧 round-trip 与 `extra="forbid"` 判据；未知帧类型 / 未知命令拒；错误码 ∈ `HttpErrorCode`；`WS_PING_INTERVAL_SECONDS == SSE_HEARTBEAT_SECONDS` 判据；`network/` 依赖面零放宽 |
| 54-2 | 依赖与配置面 | 54-1 | done | `pyproject.toml` http extra 追加 `websockets>=13.0,<18`（D4）；`Settings.http_ws_max_connections`（默认 16，`ge=1`，D6）；`HttpServerConfig.ws_max_connections` + uvicorn 参数接线（`ws_ping_interval=15` / `ws_ping_timeout=20` / `ws_max_size=64KiB`，D7/D9）；`cli/http.py` 传参缝与 `--ws-max-connections`；`.env.example` 同步 | 配置面三处同步判据（`.env.example` 文档判据 + `catalog.classify` 归 `listening_surface`）；`HttpServerConfig` 默认值与 `Settings` 一致；CLI 覆盖优先于 Settings；**缺 `websockets` 时 `http-server` 启动不崩**并给安装诊断 |
| 54-3 | WS 端点：订阅、续传、命令与防线 | 54-1, 54-2 | done | `network/http_server.py`：`_RUN_WS_PATH = "/api/runs/{run_id}/ws"` + `WebSocketRoute`；握手前 Origin 校验（复用 `_request_origin_violation`，D8）；accept 后队列登记（独立计数，检查与登记同一步，D6）；读/写双任务（事件下发 + 命令处理 + 断线检测）；`cancel` 复用 `cancel_run`；`ping` 回 `ack`；续传游标 `?last_event_id=N`（D5）；纳入 `HttpRunService.close()` 有界关停 | 六条判据组逐一有测试（含变异体精确变红）：Origin 跨源/伪造 Host/端口不符拒 + **无 Origin 放行**；限额第 N+1 个收 `rate_limited` 帧；越窗 `resync_required`；`cancel` 幂等且不触碰其它 run；**断线不取消 run**；关停有界且终态 `cancelled` |
| 54-4 | 文档、契约与质量门 | 54-3 | done | `docs/frame.md` 4.17/4.18（WS 段、错误码表、配置表、依赖面、已知缺口口径）；`AGENTS.md` network 行与安全声明；`tests/test_architecture_contracts.py` 同步（`network/` 依赖面 + 新模块）；真回环 e2e 判据；全量质量门亲跑并登记实测数字 | `frame.md`/`AGENTS.md` 无「WS 更安全」这类扩大宣称；架构契约零改动或同步后全绿；真 listener 上跑通「事件 + 续传 + cancel + Origin 拒绝」四态；`pytest` + `ruff check` + `ruff format --check` + `mypy` + `bandit -ll` 全绿 |

## 实施约束

1. 交付顺序 `54-1 → 54-2 → 54-3 → 54-4`；54-3 的**安全判据（Origin / 限额）与端点同批落地**——不得先合入一个不设防的 WS 端点再补。
2. **D1–D9 冻结在 `brief.md`**，任一变更须经用户裁定并回写 brief；实现期发现与冻结值冲突（如 uvicorn 行为变化）时**先报告再改**，不静默偏离。
3. 传输层职责边界不变：`network/` 不导入运行栈与配置；跨模块数据一律 Pydantic 模型（`pub/types.py` / 本层协议模型），**禁原始 dict**。
4. 事件分发**不重写**：复用 `_RunRecord` 的 ring buffer / seq / 背压踢除 / `needs_resync`；WS 只换传输与命令通道。`stream_events` 若需「不做心跳超时」的形态，只允许**追加可选参数**，SSE 默认行为逐字不变。
5. **错误信封单出口**：WS `error` 帧内容必须由既有 `error_envelope` + `sanitize_message` 生成，不新写文案；`HttpErrorCode` 是封闭枚举，WS 不新增错误码（D8 复用之）。
6. **Origin 判据单源**：WS 握手调 `_request_origin_violation`，不复制规则；跨源拒绝时**不**透露允许的 host 集合（与 HTTP 一致）。
7. **限额原子性**：WS 订阅者的「检查 + 登记」必须在同一个无 `await` 的同步方法内完成（对标 `try_add_subscriber` 的 A9③ 修复），否则并发连接能穿透上限。
8. **断线语义**：连接关闭只注销订阅者与连接登记，**绝不**取消运行；取消只能来自显式 `cancel` 命令或 `DELETE`。
9. **不引入应用层心跳帧**（D7）：SSE 的心跳是「SSE 无协议保活」的补偿，WS 有协议级 ping/pong，再加应用帧会让帧契约多一种类型并逼客户端分辨。
10. 新增 Settings 字段按既有三处同步口径：`.env.example` + `catalog.classify` 归组（`HTTP_*` 由 `catalog.py:388` 模式行归 `listening_surface`，不进可写白名单 ⇒ 不进 `RESOURCE_CEILINGS`）+ `docs/frame.md` 配置表与字段计数。
11. 每个 story 的验证命令是规划口径，执行后登记**实测**结果；引用不存在的文件/行号按实测更正（不伪造未运行命令）。
12. CI `test` job 装 `.[dev,http]` ⇒ `websockets` 随 http extra 自动可用；测试仍按既有惯例 `pytest.importorskip("starlette")` 兜底缺依赖环境。

## 决策 → story 映射

| 决策 | 落点 |
|---|---|
| D1 并存、D3 单 run 端点 | 54-3（路由与订阅面） |
| D2 首期能力（事件 / `{cancel,ping}` / `ack` / 错误帧） | 54-1（封套）+ 54-3（行为） |
| D4 依赖与「不依赖 denial 通道」 | 54-2（extra）+ 54-3（拒绝形态） |
| D5 续传与游标 | 54-3 |
| D6 独立限额 | 54-2（旋钮）+ 54-3（同一步登记） |
| D7 协议级心跳 | 54-2（uvicorn 参数） |
| D8 错误分布 | 54-3（Origin 裸 403 / 其余错误帧） |
| D9 入站上界 | 54-2（`ws_max_size`）+ 54-1（应用层 4 KiB 常量）+ 54-3（超限关闭） |
