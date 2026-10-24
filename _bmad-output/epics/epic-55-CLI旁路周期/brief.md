# Epic 55 · CLI 旁路周期 · Brief（回溯补记）

> **流程声明**：本周期未走 brief → 拍板 → story 拆分流程，代码与测试于 2026-10-23/24 直接实现，后随压缩提交 98ef6d8 入库。本文为 2026-10-24 回溯补记，把已实现的设计决策从代码注释提升为决策记录。**代码为事实权威**，本文如有出入以代码为准。

## 背景

CLI 终端里跑的那一轮 run（单次 / 交互）在 Epic 49–54 的 HTTP run 服务之外：没有 `_RunRecord`、不占 `HTTP_MAX_INFLIGHT_RUNS` 名额、不写会话历史。但外部客户端需要看到终端在跑什么——本周期交付**旁路**：把终端轮次的事件按同一套 `RunEventPayload` 契约经 `WS /api/cli/ws` 广播给订阅者。定位是**观众席**，不是控制台。

## 决策记录（从实现回溯，已随代码落地）

| # | 决策 | 值 | 代码落点 |
|---|------|----|----------|
| D1 | 定位 / 所有权 | 旁路**不拥有运行**：终端是唯一所有者与唯一写者。不建 RunRecord、不占在途名额、不写 HTTP 会话历史、不开取消通道（`cancel` 回错误帧且**不断连**——做成「不支持」而不是静默忽略，让客户端知道连的是观众席；取消通道 = Ctrl+C / 双击 Esc） | `cli_event_hub.py` 模块 docstring；`ws_server.py` `_cli_handle_commands` |
| D2 | 端点与粒度 | `WS /api/cli/ws`，**跨轮次单流**：不按 run_id 路由，一条流看所有轮，`run_id` 逐帧携带；`cli_hub=None` 时不注册该路由（404），与 `run_service` 互相独立（旁路不因网页侧有无 run 服务而存在或消失） | `http_server.py:131-132`、`build_http_app` docstring；`ws_protocol.py:86-96` |
| D3 | 帧契约 | 事件帧 `WsCliEventFrame` 与 `WsEventFrame` **分开**（不加字段）：run WS 一连接一 run、run_id 由 URL 承担，旁路跨轮、run_id 必须逐帧携带。ack 帧 `WsCliAckFrame` **不带 RunStatus**（避免「这个连接能控制运行」的假象），`run_id` 空串 = 此刻终端没有在跑的轮次。命令面仅 `ping`→ack、`cancel`→错误帧 | `ws_protocol.py:86-113`；`ws_server.py:292-326` |
| D4 | 状态源 | `CliEventHub` 唯一状态源：独立 seq（跨轮单调）、256 条环形缓冲（CLI 一轮事件量远小于网页 run，且订阅者通常在本机）、订阅队列与缓冲同界。三条不变量：写侧同步无 await；`publish_*` 绝不抛（故障降级为少一条事件，**绝不打断终端 run**）；背压踢除与 SSE/WS 同语义 | `cli_event_hub.py:36-41, 8-16, 169-197` |
| D5 | 续传语义 | 与 SSE / run WS 完全同口径：`?last_event_id=N` 游标、`needs_resync` 同语义（越窗 = `resync_required` 错误帧 + close 1008，提示去游标重连）、背压踢除后客户端按游标续传 | `cli_event_hub.py:122-131`；`ws_server.py:361-377` |
| D6 | 限额 | **按 hub 计**而不是按 run 计（旁路只有一条流，与 `/api/runs/{id}/ws` 的每 run 额度是不同口径）：`max_connections` 默认 16（与 `HTTP_WS_MAX_CONNECTIONS` 同值、语义独立）。限额检查 + 重放快照 + 登记在**同一个同步调用**内完成（防并发穿透，2026-09-27 SSE 教训口径） | `cli_event_hub.py:64-68, 201-215` |
| D7 | 防线 / 关停 | Origin 校验与 run WS 同口径（未 accept 前 close → 客户端拿 HTTP 403；判据由 http_server 单点注入）；关停 = `shutting_down` 错误帧 + close 1001，`close_websockets` 有界收尾；双协程收尾共用 `_supervise`（任一路结束取消另一侧，防「Task exception was never retrieved」） | `ws_server.py:343-349, 147-162`；`cli_event_hub.py:251-269` |

## 交付物（已落工作区，未提交）

- `src/heagent/network/cli_event_hub.py`（新增：CliEventHub / CliSubscription）
- `src/heagent/network/ws_server.py`（`build_cli_ws_endpoint` + `_supervise`）
- `src/heagent/network/http_server.py`（`/api/cli/ws` 装配 + `cli_hub` 注入缝）
- `src/heagent/network/ws_protocol.py`（`WsCliEventFrame` / `WsCliAckFrame`）
- 测试：`tests/network/test_cli_event_hub.py`、`tests/network/test_http_cli_ws.py`、`tests/test_cli_ws_publish.py`、`tests/test_cli_ws_wiring.py`
- 发布接线在 cli/ 侧（终端轮次 begin/publish/end），由 publish / wiring 两个测试文件钉住

## 冻结边界（回溯认定）

- 不做：经旁路取消运行（终端独占取消通道）、经旁路提交 run、旁路写会话历史
- 与 Epic 54 的关系：复用其帧协议、错误信封、续传口径与 Origin 防线；连接额度语义按 hub 独立
- 与 Epic 56 的关系：`/api/cli/ws` 留**本机监听器**（Epic 56 D7 提议值，旁路是本机终端语义，不随对外入口暴露）

## 遗留

- 无 story 拆分与 sprint-status 登记（流程缺口；本补记即弥补动作，不再补拆 story）
- 代码已随 98ef6d8（16 笔压缩提交）入库；装配开关 `HTTP_CLI_WS_ENABLED`（默认关）与质量门实测见该提交记录（本文不代称「已验证」）
