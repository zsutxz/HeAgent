---
id: 49-5
title: HTTP 安全边界与可观测性
status: done
parent_epic: E49
priority: P0
depends_on: [49-3, 49-4]
created: '2026-09-23'
---

# Story 49-5：HTTP 安全边界与可观测性

## 用户故事

作为 HeAgent 维护者，我希望 HTTP 入口明确暴露风险并保护浏览器状态变更，以便本机服务不会被误当成认证完成的远程 API。

## 范围

- 复用 `network.exposure` 的回环判定和非回环告警。
- 对状态变更请求执行 Host/Origin 同源校验，拒绝宽泛 CORS。
- 为静态/API/SSE 响应设置 CSP、nosniff、禁止 framing 等安全头。
- 统一错误脱敏和日志字段，避免正文、凭据和敏感工具输出泄漏。
- 明确 HTTP 入口不自动连接 MCP、不读取 stdin 审批，并继续走现有工具治理链。

## 边界与约束

**Always**

- 默认 localhost 仍按不可信输入处理；回环不是认证边界。
- 非回环绑定启动前后都给出明确风险提示。
- 用户可见文本按纯文本处理，API 错误有界且稳定。
- 日志记录 request/run id、状态、耗时和错误类别，不记录 prompt/answer 正文。

**Never**

- 不把随机路径、CORS 或 localhost 判断当作身份认证。
- 不把 traceback、API key、绝对路径或未经处理的工具输出返回客户端。
- 不让 HTTP 请求修改 Provider、模型、system prompt、工具策略、沙箱或迭代预算。
- 不在无用户交互的 HTTP 进程中安装 stdin 审批处理器或自动接入 MCP server。

## 任务

- [x] 接入 `exposure_warning` 并统一 HTTP 启动告警。
- [x] 实现 Host/Origin 校验和状态变更请求拒绝。
- [x] 添加安全响应头和静态资源 CSP，确认页面纯文本渲染。
- [x] 实现 HTTP 错误映射、日志脱敏和 request/run 观测字段。
- [x] 增加 MCP 未连接、审批 fail-safe 和 Agent 治理链回归测试。

## 验收标准

- Given 服务绑定非回环地址，When 服务启动，Then stderr 和日志给出统一的无认证、无 TLS、非生产安全边界告警。
- Given 请求来自不匹配的 Host 或 Origin，When 执行状态变更操作，Then 服务拒绝请求且不创建、取消或修改 Agent run。
- Given 浏览器加载静态页面，When 响应返回，Then 设置 CSP、`X-Content-Type-Options: nosniff`、禁止 framing 等安全响应头，页面不加载第三方脚本。
- Given Provider、Agent 或工具抛出异常，When API/SSE 返回错误，Then 客户端只收到稳定脱敏文案，服务端日志包含有限诊断字段而不记录 prompt、answer、密钥或敏感工具输出。
- Given HTTP 入口处理工具调用或审批型工具，When Agent 执行，Then 仍经既有治理链；不自动连接 MCP，不读取服务进程 stdin 进行交互审批。

## Definition of Done

- HTTP 复用 `network.exposure` 的地址判定和告警文案。
- Origin/Host、CSP、响应头和纯文本渲染有测试。
- 日志字段包含 request/run id、状态、耗时和错误类别，但不含正文与凭据。
- 架构契约测试确认 network 层依赖方向和 HTTP 入口安全边界。

## 代码地图

- `src/heagent/network/http_server.py`：请求来源校验、响应头、日志和错误边界。
- `src/heagent/network/exposure.py`：复用既有回环判定和告警。
- `src/heagent/cli_http.py`：HTTP 入口安全配置与 MCP/审批禁用决策。
- `src/heagent/web/`：CSP 兼容的静态页面和纯文本渲染。
- `tests/test_http_security.py`：来源、响应头、脱敏和治理链测试。
- `tests/test_architecture_contracts.py`：network 依赖方向回归。

## Review Status

**已实现并验证（2026-09-23）。**

### 实现记录

| 变更 | 说明 |
| --- | --- |
| `src/heagent/network/http_server.py` | 新增同源防线与观测：`_OriginGuardMiddleware`（Host 唯一且匹配本 listener、Origin 同源、拒绝 `null`/跨站/重复 Host/forwarded-* 头，403 `origin_forbidden`）、`_AccessLogMiddleware`（每请求一条 `event=request` 日志 + 响应头 `x-request-id`：只记 id/method/path/status/elapsed_ms）、`_canonical_authority` / `_allowed_hosts` / `_allowed_ports` / `_split_authority` / `_request_origin_violation` / `_send_json`（中间件层发 JSON 信封）、`_UNTRUSTED_FORWARD_HEADERS` / `_LOOPBACK_HOST_ALIASES`；`_RunRecord.created_at` + `elapsed_ms()`；`_finalize` 统一终态观测（`event=run_started` / `event=run_finished`，含状态与耗时） |
| `tests/test_http_security.py`（新增 28 例） | Host 允许/拒绝矩阵（含等价回环写法、端口不符、DNS rebinding 域名、重复 Host、forwarded 头）、Origin 矩阵（同源、缺 Origin 放行、`null`、跨站、https 变体）、**被拒状态变更无副作用**（提交不建 run、DELETE 不取消）、403 仍带安全头与 request id、日志不含 prompt/answer/工具输出正文、`x-request-id` 唯一、审批型工具 fail-safe 阻断（含「文件确实没被写」断言）、不装 stdin 审批、不连 MCP |
| `docs/frame.md` | 4.17 新增「来源校验」「可观测性」两行；调用链补中间件层级顺序 |

### 验证证据（本机 2026-09-23）

| 项 | 命令 | 结果 |
| --- | --- | --- |
| 定向测试 | `pytest tests/test_http_security.py` | **28 passed** |
| 全量回归 + 覆盖率 | `pytest --cov=heagent --cov-fail-under=87` | **2445 passed, 9 skipped, 18 deselected；91.12%** |
| Lint / 格式 / 类型 | `ruff check`；`ruff format --check`（261 files）；`mypy src --platform linux` | 全部通过（140 source files） |

### 决策与边界（如实记录）

1. **回环绑定时接受三个等价本机写法**（`127.0.0.1` / `localhost` / `[::1]`）：AD-6 要求「唯一 authority」，但三者在浏览器地址栏里都指向同一 listener，只认一个会让「本机自用」这个主用例莫名其妙地 403。**非回环绑定不额外放宽**（只认配置的那个名字），DNS rebinding 防护（`evil.example` 被拒）不受影响。
2. **`port=0`（随机端口，仅程序化/测试）时不再校验端口**：构建 app 时还不知道实际端口；CLI 与 `HTTP_PORT` 都限定 1..65535，生产路径永远有确定端口。
3. **缺少 `Origin` 视为非浏览器客户端并放行**：Host 已校验；curl / 脚本不带 Origin，硬性要求会让「本机自动化」不可用（AD-6 明确允许这一分支）。
4. **转发头一律拒绝而非忽略**：MVP 不支持反向代理部署；拒绝比忽略更可诊断（日志里会是 `reason=untrusted forwarded header`）。
5. **日志的既有边界**：工具名与作用对象（路径/命令摘要）仍会经引擎的 `LoggingObserver` 进日志——这是 CLI/GUI 同样存在的行为（frame 五已有条目）；本 Story 保证的是**不记 prompt / 回答 / 工具输出正文**，有 caplog 断言钉住。
6. **同源防线不是认证**：能连上回环端口的本机进程可以伪造 Header 直接调 API（frame 的「HTTP 入口非安全边界」条目已写明）。

## Requirement Traceability

FR10; NFR1, NFR2, NFR5, NFR6, NFR7; UX-DR5, UX-DR6。
