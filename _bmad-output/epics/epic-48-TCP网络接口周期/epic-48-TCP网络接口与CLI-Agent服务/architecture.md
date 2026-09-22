---
stepsCompleted: [step-01-validate-prerequisites, step-02-define-boundaries, step-03-design-components, step-04-define-lifecycle-and-tests]
status: planning
---

# Epic 48 Architecture：TCP 网络接口与 CLI Agent 服务

> 设计日期：2026-09-22（中国标准时间）
> 对应 PRD：`prd.md`
> 当前状态：in-progress；Architecture 已建立，Story 已细化
> 代码事实仍以 `src/` 和 `docs/frame.md` 为准；本文是实现前的架构契约。

## 1. 架构目标

在不改变现有 AgentLoop、Provider、Engine 和工具治理链的前提下，为 HeAgent 增加一个显式启动的异步 TCP Server：

```text
TCP Client
   │ UTF-8 JSON Lines
   ▼
network.tcp_server
   │ Protocol model + injected handler
   ▼
CLI / wiring 组合根
   │ 构造现有运行时
   ▼
AgentLoop.run(prompt)
   │
   ▼
network response model
   │
   ▼
TCP Client
```

核心设计原则：

1. TCP 是入口传输层，不是 Provider、Tool 或 MCP 适配层。
2. 网络层只处理 framing、协议、连接和资源生命周期，不构造 Provider，不执行 Tool。
3. 组合根负责将已有 AgentLoop 适配为网络 request handler。
4. TCP Server 默认不启动，普通 CLI 行为保持不变。
5. 协议和跨模块数据使用 Pydantic 模型，避免裸 dict 作为接口契约。
6. 所有安全机制继续沿用现有 Agent/Engine 链；TCP 本身不是安全边界。

## 2. 模块边界与依赖方向

### 2.1 推荐目录

```text
src/heagent/network/
├── __init__.py
├── protocol.py
└── tcp_server.py
```

首版不单独建立 `errors.py`：协议错误码和网络层异常数量有限，先分别归属 `protocol.py` 与 `tcp_server.py`；当错误模型出现跨入口复用需求时再拆分。

### 2.2 `network/protocol.py`

职责：

- `TcpRequest` Pydantic 模型。
- `TcpSuccessResponse` / `TcpErrorResponse` 或统一响应模型。
- 错误码模型和错误响应工厂。
- JSON 编码/解码。
- UTF-8 与 JSON Lines 单行约束。
- 请求大小、字段和空 prompt 校验。

禁止：

- 导入 `cli.py`、`wiring.py`、`AgentLoop`、Provider SDK、Engine 或 ToolRegistry。
- 读取 `.env`、访问文件系统或网络。
- 执行用户 prompt。

### 2.3 `network/tcp_server.py`

职责：

- `asyncio.start_server()` 生命周期。
- 客户端连接读写。
- 单请求单响应流程。
- 最大连接数、最大消息大小、空闲超时和请求超时。
- Agent handler 的注入与调用。
- 优雅关闭、连接清理和任务取消。

禁止：

- 直接构造 Provider、AgentLoop、EngineContainer 或 ToolRegistry。
- 直接调用工具 handler。
- 解析 HeAgent 配置文件。
- 依赖 Click。

### 2.4 CLI / wiring 组合根

组合根负责：

1. 解析 CLI 参数和当前 `Settings`。
2. 按现有路径构造 Provider、EngineContainer、Memory/Session 和 AgentLoop。
3. 创建 `TcpRequestHandler` 适配闭包或专用适配对象。
4. 创建 `TcpServer` 并注入 handler、limits 和 logger。
5. 将服务停止信号转换为 server shutdown。

推荐依赖形状：

```text
network.protocol      ← types/exceptions（如确有需要）
network.tcp_server    ← network.protocol + stdlib asyncio
cli / wiring          ← network + agent + engine + providers + config
```

网络层不得反向依赖 CLI；`AgentLoop` 不增加 TCP 专用分支。

## 3. 协议设计

### 3.1 分帧

首版使用 UTF-8 JSON Lines：每条请求和响应各占一行，以 ASCII LF (`\\n`) 结束。

```text
<JSON object><LF>
```

实现规则：

- 使用 `StreamReader.readline()` 或等价的有界读取方式。
- 必须设置 `limit`，不得使用无上限 `readuntil()`。
- 收到 CRLF 时允许去除行尾 CR，但生成响应固定使用 LF。
- 超过最大行长度必须进入 `request_too_large`，不能继续累积。
- EOF 前没有 LF 的不完整消息视为协议错误或连接结束，不调用 AgentLoop。
- 一次读取多个请求不属于 MVP；若实现层发现额外字节，应按明确策略处理，推荐单请求完成后关闭连接，避免隐式多请求语义。

### 3.2 请求模型

逻辑模型：

```text
TcpRequest
├── id: str
└── prompt: str
```

首版只承诺 `id` 与 `prompt`。模型应拒绝未知字段，防止客户端通过隐藏字段修改安全或运行配置。

建议约束：

- `id`：非空、去除首尾空白后仍非空；保留原始可回传值或明确规范化规则。
- `prompt`：必须是字符串；空白 prompt 拒绝；长度受最大消息字节数间接限制。
- JSON 顶层必须是 object。
- JSON 数字、数组、null、嵌套控制字段均拒绝。

### 3.3 响应模型

统一逻辑响应可以有两种内部形态，但线上字段固定：

```text
TcpResponse
├── id: str
├── ok: bool
├── result: str | None
├── error: TcpError | None
├── model: str | None
└── usage: TokenUsage | None
```

`ok=true` 时必须有 `result` 且无 `error`；`ok=false` 时必须有 `error`，`result` 为空或省略。`model` 和 `usage` 是可选元数据，不属于第一版客户端必须依赖的字段。

错误码由协议层定义为稳定字符串：

```text
invalid_json
invalid_request
empty_prompt
request_too_large
rate_limited
timeout
agent_error
server_error
```

内部异常必须在协议边界被转换，禁止把 Python 异常名称、traceback 或敏感路径作为客户端契约。

## 4. Handler 接口与 Agent 适配

### 4.1 传输层接口

TCP Server 不知道 AgentLoop 类型，只接受注入的异步 handler：

```text
request_handler(TcpRequest) -> Awaitable[TcpResponse]
```

实际代码可使用 `Protocol` 或 `Callable` 类型别名。handler 的输入输出应使用 Pydantic 模型，避免 handler 之间传裸 JSON dict。

### 4.2 组合根 handler

CLI 组合根建立的 handler 执行：

```text
TcpRequest
  → AgentLoop.run(request.prompt)
  → ProviderResponse / Agent result
  → TcpSuccessResponse
```

handler 需要：

- 只读取服务端固定运行配置。
- 不使用客户端输入修改 system prompt、Provider、工具权限、沙箱或迭代预算。
- 将已知 Agent/Provider 异常映射为 `agent_error` 或 `timeout`。
- 保留 request id，供日志和响应关联。
- 在取消时让 `CancelledError` 按取消语义传播到连接任务，不把服务关闭误记为普通 Agent 错误。

### 4.3 运行时复用

TCP 入口应尽量复用现有 CLI 的运行时装配函数，而不是复制 Provider/Engine 构造逻辑。若现有 `_build_loop` 需要调整，优先提取入口层共享装配 helper，但保留既有 `heagent.cli` monkeypatch seam 和测试导入路径。

每个 TCP 请求是否复用 AgentLoop 实例：

- 推荐：服务启动时构造一个服务级 AgentLoop，单请求通过其公开 `run()` 入口执行。
- 请求之间不共享对话消息、session id 或用户上下文；请求 prompt 仍是独立输入。
- 如果现有 AgentLoop 内含只能单 run 使用的 ContextVar/RuntimeSlot，必须在架构实现中确认并在 handler 层加请求级隔离，不得假设并发安全。
- 若验证发现 AgentLoop 实例不可并发复用，则使用受控的 per-request loop 或串行锁；该选择必须由测试证据决定，不能静默共享可变状态。

## 5. TCP Server 生命周期

### 5.1 启动

```text
CLI 解析
  ↓
校验 host/port/limits
  ↓
构造 Provider + Engine + AgentLoop
  ↓
构造 TcpServer(handler=...)
  ↓
await server.start()
  ↓
输出 listening 信息到 stderr/log
  ↓
await server.serve_forever()
```

启动失败（端口占用、非法配置、Provider 无法构造）应显式失败，不能报告“已监听”。

### 5.2 单连接处理

```text
accept client
  ↓
登记连接与连接上限
  ↓
有界读取一行
  ↓
协议解析/校验
  ├── 失败 → 写 error response → close
  └── 成功
        ↓
      获取 inflight semaphore
        ├── 无名额 → error rate_limited → close
        └── 获得名额
              ↓
            await handler(request) with request timeout
              ↓
            写一条 response + drain
              ↓
            finally 释放 semaphore
              ↓
            close writer
```

所有路径必须位于 `try/finally` 结构中：连接记录、inflight permit、request task、writer 都不得因异常或取消泄漏。

### 5.3 服务关闭

```text
收到 CLI 取消/终止
  ↓
停止接受新连接
  ↓
等待在途连接至 shutdown timeout
  ↓
取消仍未结束的请求任务
  ↓
关闭 writer
  ↓
await wait_closed()
  ↓
退出服务
```

关闭流程必须区分：

- 客户端取消：只影响当前连接。
- 单请求超时：取消当前 Agent 请求，服务继续。
- 服务整体关闭：停止接收新连接，统一收尾。
- 观测/日志写入失败：只告警，不改写业务响应。

## 6. 并发与资源限制

### 6.1 两级限制

1. **连接数限制**：保护 socket/连接对象；达到上限时拒绝新连接。
2. **在途 Agent 限制**：保护 Provider、内存、工具和 Agent 运行资源；使用 `asyncio.Semaphore`。

TCP Server 不应为每个无限连接都创建长期后台 task。连接登记、拒绝和清理必须是有界的。

### 6.2 默认配置

| 配置 | 默认值 | 约束 |
|---|---:|---|
| `TCP_HOST` | `127.0.0.1` | 非空；非 loopback 需告警 |
| `TCP_PORT` | `8765` | 1–65535 |
| `TCP_MAX_CONNECTIONS` | `32` | >= 1 |
| `TCP_MAX_INFLIGHT_REQUESTS` | `4` | >= 1 |
| `TCP_MAX_REQUEST_BYTES` | `1048576` | >= 1 |
| `TCP_IDLE_TIMEOUT` | `60` | > 0 |
| `TCP_REQUEST_TIMEOUT` | `300` | > 0 |
| `TCP_SHUTDOWN_TIMEOUT` | `5` | > 0 |

Settings 新字段应采用 Pydantic `Field(..., ge=...)` 等约束。CLI 参数覆盖 Settings，但最终进入同一个 Pydantic/配置校验路径，避免 CLI 和 env 两套校验规则漂移。

### 6.3 超时实现

- 空闲读取超时包住从连接建立到完整 LF 消息形成的读取阶段。
- Agent 请求超时只包住 handler/AgentLoop 调用，不把连接关闭和响应写回时间混入 Agent 预算。
- `writer.drain()` 必须有关闭/取消处理，避免慢客户端长期占用处理任务。
- 所有 `asyncio.timeout()` 或等价机制退出后，必须在 finally 释放连接与 semaphore。

## 7. 配置与 CLI 接线

### 7.1 CLI 命令

推荐新增 Click 子命令：

```text
heagent tcp-server [OPTIONS]
```

参数：

```text
--host TEXT
--port INTEGER
--max-connections INTEGER
--max-inflight INTEGER
--max-request-bytes INTEGER
--idle-timeout FLOAT
--request-timeout FLOAT
--shutdown-timeout FLOAT
```

参数名可在实现 Story 中按现有 CLI 命名风格最终冻结，但语义必须与 PRD 一致。

### 7.2 `TCP_ENABLED`

`TCP_ENABLED=false` 可作为配置可见性和未来自动化入口的开关，但显式 `heagent tcp-server` 是唯一启动方式。推荐：

- 普通 CLI 不读取该开关来自动启动 TCP。
- `tcp-server` 命令若显式发现 `TCP_ENABLED=false`，仍可启动并以 CLI 参数作为明确意图；或在 Story 中冻结为拒绝启动。两者必须选定并测试，不能出现“配置含义不明”。
- 当前推荐：显式子命令优先，`TCP_ENABLED` 只作为默认配置开关，不阻止显式命令。

### 7.3 日志

服务启动、停止、连接和请求状态写 stderr/现有日志系统；TCP stdout 不作为协议输出通道。日志字段至少包括：

```text
request_id
peer/local connection summary
phase: accepted|rejected|processing|completed|failed
error_code
elapsed_ms
```

不记录 API Key。prompt 和工具结果只能按现有日志隐私策略处理，不新增无界全文日志。

## 8. 安全边界

TCP Server 的可信边界：

```text
客户端输入 = 不可信用户输入
网络可达性 = 不能替代认证
TCP Server = 不能替代授权
SafetyGuard/PolicyEngine/Sandbox = defense-in-depth，非 OS 安全边界
```

必须满足：

- 默认 localhost。
- 非 loopback 监听输出告警。
- 不从客户端请求读取 Provider、system prompt、工具策略、沙箱参数或资源限制。
- 不将 TCP 输入拼入系统 prompt 的配置段；只作为用户 prompt 传给 AgentLoop。
- 错误响应做信息最小化。
- 文档明确公网部署不在 MVP 支持范围。

## 9. 可观测性与事件边界

首版 TCP 响应只返回最终结果，不发送 `StreamEvent` 或引擎事件流。已有 `events/` 的 JSONL rollout 继续按现有 Settings 控制，不与 TCP 响应复用 stdout。

可选的内部观测方式：

- 在 TCP 层使用模块 logger 记录连接/协议/耗时。
- 如果已有 EngineEvent 与 run_id，可在 handler 日志中关联 run_id；不能为了 TCP 复制一套 Agent 埋点。
- 观测失败只 warning，不阻断响应。

未来若增加流式 TCP，应另建协议版本或消息类型，不能把首版单响应格式隐式改成多行事件流。

## 10. 测试架构

### 10.1 协议单元测试

文件建议：`tests/network/test_protocol.py`

覆盖：

- 合法 JSON、Unicode、转义字符。
- 缺字段、错误类型、未知字段、空 prompt。
- request id 保真。
- 错误码和错误响应字段。
- 最大字节数和 LF/CRLF。
- 响应 JSON Lines 序列化稳定性。

### 10.2 TCP 生命周期测试

文件建议：`tests/network/test_tcp_server.py`

使用本机 loopback 和随机可用端口，不依赖外部 Provider；覆盖：

- 启停和端口暴露。
- 单客户端请求响应。
- 半包、断行、CRLF。
- 非法 JSON 后继续服务。
- 连接提前断开。
- 空闲读取超时。
- writer 写回失败。
- 最大连接数和 inflight 限制。
- 服务整体 shutdown 等待与取消。
- task、writer、semaphore 释放。

### 10.3 Agent 适配集成测试

文件建议：`tests/test_tcp_agent_integration.py`。

使用 `StubProvider` 或注入 fake handler 覆盖：

- 正常 AgentLoop 最终答案。
- AgentLoop/Provider 异常映射。
- Agent 请求超时和取消。
- 两个并发请求互不污染。
- 现有工具治理链仍由 AgentLoop/Engine 负责。

### 10.4 CLI 测试

覆盖：

- `tcp-server --help`。
- 默认 host/port。
- CLI 覆盖 Settings。
- 非法参数拒绝。
- 非 loopback 告警。
- 普通 CLI 不启动 TCP。

保留现有 `heagent.cli` monkeypatch seam；如果装配逻辑抽取到入口层，必须保留既有测试调用路径或提供兼容 re-export。

### 10.5 质量门禁

实现阶段至少运行：

```text
pytest tests/network tests/test_tcp_agent_integration.py tests/test_cli*.py
ruff check src tests
ruff format --check src tests
mypy src --platform linux
pytest --cov=heagent --cov-fail-under=87
```

真实外部 Provider、跨机器网络和非 localhost 测试使用 `integration` 标记，不进入默认回归基线。

## 11. Story 实施顺序与文件映射

### 48-1：TCP 协议模型与消息边界

主要文件：

```text
src/heagent/network/__init__.py
src/heagent/network/protocol.py
src/heagent/config.py（若提前加入 Settings，需同步 .env.example）
tests/network/test_protocol.py
```

完成标准：协议模型和有界 JSON Lines 编解码可独立测试，不依赖 AgentLoop。

### 48-2：异步 TCP Server 生命周期

主要文件：

```text
src/heagent/network/tcp_server.py
tests/network/test_tcp_server.py
```

完成标准：注入 fake handler 的 TCP Server 能安全启停、处理一条请求并覆盖超时/断开/取消。

### 48-3：AgentLoop 请求适配与 CLI 接线

主要文件：

```text
src/heagent/cli.py
src/heagent/wiring.py（仅在确有共享装配需求时调整）
tests/test_cli_tcp.py
tests/test_tcp_agent_integration.py
```

完成标准：真实 CLI 组合根可构造 TCP handler，StubProvider 端到端返回结构化响应；普通 CLI 无回归。

### 48-4：并发、超时与资源限制

主要文件：

```text
src/heagent/network/tcp_server.py
src/heagent/config.py
.env.example
tests/network/test_tcp_server.py
```

完成标准：资源限制在协议/连接/Agent 三层分别有测试，取消后没有残留 task 或 permit。

### 48-5：网络入口安全边界与可观测性

主要文件：

```text
src/heagent/network/tcp_server.py
src/heagent/cli.py
README.md
docs/frame.md
```

完成标准：非 loopback 告警、日志脱敏和安全声明可核验；不新增绕过现有治理链的执行路径。

### 48-6：TCP 回归测试与开发文档

主要文件：

```text
README.md
docs/frame.md
docs/README.md
顶层 tests/ 相关回归文件
```

完成标准：全量质量门禁通过，协议示例可复制运行，Architecture 与代码事实同步。

## 12. 架构决策记录

### ADR-48-1：选 asyncio 原生 TCP

**决策**：使用 `asyncio.start_server()` 和标准库 stream API。

**原因**：项目本身是 asyncio 架构；减少依赖；跨平台；测试可控。

**拒绝方案**：第一版引入第三方 TCP/Web 框架，收益不足且扩大部署面。

### ADR-48-2：选 JSON Lines 而非裸文本

**决策**：UTF-8 JSON Lines，以 LF 分帧。

**原因**：明确边界、可扩展字段、易于脚本调试和测试；比裸文本可安全表达错误和 request id。

### ADR-48-3：网络层使用注入 handler

**决策**：`TcpServer` 不直接依赖 AgentLoop，使用异步 handler 注入。

**原因**：隔离传输与 Agent 编排；便于 fake handler 测试；未来可复用协议层。

### ADR-48-4：首版无状态、单请求单响应

**决策**：一次连接处理一条请求并返回最终结果后关闭。

**原因**：避免第一版引入 session 所有权、并发上下文和流式协议复杂度。

### ADR-48-5：默认 localhost 且无认证

**决策**：默认只监听 `127.0.0.1`，非 localhost 为显式实验能力并告警。

**原因**：首版不实现认证/TLS，必须缩小默认暴露面；非 loopback 不得被误解为生产安全服务。

### ADR-48-6：不复制 Agent 运行时装配

**决策**：TCP 入口复用 CLI/wiring 的 Provider 和 Engine 装配。

**原因**：保持单一运行时事实，避免 TCP 路径绕过配置、治理、审计或沙箱策略。

## 13. Architecture 完成标准

- 模块边界、依赖方向和组合根职责明确。
- 协议 framing、Pydantic 模型和错误映射明确。
- 连接、请求、超时、取消和服务关闭生命周期明确。
- 配置默认值和 CLI 覆盖关系明确。
- 安全边界与非目标明确。
- 测试文件、fake handler、StubProvider 和质量门禁明确。
- 6 个 Story 均有文件映射和依赖顺序。
- 后续 Story 阶段只需补 Given-When-Then、DoD、代码地图和执行序列，不再重新设计入口方向。

## 当前状态

Architecture 已建立，Epic 48 仍为 `backlog`。下一步进入 BMad Story 细化与 Sprint Plan，之后才能开始代码实现。
