---
baseline_commit: 4d4cd61f043fdb333f14e7b1e9e5e43d88dd21b0
---

# Story 15.1: MCPClientManager._sessions 映射（B/C 前置 + flag-before-pop 断连语义）

Status: done

## Story

As a HeAgent 开发者,
I want MCPClientManager 持有 server→session 的只读查找表,
So that Resources/Prompts 桥接代码能经统一映射取 session，且断连有规范化错误语义。

> **本 story 是 Epic B（Resources on-demand）的起点**——也是 Epic C（Prompts）的前置。引入 `self._sessions` 后，后续桥接工具（list_resources/read_resource）和 slash 分发器可经统一映射取 session（AR-4, AD-4）。本 story 独立可交付，B/C 共享。

## Acceptance Criteria

**AC-1（AD-4：_sessions 查找表）**
**Given** `MCPClientManager` 新增 `self._sessions: dict[str, ClientSession]`
**When** `_server_loop` 中 `session.initialize()` 成功
**Then** 把 session 登记进 `_sessions[name]`（name 即 server 配置名，与 `_registered` 键一致）

**AC-2（AD-4：flag-before-pop 断连语义）**
**Given** server 断连或 `__aexit__` 关停
**When** `_unregister_server` / `_unregister_all` 执行
**Then** 按 flag-before-pop 顺序：先从 `_sessions` 移除该键，再让 transport context 退出
**And** session 的唯一属主始终是其 `_server_loop` task（负责 enter/exit transport），`_sessions` 是只读查找表非第二属主

**AC-3（AD-4：规范断连错误）**
**Given** 一个 in-flight 桥接调用观察其 server 键已被移除（断连竞态）
**When** 桥接代码取 session
**Then** 抛规范化 `ToolError("MCP server '%s' disconnected")`，由 `_execute_one` 转 `is_error=True` 进 LLM 上下文（与既有 MCP 工具断连语义一致）
**And** 不得裸抛 `KeyError`/`AttributeError`/None 访问（AD-4）

## Tasks / Subtasks

- [x] **Task 1: MCPClientManager.__init__ 增 _sessions** (AC: #1)
  - [x] 新增 `self._sessions: dict[str, ClientSession] = {}`

- [x] **Task 2: _server_loop 初始化成功时登记 session** (AC: #1)
  - [x] `await session.initialize()` 成功后 `self._sessions[name] = session`

- [x] **Task 3: _unregister_server flag-before-pop** (AC: #2)
  - [x] 先 `self._sessions.pop(name, None)` 再切 `_registered` 内工具名列表（transport 退出在 finally）

- [x] **Task 4: _unregister_all 遍历清 _sessions** (AC: #2)
  - [x] 保留既有 `list(self._registered)` 遍历 —— `_unregister_server` 已含 `_sessions.pop`，`_sessions` 自然清空

- [x] **Task 5: _get_session 辅助方法** (AC: #3)
  - [x] 新增 `_get_session(name) -> ClientSession`：缺键时抛 `ToolError`，不裸 KeyError/None
  - [x] 导入 `ToolError`（已有，上层 exceptions 模块）

- [x] **Task 6: 测试** (AC: #1, #2, #3)
  - [x] 测试 `_sessions` 在连接成功后填充（透传既有的 test_connect_discovers_and_registers 路径）
  - [x] 测试 `_get_session` 返回 session（已连 server）
  - [x] 测试 `_get_session` 缺键抛 ToolError
  - [x] 测试 unregister 后 `_sessions` 键已移除（flag-before-pop）

## Dev Notes

- `_sessions` 的键与 `_registered` 一致（server 配置名，无 normalized 逻辑）。
- `_get_session` 是 Resources/Prompts 桥接工具的首选入口——后续桥接代码应经此取 session，不直接触 `_sessions`。
- 本 story 不涉及 Resources/Prompts 桥接工具的注册——仅引入查找表基础设施。

## File List

- `src/heagent/tools/mcp/manager.py` — 增 `_sessions` 字段 + 登记/清除逻辑 + `_get_session` 辅助方法
- `tests/test_mcp_manager.py` — 新增 `_sessions`/`_get_session` 测试用例

## Change Log

- 2026-07-17：Story 15-1 实现完成——`_sessions` 登记/清除 + `_get_session` 辅助方法 + 测试用例。Status → done。
