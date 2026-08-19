---
baseline_commit: 4d4cd61f043fdb333f14e7b1e9e5e43d88dd21b0
---

# Story 15.2: mcp__list_resources 聚合桥接工具（继承 V1 门控 + on-demand 不注入）

Status: done

## Story

As a HeAgent 操作者,
I want 调用 mcp__list_resources 列出已连 server 暴露的资源清单,
So that agent 能发现可寻址资源而不被自动全量塞进上下文。

> **本 story 是 Epic B（Resources on-demand）的核心交付**——注册聚合桥接工具 `mcp__list_resources`，自声明 `readOnlyHint=True`，继承 V1 MCP 门控，on-demand 不自动注入（FR-B1/B3, AR-5）。

## Acceptance Criteria

**AC-1（AR-5：聚合 token + V1 门控继承）**
**Given** MCP 活跃（有 server 连接）
**When** MCPClientManager 注册聚合桥接工具 `mcp__list_resources`
**Then** 其命名含 `mcp__` 聚合 token，被 `_is_mcp_tool` 识别为 MCP 工具，继承全量 V1 MCP 门控（`block_mcp_tools`/`approval_mcp_tools`/`sandbox_mcp_tools`/`__mcp__` 授权）
**And** 自声明 `readOnlyHint=True`（默认不审批，用户可 `approval_mcp_tools=True` 强制确认覆盖）

**AC-2（FR-B1：返回 server-tagged 资源列表）**
**Given** 多个已连 server 暴露资源
**When** 调用 `mcp__list_resources()`
**Then** 返回 server-tagged 列表，每项含 `{server, uri, name, description}`（FR-B1）

**AC-3（FR-B1：空结果不抛错）**
**Given** 无任何 server 连接或 server 不暴露资源
**When** 调用 `mcp__list_resources()`
**Then** 返回空列表，不抛错（FR-B1）

**AC-4（AR-5：无 MCP 配置时不注册）**
**Given** 无 MCP 配置（纯内置模式）
**When** manager 初始化
**Then** 不注册 `mcp__list_resources`（与 V1 一致）

**AC-5（FR-B3：on-demand 不自动注入）**
**Given** 会话启动 / server 连接成功后
**When** 检查 system prompt
**Then** 不含各 server 全量 resources 文本（on-demand）；资源内容仅在被 `mcp__read_resource` 调用后才进上下文

## Tasks / Subtasks

- [x] **Task 1: 注册 mcp__list_resources 桥接工具** (AC: #1)
  - [x] 在 `_connect_all` 成功后（MCP 非空），注册 `mcp__list_resources` 到 ToolRegistry
  - [x] 自声明 `readOnlyHint=True` 的 ToolSchema.annotations
  - [x] handler 签名无参数
  - [x] 无 MCP 配置时跳过注册

- [x] **Task 2: handler 实现——聚合各 server 的 list_resources** (AC: #2, #3)
  - [x] 遍历 `_sessions` 逐 server 调 `session.list_resources()`
  - [x] 产出 `{server, uri, name, description}` 格式的 JSON 字符串
  - [x] 无资源/无 server 时返回空列表

- [x] **Task 3: 测试** (AC: #1-#5)
  - [x] `test_list_resources_aggregates_all_servers`
  - [x] `test_list_resources_empty_when_no_resources`
  - [x] `test_list_resources_not_registered_when_empty_config`
  - [x] `test_list_resources_has_readonly_hint`

## Dev Notes

- 工具名 `mcp__list_resources`：`mcp__` 前缀确保 `_is_mcp_tool`（含双下划线）识别为 MCP 工具。
- handler 签名无参（`list_resources()` 无输入参数）。
- 聚合逻辑：对每个 server 调 `session.list_resources()`，异常隔离（单 server 失败不崩全部），结果合并排序后返回。

## File List

- `src/heagent/tools/mcp/manager.py` — 注册 `mcp__list_resources` + handler 聚合逻辑

## Change Log

- 2026-07-17：Story 15-2 创建，开始实施。
- 2026-07-17：Story 15-2 实现完成——`mcp__list_resources` 聚合桥接工具（`_connect_all` 成功后惰性注册 + 幂等 + `readOnlyHint=True`）+ handler 聚合各 server resources（单 server 失败隔离）+ 10 测试用例全覆盖。Status → done。
