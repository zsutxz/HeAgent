---
stepsCompleted: [1, 2, 3, 4]
epicStructureApproved: true
status: complete
completedAt: 2026-07-12
resumeState: "epics 工作流完成（Fast path，直接基于 prd FR-1~5 + architecture AD-1~6 产出）。Epic 14 = 3 stories（14-1 pin / 14-2 隔离层 / 14-3 测试基线）；FR-3/5 由 architecture.md 交付（切换路径 + open question），无独立 story。文档就绪，进入实现：14-1 pin → 14-2 session_api.py → 14-3 测试。"
inputDocuments:
  - _bmad-output/mcp-v2-upgrade/prd.md
  - _bmad-output/mcp-v2-upgrade/architecture.md
  - _bmad-output/mcp-v2-upgrade/brief.md
  - _bmad-output/mcp-v2-upgrade/addendum.md
---

# HeAgent MCP v1→v2 升级准备 - Epic Breakdown

## Overview

本文档提供 **HeAgent MCP v1→v2 升级准备** 的 epic 与 story 拆分，把 PRD（FR-1~5 / NFR-1~6）+ Architecture（AD-1~6 + 切换路径）的需求分解为可实现的 story。

> 输入：PRD `_bmad-output/mcp-v2-upgrade/prd.md`、Architecture `_bmad-output/mcp-v2-upgrade/architecture.md`。技术型 PRD，无 UX 设计。承接 mcp-client 周期（Epic 11-13），延续主线编号至 Epic 14。

## Requirements Inventory

### Functional Requirements

```
FR-1: 收紧 SDK pin 到 mcp>=1.27.2,<2（补当前 mcp>=1.27,<2 落后小档；1.27.2 为 v1 线最新 stable 2026-05-29）
FR-2: 在 MCPClientManager 内建隔离层（session_api.py），封装 5 个 v2-sensitive 调用点（handshake/ping/list_tools/call_tool/types 导入+字段访问），对外暴露稳定内部接口
FR-3: 文档化 mcp-client FR-3（运行时 ping-watch 断连 auto-unregister）在 v2 stateless 下的等价机制选型（C 过渡 + v2 切 A 被动）——由 architecture 交付，不含实现
FR-4: 迁移测试基线——Epic 11-13 的 MCP 测试（tests/test_mcp_*.py）在本周期所有改动后全绿 + session_api 新增单测
FR-5: 文档化 v2 stable 落地时的切换路径——由 architecture 交付，不含实际切换执行
```

### NonFunctional Requirements

```
NFR-1: 零回归（tests/test_mcp_*.py 全绿，含 mcp-client DP-4 用例；以 FR-4 基线为零回归上限）
NFR-2: 封装局部化（隔离层对外接口签名 v1→v2 切换前后 diff 为空；改动限于 MCPClientManager 内部，不波及 AgentLoop）
NFR-3: DP-4 立场延续（mcp-client DP-4 两半不因升级退化）
NFR-4: 纯 v1 准备（不引入 v2 alpha 依赖；隔离层在 v1 上做抽象）
NFR-5: 继承约束（异步 + DAG：tool 层禁从 agent 导入）
NFR-6: 可观测（隔离层调用、握手、健康探测有日志）
```

### Additional Requirements

```
- 承接 mcp-client NFR-3（握手封装局部化，为 stateless 迁移留接口）——本周期兑现：扩展隔离到全部 5 调用点
- 隔离层形态=Adapter 函数式收敛模块（session_api.py），非 Protocol（v1→v2 替换非并存，多态无价值）
- FR-3 等价机制=C 过渡占位（v1 保留 send_ping）+ v2 切 A 被动（call_tool 失败即注销）；本周期只文档化选型+路径，不含实现
- 切换路径：v2 stable（目标 2026-07-27）落地时改 session_api.py 内部 + manager.py 局部（_make_handler A-path 回调），mapping.py 零改动，不波及 AgentLoop
- Open question：ClientSession vs Client(mode='auto') 迁移留 v2 切换任务定（SDK v2 保留 legacy initialize，协议删握手）
- 安全立场不可退化：v2 形态下断连工具必须注销（AD-3）
- story 无独立 N-M 文件，直接基于本文档 AC 实现（同 mcp-client 周期惯例）
```

### UX Design Requirements

无（技术型 PRD，无 UI）。

### FR Coverage Map

```
FR-1:  Story 14-1 — pin 收紧 mcp>=1.27.2,<2
FR-2:  Story 14-2 — 隔离层 session_api.py（5 调用点收敛）
FR-3:  由 architecture.md 交付（AD-3 + 切换路径 open question）——无独立 story
FR-4:  Story 14-3 — 测试基线（session_api 单测 + 零回归）
FR-5:  由 architecture.md 交付（§v2 切换路径）——无独立 story
```

**NFR 横切**（织入全部 story）：NFR-1/5 全程；NFR-2 承重于 14-2；NFR-3 由 14-3 零回归验证（DP-4 用例在 tests/test_mcp_*.py）；NFR-4 14-2（纯 v1）；NFR-6 14-2 日志。

## Epic List

> ✅ **状态：APPROVED（Fast path，tan 推进）**。规模小（实际实现仅 FR-1 pin + FR-2 隔离层 + FR-4 测试；FR-3/5 文档已由 architecture 交付）→ 单 epic。合计 **3 stories**。

| Epic | 标题 | FRs | Stories |
|------|------|-----|---------|
| Epic 14 | MCP v1→v2 升级准备（隔离层先行） | FR-1, FR-2, FR-4（FR-3/5 由 arch 交付） | 14.1~14.3 |

**依赖：** 14-1 → 14-2 → 14-3 线性（pin 先定 SDK 版本 → 隔离层基于该版本 → 测试验证隔离层）。无前向依赖、无并行。

---

## Epic 14: MCP v1→v2 升级准备（隔离层先行）

**用户成果：** tan 在 v2 stable（2026-07-27）落地前，把 MCPClientManager 的 5 个 v2-sensitive 调用点收敛进 session_api.py 隔离层；v2 落地时切换限于 MCPClientManager 内部，Epic 11-13 零回归。
**FRs covered:** FR-1, FR-2, FR-4（FR-3/5 由 architecture 交付）
**为何单 epic：** 本周期是「准备」非「切换」——实际实现工作集中在 pin + 隔离层 + 测试三件，架构已完整预设计（AD-1~6），无子件反馈环，按 file-churn 规则合并为单 epic 有序 story。
**实现序列锚点（architecture §v2 切换路径 + AD-1~6）：** pin → session_api.py 骨架 → manager/mapping 改引用 → 测试。

### Story 14.1: 收紧 MCP SDK pin 到 mcp>=1.27.2,<2

As a framework author,
I want 把 `mcp` SDK pin 从 `mcp>=1.27,<2` 收紧到 `mcp>=1.27.2,<2`,
So that 补当前落后小档、锁定 v1 线最新 stable（2026-05-29）、`<2` 排除 v2 alpha（NFR-4 纯 v1）。

**Acceptance Criteria:**

**Given** `pyproject.toml`
**When** 把 `mcp>=1.27,<2` 改为 `mcp>=1.27.2,<2` 并执行 `pip install -e ".[dev]"`
**Then** 安装成功、`mcp` 1.27.2 可导入
**And** `<2` 约束排除 v2 alpha（2.0.0a1），与既有依赖无版本冲突。

**Given** 既有 `tests/test_mcp_*.py`
**When** 运行 `pytest tests/test_mcp_*.py`
**Then** 全绿（pin 收紧不破坏既有 MCP 集成，NFR-1 零回归）。

### Story 14.2: 建 session_api.py 隔离层收敛 5 个 v2-sensitive 调用点

As a framework author,
I want 新建 `tools/mcp/session_api.py` 隔离层（Adapter 函数式收敛模块），导出 handshake/ping/list_tools/call_tool 稳定函数 + 类型别名 + 字段访问兼容，`manager.py`/`mapping.py` 改从此取,
So that 5 个 v2-sensitive 调用点被收敛（initialize/send_ping/list_tools/call_tool/types 导入+inputSchema 字段），v2 stable 落地时切换限于 MCPClientManager 内部、不波及 AgentLoop（兑现 mcp-client NFR-3）。

**Acceptance Criteria:**

**Given** 新建 `src/heagent/tools/mcp/session_api.py`
**When** 实现
**Then** 导出：`async handshake(session) -> None`、`async ping(session, timeout) -> None`（失败 raise）、`async list_tools(session) -> list[Tool]`、`async call_tool(session, name, args) -> CallToolResult`、类型别名 `Tool`/`CallToolResult`/`TextContent`/`ImageContent`/`EmbeddedResource`、`input_schema_of(tool) -> dict`、`result_is_error(result) -> bool`（AD-1 表）
**And** v1 实现：handshake=`session.initialize()`、ping=`session.send_ping()`、list_tools=`session.list_tools()`、call_tool=`session.call_tool()`、类型 `from mcp.types import`、`input_schema_of`=`tool.inputSchema`、`result_is_error`=`result.isError`。

**Given** `manager.py` 的 `_transport_and_session`/`_watch`/`_discover_and_register`/`_make_handler`
**When** 改引用
**Then** 全部经 `session_api`：`session.initialize()`→`session_api.handshake(session)`、`session.send_ping()`→`session_api.ping(session, timeout)`、`session.list_tools()`→`session_api.list_tools(session)`、`session.call_tool(...)`→`session_api.call_tool(session, name, args)`
**And** `manager.py` 不再直接调 `session.initialize/send_ping/list_tools/call_tool`（AD-1 Rule）。

**Given** `mapping.py` 的 `mcp_tool_to_schema`/`call_result_to_text`/`bridge_result`
**When** 改引用
**Then** 类型从 `session_api` 取（`from .session_api import Tool, CallToolResult, ...`）、`tool.inputSchema`→`input_schema_of(tool)`、`result.isError`→`result_is_error(result)`
**And** `mapping.py` 不再 `from mcp.types import ...`（AD-1 Rule）；`bridge_result` 的 DP-4 注入启发式围栏逻辑不动（NFR-3 立场延续）。

**Given** DAG 约束（AD-6）
**When** 检查 `session_api.py` 全部导入
**Then** 仅依赖 mcp SDK + 按需 `heagent.types`/`exceptions`；无 `heagent.agent.*`、**无 `from .mapping import`**（mapping→session_api 单向，防循环导入）。

**Given** 异步约束（NFR-5）
**When** 静态检查
**Then** `session_api.py` 全 async（handshake/ping/list_tools/call_tool），无同步 I/O。

**Given** `_watch` 周期探测（AD-3 v1）
**When** 改引用
**Then** `_watch` 逻辑不动，仅 `send_ping` 调用点改经 `session_api.ping(session, timeout)`；ping 失败仍由 `_watch` 既有 `except Exception` 兜底→`_unregister_server`（FR-3 v1 行为不变）。

**Given** 可观测（NFR-6）
**When** 实现
**Then** `session_api.py` 有 `logging.getLogger(__name__)`，handshake/健康探测有 INFO/WARNING。

**Given** 既有 `tests/test_mcp_*.py`
**When** 运行
**Then** 全绿（隔离层重构零回归，NFR-1；含 mcp-client DP-4 用例，NFR-3）。

### Story 14.3: 迁移测试基线——session_api 单测 + 零回归验证

As a framework author,
I want 新增 `tests/test_mcp_session_api.py` 覆盖隔离层各 v1 实现 + 字段兼容，并与既有 `tests/test_mcp_*.py` 共同构成切换前后零回归基线,
So that 隔离层自身有测试保护、v2 切换时有基线比对（AD-5）、story 间对测试范围无分歧。

**Acceptance Criteria:**

**Given** 新建 `tests/test_mcp_session_api.py`（平铺，Stub session 无网络）
**When** 运行
**Then** 覆盖：`handshake`（调 session.initialize）、`ping`（调 session.send_ping + 失败 raise）、`list_tools`（返 list[Tool]）、`call_tool`（返 CallToolResult）、`input_schema_of`（tool.inputSchema passthrough + 非 dict 兜底）、`result_is_error`（result.isError）
**And** 全程无网络调用（Stub session）。

**Given** 既有 `tests/test_mcp_*.py`（含 mcp-client DP-4 用例）
**When** 运行 `pytest tests/test_mcp_*.py`
**Then** 全绿（NFR-1 零回归基线；DP-4 用例绿=NFR-3 立场不退化）。

**Given** 全量 `pytest`
**When** 运行
**Then** 零回归（隔离层重构不破坏 Epic 11-13 MCP 集成四链：连接/发现/调用/断连探测）。

**Given** `ruff check src tests` / `mypy src`
**When** 运行
**Then** 全绿（NFR-5 代码规范）。

---

## FR Coverage Verification

| FR | Story | 覆盖 |
|----|-------|------|
| FR-1 | 14.1（pin 收紧） | ✅ |
| FR-2 | 14.2（隔离层 5 调用点收敛） | ✅ |
| FR-3 | architecture.md AD-3 + 切换路径 open question（文档交付，不含实现） | ✅ |
| FR-4 | 14.3（session_api 单测 + 零回归基线） | ✅ |
| FR-5 | architecture.md §v2 切换路径（文档交付，不含执行） | ✅ |

**NFR 横切覆盖：** NFR-1（零回归）14.1/14.2/14.3 均验证；NFR-2（封装局部化）承重于 14.2（session_api 对外签名稳定）；NFR-3（DP-4 不退化）由 14.2/14.3 零回归验证（DP-4 用例在 tests/test_mcp_*.py）；NFR-4（纯 v1）14.2（无 v2 import）；NFR-5（DAG/异步）14.2；NFR-6（可观测）14.2 日志。无 UX Design Requirement（技术型 PRD）。
