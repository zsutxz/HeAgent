---
title: '56-9 客户端首次连接成功时下发服务器当前版本（WS hello 首帧）'
type: 'feature'
created: '2026-11-06'
status: 'done'
route: 'oneshot'
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** WS 客户端连接成功后拿不到服务端版本，无法判断对端版本与协议兼容性（HTTP 侧已有 `/api/health` 携带 version 且 web 客户端主动拉取；WS 侧缺位）。

**Approach:** WS 四端点（提交 / 单 run 订阅 / CLI 旁路 / 通知流）在 `accept()` 之后、任何配额/游标/关停判定之前立即下发首帧 `{"type":"hello","version":…}`；版本由入口层注入（`heagent.__version__`，经 `cli/http → WsServer → build_ws_app → builders` 参数链），传输层不读包元数据。历史注记：本 story 2026-11-06 首次立项时因并行会话在制代码污染调查（误判「已实现」）而撤回；并行实现其后撤出工作树，本次在净树重建，协议设计与撤回稿同构。

</frozen-after-approval>

## Implementation Notes

<!-- Agent-owned. Append-only during implementation: decisions made, files touched, surprises encountered. -->

**调查结论（2026-11-06 二次立项，净树 HEAD 3dec905 全部 `git show HEAD:` 对拍核实）：**

- HEAD 的 ws_protocol/ws_server/ws_host/cli/http 零 hello 符号（grep=0）；HTTP 侧 `http_server.py:1630` `/api/health` 携带 version、`web/app.js:1646` 主动拉取（此两处在前轮污染面之外，HEAD 真实存在）。
- 四个 accept 位点全在 `ws_server.py`：submit `:317`、subscribe `:445`、CLI 旁路（build_cli_ws_endpoint 内）、通知流（build_notification_ws_endpoint 内）；认证与 Origin 拒绝都在 accept 之前（被拒连接不经 hello，协议面天然不扩）。
- 装配链：`cli/http.py:576,580` 两处 `WsServer(...)`（version 注入点；`_current_version` 已在 display.py:108-117，HEAD 真实）→ `WsServer`（ws_host.py:251，`__init__` :254）→ `.app` 属性 → `build_ws_app`（ws_host.py，builder 调用位 :192-247）→ 四个 `build_*_endpoint`（ws_server.py :291/:424/:576/:731）。
- 测试面冲击评估：e2e（test_ws_e2e/test_cli_ws_e2e）不注入 version → 全走跳过路径 → 既有测试零改动即可通过（**非**「弹性收帧」：test_ws_e2e 是按数收帧的严格读，只是不注入版本所以无 hello；Blind Hunter #5 勘误）；首帧严格断言在 test_ws_server（fake ws）、test_notification_ws_e2e、test_cli_ws_wiring（`:37` 现读首帧为 event，需改为先读 hello 再读 event）。
- 版本参数缺省口径：`version: str = ""` 全链缺省，端点侧空版本**跳过 hello 但记 debug**（`ws event=hello_skipped reason=version_not_injected`）——生产装配恒注入，空版本=测试装配形态；对齐 D2「必须可见」家规（跳过可循证，不静默）。
- 协议契约（沿用撤回稿口径）：hello 不属于任何一条流——无 run_id/seq、不进环形缓冲、续传/游标语义逐字不变；客户端按「可忽略类型」处理。

## Review Triage Log

**Blind Hunter（2026-11-06，9 项 → 8 patch / 1 reject；审查代理因 API 限额中断但 9 项完整交付于结果载荷）**

| # | 主张 | 裁定 | 处置 |
|---|---|---|---|
| 1 | ws_manual_probe.py ping/submit/bad 严格读首帧 → hello 落地即误判（首方探针断） | high·真 | patch：`greet()` 助手 + 四 case（ping/submit/cancel/bad）前置消费 hello；sub/cli/handshake 循环内天然弹性不动 |
| 2 | 订阅端点（build_ws_endpoint）非空版本路径零覆盖 | medium·真 | patch：`test_subscribe_endpoint_sends_hello_before_unknown_run_error`（`_EmptyRunService` → UNKNOWN_RUN 判定，fake-ws 顺序钉） |
| 3 | 空版本跳过分支无钉（数十 e2e 隐式依赖） | medium·真 | patch：`test_empty_version_skips_hello_but_stays_visible`（帧面无 hello + caplog 钉 debug 痕，不静默契约入测） |
| 4 | sprint-status.yaml 缺 56-9 条目 | — | **reject（政策）**：sprint-status 本仓只读，bmad-build 明示跳过同步并每轮告知用户一次 |
| 5 | story Implementation Notes + epics.md 判据称 e2e「弹性收帧 any(...)」——实为 test_ws_e2e 按数收帧、不注入 version 走跳过路径才零改动 | medium·真 | patch：两处勘误（story `:30`、epics.md 判据 cell），订阅端点判据措辞同步对齐实际钉法（UNKNOWN_RUN 而非配额） |
| 6 | build_ws_app docstring 缺 version 参数说明 | low·真 | patch：docstring 补一句 |
| 7 | WsHelloFrame「必须注入」强于代码立场（缺省 "" 仅 debug 跳过） | medium·真 | patch：措辞对齐——「生产装配（cli/http）注入，由 wiring 测试钉死」；enforcement 在装配+测试而非运行时断言，如实陈述 |
| 8 | _RecordingWebSocket 缺 path_params/query_params（WebSocketLike 结构面不完整） | low·真 | patch：两属性补齐 |
| 9 | deploy/README.md 对外集成者指引缺 hello 首帧说明 | medium·真 | patch：listener 表后加「连接首帧（56-9 起）」blockquote |
