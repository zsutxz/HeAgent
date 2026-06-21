---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8]
lastStep: 8
inputDocuments:
  - docs/_bmad-output/planning-artifacts/briefs/brief-heagent-2026-06-20/brief.md
  - docs/_bmad-output/planning-artifacts/briefs/brief-heagent-2026-06-20/addendum.md
  - docs/_bmad-output/planning-artifacts/briefs/brief-heagent-2026-06-20/.decision-log.md
  - docs/_bmad-output/planning-artifacts/prds/prd-heagent-2026-06-20/prd.md
  - docs/_bmad-output/planning-artifacts/prds/prd-heagent-2026-06-20/.decision-log.md
  - docs/_bmad-output/planning-artifacts/prds/prd-heagent-2026-06-20/review-rubric.md
  - docs/planning/architecture/architecture.md
  - CLAUDE.md
workflowType: 'architecture'
project_name: 'HeAgent'
user_name: 'tan'
date: '2026-06-20'
status: 'complete'
completedAt: '2026-06-20'
---

# Architecture Decision Document — HeAgent MCP Client 集成

_本文档通过分步协作逐步构建。各架构决策章节随我们逐步推进而追加。_

> **作用域**：本文是 MCP Client 集成（新增 epic）的架构决策，不是 HeAgent 整体架构重写。既有架构基线见 `docs/planning/architecture/architecture.md`；本文聚焦「如何把 MCP client 适配层干净地嵌入既有 DAG / `ToolRegistry` / `AgentLoop`」。

## Project Context Analysis

### Requirements Overview

**Functional Requirements（11 FR / 5 组）：**

| 组 | FR | 架构含义 |
|---|---|---|
| 连接与生命周期 | FR-1,2,3 | `MCPClientManager` 管理 stdio 子进程 + Streamable HTTP 双 transport；生命周期与 `AgentLoop` 绑定（`AsyncExitStack` 托管）；区分「连接建立失败（工具不注入）」vs「运行时断连（已注册工具调用时降级）」 |
| 发现与桥接 | FR-4,5,6 | 连接后 `tools/list` 动态发现 → 映射为 `ToolSchema` → 注册进 `ToolRegistry`；调用结果桥接为 `ToolResult`，走与内置工具一致的并行执行路径；多 server 加 namespace 前缀去歧义 |
| 声明式配置 | FR-7,8 | 项目根 `.mcp.json` 声明 `mcpServers`（对齐 Claude Code/Cursor）；支持 `${ENV}` 插值；PAT 走环境变量不落明文；无配置 = 纯内置工具模式启动，不报错 |
| GitHub 只读验收 | FR-9 | 官方远程 GitHub server（Streamable HTTP）跑通「列 open issue」+「代码搜索」两类 E2E，结果经 `ToolResult` 桥接可断言关键字段 |
| 安全 | FR-10,11 | MCP server 归入既有不可信边界（CLAUDE.md 安全声明更新）；工具返回内容视为不可信；`SafetyGuard` 扩展为架构探索项，V1 以边界声明为主 |

**Non-Functional Requirements（驱动架构的 7 项）：**

- **NFR-1 全异步**：库代码无同步 I/O；MCP SDK 原生 asyncio。
- **NFR-2 零回归**：18 内置工具 + 既有测试零回归；覆盖率以实现时基线不下降。
- **NFR-3 版本可控**：`mcp>=1.27,<2`；握手/transport 封装在 `MCPClientManager` 内部 → v2/stateless 迁移改动局部化、不波及 `AgentLoop`。
- **NFR-4 启动性能**：多 server 连接 + 发现不显著拖慢启动（eager/lazy 取舍）。
- **NFR-5 可观测**：连接状态 / 发现数量 / 调用结果有日志（stdlib logging）。
- **NFR-6 错误隔离**：单 server 失败不影响其他 server 与内置工具。
- **NFR-7 代码规范**：PEP8 / Pydantic BaseModel / 120 行宽 / 3.11+；tool 层禁止从 `agent/` 导入（DAG）。

**Scale & Complexity:**

- Primary domain: 后端 AI Agent 框架库（异步 Python，brownfield 扩展）
- Complexity level: 中等 — 范围单一（一个 epic），无分布式/实时/合规，但外部进程生命周期 + 协议封装边界 + 无侵入集成三处需精细设计
- Estimated architectural components: ~4-5 个新增模块

### Technical Constraints & Dependencies

- **语言/运行时**：Python 3.11+，全异步（`async/await`，CLI 经 `asyncio.run()` 桥接）。
- **新增依赖**：官方 `mcp` Python SDK，pin `mcp>=1.27,<2`（stable 1.28.0，2026-06）；SDK 原生 asyncio，`ClientSession` / `StdioServerParameters` / `streamable_http_client`。
- **协议窗口**：stable `2025-11-25`；`2026-07-28` RC 为 breaking（转 stateless、删 `initialize` 握手）→ V1 落 stable，适配层为迁移留接口。
- **架构 DAG 约束**：MCP 属 `tools/` 层（PRD §6 / CLAUDE.md），禁止从 `agent/` 导入；复用 `ToolRegistry` / `ToolSchema` / `ToolResult` / `SafetyGuard` / 既有异常层级（`HeAgentError → ToolError/ProviderError`）。
- **既有体系（brownfield 基线）**：`ToolRegistry` 进程单例 + `@tool` 装饰器静态注册；`AgentLoop` 顶层编排；Provider 三层容错（重试/密钥轮换/chain）；`ContextCompressor`；中间件管道 `(Request, NextFn) → Response`；`.heagent/` 运行时产物目录。
- **配置形态**：声明式 `mcpServers`（项目根 `.mcp.json`，对齐 Claude Code / Cursor）。

### Cross-Cutting Concerns Identified

1. **异步生命周期管理** — MCP server 连接生命周期与 `AgentLoop` 绑定；stdio 子进程 spawn/监控/优雅关闭、防僵尸/env 泄漏；`AsyncExitStack` 统一托管。（影响：`MCPClientManager` ↔ `AgentLoop` 集成点）
2. **错误隔离与降级** — 连接建立失败 vs 运行时断连两条路径；单 server 失败不影响其他 server 与内置工具（NFR-6）；复用既有异常层级，不崩溃 agent。（影响：注册路径 + 调用路径）
3. **协议演进封装** — `initialize` 握手 / transport 机制 / protocolVersion 协商封在 `MCPClientManager` 内部，`AgentLoop` 只见 `ToolSchema`/`ToolResult`；为 2026-07-28 stateless 迁移留接口。（影响：模块边界）
4. **工具规模与命名** — 多 server 叠加工具数量爆炸侵蚀上下文、降低工具选择准确率（R3）；namespace 前缀去歧义（FR-6）；eager/lazy 发现取舍；可复用 `ContextCompressor`。（影响：发现策略 + 注册路径）
5. **配置与鉴权安全** — `.mcp.json` 声明 + `${ENV}` 插值；PAT 走环境变量不落配置明文；无配置时纯内置模式不阻断。（影响：配置加载 + 启动路径）
6. **安全边界** — MCP server = 不可信代码 + 不可信输出进 LLM 上下文，与 `SafetyGuard` 局限同构（FR-10/11）；返回内容视为不可信（prompt injection 无隔离）；须 OS 级沙箱兜底。（影响：安全声明 + 工具调用路径）

## Starter Template Evaluation

### Primary Technology Domain

**自定义 Python AI Agent 框架库（brownfield 扩展）** — 非 Web/API/Mobile/CLI-starter 项目，不适用标准 starter template。与既有架构（2026-05-23）结论一致：技术栈已锁定，无匹配的 starter。

### Starter Options Considered

**评估结论：不引入外部 starter template。**

原因：
1. HeAgent 是已落地的自定义框架，目录结构 / 配置 / 测试 / lint / 类型检查基础设施全部就位（`pyproject.toml` / `ruff.toml` / `pytest` / `mypy` / `src/heagent/` 布局）。
2. 本次是给既有框架加一个 **epic 级新能力**（MCP 适配层），不是新建项目——新增代码落进既有 `tools/` 层目录结构即可。
3. 无匹配的 starter（agent 框架库 + brownfield 扩展，没有现成模板）。

**唯一的新依赖决策：MCP Python SDK。**（已 web 验证版本，2026-06-20）

### Selected Starter: 无（沿用既有项目骨架）

**选型理由：** brownfield 扩展，骨架已存在；新增代码遵循既有 `tools/` 层目录约定，复用既有构建 / 测试 / lint 基础设施。

**初始化命令：** 无（不新建项目）。新增依赖加入 `pyproject.toml`：

```bash
pip install "mcp>=1.28,<2"   # stable 1.28.0 (2026-06-16)；<2 排除 v2 alpha（2026-07-27 预发布）
```

**既有骨架提供的架构决策（无需重定）：**

| 维度 | 既有决策（沿用） |
|---|---|
| 语言/运行时 | Python 3.11+，全异步 |
| 数据模型 | Pydantic v2 BaseModel（新增 MCP 模型沿用） |
| HTTP 客户端 | httpx.AsyncClient（MCP transport 复用 SDK 自带） |
| 测试框架 | pytest + pytest-asyncio（auto 模式）|
| Lint/Format | ruff（check + format）|
| 类型检查 | mypy |
| CLI | click（经 `asyncio.run()` 桥接）|
| 配置 | pydantic-settings `Settings` 单例 + `.env` |
| 日志 | stdlib `logging`，每模块 `getLogger(__name__)` |
| 代码组织 | 功能域目录（MCP 落 `tools/` 层）|

**新增依赖（MCP SDK）的架构含义：**

- `mcp` SDK 原生 asyncio（`ClientSession` / `StdioServerParameters` / `streamable_http_client`），与全异步约束（NFR-1）天然契合。
- SDK 自带 transport（stdio 子进程管理 + Streamable HTTP），HeAgent 不重造 transport——只做 SDK ↔ HeAgent `ToolSchema`/`ToolResult` 的适配桥接。
- **版本窗口（NFR-3 承重）**：`>=1.28,<2` 锁 stable，`<2` 排除 2026-07-27 的 v2 alpha；协议 `initialize` 握手等 breaking 细节封在 `MCPClientManager` 内部，为 2026-07-28 stateless 迁移留接口。

> **Note：** 项目初始化不是首个 story（项目已存在）。首个实现 story 应是 MCP 适配层的基础设施搭建（依赖引入 + `MCPClientManager` 骨架）——由下游 epics 细化。

## Core Architectural Decisions

> 下列决策基于**真实代码核实**（`registry.py` / `decorator.py` / `types.py` / `loop.py` / `cli.py` / `exceptions.py`），非臆断。关键发现：`ToolRegistry.register(schema, handler)` 已原生支持动态注册 → MCP 复用既有注册路径，**registry API 零扩展**；`_invoke()` 做 `handler(**call.arguments)` + async 自检 → MCP 闭包 handler 天然契合，**AgentLoop 执行路径零改动**。

### Decision Priority Analysis

**Critical Decisions（阻塞实现）：**

- A. 模块落点（`tools/mcp/`，纠正老 `providers/mcp.py` 占位）
- B. 工具发现/注册路径（复用 `register()`，eager+并发+隔离）
- C. 生命周期绑定（外部 `async with` ctx mgr，AgentLoop 不动）
- D. 协议封装边界（`MCPClientManager` 吃掉握手 + transport）

**Important Decisions（塑形）：**

- E. Transport 分派（内部 dispatch，YAGNI 不抽 Transport Protocol）
- F. Namespace 命名（`<server>__<tool>`）
- G. 结果与错误映射（CallToolResult → ToolResult，V1 text-only，is_error 经抛 `ToolError`）
- H. 配置加载（独立 `.mcp.json` loader + Settings 门控）

**Deferred Decisions（V1 简化 / 后续）：**

- `SafetyGuard` 扩展到 MCP 工具调用（架构探索项，V1 以安全声明 + 边界声明为主，DP-4）
- Resources / Prompts 原语（V1 只接 Tools，D2）
- 写操作（建 issue / 提 PR，紧接下一步，D3）
- 正式 `Transport` Protocol 抽象（仅 2 种 transport 时 YAGNI）

### A. 模块落点与集成边界 — `tools/mcp/` 层

**决策：MCP 落 `tools/mcp/`，纠正老架构 `providers/mcp.py` 占位。**

- MCP 暴露的是**工具**（model-controlled，进 `ToolRegistry`），不实现 `BaseProvider.send()`，不是模型 provider。`providers/` 层语义 = 「与模型通信」。
- CLAUDE.md / PRD §6 均指向 `tools/` 层；老 `providers/mcp.py` 是 2026-05 投机性占位（当时 FR-18「MVP 后」），现正式纠正。
- **DAG 合规**：`tools/mcp/` 仅从 `tools.registry` / `types` / `exceptions` 导入，**禁止从 `agent/` 导入**；`cli.py` 负责装配（同既有 `configure_skill_tools` / `configure_subagent_tools` 模式）。

### B. 工具发现与注册路径 — 复用 `register()`，eager + 并发 + 隔离

**注册路径：MCP 调既有 `registry.register(ToolSchema(...), mcp_handler)`，registry API 零扩展。**

`ToolRegistry.register(schema, handler)`（registry.py:47）本就接受 `ToolSchema` + handler 对象；`@tool` 装饰器内部即构造 schema 后调 `register()`。MCP 工具动态发现的 `inputSchema`（JSON Schema dict）直接填入 `ToolSchema.parameters`。

**发现时序：eager + 并发 + 隔离 + 每服务器连接超时**（否决 lazy；超时为 step-7 验证 apply 的 refinement）。

- `MCPClientManager.__aenter__` 用 `asyncio.gather(*connect_tasks, return_exceptions=True)` **并发**连接所有 server + `tools/list` 发现 + 映射 + 注册；**在 `loop.run()` 之前完成**（满足 FR-2 时序锚点——`enabled_schemas()` 在首次 `_call_provider` 调用，loop.py:438，LLM 首轮即见全部 MCP 工具）。
- **否决 lazy**：LLM 只能从发给它的 schema 列表里选工具；lazy 发现意味着工具未被发现时 LLM 看不到它（鸡生蛋）。eager 是 V1 唯一合理选择；启动不阻塞 AgentLoop 构造（连接在 `async with` 阶段并发进行）。
- 并发连接 + 单 server 失败隔离（NFR-6）：某 server 连接失败 → 工具不注入 + 记日志（NFR-5），不阻塞其他 server 与内置工具。
- **每服务器连接超时**（NFR-4，step-7 apply）：每 server 连接用 `asyncio.wait_for(_connect(entry), timeout=...)` 包裹，超时即隔离该 server，防单 server 卡死无限阻塞 agent 启动。

### C. 生命周期绑定 — 外部 `async with` ctx mgr，AgentLoop 零改动

**决策：`MCPClientManager` 是 async ctx mgr，CLI 用 `async with` 包住 AgentLoop 运行；AgentLoop 契约不变（NFR-2 零回归）。**

```python
# cli.py 内（_run_single / _run_chat）
async with MCPClientManager(mcp_config) as mcp:   # 并发连接 + 发现 + 注册到 ToolRegistry 单例
    loop = AgentLoop(provider, ...)
    result = await loop.run(prompt)
# __aexit__：unregister 全部 MCP 工具 + 关闭所有 session/子进程（AsyncExitStack）
```

- 理由：① NFR-2 零回归——AgentLoop 无异步生命周期钩子（`__init__` 同步、`run()` 异步入口），改它会动核心契约；② NFR-3 封装——生命周期全在 MCPClientManager 内；③ 沿用 `CronScheduler` start/stop 先例（cli.py:269-300）；④ `ToolRegistry` 是进程单例，MCP 进/出时 register/unregister，干净（退出即还原纯内置状态，利于测试隔离）。
- **替代方案（否决）**：让 AgentLoop 变 async ctx mgr（`__aenter__`/`__aexit__`）——改动核心契约，违反零回归。

### D. 协议封装边界 — `MCPClientManager` 吃掉握手 + transport（NFR-3 承重）

- `initialize` 握手 / `protocolVersion` 协商 / transport 细节全封在 `MCPClientManager` 内部；**`AgentLoop` 只见 `ToolSchema` / `ToolResult`**。
- 为 2026-07-28 stateless 迁移（删 `initialize`、删 `Mcp-Session-Id`，SEP-2575）留接口：迁移时改动限于 `MCPClientManager` 内部，不波及 `AgentLoop` / `ToolRegistry`。
- MCP 错误映射到 `ToolError`（tools/ 层语义，`exceptions.py` 既有层级），不引入新异常。

### E. Transport 分派 — 内部 dispatch，不抽 Transport Protocol（YAGNI）

- stdio（`mcp.client.stdio.stdio_client`）与 Streamable HTTP（`mcp.client.streamable_http.streamable_http_client`）是 SDK 两个 async ctx mgr；`MCPClientManager._connect(entry)` 内部按配置类型分派。
- **否决正式 `Transport` Protocol 抽象**：仅 2 种 transport，stateless 迁移本就封在 MCPClientManager 内，YAGNI；第 3 种 transport 出现再重构。

### F. Namespace 命名 — `<server>__<tool>`

- 工具名 = **`<server>__<tool>`**（双下划线，LangChain 风格，无歧义，LLM 友好）。server 名规整化（小写、非字母数字 → `_`）。
- 冲突处理：两 server 规整后撞前缀 → 注册时检测并告警 / 去重（解决 review-rubric 的 FR-6 low finding）。

### G. 结果与错误映射 — CallToolResult → ToolResult（V1 text-only）

- `CallToolResult.content`（TextContent / ImageContent / EmbeddedResource 块）→ **V1 仅取 TextContent 拼接**为 `ToolResult.content`（str）；非文本块 → `[image]` / `[resource: uri]` 占位（V1 简化，LLM 拿到文本）。
- `CallToolResult.isError=True` → **MCP handler 抛 `ToolError`**，走 `_execute_one` 的 except 路径（loop.py:510）→ `ToolResult(is_error=True)`；**AgentLoop 零改动**即保留错误语义。
- FR-9 schema：GitHub issue 列表项（`number/title/state/url`）/ 搜索命中（`path/snippet`）经 TextContent 到达，text 拼接即可断言。

### H. 配置加载 — 独立 `.mcp.json` loader + Settings 门控

- `.mcp.json`（项目根）= 独立结构化多 server JSON，**独立 `MCPConfig` Pydantic 模型 + `load_mcp_config(path)` loader**，不进 `Settings`（Settings 是 `.env`/env 单值驱动，与多 server JSON 性质不同）。
- `${ENV}` 插值：加载时从 `os.environ` 展开；**引用的变量未设 → 加载即报错（fail-fast）**，PAT 绝不落配置明文（DP-2）。
- Settings 增门控字段：`mcp_enabled: bool = True`、`mcp_config_path: str = ".mcp.json"`。无文件 / 空 → 纯内置工具模式，不报错不阻断（FR-7）。

### Decision Impact Analysis

**实现序列（下游 epics 拆分依据）：**

1. 依赖引入（`mcp>=1.28,<2`）+ `tools/mcp/` 骨架
2. `config.py`（MCPConfig + loader + env 插值）+ 单元测试
3. `mapping.py`（ToolSchema 映射 + 结果/错误映射）+ 测试（Stub session）
4. `manager.py`（MCPClientManager ctx mgr + 并发连接 + 隔离 + AsyncExitStack）+ 测试
5. `cli.py` 装配（`async with MCPClientManager` 包 `_run_single` / `_run_chat`）
6. GitHub 只读 E2E 验收（FR-9，官方远程 server）

**跨组件依赖（单向、无环，合规 DAG）：**

- `config` → `manager`（读配置）；`mapping` ← `manager`（发现后映射）；`manager` → `ToolRegistry`（注册）；`cli` → `manager`（生命周期）。
- MCP 层（`tools/mcp/`）→ 叶子类型（`types` / `exceptions` / `registry`）；**无 `agent/` 反向依赖**。

## Implementation Patterns & Consistency Rules

> **brownfield 铁律**：新增 MCP 代码**继承既有 codebase 全部模式**（既有架构 2026-05-23 已定）：PEP8 命名 / `snake_case.py` 文件 / `PascalCase` 类名 / 无 `Protocol`·`Interface` 后缀 / async 方法无 `_async` 后缀 / Pydantic `BaseModel` 数据模型 / `HeAgentError` 异常层级 / 每模块 `logging.getLogger(__name__)` / 120 行宽 / Python 3.11+。下列仅列 **MCP 特有、AI agent 可能分歧**的新规则。

### Pattern Categories Defined

**Critical Conflict Points Identified:** 8 处 MCP 特有分歧点（落点 / 注册方法 / 工具名 namespace / 异常类型 / 重试 / 数据模型 / 生命周期 / 结果序列化），AI agent 若不约束会写出互不兼容的代码。

### Naming Patterns

**模块/文件/类命名（继承既有）：**

- 模块：`tools/mcp/`（与 `tools/builtins/` 平级）
- 文件：`manager.py`（`MCPClientManager`）/ `config.py`（`MCPConfig` 等）/ `mapping.py`（映射函数）/ `__init__.py`（导出）
- 类名：`MCPClientManager`、`MCPConfig`、`StdioServerConfig`、`HttpServerConfig`（PascalCase，无 Protocol 后缀）
- async 方法无 `_async` 后缀（如 `async def connect()` 而非 `connect_async()`）

**LLM 可见工具名（MCP 特有）：**

- 内置工具用裸名（`shell` / `file_read`）；**MCP 工具必须 namespace**：`<server>__<tool>`（双下划线）。
- server 名规整化：小写 + 非字母数字 → `_`（如 `GitHub-MCP` → `github_mcp`）。
- 冲突检测：注册时若前缀撞名，告警并跳过 / 去重。

**Settings 字段：**

- `mcp_enabled: bool`、`mcp_config_path: str`（snake_case，对齐既有 `cron_enabled` / `skill_match_threshold`）。

**`.mcp.json` 字段（对齐 Claude Code / Cursor，非 HeAgent 自创）：**

- 顶层 `{"mcpServers": {"<name>": {...}}}`
- stdio entry：`command` / `args` / `env`
- http entry：`url` / `headers`
- 环境插值语法：`${VAR_NAME}`

### Structure Patterns

**模块组织：**

- `tools/mcp/` 与 `tools/builtins/` 平级；MCP 工具是**动态发现**的，不在 `builtins/` 下硬编码。
- `tools/mcp/` 仅依赖叶子类型（`types` / `exceptions`）+ `tools.registry`；**禁止从 `agent/` 导入**（DAG）。

**测试位置（继承既有 — 平铺不镜像）：**

- `tests/test_mcp_config.py`、`tests/test_mcp_mapping.py`、`tests/test_mcp_manager.py`（平铺 `tests/`，**不**镜像 `tools/mcp/` 子目录 —— CLAUDE.md 明确）。
- MCP manager 测试用 **Stub session**（mock `ClientSession.list_tools` / `call_tool`），不打真实网络。
- GitHub E2E 验收测试**独立标记**（`@pytest.mark.integration` / 需 `GITHUB_TOKEN`），不进默认 `pytest` 全绿基线（NFR-2 零回归指单测全绿）。

**配置文件位置：**

- 项目根 `.mcp.json`（运行时读取）；`.mcp.json.example` 作示例（对齐 `.env.example` 惯例）。
- `.mcp.json` 含 `${ENV}` 插值 → 密钥在 env，不落配置明文；`.mcp.json` 含私有 server URL 时是否提交由用户自决，框架不强求 gitignore。

### Format Patterns

**数据模型（继承 — Pydantic）：**

- `MCPConfig`、`StdioServerConfig`、`HttpServerConfig` 用 `Pydantic BaseModel`，**不用 dataclass**（CLAUDE.md：跨模块数据流一律 Pydantic；dataclass 仅限 `AgentState` / `SubAgentResult` 内部状态）。

**`.mcp.json` ↔ 模型映射：**

- `inputSchema`（MCP 工具的 JSON Schema）→ **直接填入 `ToolSchema.parameters`**，passthrough 不重映射（MCP 已是标准 JSON Schema）。

**结果映射（决策 G — V1 text-only）：**

- `CallToolResult.content` 块：取 `TextContent.text` 拼接 → `ToolResult.content`；`ImageContent` → `[image]` 占位；`EmbeddedResource` → `[resource: uri]` 占位。
- 多 text 块用 `\n` 连接。

### Communication Patterns

**日志（继承 — stdlib logging）：**

- `logger = logging.getLogger(__name__)`；连接 / 断开 / 发现 N 个工具 / 调用 → INFO；失败 / 重试 → WARNING；连接握手细节 → DEBUG（NFR-5 可观测）。
- 不引入新日志库。

**结果回流（继承 — 无新事件系统）：**

- MCP 工具结果走 `_execute_one` → `ToolResult` → `Message(role=TOOL)` → 既有 AgentLoop 消息流，与内置工具**完全一致**（含并行执行 `asyncio.gather`）。

### Process Patterns

**错误处理（决策 D + 既有层级）：**

- MCP 连接失败 / 运行时断连 → `ToolError`；config 引用的 `${VAR}` 未设 → 加载即 fail-fast；单 server 失败隔离，不崩溃 agent（NFR-6）。
- `CallToolResult.isError=True` → handler 抛 `ToolError` → `_execute_one` except → `ToolResult(is_error=True)`（LLM 据此自决重试）。

**重试（继承 — 不为 MCP 新建）：**

- 既有 `make_retry_middleware` 包的是 **provider 调用**，不包工具调用。MCP 工具调用走 `_execute_one`（异常→is_error），**不加 MCP 专用重试**；瞬态失败由 LLM 收到 is_error 后自行重试 —— 与内置工具行为一致。

**生命周期（决策 C）：**

- `MCPClientManager` 实现 `__aenter__` / `__aexit__`；内部 `AsyncExitStack` 托管所有 server 的 transport ctx + `ClientSession` ctx。
- `__aenter__`：并发连接（`asyncio.gather(..., return_exceptions=True)`）+ 发现 + 注册。
- `__aexit__`：逆序 unregister 全部 MCP 工具 + 关闭所有 session/子进程（优雅，防僵尸 / env 泄漏）。

**验证时机：**

- `.mcp.json` 结构 → 加载时 Pydantic 校验；`${ENV}` 插值 → 加载时展开；server 连接 → `__aenter__` eager 验证（失败隔离）。

### Enforcement Guidelines

**所有 AI agent 必须：**

- MCP 代码落 `tools/mcp/`，不从 `agent/` 导入（DAG）。
- 工具注册复用 `registry.register()`，**不**给 `ToolRegistry` 加新方法。
- MCP 工具名带 `<server>__` namespace，不裸注册。
- MCP 异常用 `ToolError`，不新建异常类、不抛裸 `Exception`。
- 数据模型用 Pydantic `BaseModel`。
- 生命周期用外部 `async with MCPClientManager`，**不**改 `AgentLoop`。
- async 方法无 `_async` 后缀，类无 `Protocol` 后缀。

**模式校验：**

- `ruff check`（命名 / 格式）+ `mypy src`（类型注解完整性）全绿。
- PR review 检查：目录归属（`tools/mcp/`）、DAG 合规（无 `agent/` 反向导入）、namespace、ToolError 使用。
- `pytest` 全绿（NFR-2）；MCP 单测用 Stub session，不依赖网络。

### Pattern Examples

**Good：**

```python
# tools/mcp/manager.py
class MCPClientManager:
    """MCP server 连接 + 工具桥接生命周期管理（async ctx mgr）。"""

    def __init__(self, config: MCPConfig) -> None:
        self._config = config
        self._stack = AsyncExitStack()

    async def __aenter__(self) -> MCPClientManager:
        await self._connect_all()   # 并发连接 + 发现 + 注册（return_exceptions 隔离）
        return self

    async def __aexit__(self, *exc) -> None:
        self._unregister_all()      # 从 ToolRegistry 摘除 MCP 工具
        await self._stack.aclose()  # 关闭所有 session/子进程
```

```python
# MCP 闭包 handler（吃 kwargs，抛 ToolError 表 is_error）
async def _make_handler(session, namespaced_name: str) -> Callable:
    async def handler(**kwargs):
        result = await session.call_tool(tool_name, kwargs)
        if result.isError:
            raise ToolError(_to_text(result))
        return _to_text(result)
    return handler
```

**Anti-Pattern：**

```python
# ❌ providers/mcp.py            ← 错：落点应是 tools/mcp/
# ❌ registry.register_mcp(...)   ← 错：应复用既有 register()
# ❌ registry.register(schema_without_namespace, ...)   ← 错：缺 <server>__ 前缀
# ❌ class MCPException(Exception): ...   ← 错：应用 ToolError，不抛裸 Exception
# ❌ async def connect_async(self): ...   ← 错：async 方法不加 _async 后缀
# ❌ await loop.__aenter__()      ← 错：不应改 AgentLoop 为 ctx mgr，外部 MCPClientManager 才是
```

## Project Structure & Boundaries

> brownfield 增量：下列为 MCP 集成**新增/改动**的文件，其余既有结构（`providers/` / `memory/` / `context/` / `cron/` / `agent/` 等）不变。

### 新增/改动文件树

```
src/heagent/
├── tools/
│   └── mcp/                          # 【新增】MCP client 适配层（tools/ 层，与 builtins/ 平级）
│       ├── __init__.py               # 导出 MCPClientManager, MCPConfig, load_mcp_config
│       ├── manager.py                # MCPClientManager（async ctx mgr）：连接/发现/注册/关闭
│       ├── config.py                 # MCPConfig + StdioServerConfig/HttpServerConfig + load_mcp_config() + ${ENV} 插值
│       └── mapping.py                # MCP tool → ToolSchema；CallToolResult → str + is_error 映射
├── config.py                         # 【改动】Settings 增 mcp_enabled / mcp_config_path 门控字段
└── cli.py                            # 【改动】_run_single / _run_chat 内 async with MCPClientManager 包住 run

tests/                                 # 平铺（继承既有约定，仅 providers/ 是子目录例外）
├── test_mcp_config.py                # MCPConfig 校验 / ${ENV} 插值 / 缺文件纯内置行为
├── test_mcp_mapping.py               # tool→ToolSchema 映射 / CallToolResult→str / isError→ToolError（Stub session）
└── test_mcp_manager.py               # MCPClientManager ctx mgr：并发连接 / 隔离 / 注册-unregister（Stub session）
# 可选：tests/test_mcp_github_e2e.py   # @pytest.mark.integration，需 GITHUB_TOKEN，不进默认全绿基线

pyproject.toml                         # 【改动】dependencies 增 "mcp>=1.28,<2"
.mcp.json.example                      # 【新增】配置示例（对齐 .env.example 惯例）
CLAUDE.md                              # 【改动】安全声明覆盖 MCP + 模块速查表增 MCP 行 + DAG 说明
```

### Architectural Boundaries

**DAG 边界（核心约束）：**

```
tools/mcp/ ──→ types ──→ exceptions ──→ tools.registry
   ↓（仅此三个方向，无 agent/ 反向依赖）
cli.py ──→ tools/mcp（装配生命周期）
```

- `tools/mcp/` 仅从 `types` / `exceptions` / `tools.registry` 导入；**禁止从 `agent/` 导入**。
- `cli.py` 是唯一装配点（同既有 `configure_skill_tools` / `configure_subagent_tools` 模式）。

**ToolRegistry 边界：** 复用既有 `register(schema, handler)` / `unregister(name)` / `enabled_schemas()`，**不扩 API**。MCP 工具与内置工具共处同一进程单例。

**AgentLoop 边界：** **零改动**——MCP 通过注册进 `ToolRegistry` 单例，AgentLoop 既有的 `_call_provider`（`enabled_schemas()`）与 `_execute_one`（`get_handler` → `_invoke`）自动覆盖 MCP 工具。

**配置边界：** `.mcp.json`（项目根，外部结构化文件）↔ `MCPConfig`（Pydantic 模型）↔ Settings 门控（`mcp_enabled` / `mcp_config_path`）。密钥经 `${ENV}` 从 `os.environ` 注入，不落 `.mcp.json` 明文。

### Requirements to Structure Mapping

| FR | 文件 | 说明 |
|---|---|---|
| FR-1 | `manager.py`（`_connect` 分派）| stdio + Streamable HTTP 双 transport |
| FR-2 | `manager.py`（`__aenter__`/`__aexit__`）+ `cli.py` | 生命周期与 AgentLoop 绑定 + eager 发现（首轮可见）|
| FR-3 | `manager.py`（`_connect_all` 用 `return_exceptions`）| 连接失败隔离，工具不注入 |
| FR-4 | `mapping.py` + `manager.py`（register）| `tools/list` 发现 → ToolSchema → 注册 |
| FR-5 | `mapping.py` + `manager.py`（handler）| 调用结果 → ToolResult |
| FR-6 | `mapping.py`（namespace）+ `manager.py` | `<server>__<tool>` 去歧义 |
| FR-7 | `config.py` + `config.py`（Settings）| `.mcp.json` 声明 + 无配置纯内置 |
| FR-8 | `config.py`（`${ENV}` 插值）| 环境变量插值 + PAT 不落明文 |
| FR-9 | `tests/test_mcp_github_e2e.py` | GitHub 只读 E2E（官方远程 server）|
| FR-10/11 | `CLAUDE.md`（安全声明）+ `manager.py` | 不可信边界 + SafetyGuard 不扩展（V1）|

### Integration Points

**外部集成点：**

- `tools/mcp/manager.py` → MCP server 进程（stdio 子进程）/ 远程 HTTP（Streamable HTTP endpoint）
- 鉴权：`${GITHUB_TOKEN}` → `os.environ` → `.mcp.json` 注入

**内部数据流（MCP 增强后的循环）：**

```
CLI
 └─ async with MCPClientManager(mcp_config):        # 并发连接所有 server（stdio/http）
        ├─ tools/list 发现
        ├─ mapping: MCP tool → ToolSchema（namespaced）
        └─ registry.register(schema, mcp_handler)    # ToolRegistry 单例现含 内置 + MCP 工具
    loop = AgentLoop(provider)                       # registry 已含 MCP 工具，AgentLoop 无感
    await loop.run(prompt)
        ├─ _call_provider → enabled_schemas() 含 mcp__* → 发给 LLM
        ├─ LLM 调 mcp__github__list_issues
        ├─ _execute_one → registry.get_handler → mcp_handler(**kwargs)
        │     └─ session.call_tool → CallToolResult
        │           └─ mapping: → str ｜ isError → raise ToolError
        └─ ToolResult → Message(TOOL) → 下一轮 LLM
    __aexit__: unregister 全部 MCP 工具 + AsyncExitStack 关闭 session/子进程
```

### File Organization Patterns

- **配置**：`.mcp.json`（项目根，运行时读）+ `.mcp.json.example`（示例）；不进 `.heagent/`（那是运行时产物）。
- **源码**：`tools/mcp/` 平级 `tools/builtins/`；4 文件分层（config / mapping / manager / init）——单文件 <400 行既有约束。
- **测试**：平铺 `tests/test_mcp_*.py`，**不**镜像 `tools/mcp/`；Stub session 隔离网络；E2E 独立 mark。
- **文档**：`CLAUDE.md` 更新（安全声明 + 模块速查 + DAG）；`.mcp.json.example` 含 GitHub 配置示例 + README 接入说明（承载 review-rubric 的「开源可用」SM ↔ FR 文档 traceability）。

## Architecture Validation Results

### Coherence Validation ✅

**Decision Compatibility：** Python 3.11+ async / `mcp` SDK 1.28 async-native / Pydantic v2 / click 全兼容；`mcp>=1.28,<2` 与既有依赖无冲突。决策全部**基于真实代码核实**（`register()` 已支持动态注册、`_invoke` 契约契合 MCP handler、`enabled_schemas()` 时序锚点），架构与现实连贯。

**Pattern Consistency：** namespace `<server>__<tool>` / `ToolError` 复用 / Pydantic 模型 / 外部生命周期——与既有 codebase 模式及彼此一致。

**Structure Alignment：** `tools/mcp/` 平级 `builtins/`、平铺测试、DAG 受控；结构支撑全部决策。

### Requirements Coverage Validation ✅

**Functional Requirements：** FR-1~11 全部架构支撑。亮点：FR-5 并行执行复用既有 `_execute_tools`（`asyncio.gather`）零成本；SubAgent 经进程单例 `ToolRegistry` 自动继承 MCP 工具。

**Non-Functional Requirements：** NFR-1/2/3/5/6/7 全部架构支撑。NFR-2 零回归由「AgentLoop + registry API 零改动」保证；NFR-3 由「握手封在 MCPClientManager 内」保证。

### Implementation Readiness Validation ✅

**Decision Completeness：** 8 类决策（A-H）均带理由 + 受影响组件；mcp 版本 web 验证钉死。
**Structure Completeness：** 增量文件树到文件级 + FR→文件映射 11/11。
**Pattern Completeness：** 8 处 MCP 特有分歧点全约束 + 正反例。

### Gap Analysis Results

**Critical Gaps：无。**

**Important Gaps：**

1. **NFR-4 连接超时**（已在本步 apply 进决策 B）：eager 连接须加每 server 超时（`asyncio.wait_for`），防单 server 卡死阻塞启动。→ 已折进架构（见决策 B refinement）。
2. **FR-3 运行时断连陈旧工具**：断连 server 工具暂留注册表，调用降级为 `ToolError`。V1 可接受；「断连自动 unregister」列为 future enhancement，不阻塞。

**Minor Gaps：**

3. **FR-9 结果 schema**：issue/search 字段形态依赖官方 GitHub server 实际输出，由 E2E 故事接真实 server 时钉死。
4. **SubAgent + MCP 可见性**：进程单例 registry 使子 agent 自动见 MCP 工具（已验证为红利，非缺口，但建议在故事中显式断言）。

### Validation Issues Addressed

- **NFR-4 连接超时**（important）：apply 进决策 B —— eager + 并发 + 隔离 **+ 每服务器连接超时**。
- 其余 important/minor gap 为故事级 refinement 或后续增强，已记录供下游 epics 承接。

### Architecture Completeness Checklist

**Requirements Analysis**
- [x] Project context thoroughly analyzed
- [x] Scale and complexity assessed
- [x] Technical constraints identified
- [x] Cross-cutting concerns mapped

**Architectural Decisions**
- [x] Critical decisions documented with versions
- [x] Technology stack fully specified
- [x] Integration patterns defined
- [x] Performance considerations addressed（eager-concurrent + 连接超时）

**Implementation Patterns**
- [x] Naming conventions established
- [x] Structure patterns defined
- [x] Communication patterns specified
- [x] Process patterns documented

**Project Structure**
- [x] Complete directory structure defined
- [x] Component boundaries established
- [x] Integration points mapped
- [x] Requirements to structure mapping complete

### Architecture Readiness Assessment

**Overall Status:** READY FOR IMPLEMENTATION（16 项 checklist 全绿，无 Critical gap；2 项 important gap 已 apply 或定为故事级 refinement）

**Confidence Level:** High

**Key Strengths：**

- 架构基于**真实代码核实**，非臆断——`register()` / `_invoke` / `enabled_schemas()` 时序均实证。
- **零回归**：AgentLoop + ToolRegistry API 零改动；MCP 纯增量嵌入既有 DAG。
- **协议演进可迁移**：握手/transport 封在 MCPClientManager，2026-07-28 stateless 迁移改动局部化。
- SubAgent / 并行执行 / 错误层级 **自动复用**，无新增机制。

**Areas for Future Enhancement：**

- 运行时断连自动 unregister（FR-3 收紧）
- `SafetyGuard` 扩展到 MCP 工具（敏感工具确认 / 返回内容复核）
- Resources / Prompts 原语、写操作
- 正式 `Transport` Protocol 抽象（第 3 种 transport 出现时）

### Implementation Handoff

**AI Agent Guidelines：**

- 严格遵循决策 A-H，不引入替代方案（落点 `tools/mcp/`、复用 `register()`、namespace、`ToolError`、外部生命周期）。
- 一致使用实现模式；尊重 DAG 边界（无 `agent/` 反向导入）。
- 所有架构疑问以本文档为准。

**First Implementation Priority：**

1. `pyproject.toml` 增 `mcp>=1.28,<2`
2. `tools/mcp/` 骨架（`config.py` → `mapping.py` → `manager.py`）
3. Settings 门控 + cli.py 装配
4. GitHub 只读 E2E 验收
