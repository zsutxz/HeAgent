---
title: 'Story 62.1 拆分 network/http_server.py'
type: refactor
ticket: 1
created: '2026-11-15'
status: in-progress
baseline_revision: '2e3b7e26919c73a39b7d735b79aadececaa449bc'
route: full
route_source: auto
risk: medium
review: ''
review_source: ''
lenses_ran: []
review_loop_iteration: 0
context:
  - 'docs/frame.md'
  - '_bmad-output/initiative-heagent/tickets/epic-62-代码架构重构/epic-62-代码架构重构.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `network/http_server.py` 1913 行，远超单文件 <1000 行红线（NFR3），是 epic-62 第一顺位（零依赖）拆分对象。

**Approach:** 拆为 `network/http_server/` 子包，按内聚分模块（config/assets/records/service/pipeline/middleware/endpoints_run/endpoints_console/app/listener），`__init__.py` 全量 `X as X` 再导出使公开 API 与导入面零变化（catalog 先例 e3554e3）。

**Decision (2026-11-15 用户裁定):** 布局采用内聚模块（上述 10 模块）；票面 routes/handlers/middleware 三分法经调查否决——HttpRunService 660 行既非 route 也非 handler。

## Boundaries & Constraints

**Always:**

- 公开导入面零变化：`__all__` 10 名逐字保留；`HttpRunConflictError`（cli/http_console.py:64 隐式依赖）与测试引用的私有名 `_RunRecord`/`_parse_last_event_id`/`_WEB_ASSETS`/`read_web_asset` 全部经 `__init__.py` 再导出
- monkeypatch 缝（已 grep 全集）：5 处 setattr patch（`_require_module`×2、`exposure_warning`、`_PROBE_TIMEOUT`、`read_web_asset`×2）随消费者搬新模块后同步更新 patch 字符串；9 处 caplog logger 名零改动——子模块显式 `logging.getLogger("heagent.network.http_server")`（catalog 先例，对 `__name__` 惯例的有意偏离）
- network/ 红线：子包禁导入 agent/engine/providers/tools/memory/skills/context/cron/events/config；无循环依赖；ws_* 仍不得 import http_server
- 行为零变化：路由/响应形状/错误信封/安全头/中间件装配顺序/日志事件名逐字节保持；新文件全部 <1000 行
- `scripts/contract_snapshot.py` 切目录形态并再生 `tests/contract_baselines/exception_types.json`（6 条 module 字段随定义位置更新）
- 本机 Windows：pytest 不带 --cov；subprocess 显式 encoding="utf-8"

**Never:**

- 不改端点行为/中间件顺序/CSP；不顺手做 A54 残余②③⑥⑦；不动 ws_* 与 http_protocol.py/event_stream_hub.py（只消费）；A52 已拆出本 plan（登记 initiative deferred-work.md）

</frozen-after-approval>

## Code Map

- `src/heagent/network/http_server.py` — 被拆对象（1913 行）。分组：常量 L104-162；`HttpStartupError` L165；`HttpServerConfig` L169-206；`read_web_asset` L209；`_client_error_message` L223；`_RunRecord` L236-397；`RunEventPublisher` L400-425；`HttpRunService` L428-907（start_run L495/_finalize L597/看门狗 L689-760/_execute L762/stream_events L871）；`_send_json` L913；中间件×3 L927-1030；请求管线 L1033-1189（_read_body L1045/_read_model L1061/_CONSOLE_ERROR_STATUS L1097/format_sse L1147/_parse_last_event_id L1169）；端点装配 L1192-1554（run/project/session/config/dialog）；`build_http_app` L1557-1692；`HttpServer` L1695-1899；`__all__` L1902-1913
- 共享状态耦合：service 直接持有 _RunRecord 全字段；端点闭包→service.stream_events/needs_resync/cancel_run + pipeline helper；app→middleware+assets+`_require_module` 别名（L75-76 保缝导入）；listener→app 属性/exposure_warning/_PROBE_TIMEOUT
- `src/heagent/config/catalog/` — 布局范本：`__init__.py:25-204` 全量 `X as X`；子模块 logger 用父包名
- `src/heagent/network/optional_deps.py:7-8` — `_require_module` 别名缝模式出处
- `scripts/contract_snapshot.py` — :70 ROUTE_MODULES；:77-79 HTTP_SERVER_MODULE 与 _CONSOLE_ERROR_STATUS 提取；:214 listener 判定（rel_path 含 "http_server" 在目录形态下仍成立）；expand_modules :55-66 已支持目录
- `tests/contract_baselines/exception_types.json:523-554` — 6 条 module=heagent.network.http_server 待再生
- patch 缝位点：tests/test_cli_http.py:395、tests/test_cli_http_lifecycle.py:259（_require_module）；tests/network/test_http_server.py:325（exposure_warning）、:375（_PROBE_TIMEOUT）、:442/:459（read_web_asset）
- caplog logger 名 9 处（零改动）：test_http_run_service.py:731,764,858,875；test_http_server.py:327,337；test_http_security.py:282,297
- 架构契约：tests/test_architecture_contracts.py:82-96 FORBIDDEN_RUNTIME_IMPORTS["network"]（:133-144 逐级前缀已覆盖子包）；:1041-1059 ws 断言
- 导入面（经 __init__ 再导出后零变化）：network/__init__.py:4、cli/http.py:41-47、cli/http_console.py:64-68、tests 16 处 import

## Tasks & Acceptance

**Execution:**

- [ ] `src/heagent/network/http_server/` — 建子包按布局搬移（config/assets/records/service/pipeline/middleware/endpoints_run/endpoints_console/app/listener），删原单文件 — 消除 >1000 行
- [ ] `src/heagent/network/http_server/__init__.py` — 全量 `X as X` 再导出（含私有缝名与 HttpRunConflictError），`__all__` 逐字保留 — 导入面零变化
- [ ] tests 5 处 patch 字符串 — 打到新消费者模块路径 — 缝不空打
- [ ] `scripts/contract_snapshot.py` + `tests/contract_baselines/exception_types.json` — 切目录形态、再生基线 — 契约与现实一致
- [ ] `tests/test_architecture_contracts.py` — grep http_server 布局断言，有则按 catalog「平铺+子包」先例更新 — 契约钉新布局

**Acceptance Criteria:**

- Given 拆分完成，when 统计 `src/heagent/network/http_server/` 全部 .py，then 每文件 <1000 行且原单文件已删除
- Given Verification 全部命令执行，then 全绿（行为零变化）
- Given grep 全部 `heagent.network.http_server` patch/caplog 字符串，then patch 目标与符号定义模块一致、caplog 名仍为父包名

## Implementation Notes

## Plan Change Log

## Review Triage Log

## Design Notes

- 层序无环：config → assets/records → service → pipeline → endpoints_* → middleware → app → listener；`__init__` 汇总导出最后导入
- 文件数 ~11、行数预估：service ~500 最大，其余 60–350，全部远离红线

## Verification

**Commands:**

- `pytest tests/network tests/test_http_agent_api.py tests/test_http_security.py tests/test_http_web_ui.py tests/test_cli_http.py tests/test_cli_http_lifecycle.py -q` — 全绿（~330 例）
- `pytest tests/network/test_ws_server.py tests/network/test_ws_e2e.py tests/network/test_ws_missing_dependency.py tests/test_architecture_contracts.py -q` — 全绿
- contract_baselines 消费测试（实现时 grep 定位测试文件后运行）— 基线再生后全绿
- `ruff check src tests scripts && ruff format --check src tests scripts && mypy src` — 零错
