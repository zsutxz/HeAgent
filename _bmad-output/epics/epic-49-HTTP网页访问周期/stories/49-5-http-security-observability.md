---
id: 49-5
title: HTTP 安全边界与可观测性
status: backlog
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

- [ ] 接入 `exposure_warning` 并统一 HTTP 启动告警。
- [ ] 实现 Host/Origin 校验和状态变更请求拒绝。
- [ ] 添加安全响应头和静态资源 CSP，确认页面纯文本渲染。
- [ ] 实现 HTTP 错误映射、日志脱敏和 request/run 观测字段。
- [ ] 增加 MCP 未连接、审批 fail-safe 和 Agent 治理链回归测试。

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

Story 范围与验收标准已确认，待实现验证。

## Requirement Traceability

FR10; NFR1, NFR2, NFR5, NFR6, NFR7; UX-DR5, UX-DR6。
