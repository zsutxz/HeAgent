---
id: 49-1
title: HTTP 服务启动与本机入口
status: done
parent_epic: E49
priority: P0
depends_on: []
created: '2026-09-23'
---

# Story 49-1：HTTP 服务启动与本机入口

## 用户故事

作为 HeAgent 用户，我希望启动 HTTP 服务后能打开一个内置网页并确认服务健康，以便知道浏览器入口已经准备好。

## 范围

- 选择并接入轻量 ASGI HTTP 框架，保留可选依赖边界。
- 定义 HTTP 配置、健康响应、错误响应和静态资源装载约束。
- 提供 `heagent http-server` 显式命令、默认回环地址和默认端口 `8766`。
- 提供 `/api/health` 与根路径静态聊天页。
- 处理绑定失败、非法配置和服务关闭，不遗留 listener 或后台任务。
- 保持 `gui`、`tcp-server`、`init`、`replay` 等其它显式子命令不监听 HTTP。

## 边界与约束

**Always**

- 默认只绑定 `127.0.0.1`，非回环绑定复用 `network.exposure` 的告警语义。
- HTTP 传输层只处理请求、响应、静态资源和生命周期；Agent 装配由入口层完成。
- API 错误稳定、有界、脱敏；静态页不加载第三方脚本。
- 配置由 Pydantic 校验，CLI 覆盖不写回 Settings 单例。

**Never**

- 不因导入 HTTP 模块而隐式启动服务。
- 不在网络层构造 Provider、AgentLoop、EngineContainer 或 ToolRegistry。
- 不把绑定失败静默降级为“服务未启动但命令继续”。
- 不把根路径静态页面当作认证机制或远程安全边界。

## 任务

- [x] 新增 HTTP 配置与协议模型，默认 `127.0.0.1:8766`，校验地址、端口和资源上限。
- [x] 新增 HTTP 生命周期服务和依赖注入入口，提供 start/serve/close 语义。
- [x] 新增 `heagent http-server` Click 子命令及启动地址输出。
- [x] 新增 `/api/health` 和根路径静态资源挂载。
- [x] 配置 wheel 包含静态资源，并增加源码/wheel 加载测试。
- [x] 增加 HTTP 网络层反向依赖架构测试。

## 验收标准

- Given 未显式配置 HTTP 地址和端口，When 用户执行 `heagent http-server`，Then 服务只绑定 `127.0.0.1:8766`，并在 stderr 输出可访问地址。
- Given HTTP 服务已启动，When 浏览器请求 `/api/health`，Then 服务返回稳定 JSON 健康结果，不包含密钥、绝对路径或 traceback。
- Given HTTP 服务已启动，When 浏览器请求根路径，Then 返回随 Python 包分发的内置静态聊天页，且页面不依赖第三方脚本。
- Given 端口已被占用或配置值非法，When 服务启动，Then 命令显式失败并给出可诊断错误，不声称服务已监听、不遗留后台任务。
- Given 用户执行 `gui`、`tcp-server`、`init` 或 `replay` 子命令，When 命令启动，Then 不因 HTTP 模块导入而创建 HTTP listener。

## Definition of Done

- HTTP 配置和协议模型有 Pydantic 校验，默认值与文档一致。
- HTTP 传输层不反向导入 Agent、Provider、Engine 或 CLI 组合根。
- 静态资源在源码运行和 wheel 安装场景均可加载。
- 覆盖健康、根路径、端口冲突、非法配置和非 HTTP 子命令不监听的测试已加入。
- 通过定向 pytest、ruff 和 mypy 检查。

## 代码地图

- `src/heagent/network/http_server.py`：HTTP 生命周期与传输层。
- `src/heagent/network/http_protocol.py`：健康/错误/配置模型。
- `src/heagent/cli_http.py`：HTTP 入口层与 Click 命令。
- `src/heagent/web/`：内置静态页面资源。
- `tests/network/test_http_server.py`：生命周期、健康和边界测试。
- `tests/test_cli_http.py`：命令注册、绑定失败和非 HTTP 子命令回归。

## Review Status

**已实现并验证（2026-09-23）。** Story 范围与验收标准在实现前确认；实现后按「意图级」核对如下。

### 实现记录

| 变更 | 说明 |
| --- | --- |
| `src/heagent/network/http_protocol.py`（新增） | 协议契约：`HttpErrorCode`（封闭 14 码，覆盖 Epic 49 全部故事的错误语义）、`HttpErrorEnvelope`、`HealthResponse`（字段封闭）、`sanitize_message`（客户端文案唯一出口，折叠空白 + 截断到 500 字符，**返回值不超过上限本身**） |
| `src/heagent/network/http_server.py`（新增） | 传输层：`HttpServerConfig`（9 个有界字段，默认值与 `HTTP_*` 一致）、`build_http_app`（健康检查 + 白名单静态资源 + 安全响应头）、`HttpServer`（`start` / `serve_forever` / `close`）、`read_web_asset`（`importlib.resources.files("heagent.web")` 唯一查找方式）；ASGI 栈经 `importlib.import_module` 延迟加载，缺依赖抛 `HttpDependencyError` |
| `src/heagent/cli_http.py`（新增） | 入口层组合根：`build_server_config`（CLI 覆盖不写回 Settings）、`_serve_http`、`http_server_cmd`（9 个限额参数 + `--host` / `--port`）；绑定失败/缺依赖转 `ClickException`，`KeyboardInterrupt` 安静退出 |
| `src/heagent/web/`（新增包） | `__init__.py` + `index.html` + `app.js` + `styles.css`：布局（消息列表 / 多行输入 / 发送 / 停止 / 状态）、健康状态轮询、纯文本渲染工具函数；无第三方资源、无内联脚本或样式 |
| `src/heagent/config.py` | 新增 9 个 `http_*` 设置（`http_host` / `http_port` / `http_max_connections` / `http_max_inflight_runs` / `http_max_request_bytes` / `http_event_buffer_size` / `http_run_history_size` / `http_request_timeout` / `http_shutdown_timeout`），无 `HTTP_ENABLED` 开关 |
| `src/heagent/cli.py` | 注册 `http-server` 命令（模块尾部 import，保持 `heagent.cli` 命名空间可用） |
| `pyproject.toml` | 新增直接声明的 `http` extra（`starlette>=1.3.1,<1.4` / `uvicorn>=0.50.1,<0.51`），不再依赖 MCP 的传递依赖 |
| `.github/workflows/ci.yml` | lint job 装 `.[dev,gui,http]`（mypy 需要 starlette 类型），test / coverage / goal-smoke / benchmark / integration 装 `.[dev,http]` |
| `.env.example` | 新增第 19 节（HTTP 网页入口：定位、同源/渲染纪律、可选依赖、9 个键与默认值） |
| `docs/frame.md` | 配置表 9 行、`network/` 模块描述、入口表、目录树、调用链新增「HTTP 网页入口流程」、新增 4.17 段 |
| `tests/network/test_http_protocol.py`（新增 25 例） | 错误码集合、文案净化边界、信封形状、健康响应字段封闭、页面 `maxlength` 与协议常量一致 |
| `tests/network/test_http_server.py`（新增 30 例） | 健康/静态页/穿越拒绝/安全头/错误信封/config 校验/真实 listener 生命周期（绑定、幂等、绑定失败、就绪回滚、关闭后拒绝连接、告警接线）/包内资源一致性 |
| `tests/test_cli_http.py`（新增 25 例） | 命令注册与选项、配置映射（含 env 驱动与不污染单例）、非法值 exit 2、绑定失败 exit 1 且不谎报监听、缺依赖安装提示、回环不告警/非回环一行告警、普通 CLI 不构造 listener |
| `tests/test_architecture_contracts.py` | `heagent.cli_http` 加入入口层模块表；新增「可选 ASGI 栈只允许延迟导入」「`heagent/web/` 零运行时导入」两条契约 |

### 验证证据（本机 2026-09-23，Windows 3.13）

| 项 | 命令 | 结果 |
| --- | --- | --- |
| 定向测试 | `pytest tests/network/test_http_protocol.py tests/network/test_http_server.py tests/test_cli_http.py tests/test_architecture_contracts.py` | **96 passed** |
| 全量回归 + 覆盖率 | `pytest --cov=heagent --cov-fail-under=87` | **2359 passed, 9 skipped, 14 deselected；90.98%**（门限 87） |
| Lint / 格式 | `ruff check src tests scripts`；`ruff format --check src tests scripts` | 通过（257 files） |
| 类型 | `mypy src`；`mypy src --platform linux` | Success（140 files，两平台一致） |
| wheel 打包 | `uv build --wheel` → 校验 zip 内容 + `sys.path` 指向 wheel 用 `importlib.resources` 读取 | `heagent/web/{__init__.py,index.html,app.js,styles.css}` 在内；loader = `zipimporter`；三个资源均可读（脚本 `.heagent/tmp/check_wheel_web.py`） |
| 端到端冒烟 | 真实子进程 `python -m heagent http-server --port <随机>` + httpx | stderr 公告 `[http] listening on http://127.0.0.1:<port>`；`/api/health` 200（`service=heagent-http`、`schema_version=1`）；`/` 200 `text/html`；`/app.js` 200 `text/javascript`；`/nope.js` 404 `not_found`；`POST /api/health` 405 `method_not_allowed`；CSP / nosniff 存在（脚本 `.heagent/tmp/smoke_http_server.py`） |
| Ctrl+C 收尾 | `CTRL_BREAK_EVENT` 发给独立进程组 → 0.01s 内退出、无 traceback、端口立即可重绑（脚本 `.heagent/tmp/smoke_http_ctrlc.py`） | 通过 |

### 偏差与边界（如实记录）

1. **页面的「发送」尚未接线**：`app.js` 目前对提交只做本地回显 + 「等待运行接口」状态，不含 `POST /api/runs` 与 SSE —— 运行 API 属 Story 49-3。此处刻意不假装提交成功（服务端此时确实没有该端点）。
2. **Ctrl+C 的 `[http] stopped` 提示未在自动化中验证**：无控制台 attach 的子进程收到 `CTRL_BREAK_EVENT` 会被系统直接终止（exit `0xC000013A`），Python 层 `KeyboardInterrupt` 分支未走到；已验证的是「立即退出、无 traceback、端口释放」。真实控制台的提示文案列入 49-6 的手工验收。
3. **`http_max_connections` 交给 Uvicorn `limit_concurrency`**：连接级上限在 ASGI 层无法精确计数（keep-alive 复用），故由服务器实现直接拒绝超限连接；其超限行为（503）在 Story 49-4 的并发测试中覆盖。
4. **wheel 验收目前是手工脚本**：`uv build` + zipimport 读取已实测，但未做成自动化测试（避免默认套件依赖构建工具）；自动化 wheel 验收归 Story 49-6。
5. **`HttpServerConfig.port` 允许 `0`**（操作系统分配随机端口），仅用于程序化/测试；CLI 与设置层限定 1..65535。

## Requirement Traceability

FR2, FR3, FR8, FR9; NFR1, NFR2, NFR3, NFR9, NFR10; UX-DR1, UX-DR6。
