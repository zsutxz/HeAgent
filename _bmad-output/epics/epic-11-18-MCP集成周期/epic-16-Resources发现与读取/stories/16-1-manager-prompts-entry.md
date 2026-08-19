---
baseline_commit: 4d4cd61f043fdb333f14e7b1e9e5e43d88dd21b0
---

# Story 16.1: manager prompts 读取入口（经 _sessions）

Status: ready-for-dev

## Story

As a HeAgent 开发者,
I want MCPClientManager 暴露 list_prompts/get_prompt 读取能力（非 LLM 工具）,
So that CLI slash 分发器能发现并渲染 server 提供的参数化模板。

> **本 story 是 Epic C（Prompts）的前置**——在 MCPClientManager 上添加 prompts 读取入口（经 15-1 引入的 `_sessions` 查找表），为 16-2 的 slash 分发器提供底层能力。Prompts 不注册为 LLM 工具（user-controlled，不该 LLM 自主调），仅经 CLI 表面暴露。

## Acceptance Criteria

**AC-1（FR-C1：list_prompts 返回模板清单）**
**Given** `MCPClientManager` 新增 `list_prompts(server: str)` 方法
**When** 调用 `manager.list_prompts("github")`
**Then** 经 `self._get_session(server)` 取 session 后调 `session.list_prompts()`
**And** 返回模板清单（每项含 name、description、参数 schema），server 无模板时返回空列表不抛错

**AC-2（FR-C1：list_prompts 所有 server 聚合）**
**Given** manager 已连多个 server
**When** 调用 `manager.list_prompts()`（无参，聚合所有 server）
**Then** 返回聚合列表，每项含 `{server, name, description, arguments}`，异常隔离

**AC-3（FR-C2/C3：get_prompt 渲染模板）**
**Given** `MCPClientManager` 新增 `get_prompt(server: str, name: str, arguments: dict | None = None)` 方法
**When** 调用 `manager.get_prompt("github", "code_review", {"file": "loop.py"})`
**Then** 经 `self._get_session(server)` 取 session 后调 `session.get_prompt(name, arguments)`
**And** 返回渲染文本（`str`）

**AC-4（FR-C2：模板不存在/参数缺失 → ToolError）**
**Given** 指定模板名不存在或参数缺失
**When** 调用 `get_prompt`
**Then** 抛 `ToolError`（显式失败，不静默空返 / 不裸 MCP SDK 异常）

**AC-5（FR-C1：list_prompts 无 server 连接时空列表）**
**Given** 无任何 server 连接
**When** 调用 `list_prompts()`
**Then** 返回空列表，不抛错

## Tasks / Subtasks

- [ ] **Task 1: MCPClientManager 新增 list_prompts 方法**
  - [ ] `list_prompts(server: str)` → 调 `session.list_prompts()` 返回模板清单
  - [ ] 单 server 异常隔离

- [ ] **Task 2: MCPClientManager 新增 get_prompt 方法**
  - [ ] `get_prompt(server: str, name: str, arguments: dict | None = None)` → 调 `session.get_prompt()`
  - [ ] 返回渲染文本
  - [ ] 模板不存在/参数缺失 → ToolError

- [ ] **Task 3: MCPClientManager 新增 list_prompts（无参，聚合所有 server）**
  - [ ] 遍历 `_sessions` 聚合所有 server 的 prompts
  - [ ] 异常隔离

- [ ] **Task 4: 测试**
  - [ ] `test_list_prompts_returns_prompts`
  - [ ] `test_list_prompts_empty_when_no_prompts`
  - [ ] `test_list_prompts_empty_when_no_sessions`
  - [ ] `test_list_prompts_partial_failure_isolated`
  - [ ] `test_get_prompt_returns_text`
  - [ ] `test_get_prompt_disconnected_server_raises_tool_error`
  - [ ] `test_get_prompt_missing_template_raises_tool_error`

## Dev Notes

- Prompts 入口**不注册为 LLM 工具**——仅经 CLI slash 分发器调用（user-controlled）。
- 本 story 仅添加底层读取能力，slash 表面在 16-2 实现。
- `list_prompts(server)` 调 MCP SDK 的 `session.list_prompts()`，返回 `ListPromptsResult`（含 `prompts` 列表）。
- `get_prompt(server, name, arguments)` 调 `session.get_prompt(name, arguments)`，返回 `GetPromptResult`（含 `messages` 列表）。

## File List

- `src/heagent/tools/mcp/manager.py` — 新增 `list_prompts` / `get_prompt` 方法
- `tests/test_mcp_manager.py` — 新增 prompts 测试用例

## Change Log

- 2026-07-23：Story 16-1 创建。
