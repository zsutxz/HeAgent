---
title: "HeAgent MCP Client 集成 — PRD"
status: final
created: 2026-06-20
updated: 2026-06-20
---

# HeAgent MCP Client 集成 — 产品需求文档（PRD）

> 输入：产品 brief（`_bmad-output/mcp-client/brief.md`）。本文把 brief 展开为可被架构 / epics 消费的需求。技术实现细节见同目录 `brief-addendum.md`（MCP 协议 / SDK / 各框架模式）。

## 1. 背景与目标

HeAgent 是已落地的自学习 AI Agent 框架，工具体系基于 `@tool` 装饰器 + `ToolRegistry` 进程单例，内置 18 个工具。当前工具**写死内置**，接外部能力（GitHub、数据库、浏览器）需逐个手写工具模块，无法复用生态。

**目标**：接入 Model Context Protocol (MCP)，让 HeAgent 能连接任意 MCP server、动态消费其 **Tools** 原语，把外部工具桥接进现有 `ToolRegistry`，从「自带工具」升级为「可连接生态无限工具」。首个验收场景：**GitHub 只读**（查 issue / 搜代码 / 读 repo）。

**非目标（V1 不做）**：
- MCP 写操作（建 issue / 提 PR）—— 紧接下一步
- Resources / Prompts 原语
- HeAgent 自身暴露为 MCP server
- OAuth 2.1 完整流
- MCP Registry / 目录集成

## 2. 受众与使用场景

**受众**：HeAgent 作者（自用提效）为主，开源用户（配自己的 MCP server）为辅。详见 brief。

**示例会话**（代表性场景）：
> tan 配置好 GitHub MCP server 后，对 HeAgent 说「HeAgent 这个 repo 最近有哪些 open issue？」→ agent 自动调用 GitHub server 的 `list_issues` 工具，返回并总结。继续问「搜一下 retry 是怎么实现的」→ agent 调用 `search_code` → 返回命中文件与片段。全程 tan 无需手写任何工具代码。

## 3. 功能需求（FR）

> FR 全局稳定编号，下游 epics 直接引用。能力导向，实现细节见 addendum / architecture。

### 3.1 MCP Server 连接与生命周期

- **FR-1**：HeAgent 能根据声明式配置连接外部 MCP server，支持 **stdio**（本地子进程）与 **Streamable HTTP**（远程）两种 transport。
- **FR-2**：MCP server 连接生命周期与 `AgentLoop` 绑定 —— loop 启动时建立连接、退出时优雅回收（子进程关闭 / session 断开），崩溃可观测。**工具发现须在 AgentLoop 首次构建工具列表（注入 system prompt）前完成，或提供 lazy 发现回退**（该时序影响 NFR-4 启动性能与 R3 工具规模策略，架构须定 eager / lazy）。
- **FR-3**：连接失败时按 HeAgent 既有异常层级降级（`ProviderError` / `ToolError` 体系），不使 agent 整体崩溃；失败 server 的工具不注入。区分两种失败：**连接建立阶段失败**（工具从未注入）与**运行时已注册工具因 server 断连失效**（调用时降级为错误结果，不崩溃）。

### 3.2 工具发现与桥接

- **FR-4**：连接 server 后**动态发现**其暴露的 Tools，映射为 HeAgent 的 `ToolSchema`（name / description / JSON Schema inputSchema），注册进 `ToolRegistry`，LLM 像调用内置工具一样调用。
- **FR-5**：MCP 工具调用的结果桥接为 HeAgent `ToolResult`，回到 `AgentLoop` 既有循环，与内置工具执行路径一致（含并行执行 `asyncio.gather`）。
- **FR-6**：多 server 工具命名去歧义 —— 工具名加 server 名前缀作 namespace，避免跨 server 冲突。

### 3.3 声明式配置

- **FR-7**：用户通过声明式 `mcpServers` 配置声明要连接的 server，配置文件为项目根 **`.mcp.json`**（对齐 Claude Code / Cursor 的文件名与位置）；stdio: `{command, args, env}`，http: `{url, headers}`。**无 `.mcp.json` 或 server 列表为空时，AgentLoop 以纯内置工具模式启动，不报错、不阻断**。
- **FR-8**：配置支持环境变量插值（如 `${GITHUB_TOKEN}`）；鉴权凭据（GitHub PAT）通过环境变量注入，不写入配置文件明文。

### 3.4 GitHub 只读验收

- **FR-9**：以 GitHub MCP server（官方 `github/github-mcp-server`）为验收场景，agent 能完成**两类只读操作**：「列出指定 repo 的 open issue」与「代码搜索」。结果经 `ToolResult` 桥接，**E2E 可断言关键字段**（issue 列表项 / 搜索命中文件路径）。V1 验收范围限于上述两类；其余只读操作（issue 详情 / 读 repo 文件）列入后续 epic backlog，不在本 PRD 验收。

### 3.5 安全

- **FR-10**：外部 MCP server 明确归入 HeAgent 既有安全声明（不可信代码 + 不可信输出进 LLM 上下文）；CLAUDE.md 安全声明更新覆盖 MCP。
- **FR-11**：MCP 工具调用受与内置工具同等的安全约束，**工具返回内容同样视为不可信**（prompt injection 无隔离）。当前 `SafetyGuard` 主要约束 shell 命令；MCP 工具的检查机制扩展（敏感工具确认、返回内容复核）作为 architecture 探索项，V1 以安全声明 + 边界声明为主。

## 4. 非功能需求（NFR）

- **NFR-1（异步）**：全异步实现，库代码无同步 I/O（符合 CLAUDE.md）；MCP SDK 原生 asyncio。
- **NFR-2（零回归）**：现有 18 个内置工具 + 全部既有测试零回归（`pytest` 全绿）；以实现时记录的当前覆盖率为基线，不下降。
- **NFR-3（版本可控）**：依赖 `mcp>=1.27,<2`（当前 stable 1.28.0，见 §6 协议窗口）；协议握手等细节封装在 `MCPClientManager` 内部，为 2026-07-28 stateless 协议迁移预留接口。**成功标准**：v2 / stateless 迁移时改动限于 `MCPClientManager` 内部，不波及 `AgentLoop`。
- **NFR-4（启动性能）**：多 server 连接与工具发现不显著拖慢 agent 启动；实现时测量并记录基线（冷启动增量，如单 server stdio 连接 + 工具发现 ≤ 数秒量级），后续不劣化。
- **NFR-5（可观测）**：server 连接状态、工具发现数量、调用结果有日志（标准库 logging，每模块 `getLogger(__name__)`）。
- **NFR-6（错误隔离）**：单个 server 失败不影响其他 server 与内置工具。
- **NFR-7（代码规范）**：遵循项目规范（PEP8 / Pydantic BaseModel / 120 行宽 / Python 3.11+）；新增 tool 层模块禁止从 `agent/` 导入（DAG 约束）。

## 5. 成功指标

| 指标 | 目标 | 反指标（counter） |
|---|---|---|
| MCP 链路打通 | agent 能发现 + 调用外部 MCP 工具 | server 连接失败率 |
| GitHub 只读验收 | ≥1 个真实 repo 的 issue / 代码搜索 E2E 通过 | — |
| 开源可用 | 声明式配置 + 文档示例可让他人接入自己的 server | 配置上手成本（步骤数） |
| 零回归 | 既有测试全绿、覆盖率不降 | 新增 bug 数 |
| 安全边界清晰 | 安全声明更新、MCP 受同等约束 | 误以为「接 MCP 更安全」 |
| 协议可迁移 | 握手封装内部，迁移改动局部化 | 与 SDK v2 强耦合面 |

## 6. 约束与依赖

- **协议窗口**：stable `2025-11-25`，`2026-07-28` RC stateless breaking（详见 addendum）。
- **SDK**：官方 `mcp` Python SDK（v1.28.0 stable，原生 async）。
- **架构 DAG**：MCP 适配属 `tools/` 层，禁止从 `agent/` 导入；复用 `ToolRegistry` / `ToolSchema` / `ToolResult` / `SafetyGuard`。
- **配置形态**：声明式 `mcpServers`（对齐 Claude Code）。
- **安全**：受 CLAUDE.md 文首安全声明约束，不可在无 OS 沙箱下裸跑外部 server。

## 7. 风险

- **R1（安全）**：外部 server = 不可信代码 + 不可信输出。缓解：安全声明 + 文档警示 + 建议沙箱。
- **R2（stdio 子进程生命周期）**：崩溃 / 僵尸进程 / env 泄漏。缓解：`AsyncExitStack` 托管 + 优雅关闭。
- **R3（工具数量爆炸）**：多 server 叠加侵蚀上下文、降低工具选择准确率。缓解：lazy 发现 + 复用 `ContextCompressor` + namespace。
- **R4（SDK breaking）**：v2 + 协议 stateless 双 breaking。缓解：握手封装内部 + pin `<2`。
- **R5（GitHub server 形态选择）**：官方远程（Streamable HTTP）vs 社区 stdio。缓解：双 transport 都支持；**验收采用官方远程 server**（只读 + 官方维护，无需本地 Docker）。

## 8. 决策定稿记录

> 全部 `[ASSUMPTION]` 已在 finalize 定稿（见 `.decision-log.md` DP-1~DP-6）：

1. ✅ **已定**：配置落点 = 项目根 `.mcp.json`（对齐 Claude Code / Cursor）。
2. ✅ **已定**：鉴权 = GitHub PAT 走环境变量 `${GITHUB_TOKEN}`。
3. ✅ **已定**：GitHub 验收清单 = 「列 open issue」+「代码搜索」两类 E2E。
4. ✅ **已定**：SafetyGuard = 安全声明 + 边界声明为主，扩展机制交 architecture。
5. ✅ **已定**：验收用官方远程 server（Streamable HTTP）。
6. ✅ **已定**：记忆整合 = Vision，不进 V1（继承 brief）。

→ 全部 `[ASSUMPTION]` 已定稿，无 phase-blocker。

## 9. 下游

- 架构（`bmad-create-architecture`）：`MCPClientManager` 设计、transport 抽象、`ToolSchema` 映射、生命周期与 `AgentLoop` 集成点。
- Epics & Stories（`bmad-create-epics-and-stories`）：按 FR 拆 epic（连接生命周期 / 发现桥接 / 配置 / GitHub 验收 / 安全）。
