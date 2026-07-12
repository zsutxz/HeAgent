---
title: "HeAgent MCP v1→v2 升级准备"
status: draft
created: 2026-07-12
updated: 2026-07-12
---

# Product Brief: HeAgent MCP v1→v2 升级准备

## 概述

HeAgent 的 MCP client（`tools/mcp/`，Epic 11-13 交付）现在能连任意 MCP server、消费 Tools 原语。但官方 Python SDK `mcp` 的 **v2.0.0 stable 目标 2026-07-27**、协议规范 **2026-07-28 RC（breaking，→final）**，将重塑 client 侧 API。

本周期不接新原语，而是**兑现 `mcp-client` brief 已埋的迁移预留**——「握手等细节封装在 `MCPClientManager` 内部，为协议演进预留接口」。把当前 client 里会被 v2 冲刷的调用点抽象成隔离层。v2 stable 落地时，切换将局限于该层内部，Epic 11-13 零回归。

## 问题

对照官方 v2 迁移指南（py.sdk.modelcontextprotocol.io/v2/migration），逐行核查 `tools/mcp/` 命中的 breaking 点，共 5 个：

**设计级（语义变化，需重新设计，非改名）——最痛：**
- `session.initialize()`（manager.py:215,226）**删除**——v2 转 stateless，握手改为每请求 `_meta` 协商 + `server/discover`。整个 `_transport_and_session`（yield 已 initialize 的 session）架构要重构。
- `session.send_ping()`（manager.py:290）**deprecated**——v2 stateless 下无持久 session，ping 语义消失。这直接冲击 **FR-3 的『运行时 ping 监测断连、自动注销工具』机制**（2026-07-01 落地的安全收紧），断连探测在 v2 形态下要重新设计（候选见 addendum §5）。`[ASSUMPTION: 等价机制选型留 architecture]`

**机械级（改名/改签名，隔离层直接吸收）：**
- `from mcp.types import CallToolResult, ...`（mapping.py:18）→ v2 拆独立 `mcp-types` 包
- `session.list_tools()`（manager.py:234）→ 签名变（去 cursor、改 `params=PaginatedRequestParams`）+ 返回字段 `inputSchema`→`input_schema`
- `session.call_tool()`（manager.py:256）→ 返回 `CallToolResult` 字段全 snake_case（经 `mapping.bridge_result` 消费）

**未命中**（没接 Resources 原语，v2 这块 breaking 不影响 HeAgent）：`subscribe_resource`/`read_resource`/`AnyUrl`/`get_server_capabilities`/`McpError`/`cursor`。

不准备 = v2 stable 落地时 Epic 11-13 的 MCP 集成（连接 / 发现 / 调用 / 断连探测四条链）被冲刷、可能破损。

## 方案

1. **隔离层抽象**：在 `MCPClientManager` 内隔离上述 5 个调用点（initialize 握手 / send_ping 健康探测 / list_tools / call_tool / types 导入），暴露稳定的内部接口；v2 形态的差异（含 FR-3 断连探测的等价机制）封装在层内。`[ASSUMPTION: 隔离层抽象形态（protocol/adapter）留 architecture]`
2. **迁移测试基线**：Epic 11-13 的 MCP 测试（`tests/test_mcp_*.py`）是回归基线，本周期所有改动须全绿——验证「准备」不破坏现有功能。
3. **切换路径设计（不执行）**：文档化 v2 stable 落地时的切换步骤（改隔离层内部实现，外部接口不动）。实际切换视 v2 stable 落地时点（2026-07-27）另开独立任务，可能跨周期。

## 受众

- **主要**：HeAgent 作者（自用）——确保 MCP 集成在 v2 落地后不破损、断连探测不失效。
- **次要**：开源用户——升级路径平滑，不被 breaking 冲刷。
- **非受众**：需 Resources/Prompts/写操作的用户（见范围-Out）。

## 成功标准

- ✅ v1.28.1 落地，现有 MCP 测试零回归（`pytest tests/test_mcp_*.py` 全绿）。
- ✅ `MCPClientManager` 的 5 个 v2-sensitive 调用点被隔离层封装；隔离层对外接口签名在 v1→v2 切换前后保持不变（diff 为空）。
- ✅ FR-3 断连探测在 v2 形态下有等价机制设计（architecture 定型，可不含实现）。
- ✅ 切换路径文档化：v2 stable 落地时改动局限于隔离层内部。

## 范围

**In：**
- pin floor 提到 `mcp>=1.28.1,<2`（对齐 v1 线最新 stable 1.28.1；现 pin `mcp>=1.28,<2` 已排除 v2 alpha，本周期 bump floor 锁最新）
- `MCPClientManager` 隔离层抽象（封装 initialize / send_ping / list_tools / call_tool / types 导入）
- FR-3 断连探测的 v2 等价机制**设计**（可不含实现）
- 迁移测试基线（Epic 11-13 测试零回归验证）
- v2 stable 切换路径**文档化**（不执行实际切换）

**Out（明确不做）：**
- Resources / Prompts 原语（research 证伪 ROI，暂挂，v2 stable 后重评）
- 写操作（正交，独立 spec）
- 实际切 v2（等 stable 落地，可能跨周期）
- 把 HeAgent 暴露为 MCP server

## 技术约束

- 依赖官方 SDK，pin floor 提到 `mcp>=1.28.1,<2`（v1 线最新 stable；v2 stable 落地后再评估 pin 上界）。
- 协议 stable `2025-11-25` 落地；`2026-07-28` 仅 RC（→final），仅作设计参照，不依赖。
- 隔离层不引入 v2 alpha 依赖——纯 v1 上做抽象，为 v2 留形。

## 愿景

HeAgent 成为「能跟随 MCP 协议演进、不被 breaking 冲刷的稳定 client」。v2 stable 后切换只动隔离层。
