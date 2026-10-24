# Verification Gap Review

**Goal:** Find changed behavior that could break without reliable verification catching it. Ask one question — "if the behavior this change is supposed to produce broke where it's actually used, would verification fail?" Do not hunt for correctness bugs, but report genuine problems you notice while tracing verification.

The main verification gap shapes are:

1. **Regression gap:** the changed code regresses where it's used, and no test covering that use would fail.
2. **Missing-adoption gap:** a place that should now use the new behavior doesn't; it handles the same case its own way, or not at all, and no test would flag the omission.
3. **Broken-verification gap:** a test appears to cover the changed behavior, but would not actually protect it because it is skipped, flaky, not run in the normal verification path, or too weak to observe the regression.

## Evidence Rules

- Read a test before claiming what it covers, runs, asserts, or misses.
- Before claiming no test exists, search the whole repo by the symbol under test and by import references; expected file locations are not enough.
- Never assert what you did not verify. If a finding cannot be grounded, drop it.
- In a finding, say what you actually checked — "none of the tests I read cover this" — and show how far you looked. Say a test doesn't exist anywhere only when the symbol/import-reference search actually shows that.
- Do not assign severity, confidence, priority, or ranking.

## Review Sequence

### Step 1: Screen for behavioral change

Screen each part of the change separately. If a part is non-behavioral, skip it. Call a part non-behavioral only when the changed code does not alter return values, thrown errors, caller-visible side effects, or observable state (including iteration order and emitted messages). Once a part meets that test, move on; do not inspect callers or tests for extra confirmation.

Common non-behavioral examples: formatting, comments, whitespace; pure renames; trivial getters/setters and pass-throughs; type-only or compiler-enforced changes with no runtime effect; etc.

Only outcomes produced by deterministic code are worth automatically testing; tests are useless on static source text and brittle on LLM output. Skip those parts.

If every part is skipped, output the clean result (see Output Format).

### Step 2: Find the behavior that changed

Identify what behavior changed compared to the previous version: output, side effect, branch, error path, schema/event shape, config default, validation/authorization rule, external contract, etc. If the change affects more than one behavior, handle each separately.

Treat broad-impact changes as behavioral even when no single changed line looks important: dependency, toolchain, build/config, data-file, etc.

### Step 3: Trace where that behavior is used

Trace the changed behavior to the places that observe it. Start with direct callers and registered entry points (routes, commands, DI), contract consumers (schemas, events, APIs, database readers), and reverse-dependency info if already available.

Follow a path only while the changed behavior is reachable and unverified. Stop when a test at that boundary would fail, the consumer does not observe the changed behavior, or the next hop is guesswork (dynamic dispatch, reflection, outside-repo consumers, etc.). Prefer the nearest observable boundary, often one to three hops away, especially across contract, integration, or service edges. If there are more than five similar consumers, group obvious repeats and check representative paths; expand only when a consumer observes the behavior differently.

### Step 4: Qualify the consumer, then check its test

For each consumer, name the smallest realistic regression this consumer would observe: invert the branch, drop the default, omit the field, return the old error code, skip the integration call, etc. This is the Demonstration. If no such regression exists, drop the path; untested downstream code is not a finding.

A `Missing-adoption gap` qualifies not by the adoption failure alone but by a supersession signal: the change gives clear evidence the new behavior is meant to replace the local one — PR intent, naming or docs, a replaced sibling site, deleted duplicate logic, or a test defining the new rule — and the local site shares the same observable contract. Without a supersession signal and a shared observable contract, it is a refactor suggestion, not a verification-gap finding. Once both hold, check whether any test for that site would flag the non-adoption; missing coverage of the non-adoption is the gap itself, not a disqualifier.

Find and read the relevant test. Ask whether the Demonstration would make an assertion fail.

- If yes, the behavior is verified. No finding.
- For a regression-style Demonstration: if no test runs the path, the test is skipped/flaky/not run normally, or the test runs the code without checking the changed result, report a `Regression gap` or `Broken-verification gap`.
- For a qualifying Missing-adoption case: if none of the site tests you found assert it adopts the new behavior, report a `Missing-adoption gap`.

A test counts only if it runs normally and an assertion observes the changed output, branch, or contract. These do not count: no execution; source-text assertions that match a file's wording instead of running it; success/no-throw/snapshot-only checks; mock/log-call checks; human-only checks; tests that mock away the integration; e2e tests that pass through without checking the changed output; stale assertions or fixtures.

For example, `expect(x ?? DEFAULT).toBe(DEFAULT)` passes when `x` is missing.

Common patterns:

- **Caller-path gap** — helper test covers the branch, but caller values skip it.
- **Contract drift** — payload/schema/event changes must be verified at the consumer.
- **Migration compatibility** — tests only create new-format rows or fresh schemas.
- **Phantom exception** — handled partial-failure path has no test.
- **Missing-adoption gap** — sibling site should use the new rule/helper and does not.
- **Removed verification** — deleted test or weakened assertion leaves behavior unpinned; removing a source-text assertion is not this, since it never counted.

### Step 5: Confirm each finding is real

Before writing a finding, re-open the specific tests or search results the finding relies on. Verify the Demonstration would not make any test you checked fail, or that the absence claim is backed by the symbol/import-reference search. Do not claim more than you verified; drop any finding you cannot ground.

Explain why the test misses the bug using what the test sets up and checks.

Do not report: compiler/type-checker-enforced cases; behavior already verified by an integration, contract, or e2e test; implementation-detail or mock-only tests; low coverage or a missing test file by itself; legacy untested code the change did not affect.

Report genuine problems you noticed while tracing verification, even if they are not verification gaps. Put them under `Other findings` in the output. This permits reporting what you already reached, not extra hunting. A claim that code misbehaves is a defect, not a gap — it goes under `Other findings` for standard triage, however you found it.

## OUTPUT FORMAT

Emit each verification-gap finding as one block. No general advice, no severity or confidence. Triage trusts a gap finding as filed and does not re-verify it, so each block must stand on its own evidence.

```markdown
### <one-line title naming the gap>

- **Changed surface:** the exact behavior or contract that changed — `file:line`.
- **Impacted consumer or site:** named concretely with `file:line` (e.g. "the `createInvoice` mutation used by the billing dashboard at `billing/dashboard.ts:88`," not "callers of this function").
- **Existing test evidence:**
  - `Regression gap`: what the relevant test actually asserts, with `file:line`; or, if none, the symbol/import-reference searches run and their result.
  - `Missing-adoption gap`: tests for the impacted site, and whether any assert it adopts the new behavior.
  - `Broken-verification gap`: the apparent test or verification path, and why it does not count.
- **Missing verification:** the precise assertion or check that's absent.
- **Demonstration:**
  - `Regression gap` / `Broken-verification gap`: the concrete regression that would ship undetected, and why the tests you checked would not fail.
  - `Missing-adoption gap`: the case the site mishandles by not adopting the new behavior, and that none of the tests you read assert adoption.
- **Consequence:** the concrete thing that ships wrong — a regression the checked evidence would not catch, or a site that should use the new behavior and doesn't.
- **Disposition:** `patch` — name the test to add, fit to the repo's own way of verifying (don't impose a generic test pyramid) — or `defer` when the gap is real but not worth closing as part of this change, with one sentence of why.
```

If you noticed genuine non-gap problems while tracing verification, append:

```markdown
## Other findings

- <description only; no severity, confidence, priority, or ranking>
```

When you find no verification gaps and no other findings, output exactly this single line, not an empty response:

`No verification gaps found.`

## CONTENT SOURCE

"Review content:" in the message that launched you gives the content itself or a path to read it from. Read the file when it is a path; either way that is the content under review, and this instruction file never is. If no content is supplied, or the file it points to is missing, empty, or unreadable, say exactly that and stop — never report a clean review for content you could not read.


Review content: the unified diff inlined below. Read it — it is the content under review.

Do not invoke any skill, and do not spawn subagents of your own — you are the reviewer. Return your findings as text in your final message.

===== BEGIN DIFF =====
diff --git a/.env.example b/.env.example
index 740c10c..29ab35a 100644
--- a/.env.example
+++ b/.env.example
@@ -334,13 +334,6 @@ ANTHROPIC_PROMPT_CACHING=true
 #                                    # 只对**未显式传 `--port`** 的路径生效 —— 显式端口是契约，冲突即报错
 # HTTP_MAX_CONNECTIONS=16            # 同时打开的客户端连接上限（超限连接被 Uvicorn 直接拒绝；内部另预留 1 条给就绪探测）
 # HTTP_MAX_SUBSCRIBERS=16            # 每个 run 的 SSE 订阅者上限（同一条 run 的并发事件流）；超限回 429 rate_limited。
-# HTTP_WS_MAX_CONNECTIONS=16         # 每个 run 的 WS 连接上限；独立于 SSE 订阅者池，超额回 rate_limited 错误帧。
-#                                    # WS 不受 Uvicorn 的 HTTP limit_concurrency 限制，故需要独立额度。
-# HTTP_CLI_WS_ENABLED=false          # CLI 旁路订阅（默认关）：给 `WS /api/cli/ws` 开一条只读事件流，
-#                                    # 把**终端里那一轮** run 的事件（文本增量 / 工具调用 / 终态）实时推给
-#                                    # 外部客户端。只占一条流、不占运行名额、不写会话历史、不提供取消通道；
-#                                    # 与 HTTP 入口同档**无认证无 TLS**，开了等于让本机能连上该端口的进程
-#                                    # 看到终端 agent 的工具输出。
 # HTTP_MAX_INFLIGHT_RUNS=1           # **每项目**同时在途网页 Agent 运行上限（满即 409 run_conflict）；
 #                                    # 不设总额（默认）时全局同时刻上限 = 项目数 × 该值（默认最多 32）
 # HTTP_MAX_TOTAL_INFLIGHT=0          # **服务级**在途运行总额（跨项目共享）；0 = 不限（默认，保持上面的
@@ -354,6 +347,22 @@ ANTHROPIC_PROMPT_CACHING=true
 # HTTP_TOOL_INFLIGHT_TIMEOUT=3600    # 单个**在途工具**的最长在途时间（秒）：超时按「工具卡死」终结该 run；
 #                                    # 刻意与静默上限分开——长工具期间同样没有事件，用静默阈值会误杀正常长调用；0 = 不限制
 # HTTP_SHUTDOWN_TIMEOUT=5            # 关闭时「停止接收 → 终结在途 run → 关订阅 → 关 listener」的等待上限
+
+# ---- WS 入口（Epic 56：与 HTTP 完全分离的独立 server，所有 WS 能力的唯一宿主）----
+# 默认 127.0.0.1:9001。两条 WS 端点（/api/runs/{run_id}/ws、/api/cli/ws）路径不变、
+# 端口 8766 → 9001 是 Epic 56 的**唯一 breaking change**。本机模式与 HTTP 入口同档无认证无 TLS；
+# 非回环绑定 = 对外模式（认证强制 + fail-closed，56-2 落地）。端口自动查找复用
+# HTTP_PORT_AUTO_FIND_ATTEMPTS，两条 listener 独立顺延。
+# WS_HOST=127.0.0.1                  # WS listener 绑定地址（非回环值启动时 stderr 一行 + 日志一条明确告警）
+# WS_PORT=9001                       # WS 入口端口（8766 → 9001，Epic 56 起生效）
+# WS_MAX_CONNECTIONS=16              # WS 连接上限：每个 run 的订阅额度 + CLI 旁路 hub 的连接总额；
+#                                    # 超额回 rate_limited 错误帧（检查+登记同一步原子完成）。
+# WS_SHUTDOWN_TIMEOUT=5              # WS server 关闭排空的等待上限（秒）
+# WS_CLI_BYPASS_ENABLED=false        # CLI 旁路订阅（默认关）：给 `WS /api/cli/ws` 开一条只读事件流，
+#                                    # 把**终端里那一轮** run 的事件（文本增量 / 工具调用 / 终态）实时推给
+#                                    # 外部客户端。只占一条流、不占运行名额、不写会话历史、不提供取消通道；
+#                                    # 与 HTTP 入口同档**无认证无 TLS**，开了等于让本机能连上该端口的进程
+#                                    # 看到终端 agent 的工具输出。
 # HTTP_CONSOLE_WRITE_ENABLED=false   # **默认关**：网页控制台的配置写入通道。关闭时配置面全只读，
 #                                    # 且网页**无法通过任何请求**打开它（它自己也在只读排除组里）。
 #                                    # 开启渠道只有启动配置（系统环境变量 / 项目 .env / 全局 .env）；
diff --git "a/_bmad-output/epics/epic-56-WS\345\257\271\345\244\226\345\205\245\345\217\243\345\221\250\346\234\237/stories/56-1-ws-server-split.md" "b/_bmad-output/epics/epic-56-WS\345\257\271\345\244\226\345\205\245\345\217\243\345\221\250\346\234\237/stories/56-1-ws-server-split.md"
new file mode 100644
index 0000000..5ccb3e8
--- /dev/null
+++ "b/_bmad-output/epics/epic-56-WS\345\257\271\345\244\226\345\205\245\345\217\243\345\221\250\346\234\237/stories/56-1-ws-server-split.md"
@@ -0,0 +1,119 @@
+---
+title: '56-1 WS server 拆分与端点迁移'
+type: 'feature'
+created: '2026-10-24'
+status: 'in-progress'
+route: 'dispatch'
+review_loop_iteration: 0
+baseline_commit: '38c0b8ee2cfc37a3ce4f8bd178610907a9eec5fc'
+context: []
+---
+
+<!-- 交付物与验收边界 = epics.md 56-1 行；冻结决策 D1–D7 见同目录 brief.md。 -->
+
+<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">
+
+## Intent
+
+**Problem:** 两条 WS 路由挂载在 HTTP 的 ASGI app 内、共用 8766 监听器与 HTTP 配置；对外入口（56-2 认证/TLS、56-3 经 WS 提交 run）无处安放，`ws_max_connections` 等旋钮与 HTTP 面混在一起。
+
+**Approach:** 新建 `network/ws_host.py`：`WsServerConfig`（默认 `127.0.0.1:9001`）+ `build_ws_app`（只挂既有两条 WS 端点，零 HTTP 路由）+ `WsServer`（start/serve_forever/close 三件套，镜像 `HttpServer` 口径）；HTTP app 拆除 WS 路由与 `cli_hub` 缝；端点逻辑复用 `ws_server.py` 不重写；组合根（`heagent http-server` 命令 + 默认 CLI 内嵌服务）双 server 编排，关停顺序 HTTP 先（排空运行）→ WS 后（关残余连接）。
+
+## Boundaries & Constraints
+
+**Always:**
+- 分离判据可执行测试（非文档句）：8766 上 WS 升级不可达（未 accept、非 101；用户裁定①A 钉实测，不钉字面 404）；9001 上无任何 HTTP API 面（REST/静态页/健康检查全 404）
+- 本机语义逐字保持：订阅/续传（last_event_id）/cancel/ping + CLI 旁路跨轮，路径不变
+- 端点与事件分发不重写：`ws_server.py` 复用；`_RunRecord`/`CliEventHub` 状态源不动
+- 限额原子性不动：「检查 + 登记」同一无 `await` 同步方法（A9③）
+- 错误信封单出口（`error_envelope`），`HttpErrorCode` 封闭不新增
+- 断线只注销、绝不取消运行（既有立场）
+- `network/` 依赖边界不变；跨模块数据一律 Pydantic
+
+**Never:**
+- 不做认证/TLS（56-2）、经 WS 提交 run（56-3）、`frame.md` 4.17/4.18 重写（56-4）
+- 不新建 CLI 命令；不引入新错误码；不改 SSE/REST/控制台行为
+- 不做双 WS 监听并存、多租户、反向代理（brief 冻结边界）
+
+## I/O & Edge-Case Matrix
+
+| 场景 | 输入/状态 | 预期行为 | 错误处理 |
+|---|---|---|---|
+| WS 升级打到 8766 | HTTP listener，任意 WS 路径 | 升级被拒：未 accept、非 101（Starlette 实测 HTTP 403 / close 1000） | 裁定①A：钉实测「不可达」，不钉字面 404（brief 措辞偏差经用户裁定） |
+| HTTP 请求打到 9001 | GET /、/api/health、/api/runs | 全 404（Starlette 默认），无任何 API 面 | N/A |
+| run 订阅限额满 | 第 limit+1 个订阅者 | `rate_limited` 错误帧 + close policy | 检查+登记同步原子 |
+| 缺 `websockets` 包 | WsServer.start() | 照常绑定 + `ws_unavailable` 安装诊断；HTTP 不受影响 | 非致命 |
+| WS 端口冲突 | auto-find 顺延；显式指定 fail-loud | 启动失败显性报错 | `WsStartupError` → 入口层 ClickException |
+| CLI 旁路关闭 | `ws_cli_bypass_enabled=false`（默认） | 9001 不注册 `/api/cli/ws` | N/A |
+
+</frozen-after-approval>
+
+## Code Map
+
+- `src/heagent/network/http_server.py` — 2172 行 HTTP 实现。拆点：`HttpServerConfig.ws_max_connections`(:200)；`build_http_app` 的 WS 路由与 cli_hub 缝(:1753-1915)；`_OriginGuardMiddleware`(:1126)；Origin 辅助 `:1032-1109`；uvicorn WS 参数(:2016-2018)；`HttpServer.close` 的 close_websockets/cli_hub(:2084-2101)；`_CLI_WS_PATH`(:132)
+- `src/heagent/network/ws_server.py` — 端点适配器（复用不重写）：`build_ws_endpoint`（配额经 `service.config.ws_max_connections` :198 需参数化）；`build_cli_ws_endpoint`；`_supervise` 共用收尾
+- `src/heagent/network/ws_protocol.py` — `WS_MAX_FRAME_BYTES`/`WS_PING_*` 常量（随迁到 ws_host 的 uvicorn 配置）
+- `src/heagent/network/cli_event_hub.py` — `CliEventHub(max_connections=...)` 构造注入，不动
+- `src/heagent/cli/http.py` — 组合根：`build_server_config`(:70)、`_serve_http`(:139)、`EmbeddedHttpService`(:156)、`build_http_service`(:254)、`http_server_cmd`(:404)、`_CLI_WS_PATH` 副本(:49)
+- `src/heagent/cli/interactive.py:139-147` — 内嵌服务唯一调用方（签名不变则零改动）
+- `src/heagent/config/__init__.py:393-409` — `http_ws_max_connections`/`http_cli_ws_enabled` 字段位
+- `src/heagent/config/catalog.py:385-389` — listening 组 `HTTP_*` 模式行
+- `tests/network/test_http_ws_config.py` — Settings/HttpServerConfig 同步测试（重构并入新文件后删除）
+- `tests/network/test_http_ws_e2e.py` — WS 订阅 e2e（HttpServer 驱动 → 改 WsServer 驱动）
+- `tests/network/test_http_cli_ws.py` — CLI 旁路 e2e（同上）
+- `tests/test_cli_ws_publish.py`/`test_cli_ws_wiring.py`/`test_cli_http.py`/`test_cli_http_lifecycle.py` — 装配/生命周期面
+- `tests/test_architecture_contracts.py:72-80` — network 禁入清单（验证，预计零改动）
+
+## Tasks & Acceptance
+
+**Execution:**
+- [x] `src/heagent/network/origin.py` — 新建：自 http_server.py 纯搬移 Origin/Host 校验（_allowed_hosts/_allowed_ports/_split_authority/_request_origin_violation/_canonical_authority + 4 个头/通配常量），公开命名；http_server.py 改导入；测试 import 同步
+- [x] `src/heagent/network/ws_host.py` — 新建：WsServerConfig + build_ws_app（两条 WebSocketRoute + Origin 防线，零 HTTP 路由）+ WsServer（三件套 + TCP 就绪探测 + uvicorn WS 参数 + ws_unavailable 诊断）+ WsStartupError
+- [x] `src/heagent/network/http_server.py` — 拆除：WS 路由、cli_hub 参数/字段/reopen/close_websockets、HttpServerConfig.ws_max_connections、uvicorn WS 参数、_CLI_WS_PATH；Origin 辅助改从 origin.py 导入
+- [x] `src/heagent/network/ws_server.py` — 两个 build_* 端点配额参数化（新增 max_connections 参数，删 service.config 读取）
+- [x] `src/heagent/config/__init__.py` — Settings：删 http_ws_max_connections/http_cli_ws_enabled；增 ws_host/ws_port/ws_max_connections/ws_shutdown_timeout/ws_cli_bypass_enabled
+- [x] `src/heagent/config/catalog.py` — listening 组 patterns 加 `WS_*`
+- [x] `src/heagent/cli/http.py` — build_server_config 去 ws_max_connections；新增 build_ws_server_config（端口 auto-find 复用 http_port_auto_find_attempts）；EmbeddedHttpService 持双 server（HTTP 先 WS 后关停）；http_server_cmd 加 --ws-host/--ws-port
+- [x] `.env.example` — 新增 WS_HOST/WS_PORT/WS_MAX_CONNECTIONS/WS_SHUTDOWN_TIMEOUT/WS_CLI_BYPASS_ENABLED；删 HTTP_WS_MAX_CONNECTIONS/HTTP_CLI_WS_ENABLED 行
+- [x] `docs/frame.md` — 配置表增 WS_* 行（4.17/4.18 全量重写留 56-4）
+- [x] `tests/network/test_ws_server.py` — 新建替身纯逻辑面：两条端点全语义（订阅/续传/cancel/ping/限额/shutting_down/Origin 拒）+ 配置同步 + 分离判据（8766 升级不可达 / 9001 全 404）+ ws_host 生命周期
+- [x] `tests/network/test_http_ws_e2e.py` / `test_http_cli_ws.py` — 改 WsServer 驱动；`test_http_ws_config.py` 删除（并入 test_ws_server.py）
+- [x] `tests/test_cli_ws_publish.py` / `test_cli_ws_wiring.py` / `test_cli_http.py` / `test_cli_http_lifecycle.py` — 双 server 装配/生命周期更新
+- [x] `tests/network/test_http_server.py` — origin 辅助 import 路径同步
+
+**Acceptance Criteria:**
+- Given 默认配置双 server 运行，when WS 客户端升级 8766 任意路径，then 升级不可达（未 accept、非 101），且 SSE/REST/静态页行为零改动
+- Given 默认配置，when HTTP 客户端请求 9001 的 /、/api/health、/api/runs，then 全 404
+- Given 同一 run，when 订阅/续传/cancel/ping 经 9001，then 语义与迁移前逐字一致（事件 seq 单调、游标续传、命令 ack）
+- Given `ws_cli_bypass_enabled=true`，when 经 9001 订阅 `/api/cli/ws`，then 跨轮次只读事件流语义保持
+- Given 第 limit+1 个订阅者，when 订阅，then `rate_limited` 错误帧且检查+登记原子
+- Given 缺 websockets，when 启动双 server，then WS server 绑定 + 安装诊断日志，HTTP 服务不受影响
+- Given 既有 HTTP 全量测试，when pytest，then 全绿（零改动或仅 import/装配同步）
+
+## Implementation Notes
+
+<!-- Agent-owned. Append-only during implementation. -->
+
+- 2026-10-24 实施完成，基线 `38c0b8e`。全部验证实测：`pytest -q` 3885 passed / 14 skipped；`pytest tests/test_architecture_contracts.py` 31 passed；`ruff check src tests` / `ruff format --check` / `mypy src` 全绿；`bandit -r src/ -ll` 退出码 0。
+- 与 spec 的两处实施级偏离（不影响验收边界）：① `origin.py` 除 Origin/Host 校验外一并随迁 `probe_host`（它依赖同批搬移的通配常量，留在 http_server 会造成跨模块常量导入）；② 两份 e2e 按 epic-54 retro 遗留意图**更名**——`test_http_ws_e2e.py → test_ws_e2e.py`、`test_http_cli_ws.py → test_cli_ws_e2e.py`（驱动 = WsServer，原名已失真）；`test_http_ws_config.py` 删除、断言并入 `test_ws_server.py`。
+- `tests/test_cli_ws_publish.py` 仅被 ruff format 触碰（格式化换行），无语义改动；其本就无 WS 耦合。
+- 实测修正记录：分离判据测试初版在异步用例里调同步 `urllib` 造成事件循环自阻塞假超时——改用异步裸 HTTP 助手 `_raw_status`；`_resolve_listener_port` 首版把 WS 基准端口误用 `http_port`，冒烟即抓出并参数化为 `default_port`。
+- brief 验收「8766 上 WS 升级 404」按裁定①A 钉实测：真实 Uvicorn 下未匹配升级回 HTTP 403（裸 socket 探测确认），ASGI 层为 WebSocketDisconnect(1000)；测试注释已注明。
+- `WsServer.start()` 补了旧 `HttpServer.start()` 的 `cli_hub.reopen()` 语义（close→start 重开后 hub 重武装，AD-5），e2e reopen 用例钉住。
+
+## Verification
+
+**Commands:**
+- `pytest tests/network/test_ws_server.py tests/network/test_http_ws_e2e.py tests/network/test_http_cli_ws.py -q` -- expected: 全绿
+- `pytest tests/test_architecture_contracts.py -q` -- expected: 全绿（依赖边界零放宽）
+- `pytest -q` -- expected: 全量绿（本机无 cov，见已知坑）
+- `ruff check src tests && ruff format --check src tests && mypy src` -- expected: 全绿
+- `bandit -r src/ -ll` -- expected: 无 HIGH/MEDIUM
+
+## Spec Change Log
+
+<!-- Append-only. step-04 填充。 -->
+
+## Review Triage Log
+
+<!-- Append-only. step-04 填充。 -->
diff --git a/_bmad-output/implementation-artifacts/epic-56-context.md b/_bmad-output/implementation-artifacts/epic-56-context.md
new file mode 100644
index 0000000..fad9b50
--- /dev/null
+++ b/_bmad-output/implementation-artifacts/epic-56-context.md
@@ -0,0 +1,43 @@
+# Epic 56 Context: WS 对外入口周期
+
+<!-- Compiled from planning artifacts. Edit freely. Regenerate with compile-epic-context if planning docs change. -->
+
+## Goal
+
+将 HTTP 与 WS **完全分离**为同进程两个独立 server：HTTP server 纯 HTTP+SSE（回环 only，控制台页 + REST + SSE，不再挂任何 WS 路由）；新 WS server 独立 ASGI app + 独立配置 + 独立监听器（默认 `127.0.0.1:9001`），零 HTTP 路由，是所有 WS 能力（run 订阅、CLI 旁路、经 WS 提交 run）的唯一宿主。WS 端口 8766 → 9001 是唯一 breaking change。经 WS 提交 run 翻 Epic 54 D2 案，使外部客户端（IDE 插件、桌面端、远程协作）获得生产价值；配置/项目/会话/对话框只走本机 HTTP。（注：本周期无 PRD/架构等标准规划工件，规划权威 = 周期目录内 brief.md + epics.md。）
+
+## Stories
+
+- Story 56.1: WS server 拆分与端点迁移
+- Story 56.2: 对外模式：认证与 TLS
+- Story 56.3: 经 WS 提交 run
+- Story 56.4: 文档、契约与质量门
+
+## Requirements & Constraints
+
+- 分离判据必须**可执行测试**：8766 上 WS 升级不可达（非 101）；9001 上无任何 HTTP API 面（控制台页/静态资源/REST/健康检查全 404）；HTTP/SSE 与本机 HTTP API 契约零改动。
+- 端点与事件分发**不重写**：`ws_server.py` 端点逻辑复用；`_RunRecord` / `CliEventHub` 状态源不动。
+- 错误信封单出口（`error_envelope` + `sanitize_message`），`HttpErrorCode` 封闭不新增。
+- 限额原子性：「检查 + 登记」同一无 `await` 同步方法（A9③ 口径）。
+- 断线语义：连接关闭只注销订阅者与登记，绝不取消运行；取消只来自显式 `cancel` 命令或 `DELETE`。
+- 传输层职责边界不变：`network/` 不导入运行栈与配置；跨模块数据一律 Pydantic 模型。
+- 新增/迁移 Settings 字段三处同步：`.env.example` + `catalog.classify` 归组 + `docs/frame.md` 配置表。
+- `pytest` / ruff / mypy / bandit / 架构契约测试全绿。
+
+## Technical Decisions
+
+- **D1 拓扑**：HTTP 与 WS 完全分离；既有两条 WS 端点（`/api/runs/{run_id}/ws`、`/api/cli/ws`）路径不变、换端口。
+- **D2 能力边界**：WS = 订阅 + `cancel`/`ping` + 提交 run（等价 `POST /api/runs`）；配置/项目/会话/对话框 WS 不可达。
+- **D3 认证**：静态 token（用户级 setting.md 真源），Bearer 握手校验，失败未 accept 前 close(1008)。
+- **D4 TLS**：原生 TLS 可选（cert/key 配齐即 wss）；不配 = 明文 + 启动告警；不引入反向代理。
+- **D5 监听模式**：单监听器按绑定地址切模式——回环 = 本地模式（Origin 防线、无认证）；非回环 = 对外模式（token 缺失拒绝启动 fail-closed、认证强制、Origin 不适用）。
+- **D6 并发语义**：期一单用户不变，所有 WS 连接共享同一运行状态机与名额。
+- **D7 CLI 旁路归属**：`/api/cli/ws` 随迁移进 WS server。
+- 立场口径：WS 与 HTTP/SSE 同为入口面**非安全边界**，OS 沙箱兜底立场不变；对外能提交 run ⇒ Epic 53 沙箱档从建议升级为强烈建议（文档义务在 56-4）。
+- 任一冻结决策（D1–D7）变更须经用户裁定并回写 brief.md；实现期发现冲突先报告再改。
+
+## Cross-Story Dependencies
+
+- 交付顺序 `56-1 → (56-2 ∥ 56-3) → 56-4`；56-2/56-3 只依赖 56-1，可并行；56-4 依赖 56-2 与 56-3。
+- 56-1 同时承担 Epic 54 retro 遗留的测试面重建（替身纯逻辑面 `test_ws_server.py` / WS 端到端）。
+- 与 Epic 54 D1（WS 与 SSE 同 app 同端口）冲突已显性取代其拓扑部分；与 Epic 49 AD-6（无反向代理）不冲突。
diff --git a/docs/frame.md b/docs/frame.md
index afd657e..eaf5868 100644
--- a/docs/frame.md
+++ b/docs/frame.md
@@ -857,8 +857,11 @@ HeAgentError (base)
 | `http_port_auto_find_attempts` | 10 | 端口被占用时自动**顺延**的尝试次数（`port+1…`）；**默认 10 = 开启**（2026-10-15 契约修订：多开实例不冲突；原默认 0 = fail-loud，源自 Epic 49 Story 49-2——hang 根因「显式端口被改写」已修，显式 `--port` 契约保留）。Windows 下探测 socket 不设 `SO_REUSEADDR`，与真实监听语义一致，避免占用探测失真。2026-09-27 加入 |
 | `http_max_connections` | 16 | 同时打开的 HTTP 客户端连接上限（交给 Uvicorn `limit_concurrency`，超限连接被直接拒绝而非排队） |
 | `http_max_subscribers` | 16 | **每 run** 的 SSE 订阅者上限（同一 run 的并发事件流；超限回 429 `rate_limited`）。与 WS 连接额度独立。 |
-| `http_ws_max_connections` | 16 | **每 run** 的 WebSocket 连接上限；独立于 SSE 订阅池，超额连接在 accept 后收到 `rate_limited` 错误帧。CLI 旁路（`http_cli_ws_enabled`）复用同一个数值，但按**整条旁路流**计（旁路只有一条流）。 |
-| `http_cli_ws_enabled` | False | **CLI 旁路订阅开关**（Epic 55）：开启时默认 CLI 的内嵌 listener 多注册一条 `WS /api/cli/ws`，把**终端里那一轮** run 的事件（文本增量 / 工具调用 / 终态）实时推给旁路订阅者。只读、跨轮次、不占运行名额、不写会话历史、没有 `cancel` 通道（终端独占 Ctrl+C / 双击 Esc）。**默认关**——与 HTTP 入口同档无认证无 TLS，开了等于让本机能连上该端口的进程看到终端 agent 的工具输出（可能含文件内容）。 |
+| `ws_host` | `127.0.0.1` | WS listener 绑定地址（Epic 56 D1：与 HTTP 完全分离的独立 server）；非回环值同 HTTP 口径告警。回环绑定 = 本地模式（Origin 防线）；非回环 = 对外模式（认证强制 + fail-closed，56-2 落地） |
+| `ws_port` | 9001 | WS 入口端口（1..65535）。两条 WS 端点路径不变、端口 8766 → 9001 是 Epic 56 的**唯一 breaking change** |
+| `ws_max_connections` | 16 | **每 run** 的 WebSocket 连接上限 + CLI 旁路 hub 的连接总额（迁移自 `http_ws_max_connections`）；独立于 SSE 订阅池，超额在 accept 后收到 `rate_limited` 错误帧（检查+登记同一步） |
+| `ws_shutdown_timeout` | 5 | WS server 关闭排空的等待上限（秒）：关既有订阅连接 → 停 listener |
+| `ws_cli_bypass_enabled` | False | **CLI 旁路订阅开关**（Epic 55，Epic 56 D7 起宿主 = WS server）：开启时 WS listener 注册 `WS /api/cli/ws`，把**终端里那一轮** run 的事件（文本增量 / 工具调用 / 终态）实时推给旁路订阅者。只读、跨轮次、不占运行名额、不写会话历史、没有 `cancel` 通道（终端独占 Ctrl+C / 双击 Esc）。**默认关**——与 HTTP 入口同档无认证无 TLS，开了等于让本机能连上该端口的进程看到终端 agent 的工具输出（可能含文件内容）。 |
 | `http_max_inflight_runs` | 1 | **每项目**同时在途的网页 Agent 运行上限（MVP 单会话单运行；超限提交收 `run_conflict`） |
 | `http_max_total_inflight` | 0 | **服务级**在途运行总额（跨项目共享）；0 = 不限 ⇒ 不设时全局上限 = 项目数 × `http_max_inflight_runs`；超限提交收 `total_inflight_limit`（2026-09-27 新增） |
 | `http_max_request_bytes` | 394240 | 单个 JSON 请求体的字节上限（超限收 `request_too_large`）。默认 = `12 × MAX_PROMPT_CHARS(32768) + 1 KiB` 信封，**保证协议允许的最大 prompt 在任何客户端编码下都发得进来**（旧默认 65536 使中文约 2.18 万字就撞 413——2026-09-23 修复；三处默认值的关系由 `tests/network/test_http_protocol.py` 钉住） |
@@ -1238,7 +1241,7 @@ WebSocket 与 HTTP/SSE **并存**，不改变 SSE 契约。端点为
 | 事件与续传 | WS 复用 `_RunRecord` 的 ring buffer、单调 `seq`、背压踢除和终态哨兵；`?last_event_id=N` 只补 `seq > N`，越过窗口返回 `resync_required` 错误帧。 |
 | 命令 | `cancel` 与 `DELETE /api/runs/{run_id}` 使用同一协作式取消语义并保持幂等；`ping` 返回 `ack`。断线只注销 WS 连接，不取消 run。 |
 | 同源防线 | WS 升级在 `accept()` 前复用 `_request_origin_violation` 校验 Host/Origin。Origin 违规时客户端看到 HTTP 403、无错误 body；缺少 Origin 的非浏览器客户端按既有 HTTP 口径放行。既有 ASGI 中间件对 `scope["type"] != "http"` 直接放行，因此 CSWSH 防线由 WS 层单独执行。 |
-| 限额与心跳 | `HTTP_WS_MAX_CONNECTIONS` 默认 `16`，按 run 独立于 SSE 订阅池；检查与登记在同一同步方法完成。心跳使用协议级 ping，`ws_ping_interval=15s`、`ws_ping_timeout=20s`，不发送应用层心跳帧。 |
+| 限额与心跳 | `WS_MAX_CONNECTIONS` 默认 `16`，按 run 独立于 SSE 订阅池；检查与登记在同一同步方法完成。心跳使用协议级 ping，`ws_ping_interval=15s`、`ws_ping_timeout=20s`，不发送应用层心跳帧。 |
 | 入站上界 | 应用层命令文本最多 `4096` 个字符；Uvicorn `ws_max_size=64 KiB`。应用层超限关闭码为 `1009`。关闭码 `1000` 表示正常结束，`1001` 表示服务关停，`1008` 表示策略/协议违规，`1011` 表示内部错误。 |
 | 可选依赖 | `websockets>=13.0,<18` 直接声明在 `http` extra；服务端不直接导入 `websockets`，由 Uvicorn 选择协议实现。缺少实现时 HTTP 仍可启动，并记录一次 `ws_unavailable` 安装诊断。 |
 | 安全立场 | WS 与 HTTP/SSE 同档：无认证、无 TLS、回环不等于可信，也不是安全边界；Origin 校验只是 CSWSH 防御的纵深措施，OS 级沙箱兜底立场不变。 |
@@ -1250,13 +1253,13 @@ WebSocket 与 HTTP/SSE **并存**，不改变 SSE 契约。端点为
 
 | 关注点 | 实现事实 |
 | --- | --- |
-| 状态源 | `network/cli_event_hub.py::CliEventHub`：seq 跨轮次单调、环形缓冲 `CLI_EVENT_BUFFER_SIZE`(256)、订阅席位上限（取 `HTTP_WS_MAX_CONNECTIONS`，按**整条流**计）、`close()` / `reopen()` 与 `HttpRunService` 同形态。**不建 run 记录**，因此不存在"淘汰 / 会话投影 / 取消"这些 HTTP 侧的语义。 |
+| 状态源 | `network/cli_event_hub.py::CliEventHub`：seq 跨轮次单调、环形缓冲 `CLI_EVENT_BUFFER_SIZE`(256)、订阅席位上限（取 `WS_MAX_CONNECTIONS`，按**整条流**计）、`close()` / `reopen()` 与 `HttpRunService` 同形态。**不建 run 记录**，因此不存在"淘汰 / 会话投影 / 取消"这些 HTTP 侧的语义。 |
 | 帧契约 | `WsCliEventFrame`（`type` + **`run_id`** + `event`）与 `WsCliAckFrame`（`command` + `run_id`，**不带** `RunStatus`）。与 `WsEventFrame` / `WsAckFrame` 分开定义 ⇒ `/api/runs/{id}/ws` 的既有契约逐字不变。 |
 | 命令面 | 仅 `ping`（回 ack，`run_id` 为空串表示此刻没有在跑的轮次）。`cancel` 回 `invalid_request` 错误帧但**不关闭连接**——旁路不拥有运行，「不支持」必须显式告知，不能静默忽略。 |
 | 续传与背压 | `?last_event_id=N` 只补 `seq > N`；窗口已淘汰开头（含「无游标但 `oldest_seq > 1`」）回 `resync_required` 错误帧。订阅队列与缓冲同界，落后一整窗口即结束该流（客户端带游标重连）——与 SSE / run-WS 同一口径。 |
 | 发布点 | 入口层 `cli/interactive.py`：`_consume_stream` 逐条镜像 `StreamEvent`（text / tool_call / tool_result / done），进入即 `begin_run`、退出（含取消与异常）即 `end_run`；单次模式走非流式 `loop.run`，只发一条终态 `done`，**不假装有增量**。中枢经 `ContextVar` 传递（`_run_prompt` 的签名是 3 处测试 patch 的契约，不能加参数）。 |
 | 故障隔离 | 中枢 `publish_*` 自身不抛；入口层 `_hub_call` 是第二道垫片——旁路坏了最坏只是「外部看不到」，终端输出 / 退出码 / 主循环状态逐字不变。 |
-| 装配 | `cli/http.py::build_http_service` 在 `HTTP_CLI_WS_ENABLED` 为真时建 hub 并注入 `HttpServer(cli_hub=...)`；未注入 ⇒ 路由不注册（Uvicorn 在「应用未 accept」时给客户端裸 403，不是应用层 404）。开启时 stderr 打一行 `[http] CLI event stream (read-only): ws://…/api/cli/ws`，避免「开了但不知道在哪」。 |
+| 装配 | `cli/http.py::build_http_service` 在 `WS_CLI_BYPASS_ENABLED` 为真时建 hub 并注入 `WsServer(cli_hub=...)`（Epic 56 D7 起宿主 = WS server，9001）；未注入 ⇒ 路由不注册（Uvicorn 在「应用未 accept」时给客户端裸 403，不是应用层 404）。开启时 stderr 打一行 `[ws] CLI event stream (read-only): ws://…/api/cli/ws`，避免「开了但不知道在哪」。 |
 | 同源防线 | 与 run-WS 共用 `_request_origin_violation`（accept 前校验，违规 close ⇒ 客户端拿 403）。既有 ASGI 中间件对非 `http` scope 放行，故 CSWSH 防线由 WS 层单独执行。 |
 | 安全立场 | 与 HTTP/SSE/WS 同档：**无认证、无 TLS、回环不等于可信**，Origin 校验只是纵深措施；默认关，需要时显式开，OS 级沙箱兜底立场不变。 |
 
diff --git a/src/heagent/cli/http.py b/src/heagent/cli/http.py
index 58af02c..2c3e22c 100644
--- a/src/heagent/cli/http.py
+++ b/src/heagent/cli/http.py
@@ -42,12 +42,10 @@ from heagent.network.http_server import (
     HttpServerConfig,
     HttpStartupError,
 )
+from heagent.network.ws_host import CLI_WS_PATH, WsServer, WsServerConfig, WsStartupError
 from heagent.pub.safe_logging import safe_log
 from heagent.pub.workspace import WorkspacePaths
 
-# 与 ``network/`` 的路由常量保持一致（这里要用它打印公告，避免两处各写一个字面量）。
-_CLI_WS_PATH = "/api/cli/ws"
-
 logger = logging.getLogger(__name__)
 
 
@@ -67,6 +65,20 @@ def _reject_non_finite(ctx: click.Context, param: click.Parameter, value: float
     return value
 
 
+def _resolve_listener_port(settings: Settings, host: str, requested: int | None, *, default_port: int) -> int:
+    """解析 listener 端口：显式指定是契约（冲突 fail-loud）；未指定时从 ``default_port`` 起顺延（HTTP/WS 共用）。"""
+    target = default_port if requested is None else requested
+    if requested is not None or settings.http_port_auto_find_attempts <= 0:
+        return target
+    from heagent.cli.port_finder import find_available_port
+
+    try:
+        return find_available_port(target, host=host, max_attempts=settings.http_port_auto_find_attempts)
+    except RuntimeError:
+        # 所有尝试都失败，使用原端口（让后续绑定失败并报错）
+        return target
+
+
 def build_server_config(
     settings: Settings,
     *,
@@ -74,7 +86,6 @@ def build_server_config(
     port: int | None = None,
     max_connections: int | None = None,
     max_subscribers: int | None = None,
-    ws_max_connections: int | None = None,
     max_inflight_runs: int | None = None,
     max_total_inflight: int | None = None,
     max_request_bytes: int | None = None,
@@ -97,33 +108,13 @@ def build_server_config(
     2026-10-15 起默认开启）。显式 ``--port`` 是契约：冲突时保持原端口、交由绑定失败显性报错
     ——否则「启动失败」会静默变成「服务跑在另一个端口上」，脚本与状态行都无从知晓（NFR-10 无回归）。
     """
-    # 解析端口，支持自动查找
-    target_port = settings.http_port if port is None else port
     target_host = settings.http_host if host is None else host
 
-    # 只在端口未由调用方显式指定时才顺延（显式端口的冲突必须 fail-loud）
-    if port is None and settings.http_port_auto_find_attempts > 0:
-        from heagent.cli.port_finder import find_available_port
-
-        try:
-            final_port = find_available_port(
-                target_port,
-                host=target_host,
-                max_attempts=settings.http_port_auto_find_attempts,
-            )
-        except RuntimeError:
-            # 所有尝试都失败，使用原端口（让后续绑定失败并报错）
-            final_port = target_port
-    else:
-        # 禁用自动查找
-        final_port = target_port
-
     return HttpServerConfig(
         host=target_host,
-        port=final_port,
+        port=_resolve_listener_port(settings, target_host, port, default_port=settings.http_port),
         max_connections=settings.http_max_connections if max_connections is None else max_connections,
         max_subscribers=settings.http_max_subscribers if max_subscribers is None else max_subscribers,
-        ws_max_connections=(settings.http_ws_max_connections if ws_max_connections is None else ws_max_connections),
         max_inflight_runs=settings.http_max_inflight_runs if max_inflight_runs is None else max_inflight_runs,
         max_total_inflight=(settings.http_max_total_inflight if max_total_inflight is None else max_total_inflight),
         max_request_bytes=settings.http_max_request_bytes if max_request_bytes is None else max_request_bytes,
@@ -136,48 +127,64 @@ def build_server_config(
     )
 
 
-async def _serve_http(server: HttpServer) -> None:
-    """启动服务并运行到取消 / 关闭；启动消息只走 stderr。
+async def _serve_web(http_server: HttpServer, ws_server: WsServer) -> None:
+    """启动双 server 并运行到取消 / 关闭（Epic 56 D1：HTTP 与 WS 完全分离、入口层统一编排）。
 
     ``start()`` 在 try 之外：它失败时要么 listener 没建起来、要么内部已回滚，不需要再 close；
     一旦进入服务循环，任何退出路径都必须走 ``close()``，否则 Ctrl+C 会留下悬挂的 listener。
     """
-    await server.start()
+    await http_server.start()
+    try:
+        # WS 起不来（端口被占且显式指定 / 就绪探测失败）时回滚 HTTP，绝不留「HTTP 活着、
+        # WS 缺席」的半启动状态——那正是 AD-5 禁止的假可用。
+        await ws_server.start()
+    except BaseException:
+        await http_server.close()
+        raise
     click.echo(
-        f"[http] listening on http://{server.address}  (open this URL in a browser; no authentication)",
+        f"[http] listening on http://{http_server.address}  (open this URL in a browser; no authentication)",
         err=True,
     )
+    click.echo(f"[ws] listening on ws://{ws_server.address}  (run & CLI WebSocket entry; no authentication)", err=True)
     try:
-        await server.serve_forever()
+        await asyncio.gather(http_server.serve_forever(), ws_server.serve_forever())
     finally:
-        await server.close()
+        # D1 关停顺序：HTTP 先（排空运行到终态），WS 后（关残余订阅连接 + listener）。
+        await http_server.close()
+        await ws_server.close()
 
 
 class EmbeddedHttpService:
-    """默认 CLI **内嵌** HTTP 服务的生命周期（同进程、同一 asyncio 生命周期）。
+    """默认 CLI **内嵌**网页入口的生命周期（同进程、同一 asyncio 生命周期）。
 
-    与 :func:`_serve_http`（显式 `http-server` 命令「跑到底」的形态）的区别：内嵌服务是**伴随**
-    CLI 的——交互模式与 REPL 共存、单次模式与那次 run 并存，CLI 生命周期结束时一起收尾。
+    Epic 56 D1 起入口 = **双 server**：HTTP listener（8766，控制台 + REST/SSE）+ WS listener
+    （9001，run 订阅 + CLI 旁路的唯一宿主）。名字保留 ``EmbeddedHttpService``：它仍是入口层
+    那个「伴随 CLI 的网页服务」单元，只是自此拥有两条 listener、一个生命周期。
 
-    - ``start()``：绑定 + 就绪门禁（失败直接抛，调用方**必须**让命令失败，不得进入「看起来正常
-      但没有网页入口」的半启动状态）+ 后台 serve 任务 + stderr 公告；
-    - ``close()``：幂等、全程有界（关闭 listener → 等 serve 循环退出，超时则取消）；
-    - ``failure``：serve 循环**意外**结束时的异常。交互模式每轮检查它——HTTP 挂掉而 CLI 还在
-      正常聊天，等于「页面打不开但看着一切正常」，正是 AD-5 要消除的假可用状态。
+    - ``start()``：先 HTTP 后 WS 绑定 + 就绪门禁（WS 失败回滚 HTTP 并抛错）+ 后台 serve 任务 + stderr 公告；
+    - ``close()``：幂等、全程有界，**HTTP 先**（排空运行到终态）**WS 后**（关订阅连接 + listener）；
+    - ``failure``：任一 serve 循环**意外**结束时的首个异常。交互模式每轮检查它——任一 listener
+      挂掉而 CLI 还在正常聊天，等于「页面/订阅打不开但看着一切正常」，正是 AD-5 要消除的假可用状态。
     """
 
-    def __init__(self, server: HttpServer, *, cli_hub: Any | None = None) -> None:
-        self._server = server
-        # CLI 旁路中枢（Epic 55）：``None`` = 未开启（路由未注册，客户端拿不到这条流）。
+    def __init__(self, http_server: HttpServer, ws_server: WsServer, *, cli_hub: Any | None = None) -> None:
+        self._http = http_server
+        self._ws = ws_server
+        # CLI 旁路中枢（Epic 55，Epic 56 D7 起宿主 = WS listener）：``None`` = 未开启。
         self._cli_hub = cli_hub
-        self._task: asyncio.Task[None] | None = None
+        self._tasks: list[asyncio.Task[None]] = []
         self._failure: BaseException | None = None
         self._closed = False
 
     @property
     def address(self) -> str:
-        """实际监听地址（stderr 公告与诊断用）。"""
-        return self._server.address
+        """HTTP listener 实际监听地址（stderr 公告与诊断用）。"""
+        return self._http.address
+
+    @property
+    def ws_address(self) -> str:
+        """WS listener 实际监听地址（stderr 公告与诊断用）。"""
+        return self._ws.address
 
     @property
     def cli_hub(self) -> Any | None:
@@ -186,22 +193,36 @@ class EmbeddedHttpService:
 
     @property
     def failure(self) -> BaseException | None:
-        """serve 循环意外结束时的异常；仍在服务或已被正常关闭时为 ``None``。"""
+        """serve 循环意外结束时的首个异常；仍在服务或已被正常关闭时为 ``None``。"""
         return self._failure
 
     async def start(self) -> None:
-        """启动服务并进入后台服务循环；绑定 / 就绪失败时抛错且不留下任务。"""
-        await self._server.start()
-        self._task = asyncio.create_task(self._server.serve_forever(), name="heagent-http-serve")
-        self._task.add_done_callback(self._on_serve_done)
+        """启动双 server 并进入后台服务循环；绑定 / 就绪失败时抛错且不留下任务。"""
+        await self._http.start()
+        try:
+            # WS 起不来时回滚已启动的 HTTP：半启动（HTTP 活着、WS 缺席）是 AD-5 禁止的假可用。
+            await self._ws.start()
+        except BaseException:
+            await self._http.close()
+            raise
+        self._tasks = [
+            asyncio.create_task(self._http.serve_forever(), name="heagent-http-serve"),
+            asyncio.create_task(self._ws.serve_forever(), name="heagent-ws-serve"),
+        ]
+        for task in self._tasks:
+            task.add_done_callback(self._on_serve_done)
         click.echo(
             f"[http] web UI: http://{self.address}  (local only; no authentication)",
             err=True,
         )
+        click.echo(
+            f"[ws] event stream: ws://{self.ws_address}  (local only; no authentication)",
+            err=True,
+        )
         if self._cli_hub is not None:
             # 开启即多暴露一条无认证通道：把地址打出来，别让用户「开了但不知道在哪」。
             click.echo(
-                f"[http] CLI event stream (read-only): ws://{self.address}{_CLI_WS_PATH}"
+                f"[ws] CLI event stream (read-only): ws://{self.ws_address}{CLI_WS_PATH}"
                 "  (local only; no authentication)",
                 err=True,
             )
@@ -215,33 +236,38 @@ class EmbeddedHttpService:
             return
         if self._closed:
             # 关闭期间 serve 循环因 listener 已关闭而报错属正常收尾，不该污染 `failure`。
-            _safe_log(logging.WARNING, "HTTP serve loop ended during shutdown: %s", error)
+            _safe_log(logging.WARNING, "%s ended during shutdown: %s", task.get_name(), error)
             return
-        self._failure = error
-        _safe_log(logging.ERROR, "HTTP serve loop stopped unexpectedly: %s", error)
+        if self._failure is None:
+            self._failure = error
+        _safe_log(logging.ERROR, "%s stopped unexpectedly: %s", task.get_name(), error)
 
     async def close(self) -> None:
-        """停止服务并回收 serve 任务（幂等、有界）。"""
+        """停止双 server 并回收 serve 任务（幂等、有界；HTTP 先 WS 后）。"""
         if self._closed:
             return
         self._closed = True
-        await self._server.close()
-        task, self._task = self._task, None
-        if task is None or task is asyncio.current_task():
-            return
-        budget = self._server.config.shutdown_timeout + 1.0
-        try:
-            await asyncio.wait_for(task, timeout=budget)
-        except TimeoutError:
-            _safe_log(logging.WARNING, "HTTP serve loop did not stop within %.1fs; cancelling", budget)
-            task.cancel()
-            with contextlib.suppress(Exception):
-                await task
-        except asyncio.CancelledError:
-            raise
-        except Exception as exc:
-            # 已在 done callback 记过 ERROR：此处既不重抛（会掩盖退出原因），也不静默（已记录）。
-            _safe_log(logging.WARNING, "HTTP serve loop ended while closing: %s", exc)
+        # D1 关停顺序：HTTP 的 close() 排空在途运行到终态（SSE 随之终结），WS 的 close() 再关
+        # 残余订阅连接与 listener——顺序颠倒会让订阅者错过终态事件。
+        await self._http.close()
+        await self._ws.close()
+        tasks, self._tasks = self._tasks, []
+        budget = max(self._http.config.shutdown_timeout, self._ws.config.shutdown_timeout) + 1.0
+        for task in tasks:
+            if task is None or task is asyncio.current_task():
+                continue
+            try:
+                await asyncio.wait_for(task, timeout=budget)
+            except TimeoutError:
+                _safe_log(logging.WARNING, "%s did not stop within %.1fs; cancelling", task.get_name(), budget)
+                task.cancel()
+                with contextlib.suppress(Exception):
+                    await task
+            except asyncio.CancelledError:
+                raise
+            except Exception as exc:
+                # 已在 done callback 记过 ERROR：此处既不重抛（会掩盖退出原因），也不静默（已记录）。
+                _safe_log(logging.WARNING, "%s ended while closing: %s", task.get_name(), exc)
 
     async def __aenter__(self) -> EmbeddedHttpService:
         await self.start()
@@ -251,20 +277,45 @@ class EmbeddedHttpService:
         await self.close()
 
 
+def build_ws_server_config(
+    settings: Settings,
+    *,
+    host: str | None = None,
+    port: int | None = None,
+    max_connections: int | None = None,
+    shutdown_timeout: float | None = None,
+) -> WsServerConfig:
+    """把 CLI 覆盖（``None`` = 未覆盖）合并到 ``Settings`` 的 WS 配置（口径同 :func:`build_server_config`）。
+
+    不写回 Settings；范围规则由 :class:`WsServerConfig`（Pydantic）统一校验。端口自动查找与
+    HTTP listener 同一开关（``http_port_auto_find_attempts``）：两条 listener 独立顺延
+    （HTTP 自 8766、WS 自 9001），实际端口以启动公告为准。
+    """
+    resolved_host = settings.ws_host if host is None else host
+    return WsServerConfig(
+        host=resolved_host,
+        port=_resolve_listener_port(settings, resolved_host, port, default_port=settings.ws_port),
+        ws_max_connections=settings.ws_max_connections if max_connections is None else max_connections,
+        shutdown_timeout=settings.ws_shutdown_timeout if shutdown_timeout is None else shutdown_timeout,
+    )
+
+
 def build_http_service(settings: Settings, *, executor: Any | None = None) -> EmbeddedHttpService:
-    """按 ``Settings`` 构造默认 CLI 的内嵌 HTTP 服务。
+    """按 ``Settings`` 构造默认 CLI 的内嵌网页入口（双 server：HTTP 8766 + WS 9001，Epic 56 D1）。
 
-    默认 CLI **不提供** HTTP 相关 CLI 选项（brief：不做含糊的参数透传），因此这里不带覆盖参数——
-    绑定地址与限额全部来自 ``HTTP_*`` 设置；需要覆盖时用显式 `heagent http-server`。
+    默认 CLI **不提供** HTTP/WS 相关 CLI 选项（brief：不做含糊的参数透传），因此这里不带覆盖参数——
+    绑定地址与限额全部来自 ``HTTP_*`` / ``WS_*`` 设置；需要覆盖时用显式 `heagent http-server`。
 
-    ``executor`` 是运行入口（入口层的 :class:`HttpAgentHandler`）：为 ``None`` 时服务只提供健康检查与
-    静态页（Story 49-1 的形态），``/api/runs*`` 与 ``/api/session`` 不注册。
+    ``executor`` 是运行入口（入口层的 :class:`HttpAgentHandler`）：为 ``None`` 时 HTTP 只提供健康
+    检查与静态页（Story 49-1 的形态），``/api/runs*`` 与 ``/api/session`` 不注册；WS 侧的 run
+    订阅端点同样不注册（端点随 ``run_service`` 注入）。
 
-    ``settings.http_cli_ws_enabled`` 为真时**另建**一个 :class:`CliEventHub` 并注册 ``/api/cli/ws``
-    （Epic 55 的 CLI 旁路）：它与 ``executor`` 无关——旁路订阅的是**终端自己那一轮** run，不是网页
-    创建的 run；两者共用同一个 listener 端口。
+    ``settings.ws_cli_bypass_enabled`` 为真时**另建**一个 :class:`CliEventHub` 并在 WS server 上
+    注册 ``/api/cli/ws``（Epic 55 的 CLI 旁路，Epic 56 D7 起宿主 = WS server）：它与 ``executor``
+    无关——旁路订阅的是**终端自己那一轮** run，不是网页创建的 run。
     """
     config = build_server_config(settings)
+    ws_config = build_ws_server_config(settings)
     run_service = HttpRunService(config, executor) if executor is not None else None
     workspace = WorkspacePaths.from_root(getattr(settings, "workspace_root", None) or os.getcwd())
     console = HttpProjectConsole(
@@ -276,15 +327,15 @@ def build_http_service(settings: Settings, *, executor: Any | None = None) -> Em
         handler_factory=executor.for_workspace if isinstance(executor, HttpAgentHandler) else None,
         write_enabled=settings.http_console_write_enabled,
     )
-    cli_hub = CliEventHub(max_connections=config.ws_max_connections) if settings.http_cli_ws_enabled else None
+    cli_hub = CliEventHub(max_connections=ws_config.ws_max_connections) if settings.ws_cli_bypass_enabled else None
     return EmbeddedHttpService(
         HttpServer(
             config,
             version=_current_version(),
             run_service=run_service,
             console=console,
-            cli_hub=cli_hub,
         ),
+        WsServer(ws_config, run_service=run_service, cli_hub=cli_hub),
         cli_hub=cli_hub,
     )
 
@@ -297,6 +348,8 @@ def embedded_http_error_message(exc: BaseException) -> str | None:
     """
     if isinstance(exc, HttpStartupError):
         return f"HTTP server failed to start: {exc}"
+    if isinstance(exc, WsStartupError):
+        return f"WS server failed to start: {exc}"
     if isinstance(exc, HttpDependencyError):
         return str(exc)
     return None
@@ -326,11 +379,22 @@ def embedded_http_error_message(exc: BaseException) -> str | None:
     default=None,
     help="Max SSE subscribers per run; extra ones get 429 rate_limited (default: HTTP_MAX_SUBSCRIBERS / 16)",
 )
+@click.option(
+    "--ws-host",
+    default=None,
+    help="WS listener bind address (default: WS_HOST / 127.0.0.1)",
+)
+@click.option(
+    "--ws-port",
+    type=click.IntRange(min=1, max=65535),
+    default=None,
+    help="WS listener bind port (default: WS_PORT / 9001)",
+)
 @click.option(
     "--ws-max-connections",
     type=click.IntRange(min=1),
     default=None,
-    help="Max WebSocket connections per run (default: HTTP_WS_MAX_CONNECTIONS / 16)",
+    help="Max WebSocket connections (per run and CLI hub total; default: WS_MAX_CONNECTIONS / 16)",
 )
 @click.option(
     "--max-inflight-runs",
@@ -406,6 +470,8 @@ def http_server_cmd(
     port: int | None,
     max_connections: int | None,
     max_subscribers: int | None,
+    ws_host: str | None,
+    ws_port: int | None,
     ws_max_connections: int | None,
     max_inflight_runs: int | None,
     max_total_inflight: int | None,
@@ -442,7 +508,6 @@ def http_server_cmd(
         port=port,
         max_connections=max_connections,
         max_subscribers=max_subscribers,
-        ws_max_connections=ws_max_connections,
         max_inflight_runs=max_inflight_runs,
         max_total_inflight=max_total_inflight,
         max_request_bytes=max_request_bytes,
@@ -460,6 +525,7 @@ def http_server_cmd(
         sandbox_backend=sandbox,
         soul_path=soul,
     )
+    ws_config = build_ws_server_config(settings, host=ws_host, port=ws_port, max_connections=ws_max_connections)
     workspace = WorkspacePaths.from_root(os.getcwd())
     run_service = HttpRunService(config, handler)
     console = HttpProjectConsole(
@@ -476,13 +542,18 @@ def http_server_cmd(
         run_service=run_service,
         console=console,
     )
+    ws_server = WsServer(ws_config, run_service=run_service)
     # 非回环绑定：启动前先向 stderr 打印一次明确告警（无认证 / 无 TLS / 非生产安全边界）。
-    # 判定与文案来自 ``network.exposure``——与 ``HttpServer.start()`` 的 ``event=exposed`` 同源。
+    # 判定与文案来自 ``network.exposure``——与 ``HttpServer.start()`` / ``WsServer.start()``
+    # 的 ``event=exposed`` 同源；WS 的对外模式（认证 fail-closed）在 56-2 落地。
     warning = exposure_warning(config.host)
     if warning is not None:
         click.echo(f"[http] WARNING: {warning}", err=True)
+    ws_warning = exposure_warning(ws_config.host)
+    if ws_warning is not None:
+        click.echo(f"[ws] WARNING: {ws_warning}", err=True)
     try:
-        asyncio.run(_serve_http(server))
+        asyncio.run(_serve_web(server, ws_server))
     except KeyboardInterrupt:
         # Ctrl+C：asyncio.run 先取消主任务、跑完 ``_serve_http`` 的 finally（有界 close），再把
         # KeyboardInterrupt 抛回来。用户主动停止不是错误——安静退出，不打印 traceback。
@@ -490,6 +561,8 @@ def http_server_cmd(
     except HttpStartupError as exc:
         # 绑定失败 / 就绪探测失败：只给一行可诊断文案，不打印任何「已监听」，也不吐 traceback。
         raise click.ClickException(f"HTTP server failed to start: {exc}") from None
+    except WsStartupError as exc:
+        raise click.ClickException(f"WS server failed to start: {exc}") from None
     except HttpDependencyError as exc:
         raise click.ClickException(str(exc)) from None
 
diff --git a/src/heagent/cli/interactive.py b/src/heagent/cli/interactive.py
index 2cf50d6..1938af9 100644
--- a/src/heagent/cli/interactive.py
+++ b/src/heagent/cli/interactive.py
@@ -96,7 +96,7 @@ logger = logging.getLogger(__name__)
 async def _cli_hub_scope(http: Any) -> AsyncIterator[Any]:
     """把内嵌 HTTP 服务上的旁路中枢挂到当前任务的 contextvar 上。
 
-    服务未开启旁路（`HTTP_CLI_WS_ENABLED` 关）或测试替身没有该属性时，作用域里是 ``None`` ——
+    服务未开启旁路（`WS_CLI_BYPASS_ENABLED` 关）或测试替身没有该属性时，作用域里是 ``None`` ——
     所有发布点因此天然是空操作，不需要在调用处再判一次「功能开没开」。
     """
     hub = getattr(http, "cli_hub", None)
diff --git a/src/heagent/config/__init__.py b/src/heagent/config/__init__.py
index f5f1c2e..eedce6c 100644
--- a/src/heagent/config/__init__.py
+++ b/src/heagent/config/__init__.py
@@ -398,14 +398,6 @@ class Settings(BaseSettings):
     # 错误信封 / 安全响应头 / 访问日志全部缺席，429 rate_limited 分支实际不可达。
     # 默认值与原连接额度一致（16）⇒ **默认行为逐字节不变**；调大连接额度时订阅面不再被迫同步放大。
     http_max_subscribers: int = Field(default=16, ge=1)
-    # 每个 run 的独立 WebSocket 连接额度。Uvicorn 的 limit_concurrency 不限制 WS；
-    # 与 SSE 订阅池分离，避免 WS 连接消耗 SSE 配额并污染 subscriber_count 语义。
-    http_ws_max_connections: int = Field(default=16, ge=1)
-    # CLI 旁路订阅（Epic 55）：给 `WS /api/cli/ws` 开一条只读事件流，把**终端里那一轮** run 的
-    # 事件（文本增量 / 工具调用 / 终态）实时推给外部客户端。**默认关**——它与 HTTP 入口同档
-    # 无认证、无 TLS，开了等于让能连上该端口的本机进程看到终端 agent 的工具输出（可能含文件内容）；
-    # 旁路不占运行名额、不写会话历史、不提供取消通道（终端独占 Ctrl+C / 双击 Esc）。
-    http_cli_ws_enabled: bool = False
     # 同时在途的网页 Agent 运行上限；MVP 固定为 1（单会话单运行），超限的提交收 run_conflict。
     http_max_inflight_runs: int = Field(default=1, ge=1)
     # **服务级**在途运行总额（跨项目共享）；0 = 不限（默认 ⇒ D9 的「并发随项目数线性」语义不变）。
@@ -433,6 +425,23 @@ class Settings(BaseSettings):
     http_tool_inflight_timeout: float = Field(default=3600.0, ge=0, allow_inf_nan=False)
     # 服务关闭时「停止接收 → 终结在途 run → 关闭订阅 → 关闭 listener」全程的等待上限（秒）。
     http_shutdown_timeout: float = Field(default=5.0, gt=0, allow_inf_nan=False)
+
+    # ---- WS 入口（Epic 56 D1：与 HTTP 完全分离的独立 server，唯一宿主所有 WS 能力） ----
+    # 定位与 HTTP 入口同档：**实验性、无认证、无 TLS**（本机模式）；默认只绑 loopback。
+    # 回环绑定 = 本地模式（Origin 防线）；非回环 = 对外模式（56-2 落地认证 fail-closed）。
+    ws_host: str = Field(default="127.0.0.1", min_length=1)
+    # 默认 9001（8766 → 9001 是 Epic 56 的唯一 breaking change：两条 WS 端点路径不变、换端口）。
+    ws_port: int = Field(default=9001, ge=1, le=65535)
+    # WS 连接额度（迁移自 `http_ws_max_connections`）：既是每个 run 的订阅额度，也是 CLI 旁路
+    # hub 的连接总额。WS 不经 Uvicorn limit_concurrency，超额在 ASGI 层原子检查+登记。
+    ws_max_connections: int = Field(default=16, ge=1)
+    # WS server 关闭排空的等待上限（秒）：关既有连接 → 停 listener 全程有界。
+    ws_shutdown_timeout: float = Field(default=5.0, gt=0, allow_inf_nan=False)
+    # CLI 旁路订阅（Epic 55，Epic 56 D7 起宿主 = WS server）：给 `WS /api/cli/ws` 开一条只读
+    # 事件流，把**终端里那一轮** run 的事件实时推给外部客户端。**默认关**——它与 HTTP 入口同档
+    # 无认证、无 TLS，开了等于让能连上该端口的本机进程看到终端 agent 的工具输出（可能含文件内容）；
+    # 旁路不占运行名额、不写会话历史、不提供取消通道（终端独占 Ctrl+C / 双击 Esc）。
+    ws_cli_bypass_enabled: bool = False
     # ---- 网页控制台的配置写入通道（Epic 50 Story 50-5） ----
     # **默认关**（I12）：关闭时配置面全只读，且**网页无法通过任何请求打开它**——它不在白名单里
     # （配置目录把它列进「控制台自身」排除组），写入通道因此改不到自己。
diff --git a/src/heagent/config/catalog.py b/src/heagent/config/catalog.py
index 753f51f..492d30c 100644
--- a/src/heagent/config/catalog.py
+++ b/src/heagent/config/catalog.py
@@ -385,7 +385,8 @@ EXCLUSION_GROUPS: tuple[ConfigGroupSpec, ...] = (
     ConfigGroupSpec(
         id="listening",
         label="监听面",
-        patterns=("HTTP_*",),
+        # Epic 56 D1：WS server 独立成 WS_* 配置面，与 HTTP_* 同属「监听面」。
+        patterns=("HTTP_*", "WS_*"),
         reason="listening_surface",
     ),
     ConfigGroupSpec(
diff --git a/src/heagent/network/cli_event_hub.py b/src/heagent/network/cli_event_hub.py
index aa6c3a7..8d0241e 100644
--- a/src/heagent/network/cli_event_hub.py
+++ b/src/heagent/network/cli_event_hub.py
@@ -64,7 +64,7 @@ class CliEventHub:
     """CLI 旁路事件的唯一状态源（seq / 缓冲 / 订阅者 / 关停）。
 
     ``max_connections`` 是**整个旁路流**的连接上限（不是每 run）：旁路只有一条流，与
-    ``/api/runs/{id}/ws`` 的「每 run 一份额度」是不同口径，故从 ``HTTP_WS_MAX_CONNECTIONS``
+    ``/api/runs/{id}/ws`` 的「每 run 一份额度」是不同口径，故从 ``WS_MAX_CONNECTIONS``
     取值但语义按 hub 计。
     """
 
diff --git a/src/heagent/network/http_server.py b/src/heagent/network/http_server.py
index 095a74b..4fb1586 100644
--- a/src/heagent/network/http_server.py
+++ b/src/heagent/network/http_server.py
@@ -66,10 +66,11 @@ from heagent.network.http_protocol import (
     error_envelope,
     sanitize_message,
 )
-from heagent.network.ws_protocol import (
-    WS_MAX_FRAME_BYTES,
-    WS_PING_INTERVAL_SECONDS,
-    WS_PING_TIMEOUT_SECONDS,
+from heagent.network.origin import (
+    allowed_hosts,
+    allowed_ports,
+    probe_host,
+    request_origin_violation,
 )
 from heagent.pub.safe_logging import safe_log
 
@@ -78,7 +79,6 @@ if TYPE_CHECKING:
 
     from starlette.types import ASGIApp, Receive, Scope, Send
 
-    from heagent.network.cli_event_hub import CliEventHub
     from heagent.network.http_console_protocol import ConsoleHandler
 
     # 入口层交回的可调用对象：把 prompt 跑成 Agent 运行，并通过 publisher 推事件。
@@ -128,8 +128,6 @@ _RUNS_PATH = "/api/runs"
 _RUN_DETAIL_PATH = "/api/runs/{run_id}"
 _RUN_EVENTS_PATH = "/api/runs/{run_id}/events"
 _SESSION_PATH = "/api/session"
-# CLI 旁路订阅（Epic 55）：跨轮次的只读事件流，见 ``network/cli_event_hub.py``。
-_CLI_WS_PATH = "/api/cli/ws"
 _PROJECTS_PATH = "/api/projects"
 _PROJECT_PATH = "/api/projects/{project_id}"
 _PROJECT_SESSIONS_PATH = "/api/projects/{project_id}/sessions"
@@ -142,10 +140,6 @@ _PROJECT_CONFIG_PATH = "/api/projects/{project_id}/config"
 # 非项目作用域的控制台端点（Story 50-8）：在**服务端所在机器**弹原生目录选择窗口。
 _DIALOG_PICK_PATH = "/api/dialogs/pick-directory"
 
-# 通配绑定地址：就绪探测改走回环（见 :func:`_probe_host`）。这里**只识别**，不在此绑定。
-_WILDCARD_HOSTS = frozenset({"", "0.0.0.0", "*"})  # nosec B104 - 仅识别通配地址，本模块不在此绑定 # noqa: S104
-_IPV6_WILDCARDS = frozenset({"::", "[::]"})
-
 # 就绪探测与关闭排空的预算（秒）。探测是进程内回环请求，正常在毫秒级返回。
 _PROBE_TIMEOUT = 5.0
 _SHUTDOWN_GRACE_MARGIN = 1.0
@@ -196,8 +190,6 @@ class HttpServerConfig(BaseModel):
     # 拆出的理由：连接额度由 Uvicorn 在**进 ASGI 之前**拒绝 ⇒ 超额订阅拿不到错误信封 / 安全头 / 访问日志，
     # 429 ``rate_limited`` 分支实际不可达；订阅面现在有独立旋钮，调大连接额度不再被迫放大它。
     max_subscribers: int = Field(default=16, ge=1)
-    # 每个 run 的 WS 连接独立额度；WS 不受 Uvicorn limit_concurrency 管理，也不占 SSE 订阅额度。
-    ws_max_connections: int = Field(default=16, ge=1)
     # **每个项目各自**的在途运行上限（Story 50-3 的 D9）：全局上限 = 项目数 × 该值，因此「A 项目在跑」
     # 不挡 B 项目；``POST /api/runs``（无项目归属）自己算一档，语义与 Epic 49 逐字相同。
     max_inflight_runs: int = Field(default=1, ge=1)
@@ -992,122 +984,6 @@ class HttpRunService:
 
 # ── 同源防线与请求观测（Story 49-5） ──
 
-# 我们不信任任何代理头：反向代理部署不在 MVP 支持范围（AD-6），出现这些头即拒绝请求——
-# 否则 `X-Forwarded-Host` 就能把「跨站请求」伪装成本机同源请求（DNS rebinding 的常见变体）。
-_UNTRUSTED_FORWARD_HEADERS = frozenset(
-    {b"forwarded", b"x-forwarded-for", b"x-forwarded-host", b"x-forwarded-proto", b"x-real-ip"}
-)
-
-# 回环绑定时接受的等价本机写法：三者指向同一个 listener（浏览器地址栏习惯不同），拒绝其中
-# 任何一个都会让「本机自用」这个主用例失效。**非回环绑定只用配置的那个名字**（不额外放宽）。
-_LOOPBACK_HOST_ALIASES = ("127.0.0.1", "localhost", "[::1]")
-
-
-def _canonical_authority(value: str) -> str | None:
-    """规范化 ``Host`` 的 authority：小写、省略 http 默认端口 80。
-
-    返回 ``None`` 表示格式不可信（含路径/查询、非数字端口、越界端口、空值）——调用方按拒绝处理。
-    IPv6 字面量写成 ``[::1]:8766``（方括号是 authority 的一部分）。
-    """
-    text = value.strip().lower()
-    if not text or "/" in text or "?" in text:
-        return None
-    if text.startswith("["):
-        end = text.find("]")
-        if end < 0:
-            return None
-        host = text[: end + 1]
-        rest = text[end + 1 :]
-        port = rest[1:] if rest.startswith(":") else ""
-    elif ":" in text:
-        host, _, port = text.rpartition(":")
-    else:
-        host, port = text, ""
-    if port and (not port.isdigit() or int(port) > 65535):
-        return None
-    effective = int(port) if port else 80
-    return host if effective == 80 else f"{host}:{effective}"
-
-
-def _allowed_hosts(config: HttpServerConfig) -> frozenset[str]:
-    """允许的 host 名集合：配置 host + （**仅当它是回环时**）等价本机写法。
-
-    这是「请求必须打在本 listener 上」的判据，用于挡住 Host 伪装（例如把 ``evil.example`` 解析到
-    127.0.0.1 的 DNS rebinding）。**不是认证**：能连上端口的本机进程可以随便伪造 Host。
-    """
-    host = config.host.strip().lower()
-    names = {host}
-    # 通配绑定（``0.0.0.0`` / ``::`` / ``*``）没有单一主机名：就绪探测与浏览器都是从回环地址
-    # 打进这个 listener 的（见 :func:`_probe_host`），因此把等价本机写法一并接受——否则探测会
-    # 撞上自己的 Host 校验（403），``HTTP_HOST=0.0.0.0`` 永远起不来。
-    # 这不削弱反 DNS-rebinding：伪造的域名（``evil.example``）仍在拒绝之列；通配绑定的其它网卡
-    # 地址也仍按「不匹配 listener 名」拒绝（非回环联网不受支持，见 CLI help 与 exposure 告警）。
-    if is_loopback_host(host) or host in _WILDCARD_HOSTS or host in _IPV6_WILDCARDS:
-        names.update(_LOOPBACK_HOST_ALIASES)
-    return frozenset(names)
-
-
-def _allowed_ports(config: HttpServerConfig) -> frozenset[int] | None:
-    """允许的端口集合；``None`` 表示「任意端口」。
-
-    ``port=0``（操作系统分配随机端口，只用于程序化/测试）时构建 app 还不知道实际端口，故不限制
-    端口；CLI 与 ``HTTP_PORT`` 都限定 1..65535，生产路径永远有确定的端口。
-    """
-    return None if config.port == 0 else frozenset({config.port})
-
-
-def _split_authority(authority: str) -> tuple[str, int]:
-    """把规范化后的 authority 拆成 ``(host, port)``；无端口视为 http 默认端口 80。"""
-    if authority.startswith("["):
-        end = authority.find("]")
-        host = authority[: end + 1]
-        rest = authority[end + 1 :]
-        return host, int(rest[1:]) if rest.startswith(":") else 80
-    host, sep, port = authority.rpartition(":")
-    if not sep:
-        return authority, 80
-    return host, int(port)
-
-
-def _request_origin_violation(
-    scope: MutableMapping[str, Any],
-    *,
-    hosts: frozenset[str],
-    ports: frozenset[int] | None,
-) -> str | None:
-    """请求是否违反同源防线；返回违规原因（供日志），``None`` 表示通过。
-
-    规则（AD-6）：
-
-    1. 出现任何 forwarded-* 头 ⇒ 拒绝（见 :data:`_UNTRUSTED_FORWARD_HEADERS`）；
-    2. ``Host`` 必须恰好一个、且规范化后的 host/port 都在允许集合内；
-    3. 若带 ``Origin``：不得为 ``null``/空，且必须等于 ``http://`` 加该 authority（同源）。
-       **缺少 Origin** 只表示「非浏览器客户端」（curl / 脚本），Host 已校验故放行。
-    """
-    headers = scope.get("headers") or []
-    if any(name.lower() in _UNTRUSTED_FORWARD_HEADERS for name, _value in headers):
-        return "untrusted forwarded header"
-    host_headers = [value.decode("latin-1") for name, value in headers if name.lower() == b"host"]
-    if len(host_headers) != 1:
-        return "missing or duplicated Host header"
-    authority = _canonical_authority(host_headers[0])
-    if authority is None:
-        return "malformed Host header"
-    host, port = _split_authority(authority)
-    if host not in hosts:
-        return "host not allowed"
-    if ports is not None and port not in ports:
-        return "port not allowed"
-    for name, value in headers:
-        if name.lower() != b"origin":
-            continue
-        origin = value.decode("latin-1").strip().lower()
-        if not origin or origin == "null":
-            return "null Origin"
-        if origin != f"http://{authority}":
-            return "origin mismatch"
-    return None
-
 
 async def _send_json(
     send: Send, status_code: int, payload: dict[str, Any], *, extra: tuple[tuple[bytes, bytes], ...] = ()
@@ -1140,7 +1016,7 @@ class _OriginGuardMiddleware:
         if scope.get("type") != "http":
             await self.app(scope, receive, send)
             return
-        violation = _request_origin_violation(scope, hosts=self.hosts, ports=self.ports)
+        violation = request_origin_violation(scope, hosts=self.hosts, ports=self.ports)
         if violation is None:
             await self.app(scope, receive, send)
             return
@@ -1756,7 +1632,6 @@ def build_http_app(
     version: str,
     run_service: HttpRunService | None = None,
     console: ConsoleHandler | None = None,
-    cli_hub: CliEventHub | None = None,
 ) -> ASGIApp:
     """构造网页入口的 ASGI 应用（健康检查 + 运行 API/SSE + 包内静态页 + 安全头）。
 
@@ -1764,10 +1639,7 @@ def build_http_app(
     也不需要在导入期触碰包元数据。``run_service`` 是**注入的运行服务**（AD-1 的接缝）——为 ``None``
     时不注册 ``/api/runs*``、``/api/session`` 或 ``/api/projects*``（那些路径回 404），Story 49-1 的用法因此保持不变。
     错误响应一律走 :func:`_json_error`，异常细节只进服务端日志。
-
-    ``cli_hub`` 是**CLI 终端运行的旁路中枢**（Epic 55）：为 ``None`` 时不注册 ``/api/cli/ws``
-    （该路径回 404）。它与 ``run_service`` 互相独立——旁路不拥有运行，也不该因为「网页侧有 run
-    服务」或「没有」而存在或消失。
+    Epic 56 D1：WS 路由已全部迁出本 app（宿主 = ``network/ws_host.py``），本 app 只剩纯 HTTP+SSE。
     """
     applications = _require_module("starlette.applications")
     responses = _require_module("starlette.responses")
@@ -1829,38 +1701,15 @@ def build_http_app(
         routing.Route("/", endpoint=index, methods=["GET"]),
     ]
     if run_service is not None:
-        from heagent.network.ws_server import build_ws_endpoint
-
-        ws_endpoint = build_ws_endpoint(
-            run_service,
-            origin_violation=lambda scope: _request_origin_violation(
-                scope,
-                hosts=_allowed_hosts(config),
-                ports=_allowed_ports(config),
-            ),
-        )
         create_run, run_events, cancel_run, session_endpoint = _build_run_endpoints(responses, config, run_service)
         routes.extend(
             [
-                routing.WebSocketRoute("/api/runs/{run_id}/ws", endpoint=ws_endpoint),
                 routing.Route(_RUNS_PATH, endpoint=create_run, methods=["POST"]),
                 routing.Route(_RUN_EVENTS_PATH, endpoint=run_events, methods=["GET"]),
                 routing.Route(_RUN_DETAIL_PATH, endpoint=cancel_run, methods=["DELETE"]),
                 routing.Route(_SESSION_PATH, endpoint=session_endpoint, methods=["GET"]),
             ]
         )
-    if cli_hub is not None:
-        from heagent.network.ws_server import build_cli_ws_endpoint
-
-        cli_ws_endpoint = build_cli_ws_endpoint(
-            cli_hub,
-            origin_violation=lambda scope: _request_origin_violation(
-                scope,
-                hosts=_allowed_hosts(config),
-                ports=_allowed_ports(config),
-            ),
-        )
-        routes.append(routing.WebSocketRoute(_CLI_WS_PATH, endpoint=cli_ws_endpoint))
     if console is not None:
         list_projects, register_project, rename_project, remove_project = _build_project_endpoints(
             responses, console, config
@@ -1910,25 +1759,11 @@ def build_http_app(
         },
     )
     # 包装顺序（由外到内）：安全头（保证连被拒的响应也带）→ 请求观测 → 同源防线 → 应用路由。
-    guarded = _OriginGuardMiddleware(app, hosts=_allowed_hosts(config), ports=_allowed_ports(config))
+    guarded = _OriginGuardMiddleware(app, hosts=allowed_hosts(config), ports=allowed_ports(config))
     logged = _AccessLogMiddleware(guarded)
     return _SecurityHeadersMiddleware(logged, _SECURITY_HEADERS)
 
 
-def _probe_host(host: str) -> str:
-    """就绪探测用的连接地址：通配绑定（``0.0.0.0`` / ``::`` / 空串）改用回环地址。
-
-    连 ``0.0.0.0`` 在多数平台上是未定义/失败行为，而「通配绑定是否真的能服务」完全可以经
-    回环地址验证（通配包含回环）。
-    """
-    candidate = host.strip()
-    if candidate in _IPV6_WILDCARDS:
-        return "::1"
-    if candidate in _WILDCARD_HOSTS:
-        return "127.0.0.1"
-    return candidate
-
-
 class HttpServer:
     """一个 HTTP listener 的所有者：绑定、服务、有界关闭。
 
@@ -1942,13 +1777,11 @@ class HttpServer:
         version: str,
         run_service: HttpRunService | None = None,
         console: ConsoleHandler | None = None,
-        cli_hub: CliEventHub | None = None,
     ) -> None:
         self.config = config
         self.version = version
         self.run_service = run_service
         self.console = console
-        self.cli_hub = cli_hub
         self._app: ASGIApp | None = None
         self._server: Any = None
         # 生命周期锁与「已关闭」标记：``close()`` 必须**等到**收尾真正完成才返回。只用一个布尔
@@ -1956,7 +1789,6 @@ class HttpServer:
         # （生命周期锁 + 布尔标记是本项目入口服务的既有形态）。
         self._lifecycle_lock = asyncio.Lock()
         self._closed = False
-        self._ws_unavailable_logged = False
 
     @property
     def app(self) -> ASGIApp:
@@ -1967,7 +1799,6 @@ class HttpServer:
                 version=self.version,
                 run_service=self.run_service,
                 console=self.console,
-                cli_hub=self.cli_hub,
             )
         return self._app
 
@@ -2013,9 +1844,6 @@ class HttpServer:
                 # 绝不信任 forwarded-* 头（AD-6）：同源判定必须基于真实 listener 地址。
                 proxy_headers=False,
                 limit_concurrency=self.config.max_connections + _CONCURRENCY_PROBE_RESERVE,
-                ws_max_size=WS_MAX_FRAME_BYTES,
-                ws_ping_interval=WS_PING_INTERVAL_SECONDS,
-                ws_ping_timeout=WS_PING_TIMEOUT_SECONDS,
                 # 关闭时连接排空的硬上界（Uvicorn 默认 None = 无限等待）。
                 timeout_graceful_shutdown=max(1, math.ceil(self.config.shutdown_timeout)),
             )
@@ -2034,14 +1862,6 @@ class HttpServer:
         except OSError as exc:
             raise HttpStartupError(f"HTTP server could not bind {self.address}: {exc}") from exc
         self._server = server
-        ws_protocol_class = getattr(server.config, "ws_protocol_class", None)
-        if ws_protocol_class is None and not self._ws_unavailable_logged:
-            self._ws_unavailable_logged = True
-            _safe_log(
-                logging.WARNING,
-                "http event=ws_unavailable install_hint=%s",
-                "pip install 'heagent[http]' (WebSocket support requires websockets)",
-            )
         _safe_log(logging.INFO, "http event=started address=%s", self.address)
         warning = exposure_warning(self.config.host)
         if warning is not None:
@@ -2057,10 +1877,6 @@ class HttpServer:
             # 409 ``run_conflict``（`server is shutting down`）拒绝——正是 AD-5 要消除的
             # 「看起来正常但不可用」。
             self.run_service.reopen()
-        if self.cli_hub is not None:
-            # 同一条理由：``close()`` 置上的「停止接收」标记不可逆，重新 ``start()`` 后
-            # 新连接会被一律回 ``shutting_down``——那正是 AD-5 禁止的「看着在运行、其实不可用」。
-            self.cli_hub.reopen()
 
     async def serve_forever(self) -> None:
         """阻塞式服务循环；Uvicorn 主循环退出（``should_exit``）或异常时返回/抛出。"""
@@ -2086,12 +1902,9 @@ class HttpServer:
                 return
             service = self.run_service
             if service is not None:
+                # Epic 56 D1：WS 连接的收尾（close_websockets / cli_hub）随拆分归 WS server 所有；
+                # 本方法只排空运行到终态并停 HTTP listener（SSE 订阅随之终结）。
                 await service.close()
-                await service.close_websockets()
-            if self.cli_hub is not None:
-                # 顺序同 run_service：先置「停止接收」（新连接立刻收 shutting_down），再关既有连接。
-                self.cli_hub.close()
-                await self.cli_hub.close_websockets(timeout=self.config.shutdown_timeout)
             server, self._server = self._server, None
             if server is None:
                 self._closed = True
@@ -2121,7 +1934,7 @@ class HttpServer:
         真的能服务」这件事用一次手写 `GET` 就能验证——返回 200 即通过，其余（连接失败、超时、
         5xx、畸形响应行）一律视为未就绪。
         """
-        host = _probe_host(self.config.host)
+        host = probe_host(self.config.host)
         port = self.port
         started_at = time.perf_counter()
         try:
diff --git a/src/heagent/network/origin.py b/src/heagent/network/origin.py
new file mode 100644
index 0000000..00c9fc0
--- /dev/null
+++ b/src/heagent/network/origin.py
@@ -0,0 +1,165 @@
+"""入口 listener 的同源防线（AD-6）与探测地址推导——HTTP 与 WS 两个 server 共用的单源。
+
+Epic 56 D1（HTTP/WS 完全分离）时自 ``http_server.py`` 纯搬移：两条 listener 的同源规则
+**必须同源演进**，两处各写一套迟早漂移（``exposure.py`` 的既有立场）。这里的判定被两个
+server 逐字共用；哪一 side 要收紧规则，改这一处即可。
+"""
+
+from __future__ import annotations
+
+from typing import TYPE_CHECKING, Any, Protocol
+
+if TYPE_CHECKING:
+    from collections.abc import MutableMapping
+
+from heagent.network.exposure import is_loopback_host
+
+# 我们不信任任何代理头：反向代理部署不在 MVP 支持范围（AD-6），出现这些头即拒绝请求——
+# 否则 `X-Forwarded-Host` 就能把「跨站请求」伪装成本机同源请求（DNS rebinding 的常见变体）。
+_UNTRUSTED_FORWARD_HEADERS = frozenset(
+    {b"forwarded", b"x-forwarded-for", b"x-forwarded-host", b"x-forwarded-proto", b"x-real-ip"}
+)
+
+# 回环绑定时接受的等价本机写法：三者指向同一个 listener（浏览器地址栏习惯不同），拒绝其中
+# 任何一个都会让「本机自用」这个主用例失效。**非回环绑定只用配置的那个名字**（不额外放宽）。
+_LOOPBACK_HOST_ALIASES = ("127.0.0.1", "localhost", "[::1]")
+
+# 通配绑定地址：就绪探测改走回环（见 :func:`probe_host`）。这里**只识别**，不在此绑定。
+_WILDCARD_HOSTS = frozenset({"", "0.0.0.0", "*"})  # nosec B104 - 仅识别通配地址，本模块不在此绑定 # noqa: S104
+_IPV6_WILDCARDS = frozenset({"::", "[::]"})
+
+
+class ListenerConfig(Protocol):
+    """两条 listener 配置的最小结构面（``HttpServerConfig`` / ``WsServerConfig`` 均满足）。"""
+
+    host: str
+    port: int
+
+
+def canonical_authority(value: str) -> str | None:
+    """规范化 ``Host`` 的 authority：小写、省略 http 默认端口 80。
+
+    返回 ``None`` 表示格式不可信（含路径/查询、非数字端口、越界端口、空值）——调用方按拒绝处理。
+    IPv6 字面量写成 ``[::1]:8766``（方括号是 authority 的一部分）。
+    """
+    text = value.strip().lower()
+    if not text or "/" in text or "?" in text:
+        return None
+    if text.startswith("["):
+        end = text.find("]")
+        if end < 0:
+            return None
+        host = text[: end + 1]
+        rest = text[end + 1 :]
+        port = rest[1:] if rest.startswith(":") else ""
+    elif ":" in text:
+        host, _, port = text.rpartition(":")
+    else:
+        host, port = text, ""
+    if port and (not port.isdigit() or int(port) > 65535):
+        return None
+    effective = int(port) if port else 80
+    return host if effective == 80 else f"{host}:{effective}"
+
+
+def split_authority(authority: str) -> tuple[str, int]:
+    """把规范化后的 authority 拆成 ``(host, port)``；无端口视为 http 默认端口 80。"""
+    if authority.startswith("["):
+        end = authority.find("]")
+        host = authority[: end + 1]
+        rest = authority[end + 1 :]
+        return host, int(rest[1:]) if rest.startswith(":") else 80
+    host, sep, port = authority.rpartition(":")
+    if not sep:
+        return authority, 80
+    return host, int(port)
+
+
+def allowed_hosts(config: ListenerConfig) -> frozenset[str]:
+    """允许的 host 名集合：配置 host + （**仅当它是回环时**）等价本机写法。
+
+    这是「请求必须打在本 listener 上」的判据，用于挡住 Host 伪装（例如把 ``evil.example`` 解析到
+    127.0.0.1 的 DNS rebinding）。**不是认证**：能连上端口的本机进程可以随便伪造 Host。
+    """
+    host = config.host.strip().lower()
+    names = {host}
+    # 通配绑定（``0.0.0.0`` / ``::`` / ``*``）没有单一主机名：就绪探测与浏览器都是从回环地址
+    # 打进这个 listener 的（见 :func:`probe_host`），因此把等价本机写法一并接受——否则探测会
+    # 撞上自己的 Host 校验（403），``HTTP_HOST=0.0.0.0`` 永远起不来。
+    # 这不削弱反 DNS-rebinding：伪造的域名（``evil.example``）仍在拒绝之列；通配绑定的其它网卡
+    # 地址也仍按「不匹配 listener 名」拒绝（非回环联网不受支持，见 CLI help 与 exposure 告警）。
+    if is_loopback_host(host) or host in _WILDCARD_HOSTS or host in _IPV6_WILDCARDS:
+        names.update(_LOOPBACK_HOST_ALIASES)
+    return frozenset(names)
+
+
+def allowed_ports(config: ListenerConfig) -> frozenset[int] | None:
+    """允许的端口集合；``None`` 表示「任意端口」。
+
+    ``port=0``（操作系统分配随机端口，只用于程序化/测试）时构建 app 还不知道实际端口，故不限制
+    端口；CLI 与 ``WS_PORT``/``HTTP_PORT`` 都限定 1..65535，生产路径永远有确定的端口。
+    """
+    return None if config.port == 0 else frozenset({config.port})
+
+
+def request_origin_violation(
+    scope: MutableMapping[str, Any],
+    *,
+    hosts: frozenset[str],
+    ports: frozenset[int] | None,
+) -> str | None:
+    """请求是否违反同源防线；返回违规原因（供日志），``None`` 表示通过。
+
+    规则（AD-6）：
+
+    1. 出现任何 forwarded-* 头 ⇒ 检出即拒（见 :data:`_UNTRUSTED_FORWARD_HEADERS`）；
+    2. ``Host`` 必须恰好一个、且规范化后的 host/port 都在允许集合内；
+    3. 若带 ``Origin``：不得为 ``null``/空，且必须等于 ``http://`` 加该 authority（同源）。
+       **缺少 Origin** 只表示「非浏览器客户端」（curl / 脚本），Host 已校验故放行。
+    """
+    headers = scope.get("headers") or []
+    if any(name.lower() in _UNTRUSTED_FORWARD_HEADERS for name, _value in headers):
+        return "untrusted forwarded header"
+    host_headers = [value.decode("latin-1") for name, value in headers if name.lower() == b"host"]
+    if len(host_headers) != 1:
+        return "missing or duplicated Host header"
+    authority = canonical_authority(host_headers[0])
+    if authority is None:
+        return "malformed Host header"
+    host, port = split_authority(authority)
+    if host not in hosts:
+        return "host not allowed"
+    if ports is not None and port not in ports:
+        return "port not allowed"
+    for name, value in headers:
+        if name.lower() != b"origin":
+            continue
+        origin = value.decode("latin-1").strip().lower()
+        if not origin or origin == "null":
+            return "null Origin"
+        if origin != f"http://{authority}":
+            return "origin mismatch"
+    return None
+
+
+def probe_host(host: str) -> str:
+    """就绪探测用的连接地址：通配绑定（``0.0.0.0`` / ``::`` / 空串）改用回环地址。
+
+    连 ``0.0.0.0`` 在多数平台上是未定义/失败行为，而「通配绑定是否真的能服务」完全可以经
+    回环地址验证（通配包含回环）。
+    """
+    candidate = host.strip()
+    if candidate in _IPV6_WILDCARDS:
+        return "::1"
+    if candidate in _WILDCARD_HOSTS:
+        return "127.0.0.1"
+    return candidate
+
+
+__all__ = [
+    "ListenerConfig",
+    "allowed_hosts",
+    "allowed_ports",
+    "probe_host",
+    "request_origin_violation",
+]
diff --git a/src/heagent/network/ws_host.py b/src/heagent/network/ws_host.py
new file mode 100644
index 0000000..2fc9081
--- /dev/null
+++ b/src/heagent/network/ws_host.py
@@ -0,0 +1,308 @@
+"""WS server 宿主（Epic 56 D1）：所有 WS 能力的唯一宿主——独立 ASGI app、独立配置、独立监听器。
+
+与 HTTP server（``http_server.py``）**完全分离**：本 app 零 HTTP 路由（控制台页 / 静态资源 /
+REST / 健康检查一律 404），HTTP app 亦不再挂任何 WS 路由。两条既有 WS 端点（run 订阅
+``/api/runs/{run_id}/ws`` 与 CLI 旁路 ``/api/cli/ws``）自 HTTP app 迁入：路径不变、端口迁移
+（8766 → 9001，唯一 breaking change）。端点逻辑复用 ``ws_server.py`` 不重写，本模块只负责
+装配、监听器生命周期与 uvicorn WS 参数。
+
+9001 没有健康端点可打，就绪判据改为**真实 TCP 连通**（D1 接缝事实：共享的只有注入的进程内
+状态 ``HttpRunService`` / ``CliEventHub`` 与 ``network/`` 同层协议模型）。本机模式语义
+（Origin 防线、无认证）与 ``exposure`` 告警逐字沿用；认证与 TLS 是 56-2 的范围。
+"""
+
+from __future__ import annotations
+
+import asyncio
+import contextlib
+import logging
+import math
+from typing import TYPE_CHECKING, Any
+
+from pydantic import BaseModel, ConfigDict, Field
+
+from heagent.network.http_server import _require_module
+from heagent.network.origin import (
+    allowed_hosts,
+    allowed_ports,
+    probe_host,
+    request_origin_violation,
+)
+from heagent.network.ws_protocol import (
+    WS_MAX_FRAME_BYTES,
+    WS_PING_INTERVAL_SECONDS,
+    WS_PING_TIMEOUT_SECONDS,
+)
+from heagent.pub.safe_logging import safe_log
+
+if TYPE_CHECKING:
+    from starlette.types import ASGIApp
+
+
+logger = logging.getLogger(__name__)
+
+# 两条 WS 路径（公开常量：入口层公告与测试共用同一字面量，别处各写一份迟早漂移）。
+RUNS_WS_PATH = "/api/runs/{run_id}/ws"
+CLI_WS_PATH = "/api/cli/ws"
+
+# 就绪探测与关闭排空的预算（秒）。探测是进程内回环 TCP 连接，正常毫秒级返回。
+_PROBE_TIMEOUT = 5.0
+_SHUTDOWN_GRACE_MARGIN = 1.0
+
+
+def _safe_log(level: int, message: str, *args: object, exc_info: bool = False) -> None:
+    """记一条日志，绝不让观测故障影响协议行为（网络传输层的既有立场）。"""
+    safe_log(logger, level, message, *args, exc_info=exc_info)
+
+
+class WsStartupError(RuntimeError):
+    """WS server 未能绑定或未通过就绪探测。"""
+
+
+class WsServerConfig(BaseModel):
+    """单个 WS server 实例的有界配置（默认值与 ``WS_*`` 设置一致，Epic 56 D1）。
+
+    ``port=0`` 允许（操作系统分配随机端口，仅程序化/测试用法）——CLI 与设置层限定 1..65535。
+    超时禁 ``inf``/``nan``：``Inf`` 会让「有界关闭」静默变成无界等待（同 ``HttpServerConfig`` 口径）。
+    """
+
+    model_config = ConfigDict(frozen=True)
+
+    host: str = Field(default="127.0.0.1", min_length=1)
+    port: int = Field(default=9001, ge=0, le=65535)
+    # WS 连接额度（迁移自 HttpServerConfig.ws_max_connections）：既是每个 run 的订阅额度
+    # （run 端点经 max_connections 参数注入），也是 CLI 旁路 hub 的连接总额。
+    ws_max_connections: int = Field(default=16, ge=1)
+    shutdown_timeout: float = Field(default=5.0, gt=0, allow_inf_nan=False)
+
+
+def build_ws_app(
+    config: WsServerConfig,
+    *,
+    run_service: Any | None = None,
+    cli_hub: Any | None = None,
+) -> ASGIApp:
+    """构造 WS server 的 ASGI 应用：只挂两条 WebSocketRoute，零 HTTP 路由（D1/D2）。
+
+    ``run_service`` / ``cli_hub`` 是注入的进程内状态（D1 接缝事实）：为 None 时对应端点
+    不注册（升级直接被 Starlette 拒掉）。同源防线经 ``origin_violation`` 回调注入端点——两条
+    端点在 accept 前执行校验（http_server 时代的同一口径）；访问日志由端点自身的结构化
+    ``ws_open``/``ws_close`` 事件承担，无需 ASGI 中间件。
+    """
+    applications = _require_module("starlette.applications")
+    routing = _require_module("starlette.routing")
+
+    def _origin_violation(scope: Any) -> str | None:
+        return request_origin_violation(
+            scope,
+            hosts=allowed_hosts(config),
+            ports=allowed_ports(config),
+        )
+
+    routes: list[Any] = []
+    if run_service is not None:
+        from heagent.network.ws_server import build_ws_endpoint
+
+        routes.append(
+            routing.WebSocketRoute(
+                RUNS_WS_PATH,
+                endpoint=build_ws_endpoint(
+                    run_service,
+                    origin_violation=_origin_violation,
+                    max_connections=config.ws_max_connections,
+                ),
+            )
+        )
+    if cli_hub is not None:
+        from heagent.network.ws_server import build_cli_ws_endpoint
+
+        routes.append(
+            routing.WebSocketRoute(
+                CLI_WS_PATH,
+                endpoint=build_cli_ws_endpoint(cli_hub, origin_violation=_origin_violation),
+            )
+        )
+    # Starlette() 无类型标注，直返会触发 no-any-return；经类型化局部变量收敛。
+    app: ASGIApp = applications.Starlette(routes=routes)
+    return app
+
+
+class WsServer:
+    """一个 WS listener 的所有者：绑定、服务、有界关闭（三件套口径对齐 HttpServer）。"""
+
+    def __init__(
+        self,
+        config: WsServerConfig,
+        *,
+        run_service: Any | None = None,
+        cli_hub: Any | None = None,
+    ) -> None:
+        self.config = config
+        self.run_service = run_service
+        self.cli_hub = cli_hub
+        self._app: ASGIApp | None = None
+        self._server: Any = None
+        # 生命周期锁 + 布尔标记：close() 等同一次收尾完成（HttpServer 既有口径）。
+        self._lifecycle_lock = asyncio.Lock()
+        self._closed = False
+        self._ws_unavailable_logged = False
+
+    @property
+    def app(self) -> ASGIApp:
+        """ASGI 应用（延迟构造一次；测试可用 ASGI transport 直接打，无需真实 listener）。"""
+        if self._app is None:
+            self._app = build_ws_app(
+                self.config,
+                run_service=self.run_service,
+                cli_hub=self.cli_hub,
+            )
+        return self._app
+
+    @property
+    def port(self) -> int:
+        """实际监听端口：port=0（随机端口）时只有绑定后才能读出来。"""
+        for listener in getattr(self._server, "servers", None) or ():
+            for sock in getattr(listener, "sockets", None) or ():
+                with contextlib.suppress(OSError):
+                    return int(sock.getsockname()[1])
+        return self.config.port
+
+    @property
+    def address(self) -> str:
+        """人类可读的监听地址（stderr 公告与诊断用）。"""
+        return f"{self.config.host}:{self.port}"
+
+    async def start(self) -> None:
+        """绑定并确认 listener 真的可连，否则抛 WsStartupError。
+
+        就绪判据是真实 TCP 连通（本 server 无 HTTP 健康端点可打，D1 接缝事实）。
+        Uvicorn 绑定失败走 sys.exit 而非 OSError（同 HttpServer.start 的注释），因此
+        同时接住 SystemExit 与 OSError 并统一转成可诊断错误。
+        """
+        if self._server is not None:
+            return
+        uvicorn = _require_module("uvicorn")
+        self._closed = False
+        server = uvicorn.Server(
+            uvicorn.Config(
+                self.app,
+                host=self.config.host,
+                port=self.config.port,
+                lifespan="on",
+                # 与 HttpServer 同口径：不动 dictConfig / 不要 access 行 / 不带 server 头 / 不信 forwarded-*。
+                log_config=None,
+                access_log=False,
+                server_header=False,
+                proxy_headers=False,
+                # WS 限额不经 limit_concurrency（Epic 54 口径）：额度在 ASGI 层原子检查+登记。
+                ws_max_size=WS_MAX_FRAME_BYTES,
+                ws_ping_interval=WS_PING_INTERVAL_SECONDS,
+                ws_ping_timeout=WS_PING_TIMEOUT_SECONDS,
+                timeout_graceful_shutdown=max(1, math.ceil(self.config.shutdown_timeout)),
+            )
+        )
+        try:
+            if not server.config.loaded:
+                server.config.load()
+            server.lifespan = server.config.lifespan_class(server.config)
+            await server.startup()
+        except SystemExit as exc:
+            raise WsStartupError(f"WS server could not bind {self.address}: address unavailable") from exc
+        except OSError as exc:
+            raise WsStartupError(f"WS server could not bind {self.address}: {exc}") from exc
+        self._server = server
+        self._log_ws_unavailable_once(server)
+        _safe_log(logging.INFO, "ws event=started address=%s", self.address)
+        from heagent.network.exposure import exposure_warning
+
+        warning = exposure_warning(self.config.host)
+        if warning is not None:
+            _safe_log(logging.WARNING, "ws event=exposed host=%s %s", self.config.host, warning)
+        if not await self._probe_ready():
+            # 绑定成功但 listener 不可连 ⇒ 回滚，绝不对外宣称「已启动」。
+            self._server = None
+            await self._stop_listener(server)
+            raise WsStartupError(f"WS server started but {self.address} is not servable")
+        if self.cli_hub is not None:
+            # close() 置上的「停止接收」标记不可逆：重新 start() 后必须重开，否则新连接一律收
+            # shutting_down——AD-5 禁止的「看着在运行、其实不可用」（同 HttpServer.start 口径）。
+            self.cli_hub.reopen()
+
+    async def serve_forever(self) -> None:
+        """阻塞式服务循环；Uvicorn 主循环退出（should_exit）或异常时返回/抛出。"""
+        server = self._server
+        if server is None:
+            raise RuntimeError("WS server is not started")
+        await server.main_loop()
+
+    async def close(self) -> None:
+        """停止接收、关闭既有 WS 连接与 CLI 旁路、停 listener；全程有界、幂等。
+
+        只做 WS 侧的收尾（D1 拆分）：在途运行的排空（service.close()）归 HTTP server 的
+        close() 所有——编排顺序由入口层保证 HTTP 先、WS 后，等运行到终态后才关残余连接。
+        单独调用本方法（无 HTTP server 的测试/装配形态）也安全：close_websockets 只注销
+        登记并关连接，不取消任何运行（断线不取消运行，既有立场）。
+        """
+        async with self._lifecycle_lock:
+            if self._closed:
+                return
+            if self.run_service is not None:
+                await self.run_service.close_websockets()
+            if self.cli_hub is not None:
+                # 先置「停止接收」（新连接立刻收 shutting_down），再关既有连接。
+                self.cli_hub.close()
+                await self.cli_hub.close_websockets(timeout=self.config.shutdown_timeout)
+            server, self._server = self._server, None
+            if server is None:
+                self._closed = True
+                return
+            server.should_exit = True
+            await self._stop_listener(server)
+            self._closed = True
+
+    async def _stop_listener(self, server: Any) -> None:
+        budget = self.config.shutdown_timeout + _SHUTDOWN_GRACE_MARGIN
+        try:
+            await asyncio.wait_for(server.shutdown(), timeout=budget)
+        except TimeoutError:
+            _safe_log(logging.WARNING, "ws event=shutdown_timeout phase=listener")
+            server.force_exit = True
+            with contextlib.suppress(Exception):
+                await asyncio.wait_for(server.shutdown(), timeout=budget)
+        except asyncio.CancelledError:
+            raise
+        except Exception:
+            _safe_log(logging.WARNING, "ws event=shutdown_failed", exc_info=True)
+
+    async def _probe_ready(self) -> bool:
+        """用真实 TCP 连接验证 listener 可连（本 server 无 HTTP 健康端点，D1 接缝事实）。"""
+        host = probe_host(self.config.host)
+        port = self.port
+        try:
+            _reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout=_PROBE_TIMEOUT)
+        except (OSError, TimeoutError) as exc:
+            _safe_log(logging.WARNING, "ws event=probe_failed phase=connect error=%r", exc)
+            return False
+        writer.close()
+        return True
+
+    def _log_ws_unavailable_once(self, server: Any) -> None:
+        """缺 websockets 时给安装诊断（非致命：HTTP 不受影响，见 spec I/O 矩阵）。"""
+        ws_protocol_class = getattr(server.config, "ws_protocol_class", None)
+        if ws_protocol_class is None and not self._ws_unavailable_logged:
+            self._ws_unavailable_logged = True
+            _safe_log(
+                logging.WARNING,
+                "ws event=ws_unavailable install_hint=%s",
+                "pip install 'heagent[http]' (WebSocket support requires websockets)",
+            )
+
+
+__all__ = [
+    "CLI_WS_PATH",
+    "RUNS_WS_PATH",
+    "WsServer",
+    "WsServerConfig",
+    "WsStartupError",
+    "build_ws_app",
+]
diff --git a/src/heagent/network/ws_server.py b/src/heagent/network/ws_server.py
index fa76c1a..2fd350b 100644
--- a/src/heagent/network/ws_server.py
+++ b/src/heagent/network/ws_server.py
@@ -53,9 +53,12 @@ OriginCheck = Callable[[dict[str, Any]], str | None]
 
 
 class RunWebSocketService(Protocol):
-    """ws_server 所需的最小运行服务端口。"""
+    """ws_server 所需的最小运行服务端口。
+
+    Epic 56 D1：WS 连接额度自 ``HttpServerConfig`` 迁入 ``WsServerConfig``，经
+    :func:`build_ws_endpoint` 的 ``max_connections`` 参数注入——端点因此不感知任何配置类。
+    """
 
-    config: Any
     _closing: bool
 
     def run(self, run_id: str) -> Any | None: ...
@@ -176,6 +179,7 @@ async def _prepare_subscription(
     websocket: WebSocketLike,
     service: RunWebSocketService,
     run_id: str,
+    max_connections: int,
 ) -> tuple[Any | None, int | None, asyncio.Queue[RunEventPayload | None] | None]:
     """验证运行与游标并原子登记独立 WS 配额。"""
     record = service.run(run_id)
@@ -195,7 +199,7 @@ async def _prepare_subscription(
         )
         return None, None, None
     queue: asyncio.Queue[RunEventPayload | None] = asyncio.Queue(maxsize=record.subscriber_queue_size)
-    if not record.try_add_ws_subscriber(queue, service.config.ws_max_connections):
+    if not record.try_add_ws_subscriber(queue, max_connections):
         await _send_error(
             websocket,
             HttpErrorCode.RATE_LIMITED,
@@ -210,8 +214,9 @@ def build_ws_endpoint(
     service: RunWebSocketService,
     *,
     origin_violation: OriginCheck,
+    max_connections: int,
 ) -> Callable[[WebSocketLike], Awaitable[None]]:
-    """构造单 run WebSocket endpoint；Origin 规则由 http_server 单点注入。"""
+    """构造单 run WebSocket endpoint；Origin 规则与连接额度由宿主（ws_host/http_server 时代为后者）单点注入。"""
 
     async def endpoint(websocket: WebSocketLike) -> None:
         started = time.perf_counter()
@@ -232,7 +237,7 @@ def build_ws_endpoint(
                     close_code=WS_CLOSE_GOING_AWAY,
                 )
                 return
-            record, cursor, queue = await _prepare_subscription(websocket, service, run_id)
+            record, cursor, queue = await _prepare_subscription(websocket, service, run_id, max_connections)
             if record is None or queue is None:
                 return
             service.register_ws(connection_id, run_id, websocket)
diff --git a/tests/network/test_http_cli_ws.py b/tests/network/test_cli_ws_e2e.py
similarity index 94%
rename from tests/network/test_http_cli_ws.py
rename to tests/network/test_cli_ws_e2e.py
index 39c2592..b9f3f71 100644
--- a/tests/network/test_http_cli_ws.py
+++ b/tests/network/test_cli_ws_e2e.py
@@ -1,7 +1,8 @@
 """CLI 旁路 WS 端点端到端契约（Epic 55）：真实 TCP + 真实 websockets 客户端。
 
-与 ``test_http_ws_e2e.py`` 同手法（``port=0`` + ``serve_forever`` + 真客户端），区别是被测端点
+与 ``test_ws_e2e.py`` 同手法（``port=0`` + ``serve_forever`` + 真客户端），区别是被测端点
 ``/api/cli/ws`` 订阅的是**终端自己那一轮** run（跨轮次、无 run 记录、无取消通道）。
+Epic 56 D1/D7：宿主自 HttpServer 迁至 WsServer（9001），本文件随之改驱动并更名。
 """
 
 from __future__ import annotations
@@ -14,17 +15,17 @@ import pytest
 
 from heagent.network.cli_event_hub import CliEventHub
 from heagent.network.http_protocol import HttpErrorCode
-from heagent.network.http_server import HttpServer, HttpServerConfig
+from heagent.network.ws_host import WsServer, WsServerConfig
 
 websockets = pytest.importorskip("websockets")
 
 
-def _server_config(**kwargs: Any) -> HttpServerConfig:
-    return HttpServerConfig(port=0, request_timeout=0, idle_timeout=0, tool_inflight_timeout=0, **kwargs)
+def _ws_config() -> WsServerConfig:
+    return WsServerConfig(port=0, shutdown_timeout=1)
 
 
-async def _start(hub: CliEventHub | None, **config_kwargs: Any) -> tuple[HttpServer, asyncio.Task[None]]:
-    server = HttpServer(_server_config(**config_kwargs), version="test", cli_hub=hub)
+async def _start(hub: CliEventHub | None) -> tuple[WsServer, asyncio.Task[None]]:
+    server = WsServer(_ws_config(), cli_hub=hub)
     await server.start()
     task = asyncio.create_task(server.serve_forever())
     # 让 serve 循环真正进入 ``main_loop`` 再返回：否则「建任务后立刻 close()」的用例里
@@ -33,7 +34,7 @@ async def _start(hub: CliEventHub | None, **config_kwargs: Any) -> tuple[HttpSer
     return server, task
 
 
-async def _stop(server: HttpServer, task: asyncio.Task[None]) -> None:
+async def _stop(server: WsServer, task: asyncio.Task[None]) -> None:
     await server.close()
     await asyncio.wait_for(task, timeout=5)
 
diff --git a/tests/network/test_http_server.py b/tests/network/test_http_server.py
index 197d555..80e9f81 100644
--- a/tests/network/test_http_server.py
+++ b/tests/network/test_http_server.py
@@ -25,7 +25,7 @@ pytest.importorskip("starlette")
 import httpx
 from pydantic import ValidationError
 
-from heagent.network import http_server
+from heagent.network import http_server, origin
 from heagent.network.http_protocol import MAX_REQUEST_BYTES_FOR_MAX_PROMPT, HttpErrorCode, RunOutcome
 from heagent.network.http_server import (
     HttpRunService,
@@ -255,33 +255,6 @@ class TestLifecycle:
         finally:
             await server.close()
 
-    async def test_start_without_websocket_protocol_logs_once_and_keeps_http_available(
-        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
-    ) -> None:
-        uvicorn = http_server._require_module("uvicorn")
-        real_config = uvicorn.Config
-
-        def missing_ws_config(*args: Any, **kwargs: Any) -> Any:
-            config = real_config(*args, **kwargs)
-            config.load()
-            config.ws_protocol_class = None
-            return config
-
-        monkeypatch.setattr(uvicorn, "Config", missing_ws_config)
-        server = HttpServer(_config(), version=_VERSION)
-        with caplog.at_level(logging.WARNING, logger="heagent.network.http_server"):
-            await server.start()
-            await server.start()
-        try:
-            async with httpx.AsyncClient() as client:
-                response = await client.get(f"http://127.0.0.1:{server.port}/api/health")
-            assert response.status_code == 200
-            warnings = [record for record in caplog.records if "event=ws_unavailable" in record.getMessage()]
-            assert len(warnings) == 1
-            assert "heagent[http]" in warnings[0].getMessage()
-        finally:
-            await server.close()
-
     async def test_start_and_close_are_idempotent(self) -> None:
         server = HttpServer(_config(), version=_VERSION)
         await server.start()
@@ -523,18 +496,18 @@ class TestBindingAndConcurrencyBudget:
 
     def test_wildcard_binding_only_adds_loopback_aliases(self) -> None:
         """通配绑定额外接受等价本机写法；普通非回环 host 不额外放宽（反 DNS-rebinding）。"""
-        assert http_server._allowed_hosts(_config(host="0.0.0.0")) >= {
+        assert origin.allowed_hosts(_config(host="0.0.0.0")) >= {
             "0.0.0.0",
             "127.0.0.1",
             "localhost",
             "[::1]",
         }
-        assert http_server._allowed_hosts(_config(host="::")) >= {"::", "[::1]"}
-        assert http_server._allowed_hosts(_config(host="192.168.1.5")) == frozenset({"192.168.1.5"})
+        assert origin.allowed_hosts(_config(host="::")) >= {"::", "[::1]"}
+        assert origin.allowed_hosts(_config(host="192.168.1.5")) == frozenset({"192.168.1.5"})
 
     @pytest.mark.parametrize(("host", "expected"), [("0.0.0.0", "127.0.0.1"), ("::", "::1")])
     def test_wildcards_are_probed_over_loopback(self, host: str, expected: str) -> None:
-        assert http_server._probe_host(host) == expected
+        assert origin.probe_host(host) == expected
 
 
 class TestCloseAndRestartSemantics:
diff --git a/tests/network/test_http_ws_config.py b/tests/network/test_http_ws_config.py
deleted file mode 100644
index 82f9fba..0000000
--- a/tests/network/test_http_ws_config.py
+++ /dev/null
@@ -1,96 +0,0 @@
-"""Epic 54 Story 54-2：WebSocket 依赖与配置契约。"""
-
-from __future__ import annotations
-
-from pathlib import Path
-
-import pytest
-from pydantic import ValidationError
-
-from heagent.config import Settings
-from heagent.config.catalog import RESOURCE_CEILINGS, classify, whitelist
-from heagent.network.http_protocol import SSE_HEARTBEAT_SECONDS
-from heagent.network.http_server import HttpServerConfig
-from heagent.network.ws_protocol import WS_MAX_FRAME_BYTES, WS_PING_INTERVAL_SECONDS, WS_PING_TIMEOUT_SECONDS
-
-
-def test_http_extra_declares_websockets_with_frozen_bounds() -> None:
-    project = Path("pyproject.toml").read_text(encoding="utf-8")
-    http_extra = project.split("http = [", 1)[1].split("]", 1)[0]
-    dev_extra = project.split("dev = [", 1)[1].split("gui = [", 1)[0]
-
-    assert '"websockets>=13.0,<18"' in http_extra
-    assert "websockets" not in dev_extra
-    assert project.count('"websockets>=13.0,<18"') == 1
-
-
-def test_ws_connection_limit_defaults_and_validation_match_server_config() -> None:
-    settings_field = Settings.model_fields["http_ws_max_connections"]
-    config_field = HttpServerConfig.model_fields["ws_max_connections"]
-
-    assert settings_field.default == config_field.default == 16
-    assert Settings().http_ws_max_connections == 16
-    assert HttpServerConfig().ws_max_connections == 16
-    for value in (0, -1):
-        with pytest.raises(ValidationError):
-            Settings(http_ws_max_connections=value)
-        with pytest.raises(ValidationError):
-            HttpServerConfig(ws_max_connections=value)
-
-
-def test_ws_connection_limit_is_classified_as_read_only_listening_surface() -> None:
-    result = classify("HTTP_WS_MAX_CONNECTIONS")
-    assert result.reason == "listening_surface"
-    assert not result.writable
-    assert "HTTP_WS_MAX_CONNECTIONS" not in whitelist()
-    assert "HTTP_WS_MAX_CONNECTIONS" not in RESOURCE_CEILINGS
-
-
-def test_ws_config_documented_in_env_example() -> None:
-    example = Path(".env.example").read_text(encoding="utf-8")
-    assert "HTTP_WS_MAX_CONNECTIONS" in example
-
-
-def test_uvicorn_ws_options_are_declared_in_config() -> None:
-    source = Path("src/heagent/network/http_server.py").read_text(encoding="utf-8")
-    assert "ws_max_size=WS_MAX_FRAME_BYTES" in source
-    assert "ws_ping_interval=WS_PING_INTERVAL_SECONDS" in source
-    assert "ws_ping_timeout=WS_PING_TIMEOUT_SECONDS" in source
-    assert WS_PING_INTERVAL_SECONDS == SSE_HEARTBEAT_SECONDS == 15.0
-    assert WS_PING_TIMEOUT_SECONDS == 20.0
-    assert WS_MAX_FRAME_BYTES == 64 * 1024
-
-
-def test_http_server_config_ws_limit_is_independent_from_sse_pool() -> None:
-    config = HttpServerConfig(max_subscribers=3, ws_max_connections=7)
-    assert config.max_subscribers == 3
-    assert config.ws_max_connections == 7
-
-
-# ---- CLI 旁路订阅（Epic 55）----
-
-
-def test_cli_ws_is_off_by_default_and_documented() -> None:
-    """默认关是**契约**：无认证的本机通道不该因为升级就自己打开。"""
-    assert Settings().http_cli_ws_enabled is False
-    example = Path(".env.example").read_text(encoding="utf-8")
-    assert "HTTP_CLI_WS_ENABLED=false" in example
-
-
-def test_cli_ws_switch_is_classified_as_read_only_listening_surface() -> None:
-    result = classify("HTTP_CLI_WS_ENABLED")
-    assert result.reason == "listening_surface"
-    assert not result.writable
-    assert "HTTP_CLI_WS_ENABLED" not in whitelist()
-
-
-@pytest.mark.embedded_http_service
-def test_embedded_service_only_attaches_a_hub_when_the_switch_is_on() -> None:
-    """``embedded_http_service`` 标记：要断言真实的 ``build_http_service``（conftest 默认打桩）。"""
-    from heagent.cli.http import build_http_service
-
-    assert build_http_service(Settings(), executor=None).cli_hub is None
-    hub = build_http_service(Settings(http_cli_ws_enabled=True), executor=None).cli_hub
-    assert hub is not None
-    # 额度取自同一个监听面旋钮：旁路只有一条流，故按 hub 计（与「每 run」的 WS 额度是不同口径）。
-    assert hub.max_connections == Settings().http_ws_max_connections
diff --git a/tests/network/test_http_ws_e2e.py b/tests/network/test_ws_e2e.py
similarity index 88%
rename from tests/network/test_http_ws_e2e.py
rename to tests/network/test_ws_e2e.py
index 12fbad5..2cf7639 100644
--- a/tests/network/test_http_ws_e2e.py
+++ b/tests/network/test_ws_e2e.py
@@ -1,4 +1,4 @@
-"""Epic 54 Story 54-3：WebSocket 端点端到端契约。"""
+"""Epic 54 Story 54-3 端到端契约，Epic 56 D1 起驱动 = WsServer（9001，宿主迁移）。"""
 
 from __future__ import annotations
 
@@ -10,7 +10,8 @@ from typing import Any
 import pytest
 
 from heagent.network.http_protocol import HttpErrorCode, RunOutcome, RunStatus
-from heagent.network.http_server import HttpRunService, HttpServer, HttpServerConfig
+from heagent.network.http_server import HttpRunService, HttpServerConfig
+from heagent.network.ws_host import WsServer, WsServerConfig
 
 websockets = pytest.importorskip("websockets")
 
@@ -38,18 +39,27 @@ def _server_config(**kwargs: Any) -> HttpServerConfig:
     return HttpServerConfig(port=0, request_timeout=0, idle_timeout=0, tool_inflight_timeout=0, **kwargs)
 
 
+def _ws_config(**kwargs: Any) -> WsServerConfig:
+    return WsServerConfig(port=0, shutdown_timeout=1, **kwargs)
+
+
 async def _start(
     executor: _Executor, *, ws_limit: int = 4, buffer_size: int = 16
-) -> tuple[HttpServer, HttpRunService, asyncio.Task[None]]:
-    config = _server_config(ws_max_connections=ws_limit, event_buffer_size=buffer_size)
-    service = HttpRunService(config, executor)
-    server = HttpServer(config, version="test", run_service=service)
+) -> tuple[WsServer, HttpRunService, asyncio.Task[None]]:
+    """双配置装配：运行状态机吃 HTTP 配置（进程内注入），WS listener 吃 WsServerConfig（D1 接缝事实）。"""
+    service = HttpRunService(
+        _server_config(event_buffer_size=buffer_size),
+        executor,
+    )
+    server = WsServer(_ws_config(ws_max_connections=ws_limit), run_service=service)
     await server.start()
     task = asyncio.create_task(server.serve_forever())
+    # 让 serve 协程先进入 main_loop（防「建任务后立刻 close」的首次调度竞态，同旧注释）。
+    await asyncio.sleep(0)
     return server, service, task
 
 
-async def _stop(server: HttpServer, task: asyncio.Task[None]) -> None:
+async def _stop(server: WsServer, task: asyncio.Task[None]) -> None:
     await server.close()
     await asyncio.wait_for(task, timeout=5)
 
@@ -197,6 +207,8 @@ async def test_shutdown_closes_websocket_and_cancels_run_within_budget() -> None
         while service.ws_connection_count(record) == 0:
             await asyncio.sleep(0)
         started = asyncio.get_running_loop().time()
+        # 入口层编排口径：HTTP 侧先排空运行到终态（service.close），WS 侧再关连接与 listener。
+        await service.close()
         await server.close()
         elapsed = asyncio.get_running_loop().time() - started
         frames: list[dict[str, Any]] = []
@@ -210,8 +222,9 @@ async def test_shutdown_closes_websocket_and_cancels_run_within_budget() -> None
         assert ws.close_code == 1001
         assert record.status is RunStatus.CANCELLED
         assert service.ws_connection_count(record) == 0
-        assert elapsed <= 2 * service.config.shutdown_timeout + 2
-        await server.close()
+        assert elapsed <= 2 * server.config.shutdown_timeout + 2
+        # main_loop 以 0.1s 轮询 should_exit：显式等 serve 任务退出，不和调度竞速。
+        await asyncio.wait_for(task, timeout=5)
         assert task.done()
     finally:
         await ws.close()
diff --git a/tests/network/test_ws_server.py b/tests/network/test_ws_server.py
new file mode 100644
index 0000000..0ee2f73
--- /dev/null
+++ b/tests/network/test_ws_server.py
@@ -0,0 +1,375 @@
+"""Epic 56 Story 56-1：WS server 宿主（ws_host）纯逻辑面 + 分离判据。
+
+与 e2e（``test_ws_e2e.py`` / ``test_cli_ws_e2e.py``）的分工：这里用替身与真实 listener 钉住
+**配置契约、路由注册矩阵、双 server 分离判据与生命周期**；端到端语义（订阅/续传/cancel/ping/
+限额/关停）随 56-1 迁入 e2e 文件（原 ``test_http_ws_e2e`` / ``test_http_cli_ws``，HttpServer
+驱动 → WsServer 驱动）。
+"""
+
+from __future__ import annotations
+
+import asyncio
+import json
+import socket
+from pathlib import Path
+from typing import Any
+
+import pytest
+from pydantic import ValidationError
+
+from heagent.config import Settings
+from heagent.config.catalog import RESOURCE_CEILINGS, classify, whitelist
+from heagent.network.cli_event_hub import CliEventHub
+from heagent.network.http_protocol import RunOutcome
+from heagent.network.http_server import HttpRunService, HttpServerConfig
+from heagent.network.ws_host import (
+    RUNS_WS_PATH,
+    WsServer,
+    WsServerConfig,
+    WsStartupError,
+    build_ws_app,
+)
+from heagent.network.ws_protocol import WS_MAX_FRAME_BYTES, WS_PING_INTERVAL_SECONDS, WS_PING_TIMEOUT_SECONDS
+
+websockets = pytest.importorskip("websockets")
+
+
+class _BlockingExecutor:
+    """先发三帧事件再挂起等待释放的替身运行器（供生命周期用例）。"""
+
+    def __init__(self) -> None:
+        self.started = asyncio.Event()
+        self.release = asyncio.Event()
+        self.cancelled = 0
+
+    async def __call__(self, prompt: str, publisher: Any) -> RunOutcome:
+        publisher.text("hello")
+        publisher.tool_call("shell", "echo hello")
+        publisher.tool_result("shell", "hello", is_error=False)
+        self.started.set()
+        try:
+            await self.release.wait()
+        except asyncio.CancelledError:
+            self.cancelled += 1
+            raise
+        return RunOutcome(answer=prompt)
+
+
+# ---- 配置契约（自 test_http_ws_config.py 迁入并按 D1 更名）----
+
+
+def test_ws_config_defaults_are_synced_with_settings() -> None:
+    """``WS_MAX_CONNECTIONS`` 设置与 ``WsServerConfig`` 默认值同源同校验（迁移自 54-2 契约）。"""
+    settings_field = Settings.model_fields["ws_max_connections"]
+    config_field = WsServerConfig.model_fields["ws_max_connections"]
+
+    assert settings_field.default == config_field.default == 16
+    assert Settings().ws_max_connections == 16
+    assert WsServerConfig().ws_max_connections == 16
+    for value in (0, -1):
+        with pytest.raises(ValidationError):
+            Settings(ws_max_connections=value)
+        with pytest.raises(ValidationError):
+            WsServerConfig(ws_max_connections=value)
+
+
+def test_ws_server_config_defaults_pin_d1_topology() -> None:
+    """默认 127.0.0.1:9001 是 D1 冻结值；port=0（随机端口）仅测试用。"""
+    config = WsServerConfig()
+    assert (config.host, config.port, config.ws_max_connections, config.shutdown_timeout) == (
+        "127.0.0.1",
+        9001,
+        16,
+        5.0,
+    )
+    with pytest.raises(ValidationError):
+        WsServerConfig(port=0 - 1)
+    with pytest.raises(ValidationError):
+        WsServerConfig(shutdown_timeout=0)
+
+
+def test_ws_limit_is_classified_as_read_only_listening_surface() -> None:
+    result = classify("WS_MAX_CONNECTIONS")
+    assert result.reason == "listening_surface"
+    assert not result.writable
+    assert "WS_MAX_CONNECTIONS" not in whitelist()
+    assert "WS_MAX_CONNECTIONS" not in RESOURCE_CEILINGS
+    assert classify("WS_HOST").reason == "listening_surface"
+    assert classify("WS_PORT").reason == "listening_surface"
+
+
+def test_ws_config_documented_in_env_example() -> None:
+    example = Path(".env.example").read_text(encoding="utf-8")
+    assert "WS_MAX_CONNECTIONS=16" in example
+    assert "HTTP_WS_MAX_CONNECTIONS" not in example
+
+
+def test_uvicorn_ws_options_moved_to_ws_host() -> None:
+    """uvicorn WS 参数随 D1 迁移：ws_host 有、http_server 无（既有 54-2 契约换宿主）。"""
+    ws_source = Path("src/heagent/network/ws_host.py").read_text(encoding="utf-8")
+    http_source = Path("src/heagent/network/http_server.py").read_text(encoding="utf-8")
+    assert "ws_max_size=WS_MAX_FRAME_BYTES" in ws_source
+    assert "ws_ping_interval=WS_PING_INTERVAL_SECONDS" in ws_source
+    assert "ws_ping_timeout=WS_PING_TIMEOUT_SECONDS" in ws_source
+    assert WS_PING_INTERVAL_SECONDS == 15.0
+    assert WS_PING_TIMEOUT_SECONDS == 20.0
+    assert WS_MAX_FRAME_BYTES == 64 * 1024
+    assert "ws_max_size=" not in http_source
+    assert "ws_ping_interval=" not in http_source
+
+
+# ---- CLI 旁路开关（自 54-2/55 契约迁入并按 D7 更名）----
+
+
+def test_cli_bypass_is_off_by_default_and_documented() -> None:
+    """默认关是契约：无认证的本机通道不该因为拆分就自己打开。"""
+    assert Settings().ws_cli_bypass_enabled is False
+    example = Path(".env.example").read_text(encoding="utf-8")
+    assert "WS_CLI_BYPASS_ENABLED=false" in example
+    assert "HTTP_CLI_WS_ENABLED" not in example
+
+
+def test_cli_bypass_switch_is_classified_as_read_only_listening_surface() -> None:
+    result = classify("WS_CLI_BYPASS_ENABLED")
+    assert result.reason == "listening_surface"
+    assert not result.writable
+    assert "WS_CLI_BYPASS_ENABLED" not in whitelist()
+
+
+@pytest.mark.embedded_http_service
+def test_embedded_service_only_attaches_a_hub_when_the_switch_is_on() -> None:
+    """embedded_http_service 标记：要断言真实的 build_http_service（conftest 默认打桩）。"""
+    from heagent.cli.http import build_http_service
+
+    assert build_http_service(Settings(), executor=None).cli_hub is None
+    hub = build_http_service(Settings(ws_cli_bypass_enabled=True), executor=None).cli_hub
+    assert hub is not None
+    # 额度取自同一个监听面旋钮：旁路只有一条流，故按 hub 计（与每 run 的 WS 额度是不同口径）。
+    assert hub.max_connections == Settings().ws_max_connections
+
+
+# ---- 路由注册矩阵与分离判据（D1 可执行判据）----
+
+
+def _ws_config(**kwargs: Any) -> WsServerConfig:
+    return WsServerConfig(port=0, shutdown_timeout=1, **kwargs)
+
+
+def _http_config(**kwargs: Any) -> HttpServerConfig:
+    return HttpServerConfig(port=0, request_timeout=0, idle_timeout=0, tool_inflight_timeout=0, **kwargs)
+
+
+async def _raw_status(port: int, path: str) -> int:
+    """异步裸 HTTP GET 的状态行（异步用例禁同步 urllib：会阻塞事件循环自身造成假超时）。"""
+    reader, writer = await asyncio.open_connection("127.0.0.1", port)
+    try:
+        request = ("GET " + path + " HTTP/1.1\r\n" + "host: 127.0.0.1:%d\r\n" + "connection: close\r\n\r\n") % port
+        writer.write(request.encode())
+        await writer.drain()
+        line = await asyncio.wait_for(reader.readline(), timeout=3)
+        return int(line.split()[1])
+    finally:
+        writer.close()
+
+
+def _run_app_matrix(app: Any) -> tuple[int, int]:
+    """对 app 各打一个 HTTP GET 与一次 WS 升级（ASGI 层），返回 (http_status, ws_close_code)。"""
+    from starlette.testclient import TestClient
+
+    client = TestClient(app)
+    response = client.get("/api/health")
+    try:
+        with client.websocket_connect(RUNS_WS_PATH.replace("{run_id}", "nope")) as ws:
+            ws.receive_json()
+            close_code = -1
+    except Exception as exc:  # TestClient 把「未 accept 即关」收敛为异常
+        close_code = getattr(exc, "code", -1)
+    return response.status_code, close_code
+
+
+def test_ws_app_has_zero_http_surface() -> None:
+    """D1 判据之 9001 侧：REST / 控制台页 / 健康检查全 404（Starlette 默认 404 文本）。"""
+    config = _ws_config()
+    for app in (
+        build_ws_app(config),
+        build_ws_app(config, run_service=HttpRunService(_http_config(), None)),
+        build_ws_app(config, cli_hub=CliEventHub()),
+    ):
+        from starlette.testclient import TestClient
+
+        client = TestClient(app)
+        for path in ("/", "/api/health", "/api/runs", "/api/projects", "/api/session"):
+            response = client.get(path)
+            assert response.status_code == 404, path
+            assert response.headers["content-type"].startswith("text/plain")
+
+
+def test_http_app_no_longer_hosts_websocket_routes() -> None:
+    from starlette.testclient import WebSocketDisconnect
+
+    """D1 判据之 8766 侧（ASGI 层）：HTTP app 对任意 WS 升级路径不再 accept。"""
+    from starlette.testclient import TestClient
+
+    from heagent.network.http_server import HttpServer
+
+    server = HttpServer(_http_config(), version="test")
+    client = TestClient(server.app)
+    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/api/runs/nope/ws"):
+        pass
+
+
+@pytest.mark.asyncio
+async def test_http_listener_rejects_ws_upgrade_over_real_tcp() -> None:
+    """D1 判据之 8766 侧（真实 TCP）：升级被拒、未 accept。
+
+    裁定①A：钉实测「非 101、未 accept」（Starlette 1.3.1 在真实 Uvicorn 下回 HTTP 403），
+    不钉 brief 验收措辞的字面 404——判据本质是「8766 上 WS 不可达」。
+    """
+    service = HttpRunService(_http_config(), _BlockingExecutor())
+    from heagent.network.http_server import HttpServer
+
+    server = HttpServer(_http_config(), version="test", run_service=service)
+    await server.start()
+    task = asyncio.create_task(server.serve_forever())
+    try:
+        with pytest.raises(websockets.exceptions.InvalidStatus) as rejected:
+            async with websockets.connect(f"ws://127.0.0.1:{server.port}/api/runs/x/ws"):
+                pass
+        assert rejected.value.response.status_code == 403
+        # 同一 listener 的 HTTP 面零改动：健康检查照常 200。
+        assert await _raw_status(server.port, "/api/health") == 200
+    finally:
+        await server.close()
+        await asyncio.wait_for(task, timeout=5)
+
+
+@pytest.mark.asyncio
+async def test_ws_listener_serves_no_http_api_over_real_tcp() -> None:
+    """D1 判据之 9001 侧（真实 TCP）：REST/静态页/健康检查全 404，WS 端点可达。"""
+    service = HttpRunService(_http_config(), _BlockingExecutor())
+    hub = CliEventHub()
+    server = WsServer(_ws_config(), run_service=service, cli_hub=hub)
+    await server.start()
+    task = asyncio.create_task(server.serve_forever())
+    try:
+        for path in ("/", "/api/health", "/api/runs", "/api/projects", "/web/app.js"):
+            assert await _raw_status(server.port, path) == 404, path
+        # 端点本体可达：无 run 记录时订阅被端点拒绝（unknown_run），而非路由 403。
+        async with websockets.connect(f"ws://127.0.0.1:{server.port}/api/runs/x/ws") as ws:
+            frame = json.loads(await ws.recv())
+        assert frame["type"] == "error"
+        assert frame["error"]["error"]["code"] == "unknown_run"
+    finally:
+        await server.close()
+        await asyncio.wait_for(task, timeout=5)
+
+
+# ---- WsServer 生命周期 ----
+
+
+@pytest.mark.asyncio
+async def test_ws_server_start_serves_and_closes_idempotently() -> None:
+    server = WsServer(_ws_config(), run_service=HttpRunService(_http_config(), _BlockingExecutor()))
+    await server.start()
+    # 让 serve 协程先进入 main_loop 再 close：否则协程体在 _server 已置空后才首次被调度，
+    # 会抛 RuntimeError（test_http_cli_ws 时代的同一坑）。
+    task = asyncio.create_task(server.serve_forever())
+    await asyncio.sleep(0)
+    try:
+        assert server.port > 0
+        assert server.address == f"127.0.0.1:{server.port}"
+        await server.close()
+        await server.close()  # 幂等
+    finally:
+        await asyncio.wait_for(task, timeout=5)
+
+
+@pytest.mark.asyncio
+async def test_ws_server_close_alone_never_cancels_runs() -> None:
+    """断线语义（D1 拆分后归属 WS 侧）：关 WS listener 只注销连接，绝不取消运行。
+
+    运行的终结归 HTTP 侧的 service.close()（入口层编排 HTTP 先、WS 后）。
+    """
+    executor = _BlockingExecutor()
+    service = HttpRunService(_http_config(), executor)
+    server = WsServer(_ws_config(), run_service=service)
+    await server.start()
+    task = asyncio.create_task(server.serve_forever())
+    record = await service.start_run("answer")
+    try:
+        await executor.started.wait()
+        uri = f"ws://127.0.0.1:{server.port}/api/runs/{record.run_id}/ws"
+        async with websockets.connect(uri):
+            while service.ws_connection_count(record) == 0:
+                await asyncio.sleep(0)
+        await asyncio.sleep(0.1)
+        await server.close()
+        await asyncio.wait_for(task, timeout=5)
+        assert record.status.value == "running"
+        assert service.ws_connection_count(record) == 0
+    finally:
+        executor.release.set()
+        await service.close()
+        if not task.done():
+            await asyncio.wait_for(task, timeout=5)
+
+
+@pytest.mark.asyncio
+async def test_ws_server_start_fails_loud_when_port_explicitly_taken() -> None:
+    """显式端口被占 ⇒ WsStartupError（fail-loud，不静默换端口）。"""
+    with socket.socket() as blocker:
+        blocker.bind(("127.0.0.1", 0))
+        blocker.listen(1)
+        taken = blocker.getsockname()[1]
+        server = WsServer(WsServerConfig(host="127.0.0.1", port=taken, shutdown_timeout=1))
+        with pytest.raises(WsStartupError):
+            await server.start()
+
+
+def test_ws_unavailable_diagnostic_is_logged_once(monkeypatch: pytest.MonkeyPatch, caplog: Any) -> None:
+    """缺 websockets（ws_protocol_class=None）⇒ 安装诊断一条、且只记一次（spec I/O 矩阵行）。"""
+    import logging
+
+    server = WsServer(_ws_config())
+    fake = type("FakeServer", (), {"config": type("FakeConfig", (), {"ws_protocol_class": None})()})()
+    with caplog.at_level(logging.WARNING, logger="heagent.network.ws_host"):
+        server._log_ws_unavailable_once(fake)
+        server._log_ws_unavailable_once(fake)
+    hints = [rec for rec in caplog.records if "ws_unavailable" in rec.getMessage()]
+    assert len(hints) == 1
+    assert "heagent[http]" in hints[0].getMessage()
+
+
+# ---- 组合根装配（build_ws_server_config / 双 server 编排）----
+
+
+def test_build_ws_server_config_maps_settings_and_overrides() -> None:
+    from heagent.cli.http import build_ws_server_config
+
+    assert build_ws_server_config(Settings()).port == 9001
+    assert build_ws_server_config(Settings(ws_port=9100)).port == 9100
+    assert build_ws_server_config(Settings(), port=9200).port == 9200
+    assert build_ws_server_config(Settings(), host="0.0.0.0").host == "0.0.0.0"
+    assert build_ws_server_config(Settings(), max_connections=7).ws_max_connections == 7
+    assert build_ws_server_config(Settings(), shutdown_timeout=9).shutdown_timeout == 9.0
+
+
+def test_build_ws_server_config_autofind_starts_from_ws_port(monkeypatch: pytest.MonkeyPatch) -> None:
+    """自动顺延的基准 = WS 端口（9001），不是 HTTP 端口——两条 listener 独立漂移。"""
+    from heagent.cli.http import build_ws_server_config
+
+    with socket.socket() as blocker:
+        blocker.bind(("127.0.0.1", 0))
+        blocker.listen(1)
+        taken = blocker.getsockname()[1]
+        monkeypatch.setenv("HTTP_PORT_AUTO_FIND_ATTEMPTS", "5")
+        config = build_ws_server_config(Settings(ws_port=taken))
+        assert config.port == taken + 1
+
+
+def test_build_server_config_no_longer_carries_ws_knob() -> None:
+    """D1：HTTP 配置面不再有 ws_max_connections（旋钮迁 WS 配置面）。"""
+    from heagent.cli.http import build_server_config
+
+    config = build_server_config(Settings())
+    assert not hasattr(config, "ws_max_connections")
diff --git a/tests/test_cli_http.py b/tests/test_cli_http.py
index b5e1169..948a128 100644
--- a/tests/test_cli_http.py
+++ b/tests/test_cli_http.py
@@ -47,13 +47,14 @@ class _StubProvider:
 
 @pytest.fixture()
 def captured_server(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> dict[str, HttpServer]:
-    """把 ``_serve_http`` 换成「记录 server 即返回」：参数断言不需要真的绑定端口。"""
-    captured: dict[str, HttpServer] = {}
+    """把 ``_serve_web`` 换成「记录双 server 即返回」：参数断言不需要真的绑定端口。"""
+    captured: dict[str, Any] = {}
 
-    async def fake_serve(server: HttpServer) -> None:
-        captured["server"] = server
+    async def fake_serve(http_server: HttpServer, ws_server: Any) -> None:
+        captured["server"] = http_server
+        captured["ws"] = ws_server
 
-    monkeypatch.setattr("heagent.cli.http._serve_http", fake_serve)
+    monkeypatch.setattr("heagent.cli.http._serve_web", fake_serve)
     monkeypatch.setattr("heagent.cli.http._build_provider", lambda settings, model: _StubProvider())
     monkeypatch.chdir(tmp_path)
     return captured
@@ -68,6 +69,8 @@ def test_help_lists_http_options() -> None:
         "--port",
         "--max-connections",
         "--max-subscribers",
+        "--ws-host",
+        "--ws-port",
         "--ws-max-connections",
         "--max-inflight-runs",
         "--max-request-bytes",
@@ -87,28 +90,28 @@ def test_ws_connection_limit_cli_override_reaches_config_without_mutating_settin
     monkeypatch: pytest.MonkeyPatch, captured_server: dict[str, HttpServer]
 ) -> None:
     monkeypatch.setenv("HTTP_PORT_AUTO_FIND_ATTEMPTS", "0")
-    monkeypatch.setenv("HTTP_WS_MAX_CONNECTIONS", "7")
+    monkeypatch.setenv("WS_MAX_CONNECTIONS", "7")
     reset_settings()
     settings = get_settings()
 
     result = CliRunner().invoke(main, ["http-server", "--ws-max-connections", "3"])
 
     assert result.exit_code == 0, result.output
-    assert captured_server["server"].config.ws_max_connections == 3
-    assert settings.http_ws_max_connections == 7
+    assert captured_server["ws"].config.ws_max_connections == 3
+    assert settings.ws_max_connections == 7
 
 
 def test_ws_connection_limit_environment_value_reaches_config(
     monkeypatch: pytest.MonkeyPatch, captured_server: dict[str, HttpServer]
 ) -> None:
     monkeypatch.setenv("HTTP_PORT_AUTO_FIND_ATTEMPTS", "0")
-    monkeypatch.setenv("HTTP_WS_MAX_CONNECTIONS", "9")
+    monkeypatch.setenv("WS_MAX_CONNECTIONS", "9")
     reset_settings()
 
     result = CliRunner().invoke(main, ["http-server"])
 
     assert result.exit_code == 0, result.output
-    assert captured_server["server"].config.ws_max_connections == 9
+    assert captured_server["ws"].config.ws_max_connections == 9
 
 
 def test_registered_as_explicit_subcommand() -> None:
@@ -129,7 +132,6 @@ def test_build_server_config_uses_settings_defaults() -> None:
         port=settings.http_port,
         max_connections=settings.http_max_connections,
         max_subscribers=settings.http_max_subscribers,
-        ws_max_connections=settings.http_ws_max_connections,
         max_inflight_runs=settings.http_max_inflight_runs,
         max_total_inflight=settings.http_max_total_inflight,
         max_request_bytes=settings.http_max_request_bytes,
diff --git a/tests/test_cli_http_lifecycle.py b/tests/test_cli_http_lifecycle.py
index 7c0d370..bbce0d1 100644
--- a/tests/test_cli_http_lifecycle.py
+++ b/tests/test_cli_http_lifecycle.py
@@ -286,10 +286,11 @@ def test_explicit_subcommands_never_start_the_embedded_service(
     _drive(monkeypatch, tmp_path, provider)
     served: list[str] = []
 
-    async def fake_serve_http(_server: object) -> None:
+    async def fake_serve_web(http_server: object, ws_server: object) -> None:
         served.append("http")
+        assert ws_server is not None  # 双 server：显式命令同样装配 WS listener（56-1）
 
-    monkeypatch.setattr("heagent.cli.http._serve_http", fake_serve_http)
+    monkeypatch.setattr("heagent.cli.http._serve_web", fake_serve_web)
     # cli/http.py 模块级绑定了 `_build_provider`（与 cli/console.py 是两处名字），逐一打桩。
     monkeypatch.setattr("heagent.cli.http._build_provider", lambda settings, model: provider)
     rollout = tmp_path / "rollout.jsonl"
diff --git a/tests/test_cli_ws_publish.py b/tests/test_cli_ws_publish.py
index 3b8bcb7..be7992d 100644
--- a/tests/test_cli_ws_publish.py
+++ b/tests/test_cli_ws_publish.py
@@ -173,9 +173,7 @@ def test_mirror_is_a_no_op_without_a_hub() -> None:
 def test_scope_propagates_into_the_stream_mirror() -> None:
     """``_cli_hub_scope`` 的作用域必须真的到达 ``_consume_stream``（contextvar 传播判据）。"""
     hub = _RecordingHub()
-    loop = _StubLoop(
-        [StreamEvent(type="text", text="hi"), StreamEvent(type="done", final_answer="ok")]
-    )
+    loop = _StubLoop([StreamEvent(type="text", text="hi"), StreamEvent(type="done", final_answer="ok")])
 
     async def scenario() -> None:
         async with interactive._cli_hub_scope(SimpleNamespace(cli_hub=hub)):
diff --git a/tests/test_cli_ws_wiring.py b/tests/test_cli_ws_wiring.py
index ea4178a..0669f25 100644
--- a/tests/test_cli_ws_wiring.py
+++ b/tests/test_cli_ws_wiring.py
@@ -1,8 +1,8 @@
-"""CLI 旁路的**装配**契约：``build_http_service`` → ``HttpServer`` → 路由 → 中枢。
+"""CLI 旁路的**装配**契约：``build_http_service`` → ``WsServer`` → 路由 → 中枢（Epic 56 D7）。
 
-为什么单独一个文件：其余用例都直接构造 ``HttpServer(cli_hub=...)``，因此「真实入口忘了把中枢
+为什么单独一个文件：其余用例都直接构造 ``WsServer(cli_hub=...)``，因此「真实入口忘了把中枢
 传下去」这类漏接不会变红（``EmbeddedHttpService.cli_hub`` 有值、路由却没注册）。这里从**入口函数**
-起步，用真 TCP 连一次 ``/api/cli/ws``。
+起步，用真 TCP 连一次 ``/api/cli/ws``（9001 侧）。
 """
 
 from __future__ import annotations
@@ -24,12 +24,12 @@ pytestmark = pytest.mark.embedded_http_service
 
 @pytest.mark.asyncio
 async def test_service_built_from_settings_serves_the_cli_event_stream() -> None:
-    service = build_http_service(Settings(http_cli_ws_enabled=True), executor=None)
+    service = build_http_service(Settings(ws_cli_bypass_enabled=True), executor=None)
     assert service.cli_hub is not None
     await service.start()
     try:
         hub = service.cli_hub
-        uri = f"ws://{service.address}/api/cli/ws"
+        uri = f"ws://{service.ws_address}/api/cli/ws"
         async with websockets.connect(uri) as ws:
             hub.begin_run()
             hub.publish_text("from the terminal")
@@ -44,7 +44,7 @@ async def test_service_built_from_settings_serves_the_cli_event_stream() -> None
 
 @pytest.mark.asyncio
 async def test_disabled_switch_leaves_the_route_unregistered() -> None:
-    service = build_http_service(Settings(http_cli_ws_enabled=False), executor=None)
+    service = build_http_service(Settings(ws_cli_bypass_enabled=False), executor=None)
     assert service.cli_hub is None
     await service.start()
     try:

===== END DIFF =====
