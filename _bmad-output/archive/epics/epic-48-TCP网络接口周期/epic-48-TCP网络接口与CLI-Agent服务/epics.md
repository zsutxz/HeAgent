# Epic 48：TCP 网络接口与 CLI Agent 服务

> 规划日期：2026-09-22（中国标准时间）
> 状态：done（2026-09-22 交付，2026-09-23 回写状态）
> 规划阶段：PRD、Architecture、Story 与 Sprint Plan 已完成；48-1 ~ 48-6 全部交付，Epic 已收口（周期回顾见 `../../retrospective-epic-48.md`）

## Epic Goal

为 HeAgent 增加一个可选的异步 TCP 服务入口：CLI 作为 TCP Server 接收外部客户端请求，将请求交给现有 `AgentLoop` 处理，并通过同一 TCP 连接返回结构化结果。

该能力用于本机脚本、局域网实验和其他程序调用 HeAgent。它不是生产级 Web/API 服务，也不改变现有 CLI、AgentLoop、Provider 或工具治理链的职责边界。

## 产品边界

### MVP 包含

- `heagent tcp-server` CLI 子命令。
- 基于 `asyncio.start_server()` 的异步 TCP Server。
- UTF-8 JSON Lines 协议，以换行作为单条消息边界。
- 单请求、单响应、默认无状态执行。
- 请求进入现有 `AgentLoop`，不绕过 `PolicyEngine → ToolExecutor → SafetyGuard → handler` 工具执行链。
- 默认监听 `127.0.0.1`。
- 请求大小、连接数、Agent 并发数、空闲时间和处理时间限制。
- 稳定的成功响应与错误响应模型。
- 协议、半包、并发、断开、超时和 Agent 异常测试。

### MVP 不包含

- TCP Client CLI 模式。
- 长连接多轮会话。
- TCP 流式文本或工具事件响应。
- 内置认证、TLS、mTLS 或多租户。
- 由客户端修改 Provider、工具权限、沙箱或系统配置。
- 把 TCP 连接能力注册为 Agent Tool。
- UDP、HTTP、WebSocket、服务发现、集群和生产部署方案。

## 初步通信契约

### 请求

```json
{"id":"req-001","prompt":"请解释 asyncio"}
```

第一版只承诺 `id` 与 `prompt` 两个字段。未知字段、空 prompt、非法 JSON 和超过大小限制的请求必须返回稳定错误，不得导致服务进程崩溃。

### 成功响应

```json
{"id":"req-001","ok":true,"result":"asyncio 是 Python 的异步 I/O 框架。"}
```

实现阶段可在不破坏上述字段的前提下增加模型和 usage 元数据。

### 失败响应

```json
{"id":"req-001","ok":false,"error":{"code":"agent_error","message":"agent execution failed"}}
```

错误响应不得默认泄露 API Key、本地绝对路径、完整异常堆栈或未经处理的敏感工具输出。

## 初步架构约束

```text
network.protocol / network.tcp_server
              ↓
        CLI / wiring 组合根
              ↓
           AgentLoop
```

- TCP 传输层不得导入 `cli.py` 或反向导入 `agent` 以外的高层模块。
- 网络请求与响应使用 Pydantic 模型，不使用跨模块裸字典。
- TCP Server 通过注入的 request handler 调用 AgentLoop，避免网络层持有 Provider 构造逻辑。
- 现有单次 CLI、交互 CLI、GUI 和 `/goal` 行为保持兼容。
- 网络接口默认关闭，不因导入模块或普通 CLI 启动而自动监听端口。
- `127.0.0.1` 以外的监听属于显式暴露，必须在 CLI/文档中明确无认证风险。

## 初步 Story 列表

> 本列表是 Epic 级拆分，不是已批准的可执行 Story 文件。进入 Story 阶段后，需补充 Given-When-Then、依赖、DoD、代码地图和验证矩阵。

### 48-1：TCP 协议模型与消息边界

定义 Pydantic 请求/响应模型、JSON Lines 编解码、UTF-8 处理、换行分帧、请求大小限制和稳定错误码。

### 48-2：异步 TCP Server 生命周期

实现监听、连接接收、单请求读取、响应写回、连接关闭、客户端提前断开和优雅停止，并通过 handler 注入业务处理。

### 48-3：AgentLoop 请求适配与 CLI 接线

新增 `heagent tcp-server` 子命令，在组合根构造现有运行时，将合法 prompt 交给 AgentLoop，并将最终结果映射为 TCP 响应。

### 48-4：并发、超时与资源限制

增加最大连接数、最大在途 Agent 数、请求超时、空闲超时和取消传播，确保单个客户端失败不影响服务和其他请求。

### 48-5：网络入口安全边界与可观测性

补充 localhost 默认、非本机监听告警、日志脱敏、request id、耗时、结果状态和安全文档，明确 TCP 服务不是认证系统或 OS 安全边界。

### 48-6：TCP 回归测试与开发文档

覆盖协议、半包、并发、断开、超时、Agent 异常、CLI help 和 StubProvider 集成路径，并同步 README、`.env.example`、`docs/frame.md`。

## 初步依赖顺序

```text
48-1 → 48-2 → 48-3 → 48-4 → 48-5 → 48-6
```

48-5 的安全约束应在 48-2/48-3 实现时同步遵守，不应等到最后才补救；实际 Story 执行顺序由后续 Sprint Plan 冻结。

## Epic 验收草案

- 客户端可以通过 TCP 发送一条合法 JSON Lines 请求。
- HeAgent CLI 可以把请求交给现有 AgentLoop 并返回一条对应 `id` 的 JSON 响应。
- 半包、非法请求、超时、客户端断开和 Agent 异常不会导致服务进程崩溃。
- 并发和资源限制生效，单个请求失败不影响其他连接。
- 默认只监听 localhost，显式监听其他地址时有风险提示。
- 原有 CLI、AgentLoop、工具治理链和全量质量门禁保持通过。
- 文档明确协议、启动方式、资源限制和非生产安全边界。

## 待进入下一阶段确认的问题

1. 是否坚持第一版采用“CLI 作为 TCP Server、外部程序作为 TCP Client”。
2. 是否确认 JSON Lines，而不是长度前缀二进制协议。
3. 是否确认第一版无状态、单请求单响应。
4. 是否确认第一版不开放客户端自定义 system prompt、Provider、工具和沙箱配置。
5. 是否确认第一版不做流式 TCP 响应。
6. 最大请求大小、最大 Agent 并发数和默认超时的最终数值。

## 当前状态

Epic 已建立并登记为 `backlog`。下一步应按 BMad 顺序先完成需求澄清/PRD，再完成架构设计，随后更新 Story 拆分；本 Epic 阶段不直接进入代码实现。
