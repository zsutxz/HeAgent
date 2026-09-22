---
stepsCompleted: [step-01-validate-prerequisites, step-02-define-product-scope, step-03-define-requirements]
status: planning
---

# Epic 48 PRD：TCP 网络接口与 CLI Agent 服务

> 规划日期：2026-09-22（中国标准时间）
> 对应 Epic：Epic 48
> 当前状态：in-progress；Story 已就绪，尚未开始实现
> 本文是需求契约，不是实现方案；详细模块设计在后续 architecture 阶段完成。

## 1. 产品概述

为 HeAgent 增加一个可选的 TCP 服务入口，使本机脚本、局域网实验程序或其他 TCP 客户端能够向 HeAgent 发送文本请求，并接收 AgentLoop 处理后的结构化结果。

本能力采用以下固定方向：

```text
外部 TCP Client
      │ UTF-8 JSON Lines
      ▼
HeAgent CLI TCP Server
      │
      ▼
现有 AgentLoop / Engine / Provider
      │
      ▼
TCP JSON 响应
```

TCP 接入是一个新的运行入口，不是新的 Provider，也不是 Agent Tool。它不得绕过现有 AgentLoop、PolicyEngine、ToolExecutor、SafetyGuard 和 handler 执行链。

## 2. 用户与使用场景

### 2.1 目标用户

- 需要从本地脚本调用 HeAgent 的开发者。
- 需要在局域网实验中把其他程序接入 HeAgent 的开发者。
- 需要使用 TCP 而不是 CLI stdin/stdout 传输请求的自动化程序。

### 2.2 主要场景

#### 场景 A：本机脚本请求 Agent

```text
启动 heagent tcp-server
脚本连接 127.0.0.1:8765
发送一条 JSON 请求
等待一条 JSON 响应
读取 result 或 error
```

#### 场景 B：多个客户端并发请求

多个客户端可以同时建立 TCP 连接；服务端限制在途 Agent 数量，单个请求失败不得终止服务或影响其他请求。

#### 场景 C：客户端异常断开

客户端在 Agent 处理完成前断开时，服务端应取消或结束该请求的等待链，释放连接和并发资源，不产生未回收任务。

#### 场景 D：非法或过大请求

服务端拒绝非法 JSON、缺少必需字段、空 prompt 和超过大小限制的消息，并返回可识别错误；服务进程继续运行。

## 3. 产品目标

### 3.1 目标

- 提供一个明确的 `heagent tcp-server` CLI 入口。
- 提供稳定、可解析、可扩展的 TCP 请求/响应协议。
- 将合法请求可靠地适配到现有 AgentLoop。
- 限制连接、请求大小、并发和时间，避免网络入口无限消耗资源。
- 默认不暴露到非本机网络。
- 通过自动化测试覆盖 TCP 分帧、生命周期、异常和 Agent 集成。
- 不破坏现有 CLI、GUI、`/goal` 和库调用方式。

### 3.2 非目标

第一版明确不实现：

- HeAgent 连接外部 TCP 服务的 Client CLI。
- 长连接多轮会话和跨请求上下文。
- TCP 流式文本、工具调用或事件响应。
- 内置认证、TLS、mTLS、用户账号和多租户。
- 客户端动态指定 Provider、system prompt、工具白名单、沙箱策略或迭代预算。
- UDP、HTTP、WebSocket、服务发现、集群、负载均衡和生产部署方案。
- 将 TCP 能力注册为模型可调用工具。

## 4. 产品决策

| 决策 | PRD 结论 |
|---|---|
| 服务方向 | HeAgent CLI 作为 TCP Server，外部程序作为 TCP Client |
| 消息格式 | UTF-8 JSON Lines，每条消息以 LF 分帧 |
| 请求模型 | 单连接默认处理一条请求 |
| 响应模型 | 一条请求对应一条最终响应 |
| 会话模型 | 无状态；每条请求独立调用 AgentLoop |
| 默认地址 | `127.0.0.1` |
| 默认端口 | `8765`，可由 CLI/配置覆盖 |
| 客户端字段 | 第一版只承诺 `id` 与 `prompt` |
| 流式 | 第一版不实现 |
| 认证 | 第一版不实现；非 localhost 暴露必须明确告警 |
| 错误处理 | 结构化错误码；详细异常只进入日志 |
| 默认开关 | TCP Server 不因普通 CLI 启动而自动监听 |

## 5. 功能需求

### FR-48-1：TCP Server CLI 入口

系统必须提供 `heagent tcp-server` 子命令。

验收要求：

- `heagent tcp-server --help` 展示 host、port、超时、限制和运行说明。
- 默认监听 `127.0.0.1:8765`。
- 可以通过 CLI 参数覆盖默认值。
- 启动普通 `heagent [PROMPT]` 或交互模式时不会自动启动 TCP Server。
- 服务启动和停止状态输出到本地 stderr/log，不混入 TCP 响应。

### FR-48-2：请求消息协议

系统必须接收 UTF-8 JSON Lines 请求，单条请求至少包含 `id` 和 `prompt`。

规范请求：

```json
{"id":"req-001","prompt":"请解释 asyncio"}
```

验收要求：

- 支持 UTF-8 中文和 JSON 转义字符。
- 正确处理 TCP 半包和一次读取多个片段的情况。
- 消息必须以 LF 结束；不允许无限等待或无限读取。
- `id` 必须能在响应中原样关联。
- `prompt` 必须是非空字符串。
- 非法 JSON、字段缺失、字段类型错误、空 prompt 和未知客户端控制字段返回 `invalid_request` 或更具体错误。
- 超过最大请求字节数返回 `request_too_large`。

### FR-48-3：响应消息协议

成功响应必须至少包含 `id`、`ok` 和 `result`。

```json
{"id":"req-001","ok":true,"result":"asyncio 是 Python 的异步 I/O 框架。"}
```

失败响应必须至少包含 `id`、`ok=false` 和结构化 `error`。

```json
{"id":"req-001","ok":false,"error":{"code":"agent_error","message":"agent execution failed"}}
```

验收要求：

- 成功响应的 `id` 与请求一致。
- `ok=true` 时存在字符串 `result`。
- `ok=false` 时存在 `error.code` 与 `error.message`。
- 响应是一条完整 JSON Lines 消息，以 LF 结尾。
- 错误响应不包含完整异常堆栈、API Key、本地绝对路径或未经脱敏的敏感输出。
- 可在兼容不破坏基本字段的前提下附加 `model`、`usage` 等元数据。

### FR-48-4：AgentLoop 适配

系统必须把合法请求的 `prompt` 交给现有 AgentLoop，并将最终回答映射为 TCP 响应。

验收要求：

- TCP 入口使用与现有 CLI 一致的 Provider、EngineContainer 和运行时配置。
- Agent 工具调用仍经过固定执行链：`PolicyEngine.evaluate()` → `ToolExecutor` → `SafetyGuard.check()` → handler。
- AgentLoop 返回最终答案时，服务端发送成功响应。
- Provider、AgentLoop 或工具执行异常时，服务端发送稳定错误响应而不是关闭整个进程。
- 不允许网络层直接执行工具、直接调用 Provider SDK 或绕过 AgentLoop。

### FR-48-5：连接与请求生命周期

系统必须隔离每个 TCP 客户端的连接生命周期。

验收要求：

- 客户端连接建立后可以发送合法请求并收到响应。
- 响应发送完成后连接按 MVP 单请求模型关闭，或明确按协议关闭。
- 客户端提前断开不会导致未处理异常冒泡到服务主任务。
- 服务关闭时停止接受新连接，并在有限时间内释放已有连接。
- 一个连接的解析、Agent 或写回失败不影响其他连接。
- 已完成的异步任务、连接 writer 和并发许可都得到回收。

### FR-48-6：并发和资源限制

系统必须提供服务端资源限制。

初始默认值：

| 限制 | 默认值 | 说明 |
|---|---:|---|
| 最大 TCP 连接数 | 32 | 超出后拒绝或关闭新连接 |
| 最大在途 Agent 请求数 | 4 | 超出后返回 `rate_limited`，不无限排队 |
| 最大请求字节数 | 1 MiB | 按单条 JSON Lines 消息计算 |
| 空闲连接超时 | 60 秒 | 客户端不发送完整请求时释放连接 |
| Agent 请求超时 | 300 秒 | 超时返回 `timeout` |
| 服务停止等待 | 5 秒 | 超时后取消剩余任务 |

验收要求：

- 限制均可通过配置或 CLI 覆盖，并有合法值校验。
- 配置为零或负数等非法值不得静默导致无限制运行；应拒绝配置或回退到安全默认值。
- 达到并发限制时不会创建无限等待任务。
- 超时会取消对应 Agent 调用并释放并发许可。
- 限制只影响 TCP 入口，不改变普通 CLI 的既有默认行为，除非共享运行配置明确要求。

### FR-48-7：安全暴露边界

系统必须以安全默认值启动 TCP Server，并向用户明确其非生产安全边界。

验收要求：

- 默认只监听 `127.0.0.1`。
- 监听 `0.0.0.0` 或其他非 loopback 地址时输出明确告警。
- 文档说明第一版无认证、无 TLS，任何可连接客户端都可能提交 Agent 请求。
- 客户端不能通过协议字段修改 Provider、工具策略、沙箱策略、system prompt 或服务端资源限制。
- TCP 输入按不可信用户输入处理，不提升为系统指令或安全配置。
- 文档明确 SafetyGuard、PolicyEngine 和内置 sandbox 不是网络安全边界，外部暴露必须配合 OS/网络级隔离。

### FR-48-8：可观测性与诊断

系统必须提供足以定位一次 TCP 请求的本地诊断信息。

验收要求：

- 每个请求日志包含 request id、连接状态、开始/结束状态和耗时。
- 失败日志包含稳定错误码和内部异常分类。
- 日志默认不记录 API Key；敏感 prompt 和工具返回不得无控制地写入普通日志。
- TCP 响应内容与已有 JSONL rollout/事件输出边界清晰，不互相污染。
- 日志故障不应改变 TCP 请求的业务结果。

## 6. 非功能需求

### NFR-48-1：异步一致性

TCP Server 必须使用 Python 3.11+ asyncio 实现，不在请求处理路径中引入阻塞式 socket I/O。网络层不得因等待一个 Agent 请求而阻塞其他连接的事件循环。

### NFR-48-2：架构一致性

网络协议模型使用 Pydantic；网络层与 AgentLoop、CLI、Provider 分层；组合根负责依赖注入。新增模块不得产生违反项目架构契约的反向运行时依赖。

### NFR-48-3：兼容性

现有单次 CLI、交互 CLI、GUI、`/goal`、Python 库入口和现有测试行为保持兼容。TCP 功能默认关闭，导入新模块不应启动监听或访问外部网络。

### NFR-48-4：可测试性

协议和 TCP 生命周期测试不得依赖真实 LLM 凭据。Agent 集成测试使用 `StubProvider`；真实网络或外部 Provider 测试使用 integration 标记。

### NFR-48-5：跨平台

实现不得依赖 Linux-only socket API。至少保证 Python 3.11、3.12、3.13 的 Windows、Linux、macOS 基础测试可运行；平台差异应通过可测试的 asyncio/标准库接口隔离。

### NFR-48-6：可恢复关闭

服务收到终止信号或 CLI 取消时，应停止接收新请求、取消或等待在途任务、关闭客户端 writer，并在有限时间内退出，不留下未回收 asyncio task。

### NFR-48-7：错误隔离

协议错误、客户端断开、Agent 超时和单请求内部异常不得使 TCP 主服务任务崩溃。不可恢复的启动配置错误应在启动阶段明确失败，而不是静默运行。

### NFR-48-8：安全声明

TCP Server 仅是应用层入口，不是身份认证、授权系统或 OS 安全边界。对不可信客户端或公网暴露场景必须明确标记为不支持的生产部署方式。

## 7. 错误码契约

| 错误码 | 触发条件 | 客户端处理建议 |
|---|---|---|
| `invalid_json` | 消息不是合法 JSON | 修正请求后重试 |
| `invalid_request` | 字段缺失、类型错误、未知控制字段 | 按协议修正，不重复原请求 |
| `empty_prompt` | prompt 为空或只有空白 | 提供有效 prompt |
| `request_too_large` | 超过消息大小限制 | 缩短请求 |
| `rate_limited` | 达到 Agent 并发限制 | 退避后重试 |
| `timeout` | 空闲或 Agent 处理超时 | 查询服务状态后重试 |
| `agent_error` | AgentLoop/Provider/工具处理失败 | 根据日志和业务决定是否重试 |
| `server_error` | 未分类服务端错误 | 退避后重试并报告 request id |

错误码是客户端契约的一部分；新增错误码应同步测试和文档，不应把 Python 异常类名直接暴露给客户端。

## 8. 配置需求

建议配置项如下，最终字段名在 architecture 阶段冻结：

```dotenv
TCP_ENABLED=false
TCP_HOST=127.0.0.1
TCP_PORT=8765
TCP_MAX_CONNECTIONS=32
TCP_MAX_INFLIGHT_REQUESTS=4
TCP_MAX_REQUEST_BYTES=1048576
TCP_IDLE_TIMEOUT=60
TCP_REQUEST_TIMEOUT=300
TCP_SHUTDOWN_TIMEOUT=5
```

CLI 参数应覆盖配置文件值；未提供参数时使用配置值；非法值必须显式报错或安全回退。`TCP_ENABLED=false` 时普通 CLI 不启动服务，`tcp-server` 子命令是显式启动入口。

## 9. 验收场景

### 场景 1：正常请求

```gherkin
Given TCP Server 监听 127.0.0.1:8765
And AgentLoop 使用 StubProvider
When 客户端发送 {"id":"req-1","prompt":"你好"}\n
Then 客户端收到一条 JSON Lines 响应
And 响应 id 为 req-1
And 响应 ok 为 true
And 响应 result 为非空字符串
```

### 场景 2：半包请求

```gherkin
Given 客户端把一条请求拆成多个 TCP write
When 服务端接收这些片段
Then 服务端在完整 LF 消息形成后只处理一次
And 返回一条对应响应
```

### 场景 3：非法 JSON

```gherkin
Given TCP Server 正常运行
When 客户端发送非法 JSON 行
Then 客户端收到 invalid_json
And 服务端仍能接受后续合法请求
```

### 场景 4：并发限制

```gherkin
Given 最大在途 Agent 请求数为 1
When 两个客户端同时发送请求
Then 一个请求执行
And 另一个请求收到 rate_limited 或按明确策略等待后处理
And 服务不会创建无限后台任务
```

### 场景 5：Agent 超时

```gherkin
Given Agent 请求超时时间已配置
When AgentLoop 超过该时间未完成
Then 客户端收到 timeout
And 对应任务被取消或结束
And 后续请求仍可处理
```

### 场景 6：客户端断开

```gherkin
Given Agent 请求正在处理
When 客户端关闭连接
Then 服务端释放连接和并发资源
And 不影响其他客户端
And 不产生未回收任务
```

### 场景 7：非本机监听

```gherkin
Given 用户显式设置 host 为 0.0.0.0
When TCP Server 启动
Then 服务端正常监听
And stderr 或日志明确提示无认证、非生产安全边界风险
```

## 10. 需求到 Story 的映射

| Story | 覆盖需求 |
|---|---|
| 48-1 TCP 协议模型与消息边界 | FR-48-2、FR-48-3、错误码契约 |
| 48-2 异步 TCP Server 生命周期 | FR-48-1、FR-48-5、NFR-48-1、NFR-48-6 |
| 48-3 AgentLoop 请求适配与 CLI 接线 | FR-48-1、FR-48-4、NFR-48-2、NFR-48-3 |
| 48-4 并发、超时与资源限制 | FR-48-6、FR-48-7、NFR-48-7 |
| 48-5 网络入口安全边界与可观测性 | FR-48-7、FR-48-8、NFR-48-8 |
| 48-6 TCP 回归测试与开发文档 | 全部 FR/NFR 的回归证据、NFR-48-4、NFR-48-5 |

## 11. PRD 完成标准

进入 architecture 阶段前必须满足：

- 服务方向、协议格式、会话模型和 MVP 边界已冻结。
- FR/NFR 均有可验证验收要求。
- 默认资源限制和错误码已定义。
- 安全边界和非目标已显式记录。
- Story 映射覆盖全部需求。
- 后续架构设计只需决定模块落点、接口形状、生命周期实现和测试组织，不再重新决定产品方向。

## 12. 待架构阶段决策

以下问题不阻塞 PRD，但必须在 architecture 阶段确定：

1. TCP Server 是每个连接只读一条请求后关闭，还是允许同一连接顺序发送多条请求；MVP 推荐前者。
2. 超过最大连接数时使用立即关闭还是发送错误后关闭；MVP 推荐立即拒绝并记录。
3. 配置是否全部新增到 `Settings`，还是将部分仅作为 CLI 参数；推荐统一进入 `Settings`，CLI 仅覆盖。
4. `TCP_ENABLED` 是否保留为配置展示项；推荐保留但要求 `tcp-server` 显式命令才能启动。
5. 成功响应是否在第一版加入 usage/model；推荐允许附加，但不把它们作为核心兼容字段。

## 当前状态

PRD 已按 Epic 48 目标建立，尚未进入 architecture 阶段。没有修改源代码、测试或运行时配置，也没有创建 Story 文件。
