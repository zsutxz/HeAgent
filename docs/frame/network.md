# 网络入口与网页控制台

> 状态：当前实现参考，由 [framework.md](../framework.md) 4.16 / 4.16.1 / 4.17 三节原样迁出（编号不变，
> 其它文档里按「4.16」「4.17」的引用仍指本页对应小节）。数据流、模块 DAG、配置总表与安全口径
> （§4.18）仍在 framework.md。

## 4.16 HTTP 网页入口 (`network/http_*` + `cli/http.py` + `web/`)

本机网页入口（Epic 49）：`heagent http-server` 起来后，浏览器打开 stderr 提示的地址即可使用内置
聊天页；默认 CLI 也会在同一进程内自动提供该入口（见下表「默认 CLI 自启动」）。分层与 HTTP 家族既有实现同构
——`network/` 只承载传输（HTTP 协议模型 / 路由 / 运行服务 / 安全响应头 / 静态资源 / listener
生命周期），装配在入口层 `cli/http.py`；`network/` 不构造 Agent，运行入口由入口层以可调用对象注入。

**Epic 56 D1 起是「同进程双 server」**（HTTP + WS 各一条；Epic 72 起第二 WS listener 已退役，非回环入口走
`lan` / `external`）：本节的 HTTP listener（默认 `127.0.0.1:9101`）只服务
HTTP+SSE 与内嵌网页，**不含任何 WS 路由**；WS 能力全部迁到独立 listener（默认 `127.0.0.1:9201`，
见 4.16.1），两者共享的只有注入的进程内状态（`HttpRunService` / `CliEventHub`）与 `network/`
同层协议模型。入口层 `EmbeddedHttpService` 拥有**两条** listener、一个生命周期：HTTP 先启动、
失败则整体回滚；关停顺序 HTTP 先（排空运行到终态）→ WS 后（关残余连接与 listener）。

| 关注点 | 实现事实（Story 49-1/49-2/49-3 已交付部分） |
| --- | --- |
| 协议模型 | `network/http_protocol.py`：`HttpErrorCode` 封闭 **37** 码（含 `HttpRunConflictError.code` 的冲突映射）+ `network/ws_protocol.py`：WS `hello` / `event` / `ack` / `error` / `notification` / `projects` 帧（`hello` 为连接首帧，见 4.16.1 帧契约）与 `{run, cancel, cancel_run, ping, projects}` 命令（`run` / `projects` 仅集合级端点有效，见 4.16.1）；错误信封与事件负载复用 HTTP/SSE 模型。 |
| 传输层 | `network/http_server/`（子包：app / listener / service / pipeline / endpoints_*）：**HTTP/SSE 独占**——listener 生命周期、路由、运行服务、安全响应头、静态资源；**不再挂任何 `WebSocketRoute`**（Epic 56 D1，9101 上的 WS 升级不可达）。WS 侧全部在 `network/ws_host.py`（listener + 装配）与 `network/ws_server.py`（端点逻辑、续传、命令）。两者均不构造 Agent；`ws_server` 与 `ws_host` 均**不得**导入 `http_server`（同层传输模块互不依赖，架构契约钉住；共用的延迟导入辅助住 `network/optional_deps.py`）。 |
| 可选依赖 | `starlette` / `uvicorn` / `websockets>=13.0,<18` 由 `pyproject.toml` 的 `http` extra **直接声明**；服务端只延迟导入 Starlette/Uvicorn，不直接导入 `websockets`。缺少 HTTP 栈抛 `HttpDependencyError`；缺少 WS 协议实现时 HTTP 仍可启动并记录 `ws_unavailable`。可执行断言：`tests/test_architecture_contracts.py::test_optional_asgi_stack_is_only_imported_lazily`。 |
| 就绪门禁 | `start()` 只在「listener 已绑定**且**用真实网络连接打通一次 `/api/health`（200）」后返回；绑定失败（Uvicorn 在该路径上是 `sys.exit(STARTUP_FAILURE)`）与探测失败都转成 `HttpStartupError`，命令层给可读错误，**绝不**打印「已监听」。**通配绑定**（`0.0.0.0` / `::`）的探测改走回环地址（连 `0.0.0.0` 是未定义行为），故允许集对通配值额外接受 `127.0.0.1` / `localhost` / `[::1]`（探测的 Host 头按 authority 语法给 IPv6 加方括号）——通配绑定可从本机浏览器访问，但经其它网卡地址访问仍被 `origin_forbidden` 拒绝（非回环联网不受支持）。连接的 `limit_concurrency` 额外预留 1 条给就绪探测，否则 `HTTP_MAX_CONNECTIONS=1` 会让入口**永远起不来**（以上两项为 2026-09-23 评审修复）；探测收尾（`writer.close()` 之后的 `await writer.wait_closed()`）**自带 `_PROBE_TIMEOUT` 上界**——对端只收不关（或黑洞）时不再把就绪门禁拖成无界等待（2026-09-28 修复，`tests/network/test_http_server.py::TestProbeBoundedClose`）|
| 关闭 | `close()` 幂等且全程有界：设 `should_exit` → Uvicorn `shutdown()`（连接排空受 `timeout_graceful_shutdown` 约束）→ 等待 serve 循环退出（超时则取消），整体再包一层 `wait_for`。信号**不归 Uvicorn 管**（不调 `serve()` / `capture_signals`）：`KeyboardInterrupt` 由 CLI 接住并安静退出 |
| 静态资源 | `src/heagent/web/` 内 `index.html` / `styles.css` 与脚本 `app.js`（对话与控制台）/ `panels.js`（面板公共桥）/ `tasks.js`（后台任务面板）/ `api-console.js`（同源 API 探索器，Epic 70）/ `status-panel.js`（服务器状态面板，Epic 71），经 `importlib.resources.files("heagent.web")` 读取（AD-11 唯一查找方式；wheel 里以 `zipimport` 加载已实测）；**白名单**路由同时挡掉路径穿越与「散落文件被意外发布」，且测试双向钉住「页面引用的都在白名单」「白名单里的都被引用」 |
| 安全响应头 | 每个响应带 `Content-Security-Policy: default-src 'none'; script-src 'self'; …; frame-ancestors 'none'`、`X-Content-Type-Options: nosniff`、`X-Frame-Options: DENY`、`Referrer-Policy: no-referrer`、`Cache-Control: no-store`（**默认不落缓存副本**，2026-09-28 补：此前只有 SSE 路径带该头，`GET /api/session` 的进程内会话快照与其它 JSON / 错误响应都能被浏览器或中间代理缓存；**已显式设置的不覆盖**——静态资源保留 `no-cache`（允许缓存但必须回源校验，Epic 50 D8 的口径）并带**内容 ETag**：`If-None-Match` 命中回 304（不重传正文，2026-11-26 补），SSE 保留 `no-store` + `x-accel-buffering: no`）；页面**不加载任何第三方脚本**（CSP 不允许内联；测试断言页面所有 `src` / `href` 都是同源绝对路径） |
| 渲染纪律 | 页面脚本只用 `textContent` / `createTextNode` 渲染提示词、回答与工具输出（**永不** `.innerHTML`）；HTML 里没有内联脚本或样式 |
| 输入与键盘 | 输入框是**多行** `<textarea>`（`rows=3`，`maxlength` = `MAX_PROMPT_CHARS`，有测试钉住「多行 + 有上限」）。**Enter 发送、Shift+Enter 换行**，Ctrl/Cmd+Enter 同样发送；**输入法组合态（`isComposing` / `keyCode 229`）一律不发送**——否则中文选词时敲回车会把半个词发出去。提交时前端 `trim()` 掉首尾空白（中间换行原样进 prompt），空内容静默忽略；行为由 `tests/test_http_web_ui.py` 的 node 探针（case E）钉住 |
| 默认 CLI 自启动 | `heagent` / `heagent "prompt"` / `heagent run ...` 在**同一个 asyncio 生命周期**内启动内嵌服务（`cli.interactive._embedded_http_service` + `cli.http.EmbeddedHttpService`）：交互模式与 REPL 共存、单次模式与那次 run 并存且 run 结束即关闭并释放端口。**Epic 56 起该服务 = 双 server**（HTTP 9101 + WS 9201，见上段；Epic 72 起 WS 恒为**单 listener**，非回环入口走 `lan` / `external`，第二 listener 已退役），WS 起不来（任一 listener）时回滚已启动的全部，绝不留下「网页能开、订阅打不开」的半启动状态。`gui` / `http-server` / `init` / `replay` 都不经过该路径（**不派生第二个实例**）。启动失败（端口冲突 / 缺 `heagent[http]` / WS 配置不成立）转成命令级错误（exit 1），绝不出现「聊天正常但页面打不开」；serve 循环意外结束时交互模式如实报出并退出（AD-5 的假可用状态禁令）。`EmbeddedHttpService.failure` 的传播链（serve 循环 done callback → `_failure` → 所有者轮询）由**真实**双 listener 故障注入钉住：注入点落在 uvicorn 自己的 `Server.main_loop`（`config.callback_notify` 抛错 ⇒ 下一 tick 抛出），不替换 HeAgent 的 `serve_forever`，断言首个异常不被后续抖动覆盖、兄弟 listener 仍应答（裸 HTTP 状态行）、HTTP 健康端点仍 200、`close()` 后历史失败不被清空（A49，2026-11-02 闭合；`tests/test_cli_http_lifecycle.py::test_one_listener_dying_is_surfaced_while_the_others_keep_serving`）|
| 运行 API | `POST /api/runs`（请求体**只认** `prompt`，`extra="forbid"` ⇒ 塞 provider/model/system/沙箱/迭代预算一律 400；单运行约束：已有在途 run 时 409 `run_conflict`，**不排队不覆盖**）、`GET /api/runs/{run_id}/events`（SSE）、`DELETE /api/runs/{run_id}`（协作式取消，只作用于该 run，幂等）、`GET /api/session`（会话 id / 当前运行状态 / 已完成历史）。请求体按块读取，超过 `HTTP_MAX_REQUEST_BYTES` 立即中断（413 `request_too_large`），不用 ``request.body()`` 把大小交给客户端决定；该上限默认按「最大 prompt 的最坏 JSON 字节数」派生（见配置表），两者口径不一致时中文提示词会在远未到字符上限前就被 413 拒（2026-09-23 修复） |
| 任务进度 API | `GET /api/tasks`（至多 64 条，最近有动静的排前面）与 `GET /api/tasks/{task_id}`（未知 / 已过保留期一律 404 `not_found`）。数据源是**入口层注入**的只读投影（`build_http_app(tasks=…)`，为 `None` 时这两条路由不注册 ⇒ 404）——传输层不认识 `engine.tasks`，故不需要 IPC、也不读磁盘；「响应 <100ms」由「只读内存 + 定长模型」这条结构保证而不是靠调优。进度注册表是**进程内**单例：网页入口与内嵌入口同进程才共享，跨进程各自独立（Story 64.11） |
| 状态 API | `GET /api/status`（进程自身状态的只读聚合：`active_runs` / `max_inflight_runs` / `run_records` / `run_status` 五档计数 / 三条 WS 流连接数 / 后台任务条数；字段封闭，不含绝对路径、凭据与 traceback）。数据源同为**入口层注入**（`build_http_app(status=…)`，`None` ⇒ 路由不注册 ⇒ 404）：网络层只做一次内存读取，不扫盘、不采样；注入方异常收敛 500 `server_error` + 固定文案，诊断只进日志（`http event=status_failed`）。WS 计数**晚绑定**——`HttpServer` 早于 `build_ws_servers` 构造，入口层先注入 source、后 `bind_ws`；通知中枢全局一份（挂在每个 listener 上），按 listener 逐个相加会把同一批连接重复计。**部署面**（71.2）同一条接缝：`listeners`（kind / label / host / **实际端口** / `local|lan|external` / TLS 身份面）、`sandbox_backend`（报**生效**档位——引擎构造期的 `sandbox_decision.effective_backend`，`auto` / daemon 不可用时降级成 `passthrough`；取不到决策才回落请求值）、`config_write_enabled`、`active_provider`（运行期读实例，`/provider` 切换即刻反映）、`routing_pools`（只给池名与池内档位名）——端口读运行中的 listener（`port=0` 与端口顺延后配置值不等于真实值），模式复用 `exposure.is_loopback_host` 的单一判定（`HttpServerConfig.mode` / `WsServerConfig.mode`），**不含**密钥值、模型名、`base_url` 与绝对路径。**依赖态**（71.3）：`started_at` / `uptime_seconds`（`start()` 成功后才写，未启动为 null——0 会被读成「刚启动」）、`cron_jobs`（**进程工作区**那份 `jobs.json` 的定义与 `last_run`；网页进程不启动调度器，故**没有**「下次触发」字段）、`skill_count` / `memory_facts`；依赖态读盘走 5 秒来源侧缓存（端点本身仍只读内存），且逐项 fail-soft（坏条目只丢一条，不让整条状态 500）。**资源**（71.4）：`rss_bytes` / `threads` / `cpu_seconds` / `resource_source`——Linux 读 `/proc/self/*`、Windows 走 `ctypes`，**不引 psutil**；不支持的平台三项为 `null` 且 `resource_source="unavailable"`（绝不填 0 冒充）。**请求计数**（71.5）：`requests`（总数 / 状态码四桶 / 延迟 p50 与 max / 稳定错误码频次）——中间件就地整数自增 + 有界 ring buffer，热路径无锁无 I/O；**SSE（`text/event-stream`）只计总数与错误码、不进延迟窗口**（连接寿命不是请求延迟，一条长订阅会独占 max）；错误码只从**非 2xx 且 ≤1KB 的 JSON 信封**里读，正常响应从不进这条路径；计数在响应发出**之后**记账，故读状态那一次本身不在快照里；**应用未处理异常**（`response.start` 之前抛错）按客户端实际收到的 500 归 `5xx` 桶、访问日志记 `outcome=unhandled_exception`（Story 71.1 / 71.2 / 71.3 / 71.4 / 71.5） |
| 事件与投影 | 事件类型 `text` / `tool_call` / `tool_result` / `done` / `error` / `cancelled` / `timed_out`；`id` 从 1 单调递增、`data` 是单行 JSON；文本字段入缓冲前截断到 16384 字符并显式标记；`done` 带**该次运行**的 model 与 usage。会话投影只有一条路径：仅 `COMPLETED` 的 run 投影 prompt + 最终回答，失败 / 取消 / 超时**绝不**把部分文本写进历史（AD-3）；运行记录按 `HTTP_RUN_HISTORY_SIZE` 保留，**只淘汰终态记录**（在途运行必须始终可按 id 取消 / 订阅，全部在途时宁可暂时超出上限——否则记录凭空消失而它仍占着名额），淘汰后按 id 订阅得 `unknown_run` |
| 取消、重连与终态 | 终态转换**首个获胜**（AD-10）：完成 / `DELETE` / 运行超时 / 关停竞争时只产生一个终态事件，名额在 done callback 里归还（**含「任务未被调度就被取消」的病态路径**——那时协程体不执行，靠 callback 兜底补写 `cancelled`）。`Last-Event-ID: N` 只重放**严格大于** N 的事件；游标早于缓冲窗口（`N < oldest_seq - 1`）返回 409 `resync_required`（不发看似连续的流），客户端据此拉 `/api/session` 快照；空闲流每 15 秒发一条 SSE 注释心跳（`yield None` → `: ping`，不占 ID）。重放与水位去重语义**单源** `http_protocol.replay_then_follow`（A54④：WS 与 SSE 曾各抄一份；2026-11-15 起 WS 侧终态判定也按快照时刻捕获，与 AD-4「终态事件先于流结束」对齐）。**断线只释放订阅者、绝不取消运行**（取消只能走 `DELETE`）。订阅者队列与事件窗口**同界**：消费端被背压卡住（客户端不读）时**结束该订阅者的流**（客户端带游标重连 → ring buffer 补齐或 409 重新同步），既不无限堆积内存、也不静默跳过事件（2026-09-23 评审修复）|
| 限额与超时 | **三条时限都面向「卡死」而非「跑得久」**（2026-09-24 修复，2026-09-27 补第三条）：`HTTP_IDLE_TIMEOUT`（默认 300s）是**静默**上限——既没有新事件、也没有在途工具（`tool_call` 已发、`tool_result` 未到）时才计时，到点按 `timed_out` 终结，文案 `run stalled: no activity for Ns`；`HTTP_REQUEST_TIMEOUT`（默认 **0 = 不限制**）是运维显式设的**总时长**硬上限，文案 `run exceeded the configured time limit (Ns)`；`HTTP_TOOL_INFLIGHT_TIMEOUT`（默认 **3600s**）是**单个在途工具**的最长在途时间——只数「有没有在途工具」会让永不返回的工具把在途名额无界占住，文案 `run stalled: a tool has been in flight for over Ns`（**刻意不复用** `http_idle_timeout`：长 shell / 子代理期间同样没有事件，用静默阈值会误杀正常长调用，既有用例 `test_in_flight_tool_stretches_the_idle_window` 钉住）。旧实现把 300s **墙钟**当默认，长任务（多轮工具 / 子代理 / goal 工作流）会被误杀成 `timed_out`。时限由看门狗任务以「取消运行任务」实现 ⇒ **超时是协作式的**：executor 吞掉 `CancelledError` 时时限并未生效——终态按实际结果走，但服务端记 `event=timeout_ignored`（带 `reason=idle|tool|hard`）；运行内部（provider / 网络）自己抛的 `TimeoutError` 按 **failed** 归因，不谎报「超过配置时限」。三个时限都可设 0 关闭（全关时看门狗根本不启动）。归因**看谁发的取消**：用户 `DELETE` 优先于看门狗，且 `deadline_reason` **一次性消费**——否则 executor 吞掉看门狗那次取消后，之后的 `DELETE` 会被误记成 `timed_out` 并吞掉取消（2026-09-27 修复）。在途运行数 `HTTP_MAX_INFLIGHT_RUNS`（**每项目**各计一份，非等待式，满即 409 ⇒ 全局同时刻上限 = 项目数 × 该值，默认最多 32；2026-09-24 评审校正：原写「全局上限」）。可选的 `HTTP_MAX_TOTAL_INFLIGHT`（默认 **0 = 不限**）另设**服务级**总额、跨项目共享，两类上限**同时**生效、先撞谁按谁拒（超限 ⇒ 409 `total_inflight_limit`；2026-09-27 新增，D9 的按项目语义逐字不变）；客户端连接数上限交给 Uvicorn `limit_concurrency`（超额连接在**进 ASGI 之前**被拒），每 run 的 **SSE 订阅者**上限是**独立旋钮** `HTTP_MAX_SUBSCRIBERS`（默认 **16**，与连接额度同值 ⇒ 默认行为不变；2026-09-28 从 `HTTP_MAX_CONNECTIONS` 拆出——此前两者复用同一个键，超额订阅只能由 Uvicorn 在 ASGI 之前拒，客户端拿裸 `text/plain` 503、本入口的 429 `rate_limited` 分支**实际不可达**）；订阅者限额的**检查与登记在同一步完成**（`_RunRecord.try_add_subscriber`）——旧实现「先查后加」拆在端点与生成器两处，并发 `GET .../events` 能一起穿过限额（2026-09-27 修复）|
| 运行隔离 | 入口层 `cli.http_console.HttpAgentHandler`：**每次运行新建独立 `AgentLoop`**（loop 持跨 run 可变展示态），handler 自建 engine（`approval_handler=None` ⇒ 需要审批的调用维持既有 fail-safe 阻断，**绝不**读服务进程 stdin）、不自动连接 MCP；传输层只认注入的可调用对象，不认识 `AgentLoop`（AD-1 的接缝）；**绑定完整 cron 工具面**（`enable_cron=True`，2026-10-28 用户裁决改判）——网页会话与交互模式共用同一份 `<项目>/.heagent/cron/jobs.json`，`cron_add` / `cron_list` / `cron_remove` 全部可用；handler **不启动**后台调度（`_build_loop` 顺带构造的 `CronScheduler` 被丢弃——构造只赋值字段、不建 task；start/stop 属**进程级**生命周期：`cli/interactive.py`、`gui/app.py`），因此网页写的任务在本进程 IDLE 不触发，由交互模式 / GUI 的调度器执行；跨进程同分钟重复执行由 `engine` ledger 的幂等键与租约兜底（`cron:{job_id}:{分钟}`，落 `.heagent/ledger/`）。原 A11② 形态（`enable_cron=False` 时连 `JobStore` 都不构造、见到已绑 cron 的 loop 即显式失败）**已撤销**（2026-09-27 修复 → 2026-10-28 改判） |
| 来源校验 | 同源防线（AD-6；边界地位见 §4.18）：所有请求必须带**唯一**且匹配本 listener 的 `Host`（规范化小写、http 默认端口省略；**回环绑定时**接受 `127.0.0.1` / `localhost` / `[::1]` 三个等价写法，非回环只认配置的那个名字）；带 `Origin` 时必须等于 `http://<该 authority>`（拒绝 `null` 与跨站）；重复 `Host` 与任何 `forwarded` / `x-forwarded-*` / `x-real-ip` 头一律 403 `origin_forbidden`（**不信任代理**，Uvicorn 侧也已 `proxy_headers=False`）。被拒的**状态变更不产生任何副作用**（提交不建 run、取消不动 run，有测试钉住） |
| 可观测性 | 每条请求一条日志（`event=request`：不透明 `request_id` / method / path / status / `elapsed_ms`），并在响应头回 `x-request-id`；每次运行在启动与终态各一条（`event=run_started` / `event=run_finished`：`run_id` / status / `elapsed_ms`）。**日志不含** prompt、回答或工具输出正文（工具名与作用对象仍会出现——那是既有引擎 `LoggingObserver` 的行为，与 CLI/GUI 一致）；入口层插桩经 `_safe_log`，日志设施故障不影响协议行为；运行失败额外记一条 `event=run_failed`（含 traceback）——运行是后台任务，异常不会走 Uvicorn 的 traceback 通道，不记就等于丢掉真实缺陷的栈（2026-09-23 评审修复）|

⚠ **安全立场**：本入口与 WS listener（4.16.1）同属入口面，边界地位见 §4.18；运行本入口
须放在容器 / VM 等 OS 级隔离中（缺口见五、已知缺口）。

## 4.16.1 WebSocket 入口（Epic 54；Epic 56 迁至独立 server）

**独立 listener**（Epic 56 D1）：`WsServer` 自建 ASGI app，**零 HTTP 路由**（控制台页 / 静态资源 /
REST / 健康检查一律 404），默认 `127.0.0.1:9201`，配置面为 `WS_HOST` / `WS_PORT` /
`WS_MAX_CONNECTIONS` / `WS_SHUTDOWN_TIMEOUT` / `WS_CLI_BYPASS_ENABLED` / `WS_TLS_CERT_FILE` /
`WS_TLS_KEY_FILE` / `WS_LAN_NO_AUTH`（HTTP 侧不再有 `HTTP_WS_*` 旋钮）。**第二 listener（期二 D8 的
`WS_EXTERNAL_*` 一族）已于 Epic 72 退役**：非回环入口只剩这一条 listener，按
`WS_LAN_NO_AUTH` 分 `lan`（内网免认证）/ `external`（强制 Bearer）两档，见下方「监听模式（三档）」行。
**端口 8766 → 9001 是 Epic 56 的唯一 breaking change**（默认值 2026-10-29 起为 9901、2026-11-04 起为 9201）：三条既有端点路径不变，客户端只需改端口（Epic 58 另新增第四条：通知流）。
四条端点共用 listener；**非回环（`lan` / `external`）listener 上除 CLI 旁路外都在**：

| 端点 | 作用 | `local`（回环） | `lan` / `external`（非回环） |
| --- | --- | --- | --- |
| `WS /api/runs/ws` | **集合级**：经 WS 提交 run（Epic 56 D2 新增；见下表「提交 run」行） | ✅ | ✅（`external` 在 token 后） |
| `WS /api/runs/{run_id}/ws` | 单 run 订阅 + `{cancel, cancel_run, ping}`（Epic 54；`cancel_run` 为 Epic 75 补充） | ✅ | ✅（`external` 在 token 后） |
| `WS /api/cli/ws` | CLI 旁路只读事件流（Epic 55，默认关；见「CLI 旁路订阅」） | ✅（开关开时） | ❌ **不注册**（D9） |
| `WS /api/notifications/ws` | 只读通知流：cron 执行结果（Epic 58，默认关；见「只读通知流」） | ✅（中枢注入时） | ✅（中枢注入时；`external` 在 token 后，Epic 58 D2） |

| 关注点 | 实现事实 |
| --- | --- |
| 生命周期与就绪 | `WsServer.start()` / `serve_forever()` / `close()` 三件套口径对齐 `HttpServer`：绑定失败与就绪探测失败都转 `WsStartupError`（命令层给一行可读错误，**绝不**打印「已监听」）。**就绪判据是真实 TCP 连通**——本 server 没有健康端点可打（D1 接缝事实）。`close()` 幂等、全程有界，只做 WS 侧收尾（关订阅连接 + 停 listener），**绝不**取消运行；在途运行的排空归 HTTP `close()`，编排顺序由入口层保证。 |
| 帧契约 | `network/ws_protocol.py` 定义封闭的 `hello` / `event` / `ack` / `error` / `notification` 帧；**`hello` 是连接首帧（56-9，2026-11-06）**：四端点 `accept()` 后、任何配额/游标/关停判定前立即下发 `{"type":"hello","version":…}`——版本由入口层注入（`heagent.__version__`，经 `WsServer → build_ws_app → builders` 参数链），传输层不读包元数据；认证/Origin 拒绝发生在 accept 前，被拒连接不经 hello；hello 不属任何一条流（无 `run_id`/`seq`、不进环形缓冲，续传/游标语义逐字不变），客户端按「可忽略类型」处理（不认识就跳过）；空版本（测试装配形态）端点侧 debug 跳过（不静默）；事件负载嵌套复用 `RunEventPayload`（通知流用 `NotificationPayload`），错误复用 `error_envelope()` 与 `HttpErrorCode`。命令集封闭为 `{run, cancel, cancel_run, ping, projects}` 五值，其中 **`run`（提交）与 `projects`（项目列表）只在集合级端点 `/api/runs/ws` 有效**（单 run 端点、CLI 旁路与通知流收到任一即回 `invalid_request` 且不断连）；`cancel_run` 与 `cancel` 的差别只在目标来源（连接绑定的 run vs 帧内 `run_id`），两者复用同一个 `service.cancel_run()` 端口。**断连口径的唯一例外**：单 run 端点上的 `cancel` / `cancel_run` 命中**已消失的 run** 时回 `unknown_run` 并关闭连接（`WS_CLOSE_POLICY`）——那条连接唯一的目标都不在了，续留没有意义；集合级端点、只读 listener 与只读流上的 `invalid_request` 一律**不断连**。 |
| 事件与续传 | WS 复用 `_RunRecord` 的 ring buffer、单调 `seq`、背压踢除和终态哨兵；`?last_event_id=N` 只补 `seq > N`，越过窗口返回 `resync_required` 错误帧。重放/水位去重与 SSE 同一实现（`http_protocol.replay_then_follow`，A54④）；`resync_required` 判据算术单源 `http_protocol.cursor_out_of_window`（三条流 + WS 共用，A54⑤）；连接登记与有界关停委托 `event_stream_hub.WsRegistry`（与只读流同一实现，A54⑤）。 |
| 命令 | `cancel` 与 `DELETE /api/runs/{run_id}` 使用同一协作式取消语义并保持幂等；`ping` 返回 `ack`。断线只注销 WS 连接，不取消 run。 |
| 提交 run（Epic 56 D2，`WS /api/runs/ws`） | **集合级**端点（路径无 `run_id`；与 `/api/runs/{run_id}/ws` 段数不同，不互相遮蔽）：收 `{"command":"run","prompt":…}` 后**复用** `RunRequest` 校验与 `HttpRunService.start_run` 创建（名额 / 记录 / 任务生成只有一处实现），回 `ack{command:run, run_id, status}`。错误走错误帧且**不断连**：空白 prompt `empty_prompt`、空串/超长 prompt `invalid_request`、名额满 `run_conflict` / 服务级总额 `total_inflight_limit`、关停 `shutting_down`——与 `POST /api/runs` 的状态码语义一一对应。**期一交互形状**：提交连接**不转事件流**，客户端拿 `run_id` 后经既有单 run 端点订阅；该连接上的 `cancel` 回 `invalid_request`（没有绑定对象）、`ping` 回连接级 ack（`run_id` 空串）。**Epic 75 扩展**：帧上加可选 `project_id`（缺省 = 启动工作区，与该字段出现之前的旧路径逐字等价）⇒ 提交到该项目；**Epic 77 扩展**：再加可选 `request_id`（1–64、不 strip）⇒ 入口层适配器在 60s / 256 条内存窗口内对同一 `(project_id, request_id)` 只真正提交一次（在途合流、成功重放、失败不缓存），相同键的两次提交拿到**同一个** `run_id`（TTL 从提交开始计时、在途项不因过期被踢；键**不含 prompt**，同键不同 prompt 重放第一次结果——键是客户端的不透明承诺，服务端不比对载荷）；ack 仍是四格（不回声 `request_id`），窗口随进程重启失效；该键**只在带 `project_id` 的项目径生效**（启动工作区径没有窗口 ⇒ 带键但不带 `project_id` 的帧合法却不去重，两次提交是两个 run），且与 HTTP 可观测性里的 `request_id`（`x-request-id` 追踪 id）**同名不同义**、互不填充；另收 `{"command":"projects"}` 回 `WsProjectsFrame`（每条三字段 + 两值 `registry_state`），见下表「项目通道」行。 |
| 项目通道（Epic 75） | **注入链路**：`build_ws_servers(project_service=…)` → `WsServer.project_service` → `ws_host.build_ws_app` → 两个端点构造器（集合级端点拿实例；单 run 端点收到非 `None` 只记 `ws event=project_service_ignored` debug——它没有项目面）。**适配器只翻译**（`cli/ws_project_adapter.ProjectChannelAdapter`，`ProjectChannelService` 的唯一入口层实现）：列表投影成 `WsProjectsFrame`（每条只留 `id` / `name` / `available`，`path` / `last_opened_at` / `is_default` 不出入口层——它们会把宿主目录结构交给持 token 的对端）+ 两值 `registry_state`；提交收窄成 `SubmittedRun`（`session_id` 不出入口层）；`ConsoleOperationError` / `ProjectRegistryError` 的 `code` **逐字**搬进 `HttpRunConflictError`，不改写、不折叠（漏译让 `ValueError` 直冒，连接骨架收敛成 `server_error`）。适配器**不解析项目目录、不探测目录是否在盘、不读注册表文件**——「传输层与适配器都不认识项目目录」是结构保证，不是纪律要求。**六项落点由编排层保证**（`cli/http_console.HttpProjectConsole.start_project_run` 经 `for_workspace` 派生 per-project 运行时）：`context.workspace_root`（围栏基址）/ 会话文件（`paths.sessions`）/ 产物目录（rollout sink 与围栏同按项目根）/ `engine` 的 run 记录与 ledger / `RunContext.state_root`（默认钉容器根，与前者同源）/ memory 根（`paths.memory_file` 与 profile）。**未注入时**（`project_service=None`）`projects` 与带 `project_id` 的 `run` 回 `project_channel_unavailable`（Epic 77 D2：与「帧字段拼错」的 `invalid_request` 分流——前者重试无用、要换 listener/环境，后者改代码）且不断连，**绝不静默按启动工作区执行**——「装配漏了」不能变成「跑错项目」。错误码：项目侧既有码（`unknown_project` / `invalid_project_path` / `project_unavailable` / `project_busy` / `project_limit_reached`）全部复用，本 epic 只新增 `project_registry_unreadable`（HTTP 500，**仅提交径**产生：适配器提交前先跑一次 `ProjectRegistry.health()` 健康探针（线程池执行，不占事件循环；`project_id="default"` 豁免——它由句柄的启动工作区直接合成、不读注册表，登记表坏了也不该让服务整体不可用），不可读即回该码——注册表读路径是 fail-soft（不可读 ⇒ 空表），不先判就会在下游被译成 `unknown_project`；列表径 fail-soft 走 `registry_state="unreadable"` + 一条 WARNING）⇒ `HttpErrorCode` 总数 35 → **36**；Epic 77 再增 `project_channel_unavailable`（WS 专用、无固定 HTTP 状态）⇒ 36 → **37**。**提交上界（2026-11-26）**：端口签名不带 `timeout`（契约钉死），上界住实现方构造期 `submit_timeout`（默认 **30s**，`DEFAULT_SUBMIT_TIMEOUT_SECONDS`），`_submit` 与 `ensure_available` 的控制台调用各包一层 `wait_for`；超时抛 `HttpRunConflictError(code=timeout)`——**复用既有码、不扩张客户端码集**，文案明写 `outcome unknown`（run 可能已建起来，`wait_for` 取消了协程但没有回滚语义），客户端重试时若同项目已被占用会先撞 `run_conflict`。**客户端对接口径（N3）**：`project_id` 随路径派生（`p` + 路径 sha256 前 8 位）⇒ **目录移动 / 改名即换 id**，旧 id 立刻变 `unknown_project`；客户端把它当临时标识，收到 `unknown_project` 就重拉列表让用户重选（已安装的 Android 客户端改目录后需重新选择项目），不要用同一 id 重试。 |
| 同源防线 | WS 升级在 `accept()` 前复用 `_request_origin_violation` 校验 Host/Origin（**仅本地模式**；对外模式的 Host/Origin 不适用，见监听模式/认证两行）。Origin 违规时客户端看到 HTTP 403、无错误 body；缺少 Origin 的非浏览器客户端按既有 HTTP 口径放行。既有 ASGI 中间件对 `scope["type"] != "http"` 直接放行，因此 CSWSH 防线由 WS 层单独执行。 |
| 限额与心跳 | `WS_MAX_CONNECTIONS` 默认 `16`，按 run 独立于 SSE 订阅池；检查与登记在同一同步方法完成。心跳使用协议级 ping，`ws_ping_interval=15s`、`ws_ping_timeout=20s`，不发送应用层心跳帧。提交端点**不占**订阅名额（它不订阅事件、不建 run 记录）。 |
| 入站上界 | 三条上限（Epic 56 Story 56-3 起）：`WS_MAX_COMMAND_CHARS=4096`（**非 run** 帧的字符上限）、`WS_MAX_INBOUND_CHARS=6×MAX_PROMPT_CHARS+信封余量`（入站文本的廉价预检——按 `ensure_ascii` 最坏转义推算，否则合法的最大 prompt 会被挡在协议层外）、`WS_MAX_FRAME_BYTES=MAX_REQUEST_BYTES_FOR_MAX_PROMPT`（Uvicorn `ws_max_size`，与 HTTP 请求体上限同源）。应用层超限关闭码 `1009`。关闭码 `1000` 正常结束、`1001` 服务关停、`1008` 策略/协议违规、`1011` 内部错误。 |
| 可选依赖 | `websockets>=13.0,<18` 直接声明在 `http` extra；服务端不直接导入 `websockets`，由 Uvicorn 选择协议实现。缺少实现时 HTTP 仍可启动、记录一次 `ws_unavailable` 安装诊断，且 WS 升级回 **404**（可执行判据：`tests/network/test_ws_missing_dependency.py`，子进程阻断 import + 裸 socket 探测）。 |
| 监听模式（三档） | 唯一 listener 按**绑定地址 + `WS_LAN_NO_AUTH`** 切档（Epic 56 D5 + Epic 72）：① 回环 = `local`（Origin/Host 防线、无认证、Epic 54/55 语义逐字保持）；② 非回环 + `WS_LAN_NO_AUTH=true` = `lan`（**内网调试入口**：无认证、无 TLS，Origin/Host 防线**保留**——无 `Origin` 的非浏览器客户端照放行、`Host` 必须等于绑定地址；三条准入 fail-loud：只接受私有地址字面量（通配 / 公网 / 主机名拒绝）、不得与 `WS_LOCAL_AUTH_ENABLED` 同开、回环绑定上开了无意义；每次启动一条 `ws event=exposed listener=lan auth=none` WARNING）；③ 其余非回环 = `external`（Host/Origin **不适用**——客户端用任意主机名连本 listener，`Host` 白名单会把它全拒掉；该 listener 的前门是 token 认证）。**2026-11-04 D5 修订**：回环 listener 可经 `WS_LOCAL_AUTH_ENABLED=true` **也**强制 token——开关打开时该 listener 的前门从 Origin/Host 换成 token（与对外档同一防线替换逻辑：浏览器 WS API 无法自定义请求头，token 门天然挡浏览器直连），端点集不变（旁路照挂、一并强制 token）。三档的边界地位见 §4.18。 |
| 只读旁观（`WsServerConfig.readonly`，默认关；Epic 72 起无入口层配置键） | `WsServerConfig.readonly` 为真时该 listener **不注册**提交端点 `/api/runs/ws`（提交能力不给，连「试一下拿 `run_conflict`」的机会都没有），`projects` 命令**同样不可达**（它只在同一条集合级端点上；Epic 77 把架构 AD-8 的「只读 listener 上 `projects` 允许」改成与实现一致，端到端仍零能力面），已订阅连接上的 `cancel` 回 `invalid_request` 且**不断连**（事件流照常、运行不受影响），`ping` 正常。用「不支持」而不是「静默忽略」——客户端必须知道它连的是观众席。原 `WS_EXTERNAL_READONLY` / `--ws-external-readonly` 随第二 listener 退役，该字段只供程序化装配与测试；判据 `tests/network/test_ws_e2e.py` 的只读 listener 用例 + 架构契约的路由集断言。 |
| 单 listener 装配（Epic 72 取代期二 D8–D14） | `cli/http_config.py::build_ws_servers()` 恒返回 **1 条** listener：`WS_HOST` 绑回环 ⇒ `local`；绑私有 IPv4 + `WS_LAN_NO_AUTH=true` ⇒ `lan`；其余非回环 ⇒ `external`（缺 token 拒绝构造）。**端点可见性由 listener 身份决定**：`/api/cli/ws` 只在 `local` 注册（终端事件可能含文件内容——口径见 §4.18 要素 5），`build_ws_app` 自身再判一次 `mode` 作为纵深（即使调用方误传 `cli_hub` 也不注册）；`lan` / `external` 上旁路跳过并打 `ws event=cli_bypass_skipped reason=non_loopback_listener` WARNING。**启动告警族**（都只喊不停，Epic 76）：`ws event=tls_identity`（到期余量 / SAN 不含绑定地址，各一条）、`ws event=external_without_sandbox listener=external sandbox=<backend>` 与 `ws event=lan_without_sandbox listener=lan sandbox=<backend>`（接受远程提交的档位且**启动期实际生效**的沙箱后端不是 `docker` ⇒ 各恰一条、锚点分开，判据取引擎构造期定下的 `effective_backend` 而非请求值；`lan` 单独一条是因为它没有 token 这层，同网段任何设备都能驱使代理）、`ws event=cli_bypass_skipped`（旁路因 listener 身份被跳过）。启动顺序 HTTP → WS（失败回滚已启动的全部），关停 HTTP 先、WS 后；日志与公告以 `listener=local|lan|external` 区分。**退役**：`WS_EXTERNAL_*` 五键、`--ws-external-*` 三选项与 `scripts/setup_ws_external.py` 全部删除（残留键由 `heagent doctor` 的 `doctor.retired_key` 提示）。 |
| 认证（对外模式，Epic 56 D3） | 静态 token 的 `Authorization: Bearer <token>` 在 **`accept()` 之前**校验（`network/ws_auth.py` 是纯逻辑面：严格单头 `Bearer` 解析 + `hmac.compare_digest` 常量时间比较 + 按来源地址的失败滑窗)。失败 `close(1008)`、**不发错误信封**（与 Origin 拒绝同形：真实 Uvicorn 下客户端拿 HTTP 403，无 body）；"缺 token / token 错 / 被限速" 对外不可区分。token 真源是**用户级 `~/.heagent/setting.md` 的 `WS_AUTH_TOKEN`**（`Settings.user_ws_auth_token` 直读该文件）——它**不是** `Settings` 字段，项目 `.env` / 系统环境变量一律不参与（否则仓库作者可预置一个已知 token；写在项目 `.env` 里时命令层启动告警，且配置面板照常把它报成未知键）。非回环绑定缺 token ⇒ 配置构造期 `WsConfigError`（fail-closed，**绝不**降级成「无认证对外」）。凭证只走**握手头**——浏览器 WebSocket API 无法自定义请求头，故对外模式不支持浏览器直连（本机控制台走 HTTP，不受影响）。**2026-11-04 D5 修订**：`WS_LOCAL_AUTH_ENABLED=true` 时回环主 listener 强制同一 token 门（accept 前校验、`close(1008)`、缺 token 构造期拒绝，口径逐字同对外模式），旁路端点**不再免认证**（token 真源与 fail-closed 同上）。 |
| TLS（Epic 56 D4） | `WS_TLS_CERT_FILE` + `WS_TLS_KEY_FILE`（PEM）**要么都给要么都不给**（半配即 `WsConfigError`），配齐则 listener 走 `wss`（uvicorn `ssl_certfile` / `ssl_keyfile`）。对外模式不配 TLS 时启动打 `ws event=plaintext_external` 告警（明文运行必须可见），本地模式配了 TLS 也照常生效。**2026-11-04 D5 修订**：回环 + 强制认证 + 明文 ⇒ 打 `ws event=plaintext_local_auth`（token 在回环明文上传输，本机窃听可读，同样必须可见）。 |
| 安全立场 | 与 4.16 / 4.16.1 同一口径，边界地位见 §4.18（本节只列机制事实）。 |

### TLS 与 pin（信任锚分层；Epic 73 / ADR-004）

客户端信任锚是**服务端身份公钥的 SPKI-SHA256**，不是整张证书。由此得出一条反直觉但刻意的结论：
**改 SAN、改有效期、重新签发 ⇒ pin 不变**；只有轮换身份密钥才会改 pin。

| 层次 | 具体字段 | 重签叶证书会变吗 | 由谁决定 |
| --- | --- | --- | --- |
| 证书外壳 | `serialNumber` / `validity`（notBefore、notAfter）/ `signatureValue` | **会变**（新 serial、新签名） | `openssl x509 -req -days N` |
| 证书扩展 | `extensions.subjectAltName`（SAN：IP / DNS 名单） | **会变**（`issue --san` 增删项） | `_render_leaf_config()`，`cli/tls_cmd.py:279` |
| **公钥** | `tbsCertificate.subjectPublicKeyInfo` | **不会变**（密钥不动则恒定） | `identity.key`（长期身份密钥） |
| pin 判定值 | `SHA-256(SPKI DER)` | **不会变** | `spki_sha256_of_der()`，`network/tls_identity.py:233` |

**服务端如何保证「密钥不动」**

- `heagent tls issue`：`openssl req -new -key identity.key` 只产 CSR，再用 CA 签出新的 `cert.pem`
  （`_issue_leaf()`，`cli/tls_cmd.py:363`）——**从不执行 `genrsa`**。
- listener 加载的 `key.pem` 是 `identity.key` 的字节副本（`_ensure_identity()`，
  `cli/tls_cmd.py:359` 的 `shutil.copyfile`）⇒ `WS_TLS_KEY_FILE` 指向的内容恒等于身份密钥。
- 机器守卫：`issue_leaf_cmd()`（`cli/tls_cmd.py:534`）重签前记 `pin_before`，重签后
  `info.spki_sha256 != pin_before` 直接抛 `TlsCommandError`（「身份密钥未被复用」）⇒ 有人把 `issue`
  改成顺手换密钥时，失败形态是命令非零退出，而不是静默让所有客户端 `pin_mismatch`。
- `heagent tls rotate-key --yes` 是**唯一**改 pin 的动作（重新 `genrsa`），输出新旧两枚 pin 与双 pin
  过渡提示；未带 `--yes` 且非 TTY 时拒绝执行。

**实测对照**（同一把 `identity.key`、同一 CA，只差天数与 SAN；材料在 `.heagent/tmp/pinlab2/` 可复现）

| 判据 | cert-A（1 天 / 2 项 SAN） | cert-B（30 天 / 4 项 SAN） |
| --- | --- | --- |
| serial | `2B1F…2CEB` | `2B1F…2CEC` |
| notAfter | `Nov 27 01:15:23 2026 GMT` | `Dec 26 01:15:23 2026 GMT` |
| SAN | `192.168.2.226`、`localhost` | 上述两项 + `5.tcp.cpolar.cn` + `99.tcp.vip.cpolar.cn` |
| 整证书 DER SHA-256 | `bb35d3f4…8c44`（变） | `9c888878…4413`（变） |
| **SPKI SHA-256（pin）** | `247a8b26…fd301` | `247a8b26…fd301`（**不变**） |

同一把密钥的三处对照：`identity.key` 的 SPKI、两张证书里的 SPKI、生产 `cert.pem` 的 SPKI 逐字节相等
（`spki_sha256 = 247a8b26…fd301`、`pin = sha256/JHqLJ…UP0wE=`、短指纹 `ER5I-WJUT-A7JP`）。

**客户端口径（与 SAN 的关系）**

- 客户端校验三条：SPKI 命中 pin（最多 old + new 两个）、证书未过期、**不校主机名**。身份由 pin 承担
  ⇒ 内网地址漂移、cpolar 域名变更都**不需要重签、不需要重发安装包**。
- 因此启动期的 `ws event=tls_identity`（SAN 不含绑定地址）对**只认 pin 的客户端并不致命**
  （`cli/http_config.py:218`）；它针对的是会校主机名的标准校验路径（`curl`、
  `openssl s_client -verify_hostname`、默认开启主机名校验的第三方库）。该告警只喊不停。
- 三个客户端本地错误码（`pin_mismatch` / `cert_expired` / `cert_unreadable`）服务端**不产生**，
  定义与 UI 要点见 `docs/errors.md` 第四节。

**三个常见误区**

- 用**整张证书**的哈希当 pin ⇒ 30 天到期就得换 pin、每台设备重装一次（ADR-004 要消灭的正是这个）。
- 以为「改了 SAN 要重发安装包」⇒ 不需要；需要重发安装包的只有 `rotate-key`。
- 把**整证书 DER** 传给 `spki_sha256_of_der()` / `short_fingerprint_of_der()` ⇒ **不报错，但算的是另一个
  哈希**（会误判「服务端换了身份密钥」）。手里只有证书时用 `spki_sha256()` / `spki_sha256_base64()`；
  手里只有私钥时用 `key_spki_der()` 再喂 `*_of_der()`。

### CLI 旁路订阅（Epic 55）

`/api/runs/{run_id}/ws` 订阅的是**网页创建的 run**；终端里那一轮 run 由 CLI 自己持有，既没有
`_RunRecord`，也不占 `HTTP_MAX_INFLIGHT_RUNS` 名额。`WS /api/cli/ws` 因此是**另一条流**：只读、
跨轮次、旁路（观众席）而非控制台。

| 关注点 | 实现事实 |
| --- | --- |
| 状态源 | `network/cli_event_hub.py::CliEventHub`：seq 跨轮次单调、环形缓冲 `CLI_EVENT_BUFFER_SIZE`(256)、订阅席位上限（取 `WS_MAX_CONNECTIONS`，按**整条流**计）、`close()` / `reopen()` 与 `HttpRunService` 同形态。**不建 run 记录**，因此不存在"淘汰 / 会话投影 / 取消"这些 HTTP 侧的语义。 |
| 帧契约 | `WsCliEventFrame`（`type` + **`run_id`** + `event`）与 `WsCliAckFrame`（`command` + `run_id`，**不带** `RunStatus`）。与 `WsEventFrame` / `WsAckFrame` 分开定义 ⇒ `/api/runs/{id}/ws` 的既有契约逐字不变。 |
| 命令面 | 仅 `ping`（回 ack，`run_id` 为空串表示此刻没有在跑的轮次）。`cancel` 回 `invalid_request` 错误帧但**不关闭连接**——旁路不拥有运行，「不支持」必须显式告知，不能静默忽略。`run`（提交）与 `projects`（项目列表）同理拒绝：两者都只在集合级端点 `/api/runs/ws` 有效（Epic 56 D2 / Epic 75 的边界：旁路是观众席，不是生产通道）。 |
| 续传与背压 | `?last_event_id=N` 只补 `seq > N`；窗口已淘汰开头（含「无游标但 `oldest_seq > 1`」）回 `resync_required` 错误帧。订阅队列与缓冲同界，落后一整窗口即结束该流（客户端带游标重连）——与 SSE / run-WS 同一口径。 |
| 发布点 | 入口层 `cli/interactive.py`：`_consume_stream` 逐条镜像 `StreamEvent`（text / tool_call / tool_result / done），进入即 `begin_run`、退出（含取消与异常）即 `end_run`；单次模式走非流式 `loop.run`，只发一条终态 `done`，**不假装有增量**。中枢经 `ContextVar` 传递（`_run_prompt` 的签名是 3 处测试 patch 的契约，不能加参数）。 |
| 故障隔离 | 中枢 `publish_*` 自身不抛；入口层 `_hub_call` 是第二道垫片——旁路坏了最坏只是「外部看不到」，终端输出 / 退出码 / 主循环状态逐字不变。 |
| 装配 | `cli/http_config.py::build_ws_servers` 在 `WS_CLI_BYPASS_ENABLED` 为真时建 hub 并注入**本地 listener**（Epic 56 D7 起宿主 = WS server，9201；期二 D9：对外 listener 恒不注入，且 `build_ws_app` 再判一次 `mode`）；未注入 ⇒ 路由不注册（Uvicorn 在「应用未 accept」时给客户端裸 403，不是应用层 404）。主 listener 本身是对外模式（期一单对外）⇒ 旁路被**跳过**并打 `ws event=cli_bypass_skipped reason=external_listener`。开启时 stderr 打一行 `[ws] CLI event stream (read-only): ws://…/api/cli/ws`，避免「开了但不知道在哪」。 |
| 同源防线 | 与 run-WS 共用 `_request_origin_violation`（accept 前校验，违规 close ⇒ 客户端拿 403）。既有 ASGI 中间件对非 `http` scope 放行，故 CSWSH 防线由 WS 层单独执行。 |
| 安全立场 | 与其它三条端点同一口径，边界地位见 §4.18；默认关，需要时显式开。 |

判据：`tests/network/test_cli_event_hub.py`（15 例：seq / 窗口 / 限额 / 背压 / 关停）、
`tests/network/test_cli_ws_e2e.py`（13 例：真实 TCP + 真 websockets 客户端）、
`tests/test_cli_ws_publish.py`（8 例：逐类镜像 / 取消与报错收尾 / 故障隔离）、
`tests/test_cli_ws_wiring.py`（5 例：装配与 ContextVar 接线）。Epic 58 起 seq / 缓冲 / 游标 / 背压 /
关停的**唯一实现**在 `network/event_stream_hub.py::EventStreamHub`，`CliEventHub` 是其薄适配
（本组既有判据是那次重构的验收线：文件内容零改动）。

### 只读通知流（Epic 58）

cron 作业由后台调度器跑（`cron/scheduler.py`），一轮执行只有一个终局答案：它不是「一条 run」
（无 run 记录、无状态机、无取消），也不是「终端观众席」（旁路按 D9 永不出网）。因此单开一条只读流
`WS /api/notifications/ws`：宿主 cron 的产物**主动推送**给已连接客户端。

| 关注点 | 实现事实 |
| --- | --- |
| 状态源 | `network/notification_hub.py::NotificationHub`（`EventStreamHub[NotificationPayload]` 薄适配）：seq **跨作业跨执行单调**、环形缓冲 256、订阅席位上限取 `WS_MAX_CONNECTIONS`（按整条流计）、`close()` / `reopen()` 与旁路同形态。 |
| 帧契约 | `WsNotificationFrame`（`type=notification` + `notification`）；载荷 `NotificationPayload`：`kind`（`cron_result`）/ `seq` / `job_id` / `cron`（表达式）/ `status`（`completed` / `failed`）/ `text`（终局答案或错误首行，入缓冲前 `clip_text`）。**不带** `run_id`、不带 `RunStatus`——客户端按 `job_id` + `seq` 定位，不产生「能订阅/控制一条运行」的错觉。 |
| 命令面 | 仅 `ping`（回 `WsCliAckFrame`，`run_id` 恒为空串）。`cancel` / `cancel_run` / `run` / `projects` 回 `invalid_request` 且**不断连**（只读流没有可取消、可提交或可列项目的对象）。 |
| 续传与背压 | `?last_event_id=N` 只补 `seq > N`；窗口越界（含无游标但 `oldest_seq > 1`）回 `resync_required`。订阅队列与缓冲同界，落后一整窗口即结束该流（同 SSE / run-WS / 旁路）。 |
| 可见性 | 与旁路**刻意不同**（Epic 58 D2）：中枢注入即注册，`local` / `lan` / `external` **都注册**——通知流送的是宿主自己排的 cron 产物，不暴露终端会话内容；`external` 上还有 token（fail-closed），`lan` 上无认证但代价（同网段可见）由启动 WARNING 写明。旁路旁观的「宿主的终端」才必须留在本地。 |
| 装配 | `cli/http_config.py::build_ws_servers` 在 `CRON_PUSH_ENABLED` 为真时建中枢并注入每一条 listener；未注入 ⇒ 路由不注册（Uvicorn 给客户端裸 403，不是应用层 404）。发布点由入口层把 `cron_notifier` 注入 `build_cron_job_runner`（一次执行一条；goal 自动推进分支不发）。 |
| 与终端回显的关系 | 两条路互不依赖：`CRON_PUSH_ENABLED` 管推送，`CRON_ECHO_TO_TERMINAL` 管终端 stderr 单行回显（`[cron <job_id>] …`），四种组合都合法（Epic 58 D4/D6）。 |
| 安全立场 | 与其它三条端点同一口径，边界地位见 §4.18；对外 listener 上意味着宿主 LLM 输出会离开本机。 |

判据：`tests/network/test_event_stream_hub.py`（10 例：通用核 seq / 窗口 / 背压 / 关停）、
`tests/network/test_notification_hub.py`（7 例：载荷 / 跨作业单调 / 文本有界）、
`tests/network/test_notification_ws_e2e.py`（8 例：真实 TCP + 真 websockets 客户端）、
`tests/test_architecture_contracts.py`（端点集封闭契约：多一条端点必须走 story 评审）、
`tests/test_cron_notify.py`（6 例：发布点——最终答案 / 失败首行 + 异常上抛 / goal 分支零通知 / 通知器故障隔离）、
`tests/test_cli_cron_echo.py`（14 例：两开关四组合 + 回显形态 + 装配判据「中枢挂每个 listener、路由随开关注册」）、
`tests/network/test_notification_cron_e2e.py`（2 例：**整链**——真 AgentLoop(stub provider) → runner → notifier → 中枢 → 真实 TCP → 真 websockets 客户端，成功与失败各一条）。

## 4.17 网页控制台 (`pub/workspace.py` + `pub/projects.py` + `config/catalog/` + `config/write.py` + `cli/http.py` + `cli/dialogs.py` + `web/`)

Epic 50 把 4.16 的「单项目聊天页」扩成**多项目控制台**：左栏项目与会话、右栏对话、设置独立成面板
（项目 / 会话 / 配置三层，全部走**项目内**路由）。分层不变——网络层只承载传输与路由，装配 / 注册表 /
会话 / 配置来源求解 / 写入流水线留在入口层 `cli/http.py` 与顶层模块（脊柱 I1：网络层不认识 `Settings`）。

| 关注点 | 实现事实 |
|---|---|
| 工作区模型 | `workspace.WorkspacePaths.from_root(root)` 是运行态路径（sessions / ledger / runs / memory / skills / user / cron / checkpoints / sandboxes / tmp / console / backups）的**唯一**来源；入口层装配期解析一次并注入 engine 与主 / cron loop，不在每次请求时重读 cwd |
| 项目注册表 | `pub/projects.py`：`<服务启动工作区>/.heagent/console/projects.json`（可用 `HTTP_CONSOLE_PROJECTS_FILE` 覆盖；**默认不写用户 home**）。条目上限 **32**（含 `default`，可登记 **31** 条；文件被手改成 32 条登记判整表不可读 —— 否则 `list()` 会回 33 条撞上响应模型的 32 上限）；id 不透明（`p` + 8 位十六进制，由路径规范化派生）；**写侧 fail-closed**（内容无法解析时拒绝改写，绝不回写空表）；目录失效不删登记而是标 `available=false` |
| 会话持久化 | `context/session.py` 的 `SessionStore` 按项目派生（`<项目根>/.heagent/sessions/<sid>.json`），与 CLI **同库同格式**；列表只读轻量元数据（D6）；**损坏文件回 `session_unreadable`**（D1），绝不当空会话覆盖。**并发写不再整份覆盖**（2026-09-27 修，见 4.5）：运行落盘带**内容基线** `base=`，别的写者追加过的消息会被保守合并（两段都保留），判不出来则退回 last-write-wins + WARNING |
| 配置来源求解（只读面） | `config/catalog/report.py::build_config_report`：四层来源 **系统环境变量 > 项目 `.env` > 用户 `~/.heagent/setting.md` > 字段默认值**，逐项给出有效值 / 来源徽标 / 可写性 / 只读原因；凭证只回「已配置 + 定长掩码」（**掩码域 = `*_API_KEY` / `*_API_KEYS` 后缀**；`*_BASE_URL` 等键的值**原样回传**——凭证写在 URL userinfo 里不会被打码，见台账同名条目）；行级诊断（重复键 / 空值键 / 行内注释 / BOM / 未知键）逐条标注 |
| 可写面划分（D2/D3） | 实测 **115 字段 = 白名单 48 + 排除 67、残留 0**（2026-10-24 复测；上一版记录的 109/61 在本次测量前已滞后 5 个字段）；优先级 **显式白名单 > 模式排除**，排除之间**显式行 > 模式行**（`HTTP_CONSOLE_*` 因此归「控制台自身」而非「监听面」） |
| 配置写入通道 | `config/write.apply_config_write`：**10 步 + 1 项生效语义** —— 闸门 → 回环来源 → 键白名单 → 值守卫 → 指纹 → 候选构造（`Settings(_env_file=候选)` 必须能构造）→ 备份 → 保真写 → 回读 → 审计；第 11 项 = 让该项目运行时缓存失效。**回环判定留在传输层**（网络层不认识 Settings），`envfile.py` 做行级保真（**只重写值区**：EOL / BOM / 注释 / 未修改行字节逐一不变），`pub/persist.atomic_update_bytes` 做字节级原子写 + **锁内**回读校验与回滚。**跨进程锁内只做「指纹判定 + 备份 + 落盘」**（2026-09-27 收窄，台账 A14③）：候选构造（候选构造经 `with_user_setting_layer` 注入用户层 md + 读候选临时文件 + 环境，是整条流水线最贵的一步）与**备份目录回收**都移到锁外；锁外用文件快照构造的候选会在锁内**复检内容基线**，快照过期（含「改走又改回」这种病态形态）则在锁内重做一次，绝不把基于旧内容的候选写下去。回收失败只告警（维护动作），不把已经落盘的写改写成错误——**回滚本身失败**时抛 `persist.RollbackFailedError`（`__cause__` = 原回读异常，`rollback_error` = 回滚失败原因），写通道据此给出如实文案（不再无条件宣称「已回滚」）并落 `rollback_failed` 审计（2026-09-27 修，台账 A14②）。⚠ **副作用**：锁文件与目标**同目录**（`<项目根>/.env.lock`），即写一次项目配置就在**用户的项目根**留下一个锁文件——HeAgent 自己的仓库有 `.gitignore` 条目，用户的项目没有；锁的落点语义不改（改落点会破坏「同一把锁贯穿读改写」），故这里只作说明（台账同名条目记录） |
| 资源旋钮上界 | `config/catalog/guards.py::RESOURCE_CEILINGS`：21 个「只有下界」的数值键按族给上界（days 3650 / seconds 604800 / bytes 8 MiB / tokens 1M / count 100；迭代 10000 与上下文窗口 16M 自成刻度）。**只作用于写通道与面板展示**，不改 `Settings` 定义语义（手工改 `.env` 不受约束）。**同一常量还是「高影响键」的事实源**（2026-09-27，台账 A13）：`impact_for(key)` → 配置项的 `impact` 字段（`high` / `normal`），面板据此挂徽标并在写入确认框里点名 —— 文案取自后端 `labels`，**前端零硬编码键名**（UX-DR3 的差异化确认） |
| 生效语义 | 写成功后**丢该项目运行时缓存** ⇒ 下一次 run 重新解析快照、**在途 run 继续用旧快照**（无热生效；响应里 `applied=next_run`） |
| 审计 | `<项目根>/.heagent/console/audit.jsonl`：一行一 JSON，只有键名 / 值的**哈希与长度** / 结果（`applied` / `rolled_back` / `rollback_failed`——后两者分别表示「回读不符但已还原」与「回读不符**且还原也失败**」，2026-09-27 补），**不含值**；行数上限 500（超限裁到最近 500 条，且只认这一个文件名 ⇒ 不碰同目录的 `projects.json`）；追加失败不阻断已成功的写，但响应如实带 `audit_recorded=false` |
| 路由 | 项目 `GET/POST/PATCH/DELETE /api/projects*`；会话 `…/sessions*`；项目内运行 `POST /api/projects/{id}/runs`；配置 `GET/PUT /api/projects/{id}/config`；原生目录选择 `POST /api/dialogs/pick-directory`（Story 50-8，**非项目作用域**）；运行事件与取消沿用 4.16 的 `GET /api/runs/{id}/events`（SSE）与 `DELETE /api/runs/{id}` |
| 原生目录选择（Story 50-8 R2） | `cli/dialogs.py`：浏览器**拿不到**本机绝对路径，故「选文件夹」由**服务端所在机器**弹原生窗口。后端顺序 `tkinter` → `powershell`（PS 5.1 `FolderBrowserDialog`）→ `none`（`--dialog-backend` 可钉死，**默认 `none` = 禁用**，2026-09-27 裁定），对话框跑在**子进程**里（`asyncio.create_subprocess_exec` + 冻结 argv + 超时 300s + kill + 有界回收 + 凭证剥离 env），只解析 stdout 的 ASCII 标记行并复验 `is_dir()`（脏值 / 取消 / 超时一律 `cancelled=true`）；入口层持有**单在途**（并发 → `dialog_busy`）。返回值**不是权限**：登记仍走 `POST /api/projects` 的全套校验 |
| 网页 cron 能力（2026-10-28，用户裁决改判） | `HttpAgentHandler.new_loop()` 以 `enable_cron=True` 组装：网页会话与交互模式 / GUI 共用同一份 `<项目>/.heagent/cron/jobs.json`，`cron_add` / `cron_list` / `cron_remove` 全部可用（原 A11② 的「不绑 cron 工具」形态**撤销**；此前网页侧一律回 `Error: cron tools not configured.`）。**handler 不启停调度器**：`_build_loop` 在有会话时顺带构造的 `CronScheduler` 被丢弃（构造只赋值字段、不建 task，无泄漏），start/stop 属进程级生命周期（`cli/interactive.py`、`gui/app.py`）⇒ 网页写的任务在本进程不触发，由那些入口的调度器执行；网页进程若也要自己跑调度，应挂 `EmbeddedHttpService` 生命周期，**不能**按 run 启停。同分钟跨进程重复执行由 `engine` ledger 的幂等键 + 租约兜底（`cron:{job_id}:{分钟}`，落 `.heagent/ledger/`）。⚠ 代价：绑定的是**可写** store ⇒ 端口可达者能增删该项目的定时任务（无认证、回环亦不可信）。判据：`tests/test_cli_http.py::test_new_loop_binds_the_full_cron_surface`（`enable_cron=True` 接线 + 同一 `jobs.json` 可见性 + 丢弃 scheduler 不抛） |
| 网页侧工具结果收敛（Story 50-8 R5；2026-09-28 扩到 `content_search` / `file_edit`） | `cli.http_console._web_tool_output`：**两类收敛**——① `file_read` / `file_edit` 的**成功**结果内容**整份**不进网页事件流（前者是文件正文、后者是 `OK: edited …` + diff + 快照，对话区只显示「工具名 → 作用对象」）；② `content_search` 的成功结果**只留去重的命中文件清单**（`_matched_files` 剥掉 `路径:行号: 正文` 的行内容，保序去重）。**失败消息照旧**（内置工具用返回值 `Error: ...` 表达可预期失败，故判据 = `is_error` **或** 该前缀；无命中消息与超大文件跳过行同属诊断，**原样保留**）；会话文件 / `rollout.jsonl` / CLI / GUI **一字不变**（审计与回放不受影响），模型侧也照旧拿到全文 |
| 控制台体验约束（Story 50-8 R1/R3/R4/R6/R7/R8） | 会话列表**默认只渲染最近 10 条**（服务端仍按时间降序给全量、硬上限 200；展开是本地 slice，且**当前会话永远可见**——落在窗口外时自动展开并隐藏展开按钮），规模提示与「显示全部」放在**会话面板最上面**（列表之上，R8）；侧栏**一列**：项目在上、会话在下（`display:flex`/`column`，**用户 2026-09-24 裁决，不得回退成多栏**）；对话区**占满所在列**（R7，2026-09-24 撤销 R6 的 48rem 限宽居中阅读列：`.chat-log > *` 与 `.composer > *` 只留 `width:100%`；设置面板打开时**对话列仍是三列里最宽的**）；侧栏 280px；设置面板只留**一行短状态**与逐项短只读标签，诊断 / 未知键折进默认收起的 `<details>`（标题带告警条数），逐项长说明压成徽标 + `title` |
| 错误码 | 传输层 `HttpErrorCode` 封闭 **37** 码，分组：项目注册表 8 / 会话 5 / 写通道 5 / 运行与边界 2（`confirm_required`、`loopback_required`）/ 原生目录选择 2（`dialog_unavailable`（503）、`dialog_busy`（409））/ 服务级在途总额 1（`total_inflight_limit`（409）），其余 14 为 Epic 49 基础运行码（Epic 75 加 `project_registry_unreadable`（500，仅提交径）；Epic 77 加 `project_channel_unavailable`（WS 专用、无固定 HTTP 状态）；Epic 74 未新增码）。口径与实测方法：对 Epic 50 开工前提交做成员名 diff，不靠人工计数 |
| 框架异常码 | `pub/exceptions.py` 每个异常类带 `code`（形态 `E_<分类>_<具体>`，**只增不复用**），`error_catalog()` 给出码 → 类名 / 描述 / 建议，`error_code_of(exc)` 对非框架异常返回 `E_UNKNOWN`；当前 **29** 类，码表与 `docs/errors.md` 第二节逐条一致（`tests/test_exceptions.py` 钉死）。与传输层码是两套封闭集合，刻意不合并（Epic 69 / Story 69.3） |
| 前端纪律 | 纯文本渲染（`createTextNode`，永不 `innerHTML`）；面板文案 / 只读原因 / 取值提示全部由后端 `labels` / `guards` / `source` 派生，**前端零硬编码**；零第三方资源、零内联脚本 / 事件属性；`[hidden]{display:none!important}` 全局兜底（作者样式的 `display:flex` 会压过 UA 的 `[hidden]`） |

⚠ **安全立场**（与 4.16 同一口径，边界地位见 §4.18）：绑定告警（`network.exposure`，判定单点）与写通道
/ 项目登记 / 项目移除的**回环门**都只是 defense-in-depth——回环门**防不住「本机浏览器发起的跨站写入」**，
同源防线是 4.16 的 `Origin` / `Host` 校验。写通道默认关闭（`HTTP_CONSOLE_WRITE_ENABLED=false`），
**开启即等于「任何能连上该端口的人都能改项目 `.env`」**（启动时 stderr + 日志双通道告警），且网页
**无法通过任何请求**打开它自己。**并发口径（D9）**：在途上限 = 项目数 × `HTTP_MAX_INFLIGHT_RUNS`
（默认最多 32），**无全局软上限**；需要硬上限时用可选的 `HTTP_MAX_TOTAL_INFLIGHT`（默认 0 = 不限，2026-09-27）。

⚠ **新增的宿主进程拉起面（Story 50-8 R2，边界地位见 §4.18）**：`POST /api/dialogs/pick-directory` 会让
**服务端所在机器**弹出一个原生窗口（子进程 `tkinter` / `powershell`）。防线是「回环来源 + 单在途 + 冻结
argv（无 shell、无用户输入）+ 300s 超时 kill」，但它**不是**「只有本机用户能触发」的保证——这是本 Epic 有意引入的**新暴露面**，已登记在五。
**默认姿态 = 关，两条入口都关**（2026-09-27 裁定，见台账 A19）：`--dialog-backend` 的默认值已由 `auto` 改为
`none`，`HttpProjectConsole.__init__` 的默认值同步改为 `none` ⇒ **默认 CLI 的内嵌服务**（`python -m heagent`
的交互 / 单次模式各起一份）即便不带任何开关也**不会**装出可用的选择器（`POST /api/dialogs/pick-directory` 回
`dialog_unavailable`）；需要时显式传 `--dialog-backend auto`（或 `tkinter` / `powershell`）开启。这与配置写入
通道的既有惯例一致（`HTTP_CONSOLE_WRITE_ENABLED` 默认 **False** —— 新控制台能力默认关）。
（默认值裁定的缘由：实测暴露内嵌路径没有关闭该入口的手段，促成上方默认关闭裁定。）

### 工作区状态路径（Story 50-1）

`WorkspacePaths` 从构造时解析的项目根派生运行状态路径；HTTP 装配与 CLI loop 优先使用已注入 engine 的根，不在每次请求时重读 cwd。GUI 保留 `context_dir=None` 的既有语义。路径围栏仍是 defense-in-depth 层（边界地位见 §4.18）。
