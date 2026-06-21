---
title: "HeAgent MCP Client 集成"
status: draft
created: 2026-06-20
updated: 2026-06-20
---

# Product Brief: HeAgent MCP Client 集成

## 概述

HeAgent 已是一个功能完整的自学习 AI Agent 框架——provider 容错链、18 个内置工具、自学习记忆、子 agent 编排、cron 调度全部落地。本次迭代给它接上 **Model Context Protocol (MCP)**：在现有工具体系之上加一层「MCP client 适配器」，让 HeAgent 能连接任意 MCP server、动态发现并调用其工具，从「自带 18 个工具」升级为「接入生态里无限的外部工具」（即 MCP server 暴露的工具）。

第一版聚焦**通用 client 能力**（只消费 MCP 的 Tools 原语），以 **GitHub** 为首个验收场景——用户能让 agent 读 GitHub 的 issue、搜索代码、浏览 repo。这是触发本次迭代的真实场景，也最能检验端到端链路是否可用。

## 问题

HeAgent 当前的工具是**内置且写死**的（shell、文件、cron、记忆……）。要接外部能力——GitHub、数据库、浏览器、第三方 API——就得为每一个手写一个 `@tool` 模块。每接一个新数据源 = 写一份新代码，无法复用生态里已有的成熟实现。

更现实的是：**MCP 已成为 agent 工具的事实标准**。Claude Desktop、Cursor，以及 Pydantic AI / CrewAI / LangChain / OpenAI Agents SDK 等主流框架都已支持。不接入，HeAgent 在工具生态里就是一座孤岛。本次迭代的第一痛点，正是「让 agent 操作 GitHub」这件事现在做不到。

## 方案

在 HeAgent 现有的 `ToolRegistry` 之上，加一层 **MCP client 适配器**（基于官方 `mcp` SDK），把外部 MCP server 的工具桥接进现有体系，提供四项产品级能力：

1. **工具桥接**：把 MCP server 暴露的工具映射成 HeAgent 的 `ToolSchema`，注册进 `ToolRegistry`——LLM 像调用内置工具一样调用外部工具，结果回到 `AgentLoop` 既有循环。
2. **动态发现**：agent 连上 server 即自动拉取其工具清单，无需为每个 server 手写适配。
3. **声明式配置**：用户用一份 `mcpServers` 配置声明要连哪些 server（`{command, args, env}` for stdio / `{url, headers}` for Streamable HTTP），对齐 Claude Code / Cursor 的主流形态。`[ASSUMPTION: 配置落在 .heagent/mcp.json，鉴权用 GitHub PAT 放环境变量——review 时校准]`
4. **工具去歧义**：多 server 的工具名加 server 前缀作 namespace，避免冲突。

## 差异化

「做一个 MCP client」本身**并非技术壁垒**——各大框架都有现成实现，SDK 也已成熟。HeAgent 的真正机会在两点：

1. **与自学习记忆系统的潜在整合**：HeAgent 已有 skill 自学习闭环。「MCP 工具的使用能否沉淀成技能」是值得探索的差异化方向。`[ASSUMPTION: 这是 Vision 探索方向，非 V1 承诺]`
2. **诚实的安全定位**：不假装「接了 MCP 就更强大更安全」。外部 MCP server = 运行不可信代码 + 返回不可信输出进 LLM 上下文，与 HeAgent 现有 `SafetyGuard` 的局限**完全同构**，明确归入既有安全声明。这种诚实的安全定位本身就是一种差异化。

**不做的事**：不自建 MCP server 把 HeAgent 暴露出去（那是后续可选增强）；不重复造 SDK 能力——专注把 client 消费侧做扎实。

## 受众

- **主要**：HeAgent 的作者（自用提效）——让 agent 帮忙读 GitHub repo / issue / 代码，替代手动翻网页。
- **次要**：HeAgent 的开源用户——通过声明式配置接入**自己**的 MCP server 来用，降低上手门槛。
- **非受众（V1）**：需要写操作的生产用户、企业级团队协作场景、不熟悉 MCP 的纯终端用户。
- **成功画像**：用户配置好 GitHub MCP server 后，能问 agent「HeAgent 这个 repo 最近有哪些 open issue」「搜一下 retry 是怎么实现的」并得到准确结果。

## 成功标准

- ✅ agent 能连接外部 MCP server、**动态发现并调用**其工具（链路打通）。
- ✅ **GitHub 只读验收**：至少 1 个真实 repo 的 issue / 代码搜索 E2E 跑通。
- ✅ 开源用户能通过声明式配置接入**任意**自己的 MCP server（有文档 + 示例）。
- ✅ 现有 18 个内置工具 + 全部既有测试**零回归**（`pytest` 全绿，覆盖率不低于当前基线）。
- ✅ MCP 工具受与内置工具**同等的安全约束**，安全声明已更新覆盖 MCP。

## 范围

**V1 In：**
- 通用 MCP client 适配层（`ToolSchema` 动态桥接 + 动态发现）
- Tools 原语的发现与调用
- stdio + Streamable HTTP 双 transport
- 声明式 `mcpServers` 配置
- GitHub 只读验收场景
- 工具 namespace 去歧义
- 安全声明更新（MCP server 归入不可信边界）

**V1 Out（明确不做，留给后续）：**
- **写操作**（建 issue / 提 PR / 评论）→ 紧接的下一步（见愿景）
- **Resources / Prompts** 原语（语义与 Tools 重叠边界不清，主流框架也尚未接入）
- 把 HeAgent **自身暴露为 MCP server**
- OAuth 2.1 完整流（远程 server 复杂认证）——V1 先支持简单 token / header
- MCP Registry / server 目录集成

## 技术约束 / 兼容性窗口

- 依赖官方 Python SDK（`mcp` 包），pin `mcp>=1.27,<2`。
- 协议握手等细节封装在 `MCPClientManager` 内部，不泄漏给 `AgentLoop`，为协议演进预留接口。
- ⚠️ **时间窗口**：当前 MCP 协议 stable 为 `2025-11-25`，但 `2026-07-28` RC 是 breaking change（转向 stateless、删除 `initialize` 握手）。V1 落在 stable 版，但适配层设计须为这次迁移留好接口。详细技术速览见 `brief-addendum.md`。

## 愿景

HeAgent 成为「**能连接任何 MCP server 的自学习 agent**」——内置工具 + 无限外接工具 + 记忆系统三合一。紧接 V1 的下一步是把 GitHub 写操作补上，形成「看 + 改」的完整闭环（提 PR、建 issue、review）。再往后：MCP 工具的使用经验沉淀进自学习记忆，agent 越用越懂得「什么任务该调哪个外部工具」——这才是 HeAgent 区别于普通 MCP client 的长期价值。
