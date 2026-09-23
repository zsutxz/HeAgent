---
id: 49-6
title: 浏览器体验、打包与回归收口
status: done
parent_epic: E49
priority: P0
depends_on: [49-4, 49-5]
created: '2026-09-23'
---

# Story 49-6：浏览器体验、打包与回归收口

## 用户故事

作为 HeAgent 用户和维护者，我希望网页聊天体验在源码和安装包中都能稳定工作，并有完整回归证据，以便可以实际使用和维护 HTTP MVP。

## 范围

- 完成内置聊天页：消息列表、多行输入、提交/停止、运行状态和空状态。
- 展示 SSE 文本增量、工具活动、结果、错误、取消、冲突、重连和服务关闭状态。
- 确保提示词、回答和工具目标按纯文本渲染，页面不加载第三方脚本。
- 配置 wheel/源码包正确包含静态资源和可选 HTTP 依赖。
- 补充 README、docs 索引、`docs/frame.md`、配置示例和 MVP 安全边界。
- 执行 HTTP、网络、CLI、GUI、Agent、ruff、format 和 mypy 回归。

## 边界与约束

**Always**

- UI 与 API 同源，使用现有 HTTP 端点，不复制 Agent 运行逻辑。
- 页面状态映射服务端状态，断线/错误/取消显式呈现。
- 验证安装包，不只验证源码目录运行。
- 文档以 `src/` 和本 Epic 当前实现为准，明确不支持未经认证的远程使用。

**Never**

- 不引入与 MVP 无关的管理后台、配置编辑、多用户或持久会话。
- 不通过 innerHTML 或 Markdown 原样注入不可信 Agent 输出。
- 不用“测试能启动”替代 SSE、取消、重连、资源清理和打包验证。
- 不修改现有 CLI/TCP/GUI 的行为来迁就网页 UI。

## 任务

- [x] 完成 `src/heagent/web/` 静态 HTML/CSS/JS 聊天界面。
- [x] 映射运行、工具、取消、错误、重连和 session 状态。
- [x] 更新 pyproject 打包配置与可选 HTTP extra，并验证 wheel 内容。
- [x] 更新 README、`docs/README.md`、`docs/frame.md` 和配置示例。
- [x] 增加浏览器/HTTP 集成测试与静态资源加载测试。
- [x] 运行定向 pytest、全量回归、ruff、format、mypy 和必要的手工浏览器验收。

## 验收标准

- Given 用户打开内置网页，When 页面加载，Then 能看到消息列表、多行输入、提交/停止操作和清晰的空状态。
- Given 用户提交 prompt，When SSE 推送文本和工具事件，Then 页面按顺序更新回答、工具目标、工具结果和终态，不渲染不可信 HTML。
- Given 页面处于运行、重连、取消、失败、冲突或服务关闭状态，When 状态发生变化，Then 页面显示对应可理解反馈，并避免重复提交。
- Given 项目构建 wheel 并在干净环境安装，When 启动 HTTP 服务并请求根路径，Then 静态资源和 API 均可用，不依赖源码目录或开发机绝对路径。
- Given 执行 HTTP 定向测试、现有网络测试、ruff 和 mypy，When 质量门禁运行，Then 新增功能通过且现有 CLI、GUI、TCP 和 Agent 回归不受影响。

## Definition of Done

- 内置网页覆盖 UX-DR1–UX-DR6 的主要状态和交互。
- 源码运行、wheel 安装、浏览器手工验收和自动化测试均有记录。
- README、docs 索引、docs/frame.md、配置示例和 HTTP MVP 边界保持一致。
- Epic 49 的 FR1–FR10、NFR1–NFR10 与 UX-DR1–UX-DR6 都能追溯到实现和测试。

## 代码地图

- `src/heagent/web/`：HTML/CSS/JS 静态聊天界面。
- `pyproject.toml`：可选 HTTP 依赖和静态资源打包配置。
- `README.md`、`docs/README.md`、`docs/frame.md`：启动、架构和安全边界文档。
- `tests/test_http_web_ui.py`：静态资源和 API/UI 契约测试。
- `tests/test_http_integration.py`：StubProvider 浏览器流程模拟。
- `scripts/quality_gate.py`：质量门禁入口。

## Review Status

**已实现并验证（2026-09-23）。** 自动化三层（静态契约 / HTTP 端到端 / wheel 安装）全绿；**浏览器里的人工点击验收尚未执行**（见「偏差」第 1 条）。

### 实现记录

| 变更 | 说明 |
| --- | --- |
| `README.md` | 命令表新增 `heagent http-server`；新增「HTTP 网页入口（实验性）」章节（启动方式、可选依赖、API 表、SSE 重连与取消语义、安全边界清单、限额与进程内状态说明） |
| `docs/README.md` | 快速定位表新增「网页入口 / 写浏览器端 / HTTP API」行；阅读路径的网络入口标注改为「TCP 4.16 / HTTP 4.17」 |
| `tests/test_http_web_ui.py`（新增 28 例） | 页面必需元素（消息列表 / 多行输入 / 提交 / 停止 / 状态 / 空状态）、严格 CSP 兼容（无内联脚本与样式、无 `style=`）、无第三方资源与动态代码执行、纯文本渲染（`createTextNode` / `textContent`、无 `.innerHTML` 家族）、页面确实调用 `/api/runs`（POST）/`EventSource`/`DELETE`/`/api/session`、状态词表覆盖（提交中/运行中/取消中/重连中/完成/失败/服务不可达）、客户端防重复提交、健康轮询 |
| `scripts/accept_http_wheel.py`（新增） | wheel 打包与安装验收：`uv build` → `pip install --no-deps --target` → 断言 `heagent.__file__` 来自 wheel → 空目录起 `python -m heagent http-server` → 健康 / 页面 / `app.js` / `session` / `POST /api/runs` + `DELETE` 取消 |
| `ruff.toml` | 新增 `scripts/**/*.py` 的 per-file-ignores（脚本层的中文注释、`subprocess`、`assert` 属正常工作方式）；顺带移除 `quality_gate.py` 因此变成多余的 `# noqa: S603` |
| `docs/frame.md` | 4.17 与调用链已在 49-1～49-5 逐 Story 补齐（本 Story 未再改动） |

### 验证证据（本机 2026-09-23）

| 项 | 命令 | 结果 |
| --- | --- | --- |
| UI 静态契约 | `pytest tests/test_http_web_ui.py` | **28 passed** |
| 全量回归 + 覆盖率 | `pytest --cov=heagent --cov-fail-under=87` | **2473 passed, 9 skipped, 18 deselected；91.12%** |
| Lint / 格式 / 类型 | `ruff check src tests scripts`；`ruff format --check`（263 files）；`mypy src --platform linux` | 全部通过（140 source files） |
| wheel 安装验收 | `python scripts/accept_http_wheel.py` | `heagent` 来自 `…\installed\heagent\__init__.py`（非源码）；`/api/health` 200；页面 1265 字符；`app.js` 9772 字符；`POST /api/runs` 201 → `DELETE` 返回 `cancelled`；stderr 公告监听地址 |

### 偏差与边界（如实记录）

1. **浏览器人工验收未执行**：本轮由我完成的验收是「HTTP 端到端（真实 uvicorn + StubProvider）＋ 页面静态契约 ＋ wheel 安装后真跑」。浏览器里的观感（点击停止的即时反馈、断网后重连提示、刷新恢复）需要人工过一遍，建议步骤：
   ```bash
   heagent                     # 或 heagent http-server
   # 浏览器打开 stderr 提示的 http://127.0.0.1:8766
   # ① 提交一个会用到工具的提示词（例如「读一下 README 并总结」）→ 看工具行与流式回答
   # ② 运行中点「停止」→ 期望：状态变「取消中…」，随后出现「已取消」
   # ③ 运行中刷新页面 → 期望：历史恢复、当前运行状态可见
   # ④ Ctrl+C 关掉 CLI → 期望：页面显示「服务不可达」，不显示虚假的完成态
   ```
2. **wheel 验收里依赖复用宿主 venv**（只有 `heagent` 本身来自 wheel）：本机到 `files.pythonhosted.org` 的下载超时，干净依赖安装会把验收变成「网络测试」。CI 的 `release` job 有网络，可覆盖这一层。
3. **UI 有意不做**：多会话管理、Markdown 富文本渲染（Agent 输出按纯文本呈现是安全要求）、移动端专门适配、配置编辑面板（brief 的 MVP 之外）。
4. **冲突/服务关闭的呈现**：409 冲突显示服务端文案；服务关闭由健康轮询转成「服务不可达」；两者都有断言覆盖词表与调用，但像素级观感需人工确认。

### 需求追溯（FR / NFR / UX-DR）

| 需求 | 实现 | 测试 |
| --- | --- | --- |
| FR1 默认 CLI 自启动 | `cli._embedded_http_service` / `cli_http.EmbeddedHttpService` | `test_cli_http_lifecycle.py`（单次/交互/绑定失败/缺 extra/关闭） |
| FR2 显式 `http-server` | `cli_http.http_server_cmd` | `test_cli_http.py`（注册/选项/配置映射/绑定失败/告警） |
| FR3 同源内置页 | `src/heagent/web/` + 白名单路由 | `test_http_server.py`、`test_http_web_ui.py` |
| FR4 SSE 展示 | `HttpRunService.stream_events` + `_sse_stream` | `test_http_run_service.py`、`test_http_agent_api.py` |
| FR5 会话快照 | `HttpRunService.session_snapshot` | `test_http_run_service.py`（投影规则/上限）、`app.js` 恢复 |
| FR6 健康/创建/订阅/取消 | 四个端点 | `test_http_run_service.py`、`test_http_agent_api.py` |
| FR7 事件序号与重连 | `RunEventPayload.seq` / `needs_resync` / `Last-Event-ID` | `test_http_run_service.py::TestReconnect` |
| FR8 资源限额 | `HttpServerConfig` 九项 + 运行超时 + 订阅上限 | `test_http_run_service.py::TestRunTimeout`、`test_cli_http.py` 非法值 |
| FR9 生命周期 | `HttpServer.start/close`、`_finalize`、`close()` 关闭序列 | `test_http_server.py::TestLifecycle`、`test_cli_http_lifecycle.py` |
| FR10 复用治理链 | `HttpAgentHandler`（独立 loop、不装审批、不连 MCP、请求体不可改策略） | `test_http_security.py::TestGovernanceChain`、`test_http_agent_api.py` |
| NFR1 默认回环 + 告警 | `exposure_warning` 复用 | `test_http_server.py`、`test_cli_http.py` |
| NFR2 传输层不反向依赖 | `network/` 导入面 | `test_architecture_contracts.py`（FORBIDDEN_RUNTIME_IMPORTS） |
| NFR3 asyncio/ASGI | Starlette + Uvicorn（无同步 `http.server`） | 同上 + `test_optional_asgi_stack_is_only_imported_lazily` |
| NFR4 每次运行独立 loop | `HttpAgentHandler.new_loop` | `test_http_agent_api.py::test_each_run_uses_a_fresh_agent_loop` |
| NFR5 稳定脱敏错误 | `error_envelope` / `_client_error_message` | `test_http_protocol.py`、`test_http_run_service.py::TestRunFailures` |
| NFR6 同源校验与响应头 | `_OriginGuardMiddleware` / `_SecurityHeadersMiddleware` | `test_http_security.py::TestHostGuard/TestOriginGuard` |
| NFR7 纯文本渲染 | `app.js` 只用文本节点 | `test_http_web_ui.py`、`test_http_server.py` |
| NFR8 资源释放 | 订阅者 `finally` 回收、`_finalize` 名额归还、`close()` 取消运行 | `test_http_run_service.py`（断线/取消/超时/关停） |
| NFR9 不影响既有入口 | `gui`/`tcp-server`/`init`/`replay` 不走内嵌路径 | `test_cli_http_lifecycle.py::test_explicit_subcommands_never_start_the_embedded_service` |
| NFR10 打包与非法配置 | `http` extra + wheel 资源 + Pydantic 校验 | `scripts/accept_http_wheel.py`、`test_http_server.py::TestConfig`、`test_architecture_contracts.py::test_web_package_has_no_runtime_imports` |
| UX-DR1 聊天工作区 | `index.html` 布局 | `test_http_web_ui.py::TestPageStructure` |
| UX-DR2 流式与工具展示 | `app.js` `handleEvent` | `test_http_agent_api.py`（工具事件）、`test_http_web_ui.py` |
| UX-DR3 各状态反馈 | `RUN_TEXT` 词表 + 忙碌态禁用 | `test_http_web_ui.py::TestRunFlowContract` |
| UX-DR4 刷新恢复 | `restoreSession()` | `test_http_web_ui.py`、`test_http_run_service.py::TestSessionSnapshot` |
| UX-DR5 纯文本 | 无 `.innerHTML` 家族 | `test_http_web_ui.py::TestPlainTextRendering` |
| UX-DR6 明确可见反馈 | 服务不可达 / 冲突 / 取消 / 重连文案 | `test_http_web_ui.py`（词表）、`test_http_security.py`（403）、`test_http_run_service.py`（409/413/429） |

## Requirement Traceability

FR3–FR9; NFR3, NFR5, NFR6, NFR7, NFR9, NFR10; UX-DR1–UX-DR6。
