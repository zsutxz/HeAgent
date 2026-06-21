# Addendum — MCP 技术约束与生态速览

> Brief 容纳不下的技术深度，供下游 PRD / architecture 直接取用。信息源：2026-06 web research（见底部链接），非凭记忆；MCP 规范 / SDK 在 2025-2026 变动剧烈，下游引用前建议复核最新版。

## 1. 协议版本线（日期戳即版本号）

| 版本 | 要点 |
|---|---|
| 2024-11-05 | 初版（HTTP+SSE + stdio）|
| 2025-03-26 | 引入 Streamable HTTP |
| 2025-06-18 | 定稿 Streamable HTTP + OAuth 2.1 + structured output + elicitation；**废弃 HTTP+SSE** |
| **2025-11-25** | **当前 stable** |
| 2026-07-28 (RC) | **breaking**：转 stateless、删 `initialize` 握手与 `Mcp-Session-Id`（2026-05-21 locked，~10 周 SDK 验证，正式版 ~2026-07 底）|

client 在 `initialize` 时协商 protocolVersion。

## 2. Transport

- **stdio**：本地子进程，client 管理生命周期，无 HTTP。
- **Streamable HTTP**：单端点 POST/GET，可选 SSE 流式响应，支持 stateful/stateless、resumability。
- 旧 HTTP+SSE：**已废弃**（2025-06-18）。

## 3. 三原语语义边界

- **Tools**（model-controlled）：LLM 自主调用，有副作用（≈ POST）。`tools/list` 发现、`tools/call` 执行。 ← **V1 只接这个**
- **Resources**（application-controlled）：宿主决定注入上下文，幂等无副作用（≈ GET），URI 寻址，可订阅。
- **Prompts**（user-controlled）：用户触发的可复用模板。
- 可选 capability：`sampling`（server 反向请求 client LLM）、`logging`、`roots`、`elicitation`。

## 4. 官方 Python SDK（`mcp` 包）

- 仓库：modelcontextprotocol/python-sdk（23.4k★）；PyPI `mcp`，**stable v1.28.0（2026-06-16）**；v2 alpha 已发，stable v2 目标 2026-07-27。
- **依赖建议**：`mcp>=1.27,<2`（v2 + 协议 2026-07-28 双 breaking）。
- 原生 asyncio，全异步。
- Client 核心 API：`mcp.ClientSession`、`StdioServerParameters`、`mcp.client.stdio.stdio_client`（async ctx mgr → read/write stream）、`mcp.client.streamable_http.streamable_http_client`。
- 典型用法：
  ```python
  async with stdio_client(params) as (read, write):
      async with ClientSession(read, write) as session:
          await session.initialize()
          tools = await session.list_tools()
          res = await session.call_tool("name", {"arg": ...})
  ```
- Server 侧 FastMCP（`@mcp.tool()`）—— HeAgent **不消费 server 侧**。

## 5. 各框架适配模式（可借鉴）

- **LangChain**：`langchain-mcp-adapters`，`MultiServerMCPClient`（默认 stateless）+ `load_mcp_tools()`（MCP tool → BaseTool）。配置支持代码或 `mcpServers` dict。
- **Pydantic AI**：`MCPServerStdio` / `MCPServerStreamableHTTP` 挂 `Agent(mcp_servers=[...])`，与 agent run 绑定。**只支持 Tools，不支持 Resources/Prompts**。
- **OpenAI Agents SDK**：`MCPServerStdio/StreamableHTTP/Sse`，agent 自动消费 tools。
- **CrewAI**：`crewai-tools` 暴露 MCP server 为 tool。
- **Claude Code / Desktop**：`.mcp.json` / `claude mcp add` 声明 `mcpServers`（command + args + env，stdio 首选）。 ← **配置形态标杆**
- **通用可借鉴模式**：① ClientSession → 框架 ToolSchema 适配层；② 多 server namespacing；③ 生命周期与 agent run 绑定；④ 声明式 JSON 配置。

## 6. GitHub MCP server（首个验收）

- 官方：github.com/github/github-mcp-server（Go），提供 remote（Streamable HTTP 托管）+ 本地 Docker 两种形态。
- 工具集：repos / issues / pull_requests / code_search / users 等（几十个）。
- 鉴权：GitHub Personal Access Token。
- 社区另有 TS 版本（stdio）。

## 7. 已知坑（须在 architecture 应对）

- **安全/信任**：MCP server = 不可信代码 + 不可信输出进 LLM 上下文，无隔离。 → 归入 HeAgent 既有安全声明。
- **stdio 子进程生命周期**：spawn / 监控 / 优雅关闭、崩溃恢复、僵尸进程、env 泄漏。 → `AsyncExitStack` 托管。
- **工具数量爆炸**：每 server 10-50+ tools，多 server 叠加侵蚀上下文、降低工具选择准确率。 → 复用 HeAgent `ContextCompressor` + lazy `list_tools` + 可选 namespacing。
- **Resources vs Tools**：边界模糊，V1 只接 Tools。
- **SDK breaking 风险**：握手 / 协议封装在 `MCPClientManager` 内部，迁移时改动局部化。

## 关键链接

- 协议规范：https://modelcontextprotocol.io/specification/2025-11-25/basic/lifecycle
- Python SDK：https://github.com/modelcontextprotocol/python-sdk · https://pypi.org/project/mcp/
- Servers（已归档）：https://github.com/modelcontextprotocol/servers-archived
- Registry：https://modelcontextprotocol.io/registry/about
- LangChain 适配器：https://github.com/langchain-ai/langchain-mcp-adapters
- Pydantic AI：https://pydantic.dev/docs/ai/mcp/client/
- 安全最佳实践：https://modelcontextprotocol.io/docs/tutorials/security/security_best_practices
