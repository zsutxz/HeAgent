# 错误信息索引

HeAgent 的用户可见错误分三层，**先认形态再查表**：

| 你看到的形态 | 属于哪一层 | 查哪一节 |
| --- | --- | --- |
| JSON 信封 `{"error": {"code": "...", "message": "..."}}` | 传输层（HTTP / WS） | [一、传输层稳定错误码](#一传输层稳定错误码) |
| 工具结果 `is_error` / 事件 `tool_call_blocked` | 框架层（异常类） | [二、框架异常](#二框架异常) |
| 终端里的一行自由文本（`Error: ...` / 中文提示） | CLI 与启动期 | [三、CLI 与启动期错误](#三cli-与启动期错误) |
| 记不清属于哪层，只有一段报错原文 | — | [关键词跳转表](#关键词跳转表) |

**CLI 错误块怎么读**：命令行失败分支统一输出固定结构——首行是原消息，随后是 `Try:` 列表
与 `Docs:` 行：

```text
Error: <原消息，逐字保留>
  Try:
    - <可执行动作，一条一行>
  Docs: docs/errors.md#三cli-与启动期错误
```

- 首行的 `Error: ` 前缀由 click 的 `ClickException` 加；走 `[前缀] …` 形态的分支（如
  `[replay] no events in …`、`[mcp config error] …`）没有该前缀，消息本身即首行。
- `Try:` 的每条都给出具体键名或命令；带 `<n>` / `<port>` 的占位符需替换成你自己的端口号。
- `Docs:` 是**仓库相对路径**（本页随源码分发）；通过 wheel 安装时回到源码仓库看同名文件。
- 状态行（`▶启动` / `✔完成`）、WARNING 与进度提示**不带**这两段——它们不是错误。

**覆盖口径**：「用户可见错误」在本页被界定为三个可枚举集合的并集——传输层全部 **35** 个稳定码
（`network/http_protocol.py::HttpErrorCode`，封闭集合）+ 框架层全部 **9** 个异常类
（`pub/exceptions.py`）+ CLI/启动期 **12** 条常见报错，合计 **56** 条，三条链路各自 **100%** 覆盖。
可枚举集合之外的自由文本不在此口径内。

**码的现状**：只有传输层有封闭码集合。框架层只有 9 个无 `code` 字段的异常类，CLI 层是自由文本
——统一错误码体系尚未落地，届时为这两层补「错误码」列。码的语义分组与权威口径见
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
| `loopback_required` | 403 | 该端点只接受回环请求 | 从非回环地址访问了本机专用端点 | 换回环境，或改用对外 listener 的端点（见 `WS_EXTERNAL_*`） |

> 码到状态码的映射单源在 `network/http_server/pipeline.py` 的 `_CONSOLE_ERROR_STATUS`：未列出的码
> 按 400 处理，枚举里不存在的码降级为 500。契约快照
> `tests/fixtures/contract_baselines/transport_errors.json` 从调用点静态抽取，标 `unmapped`
> 表示「脚本不猜值」，不表示「线上不会出现」。

## 二、框架异常

框架异常**不带稳定码**，但会以这些形态出现在工具结果、事件流与日志里：

| 异常类 | 触发 | 用户看到什么 | 方案 |
| --- | --- | --- | --- |
| `HeAgentError` | 其余框架异常的基类 | 各自子类形态 | 按具体子类处理 |
| `ProviderError` | Provider 调用失败（可带上游 `status_code`） | 重试耗尽后 run 失败 | 日志 `provider_call_completed` 里的 `details.model` 与上游状态码；认证问题查该条目的 `*_API_KEY` |
| `ToolError` | 工具执行失败 | 工具结果为 `is_error=true` | 读工具返回正文；路径类错误见[常见问题](faq.md#三故障排查) |
| `SafetyViolation` | `SafetyGuard.check()` 拦下调用 | 事件 `tool_call_blocked`，`details.mode="safety_blocked"` | 该调用**未执行**；看 `details.reason`，或 `SAFETY_BLOCKED_TOOLS` 是否误伤 |
| `PolicyViolation` | `PolicyEngine.evaluate()` 拒绝 | 事件 `tool_call_blocked`，`details.mode` 为策略档位 | 该调用**未执行**；`SANDBOX_MODE=read-only` 会拦所有写操作与 shell |
| `BudgetExceeded` | 迭代或 token 预算用尽 | run 以失败结束 | 调大 `MAX_ITERATIONS` / `SUBAGENT_MAX_ITERATIONS`，或拆小任务 |
| `SessionConflictError` | 写入时带了 `expected_version` 且文件已变 | 仅 API 调用方可见 | 重新读取会话再写；不传 `expected_version` 即 last-write-wins |
| `SessionNotFoundError` | 会话 id 无对应文件 | 与 `unknown_session` 同源 | 用服务端返回的 id |
| `SessionUnreadableError` | 会话文件无法解析 | 与 `session_unreadable` 同源 | 备份后删除该会话文件 |

## 三、CLI 与启动期错误

这一层的错误是**自由文本**，按「原文片段 → 成因 → 修法」检索：

| 报错原文片段 | 成因 | 方案 |
| --- | --- | --- |
| `Error: No API key configured. Set DEEPSEEK_API_KEY, ...` | 一个 Provider 凭据都没配 | 在 `.env` 或 `~/.heagent/setting.md` 配一个凭据；本地模型改用 `OLLAMA_ENABLED=true` |
| `Error: OLLAMA_ENABLED=true requires OLLAMA_MODEL` | 开了 Ollama 但没给模型名 | 设 `OLLAMA_MODEL=qwen3:8b`；列本地模型 `curl http://127.0.0.1:11434/api/tags` |
| `invalid --resume session id: ...` | `--resume` 的 id 含路径分隔符 / 控制字符 / 保留名 | 用会话列表里的真实 id；不要自己拼路径 |
| `[mcp config error] ...` | `.mcp.json` 解析失败或引用的 server 不可用 | 校验 JSON 语法；必要时 `MCP_ENABLED=false` 先跑起来 |
| `auth-enforcing WS listeners require WS_AUTH_TOKEN in ~/.heagent/setting.md` | WS 绑了非回环地址但没配 token | 在 `~/.heagent/setting.md` 加 `WS_AUTH_TOKEN: <长随机串>`；项目 `.env` 写不生效 |
| `HTTP server could not bind <addr>: address unavailable` | 端口被占或地址不可绑 | 换端口（`--port` / `--ws-port`）；不显式传端口时会在 `preferred…preferred+9` 内自动顺延 |
| `HTTP server started but /api/health is not servable` | 启动自检失败：listener 起来了但路由不可达 | 换端口重试；检查是否有代理/防火墙拦截回环 |
| `the HTTP entry point requires optional dependencies (missing 'aiohttp')` | 没装 http extra | `pip install "heagent[http]"` |
| `WebSocket support requires websockets` | 没装 ws 依赖 | `pip install "heagent[http]"` |
| `sandbox backend ... unavailable`（启动日志 WARNING） | 指定后端不可用，已显性降级为宿主执行 | 装 firejail / 起 docker daemon；或 `--sandbox passthrough` 明确接受零隔离 |
| `workflow role 'X' is unavailable` | `/goal` 声明的角色在技能库里找不到 | 把角色包放到 `.heagent/skills/<role>/` 或 `~/.heagent/skills/`（技能库全局优先） |
| `workflow package 'X' is unavailable under the skill library` | `/goal` 绑定的工作流包不存在 | 确认 `.heagent/skills/<pkg>/SKILL.md` 存在且 frontmatter 的 `canonical_id` 对得上 |

> 工具被拦下时**不会**在终端打一行自由文本，而是在工具结果里给 `is_error` 与正文、并发出
> `tool_call_blocked` 事件——按上面的[框架异常](#二框架异常)节查。

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
