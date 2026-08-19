---
baseline_commit: 4d4cd61f043fdb333f14e7b1e9e5e43d88dd21b0
---

# Story 16.2: slash 分发器 + /mcp-prompt 渲染注入（含参数化）

Status: ready-for-dev

## Story

As a HeAgent 操作者,
I want 在 CLI 敲 /mcp-prompt 渲染 server 模板并注入会话,
So that 一键复用参数化模板（如代码审查），缺参数或模板不存在时显式报错。

> **本 story 是 Epic C 的核心交付**——在 `_run_chat` REPL 中加最小 slash 分发器（`input()` 与 `run_stream()` 间），支持 `/mcp-prompt <server> <name> [key=value ...]` 格式，经 16-1 的 manager prompts 入口渲染后作为 user message 注入会话。

## Acceptance Criteria

**AC-1（FR-C2：slash 分发器）**
**Given** `_run_chat` REPL 当前以 `input()` 直送 `run_stream()`
**When** 在 `input()` 与 `run_stream()` 间加最小 slash 分发器
**Then** `user_input.startswith("/")` → 查命令表分发，否则原样送 `run_stream`

**AC-2（FR-C2：/mcp-prompt 语法）**
**Given** `_mcp_lifecycle` 返回 manager，`_run_chat` 以 `async with mcp_ctx ... as mgr` 捕获实例
**When** 用户敲 `/mcp-prompt github code_review file=loop.py`
**Then** 解析 server=`github`, name=`code_review`, arguments=`{"file": "loop.py"}`
**And** 调 `mgr.get_prompt("github", "code_review", {"file": "loop.py"})` 渲染
**And** 渲染文本作为 user message 走 `run_stream`（复用既有循环）

**AC-3（FR-C2：模板不存在 → 显式错误）**
**Given** 指定模板名不存在
**When** 调用 `/mcp-prompt`
**Then** 错误回显到 REPL（不静默注入空内容，不中断循环）

**AC-4（FR-C3：缺必填参数 → 显式错误）**
**Given** 模板声明必填参数 `file`
**When** `/mcp-prompt` 未提供该参数
**Then** 报错列出缺失参数，不注入空内容

**AC-5（FR-C3：完整参数正常渲染）**
**Given** `/mcp-prompt` 带完整参数
**When** 调用
**Then** 模板正常渲染注入

## Tasks / Subtasks

- [ ] **Task 1: _run_chat 捕获 MCP manager 实例**
  - [ ] `async with mcp_ctx ... as mgr` 捕获上下文管理器返回值
  - [ ] `isinstance(mgr, MCPClientManager)` 判断是否 MCP 活跃
  - [ ] 适配 `nullcontext()` 返回 None 的场景

- [ ] **Task 2: slash 分发器逻辑**
  - [ ] `_run_chat` 中 `input()` 后检查 `user_input.startswith("/")`
  - [ ] 分发器命令表（当前仅 `/mcp-prompt`）
  - [ ] 非 slash 命令原样送 `run_stream`

- [ ] **Task 3: /mcp-prompt 解析器**
  - [ ] 解析 `server name [key=value ...]` 格式
  - [ ] `str.split()` 处理，组装 arguments dict
  - [ ] 无 MCP 活跃时提示错误

- [ ] **Task 4: 渲染文本注入**
  - [ ] 调 `mgr.get_prompt()` 获取渲染文本
  - [ ] 作为 user message 经 `run_stream` 注入
  - [ ] 异常处理（模板不存在/参数缺失）

- [ ] **Task 5: 测试**
  - [ ] CLI 集成测试（mock input / mock manager）
  - [ ] 解析器边缘用例（无参数、多余空格）

## Dev Notes

- slash 分发器保持最小：仅 `input()` 后加一个 if 分支，不引入新依赖。
- `/mcp-prompt` 格式：`/mcp-prompt <server> <name> [key=value ...]`，`key=value` 按空格分割。
- 无等价于 `list_prompts` 的 slash（尚不需要）——agent 可用 `mcp__list_resources` 等价物发现。
- `_run_chat` 的 `async with mcp_ctx ... as mgr` 修改须同步 `_run_single`（保持签名一致）。

## File List

- `src/heagent/cli.py` — `_run_chat` slash 分发器 + `/mcp-prompt` 解析器
- `tests/test_cli.py` — 新增 slash 解析测试

## Change Log

- 2026-07-23：Story 16-2 创建。
