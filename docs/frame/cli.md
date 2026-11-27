# CLI 入口（`cli/` 包）

> 状态：实现细节参考，自 [`framework.md`](../framework.md) **4.1** 迁出（2026-11-24 整理；编号不变，
> 其它文档里「4.1」的引用即指本页）。架构视角（项目定位 / 数据流 / 模块 DAG / 各模块职责与边界）见
> [`framework.md`](../framework.md)，安全立场（canonical）见 [§4.18](../framework.md#418-安全口径canonical)，
> 扩展页总索引见 [`frame/README.md`](README.md)。

## 4.1 CLI 入口 (`cli/console.py`)

**入口层是 `heagent/cli/` 包**（2026-09-26 由七个平铺 `cli*.py` 收编；本节标题保留入口脚本所在模块）。
`__init__.py` **零 import**（入口脚本指向 `heagent.cli.console:main`，不做包级 re-export），子模块按职责分：

| 子模块 | 职责 | 原文件 |
|--------|------|--------|
| `console.py` | Click 命令组 + 参数解析 + 单次/交互的**启动编排**（`run` / `replay` / `_run_cli_impl`） | `cli.py` |
| `composition.py` | 装配：provider→engine→AgentLoop、soul、上下文策略、plan mode、dream 调度、事件 sink、路由提取 | `cli.py` 拆出 |
| `interactive.py` | 单次/交互**执行**：REPL 循环、斜杠命令族、会话 id 解析、内嵌 HTTP 的挂载点 | `cli.py` 拆出 |
| `help_view.py` | `/help` 渲染面：列表版（名字对齐）、详情版（语法/参数/示例三段）、未知命令建议——纯展示，注册与派发仍在 `interactive.py`（2026-11-18 自 `interactive.py` 拆出，守单文件 1000 行上限） | `cli.py` 拆出 |
| `init.py` | `heagent init` 子命令（全局配置与项目上下文模板） | `cli_init.py` |
| `goal/` | `/goal` 命令族子包（commands / execution / messages / verify；Story 62.2 拆包） | `cli_goal.py` |
| `port_finder.py` | 端口顺延查找（preferred..preferred+9 内找空口） | 新增 |
| `http.py` | `http-server` 子命令 + HTTP 服务/生命周期装配（Epic 49） | `cli_http.py` |
| `http_config.py` | HTTP/WS listener 配置装配：`Settings` + CLI 覆盖 → `HttpServerConfig` / `WsServerConfig`（纯派生，Story 62.8 自 `http.py` 拆出） | `cli_http.py` 拆出 |
| `http_console.py` | 网页控制台的**项目/会话/配置面**（Epic 50；`HttpProjectConsole` / `HttpAgentHandler`） | `cli_http.py` 拆出 |
| `http_status.py` | `GET /api/status` 的来源适配：把运行服务 / 三条 WS 流 / 后台任务注册表聚合成 `StatusResponse`（WS 计数晚绑定，Story 71.1） | 新增 |
| `ws_submission_cache.py` | WS 提交幂等窗口（Epic 77）：`(project_id, request_id)` → 在途 `Future` / 成功结果，60s TTL + 256 条上限；在途合流、成功重放、失败移出，**纯内存**（进程重启即失效，刻意不落盘）。两条边界是刻意的：TTL **从提交开始计时**且**只清已完成项**（在途项一条都不踢，否则同键会二次真提交）；容量满时先淘汰已完成的旧项，全是在途才退化为按插入序淘汰最旧一条（内存有界优先于合流）。过期清理带两层早停：最旧一条都未过期时一次 O(1) 探测即跳过整趟扫描，真要扫也按插入序从最旧往后走、遇未过期即停（2026-11-26 优化）。可观测面（E78）：容量淘汰打 `ws event=idempotency_evicted reason=capacity`、键移出打 `ws event=idempotency_dropped reason=failed|cancelled`，两条都只带 `project_id`（`request_id` 不进日志，与 ack 不回显同一立场）；TTL 过期清理刻意静默 | 新增 |
| `ws_project_adapter.py` | WS 项目通道适配器：`ProjectChannelService` 的入口层实现——项目列表 → `WsProjectsFrame`（每条恰三字段）、提交收窄成 `SubmittedRun`、控制台/注册表错误码逐字转成 `HttpRunConflictError`（Epic 75；不解析项目目录、不碰盘与注册表）。**唯一一处实现方判断**是提交上界：构造期 `submit_timeout`（默认 30s）包住控制台调用，超时为 `_bounded` 用 `asyncio.wait` 判出的 pending（映射既有 `timeout` 码、文案写 `outcome unknown`），内层自抛的 `TimeoutError` 原样透传不代译（2026-11-26 / 2026-11-27 A77） | 新增 |
| `dialogs.py` | 服务端原生「选择目录」对话框（Story 50-8） | `cli_dialogs.py` |
| `display.py` | 终端渲染辅助（CLI 与 GUI 共用） | `cli_display.py` |
| `errors.py` | CLI 错误的统一出口：描述 + `Try:` 可用选项 + `Docs:` 文档锚点（Story 64.5） | 新增 |
| `doctor.py` | `heagent doctor` 配置诊断（只读；11 组检查产出 30 个诊断码，Story 64.6 / 73.3 加 TLS 身份四项） | 新增 |
| `cron_cmd.py` | `heagent cron status` 定时任务状态查询（只读 `jobs.json`：状态 / 最后与下次执行 / 失败原因，Story 64.10） | 新增 |
| `audit_cmd.py` | `heagent audit list\|export\|verify`：审计 JSONL 的查询 / 导出 / 跨段哈希链校验（读 `<状态根>/audit/tool-audit.jsonl` 与归档段 `tool-audit.seg-NNN.jsonl`，Story 67.2 / 67.3；段轮转 A61） | 新增 |
| `progress.py` | 进度原语：工具执行超 3s 的实时耗时行 + 大文件（>10MB）读写进度（Story 64.8 / 64.9） | 新增 |
| `tls_cmd.py` | `heagent tls init\|issue\|rotate-key\|fingerprint\|verify`：WS TLS 身份材料唯一入口（身份密钥长期固定 ⇒ 重签不改客户端 pin；Story 73.2） | 新增 |
| `run_history.py` | 重启后的**读侧事件回放**（A35）：从 `<项目根>/.heagent/runs/<id>/rollout.jsonl` 读回引擎事件并映射成 SSE 负载（工具输出未落盘 ⇒ 如实标注；缺终态补 `cancelled` 说明）；run_id 过白名单 + 路径越界校验。入口层模块——它同时认识 `events` 与 `network` 模型，`network/` 自身不得导入运行栈 | 新增 |
| `settings_audit.py` | CLI 侧用户级配置写入的统一审计留痕（A62）：`heagent init` / `--interactive` 写 `~/.heagent/setting.md` 时经 `record_operation` 记一条 `settings.write`，`before`/`after` 只放文件摘要（sha256 + 字节数，值不进审计），落 `<setting.md 目录>/audit/` | 新增 |
| `suggestions.py` | 错误场景 → ≥2 条**可执行命令**建议的声明式映射表（Story 64.13） | 新增 |
| `wizard.py` | `heagent init --interactive` 配置向导主体（45 项常用键按 11 个面分组，推荐值取自 `Settings` 字段默认，Story 64.14） | 新增 |
| `slash.py` | 交互模式斜杠命令注册表 + `.heagent/commands/*.md` 用户自定义命令加载 | 顶层 `slash.py` |
| `terminal.py` | 终端键盘监听（Esc 暂停 / Enter 恢复 / 双击 Esc 打断） | 顶层 `terminal.py` |
| `wiring.py` | provider 呈现薄壳（规则在 `providers/composition.py`，2026-11-07 迁出）+ `ensure_runtime_config` / `build_cron_job_runner`（CLI/GUI 共用） | 顶层 `wiring.py` |
| `housekeeping.py` | 启动期运行时产物保留期回收（日志 / 会话 / 编辑快照 / 沙箱会话目录 / 已停止 `heagent-*` 容器） | 顶层 `housekeeping.py`（2026-11-06 迁回顶层） |

**缝（monkeypatch 模块路径）按调用方分模块**：`_run_prompt` / `_run_single` 在 `interactive`（其调用方
`_run_chat` 同模块）；console 的命令层用**函数内导入**读 `_run_single`；`_build_loop` 在 `cli/composition`
（网络侧 `http.py` / `http_console.py` 函数内导入，CLI 侧 `interactive` 模块级导入）。
覆盖率 omit 只含命令层/交互层/`goal`/`display`（见 `pyproject.toml`）。

| 功能 | 说明 |
|------|------|
| 入口命令 | `python -m heagent [PROMPT]` |
| 单次模式 | 传入 PROMPT 参数，执行后退出 |
| 交互模式 | 不传参数，进入 REPL 聊天循环 |
| Provider 构建 | 自动检测 `DEEPSEEK_API_KEY` → `OPENAI_API_KEY` → `ANTHROPIC_API_KEY`；本地 Ollama 经 `OLLAMA_ENABLED=true` 显式启用 |
| 工具注册 | 导入 `heagent.tools.builtins` 触发 `@tool` 注册 |
| 模块初始化 | 自动创建 SkillStore、FactStore、ProfileStore、SoulStore、SessionStore、ContextCompressor、JobStore |
| Cron 调度 | 交互模式下启动 CronScheduler 后台任务 |
| 重试中间件 | 通过 `make_retry_middleware()` 接入 AgentLoop |
| Token 统计 | 每次回答后显示 `[tokens: N in + M out = T total]` |
| 运行暂停/恢复/中断 | 交互模式运行期间按 Esc 暂停当前 run、Enter 恢复、双击 Esc 打断（取消当前 run、回到输入状态，见 `cli/terminal.py`） |
| HTTP 入口 | `heagent http-server`（实现拆在 `cli/http.py` + `cli/http_config.py` + `cli/http_console.py` + `network/http_protocol.py` + `network/http_server/` + 包内 `web/`，协议、静态页与安全立场见 [frame/network.md](network.md) 4.16） |
