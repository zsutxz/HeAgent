# 完整调用链

> 状态：实现细节参考，自 [`framework.md`](../framework.md) **七 ** 迁出（2026-11-24 整理；编号不变，
> 其它文档里「七、完整调用链」的引用即指本页）。架构视角（项目定位 / 数据流 / 模块 DAG / 各模块职责与边界）见
> [`framework.md`](../framework.md)，安全立场（canonical）见 [§4.18](../framework.md#418-安全口径canonical)，
> 扩展页总索引见 [`frame/README.md`](README.md)。

## 七、完整调用链

```
python -m heagent "your prompt"
  │
  ▼
__main__.py → heagent.cli.console:main()（`heagent.cli` 包的命令组；原 `cli.py`）
  │
  ├── import heagent.tools.builtins → @tool 注册到 ToolRegistry（29 个工具）
  ├── get_settings() → 读取 DEEPSEEK_API_KEY / OPENAI_API_KEY / ANTHROPIC_API_KEY（+ OLLAMA_ENABLED 本地条目）
  ├── _build_provider() → OpenAIProvider（含本地 ollama）/ AnthropicProvider / ProviderChain
  │
  ▼
asyncio.run(_run_single())
  │
  ├── 初始化模块
  │     ├── SkillStore()          → 技能存储
  │     ├── FactStore()           → 事实记忆
  │     ├── ProfileStore()        → 用户画像
  │     ├── SoulStore()           → 人格加载器
  │     ├── ContextCompressor()   → 上下文压缩器
  │     ├── JobStore()            → Cron 任务存储
  │     └── make_retry_middleware() → 重试中间件
  │
  ▼
AgentLoop(provider, skills, facts, profile, compressor, soul, cron_store, ...).run(prompt)
  │
  ├── 构建 Message(USER, prompt) 加入 state.messages
  │
  ├── _build_system() → 按注入顺序构建系统提示词
  │     ├── <identity>            — SOUL.md 人格
  │     ├── 用户 system 字符串
  │     ├── <project-context>     — CONTEXT.md / AGENTS.md / CLAUDE.md
  │     ├── <memory>              — 事实记忆列表
  │     ├── <memory-nudge>        — 记忆保存提醒（紧随 memory）
  │     ├── <profile>             — 用户画像
  │     ├── <shell-workspace>     — 本 run 的 shell 沙箱工作目录（真正生效时；E40-D2）
  │     └── <skills>              — SkillStore.match() 自动匹配 ≤ skill_max_auto_invoke 个
  │
  ▼ 循环开始 ─────────────────────────────
  │
  ├── _call_provider(state)
  │     ├── count_tokens(state.messages)        # Token 估算（日志）
  │     ├── compose([retry_mw], provider.send)  # 中间件链
  │     ├── ProviderResponse(tool_calls=[...])
  │     └── 日志：估算 vs 实际 Token 对比
  │
  ├── 累计 TokenUsage 到 accumulated
  │
  ├── ContextCompressor.check()  # Token ≥ 阈值时压缩旧消息
  │
  ├── 有 tool_calls？
  │     ├── YES → _execute_tools(calls, state)   # asyncio.gather 并行
  │     │         └── _execute_one(call) per call:
  │     │             ├── ledger.acquire()        # 幂等/租约（COMPLETED 短路返回缓存，但 BLOCKED 复核 bypass；lease-active 跳过执行）
  │     │             ├── PolicyEngine.evaluate() # 准入/审批/沙箱裁决
  │     │             ├── ToolExecutor.execute()  # 按 verdict 分发
  │     │             │    └── SafetyGuard.check()# shell 命令模式黑名单（executor 内部串行）
  │     │             ├── handler(**arguments)    # 执行
  │     │             ├── ledger.complete()/fail()# 回写结果
  │     │             └── ToolResult → 追加到 messages
  │     │
  │     └── NO → 返回 response.content（最终答案）
  │
  ├── finally:
  │     ├── SessionStore.save()    # 持久化对话（有 session_id 时）
  │     └── self.last_usage = accumulated
  │
  └── iteration >= max_iterations → BudgetExceeded
  │
  ▼
click.echo(result)
_print_usage(loop.last_usage)  # [tokens: N in + M out = T total]
show_tool_activity(loop)       # [tools] N 次调用尝试：file_read → src/a.py …
```

**交互模式额外流程：**

```
python -m heagent
  │
  ├── _run_chat() 代替 _run_single()
  │     ├── SessionStore() → 生成 session_id
  │     ├── CronScheduler(job_store, provider, ...) → 后台调度
  │     │
  │     ├── scheduler.start()  → 后台 tick 循环
  │     │     └── 每 cron_tick_seconds 秒 → 检查到期 CronJob → 创建独立 AgentLoop 执行
  │     │
  │     └── REPL: while True
  │           ├── input("> ")
  │           ├── loop.run_stream(input, session_id=session_id, system=system)  # 流式 yield StreamEvent
  │           │     └── 命中 tool_calls 时回退 send() 重取该轮调用
  │           └── finally: scheduler.stop()
  │
  └── 一次性 Cron 任务成功后自动从 JobStore 删除
```

**HTTP + WS 双入口流程（Epic 49 HTTP / Epic 54–56 WS；Epic 56 D1 起同进程双 server，期二可加一条对外 WS listener）：**

默认 CLI（`heagent` / `heagent "prompt"` / `heagent run ...`）会**内嵌**启动同一套服务——生命周期
包在 `cli.interactive._embedded_http_service`（`cli.http.EmbeddedHttpService`）里，与 CLI 共享一个
`asyncio.run`：交互模式与 REPL 共存，单次模式与那次 run 并存、run 结束即关闭并释放端口；
`gui` / `http-server` / `init` / `replay` 都不经过该路径（不派生第二实例）。

```
python -m heagent http-server [--host H] [--port P] [--ws-host H] [--ws-port P] ...
  │
  ├── _setup_logging() → get_settings() → _prune_runtime_artifacts()
  ├── load_agent_roles() → cli/wiring._build_provider()          # 服务级共享 provider（规则在 providers/composition，wiring 为呈现薄壳）
  ├── HttpAgentHandler(...)                                   # 每次运行新建 AgentLoop（不装审批、不连 MCP）
  ├── HttpRunService(config, handler)                         # 单用户会话 + 运行记录/事件缓冲的唯一所有者
  ├── HttpServer(config, version=heagent.__version__, run_service=service)
  ├── WsServer(ws_config, run_service=service[, cli_hub=hub])  # D1：独立 listener，零 HTTP 路由
  │     └── ws_config 来自 build_ws_server_config：token 只读用户级 setting.md；
  │           非回环绑定缺 token → WsConfigError（fail-closed）；TLS 半配同判
  ├── exposure_warning(config.host) / exposure_warning(ws_config.host) → 非回环各一行 stderr 告警
  └── asyncio.run(_serve_web(http_server, ws_server))
        ├── await http_server.start()          # 绑定 + 真实请求一次 /api/health
        ├── await ws_server.start()            # 绑定 + 真实 TCP 连通探测（D1：无健康端点可打）；失败回滚 HTTP
        ├── stderr: [http] listening on http://… / [ws] listening on ws(s)://…
        └── gather(http.serve_forever(), ws.serve_forever())
              ├── HTTP listener（9101）：
              │     └── 中间件（由外到内）：安全响应头 → 请求日志（x-request-id）→ 同源防线（Host/Origin）
              │           └── 路由：
              │               ├── GET  /api/health            → HealthResponse（字段封闭，不含密钥/路径/traceback）
              │               ├── POST /api/runs              → 有界非空 prompt ⇒ 201 {run_id,status}；在途 ⇒ 409 run_conflict
              │               │                                    （服务级总额满 ⇒ 409 total_inflight_limit）
              │               │       └── start_run → 后台任务 `_execute` → handler(prompt, publisher) → AgentLoop.run_stream
              │               │             └── 事件映射：text / tool_call / tool_result（seq 单调、文本截断、广播给订阅者）
              │               │                  终态（首个 claim_terminal 获胜）：done（带 model/usage）/ error / cancelled / timed_out
              │               ├── GET  /api/runs/{id}/events  → SSE：按 Last-Event-ID 重放（游标越窗 ⇒ 409 resync_required）
              │               ├── DELETE /api/runs/{id}       → 协作式取消该 run（首个终态获胜；幂等）
              │               ├── GET  /api/session           → 会话 id / 当前状态 / 已完成历史（只有 completed 投影）
              │               ├── GET  /                      → 包内 index.html；GET /{asset} → 白名单资源
              │               └── 每个响应补 CSP / nosniff / 禁 framing；错误一律稳定信封
              │                   （**没有任何 WebSocketRoute**：9101 上的 WS 升级不可达）
              └── WS listener（9201，四条端点；本地模式 Origin 前门 / `WS_LOCAL_AUTH_ENABLED` 时 token 前门 / 对外模式 token 前门）：
                    ├── WS /api/runs/ws               → {"command":"run","prompt":…} ⇒ ack{run_id,status}
                    │                                    （名额判定/记录/任务生成复用 HttpRunService.start_run；
                    │                                      错误帧 run_conflict / total_inflight_limit / shutting_down /
                    │                                      empty_prompt / invalid_request，不断连）
                    │                                    （Epic 75：帧带 project_id ⇒ 提交到该项目；projects ⇒ WsProjectsFrame）
                    ├── WS /api/runs/{run_id}/ws      → 重放 ring buffer（?last_event_id=N）→ 跟随实时事件
                    │                                    + {cancel, cancel_run, ping}（cancel 与 DELETE 同语义、幂等；cancel_run 用帧内 run_id）
                    ├── WS /api/cli/ws                → CLI 旁路（默认关）：跨轮次只读，仅 ping；cancel/run 显式拒绝
                    └── WS /api/notifications/ws      → 通知流（默认关）：cron 执行结果（?last_event_id=N 续传），仅 ping
        └── finally: await http_server.close() → await ws_server.close()
              # 顺序是契约：HTTP 先（排空在途 run 到终态）→ WS 后（关残余订阅/提交连接 + 停 listener）
```

（浏览器体验、wheel 打包验收与文档收口在 Story 49-6。）

**控制台流程（Epic 50，多项目；Story 50-1…50-7）：**

```
heagent http-server（同一入口；console 由入口层装配后注入 HttpServer，网络层只看到不透明 id 与协议模型）
  ├── HttpProjectConsole(workspace, projects_file=settings.http_console_projects_file,
  │                      runs=service, handler_factory=handler.for_workspace,
  │                      write_enabled=settings.http_console_write_enabled)
  │     └── 闸门开启 → stderr + 日志双通道高亮告警；网页**无法通过任何请求**打开它自己
  ├── 每请求按项目解析运行时：项目 id → WorkspacePaths.from_root(项目根) → SessionStore / Settings / EngineContainer
  │     └── settings 显式带 `_env_file=[项目 .env]`（用户层走类级默认源；不依赖进程 cwd，坏文件回退 + WARNING）
  └── 路由（在 49 的路由之上追加；错误一律稳定信封 + 与 49 相同的安全响应头）
        ├── GET    /api/projects                     → 注册表列表（含 available / is_default）
        ├── POST   /api/projects                     → 登记（**回环门**；路径须为已存在目录的绝对路径）
        ├── PATCH  /api/projects/{id}                → 重命名显示名（当前**无**回环门，见五）
        ├── DELETE /api/projects/{id}?confirm=true   → 移除登记（**回环门**；保留目录与项目数据）
        ├── …/sessions*                              → 会话列表 / 新建 / 详情 / 重命名（version 冲突 ⇒ session_conflict）
        │                                              / 删除（?confirm=true）；损坏文件 ⇒ session_unreadable
        ├── POST   /api/projects/{id}/runs           → 项目内运行（**每项目**单运行，超限 ⇒ 409 run_conflict；
        │                                             服务级总额满 ⇒ 409 total_inflight_limit）
        │       └── handler_factory(项目路径) → 该项目自己的 AgentLoop（构造期冻结 ResolvedRuntimeConfig）
        ├── GET    /api/projects/{id}/config         → 配置面板（四层来源 / 可写性 / 只读原因 / 凭证掩码 / 行级诊断）
        ├── PUT    /api/projects/{id}/config         → 写通道（**回环门** → 10 步流水线，见下）
        └── POST   /api/dialogs/pick-directory       → 原生目录选择（**回环门** + 单在途；50-8）
              └── cli.dialogs.DirectoryPicker：**默认 none = 禁用**；显式 auto(tkinter→powershell) ⇒ 子进程弹窗
                    ├── 冻结 argv（无 shell / 无用户输入）+ 凭证剥离 env + 300s 超时 ⇒ kill + 有界回收
                    ├── 只认 stdout 的 ASCII 标记行 + `is_dir()` 复验 ⇒ 取消/超时/脏值统一 cancelled=true
                    └── 返回值不是权限：仍要 POST /api/projects 走完整套校验
```

其余 Story 50-8 的体验约束（会话列表只渲染最近 **10** 条 / 侧栏**一列** / 对话区**占满所在列**（R7，撤销 48rem
限宽阅读列，2026-09-24） / 会话规模与展开控件置于面板最上面（R8） / 设置面板瘦身 / 网页侧读取结果收敛）
见 [frame/network.md](network.md) 4.17 表格末三行与 4.17 的安全声明段——它们**不新增路由**，只改前端渲染与网页桥的收敛判据。

写通道（`config/write.apply_config_write`，**10 步 + 1 项生效语义**；任一步失败即拒绝且文件不变）：

```
PUT /api/projects/{id}/config  {changes:[{key,value}], fingerprint}
  1  闸门       HTTP_CONSOLE_WRITE_ENABLED 关 ⇒ 403 write_disabled（连「项目是否存在」都不回答）
  2  回环来源   传输层 `_loopback_error`（网络层不认识 Settings）⇒ 403 loopback_required，且零副作用
  3  键白名单   classify()：非白名单 / 凭证键 / 被系统环境变量提供 ⇒ 400 field_not_writable
  4  值校验     VALUE_GUARDS + RESOURCE_CEILINGS（枚举 / 上下界）+ config/envfile.check_value（能否无损表达）
  5  指纹       与盘上不符 ⇒ 409 config_conflict（绝不覆盖他人的修改）
  6  候选构造   Settings(_env_file=候选) 必须能构造 + ROUTING_POOLS 池解析 ⇒ 否则 400 invalid_value
  7  备份       当前内容 → `.heagent/backups/<name>-<utc微秒>-<指纹前缀>.bak`（条数与保留期有上限）
  8  保真写     pub/persist.atomic_update_bytes（跨进程锁贯穿读改写；只重写值区，字节级保真）
  9  回读       同一把锁内重读 + 指纹比对；不符 ⇒ 还原原内容并 500 config_write_failed
  10 审计       `.heagent/console/audit.jsonl` 追加一行（键名 / 值的哈希与长度 / 结果，**不含值**；上限 500 行）
  11 生效语义   丢该项目运行时缓存 ⇒ 下一次 run 用新值、**在途 run 继续用旧快照**（响应 applied=next_run）
```
