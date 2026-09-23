# HTTP Server MVP 方案

## 目标

让用户通过浏览器访问并操作正在运行的 HeAgent，首版聚焦本机单用户聊天体验。用户启动 HeAgent 默认 CLI（交互聊天或单次提示词）时，同一进程自动启动 HTTP 服务；显式运行 `gui`、`tcp-server`、`http-server`、`init`、`replay` 等子命令时不自动附带启动，避免多入口重复监听。HTTP 服务仅在默认 CLI 进程存活期间提供访问，不作为独立后台守护进程。

## MVP 范围

- 默认 CLI 启动时自动启动 HTTP 服务，并输出本地访问地址；同时保留 `heagent http-server` 显式启动方式，供只需要网页服务的场景使用。
- 提供内置静态聊天页：输入提示词、查看助手回答、显示工具调用/结果与运行状态、停止当前运行。
- 对话使用 `AgentLoop.run_stream()`，浏览器通过 Server-Sent Events (SSE) 接收文本增量、工具活动和结束/错误事件。
- 服务端维护一个内存会话；一次只允许一个活跃 run。重启后会话丢失，首版不承诺多用户隔离。
- 提供健康检查端点，用于确认服务已启动；UI 与 API 同源部署。
- 共享一个服务级 Provider、Engine 与记忆存储；每个 run 创建独立 `AgentLoop`，避免请求间可变展示状态串扰。复用 `cli_tcp.py` 的入口装配决策与 `cli._build_loop`，不在 `network/` 中装配 Agent。

## 不在 MVP 范围

- 公网/局域网部署、账号体系、TLS 终止、反向代理配置和多租户。
- 多会话管理、会话持久化/恢复、历史检索与导出。
- Provider/模型在网页中切换，配置编辑，工具审批 UI，MCP 管理。
- WebSocket、文件上传、语音、移动端专用体验及多进程部署。
- 让浏览器直接访问 TCP 协议或复用其 JSON Lines framing。

## 架构与模块边界

建议分为三层：

1. `heagent.network` 保持入口传输层职责，仅新增 HTTP 服务配置/生命周期及与 Agent 无关的 HTTP 协议模型；继续禁止依赖运行栈和入口层。
2. 新增入口层 `heagent.cli_http`，负责复用 `wiring._build_provider`、角色加载、日志/运行时清理、Engine 与记忆装配，创建 HTTP Agent handler，并注册 Click 子命令。按 `cli_tcp.py` 的延迟导入方式避免 `cli` 循环导入。
3. 新增轻量 Web UI 静态资源（建议 `src/heagent/web/`，随 wheel 打包），只调用本机 HTTP API。API 与静态资源同源，避免额外 CORS 面。

HTTP 框架建议评估 Starlette：ASGI 生命周期、SSE `StreamingResponse`、静态文件挂载与测试客户端均成熟，依赖较轻。若选择它，应作为可选依赖组 `http` 安装，命令在缺依赖时明确提示安装方式；MVP 不自制 HTTP 协议栈，也不使用同步 `http.server` 承载长时异步 Agent 任务。最终依赖选择应在实现前以当前 Python 3.11+ 和项目支持矩阵验证。

## API 草案

统一前缀 `/api`，请求/响应采用 JSON，流采用 `text/event-stream`：

| 方法与路径 | 用途 | MVP 行为 |
| --- | --- | --- |
| `GET /api/health` | 健康检查 | 返回服务状态与版本，不暴露凭据或本机路径 |
| `GET /api/session` | 获取当前会话 | 返回内存会话 ID、运行状态及可呈现的历史消息 |
| `POST /api/runs` | 开始一次运行 | 接受有界、非空 `prompt`；若已有运行则返回 `409`；返回 `run_id` |
| `GET /api/runs/{run_id}/events` | 订阅进度 | SSE 事件：`text`、`tool_call`、`tool_result`、`done`、`error`；断线不取消运行，重连可从有界事件缓存续读 |
| `DELETE /api/runs/{run_id}` | 停止运行 | 取消对应 asyncio task；运行清理后报告 `cancelled` |

事件负载应复用 `StreamEvent` 可表达的信息，不把内部对象直接序列化。事件带单调递增序号；SSE `id` 支持 `Last-Event-ID`。MVP 只需进程内有界 ring buffer，若客户端落后于缓存窗口，返回明确的重同步错误并让 UI 拉取 session 快照，不静默丢失状态。

请求错误使用稳定结构 `{ "error": { "code": ..., "message": ... } }`，并区分无效输入、运行冲突、未知 run、限流、超时和 Agent 失败。客户端文案有界且不含 traceback、密钥或内部路径；服务端日志保留诊断信息但不记录提示词/回答正文。SSE 生成器必须在客户端断线时释放订阅者资源；明确约定断线不会取消 Agent，取消只能调用 DELETE。

## 运行与并发

- 默认地址 `127.0.0.1`，默认端口 `8766`（与 TCP 默认 `8765` 错开）；允许 `HTTP_HOST`、`HTTP_PORT` 配置，独立服务命令可提供 `--host`、`--port` 覆盖。默认 CLI 模式不增加含糊的参数透传，绑定由配置控制。
- 默认仅一个客户端会话、最多一个在途 Agent run；请求体、最大连接数、事件缓存、空闲/运行超时和关闭 drain 时间均设有限值。
- 同一进程只启动一个 HTTP 服务实例。默认 CLI 启动时 HTTP 初始化/绑定失败必须显式告警并中止启动，不能悄悄退回“未启动但看似可用”；Ctrl+C 或 CLI 退出时停止接收、取消/等待在途 HTTP 任务并关闭 Provider 客户端等可关闭资源。
- HTTP 服务与交互聊天共用同一 Provider、Engine、记忆存储；各自 run 使用独立 `AgentLoop`。MVP 只有一个 HTTP 会话，CLI 终端会话和网页会话的对话历史彼此独立，不共享同一个 `SessionStore`。
- 单次 CLI 模式下 HTTP 服务与一次性 run 并行存活；CLI run 完成即关闭 HTTP 服务，因此只适合在该命令执行期间访问网页。需要持续网页会话时使用默认交互模式或 `heagent http-server`。
- Provider 与引擎共享策略沿用 TCP：不从网络请求接受 system/provider/model/工具策略/沙箱/迭代预算；不装 stdin 审批 handler，不自动连接 MCP。审批型工具调用保持 fail-safe 阻断语义。
- 所有请求都按不可信输入处理。输入长度、SSE 订阅数、运行数、响应事件大小均有上限；不将异常 traceback 回传浏览器。

## 安全决策

MVP 是本机个人工具，不是安全的远程服务。绑定地址默认回环；启动时复用 `network.exposure` 的保守暴露判定和统一告警。非回环绑定应在 MVP 中明确标为实验性/不受支持，并要求操作者自行在 OS 防火墙或隔离环境限制访问。不要仅凭 CORS、随机 URL 路径或“本机访问”视为认证。

首版应防止网页端点成为跨站请求伪造入口：仅允许同源 `Origin` 的状态变更请求，并拒绝不匹配的 Host/Origin；API 不启用宽泛 CORS。静态页不加载第三方脚本，设置严格 CSP、`X-Content-Type-Options: nosniff`、禁止 framing。提示词和 Agent 输出作为纯文本渲染，禁止不可信 HTML。该防护用于降低浏览器跨站滥用风险，不等同身份认证；能访问回环端口的本机进程仍可调用 API。

若未来要支持局域网/公网用户，必须另立方案加入身份认证、会话隔离、CSRF/Origin 策略、TLS/反向代理指引、审计与资源配额；不得仅开放 `--host 0.0.0.0` 就宣称可远程安全使用。

## 页面交互

- 主页面为紧凑聊天工作区：消息列表、文本输入、多行发送、运行中状态和停止按钮。
- 通过 SSE 增量显示回答；工具调用显示名称/目标/执行结果，工具错误显式标记。
- 运行期间禁用重复提交，显示连接中/重连中/取消中/失败状态；页面刷新后从 `/api/session` 恢复当前进程内快照。
- MVP 不暴露服务端配置、不提供管理面板。空状态、服务断连、运行冲突、Agent 错误和服务端关闭均有明确可见反馈。

## 配置建议

新增独立 `HTTP_*` 环境变量，不复用 `TCP_*` 命名。默认 CLI 自启动 HTTP 服务；显式服务子命令仍按命令语义启动 HTTP 服务：

| 配置 | 建议默认值 | 说明 |
| --- | --- | --- |
| `HTTP_HOST` | `127.0.0.1` | 默认回环绑定 |
| `HTTP_PORT` | `8766` | 避开 TCP 默认端口 |
| `HTTP_MAX_CONNECTIONS` | `16` | HTTP 客户端连接上限 |
| `HTTP_MAX_INFLIGHT_RUNS` | `1` | MVP 单会话单运行 |
| `HTTP_MAX_REQUEST_BYTES` | `65536` | JSON 请求体上限 |
| `HTTP_EVENT_BUFFER_SIZE` | `512` | 每个 run 的 SSE 事件缓存上限 |
| `HTTP_REQUEST_TIMEOUT` | `300` 秒 | Agent 单次运行上限 |
| `HTTP_SHUTDOWN_TIMEOUT` | `5` 秒 | 服务关闭 drain 上限 |

不设置 `HTTP_ENABLED` 开关，以免配置和 CLI 启动语义出现两套状态。配置模型由 Pydantic 校验；子命令 CLI 覆盖不写回 Settings 单例，行为对齐 TCP 入口。

## 实施切分

1. **协议与配置**：确定 Starlette 可选依赖；增加 HTTP 配置模型、请求/事件模型、输入限制与同源校验测试。
2. **HTTP 生命周期与 API**：实现健康、session、run 创建、SSE、取消、并发/超时/关闭管理；验证客户端断连与取消语义。
3. **Agent 适配与命令**：新增 `cli_http.py`，复用现有 Provider/wiring/loop 构造方式；明确不连接 MCP、不装交互审批；挂接 `heagent http-server`。
4. **默认 CLI 生命周期集成**：在 `_run_cli_impl` 的同一 asyncio 生命周期中启动 HTTP 服务。交互聊天模式中 HTTP server 与 REPL 共存；单次模式中与 Agent run 共存并在 run 结束后关闭。保证显式其他子命令不触发自动启动，并覆盖端口冲突、绑定失败、Ctrl+C 和资源收尾测试。
5. **内置 Web UI**：加入聊天、工具活动、错误/取消/重连状态；验证生产 wheel 包含静态资源。
6. **文档与验收**：补充 README、配置示例、`docs/frame.md` 当前架构与文档索引；运行相关 pytest、ruff、mypy 以及本机浏览器手工验收。

## MVP 验收标准

- 默认执行 `heagent`、`heagent "prompt"` 或 `heagent run ...` 时自动监听 `127.0.0.1:8766`；显式 `gui`、`tcp-server`、`init`、`replay` 子命令不会意外启动 HTTP server。
- `heagent http-server` 仍可独立启动 HTTP 服务；绑定冲突或初始化错误会显式失败，不会静默跳过。
- 浏览器可以发送提示词、逐步接收文本和工具事件、看到最终状态，并能可靠取消在途 run。
- 重复提交会明确返回冲突；非法/超大请求、未知 run、超时、Agent 失败和关闭均有稳定且不泄漏内部信息的响应。
- SSE 重连可通过事件序号续读；越过缓存窗口时明确要求重新同步，而非卡住或假装完整。
- 服务关闭不遗留任务；每个 run 的模型、token 用量和状态不串入其他请求。
- 不自动连接 MCP，不向服务进程 stdin 请求审批；安全工具策略仍由现有 PolicyEngine、ToolExecutor、SafetyGuard 执行。
- 新增配置不会改变 GUI/TCP/库调用行为；单元测试覆盖协议边界、默认 CLI 自动启动判定、生命周期、隔离和静态资源加载。

## 主要风险与待实现阶段验证

- Agent 的运行历史和中断后状态目前不是一个通用 Web 会话 API；需由入口层 owner 明确维护进程内 session 投影，不能直接依赖 Textual 的 `GuiState` 或 `AgentBridge`。
- SSE 客户端断线、浏览器刷新、取消竞态需有明确 task 所有权与订阅者清理，避免重复运行或任务泄漏。
- 项目 wheel 当前只声明 Python 包；静态资源的打包配置必须实测，源码运行正常不足以验收。
- 纯回环监听不能抵御本机恶意进程或被诱导访问 localhost 的浏览器上下文；MVP 不承诺远程访问安全性。
- 外部 Provider 调用、工具执行的耗时和成本仍由现有 Agent/Policy 配置决定；服务层并发和大小限制不能替代下层沙箱。
