---
title: '58-2 入口接线：两个变量 + cron notifier + 终端回显 + 文档/契约收口'
type: 'feature'
created: '2026-10-28'
status: 'ready-for-dev'
route: 'dispatch'
review_loop_iteration: 0
baseline_commit: 'a372f2b80ce308b81426be82c361827c12912676'
context: []
---

<!-- 交付物与验收边界 = epic-58 epics.md 的 D2/D4/D5/D6；依赖 58-1 的 NotificationHub 与端点。 -->

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 58-1 只交付了「能力」（中枢 + 端点），没有任何东西往里发布；同时用户要求
「终端也要看到 cron 结果，但要由变量控制」。当前 `cron runner`（`cli/wiring.py:383`）拿到
`loop.run(prompt)` 的返回值就丢掉，终端与网络两侧都拿不到。

**Approach:** 给 `build_cron_job_runner` 加一个**注入式回调** `cron_notifier`（入口层构造、wiring 只调用），
一次 cron 执行产出**一条**通知；回调内部按两个独立开关扇出到网络中枢与终端 stderr。
中枢由 `build_ws_servers` 在 `CRON_PUSH_ENABLED=true` 时创建设到 listener 上（`WsServer.notification_hub`），
入口层经 `EmbeddedHttpService.notification_hub` 取到。

## Boundaries & Constraints

**Always:**
- 两个 Settings 字段：`cron_push_enabled: bool = False`、`cron_echo_to_terminal: bool = False`
  （默认**都是 False**：不改变现行为）
- 两个开关**互相独立**：只推送 / 只回显 / 都开 / 都关，四种组合都要有判据
- 开关取值读 **`EngineContainer.runtime_config` 快照**（`ensure_runtime_config`），不二次 `get_settings()`
  （与 `composition.py` 的 Phase 1 口径一致）
- notifier 的每一次调用都**不得**影响 cron 执行结果：异常一律 warning 后吞掉（同 `interactive.py::_hub_call` 语义）
- 57 号台账纪律：`.env.example` 必须文档化新键（`tests/test_config.py::test_every_settings_field_is_documented_in_env_example`），
  `config/catalog.py` 必须把新键登记进某个分组（`tests/test_config_catalog.py` 的「分组条目总数 == 字段数」判据）
- 终端回显走 **stderr**、单行（`\n` 折成 ` ⏎ `）、带 `[cron <job_id>]` 前缀、按 500 字符截断
- `--json`（单次模式）不涉及 cron；但回显实现不得写 stdout，避免污染 JSONL 契约

**Never:**
- 不改 `cron/scheduler.py`（幂等租约、last_run、失败重试口径全部保持）
- 不让 goal 自动推进分支发通知（D5：它不是「给用户的回答」）
- 不在 `http_console`（网页会话）入口开 cron（该入口仍 `enable_cron=False`）
- 不给 cron 结果加「取消」「审批」「回放历史落盘」能力
- 不改 `FrozenRuntimeConfig` 之外的第二套配置解析

</frozen-after-approval>

## I/O & Edge-Case Matrix

| 场景 | 输入/状态 | 预期行为 | 错误处理 |
|---|---|---|---|
| 两个开关都关 | `CRON_PUSH_ENABLED=false`、`CRON_ECHO_TO_TERMINAL=false` | 不建中枢（端点不注册）、不建 notifier、不输出 | N/A |
| 只开推送 | push=true、echo=false | 中枢建好，客户端收到帧；终端零输出 | N/A |
| 只开回显 | push=false、echo=true | 端点不注册（403）；终端一行 `[cron <job_id>] …` | N/A |
| 都开 | 两个 true | 两条路都拿到同一条通知 | N/A |
| cron 成功 | `loop.run` 返回答案 | `status=completed`，`text=答案` | N/A |
| cron 失败 | runner 内抛异常 | `status=failed`，`text=异常首行`；异常**继续上抛**（scheduler 仍 ledger.fail + last_run） | 不吞异常 |
| goal 自动推进 | prompt 命中 `_goal_auto_goal_id` | 不发通知（分支短路） | N/A |
| 中枢缺席但 echo 开 | `WS_ENABLED=false` 或 push=false | notifier 仍存在，只回显；hub 分支空操作 | 不报错 |
| 中枢发布抛异常 | hub 实现出故障 | 一条 warning，cron 结果不受影响 | 降级为「少一条通知」 |
| 外部 listener 存在 | `WS_EXTERNAL_HOST` 非空 + push=true | 对外 listener **也**挂中枢；启动时打一条 WARNING（D2） | 不静默 |
| `--no-ws` | 本次进程显式关 WS | 无 listener ⇒ 无中枢 ⇒ 只回显（若有） | N/A |
| 网页会话入口 | `heagent http-server` / HTTP console 跑一轮 | 无 cron、无通知（`enable_cron=False` 照旧） | N/A |
| `.env` 追加两键 | 用户环境 | 字节级追加，保持既有 EOL/BOM/末行换行状态 | 见 Tasks 的 .env 护栏 |

## Code Map

- `src/heagent/config/__init__.py` —— `cron` 段新增两字段（默认 False）
- `src/heagent/config/catalog.py` —— `ConfigGroupSpec(id="cron", keys=("CRON_TICK_SECONDS", "CRON_PUSH_ENABLED", "CRON_ECHO_TO_TERMINAL"))`
- `.env.example` —— 两键的说明与示例（含「默认关」的理由）
- `.env`（本机项目文件，用户已授权本会话修改）—— 追加 `CRON_PUSH_ENABLED=True` / `CRON_ECHO_TO_TERMINAL=True`
- `src/heagent/cli/http.py`
  - `build_ws_servers`：push 开时 `NotificationHub(max_connections=primary.ws_max_connections)`，
    传给**每一个** `WsServer`（本地 / 对外 / readonly）；**返回值形状不变**（仍 `(servers, cli_hub)`），
    中枢经 `servers[i].notification_hub` 暴露——避免打断 8 处既有解包与 3 个测试
  - `build_http_service`：`EmbeddedHttpService(..., notification_hub=<取自 servers>)`
  - `EmbeddedHttpService`：新增只读属性 `notification_hub`
- `src/heagent/cli/wiring.py` —— `build_cron_job_runner(..., cron_notifier: CronNotifier | None = None)`；
  `_run_job` 改为：`answer = await loop.run(prompt)` → `_notify(completed, answer)`；
  异常路径先 `_notify(failed, str(exc).splitlines()[0])` 再 `raise`
- `src/heagent/cli/composition.py` —— `_build_loop(..., cron_notifier=None)` 透传给 runner
- `src/heagent/cli/interactive.py` —— `_run_chat` 里用 `ensure_runtime_config(engine)` 的快照构造 notifier
  （`_build_cron_notifier(http, config)`），再传进 `_build_loop`
- `src/heagent/cli/display.py` —— `echo_cron_result(job_id, status, text)`（stderr / 单行 / 前缀 / 截断）
- 测试：`tests/test_cron_notify.py`（新，runner 契约）、`tests/test_cli_cron_echo.py`（新，回显与开关矩阵）、
  `tests/test_cli_http.py` 或 `tests/network/test_ws_server.py`（装配判据：flag 决定中枢与端点是否装）
- 文档：`AGENTS.md`（网络入口条目补通知流与两键）、`docs/frame.md`（network 模块表 / WS 端点表 / Settings 表）、
  `deploy/README.md`（若对外 listener 段落列举端点集，补一条）

## Tasks & Acceptance

**Execution:**
- [x] `config/__init__.py` + `config/catalog.py` + `.env.example` 两键落地
- [x] `.env` 追加两键（**字节级**：先 `read_bytes` 复核行数 / EOL / BOM / 末行换行，只追加不重排，
      写回保持原 EOL 与末行状态；报告给出精确到行的 diff）
- [x] `cli/http.py` 中枢构造 + `EmbeddedHttpService.notification_hub` + 对外 listener WARNING
- [x] `cli/display.py::echo_cron_result`
- [x] `cli/interactive.py::_build_cron_notifier` + 传参
- [x] `cli/composition.py` / `cli/wiring.py` 透传与发布点
- [x] 新测试两份 + 装配判据
- [x] 文档三处同步（AGENTS / frame / deploy）

**Acceptance Criteria:**
- Given push=true、echo=false，when 一次 cron 执行完成，then 已连接客户端收到
  `{"type":"notification","notification":{"kind":"cron_result","status":"completed","job_id":…,"text":"hello"}}`
  且终端**零输出**
- Given push=false，when 客户端连 `/api/notifications/ws`，then 403（路由未注册）
- Given echo=true，when 一次 cron 执行完成，then stderr 恰好多**一行** `[cron <job_id>] …`，stdout 不变
- Given cron 抛异常，when 执行，then 客户端收到 `status=failed` 且 `scheduler` 仍记 `cron_job_failed`、
  仍更新 `last_run`（异常没有被 notifier 吞掉）
- Given goal 自动推进 prompt，when 执行，then 零通知、零回显
- Given notifier 内部抛异常（测试桩），when 执行，then cron 结果不受影响、warning 一条
- Given 两个开关的四种组合，when 装配，then `notification_hub` / 输出行为与矩阵一致
- Given 全量 `pytest` + `ruff check` + `ruff format --check` + `mypy src` + `bandit -r src/ -ll`，then 全绿

## Verification

**Commands（实现后逐条实跑并回填实测数字；未跑不得填）:**
- `pytest tests/test_cron_notify.py tests/test_cli_cron_echo.py -q`
- `pytest tests/test_config.py tests/test_config_catalog.py tests/test_architecture_contracts.py -q`
- `pytest tests/network -q`
- `pytest -q`
- `ruff check src tests && ruff format --check src tests && mypy src && bandit -r src/ -ll`
- `python scripts/quality_gate.py`（本地六门）

**端到端手工验收（需真实进程，实现会话记录日志行）:**
1. `.env` 两键为 True → 重启 `heagent`（交互模式）
2. 建一条 `* * * * *` 的 job（prompt = `说 hello`）
3. 客户端（Windows 侧，`websockets` 17.3 已装在 `.venv`）连 `ws://127.0.0.1:9001/api/notifications/ws`
4. ≤60s 内应收到一条 `cron_result`；终端同时出现一行 `[cron <job_id>] hello`
5. 判据分层：有 `[accepted]` 无帧 = 发布点没接上；无 `[accepted]` = 路由没注册（flag 没生效）

**实测结果（2026-10-30，容器 `py311-venv-linux`，`PYTHONPATH=/workspace/src`）:**

| 命令 | 实测 |
|------|------|
| `pytest -q`（全量，终态） | **4187 passed, 50 skipped, 25 deselected**，6 分 10 秒 |
| `pytest -q --cov`（覆盖率门限 87%，终态） | **92.46%**，同 4187 passed |
| `pytest tests/test_cron_notify.py tests/test_cli_cron_echo.py tests/network/test_notification_cron_e2e.py -q` | **22 passed**（6 + 14 + 2） |
| `pytest tests/test_config.py tests/test_config_catalog.py tests/test_architecture_contracts.py tests/network -q` | **666 passed** |
| `ruff check src tests` | All checks passed |
| `ruff format --check src tests` | 360 files already formatted |
| `mypy src` | Success: no issues found in 177 source files |
| `bandit -r src/ -ll` | No issues identified（High/Medium 0） |
| `.env` 字节级追加 | 46 → 49 行；`eol=LF (crlf=0)` 保持；`bom=False`；`trailing_newline=False` 保持；见下 |

`.env` 追加内容（精确到行，既有 46 行零改动）：

```
47: # cron 结果推送（Epic 58）：推送 / 终端回显（两个独立开关）
48: CRON_PUSH_ENABLED=True
49: CRON_ECHO_TO_TERMINAL=True
```

**未做的一步（需用户在场）**：真实进程手工验收。本机活进程 `logs/heagent-20261030-140420.log`
的 PID 于 14:04 启动，`Settings` 已固化 ⇒ 新键不生效；须重启 `heagent` 交互进程后再连
`ws(s)://127.0.0.1:9901/api/notifications/ws` 验收（判据分层见本文末）。

## Spec Change Log

<!-- Append-only. -->

## Implementation Notes

<!-- Agent-owned. Append-only during implementation. -->

### 2026-10-30 根因取证：App 零投递 = 本 story 未实现（58-1 无发布方 + 中枢未装配）

**现象（用户观测）**：cron `1661798f` 每分钟正常产出 hello；App 推送连接「在线」且横跨多次触发；会话零投递。

**结论**：客户端与 cron 都不是主因。断点两处，全落在本 story 的交付范围。

**断点 A —— `/api/notifications/ws` 在生产装配里根本不注册**

- `cli/http.py:549`、`cli/http.py:552`：`build_ws_servers` 构造 `WsServer(primary, run_service=..., cli_hub=hub)` 与
  `WsServer(external, run_service=...)`，**两处都不传** `notification_hub`。
- `network/ws_host.py:229`：`if notification_hub is not None:` 才注册 `/api/notifications/ws`；为 `None` 时路由表中无此条。
- 全仓 `NotificationHub(...)` 实例化点**仅存在于 tests**（`tests/network/test_notification_hub.py`、
  `test_notification_ws_e2e.py`），生产代码零处。
- 后果：客户端连该路径拿到 uvicorn 在「应用未 accept」时补的 **403**（不是应用层 404；
  `tests/network/test_cli_ws_e2e.py:168-179` 已钉此口径）。

**断点 B —— 即使中枢装上，也没有任何东西往里发布**

- `network/notification_hub.py:51` 的 `publish_cron_result`：调用方只有 tests，**生产零调用**。
- `cli/wiring.py:383` 的 `_run_job`：`await loop.run(prompt)` 的返回值直接丢弃（`AgentLoop.run` 声明返回
  `str`，`agent/loop.py:244-259`），runner 签名仍是 `-> None`。
- `cron/scheduler.py:166`：只把结果写成 engine 事件 `cron_job_started` / `cron_job_completed` / `cron_job_failed`，
  从不进通知中枢；失败路径同样无通知。

**实测证据（活进程 `logs/heagent-20261030-140420.log`，325 行）**

| 判据 | 实测 |
|------|------|
| listener 数量 | 1 条，`L5 ws event=started address=127.0.0.1:9901 listener=local tls=wss` |
| cron `1661798f` 触发 | 3 次且全成功：`14:14:39` → `14:15:43` → `14:16:44`（均带 `cron_job_completed`） |
| 另一 job `3055f010` | `14:15:41` 起跑、`14:15:43` 完成 |
| `notification_ws_open` 计数 | **0** |
| `/api/notifications/ws` 真实握手 | 近期 5 个日志中命中 4 次，**全部是排查工具调用回显**，零次真实握手 |
| 被 accept 的端点 | 仅 `/api/cli/ws`（14:04:25、14:04:41）与 `/api/runs/ws`、`/api/runs/<id>/ws` |

⇒ 「App 在线」不可能建立在 `/api/notifications/ws` 上（路由不存在，握手必 403）；若 App 连的是
`/api/runs/ws`，它确实在线，但按 epic D1 **设计上永远收不到 cron 帧**。

**本 story 的闭合判据（除 AC 外新增两条回归防线）**

1. 装配判据：`CRON_PUSH_ENABLED=true` 时，`build_ws_servers` 返回的**每一个** `WsServer.notification_hub`
   非 `None`，且 `build_ws_app` 的路由集合包含 `/api/notifications/ws`。
2. 发布判据：一次真实 cron 执行（stub runner 的 `loop.run` 返回 `"hello"`）后，订阅者收到
   `status=completed, text=hello`——即「`loop.run` 的返回值必须流到 `publish_cron_result`」这条链有断言。

### 2026-10-30 实现记录（58-2 落地）

**改动清单（按层）**

| 文件 | 改动 |
|------|------|
| `config/__init__.py` | `cron_push_enabled` / `cron_echo_to_terminal` 两字段，默认 `False`（不改变现行为） |
| `config/catalog.py` | `cron` 组 keys 由 1 条扩到 3 条 ⇒ 两键**可写**（`whitelist()` 49 → 51） |
| `.env.example` | 第 10 段补两键说明（含「失败也送达」「goal 推进不发」） |
| `.env`（本机） | 字节级追加第 47–49 行；LF / 无 BOM / 末行无换行 全部保持 |
| `cli/http.py` | `build_ws_servers(..., push_enabled=None)` 三态；push 真才建 `NotificationHub` 并挂**每个** listener；对外 listener 存在时打 `ws event=cron_push_exposed`；`EmbeddedHttpService.notification_hub`（只读属性）；`build_http_service` 抬中枢 |
| `cli/wiring.py` | `CronNotifier` 类型 + `build_cron_job_runner(..., cron_notifier=None)`；`_run_job` 改为 `answer = await loop.run(prompt)` → `_notify(COMPLETED, answer)`；异常路径 `_notify(FAILED, 首行)` 后 **继续上抛**；`_notify` 单点 try/except（warning 后丢弃）；`_first_line` 叶子函数 |
| `cli/composition.py` | `_build_loop(..., cron_notifier=None)` 透传给 runner |
| `cli/interactive.py` | `_build_cron_notifier(service, config)`（两开关扇出；push 无中枢时 warning）；`_run_chat` 经 `ensure_runtime_config(engine)` 快照构造后传入 |
| `cli/display.py` | `CRON_ECHO_MAX_CHARS = 500` + `echo_cron_result(job_id, status, text)`（stderr / 单行 / `[cron <job_id>]` / `failed:` / 截断） |
| 测试 | 新增 `tests/test_cron_notify.py`(6)、`tests/test_cli_cron_echo.py`(14)、`tests/network/test_notification_cron_e2e.py`(2)；`tests/conftest.py` 的 `_StubEmbeddedHttp` 补 `cli_hub` / `notification_hub` 两属性（与真实服务同形）；`tests/test_config_catalog.py` 白名单计数 49 → 51 |

**story 之外的四处补充（都属「不补就是假可用」类）**

1. `build_ws_servers` 增 `push_enabled: bool | None` 三态覆盖（与 `cli_bypass` / `enabled` 同风格）：
   装配判据与 `http-server` 都需要在不改 Settings 的前提下开关中枢。
2. `heagent http-server` 显式传 `push_enabled=False`：该入口 `enable_cron=False`，中枢建了也永远不会
   有帧——注册一条永不投递的端点正是本 story 要消灭的那类假可用。
3. `_build_cron_notifier` 在「开了推送但本进程没有中枢」（`WS_ENABLED=false` / `--no-ws`）时打 warning：
   默认的静默失败正是本次故障的形态。
4. `tests/conftest.py` 的替身补两个中枢属性：否则每次交互模式测试都会走进那条 warning（噪声假红风险）。

**明确的未覆盖项（设计取舍，不是遗漏）**

- `heagent gui`（TUI）入口**不接** notifier：该入口不构造 HTTP/WS 服务（无中枢 ⇒ 推送无从谈起），
  且在没有 TTY 语义的 Textual 界面里往 stderr 回显会破坏渲染。结果：`heagent gui` 里的 cron
  既不推送也不回显。若将来 TUI 也要这条能力，落点是 `GuiState` 的通知区而不是 stderr。
- 通知载荷的 `cron`（表达式）字段当前恒为空串：`cron/scheduler.py` 的 `create_run_context` metadata
  只写 `job_id`，而本 story 的 Never 明确不改 scheduler；要补需先改约束（一处 metadata 增键）。

## Review Triage Log

<!-- 三层自审（blind-hunter / edge-case-hunter / verification-gap）逐层执行后追加。 -->
