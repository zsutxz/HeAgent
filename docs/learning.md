# HeAgent 项目架构学习笔记

> 本文是对 HeAgent 项目架构的浓缩总结，适合初次接触时快速理解整体设计。

---

## 一、项目定位

**HeAgent** 是一个**自学习 AI Agent 框架**——单进程异步 Python 库，编排 LLM ↔ 工具执行循环。

- 非 HTTP 服务，而是 CLI / Python API
- 面向学习、实验和原型验证，**不是已加固的生产代理**
- 全部 I/O 为 `async/await`，CLI 通过 `asyncio.run()` 桥接

---

## 二、模块依赖关系（DAG）

```
exceptions  types  config
    ↑          ↑       ↑
    └─ providers ─┴── tools ─┴── context ── engine ── agent
                            ↑              ↑
                        memory ───── cron ──┘
```

**依赖规则：**
- `agent/` = 顶层编排器，依赖所有其他模块
- `providers/` 和 `tools/` 互不依赖
- `exceptions.py` 和 `types.py` 是叶子模块，无内部依赖
- `engine/` = 运行时治理层，依赖 `types`/`exceptions`/`tools.safety`；被 `agent/` 依赖
- 新增 Provider 或 Tool **禁止**从 `agent/` 导入

---

## 三、模块一句话清单

| 模块 | 一句话 |
|------|--------|
| `agent/` | 顶层编排：`AgentLoop` 主循环 + `middleware` 管道 + `SubAgent` 子 Agent |
| `providers/` | LLM Provider 层：OpenAI/Anthropic + 三层容错（重试→密钥轮换→跨 Provider 回退） |
| `tools/` | 工具系统：`@tool` 注册 + `SafetyGuard` + `path_safety` + 19 个内置工具 + MCP 桥接 |
| `engine/` | 运行时治理：`PolicyEngine` 准入/审批/沙箱裁决 + `ToolExecutor` 分发 + `RunStore`/`ExecutionLedger` |
| `context/` | 上下文管理：文件扫描加载 + Token 估算 + 压缩/窗口重置 + 会话持久化 |
| `memory/` | 自学习闭环：技能(`skills`) + 事实(`facts`) + 画像(`profile`) + 人格(`soul`) |
| `cron/` | 后台定时调度：cron 表达式解析 + 到期执行 |
| `config.py` | pydantic-settings 加载 `.env` + 环境变量 |
| `types.py` | 共享 Pydantic 模型——跨模块数据只用模型，禁止原始 dict |
| `exceptions.py` | `HeAgentError` → `ProviderError`/`ToolError`/`SafetyViolation`/`BudgetExceeded`/`PolicyViolation` |

---

## 四、核心数据流

```
用户输入 → CLI → AgentLoop.run(prompt)
  │
  ├── _build_system() → 注入顺序：
  │    1. <identity>       — SOUL.md 人格
  │    2. 用户 system 字符串
  │    3. <project-context> — 上下文文件
  │    4. <skills>          — 自动匹配技能
  │    5. <memory>          — 事实记忆
  │    6. <memory-nudge>    — 记忆保存提醒
  │    7. <profile>         — 用户画像
  │
  └── 循环开始：
      Provider.send() → 有 tool_calls?
        ├── 否 → 返回文本答案（循环结束）
        └── 是 → _execute_tools() 并行执行：
              └── _execute_one() per call:
                   1. ExecutionLedger.acquire()    — 幂等/租约检查
                   2. PolicyEngine.evaluate()      — 准入/审批/沙箱裁决
                   3. ToolExecutor.execute()       — 按 verdict 分发
                    │    └── SafetyGuard.check()   — shell 命令黑名单
                   4. handler(**arguments)         — 执行
                   5. ledger.complete()/fail()     — 回写结果
                   6. ToolResult → 追加消息 → 回到循环顶部
```

**流式路径**：`run_stream()` 经 `provider.stream()` 逐块 yield `StreamEvent`，命中 tool_calls 时回退 `send()` 重取该轮调用。

**窗口重置**：Token ≥ 阈值时清窗重建（进度摘要 + 原始 task + 续跑提示），`resume(run_id)` 同 ID 跨多段续跑。

---

## 五、模块详解

### 5.1 agent/ — 顶层编排

| 文件 | 关键组件 | 说明 |
|------|----------|------|
| `loop.py` | `AgentLoop` | 主循环：`run()`/`run_stream()`/`resume()`/`resume_stream()` |
| | `_build_system()` | 拼接系统提示词（7 层注入） |
| | `_execute_one()` | 单工具执行链（ledger → policy → executor → guard → handler） |
| | `_runtime_scope()` | 技能/记忆/Cron/子 Agent 工具运行态绑定 |
| `middleware.py` | `compose()` + `make_retry_middleware()` | 中间件管道组合 |
| `system_prompt.py` | _build_system 拼装实现 | 各注入层的具体拼装逻辑 |
| `tool_execution.py` | _execute_one 实现 | 工具执行链实现（ledger→policy→executor） |
| `sub.py` | `SubAgent` / `run_parallel` | 隔离子 Agent + 并行委派 + 角色化 |

### 5.2 providers/ — LLM Provider（三层容错）

```
ProviderChain (外层：跨 Provider 类型回退，NON_TRANSIENT 不回退)
  └── KeyRotatingProvider (中层：同类型多 key 轮换，429/401 触发)
        └── OpenAIProvider / AnthropicProvider (内层)
              └── retry_with_backoff (内层：仅 TRANSIENT 指数退避)
```

| 文件 | 说明 |
|------|------|
| `base.py` | `BaseProvider` Protocol（send/stream/get_metadata） |
| `openai.py` | OpenAI 兼容（DeepSeek 经 base_url 接入） |
| `anthropic.py` | Anthropic + 提示词缓存（`cache_control: ephemeral`） |
| `chain.py` | `ProviderChain` 有序回退列表 |
| `key_rotation.py` | `KeyRotatingProvider` 密钥池轮换 |
| `retry.py` | 错误分类器（RATE_LIMITED/AUTH_FAILED/TRANSIENT/NON_TRANSIENT） + 指数退避 |

### 5.3 tools/ — 工具系统

**注册机制**：`@tool` 装饰器从函数签名 + docstring 自动生成 `ToolSchema`，注册到 `ToolRegistry` 单例。

**安全层**：
- `SafetyGuard` — 工具名黑名单（对所有工具生效）+ shell 命令黑/白名单（仅 shell 工具）
- `path_safety.py` — 工作区路径校验（`resolve_workspace_path` + `resolve_under_root` 单算法）
- `sandbox.py` — `CommandRunner` 抽象（PassthroughRunner / FirejailBackend）

**19 个内置工具**：

| 类别 | 工具 |
|------|------|
| 基础 (5) | `shell`, `file_read`, `file_write`, `file_search`, `content_search` |
| 技能管理 (6) | `skill_create`, `skill_update`, `skill_list`, `skill_delete`, `skill_curate`, `skill_archive` |
| 记忆管理 (2) | `fact_add`, `profile_update` |
| Cron (3) | `cron_add`, `cron_list`, `cron_remove` |
| 子 Agent (3) | `task_delegate`, `task_parallel`, `task_status` |

**MCP（tools/mcp/）**：
- `config.py` — 从 `.mcp.json` 加载 MCP server 声明（支持 `${ENV}` 插值）
- `mapping.py` — namespace 转写（`<server>__<tool>`）+ 返回内容启发式围栏标记
- `manager.py` — `MCPClientManager` 并发连接 + 发现 + 注册 + ping-watch 健康探测

### 5.4 engine/ — 运行时治理（P0 增量）

| 模块 | 说明 |
|------|------|
| `container.py` | `EngineContainer` — DI 容器，`default()` 装配全部服务 |
| `context.py` | `RunContext`（run_id/session_id/parent_run_id/iteration/metadata）|
| `policy.py` | `PolicyEngine.evaluate_tool_call()` → `PolicyVerdict`（DIRECT/APPROVAL_REQUIRED/SANDBOX_REQUIRED/BLOCKED）|
| `roles.py` | `RoleSpec` + 内置角色（planner/coder/tester/supervisor）|
| `executor.py` | `ToolExecutor.execute()` — 按 verdict 分发，内部串行 `SafetyGuard.check()` |
| `store.py` | `RunStore` — `.heagent/runs/<run_id>.json` 运行快照（async I/O）|
| `ledger.py` | `ExecutionLedger` — 幂等/租约，防重入（async I/O）|
| `persist.py` | 原子写（tmp+replace）+ 损坏 JSON 容错 |
| `observability.py` | `EventBus` / `EngineEvent` / `LoggingObserver` |

### 5.5 context/ — 上下文管理

| 组件 | 说明 |
|------|------|
| `loader.py` | 扫描 `.heagent/CONTEXT.md` > `AGENTS.md` > `CLAUDE.md` |
| `tokens.py` | CJK 感知启发式 Token 估算（无需外部依赖） |
| `compressor.py` | Token ≥ 阈值时通过 LLM 摘要旧消息（原位压缩） |
| `window_reset.py` | Token ≥ 阈值时清窗重建 + checkpoint-resume（与 compressor **互斥**） |
| `session.py` | `.heagent/sessions/<id>.json` 对话历史持久化 |

### 5.6 memory/ — 记忆系统

| 存储 | 位置 | 说明 |
|------|------|------|
| `SkillStore` | `.heagent/skills/<name>/SKILL.md` | 技能（HermesAgent 标准目录结构），匹配算法：词集重叠 ≥ threshold |
| `FactStore` | `.heagent/memory/MEMORY.md` | 事实记忆，70% 关键词重叠去重 |
| `ProfileStore` | `.heagent/user/USER.md` | 用户画像，按 section 更新 |
| `SoulStore` | `~/.heagent/SOUL.md` + `.heagent/SOUL.md` | 人格系统，两级加载（项目级覆盖全局级） |

### 5.7 cron/ — 定时调度

- `CronJob` — Pydantic 模型（id/prompt/cron 表达式/recurring）
- `JobStore` — `.heagent/cron/jobs.json` CRUD 持久化
- `CronScheduler` — asyncio 后台任务，每 `cron_tick_seconds` 检查到期任务，创建独立 AgentLoop 执行

---

## 六、关键设计决策

| 决策 | 说明 |
|------|------|
| **Pydantic 全栈** | 跨模块数据全部用 `BaseModel`，禁止原始 dict |
| **Protocol 而非抽象类** | Provider 接口用 `typing.Protocol`（结构化子类型，不强制继承） |
| **单例 ToolRegistry** | 所有工具共享一个注册中心，MCP 工具动态注册/注销 |
| **str 而非 enum 的 tool name** | 工具名用字符串，便于 MCP namespace 动态拼接 |
| **Serial 安全层** | `PolicyEngine` 先裁决 → `ToolExecutor` 内部再 `SafetyGuard.check()` — 职责分离 + 纵深防御 |
| **compressor vs window_reset 互斥** | 二选一，`AgentLoop.__init__` 断言保证 |
| **异步工具 ≠ async handler** | `@tool` 装饰器支持 `async def`，但 ToolExecutor 可同步/异步混调 |
| **MCP namespace** | 工具名带 `<server>__` 前缀防冲突，`SafetyGuard` 黑名单也以 namespace 形式覆盖 |
| **执行前拦截 + 返回后围栏** | MCP 安全两面：DP-4 第一半（工具名黑名单预校验）+ DP-4 第二半（返回内容启发式标记透传） |
| **NON_TRANSIENT 不回退** | ProviderChain 对 400/422 等客户端错误立即抛出，不浪费配额 |
| **"非真正安全边界"声明** | SafetyGuard / path_safety / engine sandbox / MCP 围栏均不是真正安全边界，须 OS 级沙箱 |

---

## 七、硬约束（违反即架构错误）

1. **新增 provider / tool 禁止从 `agent/` 导入** — `tools/mcp/` 同，仅经 `ToolRegistry` 注入
2. **`engine/` 依赖 `types`/`exceptions`/`tools.safety`**，被 `agent/` 依赖
3. **跨模块数据必须用 Pydantic 模型**，禁止原始 dict（例外：内部状态 `AgentState`/`SubAgentResult` 用 `dataclass`）
4. **工具执行链固定**：`PolicyEngine.evaluate()` → `ToolExecutor` → `SafetyGuard.check()` → handler
5. **全部异步**：库代码中不出现同步 I/O（engine store/ledger 经 `asyncio.to_thread` 包裹）
6. **禁止抛出裸 Exception**，统一用 `HeAgentError` 层级

---

## 八、目录结构速览

```
src/heagent/
├── __init__.py / __main__.py / cli.py      # 入口
├── config.py / exceptions.py / types.py     # 基础设施
│
├── agent/           # 顶层编排
│   ├── loop.py              # AgentLoop 主循环
│   ├── system_prompt.py     # 系统提示词拼装
│   ├── tool_execution.py    # 工具执行链
│   ├── middleware.py        # 中间件管道
│   └── sub.py               # 子 Agent
│
├── providers/        # LLM Provider
│   ├── base.py / openai.py / anthropic.py
│   ├── chain.py             # 跨 Provider 回退
│   ├── key_rotation.py      # 密钥池轮换
│   └── retry.py             # 错误分类+重试
│
├── tools/            # 工具系统
│   ├── decorator.py / registry.py / safety.py / path_safety.py / sandbox.py
│   ├── builtins/             # 19 个内置工具
│   │   ├── shell.py / file.py / search.py
│   │   ├── skills.py / memory.py / cron.py / subagent.py
│   └── mcp/                  # MCP 桥接
│       ├── config.py / mapping.py / manager.py
│
├── engine/           # 运行时治理
│   ├── container.py / context.py / policy.py / roles.py
│   ├── executor.py / store.py / ledger.py / persist.py / observability.py
│
├── context/          # 上下文管理
│   ├── loader.py / tokens.py / compressor.py / window_reset.py / session.py
│
├── memory/           # 记忆系统
│   ├── facts.py / skills.py / profile.py / soul.py
│
└── cron/             # 定时调度
    ├── jobs.py / scheduler.py
```

运行时数据目录 `.heagent/`：
```
.heagent/
├── skills/<name>/SKILL.md   # 技能
├── memory/MEMORY.md          # 事实记忆
├── user/USER.md              # 用户画像
├── sessions/<id>.json        # 会话历史
├── cron/jobs.json            # Cron 任务
├── runs/<run_id>.json        # 运行快照
└── ledger/<key>.json         # 执行幂等/租约
```

---

## 九、已知缺口（非安全边界 + 设计权衡）

| 缺口 | 说明 |
|------|------|
| **SafetyGuard ≠ 安全边界** | 工具名黑名单 + shell 命令检查，仅命令级护栏 |
| **path_safety ≠ 安全边界** | 工作区路径校验，纵深防御用 |
| **engine sandbox ≠ 安全边界** | `execute_in_sandbox()` 默认 Passthrough；`FirejailBackend` 仅 shell 子进程、Linux-only |
| **MCP 返回围栏 ≠ 安全边界** | 返回内容启发式扫描标记透传，非真正阻断 |
| **CLI 阻塞事件循环** | 交互模式 `input()` 阻塞 asyncio（单用户 CLI 可接受） |
| **cron 范围表达式** | V1 解析器不支持 `1-5` 等范围语法 |
| **流式 tool_calls 回退** | 多数 Provider 流式模式不返回 tool_calls，须回退 `send()` 重取 |
| **跨进程持久化** | store/ledger 无文件锁（单进程 async 下安全，多进程须避免并发写） |

---

*最后更新：2026-07-08*
*来源：代码 + `docs/frame.md`（架构权威） + `docs/design.md`（设计愿景） + `docs/iteration.md`（迭代历程）*
