# Addendum — MCP v1→v2 升级准备：技术速览与生态快照

> Brief 容纳不下的技术深度，供下游 PRD / architecture 直接取用。事实源：2026-07-12 一手 research（modelcontextprotocol.io 博文与 spec、PyPI release history、官方 v2 迁移指南全文、modelcontextprotocol/servers 仓库），非凭记忆；MCP 规范 / SDK 在 2025-2026 变动剧烈，下游引用前建议复核最新版。

## 1. 协议版本线（日期戳即版本号）

| 版本 | 要点 |
|---|---|
| 2024-11-05 | 初版（HTTP+SSE + stdio）|
| 2025-03-26 | 引入 Streamable HTTP |
| 2025-06-18 | 定稿 Streamable HTTP + OAuth 2.1 + structured output + elicitation；废弃 HTTP+SSE |
| **2025-11-25** | **当前 stable**（HeAgent 落点）|
| **2026-07-28（RC→final）** | **breaking**：转 stateless、删 `initialize` 握手与 `Mcp-Session-Id`（SEP-2575/2567，2026-05-21 locked）；Roots/Sampling/Logging 标注式 deprecated（SEP-2577，宽限 ≥12 个月）；资源未找到码 `-32002`→`-32602`（SEP-2164）|

## 2. 官方 Python SDK `mcp` 版本

- **v1 线最新 stable：1.27.2（2026-05-29）**；下一档 1.27.1（2026-05-08）、1.27.0（2026-04-02）。HeAgent 现 pin `mcp>=1.27,<2`，本周期收紧到 `mcp>=1.27.2,<2`。
- **v2 仅 alpha：2.0.0a1（2026-06-11）**；stable v2.0.0 目标 **2026-07-27**，与 spec 同步。
- 原生 asyncio，全异步。

## 3. v1→v2 breaking 全清单（官方迁移指南）× HeAgent 命中核查

| breaking 项 | HeAgent 命中？ | 位置 / 说明 |
|---|---|---|
| `read_resource/subscribe_resource` uri `AnyUrl→str` | ✗ 未用 | 未接 Resources |
| `subscribe_resource` deprecated → `client.listen(...)` | ✗ 未用 | 未接 Resources |
| `list_*(cursor=)` → `params=PaginatedRequestParams(cursor=)` | ✓ `list_tools`（无 cursor，但签名变） | manager.py:234 |
| `mcp_types` camelCase→snake_case（`inputSchema`→`input_schema` 等） | ✓ `Tool`/`CallToolResult` 消费 | mapping.py:18, manager.py:237, bridge_result |
| `get_server_capabilities()` 删 → 属性 | ✗ 未用 | — |
| `McpError→MCPError`（构造签名变） | ✗ 未捕获（用宽 `except Exception`） | — |
| timeout `timedelta→float`、请求超时码 `408→-32001` | ✗ 未显式传 timeout | — |
| `mcp.types` 拆独立 `mcp-types` 包 | ✓ 导入 | mapping.py:18 |
| `Client` 默认 `mode='auto'`（探 `server/discover`，回退 `initialize`） | ✗ 未用 | HeAgent 直接构造 `ClientSession`，非 `Client` 类（`mode='auto'` 是 `Client` 参数）；v2 切换若迁 `Client` 才命中，见 architecture open question |
| `send_ping()` deprecated | ✓ 健康探测 | manager.py:290（**FR-3 设计级冲击**）|
| `initialize`/`initialized` 握手删除 | ✓ 显式调用 | manager.py:215,226（**握手重构，设计级**）|
| 实验性 Tasks 模块全删 | ✗ 未用 | — |

**命中 5 项**（manager.py 4 + mapping.py 1），其中 `initialize` 与 `send_ping` 为设计级，余 3 项机械级。

## 4. 为何 Resources/Prompts 暂挂：生态依据（历史，非本周期消费）

> 原方向（Resources/Prompts 原语扩展）暂挂的依据。本周期不反向取用，留作未来重评的存量证据。

**框架侧（client 消费支持）**——Tools 原语这些框架都支持，下表只列 Resources/Prompts：

| 框架 | Resources | Prompts |
|---|---|---|
| Pydantic AI（与 HeAgent 同代异步栈） | ✗ | ✗ |
| CrewAI（同代异步栈） | ✗ | ✗ |
| OpenAI Agents SDK | 进行中（PR） | ✓ |
| LangChain（langchain-mcp-adapters） | ✓ | ✓ |
| FastMCP Client | ✓ | ✓ |

**server 生态（真实采用）**：

| Server | Tools | Resources | Prompts |
|---|---|---|---|
| filesystem | ✓ | ✓（文件内容 URI）| ✗ |
| git | ✓（主）| 稀少 | ✗ |
| postgres | ✓ | ✓（schema/数据）| 官方版罕见 |
| memory（知识图） | ✓ | ✓ | ✗ |
| Everything（演示） | ✓ | ✓ | ✓（刻意全开）|

两极分化且同向：与 HeAgent 架构最相近的 Pydantic AI / CrewAI 均 tools-only；Resources 仅在数据源类 server 有立足点，Prompts 几无真实消费方（基本只出现在 demo server）。生态整体仍 tools 压倒性主导。

## 5. FR-3 断连探测 v2 等价机制候选（供 architecture 选型）

**现状（v1）**：`_watch`（manager.py:272）每 `_health_check_interval` 秒 race `stop.wait()` vs `session.send_ping()`；ping 失败/超时 → 注销该 server 全部工具（FR-3 收紧，2026-07-01 落地）。

**v2 冲击**：`send_ping()` deprecated；stateless 下无持久 session，ping 语义消失。FR-3 的主动健康探测机制整个失效。

**候选：**
- **A. call_tool 失败即注销（被动）** —— 下次该 server 工具被调用时 `call_tool` 抛错 → 注销。延迟发现（断连到下次调用之间工具仍滞留 LLM 列表），但零额外开销、与 stateless 契合。
- **B. `server/discover` 周期探测（主动）** —— v2 新方法，周期调用探活。保持 FR-3 主动语义，但依赖 v2 API（v1 上无法实现，只能「设计」）。
- **C. 过渡占位** —— v1 隔离层保留 ping 调用，v2 切换时改实现。保持本周期「纯 v1 准备」边界。

`[ASSUMPTION: 选型留 architecture。本周期 Scope 含「设计」不含「实现」（C 过渡占位即可）。]`

## 6. 关键来源

- 协议 RC 博文：https://blog.modelcontextprotocol.io/posts/2026-07-28-release-candidate/
- 协议规范（lifecycle）：https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle
- PyPI `mcp` history：https://pypi.org/project/mcp/#history
- SDK 仓库：https://github.com/modelcontextprotocol/python-sdk
- v2 迁移指南（权威 breaking 清单）：https://py.sdk.modelcontextprotocol.io/v2/migration/
- servers 仓库：https://github.com/modelcontextprotocol/servers
- Pydantic AI gap：https://github.com/pydantic/pydantic-ai/issues/1783
- LangChain 适配器：https://reference.langchain.com/python/langchain-mcp-adapters
- OpenAI Agents SDK：https://github.com/openai/openai-agents-python/issues/396
- CrewAI：https://docs.crewai.com/v1.15.1/en/mcp/overview
- FastMCP client：https://gofastmcp.com/clients/client
- 安全最佳实践：https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices
