# MCP v1→v2 升级 Alpha POC — 切换就绪度报告

> **状态：POC 完成（feat/mcp-v2-poc 分支，不合并主线）。** 核心目标——验证 `architecture.md §v2 切换路径` 在真实 v2 上的可执行性 + 回答 open question——达成。本报告为 stable 落地（目标 2026-07-27）的执行依据。

## 元信息

| 项 | 值 |
|---|---|
| 日期 | 2026-07-12 |
| POC 分支 | `feat/mcp-v2-poc`（从 master，不合并） |
| v2 实装版本 | **mcp 2.0.0b1** + mcp-types 2.0.0b1 + opentelemetry-api 1.43.0 |
| 依赖 floor | anyio 4.14.1 / pydantic 2.13.4 / typing-extensions 4.16.0 / sse-starlette 3.4.5 / pywin32 312（**均已在 POC 前满足 v2 floor**，pip 无需 bump，仅新增 opentelemetry-api） |

## 版本线更新（research 后）

addendum（2026-07-12 一手 research）记"v2 仅 alpha 2.0.0a1"。**PyPI 实测（POC 日）**：已推进到 2.0.0a1 / a2 / a3 / **b1（beta，最新）**。POC 选 **b1**——beta 比 alpha 更接近 stable 目标态，delta 风险更小。

## 逐条预测 vs 实测表

| 切换路径项 | architecture 预测 | 官方指南（Agent A） | **2.0.0b1 实测** | 一致？ |
|---|---|---|---|---|
| 类型 import | `from mcp.types`→拆包 | 拆 mcp-types；**顶层 re-export 保持**（`from mcp import Tool`） | `mcp.types` **移除**；`from mcp import CallToolResult` **FAIL**（顶层不 re-export CallToolResult）；`from mcp_types import` **OK** | ⚠️ **delta**（A 的"顶层 re-export"预测在 b1 不成立） |
| Tool/CallToolResult 字段 | camelCase→snake_case | snake_case 属性；构造兼容双拼写 | `input_schema` / `is_error` ✓；构造 `inputSchema=` / `isError=` 仍接受 ✓ | ✓ |
| handshake `initialize` | 删除→no-op？ | **SDK 保留 legacy initialize** | `ClientSession.initialize()` **保留**（无参签名不变） | ✓（A 修正 architecture"删除"预测） |
| `list_tools` 签名 | `params=PaginatedRequestParams` | `*, params: PaginatedRequestParams \| None = None` | 无参调用仍可行，返回 `.tools` 不变 ✓ | ✓ |
| `call_tool` | 返回 snake_case | — | `(name, arguments)` 前两参兼容；返回 **`CallToolResult \| InputRequiredResult \| Result` union**（新形态） | ⚠️ union 新增（A 未列） |
| `send_ping` | deprecated | ping 2026-07-28 spec 移除 | `send_ping` **仍在**，**无 deprecation 标记** | ⚠️ b1 未删未标 |
| FR-3 A 语义 | call_tool 失败被动注销 | — | **实现 + 测试通过**（manager 15 测试全绿，含 2 A 语义断连用例） | ✓ |
| `mapping.py` 零改动（AD-2） | diff 为空 | — | **git diff 确认 mapping.py 零改动** ✓ | ✓ **兑现** |
| `session_api` 对外签名 diff 空（AD-2） | 为空 | — | **签名不变，只改内部**（import + 2 字段） ✓ | ✓ **兑现** |
| transport 层 | streamable_http v2 形态 | 2-tuple + http_client 注入 | HeAgent 现代码已 v2 形态（manager.py:223-225），改动接近零 | ✓ **正向发现** |

## Open Question 实测答案

**保持 `ClientSession`，不迁 `Client(mode='auto')`。** 依据：
- `ClientSession.initialize()` v2 **保留**，对 ≤2025-11-25 server 继续有效（最小改动路径）
- `mode` 是 `Client` 参数，HeAgent 用 `ClientSession`（manager.py:215,225）不命中
- `Client` 收益在 2026-07-28-only servers 普及后显现；留 stable 后续 epic

## architecture.md 修正建议

1. **§v2 切换路径步骤 1（handshake）**：改"initialize 删除→no-op"为"**initialize 保留**（SDK v2 保留 legacy；2026-07-28 server 用 `server/discover` 替代，HeAgent 连现有 server initialize 继续）"
2. **类型 import**：改"顶层 re-export"为"**必须 `from mcp_types import`**"（b1 实测顶层不导出 `CallToolResult`）
3. **addendum L13 资源码**：v1 起点 `-32002` 订正为 `0`（v2 终态 `-32602` 一致）
4. **正向发现补录**：transport 层（manager.py:223-225）已是 v2 形态，切换改动接近零
5. **`call_tool` 返回 union**：补录 `CallToolResult | InputRequiredResult | Result`，`bridge_result` duck-type 读 `.content`/`.is_error` 已兼容

## alpha→stable delta（b1 实测偏离，stable 落地必复核）

1. **顶层 re-export 缺失**：b1 `from mcp import CallToolResult` 失败（指南称保持）→ stable 复核是否恢复
2. **send_ping 未删未标**：b1 保留且无 deprecation 标记（指南称 deprecated）→ stable 可能真删，A 语义已就位（不依赖 ping）
3. **FastMCP 移除**：v2 `mcp.server.fastmcp` 消失（server 侧重组为 `MCPServer`/`lowlevel`/`mcpserver`）→ 影响 `test_mcp_manager_http.py` 测试基建（起 in-process server），**非 HeAgent client 问题**
4. **`call_tool` 返回 union**：`InputRequiredResult`（elicitation 相关）新增，HeAgent 透传不窄化

## 切换工作量实测估计（vs 文档预测）

- **session_api.py**：对外签名 diff **真为空**（AD-2 兑现）；内部仅改 3 处（import + `input_schema` + `is_error`），<10 行——**比预测更小**（handshake/list_tools/call_tool 实现已兼容 v2）
- **manager.py**：A 语义 `_make_handler` try/except + `_watch` 退化为 `await stop.wait()`，~20 行
- **mapping.py**：**零改动**（AD-2 兑现，超出预期——session_api 类型别名隔离生效）
- **不波及 AgentLoop**：✓（AD-2 兑现）
- **总计**：client 切换约 **1 story（<1 人日）**，比 architecture 预估更轻

## 未覆盖风险（stable 落地需补）

1. **http 真实路径（cancel-scope 跨 task 回归）**：`test_mcp_manager_http.py` 因 FastMCP v2 移除无法 collect → **client 真实 transport 路径在 v2 下未验证**。stable 适配 FastMCP 新路径（`MCPServer` 或独立 `fastmcp` 包）后必跑
2. **stdio 真实路径**：本 POC 未新增 stdio 真实测试（Agent A 警告 POSIX shutdown 子进程保留）→ Windows Job Object 行为待 stable 验证
3. **`_meta` envelope wire 变化**：v2 每请求带 OTel envelope（无配置恢复 v1 wire）；HeAgent 无 wire bytes 断言，未命中
4. **ClientSession 入站校验**：v2 校验 server 输出，off-schema 响应可能抛 `pydantic.ValidationError`（HeAgent 宽 `except Exception` 兜底）
5. **opentelemetry-api 副作用**：新增硬依赖，默认开 OTel——可观测但需确认无性能/日志噪声

## 结论

**v2 client 切换路径在 2.0.0b1 上验证通过**：session_api 对外签名 diff 为空 + mapping.py 零改动 + A 语义（call_tool 失败被动注销）实现 + 不波及 AgentLoop。architecture 核心承诺（AD-1/AD-2/AD-3）**兑现**。

修正 5 处预测（initialize 保留 / `mcp_types` import / 资源码 `0→-32602` / transport 正向发现 / call_tool union）。

**stable 落地（目标 2026-07-27）后**，按修正版切换路径执行 client 切换约 **1 story 工作量**；http 真实路径需补 FastMCP 适配后验证。本 POC 分支保留供 stable 切换参考。
