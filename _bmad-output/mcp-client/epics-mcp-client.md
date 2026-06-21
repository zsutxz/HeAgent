---
stepsCompleted: [1, 2, 3, 4]
epicStructureApproved: true
status: complete
completedAt: 2026-06-20
resumeState: "epics 工作流全部完成（step-1~4 通过）。8 stories（Epic1×5 / Epic2×1 / Epic3×2）已写入并经 step-4 终验通过。文档就绪，进入实现阶段：Epic 1 Story 1.1 起按架构实现序列（pyproject 加 mcp>=1.28,<2 → tools/mcp/ 骨架 → config → mapping → manager → cli 装配 → GitHub E2E）。"
inputDocuments:
  - _bmad-output/mcp-client/prd.md
  - _bmad-output/mcp-client/architecture.md
  - _bmad-output/mcp-client/brief.md
  - _bmad-output/mcp-client/brief-addendum.md
---

# HeAgent MCP Client 集成 - Epic Breakdown

## Overview

本文档提供 **HeAgent MCP Client 集成** 的完整 epic 与 story 拆分，把 PRD（FR-1~11 / NFR-1~7）+ Architecture（决策 A-H / 实现序列）的需求分解为可实现的 story。

> 输入：PRD `_bmad-output/mcp-client/prd.md`、Architecture `_bmad-output/mcp-client/architecture.md`。技术型 PRD，无 UX 设计。

## Requirements Inventory

### Functional Requirements

```
FR-1: 连接外部 MCP server，支持 stdio（本地子进程）+ Streamable HTTP（远程）双 transport
FR-2: 连接生命周期与 AgentLoop 绑定（启动建立、退出回收）；工具发现须在 AgentLoop 首次构建工具列表前完成（或 lazy 回退）
FR-3: 连接失败按既有异常层级降级不崩溃；区分「连接建立失败（工具不注入）」vs「运行时断连（已注册工具调用时降级）」
FR-4: 连接后动态发现 Tools → 映射 ToolSchema → 注册进 ToolRegistry
FR-5: MCP 工具调用结果桥接为 ToolResult，与内置工具执行路径一致（含并行 asyncio.gather）
FR-6: 多 server 工具命名去歧义（<server>__<tool> namespace 前缀）
FR-7: 声明式 mcpServers 配置（项目根 .mcp.json）；无配置=纯内置模式不报错不阻断
FR-8: 配置支持 ${ENV} 插值；鉴权凭据走环境变量不落配置明文
FR-9: GitHub 只读验收（列 open issue + 代码搜索），E2E 可断言关键字段
FR-10: 外部 MCP server 归入既有安全声明；CLAUDE.md 安全声明更新覆盖 MCP
FR-11: MCP 工具调用受同等安全约束；工具返回内容视为不可信
```

### NonFunctional Requirements

```
NFR-1: 全异步，库代码无同步 I/O（MCP SDK 原生 asyncio）
NFR-2: 零回归（18 内置工具 + 既有测试全绿；覆盖率以实现时基线不下降）
NFR-3: 版本可控（mcp>=1.27,<2；握手封装内部为 2026-07-28 stateless 迁移预留）
NFR-4: 启动性能（多 server 连接+发现不拖慢启动；eager+并发+隔离+每服务器超时）
NFR-5: 可观测（连接/发现/调用日志，stdlib logging）
NFR-6: 错误隔离（单 server 失败不影响其他 server 与内置工具）
NFR-7: 代码规范（PEP8 / Pydantic BaseModel / 120 行宽 / 3.11+；tool 层禁从 agent 导入）
```

### Additional Requirements

```
- Starter template：无（brownfield，沿用既有骨架）→ Epic 1 Story 1 是「依赖引入 + tools/mcp/ 骨架」，非项目初始化
- 依赖：pyproject.toml 增 "mcp>=1.28,<2"（web 验证 stable 1.28.0，2026-06-16）
- 集成约束：复用既有 ToolRegistry.register()（零扩展）、AgentLoop 零改动、MCP 异常映射 ToolError
- 配置：Settings 增 mcp_enabled / mcp_config_path 门控；.mcp.json 独立 Pydantic loader + ${ENV} 插值（fail-fast）
- 生命周期：MCPClientManager 作 async ctx mgr，CLI 用 async with 包住 run；AsyncExitStack 托管；eager+并发+隔离+每服务器连接超时
- 文档：CLAUDE.md 安全声明更新 + 模块速查 + DAG；.mcp.json.example；README 接入说明
- 测试：平铺 tests/test_mcp_*.py + Stub session 隔离网络；GitHub E2E 独立 @pytest.mark.integration（需 GITHUB_TOKEN，不进默认全绿基线）
- 协议迁移预留：握手/transport 封在 MCPClientManager，2026-07-28 stateless 迁移改动局部化
```

### UX Design Requirements

无（技术型 PRD，无 UI）。

### FR Coverage Map

```
FR-1:  Epic 1 — stdio + Streamable HTTP 双 transport
FR-2:  Epic 1 — 连接生命周期绑定 AgentLoop + eager 发现时序
FR-3:  Epic 1 — 失败隔离（连接建立失败 vs 运行时断连）
FR-4:  Epic 1 — 发现 → ToolSchema → 注册
FR-5:  Epic 1 — 结果 → ToolResult（含并行 asyncio.gather）
FR-6:  Epic 1 — <server>__<tool> namespace 去歧义
FR-7:  Epic 1 — 声明式 .mcp.json + 无配置纯内置模式
FR-8:  Epic 1 — ${ENV} 插值 + PAT 走环境变量不落明文
FR-9:  Epic 2 — GitHub 只读 E2E（列 open issue + 代码搜索）
FR-10: Epic 3 — 安全声明覆盖 MCP
FR-11: Epic 3 — 同等安全约束 + 返回内容视为不可信
```

**NFR 横切**（织入全部 epic）：NFR-1/7 全程；NFR-2 零回归全程验证；NFR-3/4/5/6 主要在 Epic 1。

## Epic List

> ✅ **状态：APPROVED — tan 已批准（2026-06-20）**。按用户价值设计（非技术层）；架构已完整预设计（决策 A-H）→ 倾向少而大的 epic；FR-9 真实 server 验收为独立反馈边界。合计 **8 stories**（Epic1×5 / Epic2×1 / Epic3×2）。

| Epic | 标题 | FRs | Stories |
|------|------|-----|---------|
| Epic 1 | MCP 工具桥接（核心能力） | FR-1~8 | 1.1~1.5 |
| Epic 2 | GitHub 只读验收（真实场景打通） | FR-9 | 2.1 |
| Epic 3 | 安全边界与开源可用（收尾） | FR-10/11 | 3.1~3.2 |

**依赖：** Epic 1 独立可用；Epic 2、Epic 3 各构建于 Epic 1 之上，彼此独立。Epic 1 内部依赖链：1.1 → (1.2 ∥ 1.3) → 1.4 → 1.5（1.2/1.3 互不依赖），无前向依赖。

---

## Epic 1: MCP 工具桥接（核心能力）

**用户成果：** tan 写一份 `.mcp.json`，HeAgent 连上任意 MCP server、自动发现其工具，LLM 像调用内置工具一样调用外部工具，结果回到既有循环。
**FRs covered:** FR-1, FR-2, FR-3, FR-4, FR-5, FR-6, FR-7, FR-8
**为何单 epic：** config / transport / 发现 / 桥接 / 生命周期全部触碰 `tools/mcp/` 核心文件，架构已完整预设计（无子件反馈环）—— 按 file-churn 规则合并为单 epic 有序 story。stdio+HTTP 同在 manager 内部分派（无独立 risk 边界，不拆）。
**实现序列锚点（architecture §Implementation Handoff）：** 依赖+骨架 → config → mapping → manager → cli 装配。

### Story 1.1: 引入 MCP 依赖与搭建 tools/mcp/ 适配层骨架

As a framework author,
I want 加入官方 `mcp` Python SDK 依赖、创建 `tools/mcp/` 包骨架并新增 Settings 门控字段,
So that 后续 MCP story 有干净落点、遵守 DAG（不引 `agent/`）且 SDK 锁定可迁移版本窗口（`<2` 排除 v2 alpha）。

**Acceptance Criteria:**

**Given** `pyproject.toml`
**When** 在 dependencies 增 `"mcp>=1.28,<2"` 并执行 `pip install -e ".[dev]"`
**Then** 安装成功、`mcp` SDK 可导入、`<2` 约束排除 2026-07-27 v2 alpha
**And** `mcp>=1.28,<2` 与既有依赖无版本冲突。

**Given** `src/heagent/tools/mcp/`
**When** 创建 `__init__.py`（占位导出）
**Then** `from heagent.tools.mcp import ...` 可导入
**And** `ruff check` / `mypy src` 对新骨架全绿。

**Given** `config.py` 的 `Settings`
**When** 新增 `mcp_enabled: bool = True` 与 `mcp_config_path: str = ".mcp.json"` 字段
**Then** `get_settings()` 暴露这两个字段（对齐既有 `cron_enabled` 命名）
**And** 既有测试零回归（`reset_settings()` 行为不变）。

**Given** DAG 约束（MCP 属 `tools/` 层）
**When** 检查 `tools/mcp/` 全部导入
**Then** 无任何 `heagent.agent.*` 反向导入。

### Story 1.2: 声明式 .mcp.json 配置加载与环境变量插值

As a framework author,
I want 独立 `.mcp.json` loader（`MCPConfig` / `StdioServerConfig` / `HttpServerConfig` Pydantic 模型 + `load_mcp_config()`）解析多 server 配置并做 `${ENV}` 插值,
So that 声明式配置 stdio/http server（对齐 Claude Code/Cursor 文件名位置）、密钥走环境变量不落配置明文、fail-fast 暴露配置错误。

**Acceptance Criteria:**

**Given** `.mcp.json` 含 `{"mcpServers": {"github": {"url": "...", "headers": {"Authorization": "Bearer ${GITHUB_TOKEN}"}}}}`
**When** `GITHUB_TOKEN` 已设于 `os.environ` 时调用 `load_mcp_config()`
**Then** 头值插值成功、token 不出现在配置的明文面
**And** 插值在加载时一次性展开（非延迟）。

**Given** `.mcp.json` 引用 `${MISSING_VAR}` 而 `MISSING_VAR` 未设
**When** 调用 `load_mcp_config()`
**Then** fail-fast 抛错（不静默、不注入空值），PAT 绝不落明文（DP-2）。

**Given** stdio 条目 `{"command": "...", "args": [...], "env": {...}}` 与 http 条目 `{"url": "...", "headers": {...}}`
**When** 加载
**Then** 分别校验为 `StdioServerConfig` / `HttpServerConfig` Pydantic 模型
**And** 非法结构（缺 `command` / `url`）被 Pydantic 校验拒绝。

**Given** 项目根无 `.mcp.json`，或 `mcpServers` 为空
**When** 调用 `load_mcp_config()`
**Then** 返回空配置（不报错、不阻断）→ 纯内置工具模式（FR-7）。

**Given** `tests/test_mcp_config.py`（平铺，不镜像 `tools/mcp/`）
**When** 运行
**Then** 覆盖校验 / `${ENV}` 插值 / 缺失变量 fail-fast / 缺文件纯内置行为
**And** 全程无网络调用。

### Story 1.3: MCP 工具到 ToolSchema 的映射与结果桥接

As a framework author,
I want `mapping.py` 把发现的 MCP 工具转成 namespace 化 `ToolSchema`、把 `CallToolResult` 桥接为文本（`isError` 抛 `ToolError`）,
So that MCP 工具套进既有 registry/执行路径、零 schema 重设计、错误语义与内置工具一致。

**Acceptance Criteria:**

**Given** MCP tool `{name: "list_issues", description: ..., inputSchema: {...}}` 来自 server "github"
**When** 映射
**Then** 生成 `ToolSchema(name="github__list_issues")`
**And** `parameters` 直接填入 `inputSchema`（JSON Schema passthrough，不重映射）。

**Given** server 名 `GitHub-MCP`
**When** 规整化
**Then** namespace 前缀用 `github_mcp`（小写 + 非字母数字 → `_`）。

**Given** 两 server 规整后产生相同前缀
**When** 映射/注册
**Then** 检测到冲突 → 记 WARNING 日志并去重/跳过（FR-6 健壮性）。

**Given** `CallToolResult.content` 含多个 `TextContent` 块
**When** 桥接
**Then** 用 `\n` 连接为单个 str 作为 `ToolResult.content`
**And** `ImageContent` → `[image]` 占位、`EmbeddedResource` → `[resource: uri]` 占位（V1 text-only）。

**Given** `CallToolResult.isError == True`
**When** handler 运行
**Then** 抛 `ToolError`（→ `_execute_one` 转 `ToolResult(is_error=True)`）
**And** 无新建异常类、无裸 `Exception`（决策 D + G）。

**Given** `tests/test_mcp_mapping.py`（Stub，无真实 session）
**When** 运行
**Then** 覆盖 schema 映射 / namespace 规整 / 冲突检测 / 文本桥接 / is_error 抛错
**And** 全程无网络调用。

### Story 1.4: MCPClientManager 连接生命周期与并发发现注册

As a framework author,
I want `MCPClientManager` 作 async ctx mgr：并发连所有 server（stdio+http）、发现工具、注册进 `ToolRegistry` 单例，失败隔离 + 每 server 连接超时 + 退出清理,
So that MCP server 生命周期绑 AgentLoop 而不动其契约、eager 发现（LLM 首轮即见全部 MCP 工具）、单 server 失败零崩溃。

**Acceptance Criteria:**

**Given** 含 2 个 server 的 `MCPConfig`
**When** 进入 `async with MCPClientManager(config)`
**Then** 两 server 并发连接（`asyncio.gather(*connect_tasks, return_exceptions=True)`）、各自 `tools/list` 发现 + 映射 + 注册进 `ToolRegistry` 单例
**And** 全部在 `__aenter__` 返回前完成（满足 FR-2 时序锚点：`enabled_schemas()` 首轮即含 MCP 工具）。

**Given** 慢/挂起的 server
**When** 连接
**Then** 每 server 用 `asyncio.wait_for(_connect(entry), timeout=...)` 包裹、超时即隔离该 server（其工具不注入）
**And** 不阻塞其他 server 与 agent 启动（NFR-4）。

**Given** 某 server 连接建立失败（如坏 command / 不可达 URL）
**When** `_connect_all` 运行
**Then** 该 server 工具不注入、记 WARNING 日志（NFR-5）
**And** 其他 server + 内置工具完全不受影响（NFR-6 错误隔离，FR-3 建立失败路径）。

**Given** manager 已进入、某 MCP 工具被 LLM 调用
**When** 执行
**Then** closure handler 调 `session.call_tool` → mapping 桥接 → 返回 `_execute_one`
**And** 走与内置工具一致的并行 `asyncio.gather` 路径（FR-5）。

**Given** 运行时某已注册工具因 server 断连失效
**When** LLM 调用它
**Then** 调用降级为 `ToolError` → `ToolResult(is_error=True)`、不崩溃 agent（FR-3 运行时断连路径）。

**Given** 退出 manager（`__aexit__`）
**When** 执行清理
**Then** 从 `ToolRegistry` unregister 全部 MCP 工具（还原纯内置状态，利于测试隔离）
**And** `AsyncExitStack` 关闭所有 session/子进程（优雅、防僵尸进程/env 泄漏，决策 C）。

**Given** `tools/mcp/manager.py`
**When** 静态检查
**Then** 无 `heagent.agent.*` 导入、仅用 `ToolError`、`AgentLoop` 零改动、复用 `registry.register()` 不扩 API。

**Given** `tests/test_mcp_manager.py`（Stub session，无网络）
**When** 运行
**Then** 覆盖并发连接 / 单 server 隔离 / 超时隔离 / register-unregister 对称 / 退出清理
**And** 全程无网络调用。

### Story 1.5: CLI 装配 MCPClientManager 生命周期到运行入口

As tan（框架作者兼终端用户）,
I want CLI 把 `_run_single` / `_run_chat` 包进 `async with MCPClientManager(...)`（由 Settings 门控）,
So that 带 `.mcp.json` 跑 HeAgent 即为该会话连接 MCP server 并退出回收，不带则纯内置模式。

**Acceptance Criteria:**

**Given** `mcp_enabled=True` 且有效 `.mcp.json`
**When** 运行 `python -m heagent "列出 open issue"`
**Then** CLI 加载配置、进入 `MCPClientManager`、MCP 工具注册、AgentLoop 运行时可用这些工具。

**Given** `mcp_enabled=True` 但项目根无 `.mcp.json`
**When** 运行 CLI
**Then** 以纯内置工具模式启动、不报错、不阻断（FR-7）。

**Given** `mcp_enabled=False`
**When** 运行 CLI（即使存在 `.mcp.json`）
**Then** 完全跳过 MCP 加载与连接（门控生效）。

**Given** 交互式 chat 会话
**When** 启动并随后退出
**Then** MCP 连接在退出时被回收（无残留子进程 / session）。

**Given** 既有 CLI 行为 + 全部既有测试
**When** 运行全量 `pytest`
**Then** 零回归（NFR-2）。

---

## Epic 2: GitHub 只读验收（真实场景打通）

**用户成果：** tan 能对 HeAgent 说「这个 repo 有哪些 open issue」「搜一下 retry 怎么实现的」并拿到准确结果 —— 触发本次迭代的真实场景。
**FRs covered:** FR-9
**为何独立：** 接**真实** GitHub server + 真实网络 + 真实 PAT 鉴权，是端到端验证里程碑；反馈可能反推调整 Epic 1 映射 —— 真正的 risk/feedback 边界。Epic 1 独立可用（任何 MCP server），Epic 2 构建其上。

### Story 2.1: 接官方远程 GitHub MCP server 跑通只读 E2E

As tan,
I want 接官方远程 GitHub MCP server（Streamable HTTP）端到端验证两类只读操作（列 open issue + 代码搜索）并断言关键字段,
So that MCP 集成对真实 server / 网络 / PAT 验证通过、本次迭代的触发场景真正可用。

**Acceptance Criteria:**

**Given** `GITHUB_TOKEN` 已设 + `.mcp.json`（或 example）配置官方远程 GitHub server（Streamable HTTP，`Authorization: Bearer ${GITHUB_TOKEN}`）
**When** agent 连接
**Then** 该 server 的只读工具被发现并 namespace 化（如 `github__list_issues`、`github__search_code`）。

**Given** 一个真实公开 repo（如 HeAgent 自身）
**When** tan 问「有哪些 open issue」
**Then** 调用 `list_issues`，返回 `ToolResult` 含 issue 列表项可断言字段（`number` / `title` / `state` / `url`，经 TextContent 到达）。

**Given** 同一 repo
**When** tan 问「搜一下 retry 怎么实现」
**Then** 调用 `search_code`，结果含命中文件路径 / 片段（可断言 `path` 字段）。

**Given** `tests/test_mcp_github_e2e.py` 标记 `@pytest.mark.integration`、需 `GITHUB_TOKEN`
**When** 有 token 运行 → 断言上述关键字段
**And** 当无 token 运行 → 被 skip，**不**进默认 `pytest` 全绿基线（NFR-2 零回归指单测全绿）。

**Given** 连接 / 鉴权失败（坏 token 或过期）
**When** E2E 运行
**Then** 降级为 `ToolError` / 隔离，不崩溃 agent。

**Given** FR-9 V1 验收范围
**When** 确认覆盖
**Then** 仅含「列 open issue」+「代码搜索」两类；其余只读操作（issue 详情 / 读 repo 文件）列入后续 backlog，不在本 story 验收。

---

## Epic 3: 安全边界与开源可用（收尾）

**用户成果：** 安全边界诚实声明（不可信边界清晰，不制造「接 MCP 更安全」假象）；配置示例 + README 让开源用户能接入自己的 server。
**FRs covered:** FR-10, FR-11（+ 文档承载「开源可用」SM）
**为何独立：** FR-10/11 安全声明 + 文档（.mcp.json.example / README / CLAUDE.md 更新）合并为「可被他人采用」收尾 epic。代码改动极小。

### Story 3.1: 诚实更新安全声明覆盖 MCP 不可信边界

As a framework author,
I want CLAUDE.md 安全声明更新显式覆盖外部 MCP server（不可信代码 + 不可信输出进 LLM 上下文）、声明 MCP 工具受同等约束并标注 OS 沙箱兜底,
So that 无人误以为「接 MCP 更安全」、边界诚实（与 SafetyGuard 非真正边界的既有立场同构）。

**Acceptance Criteria:**

**Given** CLAUDE.md 首部安全声明
**When** 更新
**Then** 显式声明：外部 MCP server = 不可信代码、其工具输出无隔离进入 LLM 上下文（prompt injection 无隔离）、须 OS 级沙箱（容器/firejail）兜底。

**Given** FR-11
**When** 文档化
**Then** 声明 MCP 工具受与内置工具同等安全约束、工具返回内容同样视为不可信
**And** 明确 V1 `SafetyGuard` **不**扩展到 MCP 工具（决策记录、扩展 deferred per DP-4），不制造「接 MCP 更安全」假象。

**Given** architecture 的 deferred / future-enhancement 项
**When** 文档化
**Then** 反映可见的后续工作：运行时断连 auto-unregister、`SafetyGuard` 扩展（敏感工具确认 / 返回内容复核）、Resources/Prompts 原语、写操作。

### Story 3.2: 开源可用配置示例与接入文档

As an open-source user of HeAgent,
I want `.mcp.json.example`（GitHub 配置样例）+ README 接入说明 + CLAUDE.md 模块速查/DAG 更新,
So that 照示例即可接入自己的 MCP server、无需读源码。

**Acceptance Criteria:**

**Given** `.mcp.json.example`（项目根，对齐 `.env.example` 惯例）
**When** 用户复制使用
**Then** 含可用的 GitHub 远程 server 配置（`${GITHUB_TOKEN}` 插值、无明文密钥）+ stdio server 示例。

**Given** README
**When** 新用户阅读
**Then** 存在 MCP 接入章节（如何启用 / `.mcp.json` 位置 / env 鉴权 / 沙箱警示）。

**Given** CLAUDE.md 模块速查表 + DAG
**When** 更新
**Then** `tools/mcp/` 层（`MCPClientManager` / `MCPConfig` / `mapping`）出现在模块速查表
**And** DAG 图显示 `tools/mcp/ → types/exceptions/registry`、无 `agent/` 反向依赖。

**Given** `.mcp.json` 含私有 server URL
**When** 用户提交
**Then** 框架不强求 gitignore（用户自决，文档说明）。

---

## FR Coverage Verification

| FR | Story | 覆盖 |
|----|-------|------|
| FR-1 | 1.4（manager transport 分派）+ 1.1（dep） | ✅ |
| FR-2 | 1.4（生命周期）+ 1.5（cli wiring） | ✅ |
| FR-3 | 1.4（隔离 + 运行时降级） | ✅ |
| FR-4 | 1.3（映射）+ 1.4（发现/注册） | ✅ |
| FR-5 | 1.3（结果桥接）+ 1.4（handler 路径） | ✅ |
| FR-6 | 1.3（namespace + 冲突） | ✅ |
| FR-7 | 1.2（声明式 + 无配置模式）+ 1.5（门控） | ✅ |
| FR-8 | 1.2（${ENV} 插值） | ✅ |
| FR-9 | 2.1 | ✅ |
| FR-10 | 3.1 | ✅ |
| FR-11 | 3.1 | ✅ |

**NFR 横切覆盖：** NFR-1（全异步）织入 1.2~1.4；NFR-2（零回归）每个 story 均验证；NFR-3（握手封装）承重于 1.4；NFR-4（启动性能）1.4 超时；NFR-5（可观测）1.2/1.4 日志；NFR-6（错误隔离）1.4；NFR-7（代码规范）全部 story。无 UX Design Requirement（技术型 PRD）。
