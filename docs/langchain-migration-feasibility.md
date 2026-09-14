# HeAgent 改为 LangChain 架构的技术可行性分析

> 分析日期：2026-09-14
>
> 本文只分析技术可行性与迁移边界，不代表已经开始迁移，也不改变当前 HeAgent 的实现。

## 一、结论

技术上可行，但不建议把 HeAgent 整体改写成普通的 LangChain Agent。

更合理的目标架构是：

```text
HeAgent Runtime
├── 保留：CLI / TUI / 配置 / 记忆 / Cron
├── 保留：PolicyEngine / ToolExecutor / SafetyGuard / Sandbox
├── 保留：RunContext / ExecutionLedger / 审计 / 持久化
├── 引入：LangChain ChatModel 作为模型适配层
├── 引入：LangChain Tool / Runnable 作为可选工具接口层
└── 可选引入：LangGraph 承载复杂状态机与长流程工作流
```

即：

> **推荐采用 HeAgent Runtime + LangChain Model/Tool + LangGraph Workflow 的混合架构，而不是 HeAgent → LangChain 的全量替换。**

原因是 LangChain 主要提供 LLM 应用组件和 Agent 抽象；HeAgent 当前已经是一个包含安全治理、运行状态、工具审计、记忆、CLI/TUI、Cron 和声明式工作流的 Agent Runtime。两者不是同一层级的直接替代品。

## 二、当前 HeAgent 的架构基线

当前核心数据流为：

```text
AgentLoop
  ├── Provider
  ├── Middleware
  ├── PolicyEngine
  ├── ToolExecutor
  ├── SafetyGuard
  ├── ExecutionLedger
  ├── RunStore
  ├── ContextCompressor / WindowReset
  ├── SubAgent
  ├── Memory
  └── WorkflowRunner
```

工具执行链是项目硬约束：

```text
PolicyEngine.evaluate()
    ↓
ToolExecutor
    ↓
SafetyGuard.check()
    ↓
handler
```

Provider 层还有多层容错和选择机制：

```text
SwitchableProvider
    ↓
RoutingProvider
    ↓
ProviderChain
    ↓
KeyRotatingProvider
    ↓
Retry Middleware
```

此外，`AgentLoop` 已经支持：

- 非流式和流式执行；
- tool call 循环；
- token 统计；
- 上下文压缩和窗口重置；
- session 持久化；
- run snapshot 与 resume；
- pause/unpause；
- steering 和 follow-up；
- 子 Agent、角色、预算和递归深度；
- 运行事件、审计和工具调用幂等 ledger。

因此，迁移的核心问题不是“LangChain 能不能调用模型”，而是“如何在不丢失上述运行时语义的情况下引入 LangChain”。

## 三、模块映射

### 3.1 Provider 层：可行性高

HeAgent 当前 Provider 接口为：

```python
class BaseProvider(Protocol):
    async def send(messages, *, tools) -> ProviderResponse:
        ...

    async def stream(messages, *, tools) -> AsyncIterator[ProviderResponse]:
        ...
```

LangChain 可提供：

- `BaseChatModel`；
- `AIMessage`、`HumanMessage`、`SystemMessage`、`ToolMessage`；
- `AIMessageChunk`；
- OpenAI、Anthropic、Ollama 等模型集成。

建议增加适配层，而不是让 LangChain 类型渗透到整个项目：

```text
HeAgent Message
        ⇅
LangChain Adapter
        ⇅
LangChain BaseMessage / AIMessage
        ⇅
具体 ChatModel
```

适配器需要处理：

- HeAgent `Message` 与 LangChain `BaseMessage` 的转换；
- `AIMessage.tool_calls` 与 HeAgent `ToolCall` 的转换；
- `ToolMessage` 与 HeAgent `ToolResult` 的转换；
- `usage_metadata` 与 `TokenUsage` 的转换；
- 模型名和结束原因；
- `reasoning_content` 的兼容提取；
- 流式 `AIMessageChunk` 的 tool call 增量聚合。

#### 主要风险

1. **reasoning_content 不一定有统一位置**

   不同 LangChain 模型集成可能将推理内容放在 `content`、`additional_kwargs` 或 `response_metadata` 中，不能假设所有模型一致。

2. **Token 字段命名不统一**

   LangChain 可能使用 `input_tokens` / `output_tokens`，而 HeAgent 使用 `prompt_tokens` / `completion_tokens`，需要统一转换。

3. **流式 tool call 需要聚合**

   LangChain 流式响应可能把工具调用拆成多个 chunk。必须先聚合为完整调用，再进入 HeAgent 的工具治理链。

结论：Provider 层非常适合最先迁移，风险可控。

### 3.2 Tool 层：描述层可行，执行层应保留 HeAgent

LangChain 可以承载：

- 工具名称；
- 工具描述；
- 参数 JSON Schema；
- `StructuredTool` / `BaseTool`；
- 工具调用消息。

但 HeAgent 必须继续负责：

- PolicyEngine 准入裁决；
- 审批和沙箱裁决；
- workspace 路径围栏；
- 凭证文件读写 deny；
- SafetyGuard shell 检查；
- 工具执行幂等和租约；
- 运行事件与审计；
- MCP 工具的 fail-safe 治理。

推荐的执行链为：

```text
LangChain Tool Call
    ↓
转换为 HeAgent ToolCall
    ↓
PolicyEngine.evaluate()
    ↓
ToolExecutor
    ↓
SafetyGuard.check()
    ↓
原有 handler
    ↓
转换为 LangChain ToolMessage
```

不建议直接使用 LangGraph 的默认 `ToolNode` 执行所有工具，因为它不会自动理解 HeAgent 的审批、沙箱、ledger、路径安全、凭证 deny 和 MCP annotations 策略。直接接入可能形成第二条绕过 HeAgent 治理的执行路径：

```text
危险路径：LangChain ToolNode → handler
正确路径：PolicyEngine → ToolExecutor → SafetyGuard → handler
```

如果未来使用 LangGraph，建议实现自定义的 `HeAgentToolNode` 或治理节点，内部仍调用现有 `ToolExecutor`。

### 3.3 Sandbox 层：可引用具体后端，但不能把 LangChain Tool 当作安全边界

LangChain 核心提供模型、工具和工作流抽象，但不提供一个可直接替换 HeAgent Runtime 的统一 OS 级沙箱。其生态中的所谓“沙箱”通常是对 Docker、远程容器、微虚拟机或开发工作区供应商的工具封装；隔离质量取决于具体后端及其网络、文件系统、资源和凭证配置，而不取决于 LangChain Tool 本身。

HeAgent 当前已经具备适合扩展真实沙箱的执行接口：

```text
PolicyEngine.evaluate()
    ↓
ToolExecutor
    ↓
SafetyGuard.check()
    ↓
handler（shell 工具经 CommandRunner 执行）
```

`CommandRunner` 是可注入的异步执行后端，现有实现包括：

| 后端 | 强度档位 | 实际能力 | 局限 |
|---|---:|---|---|
| `PassthroughRunner` | `passthrough` | 直接执行 shell | 无隔离 |
| `WinJobBackend` | `job` | Windows Job Object 在结束时清理子孙进程 | 不隔离文件系统和网络 |
| `FirejailBackend` | `firejail` | Linux shell 子进程隔离、可用 `--private` 工作区 | Linux-only，非完美边界 |
| `SandboxTier.CONTAINER` | `container` | 已预留的强隔离等级 | 当前尚无实现后端 |

因此，合理的引用方式不是让 LangChain 的默认 `ToolNode` 或某个 Sandbox Tool 直接执行命令，而是把选定的真实沙箱实现为 HeAgent 的 `CommandRunner` 后端，例如 `ContainerSandboxBackend`、`E2BSandboxBackend` 或 `DaytonaSandboxBackend`：

```text
LangChain Tool Call（若使用）
    ↓ 转换
HeAgent ToolCall
    ↓
PolicyEngine → ToolExecutor → SafetyGuard
    ↓
ContainerSandboxBackend（tier=container）
    ↓
Docker / Podman / E2B / Daytona 等实际隔离环境
```

这样仍保留 HeAgent 的审批与 sandbox-required 裁决、路径与凭证防护、`ExecutionLedger` 幂等/租约、`RunContext`、事件和审计；不得形成 `LangChain ToolNode → handler` 的第二条直达执行路径。

#### 推荐的首个后端：Docker / Podman 容器

项目当前也运行在 Windows，`WinJobBackend` 只解决进程生命周期，不能提供文件系统或网络隔离。优先实现本地 Docker/Podman 后端通常比先引入 LangChain 更直接：Windows 可经 Docker Desktop/WSL2 使用 Linux 容器，并让该后端声明 `tier = SandboxTier.CONTAINER`。

后端应复用既有 `sandbox_session_workspace` 的每 run 目录，并以固定镜像摘要和最小权限启动命令。概念上的 argv 如下（实际参数须按目标引擎和平台验证）：

```text
docker run --rm
  --network none
  --read-only
  --cap-drop ALL
  --pids-limit 128
  --memory 1g
  --cpus 1
  --security-opt no-new-privileges
  -v <per-run-workspace>:/workspace:rw
  -w /workspace
  <pinned-image-digest>
  sh -lc <command>
```

实现必须保持 `CommandRunner.run(command, *, timeout)` 的异步契约和现有 `exit_code/stdout/stderr` 格式，复用超时、取消时的清理、结果截断及 `SandboxSession` cwd 延续语义；还应为镜像来源、可挂载目录、默认禁网、CPU/内存/进程限制和超时提供显式、可审计的配置。

#### 重要边界

`CommandRunner` 目前只覆盖会 spawn 子进程的 shell 类工具。file、memory 等在 HeAgent 宿主 Python 进程内直接 I/O 的工具不会因 shell 进入容器而自动隔离。因此需要区分：

- **Shell 容器化：** 显著降低 AI 生成命令、构建和测试的执行风险，但宿主 file 工具仍可访问工作区；
- **整体运行时容器化/VM 化：** 将 HeAgent 进程、file 工具、shell 和外部 MCP 一并置于 OS 级隔离中，才更适合处理不可信 prompt、仓库和 MCP server。

两者都不是仅靠 LangChain wrapper 就能获得的保证。即使引入 LangChain 的某个供应商集成，也必须确认默认是否禁网、是否限制挂载、是否固定镜像、是否限制资源和是否会注入凭证。所有现有围栏和后端同样只是 defense-in-depth；不可信代码或外部 MCP 仍应在独立容器、VM 或等价 OS 级边界中运行。

### 3.4 AgentLoop 层：部分可行，是主要改造点

LangChain 的 `create_agent` 可以提供基本的模型—工具循环，但与当前 `AgentLoop` 并不等价。

| HeAgent 能力 | LangChain 是否直接等价 |
|---|---|
| 基本 tool call 循环 | 有 |
| 异步执行 | 有 |
| 基本流式输出 | 有 |
| Middleware | 有，但语义不同 |
| 消息历史 | 有 |
| 精确运行 checkpoint | 需要额外设计 |
| run_id / ExecutionLedger | 无直接等价 |
| PolicyEngine | 需要自定义 middleware/节点 |
| 审批 | 需要 interrupt 或自定义状态 |
| 沙箱 | 仍需保留 HeAgent |
| ContextCompressor | 需要自定义 |
| WindowReset | 需要自定义 |
| follow-up / steering | 需要自定义 |
| 子 Agent 递归深度 | 需要自定义 |
| 多层 Provider 容错 | 部分可用，语义不完全相同 |
| `/goal` 工作流 | 更适合 LangGraph，但不能直接替换 |
| 精确 `StreamEvent` | 需要适配 |

因此，直接用 `create_agent` 替换 `AgentLoop` 会产生较大的功能回退风险，并可能形成两个运行时同时存在。

### 3.5 Engine 层：不适合整体替换

HeAgent Engine 包含：

```text
EngineContainer
├── PolicyEngine
├── ToolExecutor
├── RunContext
├── Approval
├── Sandbox
├── RunStore
├── ExecutionLedger
├── Events
├── Hooks
└── Persistence
```

LangGraph checkpoint 主要保存：

- 图状态；
- 当前节点；
- 中断位置；
- 消息历史；
- 分支状态。

而 HeAgent 的 ExecutionLedger 解决的是另一类问题：

- 某个具体 `run_id:tool_call_id` 是否已有执行租约；
- 是否正在执行；
- 是否已经完成；
- 是否可以幂等复用结果；
- 策略收紧后是否必须重新执行；
- 是否发生重复 tool call 或并发重入。

因此二者不能互相替代。建议并存：

```text
LangGraph Checkpointer
    └── 图节点、图状态、interrupt、消息状态

HeAgent RunStore
    └── run snapshot、最终答案、token、运行元数据

HeAgent ExecutionLedger
    └── 工具调用租约、幂等、执行结果和审计
```

### 3.6 Context 层：可迁移，但建议保留核心实现

LangChain 的 Prompt Template、Messages Placeholder 和 Runnable 可以承载提示词拼接，但当前 HeAgent 的系统提示词顺序是项目行为契约：

```text
1. identity / SOUL
2. 用户 system 字符串
3. project-context
4. skills
5. facts / memory
6. memory-nudge
7. profile
```

如果改用 LangChain，需要保证：

- 顺序不变；
- system message 不被错误拆分；
- Anthropic system 参数仍正确；
- reasoning content 和 tool call 历史格式不被破坏；
- resume 时不重复注入；
- 压缩后 tool call / tool result 配对仍完整；
- window reset 后仍能恢复必要进度。

建议继续保留：

```python
build_system_prompt(...)
ContextCompressor
WindowReset
```

只在最终调用模型前后做 LangChain 消息转换。

### 3.7 Memory 层：不建议替换成 LangChain 普通 Memory

HeAgent 的 Memory 是领域能力：

```text
SkillStore
FactStore
ProfileStore
SoulStore
Dreaming
```

LangChain 的 memory、store、retriever 主要解决对话历史、检索和通用状态保存，不等价于 HeAgent 的自学习闭环。

建议保留 HeAgent Memory，并提供可选适配器：

```text
LangChain Agent
    ↓
HeAgent Memory Adapter
    ├── SkillStore
    ├── FactStore
    ├── ProfileStore
    └── SoulStore
```

不建议直接把事实、画像、技能和人格合并为一个向量数据库，因为它们的可信度、更新策略和生命周期不同。

### 3.8 SubAgent 层：可用 LangGraph 子图，但必须保留 HeAgent 约束

LangGraph 可以表达 supervisor/worker 或多 Agent 子图，但迁移时必须把以下信息显式放入 graph state 或 config：

```python
class HeAgentGraphState(TypedDict):
    run_id: str
    parent_run_id: str | None
    delegation_depth: int
    max_delegation_depth: int
    role: str | None
    tool_policy: object
```

必须继续保留：

- 父子 run_id；
- 角色和工具权限；
- 子 Agent 预算；
- 委派递归深度；
- 并行任务与结果数量一致性；
- 子 Agent 失败状态；
- Engine 和审计上下文继承。

建议保留 `SubAgent` 作为 HeAgent 外壳，内部按需运行 LangGraph 子图，而不是直接使用一个没有 HeAgent 约束的通用 Supervisor。

### 3.9 `/goal` 工作流：LangGraph 适合承载，但不是直接替换

当前 `/goal` 是声明式 Markdown 工作流，包含：

- frontmatter；
- Step 输入输出契约；
- validation section 门禁；
- Story/Epic 解析；
- checkpoint 恢复；
- artifact 目录布局；
- workflow 改名兼容；
- Step 07 的实现、测试、验证和收口评审；
- Step 08 的系统集成测试和全量质量门禁。

LangGraph 很适合表达这些流程：

```text
START
  ↓
market_research
  ↓
brainstorm
  ↓
analyze_requirements
  ↓
define_scope
  ↓
design_architecture
  ↓
refine_stories
  ↓
implement_story
  ↓
system_integration_test
  ↓
END
```

但 LangGraph 不会自动理解现有 `workflow.md` 语义、Markdown artifact、Story/Epic 路径、validation 门禁和存量 goal 数据。因此有两条路线：

#### 路线 A：保留 Markdown 工作流，内部使用 LangGraph 子图

```text
workflow.md
    ↓
HeAgent WorkflowParser
    ↓
HeAgent WorkflowRunner
    ↓
每个复杂步骤内部调用 LangGraph 子图
```

优点是保持当前契约和存量恢复兼容，风险最低。

#### 路线 B：将 workflow.md 编译为 LangGraph

```text
workflow.md
    ↓
Workflow Compiler
    ↓
StateGraph
    ↓
LangGraph Checkpointer + HeAgent Store
```

这需要实现：

- `WorkflowStepResource → GraphNode`；
- `story_loop → 动态子图或 Send`；
- `validation → Gate Node`；
- `waiting_user → interrupt`；
- checkpoint 双写或迁移；
- 旧 goal 数据兼容层。

这本质上是开发一个“ HeAgent Workflow DSL 到 LangGraph 的编译器”，不是简单更换 Agent 库。

## 四、三种迁移方案

### 方案一：只引入 LangChain Model/Tool 层

```text
HeAgent AgentLoop
    ↓
HeAgent LangChain Provider Adapter
    ↓
LangChain ChatModel
```

修改范围主要是：

- 新增 LangChain Provider 适配器；
- 增加 LangChain 消息转换；
- 可选增加 `langchain-openai`、`langchain-anthropic`、`langchain-ollama`；
- 保持 HeAgent ToolRegistry、ToolExecutor 和 Engine 不变。

优点：

- 风险最低；
- 不改变主循环；
- 不绕过 PolicyEngine；
- 不破坏沙箱和审计；
- 可以利用 LangChain 的模型集成；
- 后续可渐进引入 LangGraph。

缺点：

- 整体仍然是 HeAgent Runtime；
- 不会立刻获得 LangGraph 的工作流能力；
- LangSmith 追踪需要另行接入。

**推荐程度：最高。**

### 方案二：HeAgent Runtime + LangGraph Agent Loop

将当前主循环显式建模为 LangGraph：

```text
START
  ↓
prepare_context
  ↓
call_model
  ↓
has_tool_calls?
  ├── no → follow_up_or_finish
  └── yes
        ↓
  policy_gate
        ↓
  execute_tools
        ↓
  compress_or_reset
        ↓
  call_model
```

对应关系：

| HeAgent | LangGraph |
|---|---|
| `AgentState` | Graph State |
| `AgentLoop.run` | `graph.ainvoke` |
| `run_stream` | `graph.astream` |
| `pause/unpause` | interrupt / 外部状态 |
| `RunContext` | config + state |
| `PolicyEngine` | policy gate node |
| `ToolExecutor` | execute tools node |
| `ContextCompressor` | context management node |
| `WindowReset` | context reset node |
| `follow-up` | 条件边 |
| `steering` | 模型调用前节点 |
| `SubAgent` | 子图 |

优点：

- 状态机表达更清晰；
- checkpoint、interrupt 和 resume 更自然；
- 复杂工作流、审批和多 Agent 更容易扩展；
- 可接入 LangSmith 运行追踪。

缺点：

- 需要重构 AgentLoop；
- 需要维护 HeAgent State 与 LangGraph State 的转换；
- 不能直接使用默认 ToolNode；
- 流式事件需要重新适配；
- 现有 checkpoint 数据不能直接使用；
- 可能形成多个状态源。

**推荐程度：中高，适合作为第二阶段目标。**

### 方案三：全量改造成 LangChain/LangGraph 项目

需要重写或重构：

- AgentLoop；
- Provider 抽象；
- Message/Response 类型；
- ProviderChain、KeyRotation、Routing、Switchable；
- ToolRegistry 和 ToolExecutor 接线；
- EngineContainer；
- RunContext、RunStore、ExecutionLedger；
- pause/resume 和流式事件；
- ContextCompressor、WindowReset；
- SubAgent；
- `/goal` WorkflowRunner；
- Memory 接口；
- CLI/TUI bridge；
- 大量测试和存量 checkpoint 兼容逻辑。

主要风险：

1. 安全执行链被 LangChain 默认工具执行路径绕过；
2. LangGraph checkpoint、HeAgent RunStore、Ledger、SessionStore 和 WorkflowCheckpointStore 形成多个状态源；
3. reasoning、tool call、usage 和 stream 语义出现兼容问题；
4. 依赖、Pydantic、类型检查和版本升级成本增加；
5. 短请求中引入 Runnable、Graph、Callback 和状态序列化开销；
6. 在迁移期间出现功能回退和存量数据不可恢复。

**推荐程度：低，不建议作为当前项目第一选择。**

## 五、推荐的分阶段迁移路线

### 阶段 0：定义兼容边界

先明确以下接口不能被 LangChain 类型替换：

```text
HeAgent Message
HeAgent ToolCall
HeAgent ToolResult
HeAgent ProviderResponse
HeAgent RunContext
HeAgent PolicyVerdict
```

建立适配层目录，例如：

```text
src/heagent/integrations/langchain/
├── messages.py
├── models.py
├── tools.py
├── callbacks.py
└── tracing.py
```

### 阶段 1：只接入 LangChain ChatModel

增加：

```text
HeAgent Provider
    ↓
LangChain ChatModel Adapter
```

保持以下内容完全不变：

- `AgentLoop`；
- `PolicyEngine`；
- `ToolExecutor`；
- `SafetyGuard`；
- `ExecutionLedger`；
- Memory；
- `/goal`；
- CLI/TUI。

验收重点：

- 非流式回答一致；
- tool call 一致；
- reasoning content 不丢失；
- token 统计正确；
- 流式文本和工具事件正确；
- 429/401/5xx 分类行为不变；
- 全量测试通过。

### 阶段 2：将 HeAgent 工具暴露为 LangChain Tool

LangChain Tool 只负责声明和调用入口，真正执行仍进入：

```text
PolicyEngine → ToolExecutor → SafetyGuard → handler
```

需要增加回归测试，确保：

- 黑名单工具不能绕过；
- 路径越界不能绕过；
- 凭证文件 deny 不能绕过；
- 审批和沙箱裁决仍生效；
- ledger 幂等仍生效；
- MCP 工具仍使用同一治理链。

### 阶段 3：接入 LangSmith 或 LangChain Callback

只接入观测，不改变控制流：

```text
HeAgent Events
    ├── 本地日志 / ledger / observability
    └── LangChain Callback / LangSmith
```

LangSmith 可用于追踪模型调用、工具调用和图运行，但不能作为 HeAgent 本地审计、权限裁决或安全边界的替代品。

### 阶段 4：为一个非核心流程试用 LangGraph

优先选择：

- 独立的规划流程；
- 一个实验性子 Agent；
- 不影响存量 `/goal` 的新工作流；
- 不涉及核心 shell/file 工具的流程。

不要第一步就替换主 `AgentLoop` 或 `/goal` 主流程。

### 阶段 5：评估是否将 AgentLoop 图化

只有在确认以下指标满足后才考虑：

- LangChain 消息转换稳定；
- 流式 tool call 稳定；
- 工具治理没有绕过路径；
- checkpoint 与 resume 语义已验证；
- 运行开销可接受；
- 子 Agent 和审批可以正确恢复；
- 存量 session/goal 兼容策略已经明确。

如果满足，再实现自定义 LangGraph 节点，而不是直接使用黑盒 Agent：

```text
HeAgentModelNode
HeAgentPolicyNode
HeAgentToolNode
HeAgentContextNode
HeAgentCheckpointNode
```

### 阶段 6：最后评估 `/goal` 编译为 LangGraph

这一步应单独立项，不能混入 Provider 或 AgentLoop 迁移。需要先完成：

- Markdown DSL 版本化；
- checkpoint schema 版本化；
- 存量 goal 迁移方案；
- artifact 路径兼容策略；
- Story/Epic 状态机映射；
- validation gate 映射；
- waiting_user 和 interrupt 映射；
- 双写和回滚策略。

## 六、最终建议

### 建议采用的目标架构

```text
CLI / GUI / /goal
        ↓
HeAgent Runtime
        ├── Agent orchestration
        ├── Policy / Approval / Sandbox
        ├── ToolExecutor / Ledger
        ├── Memory / Cron / Persistence
        └── Workflow compatibility
                ↓
        LangChain Adapter Layer
                ├── ChatModel
                ├── Message conversion
                ├── Tool schema conversion
                └── Callback / tracing
                        ↓
                LangChain / LangGraph
```

### 不建议做的事情

- 不要直接删除 `AgentLoop`；
- 不要直接用默认 `ToolNode` 替换 `ToolExecutor`；
- 不要让 LangChain 类型进入 `engine/` 和 `memory/` 的领域接口；
- 不要一开始迁移 `/goal` 和存量 checkpoint；
- 不要把 LangChain checkpoint 当成 ExecutionLedger；
- 不要把 LangChain middleware 当成安全边界；
- 不要因为 LangChain 支持工具调用，就省略 HeAgent 的 PolicyEngine 和沙箱；
- 不要在没有回滚方案的情况下做全量替换。

### 综合判定

| 维度 | 结论 |
|---|---|
| 引入 LangChain ChatModel | 高度可行 |
| 引入 LangChain Tool Schema | 高度可行 |
| 用 LangChain 替换 Provider | 可行，需适配 reasoning/usage/stream |
| 用 LangChain Agent 替换 AgentLoop | 可行但收益有限，风险较高 |
| 用 LangGraph 表达复杂 Agent 状态机 | 可行，适合第二阶段 |
| 用 LangGraph 替换 Engine 治理 | 不建议 |
| 用 LangChain Memory 替换 HeAgent Memory | 不建议 |
| 用 LangGraph 直接替换 `/goal` | 可行但需要编译器和数据迁移 |
| 全量迁移为 LangChain 项目 | 技术可行，工程上不划算 |

**最终建议：先做适配层，不做重写；先引入 LangChain 的模型能力，再根据实际需求引入 LangGraph 的状态机能力。**
