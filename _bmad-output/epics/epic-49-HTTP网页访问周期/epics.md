---
stepsCompleted: [step-01-validate-prerequisites, step-02-design-epics, step-03-create-stories, step-04-final-validation]
status: final
inputDocuments:
  - _bmad-output/epics/epic-49-HTTP网页访问周期/brief.md
  - docs/frame.md
---

# HeAgent - Epic Breakdown

## Overview

本文件按 BMad 方法把 HTTP 网页访问方案拆解为可执行的 Epic 与 Story。当前产品输入为本目录的
`brief.md`，架构事实以 `docs/frame.md` 和 `src/` 为准。HTTP MVP 面向本机单用户，
默认 CLI 启动时自动提供网页入口；不把该能力扩展为未经认证的远程服务。

## Requirements Inventory

### Functional Requirements

FR1: 用户运行默认 CLI（`heagent`、`heagent "prompt"` 或 `heagent run ...`）时，HeAgent 在同一进程内自动启动 HTTP 服务。
FR2: 用户可通过 `heagent http-server` 显式启动只提供网页服务的 HTTP 进程。
FR3: HTTP 服务提供同源的内置静态聊天页，用户可以输入并提交提示词。
FR4: 网页可以通过 SSE 接收回答文本增量、工具调用、工具结果、完成、取消和错误事件。
FR5: 服务维护一个进程内单用户会话，网页刷新后可获取当前会话状态和可展示历史。
FR6: 客户端可以查询健康状态、创建运行、订阅指定运行事件并取消在途运行。
FR7: 运行事件带递增序号，客户端可通过 `Last-Event-ID` 重连；超出缓存窗口时得到明确的重新同步结果。
FR8: 服务对提示词、请求体、连接数、在途运行数、事件缓存和运行时长实施有界限制。
FR9: 服务在启动、端口冲突、请求失败、客户端断连、取消和进程退出时执行确定性的生命周期处理。
FR10: HTTP 请求进入现有 Provider → AgentLoop → PolicyEngine → ToolExecutor → SafetyGuard 工具治理链，网络请求不能改变 Provider、system prompt、工具策略、沙箱或迭代预算。

### NonFunctional Requirements

NFR1: 默认只绑定 `127.0.0.1`，非回环绑定必须给出与现有 `network.exposure` 一致的明确风险告警。
NFR2: HTTP 传输层保持入口层职责，不反向依赖 `agent`、`engine`、`providers`、`tools` 或其它运行时模块；Agent 装配由入口层完成。
NFR3: HTTP 实现使用 asyncio/ASGI，不使用同步 `http.server` 承载异步 Agent 运行。
NFR4: 每个运行使用独立 `AgentLoop`，共享 Provider/Engine/记忆存储时不得串联跨请求可变状态。
NFR5: API 错误使用稳定、有界、脱敏的错误结构，不向浏览器泄露 traceback、密钥、绝对路径或未经处理的敏感工具输出。
NFR6: 状态变更请求执行同源 Origin/Host 校验；不启用宽泛 CORS；静态页设置 CSP、`nosniff`、禁止 framing。
NFR7: 提示词与 Agent 输出按纯文本渲染，静态页不加载第三方脚本。
NFR8: SSE 订阅、客户端断连、取消和服务关闭必须释放任务/订阅资源，不遗留后台任务或并发名额。
NFR9: 新增 HTTP 能力不改变现有 CLI、GUI、TCP、库调用和默认工具治理行为；显式非 HTTP 子命令不应意外监听 HTTP 端口。
NFR10: 静态资源、可选 HTTP 依赖和配置在源码运行与 wheel 安装场景都能被明确验证；HTTP 配置非法值显性失败。

### Additional Requirements

- 复用 `cli_tcp.py` 的网络入口安全立场、`cli._build_loop` 和 `wiring._build_provider`，避免复制 Provider/Engine 装配分支。
- 新增入口层 `heagent.cli_http`，网络层只接收注入的 request handler，不导入 Click 或 AgentLoop。
- HTTP 默认端口建议为 `8766`，与 TCP 默认端口 `8765` 分离；配置使用独立的 `HTTP_*` 字段，不设置隐式 `HTTP_ENABLED` 开关。
- 默认 CLI 的 HTTP 生命周期与 `_run_cli_impl` 同一 asyncio 生命周期：交互模式与 REPL 共存，单次模式与 Agent run 并存并在 run 结束后关闭。
- 默认 CLI HTTP 绑定/初始化失败必须显式失败，不能静默降级为没有网页入口的半启动状态。
- 网络入口不装 stdin 交互审批处理器，不自动连接 MCP；审批型工具保持既有 fail-safe 阻断语义。
- 使用 Pydantic 模型表达 HTTP 请求、响应和事件；不把内部对象直接序列化为外部协议。
- 建议评估 Starlette 作为轻量 ASGI 框架，并将依赖作为可选 `http` extra；最终选择需验证 Python 3.11+、wheel 打包和测试客户端支持。

### UX Design Requirements

UX-DR1: 首屏提供紧凑聊天工作区，包含消息列表、多行提示词输入、提交操作和运行状态。
UX-DR2: 流式回答逐步显示，工具调用显示名称、作用目标和结果；工具错误必须有明确失败状态。
UX-DR3: 运行中禁用重复提交，并分别呈现连接中、重连中、取消中、完成、失败和服务关闭状态。
UX-DR4: 页面刷新后调用会话接口恢复当前进程内可展示状态；不能假装恢复已不存在的持久历史。
UX-DR5: 所有用户文本按纯文本显示；不渲染不可信 HTML，不依赖第三方脚本。
UX-DR6: 空状态、运行冲突、超限、断连、未知运行和 Agent 错误都必须有可理解的可见反馈。

### FR Coverage Map

FR1: Epic 49 - 默认 CLI 生命周期内自动启动 HTTP 服务。
FR2: Epic 49 - 提供独立 `heagent http-server` 启动方式。
FR3: Epic 49 - 提供同源内置静态聊天页。
FR4: Epic 49 - 通过 SSE 展示文本和工具运行事件。
FR5: Epic 49 - 提供进程内单用户会话快照。
FR6: Epic 49 - 提供健康、运行创建、事件订阅和取消 API。
FR7: Epic 49 - 提供事件序号与 SSE 重连/重同步语义。
FR8: Epic 49 - 提供请求、连接、运行和事件资源上限。
FR9: Epic 49 - 提供显式的启动、失败、取消、断连和关闭生命周期。
FR10: Epic 49 - 复用现有 Agent 与工具治理链，禁止网络请求改变服务端策略。

## Epic List

### Epic 49: 本机网页 Agent 访问

用户启动 HeAgent 后，可以通过本机浏览器提交提示词，实时查看回答和工具活动，取消在途运行，并在服务退出时获得确定性的资源收尾。该 Epic 是一个完整的本机单用户 HTTP MVP；远程认证、多用户和持久会话不属于本 Epic。

**FRs covered:** FR1–FR10
**NFRs:** NFR1–NFR10 贯穿所有 stories
**UX-DRs:** UX-DR1–UX-DR6 贯穿网页和 API 验收

## Story 49.1: HTTP 服务启动与本机入口

作为 HeAgent 用户，我希望启动 HTTP 服务后能打开一个内置网页并确认服务健康，以便知道浏览器入口已经准备好。

**Acceptance Criteria:**

**Given** 未显式配置 HTTP 地址和端口，**When** 用户执行 `heagent http-server`，**Then** 服务只绑定 `127.0.0.1:8766`，并在 stderr 输出可访问地址。

**Given** HTTP 服务已启动，**When** 浏览器请求 `/api/health`，**Then** 服务返回稳定 JSON 健康结果，不包含密钥、绝对路径或 traceback。

**Given** HTTP 服务已启动，**When** 浏览器请求根路径，**Then** 返回随 Python 包分发的内置静态聊天页，且页面不依赖第三方脚本。

**Given** 端口已被占用或配置值非法，**When** 服务启动，**Then** 命令显式失败并给出可诊断错误，不声称服务已监听、不遗留后台任务。

**Given** 用户执行 `gui`、`tcp-server`、`init` 或 `replay` 子命令，**When** 命令启动，**Then** 不因 HTTP 模块导入而创建 HTTP listener。

**Definition of Done:**

- HTTP 配置和协议模型有 Pydantic 校验，默认值与文档一致。
- HTTP 传输层不反向导入 Agent、Provider、Engine 或 CLI 组合根。
- 静态资源在源码运行和 wheel 安装场景均可加载。
- 覆盖健康、根路径、端口冲突、非法配置和非 HTTP 子命令不监听的测试已加入。
- 通过定向 pytest、ruff 和 mypy 检查。

**Requirement Traceability:** FR2, FR3, FR8, FR9; NFR1, NFR2, NFR3, NFR9, NFR10; UX-DR1, UX-DR6。

## Story 49.2: 默认 CLI 自动启动与生命周期

作为 HeAgent 用户，我希望正常启动 CLI 时网页入口自动可用，以便不必额外维护一个 HTTP 后台命令。

**Acceptance Criteria:**

**Given** 用户执行 `heagent` 进入交互模式，**When** CLI 初始化完成，**Then** HTTP 服务在同一 asyncio 生命周期内启动，stderr 显示本地访问地址，REPL 与网页入口可以同时存活。

**Given** 用户执行 `heagent "prompt"` 或 `heagent run "prompt"`，**When** 单次 Agent 运行开始，**Then** HTTP 服务已可用；**When** 单次运行结束或失败，**Then** HTTP 服务随 CLI 生命周期关闭并释放端口。

**Given** 用户执行 `heagent gui`、`heagent tcp-server`、`heagent http-server`、`heagent init` 或 `heagent replay`，**When** 子命令启动，**Then** 不额外自动创建第二个 HTTP 服务实例。

**Given** 默认 CLI 自动启动 HTTP 服务时绑定失败，**When** CLI 初始化，**Then** 命令显式失败，不继续进入看似正常的聊天状态，也不遗留 Provider、任务或 socket 资源。

**Given** 用户发送 Ctrl+C 或 CLI 收到取消信号，**When** 进程退出，**Then** HTTP listener、SSE 订阅和在途 HTTP 任务按有界超时收尾。

**Definition of Done:**

- `_run_cli_impl` 的默认路径和 HTTP 服务生命周期在同一个 asyncio 管理边界内。
- 交互、单次和显式子命令的启动矩阵有测试覆盖。
- 端口冲突、初始化异常、取消和关闭路径不吞错、不泄漏资源。
- 现有 CLI/TCP/GUI 测试保持通过。

**Requirement Traceability:** FR1, FR2, FR9; NFR1, NFR4, NFR8, NFR9; UX-DR3, UX-DR6。

## Story 49.3: 网页运行 API 与流式 Agent 会话

作为网页用户，我希望提交提示词并实时看到 Agent 回答和工具活动，以便在浏览器中完成一次完整的 HeAgent 运行。

**Acceptance Criteria:**

**Given** 服务健康且没有其他运行，**When** 客户端向 `POST /api/runs` 提交有界非空 prompt，**Then** 服务返回唯一 `run_id`，并使用服务端固定配置创建独立 AgentLoop。

**Given** 一个运行已创建，**When** 客户端订阅 `/api/runs/{run_id}/events`，**Then** SSE 按序发送文本增量、tool_call、tool_result 和终态事件，且字段来自结构化 StreamEvent 映射。

**Given** Agent 运行完成，**When** 客户端收到终态事件，**Then** 页面显示完整回答、成功状态、可选 usage/model 信息，并把结果纳入当前进程内会话快照。

**Given** Agent 或 Provider 失败，**When** 运行结束，**Then** 客户端收到稳定的 error 事件，不包含 traceback、密钥或绝对路径，服务仍可接受下一次运行。

**Given** 已有一个在途运行，**When** 客户端再次创建运行，**Then** API 返回明确的冲突错误，不排队、不覆盖原运行。

**Definition of Done:**

- API 请求/响应/事件均有 Pydantic 模型和有界序列化。
- 每个 run 使用独立 AgentLoop，服务级共享对象不会覆盖其他 run 的 usage、model 或活动状态。
- SSE 订阅在完成和失败后结束，异常路径不会遗留任务。
- 使用 StubProvider 覆盖成功、工具事件、Agent 异常和重复提交。

**Requirement Traceability:** FR3–FR6, FR10; NFR4, NFR5, NFR8; UX-DR1, UX-DR2, UX-DR3, UX-DR6。

## Story 49.4: 运行取消、SSE 重连与资源限制

作为网页用户，我希望能停止卡住或不再需要的运行，并在浏览器短暂断线后继续接收进度，以便网页操作不会留下失控任务或错误状态。

**Acceptance Criteria:**

**Given** 一个运行正在执行，**When** 客户端请求 `DELETE /api/runs/{run_id}`，**Then** Agent task 收到取消信号，SSE 最终发送 `cancelled`，并释放在途运行名额。

**Given** 客户端已收到事件序号 N 后断线，**When** 客户端带 `Last-Event-ID: N` 重新订阅，**Then** 服务从 N 之后的有界缓存继续发送，事件不重复且顺序稳定。

**Given** 客户端请求的序号早于已淘汰的缓存窗口，**When** 客户端重新订阅，**Then** 服务返回明确的 `resync_required`，客户端可以通过 session 快照恢复，不伪造完整事件流。

**Given** 请求体、连接数、SSE 订阅数、在途运行数或单次运行超过配置上限，**When** 客户端发起请求或运行持续，**Then** 服务返回稳定限流/超时错误或取消运行，不无限排队、不耗尽进程资源。

**Given** SSE 客户端断线、取消竞态或服务关闭，**When** 清理逻辑执行，**Then** 订阅者、任务和并发登记最终释放，后续运行可正常开始。

**Definition of Done:**

- run 状态机明确区分 running、completed、failed、cancelled、timed_out。
- 事件 buffer 有界且事件 id 单调递增；Last-Event-ID 处理有覆盖测试。
- DELETE 取消、SSE 断线、超时和 shutdown 的 task ownership 不产生 orphan task。
- 资源限制和稳定错误码在 API 测试中覆盖，现有 TCP 限额行为不受影响。

**Requirement Traceability:** FR6–FR9; NFR5, NFR8; UX-DR3, UX-DR4, UX-DR6。

## Story 49.5: HTTP 安全边界与可观测性

作为 HeAgent 维护者，我希望 HTTP 入口明确暴露风险并保护浏览器状态变更，以便本机服务不会被误当成认证完成的远程 API。

**Acceptance Criteria:**

**Given** 服务绑定非回环地址，**When** 服务启动，**Then** stderr 和日志给出统一的无认证、无 TLS、非生产安全边界告警。

**Given** 请求来自不匹配的 Host 或 Origin，**When** 执行状态变更操作，**Then** 服务拒绝请求且不创建、取消或修改 Agent run。

**Given** 浏览器加载静态页面，**When** 响应返回，**Then** 设置 CSP、`X-Content-Type-Options: nosniff`、禁止 framing 等安全响应头，页面不加载第三方脚本。

**Given** Provider、Agent 或工具抛出异常，**When** API/SSE 返回错误，**Then** 客户端只收到稳定脱敏文案，服务端日志包含有限诊断字段而不记录 prompt、answer、密钥或敏感工具输出。

**Given** HTTP 入口处理工具调用或审批型工具，**When** Agent 执行，**Then** 仍经既有治理链；不自动连接 MCP，不读取服务进程 stdin 进行交互审批。

**Definition of Done:**

- HTTP 复用 `network.exposure` 的地址判定和告警文案。
- Origin/Host、CSP、响应头和纯文本渲染有测试。
- 日志字段包含 request/run id、状态、耗时和错误类别，但不含正文与凭据。
- 架构契约测试确认 network 层依赖方向和 HTTP 入口安全边界。

**Requirement Traceability:** FR10; NFR1, NFR2, NFR5, NFR6, NFR7; UX-DR5, UX-DR6。

## Story 49.6: 浏览器体验、打包与回归收口

作为 HeAgent 用户和维护者，我希望网页聊天体验在源码和安装包中都能稳定工作，并有完整回归证据，以便可以实际使用和维护 HTTP MVP。

**Acceptance Criteria:**

**Given** 用户打开内置网页，**When** 页面加载，**Then** 能看到消息列表、多行输入、提交/停止操作和清晰的空状态。

**Given** 用户提交 prompt，**When** SSE 推送文本和工具事件，**Then** 页面按顺序更新回答、工具目标、工具结果和终态，不渲染不可信 HTML。

**Given** 页面处于运行、重连、取消、失败、冲突或服务关闭状态，**When** 状态发生变化，**Then** 页面显示对应可理解反馈，并避免重复提交。

**Given** 项目构建 wheel 并在干净环境安装，**When** 启动 HTTP 服务并请求根路径，**Then** 静态资源和 API 均可用，不依赖源码目录或开发机绝对路径。

**Given** 执行 HTTP 定向测试、现有网络测试、ruff 和 mypy，**When** 质量门禁运行，**Then** 新增功能通过且现有 CLI、GUI、TCP 和 Agent 回归不受影响。

**Definition of Done:**

- 内置网页覆盖 UX-DR1–UX-DR6 的主要状态和交互。
- 源码运行、wheel 安装、浏览器手工验收和自动化测试均有记录。
- README、docs 索引、docs/frame.md、配置示例和 HTTP MVP 边界保持一致。
- Epic 49 的 FR1–FR10、NFR1–NFR10 与 UX-DR1–UX-DR6 都能追溯到实现和测试。

**Requirement Traceability:** FR3–FR9; NFR3, NFR5, NFR6, NFR7, NFR9, NFR10; UX-DR1–UX-DR6。

<!-- Subsequent BMad steps will append the approved Epic details and Stories. -->
