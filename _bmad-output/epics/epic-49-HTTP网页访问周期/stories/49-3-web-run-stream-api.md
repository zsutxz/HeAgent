---
id: 49-3
title: 网页运行 API 与流式 Agent 会话
status: done
parent_epic: E49
priority: P0
depends_on: [49-1, 49-2]
created: '2026-09-23'
---

# Story 49-3：网页运行 API 与流式 Agent 会话

## 用户故事

作为网页用户，我希望提交提示词并实时看到 Agent 回答和工具活动，以便在浏览器中完成一次完整的 HeAgent 运行。

## 范围

- 实现 `POST /api/runs` 创建一次网页 Agent 运行。
- 实现 `GET /api/runs/{run_id}/events` SSE 订阅。
- 映射 `AgentLoop.run_stream()` 的文本、工具调用、工具结果和终态事件。
- 实现单用户会话快照，提供当前运行状态和已完成消息。
- 映射重复提交、未知 run、Agent/Provider 异常为稳定 API 错误。
- 保持服务端 system/provider/model/工具策略/沙箱/迭代预算不可由请求覆盖。

## 边界与约束

**Always**

- 请求体和事件使用 Pydantic 模型，有界校验和序列化。
- 每个 run 新建独立 AgentLoop，服务级 Provider/Engine/记忆存储按现有入口规则共享。
- 文本与工具目标按纯文本传输和呈现；错误文案有界脱敏。
- 运行完成、失败或取消后，SSE 生成器和 Agent task 都得到清理。

**Never**

- 不让 HTTP 请求指定 system、provider、model、工具策略、沙箱或 max_iterations。
- 不把内部 `StreamEvent`/异常对象直接交给 JSON 序列化器。
- 不在重复提交时排队或覆盖在途运行。
- 不从 HTTP 层绕过 PolicyEngine → ToolExecutor → SafetyGuard → handler。

## 任务

- [x] 定义 HTTP run/session/event 请求响应模型和稳定错误码。
- [x] 实现内存单用户 session projection 与 run 状态机。
- [x] 接入 `AgentLoop.run_stream()`，映射文本和工具事件为 SSE。
- [x] 实现 run task 所有权、重复提交保护和异常清理。
- [x] 添加 StubProvider API 集成测试，覆盖成功、工具事件、失败和冲突。
- [x] 让内置页面调用创建运行、事件流和 session 接口。

## 验收标准

- Given 服务健康且没有其他运行，When 客户端向 `POST /api/runs` 提交有界非空 prompt，Then 服务返回唯一 `run_id`，并使用服务端固定配置创建独立 AgentLoop。
- Given 一个运行已创建，When 客户端订阅 `/api/runs/{run_id}/events`，Then SSE 按序发送文本增量、tool_call、tool_result 和终态事件，且字段来自结构化 StreamEvent 映射。
- Given Agent 运行完成，When 客户端收到终态事件，Then 页面显示完整回答、成功状态、可选 usage/model 信息，并把结果纳入当前进程内会话快照。
- Given Agent 或 Provider 失败，When 运行结束，Then 客户端收到稳定的 error 事件，不包含 traceback、密钥或绝对路径，服务仍可接受下一次运行。
- Given 已有一个在途运行，When 客户端再次创建运行，Then API 返回明确的冲突错误，不排队、不覆盖原运行。

## Definition of Done

- API 请求/响应/事件均有 Pydantic 模型和有界序列化。
- 每个 run 使用独立 AgentLoop，服务级共享对象不会覆盖其他 run 的 usage、model 或活动状态。
- SSE 订阅在完成和失败后结束，异常路径不会遗留任务。
- 使用 StubProvider 覆盖成功、工具事件、Agent 异常和重复提交。

## 代码地图

- `src/heagent/network/http_protocol.py`：run/session/event 模型和错误码。
- `src/heagent/network/http_server.py`：API 路由、task 和 SSE 生命周期。
- `src/heagent/cli_http.py`：AgentLoop factory 与服务级共享依赖。
- `src/heagent/web/`：创建运行、事件订阅和会话恢复脚本。
- `tests/test_http_agent_api.py`：StubProvider 端到端测试。

## Review Status

**已实现并验证（2026-09-23）。** 范围与验收标准实现前确认；实现后按「意图级」核对。

### 实现记录

| 变更 | 说明 |
| --- | --- |
| `src/heagent/network/http_protocol.py` | 新增 `RunStatus`（含 `TERMINAL_RUN_STATUSES`）、`RunEventKind`、`HttpUsage`、`RunRequest`（`extra="forbid"` + 非空白校验）、`RunCreatedResponse`、`RunEventPayload`、`RunOutcome`、`SessionMessage`、`SessionResponse`、`clip_text`（截断到 `MAX_EVENT_TEXT_CHARS=16384` 并显式标记） |
| `src/heagent/network/http_server.py` | 新增 `HttpRunService`（单用户会话 + 运行记录 + 事件 ring buffer + 订阅广播）、`_RunRecord`（`claim_terminal` 首个终态获胜 / `close_subscribers`）、`RunEventPublisher`（入口层事件出口，`seq`/截断/广播都在服务层）、`HttpRunConflictError`、`_client_error_message`（duck-typing 取 `HeAgentError.message`，否则固定兜底）、`_read_body`（按块读、超限即断）、`format_sse`、`_build_run_endpoints`、`_build_run_endpoints` 抽出的三个端点；`build_http_app(config, version=, run_service=)` 在注入 service 时才注册运行路由；`HttpServer(config, version=, run_service=)` 与 `close()` 关闭序列（先 `service.close()` 再关 listener） |
| `src/heagent/cli_http.py` | 新增 `HttpAgentHandler`（每运行新建 `AgentLoop`、`run_stream` → 协议事件映射、自建 engine 不装审批、不连 MCP）、`_to_http_usage`、`_resolve_model`；`build_http_service(settings, executor=)`；`http-server` 命令新增 `--model/--system/--max-iterations/--soul/--sandbox` 并装配 handler + `HttpRunService` + `load_agent_roles()` |
| `src/heagent/cli.py` | `_embedded_http_service(settings, provider)` 构造并注入 `HttpAgentHandler`（默认 CLI 的内嵌服务同样带运行入口） |
| `src/heagent/web/app.js` | 接线运行 API：提交 → `POST /api/runs`（409/400/413 的稳定文案）→ `EventSource` 订阅；渲染 text / tool_call / tool_result / done / error / cancelled / timed_out；加载时 `GET /api/session` 恢复历史；运行中禁用提交；连接层断线如实显示 `连接已断开`（不假装完成） |
| `src/heagent/web/styles.css` | 新增 `.entry-assistant` 样式 |
| `tests/network/test_http_run_service.py`（新增 21 例） | 运行创建/单运行冲突/无 service 时 404、请求体边界（extra 字段/空白 prompt/坏 JSON/超大 body）、事件文本有界、SSE 顺序与 seq 单调、SSE 头与帧尾、终态后流结束、失败脱敏与「失败后仍可再运行」、失败不投影、会话快照与历史上限、淘汰后 `unknown_run`、关停取消在途 run（`cancelled` 终态） |
| `tests/test_http_agent_api.py`（新增 7 例） | 真实 uvicorn + 真实 `HttpAgentHandler` + StubProvider：端到端提交与 session 投影、真实工具事件（`tool_call`/`tool_result`）、未知工具回 `is_error` 结果、provider 错误脱敏且服务继续可用、两次运行各自报告 model/usage、不装审批、不连 MCP、每次运行新建 loop |
| `tests/test_cli_http_lifecycle.py` | 新增 `test_default_cli_exposes_the_run_api`：默认 CLI 的内嵌服务确实带运行入口（真实 listener + stub provider 走完 `POST /api/runs` → SSE `done` → session 投影） |
| `tests/test_cli_http.py` | `http-server` 测试补 `_build_provider` 桩（命令现在会装配 Agent handler） |
| `docs/frame.md` | 4.17 新增「运行 API」「事件与投影」「运行隔离」三行；调用链补运行 API/SSE/session 与终态语义 |

### 验证证据（本机 2026-09-23，Windows 3.13）

| 项 | 命令 | 结果 |
| --- | --- | --- |
| 定向测试 | `pytest tests/network tests/test_http_agent_api.py tests/test_cli_http.py tests/test_cli_http_lifecycle.py` | **202 passed** |
| 全量回归 + 覆盖率 | `pytest --cov=heagent --cov-fail-under=87` | **2397 passed, 9 skipped, 18 deselected；91.03%** |
| Lint / 格式 / 类型 | `ruff check`；`ruff format --check`（260 files）；`mypy src --platform linux` | 全部通过（140 source files） |

### 偏差与边界（如实记录）

1. **超时（`timed_out`）的代码路径已就位但验证归 49-4**：`RunStatus.TIMED_OUT` 与 `_execute` 的终态机制一次写好（避免 49-4 重写终态处理），但「运行超时」的触发与断言属 49-4 的限额 Story。
2. **`Last-Event-ID` 参数已实现但未接线**：`HttpRunService.stream_events(record, last_event_id=)` 已支持「只重放严格大于 N 的事件」，但请求头解析、`resync_required`（409）与心跳在 49-4。
3. **`max_connections` 仍由 Uvicorn `limit_concurrency` 承担**（49-1 的边界延续）；应用层的运行并发由 `max_inflight_runs` 非等待式名额把住。
4. **交互细节待 49-4/49-6**：停止按钮此刻保持 disabled（取消 API 在 49-4 接线）；页面未做重连提示（49-4）。
5. **失败不投影、成功才投影** 是 AD-3 的硬性要求：`_project` 只在 `COMPLETED` 时写历史，越权路径有专门测试（`test_failed_run_is_not_projected_into_session`）。

## Requirement Traceability

FR3–FR6, FR10; NFR4, NFR5, NFR8; UX-DR1, UX-DR2, UX-DR3, UX-DR6。
