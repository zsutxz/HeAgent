# Architecture — HeAgent MCP Client 集成（三阶段整合）

> **2026-08-18 整合**：本文整合原 `mcp-client/architecture.md`（阶段一 V1，决策 A-H）、`mcp-v2-upgrade/architecture.md`（阶段二 升级准备，AD-1~6）、`mcp-client-v2/ARCHITECTURE-SPINE.md`（阶段三 V2，AD-1~8）。三阶段决策编号独立，**跨阶段引用须写全限定**（如「V1 决策 B」「升级 AD-1」「V2 AD-1」）。
> **作用域**：三阶段均为 MCP Client 集成的架构决策，不是 HeAgent 整体架构重写。既有架构基线见 `../baseline/architecture.md` 与 `docs/frame.md`。

---

# 阶段一 · MCP V1 集成（决策 A-H）— 2026-06-20

> 基于**真实代码核实**（`registry.py` / `decorator.py` / `types.py` / `loop.py` / `cli.py` / `exceptions.py`），非臆断。关键发现：`ToolRegistry.register(schema, handler)` 已原生支持动态注册 → **registry API 零扩展**；`_invoke()` 做 `handler(**call.arguments)` + async 自检 → MCP 闭包 handler 天然契合 → **AgentLoop 执行路径零改动**。

## Requirements Overview

**FR（11 / 5 组）**：连接与生命周期（FR-1,2,3）→ `MCPClientManager` 管理 stdio + HTTP 双 transport、生命周期绑 `AgentLoop`、区分连接失败 vs 运行时断连；发现与桥接（FR-4,5,6）→ `tools/list` 动态发现 → `ToolSchema` → `ToolRegistry`、结果桥接 `ToolResult`、namespace 前缀；声明式配置（FR-7,8）→ 项目根 `.mcp.json` + `${ENV}` 插值 + PAT 走环境变量；GitHub 只读验收（FR-9）→ 官方远程 server 两类 E2E；安全（FR-10,11）→ 不可信边界声明。

**NFR（7）**：NFR-1 全异步 / NFR-2 零回归 / NFR-3 版本可控（握手封装内部）/ NFR-4 启动性能 / NFR-5 可观测 / NFR-6 错误隔离 / NFR-7 代码规范。

**Scale**：中等复杂度；~4-5 个新增模块。**新增依赖**：官方 `mcp` SDK，pin `mcp>=1.27,<2`（后统一 `>=1.28,<2`）。**协议窗口**：stable `2025-11-25`；`2026-07-28` RC breaking。

## Core Architectural Decisions

**Critical（阻塞实现）**：A 模块落点 / B 工具发现注册路径 / C 生命周期绑定 / D 协议封装边界。**Important（塑形）**：E Transport 分派 / F Namespace / G 结果错误映射 / H 配置加载。**Deferred**：SafetyGuard 扩展（DP-4）、Resources/Prompts、写操作、正式 Transport Protocol（YAGNI）。

### A. 模块落点 — `tools/mcp/` 层

MCP 暴露的是**工具**（model-controlled，进 `ToolRegistry`），不实现 `BaseProvider.send()`，不是模型 provider。`providers/` 层语义 = 「与模型通信」。老 `providers/mcp.py` 是 2026-05 投机性占位（FR-18「MVP 后」），现正式纠正。**DAG 合规**：`tools/mcp/` 仅从 `tools.registry` / `types` / `exceptions` 导入，**禁止从 `agent/` 导入**；`cli.py` 负责装配。

### B. 工具发现与注册路径 — 复用 `register()`，eager + 并发 + 隔离

MCP 调既有 `registry.register(ToolSchema(...), mcp_handler)`，registry API 零扩展；`inputSchema` 直接填 `ToolSchema.parameters`。

**发现时序：eager + 并发 + 隔离 + 每服务器连接超时**（否决 lazy）：
- `MCPClientManager.__aenter__` 用 `asyncio.gather(*connect_tasks, return_exceptions=True)` **并发**连接所有 server + `tools/list` 发现 + 映射 + 注册；**在 `loop.run()` 之前完成**（FR-2 时序锚点：`enabled_schemas()` 首次 `_call_provider` 调用，LLM 首轮即见全部 MCP 工具）。
- **否决 lazy**：LLM 只能从发给它的 schema 列表选工具；lazy 是鸡生蛋。
- 并发 + 单 server 失败隔离（NFR-6）：失败 server 工具不注入 + 记日志（NFR-5）。
- **每服务器连接超时**（NFR-4）：`asyncio.wait_for(_connect(entry), timeout=...)`，超时即隔离，防单 server 卡死阻塞启动。

### C. 生命周期绑定 — 外部 `async with` ctx mgr，AgentLoop 零改动

```python
async with MCPClientManager(mcp_config) as mcp:   # 并发连接 + 发现 + 注册
    loop = AgentLoop(provider, ...)
    result = await loop.run(prompt)
# __aexit__：unregister 全部 MCP 工具 + AsyncExitStack 关闭 session/子进程
```

理由：① NFR-2 零回归（AgentLoop 无异步生命周期钩子，改它动核心契约）；② NFR-3 封装；③ 沿用 `CronScheduler` start/stop 先例；④ `ToolRegistry` 进程单例，MCP 进出 register/unregister 干净（退出还原纯内置状态，利于测试隔离）。**否决**：AgentLoop 变 async ctx mgr（违反零回归）。

### D. 协议封装边界 — `MCPClientManager` 吃掉握手 + transport（NFR-3 承重）

`initialize` 握手 / `protocolVersion` 协商 / transport 细节全封在 manager 内；**AgentLoop 只见 `ToolSchema`/`ToolResult`**。为 2026-07-28 stateless 迁移留接口（迁移改动限于 manager 内部）。MCP 错误映射 `ToolError`（既有层级），不引入新异常。

### E. Transport 分派 — 内部 dispatch，不抽 Transport Protocol（YAGNI）

stdio（`stdio_client`）与 Streamable HTTP（`streamable_http_client`）是 SDK 两个 async ctx mgr；`_connect(entry)` 内部按配置类型分派。**否决正式 Transport Protocol 抽象**：仅 2 种 transport，YAGNI；第 3 种出现再重构。

### F. Namespace 命名 — `<server>__<tool>`

工具名 = **`<server>__<tool>`**（双下划线，LangChain 风格）。server 名规整化（小写、非字母数字 → `_`，如 `GitHub-MCP` → `github_mcp`）。冲突处理：两 server 规整后撞前缀 → 注册时检测并告警/去重。

### G. 结果与错误映射 — CallToolResult → ToolResult（V1 text-only）

- `CallToolResult.content`（TextContent / ImageContent / EmbeddedResource 块）→ **V1 仅取 TextContent 拼接**为 `ToolResult.content`（str，多块 `\n` 连接）；非文本块 → `[image]` / `[resource: uri]` 占位。
- `CallToolResult.isError=True` → **MCP handler 抛 `ToolError`**，走 `_execute_one` except 路径 → `ToolResult(is_error=True)`；**AgentLoop 零改动**保留错误语义。
- FR-9 schema：GitHub issue 列表项（`number/title/state/url`）/ 搜索命中（`path/snippet`）经 TextContent 到达即可断言。

### H. 配置加载 — 独立 `.mcp.json` loader + Settings 门控

`.mcp.json` = 独立结构化多 server JSON，**独立 `MCPConfig` Pydantic 模型 + `load_mcp_config(path)` loader**，不进 `Settings`（Settings 是 `.env`/env 单值驱动）。`${ENV}` 插值加载时展开；**未设变量 → fail-fast 抛错**（PAT 绝不落明文，DP-2）。Settings 门控：`mcp_enabled: bool = True`、`mcp_config_path: str = ".mcp.json"`。无文件/空 → 纯内置模式不报错（FR-7）。

## Implementation Patterns（MCP 特有规则）

- **命名**：`tools/mcp/`（与 `tools/builtins/` 平级）；`manager.py` / `config.py` / `mapping.py` / `__init__.py`；类 `MCPClientManager`/`MCPConfig`/`StdioServerConfig`/`HttpServerConfig`；async 方法无 `_async` 后缀。
- **工具名**：内置工具裸名（`shell`）；**MCP 工具必须 namespace** `<server>__<tool>`。
- **测试**：平铺 `tests/test_mcp_config.py` / `test_mcp_mapping.py` / `test_mcp_manager.py`（**不**镜像 `tools/mcp/` 子目录）；manager 测试用 **Stub session** 不打真实网络；GitHub E2E 独立 `@pytest.mark.integration`（需 `GITHUB_TOKEN`，不进默认全绿基线）。
- **配置**：项目根 `.mcp.json` + `.mcp.json.example`（对齐 `.env.example` 惯例）。
- **数据模型**：`MCPConfig` 等用 Pydantic BaseModel；`inputSchema` → 直接填入 `ToolSchema.parameters`（passthrough）。
- **错误处理**：MCP 连接失败/断连 → `ToolError`；`${VAR}` 未设 → 加载 fail-fast；单 server 失败隔离。`CallToolResult.isError=True` → handler 抛 `ToolError`。
- **重试**：**不为 MCP 新建重试**——MCP 工具调用走 `_execute_one`（异常→is_error），瞬态失败由 LLM 收到 is_error 后自行重试（与内置工具一致）。
- **生命周期**：`MCPClientManager` 实现 `__aenter__`/`__aexit__`；内部 `AsyncExitStack` 托管所有 server transport ctx + `ClientSession` ctx。

**Anti-Patterns**：❌ `providers/mcp.py`（落点错）；❌ `registry.register_mcp(...)`（应复用 register）；❌ 缺 `<server>__` 前缀；❌ `class MCPException`（应用 ToolError）；❌ `connect_async`（不加 _async 后缀）；❌ `await loop.__aenter__()`（不改 AgentLoop）。

## Project Structure（新增/改动）

```
src/heagent/
├── tools/mcp/                     # 【新增】MCP client 适配层
│   ├── __init__.py                # 导出 MCPClientManager, MCPConfig, load_mcp_config
│   ├── manager.py                 # MCPClientManager（async ctx mgr）：连接/发现/注册/关闭
│   ├── config.py                  # MCPConfig + StdioServerConfig/HttpServerConfig + load_mcp_config() + ${ENV} 插值
│   └── mapping.py                 # MCP tool → ToolSchema；CallToolResult → str + is_error 映射
├── config.py                      # 【改动】Settings 增 mcp_enabled / mcp_config_path
└── cli.py                         # 【改动】_run_single / _run_chat 内 async with MCPClientManager
tests/                             # 平铺
├── test_mcp_config.py / test_mcp_mapping.py / test_mcp_manager.py
# 可选 tests/test_mcp_github_e2e.py（@pytest.mark.integration）
pyproject.toml                     # 【改动】dependencies 增 "mcp>=1.28,<2"
.mcp.json.example                  # 【新增】配置示例
CLAUDE.md                          # 【改动】安全声明 + 模块速查 + DAG
```

**DAG 边界**：`tools/mcp/ → types → exceptions → tools.registry`（仅此三方向，无 `agent/` 反向依赖）；`cli.py` 是唯一装配点。**ToolRegistry 边界**：复用既有 `register`/`unregister`/`enabled_schemas`，不扩 API。**AgentLoop 边界**：**零改动**。

## Validation Results

- 16 项 checklist 全绿；无 Critical gap；2 项 important gap 已 apply 或定为故事级 refinement（NFR-4 连接超时 → apply 进决策 B；FR-3 运行时断连陈旧工具 → future enhancement）。
- **Overall: READY FOR IMPLEMENTATION（Confidence: High）**。
- Areas for future：运行时断连 auto-unregister、SafetyGuard 扩展、Resources/Prompts/写操作、Transport Protocol 抽象。

---

# 阶段二 · MCP v1→v2 升级准备（AD-1~6）— 2026-07-12

> Feature-altitude spine。不重述既有架构；只固定本周期（Epic 14）引入的隔离层不变量。技术事实源 = `brief.md` 技术速览（一手 research 2026-07-12）。

## Design Paradigm

**Anti-corruption layer（Adapter，函数式收敛模块）。** 在 `tools/mcp/` 与官方 `mcp` SDK 之间插一层 `session_api.py`，收敛全部 v2-sensitive 调用点；`manager.py` / `mapping.py` 不再直接触碰 SDK session 方法或 `mcp.types`。**函数式而非 Protocol 类**——v1→v2 是**替换**不是并存，多态无价值。

## Inherited Invariants

| Inherited | From | Binds here |
| --- | --- | --- |
| V1 NFR-3（握手封装在 MCPClientManager 内） | V1 prd | 隔离层把已封装握手扩展到全部 5 点——兑现而非重设 |
| V1 FR-3（ping-watch 断连 auto-unregister，2026-07-01 落地） | V1 prd | v2 等价机制不可退化断连注销立场（AD-3） |
| V1 DP-4（执行前拦截 + 返回内容围栏） | V1 prd / CLAUDE.md | 隔离层不削弱 `mapping.bridge_result` 围栏 |
| DAG：`tools/mcp/` 禁从 `agent/` 导入 | frame.md / CLAUDE.md | 隔离层只依赖 types/exceptions/registry/config |
| 异步：库代码无同步 I/O | CLAUDE.md | 隔离层全 async |
| Pydantic 跨模块，禁 raw dict | CLAUDE.md | 隔离层 passthrough SDK 原生类型，不新造模型 |

## Invariants & Rules

### AD-1 — 隔离层收敛全部 v2-sensitive 调用点

新建 `tools/mcp/session_api.py`，导出稳定函数 + 类型别名。`manager.py` / `mapping.py` **禁止**直接 `session.initialize()` / `send_ping()` / `list_tools()` / `call_tool()` 或 `from mcp.types import ...`。5 点精确映射：

| 隔离层导出 | v1 实现 | v2 切换时改 |
| --- | --- | --- |
| `async handshake(session) -> None` | `await session.initialize()` | v2 见切换路径 open question |
| `async ping(session, timeout) -> None` | `await session.send_ping()`（失败 raise） | 占位 C → 切 A（AD-3） |
| `async list_tools(session) -> list[Tool]` | `await session.list_tools()` | `params=PaginatedRequestParams(cursor=)` + snake_case |
| `async call_tool(session, name, args) -> CallToolResult` | `await session.call_tool(name, args)` | 返回字段全 snake_case |
| 类型别名 `Tool`/`CallToolResult`/`TextContent`/`ImageContent`/`EmbeddedResource` | `from mcp.types import ...` | `from mcp_types import ...` |
| `input_schema_of(tool) -> dict` | `tool.inputSchema` | `tool.input_schema` |
| `result_is_error(result) -> bool` | `result.isError` | `result.is_error` |

### AD-2 — 隔离层对外接口 v1→v2 切换 diff 为空

`session_api.py` 导出函数签名 v1→v2 切换前后保持不变（NFR-2 字面）。v2 切换改动**限于 `MCPClientManager` 内部**——`session_api.py` 内部实现 + `manager.py` 的 `_make_handler`/`_watch` 局部（A-path 失败回调）；`mapping.py` 零改动；**不波及 `AgentLoop`**。

### AD-3 — FR-3 v2 等价机制 = C 过渡占位 + v2 切 A 被动

- **本周期（v1）**：`session_api.ping()` 保留 `send_ping` 占位（候选 C，纯 v1，NFR-4）；`_watch` 周期探测**逻辑不动**，仅调用点改经 `session_api.ping()`。
- **v2 切换时**：`ping()` 语义改为**候选 A**——`_make_handler` 的 handler 闭包加 `try/except session_api.call_tool`，失败调 `_unregister_server(name)`（被动注销）。A 与 stateless 哲学一致、零额外开销。
- **异常范围**：`try/except` **只包 `session_api.call_tool`**，永不包 `bridge_result`——`isError`→`ToolError` 是正常工具错误语义，不触发注销。
- **安全立场不可退化**：v2 形态下断连工具必须主动或被动注销，不得滞留。`_unregister_server` 复用且幂等（`pop(name, ())`）。

### AD-4 — 纯 v1 准备边界

`session_api.py` 在 v1 SDK（`mcp>=1.28.1,<2`）上实现，不 import v2-only API（`server/discover`、`mcp_types` 等）；v2 stable 落地前不执行切换。本周期交付不依赖 v2 时点。

### AD-5 — [ADOPTED] 零回归基线

`tests/test_mcp_*.py`（含 V1 DP-4 用例）全绿为本周期所有改动的零回归上限。须为 `session_api.py` 新增单测（handshake/ping/list_tools/call_tool v1 实现 + 字段兼容）。

### AD-6 — [ADOPTED] DAG + 异步 + 类型

隔离层依赖 mcp SDK + 按需 `heagent.types`/`exceptions`；禁从 `agent` 导入，**禁从 `mapping` 导入**（mapping→session_api 单向，防循环）；全 async；passthrough SDK 原生类型，不新造 Pydantic 模型。

## Consistency Conventions

命名 `session_api.py`（snake_case）、函数动词短语、类型别名沿用 SDK 原名不加后缀；数据 passthrough SDK 原生类型、字段访问经兼容函数；隔离层无状态（纯函数 + 传入 session），session 生命周期由 `MCPClientManager` 持有（per-server task，同 task enter/exit，避免 anyio cancel scope 跨 task）；日志 stdlib；错误沿用 `ToolError`。

## Stack

Python 3.11+；mcp >=1.28.1,<2（FR-1，bump 自 >=1.28）；pytest + pytest-asyncio auto；asyncio stdlib。

## Structural Seed（DAG）

```
agent/ → tools/mcp/ → mcp SDK（正向）
tools/mcp/config.py        # 无 v2-sensitive，不动
tools/mcp/session_api.py   # 【新增】隔离层：5 调用点收敛 + 类型别名 + 字段兼容
tools/mcp/manager.py       # 改从 session_api 取（_transport_and_session/_watch/_discover_and_register/_make_handler）
tools/mcp/mapping.py       # 改从 session_api 取类型 + 字段兼容
```

## v2 切换路径（FR-5 文档化，不含执行）

触发条件：v2 stable（目标 2026-07-27）落地。切换另开独立任务。

1. **`session_api.py` 内部改实现 + `manager.py` 局部**（限于 MCPClientManager 内部；`session_api` 对外签名 diff 为空）：handshake → 见 open question；ping → 候选 A 语义；list_tools → `PaginatedRequestParams` + snake_case；call_tool → snake_case；类型别名 → `from mcp_types import`；字段兼容 → snake_case。
2. **`manager.py` 局部改 + `mapping.py` 零改动**（AD-2：`_make_handler` 加 A-path 失败回调 + `_watch` 经 `session_api.ping`）。
3. **FR-3 等价机制实现（A）**：`_watch` 从周期 ping 改 `call_tool` 失败回调注销；注销路径复用 `_unregister_server`。
4. **测试**：`tests/test_mcp_*.py` 全绿 + 新增 v2 断连探测用例。
5. **备选 B（重评条件）**：若 A 的延迟发现窗口不可接受且 `server/discover` 稳定，重评切 B。

**Open question（留 v2 切换任务定）**：是否迁移 `ClientSession`→`Client(mode='auto')`？POC 实测答案：**保持 `ClientSession`，不迁**（v2 SDK 保留 legacy `initialize`，对 ≤2025-11-25 server 继续有效；`mode` 是 `Client` 参数，HeAgent 用 `ClientSession` 不命中）。

## Deferred

> **2026-09-15 标注｜本节是阶段二当时的 Deferred 记录，不是当前待办账本。** `Resources/Prompts/写操作` 已随阶段三交付（Epic 14-16）；`FR-3 A`（运行时断连主动注销）亦已交付（`tools/mcp/manager.py` 的 `_watch` 健康探测，见 `deferred-work.md` E11-D1）；其余 MCP 域未开发项——`v2` 实际切换、`server/discover` 主动探测（B）、隔离层升级 Protocol、全局（home）级注入签名入口——已随「MCP 不再作为 HeAgent 必要开发方向」的决策**冻结**（`CLAUDE.md` 文首 MCP 立场；签名入口一项见 E11-D3「决策关闭（won't do）」）。当前 MCP 域唯一活动项是「stdio server 子进程未接入沙箱后端」，见 `implementation-artifacts/deferred-work.md`。

v2 实际切换执行；FR-3 A 实现；Resources/Prompts/写操作（v2 stable 后重评——后由阶段三落地）；`server/discover` 主动探测（B）；隔离层升级 Protocol（若需 v1/v2 并存）；用户可配置注入签名入口（DP-4 deferred 项，正交）。

---

# 阶段三 · MCP Client V2（AD-1~8）— 2026-07-17

> 本 spine 只承重「V2 引入的、未来 builder 无法从合规代码读出的不变量」。既有架构权威见 `docs/frame.md`；V1 决策见本文件阶段一——本 spine **继承而非重述**两者。

## Design Paradigm

**brownfield 扩展（在既有扩展点上加固 + 接入，非新机制）**。落点：
1. **给 V1 既有 `call_tool` 路径加确定性治理闸门**——`Tool.annotations` 透传进 `ToolSchema`，由既有 `PolicyEngine` 消费（destructive 审批 / readOnly 放行 / 缺省 fail-safe）。判定在代码层、不在 LLM 层。
2. **把 Resources/Prompts 两原语以最小侵入接入既有循环**——Resources 走「manager 注册桥接工具」路径；Prompts 走 CLI 新 slash 分发器。两者返回内容复用 V1 注入启发式围栏。

承重约束：**确定性逻辑交给代码、不交给概率模型**。

## Inherited Invariants

| Inherited | From | Binds here |
| --- | --- | --- |
| 工具执行链 `PolicyEngine.evaluate() → ToolExecutor → SafetyGuard.check() → handler` | frame.md + CLAUDE.md | V2 治理闸门加在 evaluate 内部，**不改链路顺序** |
| `tools/mcp/` 禁从 `agent/` 导入（DAG） | baseline + V1 | 桥接代码只向 types/exceptions/registry/mapping 依赖 |
| 跨模块数据用 Pydantic BaseModel | baseline | `ToolSchema.annotations` 为自有模型，不上浮 mcp 依赖 |
| DP-4 围栏非真正安全边界 | V1 DP-4 + CLAUDE.md | Resources/Prompts 返回同等不可信，须 OS 沙箱兜底 |
| V1 MCP 工具经 `mcp_tool_to_schema` + `bridge_result` + `_make_handler` 注册 | V1 architecture FR-4/5/6 | V2 annotations 透传落在 `mcp_tool_to_schema` |

## Invariants & Rules

### AD-1 — annotations 经 ToolSchema 显式 kwarg 注入 PolicyEngine（OQ-2 定稿）

`PolicyEngine.evaluate_tool_call(call, *, context=None, schema=None)` 增可选 kwarg `schema: ToolSchema | None = None`，读 `schema.annotations` 裁决。调用方（`tool_execution.execute_tool_call`）在裁决前 `schema = loop.registry.get_schema(call.name)` 并传入——该处已用同一 registry 取 handler。**两个 evaluate 调用点（正常路径 + ledger 缓存命中复核）都传 schema**。`ToolCall`/`RunContext` 结构不变。否决三种备选：污染 ToolCall / 注入 registry / 塞 RunContext.metadata。

### AD-2 — 注解驱动的 fail-safe 审批裁决（策略优先级固定，fail-safe 仅 MCP）

`PolicyEngine` 在既有裁决审批步内，按固定优先级（前者短路）：

0. **前置闸门**：`schema=None`（V1 内置/未知工具，无 annotations）→ **跳过注解裁决**回既有路径。**fail-safe 仅作用于 MCP 工具**——内置工具零回归（SM-4 生命线）。
1. 显式策略命中即 `APPROVAL_REQUIRED`（`approval_tools` 含名 / `approval_mcp_tools` 开关且为 MCP 工具）——**显式策略覆盖 annotation**。
2. 否则（MCP）`destructiveHint=true` → `APPROVAL_REQUIRED`；
3. 否则（MCP）`readOnlyHint=true` → 不审批（落 DIRECT / 既有沙箱裁决）；
4. 否则（**MCP 缺 annotations**）→ `APPROVAL_REQUIRED`（fail-safe）。

触发前提 = `_is_mcp_tool(call)` **且** `schema.annotations` 存在；任一不满足即走前置闸门。`idempotentHint`/`openWorldHint` 透传存储、**不进裁决**。授权语义沿用 `metadata.approved_tools`（含 `*` / MCP `__mcp__`）。

### AD-3 — 治理裁决确定性、纯函数化、可单测

annotations → `PolicyVerdict` 路径**不调用任何 LLM**：输入 `(ToolCall, annotations, context)` → 固定 `PolicyVerdict`。存在不触达 provider 的单元测试断言 destructive/readOnly/缺省三种 annotations 对应 verdict。

### AD-4 — MCPClientManager 持有 server→session 映射（B/C 前置）

`MCPClientManager` 增 `self._sessions: dict[str, ClientSession]`。`_server_loop` 在 `initialize()` 成功后登记 `_sessions[normalized_name]`；`_unregister_server`（断连）/`_unregister_all`（`__aexit__`）同步摘除。Resources/Prompts 桥接代码只经此映射取 session。

**所有权与断连语义**：session 唯一属主始终是其 `_server_loop` task（负责 enter/exit transport）；`_sessions` 是**只读查找表**非第二属主。断连按 **flag-before-pop**：先摘键再退 transport；桥接调用见键移除 → 规范化 `ToolError("MCP server '%s' disconnected")`（`_execute_one` 转 `is_error=True`），**禁裸 KeyError/AttributeError/None**。in-flight 跨 task await 期间断连由 SDK 抛错捕获转同一 ToolError。

### AD-5 — Resources 走「manager 注册的聚合桥接工具」路径（mcp__ 命名空间 + readOnly 自声明）

`MCPClientManager` 在 **MCP 活跃时**注册两个聚合桥接工具（与 V1 MCP 工具同 `registry.register` 路径），闭包捕获 `self._sessions`：
- **命名 = `mcp__` 聚合命名空间**：`mcp__list_resources` / `mcp__read_resource`（双下划线 → `_is_mcp_tool` 识别为 MCP 工具，**全量继承 V1 MCP 门控**：`block_mcp_tools` 拉闸即连 Resources 一起阻断、`approval_mcp_tools`/`sandbox_mcp_tools`/`__mcp__` 授权生效）。`mcp` 作聚合 server token。
- **自声明 `readOnlyHint=True`** → 默认不审批（AD-2 步 3 放行）；用户可 `approval_mcp_tools=True` 强制确认覆盖。
- **LLM 可见签名钉死**：`list_resources()` → server-tagged 列表（`{server, uri, name, description}`）；`read_resource(server: str, uri: str)` → `server` 必填（消解跨 server 同 URI 歧义）。**收紧 PRD FR-B2**（原 `read_resource(uri=...)` 跨 server 歧义）。
- 无 MCP 配置时不注册（纯内置模式）。`read_resource` 返回文本经公共注入启发式围栏（AD-6）标记透传。server 不在 `_sessions` / URI 不存在 → `ToolError`。[ASSUMPTION: server 不暴露资源 → `list_resources` 空列表不抛错。]

### AD-6 — 三原语统一 on-demand + 同等不可信围栏（fence 提升为公共函数）

(a) Resources **不**在会话启动自动注入——仅 `read_resource` 显式请求的 URI 进上下文；(b) Prompts 渲染文本作 user message 经既有 `run_stream` 进循环，**不**绕过消息管道；(c) **注入围栏提升为 `mapping.py` 公共函数**（如 `guard_content(text) -> str`，复用既有 `_scan_injection`/`_INJECTION_PATTERNS` 单一实现），`bridge_result` 改为对其文本结果调用同一函数；Tools（`bridge_result`）/ Resources（`mcp__read_resource`）/ Prompts（slash 分发器，AD-7）**三者一律调用同一公共围栏**，标记透传、不阻断、同等不可信。

### AD-7 — Prompts 经最小 CLI slash 分发器（OQ-4 定稿）

`_run_chat` REPL 在 `input()` 与 `loop.run_stream()` 之间加最小 slash 分发器：`user_input.startswith("/")` → 查命令表分发；`/mcp-prompt <server> <name> [key=value ...]` 为首条命令，持 manager 引用调 `list_prompts`/`get_prompt`，渲染文本**先经公共围栏 `guard_content` 标记**（AD-6），再**作为 user message** 走 `run_stream`。无既有 slash 机制可复用——新增薄表面。缺必填参数/模板不存在 → 显式错误。

**结构变更（核实纠正）**：REPL 当前**并不持有 manager 引用**——`_mcp_lifecycle(settings)` 返回 ctx mgr，manager 实例被包进 `async with` 不可达（原假设的 `_build_mcp` 函数不存在，实为 `_mcp_lifecycle`）。两条可选接入：(i) `_mcp_lifecycle` 返回 manager，`_run_chat` 绑定变量经 `as` 取实例进 REPL 作用域；(ii) manager 把 prompts 读取注册成 `mcp__` 桥接工具。**推荐 (i)**：与 V1「外部 async with ctx mgr」架构一致，改动最小、不把 prompts 塞进 LLM 工具列表（Prompts 是 user-controlled，不该 LLM 自主调）。

### AD-8 — 治理闸门 + 围栏均非真正安全边界（诚实立场）

`Tool.annotations` 是 server 自声明、不可信（恶意 server 可谎报 `readOnlyHint=true`）；治理闸门与 DP-4 围栏同构，仅 defense-in-depth 标记。**须 OS 级沙箱兜底**。`CLAUDE.md` / `docs/frame.md` 安全声明须更新覆盖：写操作治理（annotation 不可信）+ Resources/Prompts 返回同等不可信。

## Consistency Conventions

- **命名**：MCP 工具 `<server>__<tool>`；Resources 聚合桥接 `mcp__list_resources` / `mcp__read_resource`（`mcp` 聚合 token，确保 `_is_mcp_tool` 识别继承全量 V1 门控）。
- **数据模型**：`ToolSchema.annotations` 自有 Pydantic 模型，四 hint；`mcp.types.ToolAnnotations` 第 5 字段 `title` **不透传**（非裁决信号）。`annotations` 缺省本身不触发 fail-safe；仅「MCP 工具 + 缺 annotations」触发（AD-2 步 0/4）。
- **错误语义**：Resources/Prompts 沿用 `ToolError`（read_resource URI 不存在 / 缺必填参数 → 显式失败）；slash 命令错误回显 REPL 不中断循环。
- **围栏复用**：三原语返回统一经 `guard_content`（单一实现，不复制）。
- **测试**：annotations→verdict 纯函数单测不触 provider；MCP 桥接 stub session；`reset_settings()`；零回归护栏覆盖既有 V1 MCP + 19 内置工具测试。

## Stack

Python 3.11+；mcp >=1.28,<2（installed 1.28.0；`ClientSession` 已暴露 list_resources/read_resource/list_prompts/get_prompt/list_resource_templates/subscribe_resource——本周期仅消费前四个）；Pydantic v2；click（CLI REPL + slash）。**V2 不新增运行时依赖**。

## Structural Seed

```
src/heagent/
  types.py                       # +ToolSchema.annotations（自有 Pydantic 模型，四 hint）
  engine/policy.py               # evaluate_tool_call +schema kwarg；annotations 裁决步（AD-1/2/3）
  tools/mcp/
    mapping.py                   # mcp_tool_to_schema 透传 annotations；注入围栏提升为公共 guard_content（AD-6）
    manager.py                   # +_sessions 映射（flag-before-pop）；+注册 mcp__list_resources/mcp__read_resource；+prompts 读取入口（AD-4/5/7）
  agent/tool_execution.py        # evaluate 调用点传 schema kwarg（AD-1）——两处
  cli.py                         # +_run_chat slash 分发器 + /mcp-prompt（AD-7）
```

## Capability → Architecture Map（节选）

| Capability / FR | Lives in | Governed by |
| --- | --- | --- |
| FR-A1/A2 | `types.py` ToolSchema + `mapping.mcp_tool_to_schema` | AD-1 |
| FR-A3/A4/A5 | `engine/policy.py` evaluate_tool_call | AD-1 + AD-2 + AD-3 |
| FR-A6 | 无 provider 单测 | AD-3 |
| FR-A7 | types 存储 + policy 不消费 | AD-2 末 |
| FR-B1/B2 | manager 聚合桥接工具 | AD-4 + AD-5 + AD-6 |
| FR-B3 | manager（不注入 system prompt） | AD-6(a) |
| FR-B4 | mapping.bridge_result | AD-6(c) |
| FR-C1 | manager（经 _sessions） | AD-4 + AD-7 |
| FR-C2/C3 | cli.py slash 分发器 | AD-7 |
| FR-C4 | mapping 注入围栏 | AD-6(c) |
| SM-6 / AR-8 | CLAUDE.md / frame.md | AD-8 |

## Deferred

> **2026-09-15 标注｜阶段三当时的 Deferred 记录，不是当前待办账本。** 本次核实：`subscribe_resource` 与 `resource templates` 未见实现（`src/heagent/tools/mcp/` 无相关符号）；`idempotentHint` / `openWorldHint` 已由 `tools/mcp/mapping.py:64,65` 映射，但 `PolicyEngine` 未据此裁决（写操作闸门只看 `destructiveHint` / `readOnlyHint`）；其余各项（fail-safe 保守度增强 → V3、全局级注入签名入口、内置工具 annotation 驱动治理、完整操作/环境维度）同属 MCP 域，随上述「MCP 非必要方向」决策冻结。未闭合项统一以 `implementation-artifacts/deferred-work.md` 为准。

subscribe_resource（OQ-5，与 on-demand 及 stateless 双冲突）；resource templates（OQ-6，边际价值低）；idempotent/openWorld 裁决消费（FR-A7）；fail-safe 保守度增强（PRD OQ-1 → V3）；用户可配置注入签名入口（DP-4 硬化，独立 spec）；内置工具 annotation 驱动治理；完整操作/环境维度。

---

# 阶段间架构演进速览

| 维度 | V1 | 升级 | V2 |
|------|----|------|----|
| 设计范式 | brownfield 增量 | Anti-corruption layer（Adapter 函数式） | brownfield 扩展（既有扩展点加固） |
| 新增模块 | `tools/mcp/`（manager/config/mapping） | `tools/mcp/session_api.py` 隔离层 | `types.py` annotations + engine/policy 裁决步 |
| 核心不变量 | AgentLoop + registry API 零改动 | 隔离层对外签名 diff 为空 | 执行链顺序不变 + fail-safe 仅 MCP |
| 决策编号 | 决策 A-H | AD-1~6 | AD-1~8（+ AR-1~10 in epics） |
| 安全立场 | 不可信边界声明 | DP-4 不退化 | annotations 不可信，闸门 defense-in-depth |
