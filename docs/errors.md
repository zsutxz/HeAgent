# 错误信息索引

HeAgent 的用户可见错误分三层，**先认形态再查表**：

| 你看到的形态 | 属于哪一层 | 查哪一节 |
| --- | --- | --- |
| JSON 信封 `{"error": {"code": "...", "message": "..."}}` | 传输层（HTTP / WS） | [一、传输层稳定错误码](#一传输层稳定错误码) |
| 工具结果 `is_error` / 事件 `tool_call_blocked` | 框架层（异常类） | [二、框架异常](#二框架异常) |
| 终端里的一行自由文本（`Error: ...` / 中文提示） | CLI 与启动期 | [三、CLI 与启动期错误](#三cli-与启动期错误) |
| 记不清属于哪层，只有一段报错原文 | — | [关键词跳转表](#关键词跳转表) |

**CLI 错误块怎么读**：命令行失败分支统一输出固定结构——首行是原消息，随后是 `Try:` 列表
与 `Docs:` 行，接入建议命令的分支再接一段 `Try these commands:`：

```text
Error: <原消息，逐字保留>
  Try:
    - <可执行动作，一条一行>
  Docs: docs/errors.md#三cli-与启动期错误
  Try these commands:
    - <可直接粘贴执行的命令>  # <这条命令用来做什么>
```

- 首行的 `Error: ` 前缀由 click 的 `ClickException` 加；走 `[前缀] …` 形态的分支（如
  `[replay] no events in …`、`[mcp config error] …`）没有该前缀，消息本身即首行。
- `Try:` 的每条都给出具体键名或命令；带 `<n>` / `<port>` 的占位符需替换成你自己的端口号。
- `Docs:` 是**仓库相对路径**（本页随源码分发）；通过 wheel 安装时回到源码仓库看同名文件。
- `Try these commands:` 是**可直接执行**的命令（至少两条，命令后的 `#` 是注释、整行可粘贴），
  与 `Try:` 的分工是：`Try:` 讲「该做什么」，这一段给「照着敲什么」。场景对照见
  [建议命令](#建议命令)。不是所有错误都有这一段——它按错误文本的场景映射产出。
- 状态行（`▶启动` / `✔完成`）、WARNING 与进度提示**不带**这些段落——它们不是错误。

**覆盖口径**：「用户可见错误」在本页被界定为三个可枚举集合的并集——传输层全部 **35** 个稳定码
（`network/http_protocol.py::HttpErrorCode`，封闭集合）+ 框架层全部 **29** 个异常类
（`pub/exceptions.py`，每个都带稳定码）+ CLI/启动期 **12** 条常见报错，合计 **76** 条，三条链路各自 **100%** 覆盖。
可枚举集合之外的自由文本不在此口径内。

**码的现状**：传输层（`HttpErrorCode`）与框架层（`pub/exceptions.py::code`）都是封闭码集合；
CLI/启动期仍是自由文本，按下面的原文片段检索。码的语义分组与权威口径见
[架构参考 4.17](frame.md)。

## 一、传输层稳定错误码

`code` 是稳定判据（**不要按 `message` 做分支**，文案会变），`message` 有界且已脱敏。下表「HTTP」
列给出该码的 HTTP 状态；「无固定状态」表示该码不经 HTTP 响应发送（WS 错误帧或当前无发送点，见描述列）。

### 输入类

| `code` | HTTP | 描述 | 原因 | 方案 |
| --- | --- | --- | --- | --- |
| `invalid_request` | 400 | 请求体不是合法 JSON 或不符合模型 schema | 字段拼错、类型不对、缺必填项；控制台写通道的值类型不符 | 读 `message` 里点名的字段改请求；确认请求体是 JSON 对象 |
| `empty_prompt` | 400 | `prompt` 缺失或全是空白 | 传了空串 / 只有空格换行 | 给非空 `prompt`；WS 侧同一个码走错误帧 |
| `request_too_large` | 413 | 请求体超过 `HTTP_MAX_REQUEST_BYTES` | 请求体字节数越过该上限（默认 394240，对超长上下文或多出来的字段同样生效） | 缩短 prompt；调大 `HTTP_MAX_REQUEST_BYTES`（`.env.example` 第 18 节） |

### 项目与会话类

| `code` | HTTP | 描述 | 原因 | 方案 |
| --- | --- | --- | --- | --- |
| `unknown_project` | 404 | 注册表里没有该 `project` | 项目 id 拼错，或该目录从未注册 | `GET /api/console/projects` 取真实 id；网页控制台里先添加项目 |
| `invalid_project_path` | 400 | 项目路径不合法 | 空路径、相对路径越界、指向文件而非目录 | 用 `ls -d <path>` 确认是存在的目录，再传绝对路径 |
| `project_unavailable` | 409 | 项目存在但没有可用的运行入口 | 服务启动时该项目的运行栈未装配成功 | 重启服务；在 `logs/heagent-*.log` 里搜该项目 id 的 WARNING |
| `project_not_removable` | 409 | 该项目不允许被移除 | **默认项目**不能移除（注册表的兜底条目） | 先移除其它项目；注册表落点是 `HTTP_CONSOLE_PROJECTS_FILE`（缺省 `.heagent/console/projects.json`） |
| `project_busy` | 409 | 该项目被占用（有在途运行 / 正在被删除） | 同一项目同时跑多个运行 | 等当前运行结束；或 `DELETE /api/runs/{run_id}` 取消 |
| `project_limit_reached` | 409 | 项目注册表已满 | 注册表条目数达到上限 | 移除不用的项目后重试；注册表落点见 `HTTP_CONSOLE_PROJECTS_FILE` |
| `unknown_session` | 404 | 没有该会话 | 会话 id 拼错，或会话文件已被保留期清理 | `ls .heagent/sessions/` 核对 id；清理周期由 `SESSION_RETENTION_DAYS` 控制 |
| `invalid_session_id` | 400 | 会话 id 形态非法 | 含路径分隔符、控制字符、保留名（如 Windows 的 `NUL`） | 用服务端返回的会话 id，不要自己拼路径 |
| `session_conflict` | 409 | 会话文件在读取后被改动（乐观锁冲突） | 两处同时写同一会话（显式传了 `expected_version` 时才会发生） | 重新读取会话内容再提交；不传 `expected_version` 即 last-write-wins |
| `session_busy` | 409 | 会话被在途运行占用 | 该会话正在跑一轮 | 等运行结束，或 `DELETE /api/runs/{run_id}` 取消后重写 |
| `session_unreadable` | 409 | 会话文件存在但无法解析 | 文件被手工改坏、写一半断电 | 备份后删除 `.heagent/sessions/` 下的该文件 |

### 原生选择类

| `code` | HTTP | 描述 | 原因 | 方案 |
| --- | --- | --- | --- | --- |
| `dialog_unavailable` | 503 | 没有可用的图形后端 | 无显示环境 / `--dialog-backend none` | 手工输入路径；或在有图形后端的环境启动 |
| `dialog_busy` | 409 | 已有一个目录选择在途 | 同时点了两次「浏览」 | 等前一个选择结束（「用户取消」走成功响应里的 `cancelled=true`，不占错误码） |

### 运行类

| `code` | HTTP | 描述 | 原因 | 方案 |
| --- | --- | --- | --- | --- |
| `run_conflict` | 409 | 已有在途运行，或服务正在关闭 | `HTTP_MAX_INFLIGHT_RUNS` 已满（默认每项目 1）；关停中提交运行同样回这个码（`message` 为 `server is shutting down`） | 等当前运行结束（不排队）；需要并发就调大 `HTTP_MAX_INFLIGHT_RUNS` |
| `total_inflight_limit` | 409 | 服务级在途总额已满（跨项目共享） | `HTTP_MAX_TOTAL_INFLIGHT` 不为 0 且已打满 | 等**任一**运行结束；或调大 `HTTP_MAX_TOTAL_INFLIGHT`（0 = 不限） |
| `unknown_run` | 404 | 没有该 `run_id` | id 拼错，或该运行已被淘汰出历史窗口 | 重新提交运行；历史保留条数由 `HTTP_RUN_HISTORY_SIZE` 控制 |
| `resync_required` | 409 | SSE 断线重连的游标已越过事件窗口 | 断线太久，缓存事件已被环形缓冲覆盖 | 拉 `GET /api/session` 拿完整快照后重新同步（页面自动完成）；可调大 `HTTP_EVENT_BUFFER_SIZE` |

### 资源类

| `code` | HTTP | 描述 | 原因 | 方案 |
| --- | --- | --- | --- | --- |
| `rate_limited` | 429 | 连接或订阅超额 | `HTTP_MAX_CONNECTIONS` / `HTTP_MAX_SUBSCRIBERS` / `WS_MAX_CONNECTIONS` 已满 | 关掉闲置页面或客户端；按实际并发调大对应上限 |
| `timeout` | 无固定状态 | **保留码，当前无发送点** | 超时判定不改用错误码：由 `HTTP_IDLE_TIMEOUT` / `HTTP_TOOL_INFLIGHT_TIMEOUT` / `HTTP_REQUEST_TIMEOUT` 各自处理 | 这三个键见 `.env.example` 第 18 节；不要等这个码出现 |

### 边界类

| `code` | HTTP | 描述 | 原因 | 方案 |
| --- | --- | --- | --- | --- |
| `origin_forbidden` | 403 | 请求的 `Origin` 未通过校验 | 跨源页面直接调用本地接口（CSRF 纵深防御） | 从同源页面访问；脚本调用请不带浏览器 `Origin` |
| `not_found` | 404 | 路径不存在 | 端点拼错，或该能力在当前 listener 上未注册 | 对照 [README「HTTP 网页入口」](../README.md) 的端点表；WS listener 上没有任何 HTTP 路由 |
| `method_not_allowed` | 405 | 路径存在但方法不对 | 用 GET 调了只接受 POST 的端点 | 换方法；[README](../README.md) 端点表的「方法与路径」列即契约 |

### 服务类

| `code` | HTTP | 描述 | 原因 | 方案 |
| --- | --- | --- | --- | --- |
| `agent_error` | 无固定状态 | **保留码，当前无发送点** | 运行期失败改由 SSE `error` 事件与运行状态 `failed` 表达，不占用错误码 | 看该 run 的事件流与 `.heagent/runs/<run_id>/` |
| `shutting_down` | 无固定状态 | 服务正在关闭（只经 WS 错误帧发送） | 收到关停信号后仍有 WS 订阅者 | 重连即可；关闭排空上限由 `WS_SHUTDOWN_TIMEOUT` 控制，关闭码 `1001`（HTTP 侧关停提交 run 走 `run_conflict`） |
| `server_error` | 500 | 服务端未捕获错误 | 内部异常、注册表无法解析、未知内部错误码 | `logs/heagent-*.log` 里搜 `http event=handler_failed` 与 traceback；附日志提 issue |

### 配置写入与确认类

> 枚举 docstring 未把这 7 个码归组（前七组是它的原文分组），本页单列为「配置写入通道 + 确认/回环」。

| `code` | HTTP | 描述 | 原因 | 方案 |
| --- | --- | --- | --- | --- |
| `write_disabled` | 403 | 配置写入通道未开启 | `HTTP_CONSOLE_WRITE_ENABLED=false`（默认） | 需要网页改配置时启动服务时置 true；注意这等于「任何能连上该端口的人都能改项目 `.env`」 |
| `field_not_writable` | 400 | 该键不允许经网页写 | 只读键或不在白名单 | 直接改项目 `.env` 后重启进程 |
| `invalid_value` | 400 | 写入值不合法 | 端口越界、计数为 0、非正超时、空 host 等 | 按 `.env.example` 对应键的注释给合法值 |
| `config_conflict` | 409 | 配置文件在读取后被改动（指纹冲突） | 两处同时改同一个 `.env` | 重新加载页面拿最新值再提交；写前备份、写后回读是既有行为 |
| `config_write_failed` | 500 | 写入失败 | 磁盘只读、权限不足、写后回读不一致 | 检查项目目录写权限；搜日志 `http event=console_write_failed` |
| `confirm_required` | 400 | 该操作需要显式确认 | 破坏性操作（如删除项目）缺确认字段 | 请求体带 `confirm=true` 重发 |
| `loopback_required` | 403 | 该端点只接受回环请求 | 从非回环地址访问了本机专用端点（HTTP listener 恒只绑回环） | 换回本机环境，或用 WS 入口（`WS_HOST` + `WS_LAN_NO_AUTH` / `WS_AUTH_TOKEN`） |

> 码到状态码的映射单源在 `network/http_server/pipeline.py` 的 `_CONSOLE_ERROR_STATUS`：未列出的码
> 按 400 处理，枚举里不存在的码降级为 500。契约快照
> `tests/fixtures/contract_baselines/transport_errors.json` 从调用点静态抽取，标 `unmapped`
> 表示「脚本不猜值」，不表示「线上不会出现」。

## 二、框架异常

框架异常带**稳定错误码**（`pub/exceptions.py` 的 `code` 类属性，实例经 `exc.code` 读）。层次是三层：
根 `HeAgentError`（旧称 `HeAgentException` 是它的别名）→ 分类（`ProviderError` / `ToolError` /
`EngineError` / `AgentError` / `SessionError` / `ConfigurationError`）→ 具体异常；`except <分类>` 一次
捕获一整类。码一经发布不改名、不复用（只增）。

下表由 `error_catalog()` 生成，`tests/test_exceptions.py` 逐条比对——**不要手改表格**：改代码后跑测试，
差异会被点名。

| 码 | 异常类 | 含义 | 建议操作 |
| --- | --- | --- | --- |
| `E_HEAGENT` | `HeAgentError` | 框架内部错误的通用形态，未归入任何分类时才会直接出现 | 按具体子类处理；只有它本身说明该错误尚未归类 |
| `E_PROVIDER` | `ProviderError` | Provider 调用失败，已用尽重试与回退 | 看日志 provider_call_completed 的 details.model 与上游状态码；认证问题核对该条目的 *_API_KEY |
| `E_PROVIDER_AUTH` | `ProviderAuthError` | Provider 认证失败（401 / 403） | 核对 .env 里该条目的 *_API_KEY；池内换档刻意不覆盖认证失败（属配置问题） |
| `E_PROVIDER_RATE_LIMIT` | `ProviderRateLimitError` | Provider 限流（429 或响应体命中 rate 关键词） | 等限流窗口重置；回退链会自动换 provider / 密钥，也可 /provider 手工切 |
| `E_PROVIDER_TIMEOUT` | `ProviderTimeoutError` | Provider 调用超时（408 / 504 或消息命中超时关键词） | 重试该调用；持续超时查网络与中转站健康度，必要时 /provider 换一家 |
| `E_PROVIDER_RESPONSE_FORMAT` | `ProviderResponseFormatError` | Provider 返回体形状不符合预期（如 choices 为空） | 确认上游是否兼容中转站（响应契约漂移）；换官方端点或换 provider |
| `E_TOOL` | `ToolError` | 工具执行失败（分类层，具体原因看子类） | 读工具返回正文（is_error=true）；路径类错误见 docs/faq.md 故障排查 |
| `E_TOOL_ARGUMENT` | `ToolArgumentError` | 工具参数不合法（缺必填参数或参数形状不对） | 按工具 Schema 补参数；文件类工具的路径须过 path_safety（工作区相对路径） |
| `E_TOOL_EXECUTION` | `ToolExecutionError` | 工具开始执行后失败（调用超时、server 断连等） | 读工具返回正文；MCP 工具查 server 连接状态与 call_timeout 配置 |
| `E_TOOL_UNKNOWN` | `UnknownToolError` | 调用了未注册或未启用的工具名 | 核对工具名；确认该工具已注册且未被 ALLOWED_TOOLS / BLOCKED_TOOLS 过滤 |
| `E_TOOL_SAFETY_VIOLATION` | `SafetyViolation` | SafetyGuard 在 handler 之前拦下调用（危险命令 / 受保护路径） | 该调用未执行；看事件 tool_call_blocked 的 details.reason 与 SAFETY_BLOCKED_TOOLS 是否误伤 |
| `E_TOOL_MCP_SDK_MISSING` | `McpSdkMissingError` | MCP 桥接的可选依赖 mcp SDK 未安装（可选能力，不影响其余功能） | 装可选依赖：pip install "heagent[mcp]"；不要 MCP 时保持 MCP_ENABLED=false |
| `E_ENGINE` | `EngineError` | 运行时治理层错误（分类层） | 按子类处理；治理层的拒绝一律「未执行」，先看事件流里的 details |
| `E_ENGINE_POLICY_VIOLATION` | `PolicyViolation` | PolicyEngine 在 handler 之前拒绝调用（档位 / 白黑名单 / 审批未过） | 该调用未执行；看 tool_call_blocked 的 details.mode；SANDBOX_MODE=read-only 会拦所有写与 shell |
| `E_ENGINE_LEDGER` | `LedgerError` | 执行台账（幂等记录）读写失败或记录状态不符 | 查 .heagent 下的台账记录文件；台账只是幂等缓存，任务可安全重跑 |
| `E_ENGINE_POLICY_EXECUTION` | `PolicyExecutionError` | 策略裁决通过但执行环境不成立（沙箱会话目录缺失等） | 检查 run metadata 的 sandbox_workspace；或关闭沙箱会话目录让路径恢复存在 |
| `E_ENGINE_WORKFLOW` | `WorkflowExecutionError` | 工作流步骤选择或状态推进不合法 | 核对 workflow 的 steps 声明与 active_step；恢复一律走 checkpoint，不猜、不静默跳过 |
| `E_ENGINE_STORE_CONFLICT` | `FactCompactConflictError` | 存储在读与写之间被并发修改（fact_compact 的 MEMORY.md 冲突），整批放弃 | 重跑 fact_compact（被移出的条目已留底）；同写 MEMORY.md 的进程需串行化 |
| `E_AGENT` | `AgentError` | Agent 循环与子 Agent 委派错误（分类层） | 按子类处理；预算 / 上限类错误改配置或拆小任务 |
| `E_AGENT_BUDGET_EXCEEDED` | `BudgetExceeded` | 迭代或 token 预算用尽 | 调大 MAX_ITERATIONS / SUBAGENT_MAX_ITERATIONS，或把任务拆小 |
| `E_AGENT_ITERATION_LIMIT` | `IterationLimitError` | 迭代硬上限用尽（本轮未给出最终回答） | 调大 MAX_ITERATIONS；或把任务拆成多轮 / 委派子 Agent |
| `E_AGENT_SUBAGENT` | `SubAgentError` | 子 Agent 委派请求不成立（任务与 agent 数量不匹配等） | 核对委派调用参数；单任务走 subagent，多任务走并行委派且两列等长 |
| `E_AGENT_RESUME` | `AgentResumeError` | 续跑时找不到该 run 的快照 | 用 run 列表里的真实 run_id；快照已被清理时只能重跑 |
| `E_SESSION` | `SessionError` | 会话文件存取错误（分类层） | 按子类处理；会话文件在 .heagent/sessions/ 下 |
| `E_SESSION_CONFLICT` | `SessionConflictError` | 会话文件在读取后被改动（显式传 expected_version 时的乐观锁冲突） | 重新读取会话再提交；不传 expected_version 即 last-write-wins |
| `E_SESSION_NOT_FOUND` | `SessionNotFoundError` | 该会话 id 没有对应的会话文件 | 用会话列表 / 服务端返回的真实 id，不要自己拼路径 |
| `E_SESSION_UNREADABLE` | `SessionUnreadableError` | 会话文件存在但无法解析 | 备份后删除 .heagent/sessions/ 下的该文件 |
| `E_CONFIGURATION` | `ConfigurationError` | 配置面错配（键值不合法，或引用了池里不存在的名字） | 按 .env.example 对应键给合法值；heagent doctor 会逐项列出问题键 |
| `E_CONFIGURATION_INVALID_INPUT` | `InputValidationError` | 输入校验失败（逐字段列出问题；当前接入面是配置写入守卫） | 按提示改对应字段；键名与取值域见 .env.example，全局体检跑 heagent doctor |

**非框架异常**（`ValueError` / `OSError` 等直接冒到用户面前）没有码；`error_code_of(exc)` 统一返回
`E_UNKNOWN`，不抛。

## 三、CLI 与启动期错误

这一层的错误是**自由文本**，按「原文片段 → 成因 → 修法」检索：

| 报错原文片段 | 成因 | 方案 |
| --- | --- | --- |
| `Error: No API key configured. Set DEEPSEEK_API_KEY, ...` | 一个 Provider 凭据都没配 | 在 `.env` 或 `~/.heagent/setting.md` 配一个凭据；本地模型改用 `OLLAMA_ENABLED=true` |
| `Error: OLLAMA_ENABLED=true requires OLLAMA_MODEL` | 开了 Ollama 但没给模型名 | 设 `OLLAMA_MODEL=qwen3:8b`；列本地模型 `curl http://127.0.0.1:11434/api/tags` |
| `invalid --resume session id: ...` | `--resume` 的 id 含路径分隔符 / 控制字符 / 保留名 | 用会话列表里的真实 id；不要自己拼路径 |
| `[mcp config error] ...` | `.mcp.json` 解析失败或引用的 server 不可用 | 校验 JSON 语法；必要时 `MCP_ENABLED=false` 先跑起来 |
| `auth-enforcing WS listeners require WS_AUTH_TOKEN in ~/.heagent/setting.md` | WS 绑了非回环地址但没配 token | 在 `~/.heagent/setting.md` 加 `WS_AUTH_TOKEN: <长随机串>`；项目 `.env` 写不生效 |
| `WS_TLS_CERT_FILE and WS_TLS_KEY_FILE are not a pair` | 证书与私钥不是同一对（常见：只换了其中一份） | `heagent tls verify` 看哪份材料不对；`heagent tls issue` 用同一身份密钥重签 |
| `WS TLS materials are unreadable` | cert/key 指向的文件读不出、不是 PEM 或私钥非 RSA | 指到 `.heagent/tls/` 的 `cert.pem` + `key.pem`；缺失就用 `heagent tls init` / `heagent tls issue` 重建 |
| `WS TLS certificate ... expires in N days`（启动日志 WARNING） | 叶证书余量 < 7 天（过期后是握手期全失败） | `heagent tls issue`（复用身份密钥 ⇒ 客户端 pin 不变） |
| `HTTP server could not bind <addr>: address unavailable` | 端口被占或地址不可绑 | 换端口（`--port` / `--ws-port`）；不显式传端口时会在 `preferred…preferred+9` 内自动顺延 |
| `HTTP server started but /api/health is not servable` | 启动自检失败：listener 起来了但路由不可达 | 换端口重试；检查是否有代理/防火墙拦截回环 |
| `the HTTP entry point requires optional dependencies (missing 'starlette')` | 没装 http extra（`uvicorn` / `websockets` 缺失同一形态，`missing` 后是实际缺的模块名） | `pip install "heagent[http]"` |
| `WebSocket support requires websockets` | 没装 ws 依赖 | `pip install "heagent[http]"` |
| `sandbox backend ... unavailable`（启动日志 WARNING） | 指定后端不可用，已显性降级为宿主执行 | 装 firejail / 起 docker daemon；或 `--sandbox passthrough` 明确接受零隔离 |
| `workflow role 'X' is unavailable` | `/goal` 声明的角色在技能库里找不到 | 把角色包放到 `.heagent/skills/<role>/` 或 `~/.heagent/skills/`（技能库全局优先） |
| `workflow package 'X' is unavailable under the skill library` | `/goal` 绑定的工作流包不存在 | 确认 `.heagent/skills/<pkg>/SKILL.md` 存在且 frontmatter 的 `canonical_id` 对得上 |

> 工具被拦下时**不会**在终端打一行自由文本，而是在工具结果里给 `is_error` 与正文、并发出
> `tool_call_blocked` 事件——按上面的[框架异常](#二框架异常)节查。

### 建议命令

错误块末尾的 `Try these commands:` 段由 `src/heagent/cli/suggestions.py` 的声明式场景表产出：
按错误文本里的关键词选场景，给出**至少两条可直接粘贴执行**的命令（命令后的 `#` 是注释，整行可
执行，不需要替换任何占位符）。

| 场景 | 触发关键词（节选） | 建议命令（示例） |
| --- | --- | --- |
| 凭据缺失 | `api key` / `api_key` / `credential` / `401` | `heagent init --interactive` / `heagent doctor` / `/provider` |
| WS 对外缺 token | `ws_auth_token` / `bearer token` / `auth-enforcing` | `heagent init`（生成带 `WS_AUTH_TOKEN` 说明的用户级模板） / `heagent doctor` |
| ⚠ 注意 | — | `--no-ws` **不能**绕过这道校验：启动校验作用于 `Settings`，早于本次进程的 `--no-ws` 覆盖生效 |
| 端口占用 / 绑定失败 | `port` / `bind` / `address already in use` / `eaddrinuse` | `heagent http-server --port 9102` / `heagent http-server --ws-port 9202` / `heagent doctor` |
| 沙箱后端不可用 | `sandbox` / `firejail` / `docker` / `winjob` | `heagent run --sandbox passthrough "hi"` / `heagent run --sandbox docker "hi"` / `heagent doctor` |
| MCP 配置 / 连接失败 | `mcp` / `.mcp.json` | `heagent doctor` / `/mcp-prompt` |
| 技能 / 工作流包不可用 | `skill` / `workflow role` / `workflow package` | `/goal doctor` / `heagent doctor` / `/help` |
| 定时任务失败 | `cron` / `job store` / `schedule` | `/goal auto` / `heagent doctor` |
| 会话 id 非法 / 会话缺失 | `session` / `--resume` / `rollout` / `replay` | `/clear` / `heagent run "hi"` |
| provider 未配置 / 切换失败 | `provider` / `routing pool` / `not supported by any configured account` | `/provider` / `/model auto` / `heagent doctor` |
| 配置键非法 | `invalid value` / `cannot parse` / `.env` / `config` | `heagent doctor` / `heagent init --interactive` |
| 未识别场景（兜底） | 上述关键词全不命中 | `heagent doctor` / `/help` |

示例：`HTTP server could not bind 127.0.0.1:9101: address unavailable` 命中「端口占用」场景，
块尾给出

```text
  Try these commands:
    - heagent http-server --port 9102  # 换一个 HTTP 端口（默认 9101 被占或不可绑时）
    - heagent http-server --ws-port 9202  # WS 端口同样顺延一位（默认 9201）
    - heagent doctor  # 只读体检：逐项列出问题键与修法
```

未命中任何关键词时走兜底（`heagent doctor` + `/help`），而不是「无建议」。

维护：新增场景或调整命令时改 `suggestions.py` 的 `SCENARIOS`——每场景必须 ≥2 条（导入期校验，
坏表当场抛错），命令必须是**真实存在**的 CLI 子命令或斜杠命令：`tests/test_cli_suggestions.py`
用代码反射逐条校验（`heagent <sub>` 对 `console.main.commands`、`/<name>` 对
`_build_slash_registry()` 的注册表、`--flag` 对该 click 命令的参数表），写错命令名测试即红。

## 关键词跳转表

| 你搜的关键词 | 去哪条 |
| --- | --- |
| `No API key configured` | [CLI：无凭据](#三cli-与启动期错误) |
| `403` + WebSocket | [常见问题：WS 连上就被关](faq.md#三故障排查) |
| `409` + 提交运行 | `run_conflict` / `total_inflight_limit`（[运行类](#运行类)） |
| `413` | `request_too_large`（[输入类](#输入类)） |
| `429` | `rate_limited`（[资源类](#资源类)） |
| `resync_required` / 断线重连丢事件 | [运行类](#运行类) |
| `tool_call_blocked` | [框架异常](#二框架异常) 的 `SafetyViolation` / `PolicyViolation` |
| `session file cannot be parsed` | `session_unreadable` |
| `server is shutting down` | `run_conflict`（HTTP 提交）或 `shutting_down`（WS 订阅） |
| `request origin rejected` | `origin_forbidden` |
| 网页改配置失败 | [配置写入与确认类](#配置写入与确认类) |

## 维护

- 新增或改名传输层错误码时：改 `HttpErrorCode` → 本页对应分组表 → 跑
  `scripts/contract_snapshot.py` 更新 `transport_errors.json`（三处同批，否则契约测试会红）。
- 新增框架异常类时：补「二、框架异常」表格行。
- 新增 CLI 报错文案时：若使用者可能照着搜索，补「三、CLI 与启动期错误」一行。
