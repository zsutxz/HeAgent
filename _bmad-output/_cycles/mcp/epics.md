# Epics — HeAgent MCP Client 集成（三阶段整合）

> **2026-08-18 整合**：本文整合原 `mcp-client/epics-mcp-client.md`（阶段一，内部 Epic 1-3 = 主线 Epic 11-13，8 stories）、`mcp-v2-upgrade/epics-mcp-v2-upgrade.md`（阶段二，主线 Epic 14，3 stories）、`mcp-client-v2/epics.md`（阶段三，内部 Epic A/B/C = 主线 Epic 15-17，11 stories；主线 Epic 18 内置 git 工具扩展见注记）。Story 文件（阶段三 9 个）存于 `stories/`；阶段一/二按惯例直接基于本文 AC 实现（无独立 story 文件）。
> 阶段一 story 编号（1.1~3.2）为周期内部编号，映射主线 Epic 11-13；阶段二 story 14-1~14-3 即主线编号；阶段三 story A.1~C.3 为内部编号，映射主线 Epic 15-17（sprint-status.yaml 用 15-x/16-x/17-x 主线编号）。

---

# 阶段一 · MCP V1 集成（内部 Epic 1-3 = 主线 Epic 11-13）

> ✅ **状态：APPROVED — tan 已批准（2026-06-20）**。按用户价值设计（非技术层）；架构已完整预设计（决策 A-H）→ 倾向少而大的 epic；FR-9 真实 server 验收为独立反馈边界。合计 **8 stories**（Epic1×5 / Epic2×1 / Epic3×2）。

## Requirements Inventory

**FR（11）**：见 `prd.md` 阶段一。**NFR（7）**：NFR-1/7 全程织入；NFR-2 零回归全程验证；NFR-3/4/5/6 主要在 Epic 1。

**Additional**：无 starter template（brownfield，沿用既有骨架）；依赖 `pyproject.toml` 增 `"mcp>=1.28,<2"`；复用 `ToolRegistry.register()`（零扩展）、AgentLoop 零改动、异常映射 `ToolError`；Settings 门控 `mcp_enabled`/`mcp_config_path`；`MCPClientManager` async ctx mgr；测试平铺 `tests/test_mcp_*.py` + Stub session；GitHub E2E 独立 `@pytest.mark.integration`。

## Epic List

| Epic（内部 / 主线） | 标题 | FRs | Stories |
|------|------|-----|---------|
| Epic 1 / 主线 11 | MCP 工具桥接（核心能力） | FR-1~8 | 1.1~1.5 |
| Epic 2 / 主线 12 | GitHub 只读验收（真实场景打通） | FR-9 | 2.1 |
| Epic 3 / 主线 13 | 安全边界与开源可用（收尾） | FR-10/11 | 3.1~3.2 |

**依赖**：Epic 1 独立可用；Epic 2、3 构建于 Epic 1 之上、彼此独立。Epic 1 内部链：`1.1 → (1.2 ∥ 1.3) → 1.4 → 1.5`（1.2/1.3 互不依赖）。

## Epic 1: MCP 工具桥接（核心能力）

**用户成果**：tan 写一份 `.mcp.json`，HeAgent 连上任意 MCP server、自动发现工具、LLM 像调内置工具一样调用外部工具。
**为何单 epic**：config/transport/发现/桥接/生命周期全触碰 `tools/mcp/` 核心文件，架构已完整预设计——按 file-churn 规则合并为单 epic。stdio+HTTP 同在 manager 内部分派（无独立 risk 边界）。

### Story 1.1: 引入 MCP 依赖与搭建 tools/mcp/ 适配层骨架

- **AC**：`pyproject.toml` dependencies 增 `"mcp>=1.28,<2"` 安装成功、`<2` 排除 v2 alpha、与既有依赖无冲突；`src/heagent/tools/mcp/__init__.py` 可导入、ruff/mypy 全绿；Settings 新增 `mcp_enabled: bool = True` 与 `mcp_config_path: str = ".mcp.json"`、`reset_settings()` 行为不变；DAG 检查无 `heagent.agent.*` 反向导入。

### Story 1.2: 声明式 .mcp.json 配置加载与环境变量插值

- **AC**：`${GITHUB_TOKEN}` 已设时插值成功、token 不出现在配置明文面、插值加载时一次性展开；`${MISSING_VAR}` 未设 → fail-fast 抛错（PAT 绝不落明文）；stdio/http 条目分别校验为 `StdioServerConfig`/`HttpServerConfig`，非法结构 Pydantic 拒绝；无 `.mcp.json` 或空 `mcpServers` → 返回空配置（纯内置模式）；`tests/test_mcp_config.py` 覆盖以上且无网络调用。

### Story 1.3: MCP 工具到 ToolSchema 的映射与结果桥接

- **AC**：`list_issues` from "github" → `ToolSchema(name="github__list_issues")`，`parameters` 直接填 `inputSchema`（passthrough）；server 名 `GitHub-MCP` → `github_mcp`（小写 + 非字母数字 → `_`）；两 server 撞前缀 → WARNING + 去重/跳过；多 `TextContent` 块用 `\n` 连接、`ImageContent`→`[image]`、`EmbeddedResource`→`[resource: uri]` 占位；`isError=True` → 抛 `ToolError`（无新建异常类）；`tests/test_mcp_mapping.py`（Stub）覆盖以上。

### Story 1.4: MCPClientManager 连接生命周期与并发发现注册

- **AC**：2 server 并发连接（`asyncio.gather(..., return_exceptions=True)`）+ 各自发现+映射+注册，全部在 `__aenter__` 返回前完成（FR-2 时序锚点）；慢/挂起 server 用 `asyncio.wait_for(_connect(entry), timeout=...)` 超时隔离、不阻塞其他 server；连接建立失败 → 工具不注入 + WARNING、其他 server + 内置工具不受影响（NFR-6）；已注册工具因断连失效 → 降级 `ToolError`→`ToolResult(is_error=True)` 不崩溃；`__aexit__` unregister 全部 MCP 工具 + `AsyncExitStack` 优雅关闭（防僵尸/env 泄漏）；静态检查无 `agent/` 导入、仅用 `ToolError`、AgentLoop 零改动、复用 `registry.register()`。

### Story 1.5: CLI 装配 MCPClientManager 生命周期到运行入口

- **AC**：`mcp_enabled=True` 且有效 `.mcp.json` → CLI 加载配置、进入 manager、MCP 工具注册可用；无 `.mcp.json` → 纯内置模式不报错；`mcp_enabled=False` → 完全跳过（门控生效）；交互 chat 退出时连接回收（无残留子进程）；全量 pytest 零回归。

## Epic 2: GitHub 只读验收（真实场景打通）

**用户成果**：tan 能对 HeAgent 说「这个 repo 有哪些 open issue」「搜一下 retry 怎么实现的」并拿到准确结果。
**为何独立**：接真实 server + 真实网络 + 真实 PAT，是端到端验证里程碑；反馈可能反推调整 Epic 1 映射。

### Story 2.1: 接官方远程 GitHub MCP server 跑通只读 E2E

- **AC**：`GITHUB_TOKEN` 已设 + `.mcp.json` 配置官方远程 GitHub server（Streamable HTTP，`Authorization: Bearer ${GITHUB_TOKEN}`）→ 只读工具被发现并 namespace 化（`github__list_issues`、`github__search_code`）；真实公开 repo 问「有哪些 open issue」→ 调 `list_issues` 返回 `ToolResult` 可断言 `number`/`title`/`state`/`url`；「搜一下 retry 怎么实现」→ 调 `search_code` 可断言 `path`；`@pytest.mark.integration` 无 token 时 skip 不进默认全绿基线；连接/鉴权失败 → 降级 `ToolError`/隔离不崩溃；V1 验收仅两类只读。

## Epic 3: 安全边界与开源可用（收尾）

**用户成果**：安全边界诚实声明 + 配置示例 + README 让开源用户能接入自己的 server。

### Story 3.1: 诚实更新安全声明覆盖 MCP 不可信边界

- **AC**：CLAUDE.md 安全声明显式声明外部 MCP server = 不可信代码、其工具输出无隔离进 LLM 上下文（prompt injection 无隔离）、须 OS 级沙箱兜底；声明 MCP 工具受同等约束、V1 `SafetyGuard` **不**扩展到 MCP（DP-4，deferred 记录）；deferred/future 项（断连 auto-unregister、SafetyGuard 扩展、Resources/Prompts、写操作）文档化。

### Story 3.2: 开源可用配置示例与接入文档

- **AC**：`.mcp.json.example` 含 GitHub 远程配置（`${GITHUB_TOKEN}` 插值、无明文密钥）+ stdio 示例；README MCP 接入章节（启用/位置/env 鉴权/沙箱警示）；CLAUDE.md 模块速查表 + DAG 更新（`tools/mcp/ → types/exceptions/registry`、无 `agent/` 反向）；私有 server URL 不强求 gitignore（用户自决）。

## FR Coverage（阶段一）

FR-1→1.4+1.1 / FR-2→1.4+1.5 / FR-3→1.4 / FR-4→1.3+1.4 / FR-5→1.3+1.4 / FR-6→1.3 / FR-7→1.2+1.5 / FR-8→1.2 / FR-9→2.1 / FR-10→3.1 / FR-11→3.1。**11/11 全覆盖**。NFR 横切：NFR-1/7 全程；NFR-2 每 story 验证；NFR-3 承重 1.4；NFR-4 1.4 超时；NFR-5 1.2/1.4；NFR-6 1.4。

---

# 阶段二 · MCP v1→v2 升级准备（主线 Epic 14）

> ✅ **状态：APPROVED（Fast path，tan 推进）**。规模小（实际实现仅 FR-1 pin + FR-2 隔离层 + FR-4 测试；FR-3/5 文档由 architecture 交付）→ 单 epic。合计 **3 stories**，线性依赖 `14-1 → 14-2 → 14-3`。

## Requirements Inventory

**FR（5）**：见 `prd.md` 阶段二。**NFR（6）**：NFR-1/5 全程；NFR-2 承重 14-2；NFR-3 由 14-3 零回归验证；NFR-4 14-2；NFR-6 14-2。

**Additional**：承接 V1 NFR-3（握手封装局部化）——扩展隔离到全部 5 调用点；隔离层形态 = Adapter 函数式收敛模块（session_api.py），非 Protocol；FR-3 等价机制 = C 过渡占位 + v2 切 A 被动；切换路径改 session_api.py 内部 + manager.py 局部，mapping.py 零改动；story 无独立 N-M 文件，直接基于本文 AC 实现（同 V1 惯例）。

## Epic List

| Epic | 标题 | FRs | Stories |
|------|------|-----|---------|
| Epic 14 | MCP v1→v2 升级准备（隔离层先行） | FR-1, FR-2, FR-4（FR-3/5 由 arch 交付） | 14.1~14.3 |

### Story 14.1: MCP SDK pin floor 提到 mcp>=1.28.1,<2

- **AC**：`pyproject.toml` floor 改为 `mcp>=1.28.1,<2` 安装成功、1.28.1 可导入、`<2` 排除 v2 alpha；既有 `tests/test_mcp_*.py` 全绿（NFR-1 零回归）。

### Story 14.2: 建 session_api.py 隔离层收敛 5 个 v2-sensitive 调用点

- **AC**：`src/heagent/tools/mcp/session_api.py` 导出 `handshake(session)` / `ping(session, timeout)`（失败 raise）/ `list_tools(session)` / `call_tool(session, name, args)` + 类型别名 `Tool`/`CallToolResult`/`TextContent`/`ImageContent`/`EmbeddedResource` + `input_schema_of(tool)` + `result_is_error(result)`（AD-1 表）；v1 实现（initialize/send_ping/list_tools/call_tool/from mcp.types/inputSchema/isError）；`manager.py` 全部经 `session_api`（不再直接调 session 方法）；`mapping.py` 类型从 `session_api` 取（不再 `from mcp.types import`）、`bridge_result` DP-4 围栏逻辑不动（NFR-3）；DAG 检查无 `agent/` 导入、无 `from .mapping import`（防循环）；全 async；`_watch` 逻辑不动仅调用点改经 `session_api.ping`；有 `logging.getLogger(__name__)`（NFR-6）。

### Story 14.3: 迁移测试基线——session_api 单测 + 零回归验证

- **AC**：`tests/test_mcp_session_api.py`（平铺，Stub session 无网络）覆盖 handshake/ping/list_tools/call_tool/input_schema_of/result_is_error；既有 `tests/test_mcp_*.py`（含 DP-4 用例）全绿；全量 pytest 零回归（四链：连接/发现/调用/断连探测）；ruff/mypy 全绿。

## FR Coverage（阶段二）

FR-1→14.1 / FR-2→14.2 / FR-3→architecture AD-3 + 切换路径（文档交付）/ FR-4→14.3 / FR-5→architecture §v2 切换路径（文档交付）。**5/5 全覆盖**。

---

# 阶段三 · MCP Client V2（内部 Epic A/B/C = 主线 Epic 15-17）

> ✅ 步骤完成（step-01~04）。**16 个 FR 全覆盖**。内部 Epic A/B/C 对应主线 Epic 15/16/17；主线 Epic 18（内置 git 工具 + path safety 集成）为同周期扩展，见注记。

## Requirements Inventory

**FR（16）**：FR-A1~A7 / FR-B1~B4 / FR-C1~C4（verbatim 自 `prd.md` 阶段三）。**NFR（7）**：NFR-1 安全/诚实立场（annotation 不可信）；NFR-2 确定性（无 LLM 参与）；NFR-3 上下文预算（Resources on-demand）；NFR-4 安全（Resources/Prompts 同等不可信围栏）；NFR-5 语义重叠披露（Prompts）；NFR-6 零回归护栏（SM-4，19 内置工具）；NFR-7 不过度审批（SM-C1）。

**Additional（AR-1~10，自 architecture 承重决策）**：
- **AR-1（AD-1）** `evaluate_tool_call(call, *, context=None, schema=None)` 增 schema kwarg；两处 evaluate 调用点传 schema；ToolCall/RunContext 不变。
- **AR-2（AD-2）** fail-safe 仅 MCP：步 0 前置闸门 `schema=None` → 跳过注解裁决回既有路径（19 内置工具零回归）。优先级：显式策略 → destructive → readOnly → fail-safe。
- **AR-3（AD-3）** annotations→verdict 纯函数不触 provider；单测覆盖三种 annotations。
- **AR-4（AD-4）** `MCPClientManager._sessions`（B/C 前置）；flag-before-pop；规范化 `ToolError("MCP server '%s' disconnected")`。
- **AR-5（AD-5）** Resources 聚合桥接工具 `mcp__list_resources`/`mcp__read_resource`（继承全量 V1 门控）；自声明 readOnlyHint=True；`read_resource(server, uri)` server 必填；无 MCP 配置不注册。
- **AR-6（AD-6）** 注入围栏提升为公共 `guard_content(text)`（bridge_result/read_resource/slash 共用）；Resources 不自动注入；Prompts 走 run_stream 不绕过。
- **AR-7（AD-7）** `_run_chat` REPL 最小 slash 分发器；推荐接入 (i) `_mcp_lifecycle` 返回 manager；渲染文本先经 guard_content；缺参数/模板不存在显式错误。
- **AR-8（AD-8）** CLAUDE.md/frame.md 安全声明更新覆盖（annotation 不可信 + 返回同等不可信）；须 OS 沙箱兜底。
- **AR-9（SM-4）** 零回归护栏（既有 V1 MCP + 19 内置工具 + annotations/桥接新单测）。
- **AR-10（Stack）** 不新增运行时依赖；Python 3.11+；Pydantic v2。

**UX**：无 UI/UX 表面（后端库 + CLI REPL slash）。

## FR Coverage Map（阶段三）

FR-A1~A7 → Epic A；FR-B1~B4 → Epic B；FR-C1~C4 → Epic C。**16/16 全覆盖**。SM-6/AR-8 安全声明拆进三 epic 各自收尾 story。

## Epic A: 写操作治理 — MCP 工具危险分级的确定性闸门

**用户成果**：agent 调 MCP 写工具时 destructive 走审批不裸跑、readOnly 静默放行、缺 annotations fail-safe 需确认——危险等级判定在代码层（纯函数可单测），19 个内置工具零回归。**完成后 V2 核心价值即达成，可独立交付**。
**实现落点**：AD-1/2/3。改 `types.py` + `tools/mcp/mapping.py` + `engine/policy.py` + `agent/tool_execution.py`。
**独立性**：✅ 无前置依赖，无 B/C 依赖。

### Story A.1: annotations 数据管线（ToolAnnotations 模型 + ToolSchema.annotations + mapping 透传）

- **AC**：`types.py` 新增 HeAgent 自有 Pydantic 模型 `ToolAnnotations`（四 hint 默认 False，**不透传** `title`，不依赖 `mcp.types`）；`ToolSchema.annotations` 缺省 None、V1 构造点零改动；`mcp_tool_to_schema` 透传（destructiveHint/readOnlyHint 对应字段为真；`tool.annotations` None → `ToolSchema.annotations` None 由 fail-safe 消费）；idempotent/openWorld 透传存储（FR-A7 存储）。

### Story A.2: PolicyEngine 注解裁决闸门（schema kwarg + 固定优先级 + fail-safe 仅 MCP）

- **AC**：`evaluate_tool_call(call, *, context=None, schema=None)`；`execute_tool_call` 裁决前 `schema = loop.registry.get_schema(call.name)` 传入，两调用点都传；destructiveHint=true 未授权 → `APPROVAL_REQUIRED`，授权后放行；readOnlyHint=true 无其他阻断 → 非 approval；显式策略 `approval_mcp_tools=True` 覆盖 readOnly 声明；MCP 缺 annotations → fail-safe `APPROVAL_REQUIRED`；内置工具 `schema=None` → 步 0 跳过注解裁决回既有路径（绝不对内置触发 fail-safe）；idempotent/openWorld 不改变 verdict。

### Story A.3: 零回归护栏 + 治理确定性验证

- **AC**：不依赖 provider 的单测断言 destructive/readOnly/缺省 → `APPROVAL_REQUIRED`/非 approval/`APPROVAL_REQUIRED`（FR-A6, SM-5）；既有 19 内置工具 + V1 MCP 测试全绿、覆盖率不降（SM-4, AR-9）；步 0 对抗测试（内置工具 `schema=None` 不因 fail-safe 变 APPROVAL_REQUIRED，除非显式 approval_tools 命中）。

### Story A.4: 安全声明更新（写操作治理）

- **AC**：CLAUDE.md 明确 `Tool.annotations` 是 server 自声明、不可信（恶意 server 可谎报 readOnlyHint）；治理闸门 defense-in-depth 非真正安全边界；须 OS 级沙箱兜底（AD-8, SM-6）；frame.md 同步。

## Epic B: Resources on-demand 发现与读取

**用户成果**：tan 问「这个 server 有哪些资源」→ agent 调 `mcp__list_resources` 拿清单 → 按需 `mcp__read_resource(server, uri)` 取回。不自动全量注入（R3 不回归），返回内容同等不可信围栏。
**实现落点**：AR-4（_sessions）+ AR-5（mcp__ 聚合桥接）+ AR-6（guard_content）。
**独立性**：✅ 自引入 `_sessions` 与 `guard_content`；Epic C 在其上构建。

### Story B.1: MCPClientManager._sessions 映射（B/C 前置 + flag-before-pop 断连语义）

- **AC**：`MCPClientManager` 新增 `self._sessions: dict[str, ClientSession]`；`_server_loop` 中 `initialize()` 成功登记 `_sessions[normalized_name]`；断连/`__aexit__` 按 flag-before-pop（先摘键再退 transport）；session 唯一属主是 `_server_loop` task，`_sessions` 只读查找表非第二属主；in-flight 桥接调用见键移除 → 规范化 `ToolError("MCP server '%s' disconnected")`（`_execute_one` 转 is_error），禁裸 KeyError/AttributeError/None。

### Story B.2: mcp__list_resources 聚合桥接工具（继承 V1 门控 + on-demand 不注入）

- **AC**：MCP 活跃时注册 `mcp__list_resources`（`mcp` 聚合 token → `_is_mcp_tool` 识别 → 继承 `block_mcp_tools`/`approval_mcp_tools`/`sandbox_mcp_tools`/`__mcp__` 授权）；自声明 `readOnlyHint=True`（默认不审批，用户可强制确认覆盖）；已连 server 暴露资源 → 返回 server-tagged 列表 `{server, uri, name, description}`；无连接/不暴露 → 空列表不抛错；无 MCP 配置不注册；system prompt 不含全量 resources 文本（on-demand, FR-B3）。

### Story B.3: mcp__read_resource 桥接工具 + guard_content 公共围栏提取

- **AC**：`mcp__read_resource(server="github", uri="repo://x/config")` 经 `self._sessions[server]` 取回资源内容经 `ToolResult` 桥接；LLM 可见签名钉死 `read_resource(server: str, uri: str)` server 必填（消解跨 server 歧义，收紧 PRD FR-B2）；server 不在 `_sessions`/URI 不存在 → `ToolError` 显式失败；`_guard_injection` 提升为公共 `guard_content(text) -> str`（`bridge_result`/`read_resource`/slash 共用单一实现）；返回内容命中注入签名 → warning 标记透传不阻断（FR-B4）；`bridge_result` 改调用 `guard_content` 后既有行为不变（回归测试）。

### Story B.4: 安全声明更新（Resources 同等不可信）

- **AC**：CLAUDE.md 明确 `mcp__read_resource` 返回内容经启发式围栏标记后透传、与内置工具返回同等不可信、须 OS 级沙箱兜底（AD-8, SM-6）；frame.md 同步。

## Epic C: Prompts CLI slash 渲染注入

**用户成果**：tan 敲 `/mcp-prompt <server> <name> [key=value ...]`，CLI 查 `list_prompts` 找到模板、渲染参数、作为 user message 注入——缺参数/模板不存在显式报错，渲染输出同等不可信。**最弱腿，预算吃紧 defer 候选**（A+B 已达成核心价值）。
**实现落点**：AR-7（slash 分发器）+ 复用 AR-4 `_sessions` + AR-6 `guard_content`。
**独立性**：✅ 依赖 Epic B 的 `_sessions` + `guard_content`。

### Story C.1: manager prompts 读取入口（经 _sessions）

- **AC**：manager 暴露 `list_prompts(server)` / `get_prompt(server, name, args)` 经 `_sessions[server]` 调 ClientSession；**不注册为 LLM 工具**（Prompts 是 user-controlled，不该 LLM 自主调）；server 有模板 → 返回清单（name/description/参数 schema）；无模板 → 空列表不抛错（FR-C1）。

### Story C.2: slash 分发器 + /mcp-prompt 渲染注入（含参数化）

- **AC**：`_run_chat` REPL 在 `input()` 与 `run_stream()` 间加最小分发器（`startswith("/")` → 查命令表，否则原样送）；推荐接入 (i) `_mcp_lifecycle` 返回 manager，`_run_chat` 经 `as` 取实例进 REPL 作用域；`/mcp-prompt github code_review file=loop.py` → 调 `get_prompt` 渲染 → 渲染文本作 user message 走 `run_stream`（复用既有循环）；缺必填参数 → 报错列出缺失参数（FR-C3）；模板不存在 → 显式错误不静默注入空内容、不中断循环。

### Story C.3: 渲染输出同等不可信围栏 + 安全声明更新

- **AC**：`get_prompt` 渲染文本注入前先经公共 `guard_content` 标记（命中注入启发式加 warning 后再注入，FR-C4）；CLAUDE.md/frame.md 覆盖 Prompts 渲染同等不可信 + 语义重叠披露（Prompts 与 context-files/自学习记忆重叠，不统一三者）（SM-6, NFR-5, AD-8）。

## FR → Story 覆盖核对（阶段三）

| FR | Story | FR | Story | FR | Story |
| --- | --- | --- | --- | --- | --- |
| FR-A1 | A.1 | FR-B1 | B.2 | FR-C1 | C.1 |
| FR-A2 | A.1 | FR-B2 | B.3 | FR-C2 | C.2 |
| FR-A3 | A.2 | FR-B3 | B.2 | FR-C3 | C.2 |
| FR-A4 | A.2 | FR-B4 | B.3 | FR-C4 | C.3 |
| FR-A5 | A.2 | | | | |
| FR-A6 | A.3（+A.2 测试） | | | | |
| FR-A7 | A.1（存储）+A.2（不裁决） | | | | |

16/16 FR 全覆盖。

---

# 注记：主线 Epic 18（内置工具扩展，git + path safety）

阶段三周期同期交付的主线 Epic 18（内部无独立 epic 文件，见 `../baseline/sprint-status.yaml` 与 `docs/frame.md`）：**内置工具扩展**——18-1 git-status-diff / 18-2 git-log-blame（git 工具，本质是 shell wrapper）/ 18-3 path-safety-integration（`resolve_under_root` 集成）/ 18-4 tests-docs。全部 `done`。

---

# 三阶段 story 状态（权威 = `../baseline/sprint-status.yaml`）

| 阶段 | 内部编号 | 主线编号 | Stories | 状态 |
|------|---------|---------|---------|------|
| 一 | Epic 1-3 | 11-13 | 1.1~1.5 / 2.1 / 3.1~3.2（8） | 全部 done |
| 二 | Epic 14 | 14 | 14.1~14.3（3） | 全部 done |
| 三 | Epic A/B/C | 15-17 | A.1~A.4 / B.1~B.3 / C.1~C.3（11） | 全部 done |
| 三扩展 | — | 18 | 18-1~18-4（4） | 全部 done |
