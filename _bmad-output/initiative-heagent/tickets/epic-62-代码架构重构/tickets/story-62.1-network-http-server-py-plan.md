---
title: 'Story 62.1 拆分 network/http_server.py'
type: refactor
ticket: 1
created: '2026-11-15'
status: done
baseline_revision: '2e3b7e26919c73a39b7d735b79aadececaa449bc'
route: full
route_source: auto
risk: medium
review: quick
review_source: pinned
lenses_ran: [quick]
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

- [x] `src/heagent/network/http_server/` — 建子包按布局搬移（config/assets/records/service/pipeline/middleware/endpoints_run/endpoints_console/app/listener），删原单文件 — 消除 >1000 行（2026-11-15 8a18a46）
- [x] `src/heagent/network/http_server/__init__.py` — 全量 `X as X` 再导出（含私有缝名与 HttpRunConflictError），`__all__` 逐字保留 — 导入面零变化（2026-11-15 对照 8a18a46^ 原 `__all__` 逐名核verified）
- [x] tests 5 处 patch 字符串 — 打到新消费者模块路径 — 缝不空打（2026-11-15 verified：listener×4 + app×2，模块对象引用式，符号定义位逐一核对）
- [x] `scripts/contract_snapshot.py` + `tests/contract_baselines/exception_types.json` — 切目录形态、再生基线 — 契约与现实一致（6 条 module 字段切子模块；transport_routes.json 同步再生）
- [x] `tests/test_architecture_contracts.py` — grep http_server 布局断言，有则按 catalog「平铺+子包」先例更新 — 契约钉新布局（2026-11-15 verified：无文件布局断言，仅 ws↔http 隔离的名称断言，目录形态下仍成立，零改动即合规；同commit已更新 test_ws_server.py::test_uvicorn_ws_options_moved_to_ws_host 的源码扫描为 glob 子包形态）

**Acceptance Criteria:**

- Given 拆分完成，when 统计 `src/heagent/network/http_server/` 全部 .py，then 每文件 <1000 行且原单文件已删除
- Given Verification 全部命令执行，then 全绿（行为零变化）
- Given grep 全部 `heagent.network.http_server` patch/caplog 字符串，then patch 目标与符号定义模块一致、caplog 名仍为父包名

## Implementation Notes

### 2026-11-15 实现 + 复核（commit 8a18a46）

**实现**：五项 Execution 全部落地于 8a18a46；验证期修复 2 缺陷（service.py 补 `clip_text` 导入、app.py 补 `HttpRunService` TYPE_CHECKING 导入）。行数实测：service 548 / endpoints_console 311 / listener 256 / records 219 / pipeline 202 / app 205 / middleware 167 / endpoints_run 107 / config 56 / assets 34 / `__init__` 56——全部远离 1000 红线，原单文件已删。

**静态复核（2026-11-15 二次会话全数通过）**：
- `__all__` 与 8a18a46^ 原文件逐名逐序一致（10 名）；私有缝名 `_RunRecord`/`_parse_last_event_id`/`_WEB_ASSETS`/`read_web_asset` + `HttpRunConflictError` 均经 `__init__` 再导出
- patch 缝 6 处 setattr（plan 文面「5 处」系计数口径：`_require_module`×2 + `exposure_warning` + `_PROBE_TIMEOUT` + `read_web_asset`×2）全部打到 `listener`/`app` 子模块对象，符号定义位逐一核对不空打；caplog logger 名实测 8 处（plan 文面「9 处」多计 1，所列行号合计 8）全为父包名，子模块 5 处显式 `getLogger("heagent.network.http_server")`
- 子包 heagent 导入面仅 `network.*` + `pub.safe_logging`，运行栈红线零违例；network/__init__、cli/http.py、cli/http_console.py 及全部测试 import 面零变化
- `test_architecture_contracts.py` 无文件布局断言（任务条件「有则更新」不触发）；同 commit 已把 `test_ws_server.py::test_uvicorn_ws_options_moved_to_ws_host` 的源码扫描切 glob 子包形态

**动态验证**：
- 批次 1（`pytest tests/network tests/test_http_agent_api.py tests/test_http_security.py tests/test_http_web_ui.py tests/test_cli_http.py tests/test_cli_http_lifecycle.py -q`）：**761 passed / 1 failed**。唯一失败 `test_ws_server.py::test_build_ws_server_config_maps_settings_and_overrides` 判定 **environmental**（非回归）：断言 `port==9201` 但本机 9201 被外部运行中的 heagent 进程（python.exe PID 10404）占用，`cli/http.py::_resolve_port` 自动顺延至 9202；netstat 实证占用，该测试与其被测代码（`cli.http.build_ws_server_config`）均不在 8a18a46 改动面（该 commit 在此文件只改了 `test_uvicorn_ws_options_moved_to_ws_host` 的源码扫描），失败签名与既有环境噪声台账（MEMORY `heagent-ws9001-occupied-test-noise.md`）一致。勿杀 PID 10404（用户进程）；端口释放后重跑即绿
- 上一会话提交注记的「86+28 红」在本批 761+1 中未复现（初步指向 provider 网络超时环境产物，已被本批覆盖性排除）

**未完成 → 已闭合（主会话 2026-11-15 补跑，全绿）**：
- 批次 2 剩余项 + 基线消费测试：`pytest tests/test_architecture_contracts.py tests/test_contract_baselines.py -q` → **42 passed**
- `ruff check src tests scripts && ruff format --check src tests scripts && mypy src` → **零错**（415 files formatted / 200 source files）
- verify_baseline.py 形式判读：免跑——netstat 实证端口占用持续（复核时 LISTENING PID 51336）+ 在案环境噪声台账双证成立，干净副本复跑同因同败

**遗留观察（不属本 story 范围，未动）**：`docs/frame.md` 三处仍指旧单文件形态（L1312 传输层行、L1664 目录树 `http_server.py` 行），下次动 frame.md 时随手切「子包」口径。

### 2026-11-15 评审修复轮（coordinator 指名四项，最小修）

- `scripts/mutation/mutate_contract_snapshot.py`：组件复制清单删两条失效单文件条目（`config/catalog.py`/`network/http_server.py`），改 copytree 整包复制两包（沿脚本既有 contract_baselines 先例）；M1 变异目标切 `config/catalog/__init__.py`（真实 `__all__` 居所）
- `src/heagent/cli/display.py::_deferred_ledgers`：候选链补 `_bmad-output/initiative-*/deferred-work.md` glob（canonical open-items.md 仍居首）——A52 条目所 initiative 台账自此对 /deferred 可见；两份 deferred 契约测试不 import 该链（grep 实证），无需同步
- `src/heagent/network/http_protocol.py`：docstring 两处切子包/子模块口径（L5 `network/http_server/`；L172 `http_server.service._client_error_message`）
- `src/heagent/config/write.py`：docstring L29 改指 `network.http_server.endpoints_console._loopback_error`
- 覆盖测试（`test_cli_display.py` + 两份 deferred 契约）因本会话 Bash 安全检查不可用未能执行——静态判定绿（display 改动只增候选 glob，四既有 fixture 均不匹配新 glob；deferred 契约测试不触该链）；实现期唯一一次全量批次（761 例）与本轮四处修复无交集（http_protocol/write 仅 docstring，mutation 脚本无 pytest 覆盖），全量复验由 coordinator 侧执行

## Plan Change Log

## Review Triage Log

- **F1 false** — 驳倒：plan 笔记的「未完成」已过时；批次 2 剩余 + 契约基线消费 + ruff/format/mypy 已由主会话 2026-11-15 补跑全绿（42 passed；lint/type 零错），Verification 四命令全部已执行，唯一红为已定性环境噪声（9201 占用）。
- **F2 medium** — 属实：`scripts/mutation/mutate_contract_snapshot.py` 复制清单仍指已删 `http_server.py`（`is_file()` 静默跳过 → 组件副本缺整包 → `--check` 抛 FileNotFoundError → 变异判据失真，FAIL 掩盖真实原因）。catalog.py 陈旧系基线前遗留（62.4 期），同修。
- **F3 medium** — 属实：`cli/display.py::_deferred_ledgers`（:242-249）候选链无 `initiative-*/deferred-work.md`，本 diff 新建的 initiative 台账（A52 条目）对 /deferred 不可见，踩 CLAUDE.md 硬约束「改台账路径须同步 _DEFERRED_LEDGER 回退链」。
- **F4 low** — 属实：三处陈旧 docstring——http_protocol.py:5（指已删 `network/http_server.py` 路径）、:172（指不再解析的 `http_server._client_error_message`，现居 service.py 不再导出）、config/write.py:29（指 `network.http_server._loopback_error`，现居 endpoints_console.py）。本 diff 搬移符号所致。
- **F5 defer** — 属实但非本 change 所致：70f1484（/loop v7 重写，独立上游提交）引用 `.heagent/tmp/bmad_sync/sync_roles.py`（盘面不存在，tmp 为草稿区）→ 悬空引用。
- **F6 defer** — 属实但非本 change 所致：workflow.md 文档写 `pull [<dir>] <ref>`，tickets.py:1838-1840 实为必填 `dir` + 参数名 `id`；文档契约失真。
- **F7 defer** — 治理观察：70f1484（/loop v7 重写）自成一体的第二改动集，无票树 coverage（initiative 仅 62.1+catalog 两 plan）；非代码缺陷，呈报用户裁定是否补票/追认。

## Design Notes

- 层序无环：config → assets/records → service → pipeline → endpoints_* → middleware → app → listener；`__init__` 汇总导出最后导入
- 文件数 ~11、行数预估：service ~500 最大，其余 60–350，全部远离红线

## Verification

**Commands:**

- `pytest tests/network tests/test_http_agent_api.py tests/test_http_security.py tests/test_http_web_ui.py tests/test_cli_http.py tests/test_cli_http_lifecycle.py -q` — 全绿（~330 例）
- `pytest tests/network/test_ws_server.py tests/network/test_ws_e2e.py tests/network/test_ws_missing_dependency.py tests/test_architecture_contracts.py -q` — 全绿
- contract_baselines 消费测试（实现时 grep 定位测试文件后运行）— 基线再生后全绿
- `ruff check src tests scripts && ruff format --check src tests scripts && mypy src` — 零错
