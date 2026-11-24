# Agent 核心（`agent/`）

> 状态：实现细节参考，自 [`framework.md`](../framework.md) **4.2** 迁出（2026-11-24 整理；编号不变，
> 其它文档里「4.2」的引用即指本页）。架构视角（项目定位 / 数据流 / 模块 DAG / 各模块职责与边界）见
> [`framework.md`](../framework.md)，安全立场（canonical）见 [§4.18](../framework.md#418-安全口径canonical)，
> 扩展页总索引见 [`frame/README.md`](README.md)。

## 4.2 Agent 核心 (`agent/`)

### loop.py — 主循环（façade）

> **Phase 2 façade 化（2026-09-21）**：`AgentLoop` 保留依赖注入装配、公共入口与同名委托；循环策略拆为 sibling 模块——`run_lifecycle.py`（状态数据类 `AgentState`/`_RunInit`/`_ResumeState` + 初始化分叉 + 非流式循环体 + 终结/检查点）、`stream_runtime.py`（流式循环体）、`resume_runtime.py`（快照重建续跑状态）、`context_runtime.py`（迭代控制/消息追加/压缩/窗口重置）、`message_ports.py`（steering/follow-up 注入 + 协作式暂停）。下表方法在 façade 上保留同名委托，实现位于对应策略模块；`AgentLoop` 与状态类的导入路径不变（策略模块运行期不反向导入 loop，仅 TYPE_CHECKING）。

| 组件 | 说明 |
|------|------|
| `AgentState` | 单次运行的可变状态（消息列表、迭代计数、结果） |
| `AgentLoop` | 核心编排器，循环调用 Provider → 执行 Tool → 直到获得文本回答 |
| `run(prompt)` | 入口方法，构建初始消息后进入循环 |
| `run_stream(prompt)` | 流式入口，逐步 yield `StreamEvent`（`text`/`tool_call`/`tool_result`/`done`）；`tool_call` 在执行前发出并带 `tool_target`（作用对象摘要），`tool_result` 带 `tool_name`/`tool_error`；命中 `tool_calls` 时回退 `send()` 重取该轮调用 |
| `resume(run_id)` | 从 `RunStore` 加载快照续跑（P3）：COMPLETED 直接返回 `final_answer`，否则用 `metadata['progress_summary']` 重建窗口续跑，同 `run_id` 跨多段 context window；内部经 `_resume` 注入 `run()` 的初始化分支 |
| `resume_stream(run_id)` | `resume` 的流式版（P5-5）：COMPLETED 产出单个携带缓存答案的 `done` 事件；否则同上重建窗口后经 `_resume` 注入 `run_stream()` 流式续跑 |
| `pause()` / `unpause()` / `is_paused` | 协作式暂停/恢复当前循环（`asyncio.Event` 实现）：`pause()` 后循环在下一轮边界挂起（进行中的 LLM 调用跑完），`unpause()` 从挂起点原地继续；`is_paused` 反映请求态。每次 run 结束（完成/失败/取消）在 `_persist_and_cache` 自动复位，不泄漏到下一次 run |
| `_build_system()` | 构建系统提示词（含人格/上下文/技能/记忆注入，见下方注入顺序） |
| `_call_provider()` | 通过 Middleware 链调用 Provider，含 Token 估算对比 |
| `_execute_tools()` | `asyncio.gather()` 并行执行所有 tool_calls |
| `_execute_one()` | `ExecutionLedger.acquire()` 幂等/租约（key=`run_id:call.id`；COMPLETED 短路返回缓存，但**命中仍复核 policy**——若已收紧为 `BLOCKED` 则 bypass 缓存走正常链路，防策略变更后泄漏旧结果；lease-active 即 RUNNING 未过期则跳过执行、返回 `is_error` skip 提示防并发/重入）→ **在途期间后台续租**（`_renew_ledger_lease`，工具可跑数分钟，固定租约会让记录被 prune 误判为孤儿删除）→ `PolicyEngine.evaluate()` → `ToolExecutor` 分发（内部 `SafetyGuard.check()`）→ handler → `ledger.complete()`/`fail()` 回写（**回写失败只记 warning，不改写工具结果**；成功路径带 `recreate_if_missing=True`，记录被清则**重建为 COMPLETED** 以保住幂等缓存）；防 window_reset 后模型重发相同 `tool_call.id`（P4，见 4.12） |
| `last_usage` | 最近一次 `run()` 的累计 `TokenUsage` |
| `last_iteration` | 最近一次 `run()`/`run_stream()` 的迭代次数 |
| `last_run_context` | 最近一次 `run()` 的 `RunContext`（run_id / 迭代 / 审批·沙箱授权元数据） |
| `active_tool` | **在途**工具批次摘要（如 `file_read → src/a.py`；多调用带 `(+N)`），由 `activity_label` 拼接：批次执行期间非空、结束或取消即清空，run 开始（含 `resume`）即重置——状态栏 `🔧 …` 段据此显示「卡在哪个工具」 |
| `tool_activity` | 本次 run 的**调用尝试**活动标签（每次调用一条，run 开始即重置，`resume` 路径同样重置）——执行前登记，被阻止 / 命中 ledger 缓存的调用同样留痕；单次模式跑完由 `cli.display.show_tool_activity` 回显 |

**`AgentLoop.__init__()` 参数：**

| 参数 | 类型 | 说明 |
|------|------|------|
| `provider` | `BaseProvider` | LLM 提供者（必需） |
| `registry` | `ToolRegistry` | 工具注册中心（默认全局单例） |
| `guard` | `SafetyGuard` | 安全防护（默认黑名单模式） |
| `middlewares` | `list[MiddlewareFn]` | 中间件链 |
| `max_iterations` | `int` | 最大迭代次数 |
| `skills` | `SkillStore` | 技能存储（激活技能工具） |
| `facts` | `FactStore` | 事实记忆（激活记忆工具） |
| `profile` | `ProfileStore` | 用户画像（激活画像工具） |
| `session` | `SessionStore` | 会话持久化 |
| `compressor` | `ContextCompressor` | 上下文压缩器（原位摘要，见 4.5） |
| `window_reset` | `WindowResetConfig` | 上下文窗口重置配置（token≥阈值清窗重建 + resume，与 `compressor` **互斥**，见 4.5；P3） |
| `context_dir` | `str` | 上下文文件扫描目录 |
| `soul` | `SoulStore` | 人格加载器 |
| `cron_store` | `JobStore` | Cron 任务存储（激活 Cron 工具） |
| `engine` | `EngineContainer` | 运行时治理容器（policy/executor/store/ledger/events），默认 `EngineContainer.default()`，见 4.12 |
| `run_context` | `RunContext` | 预置的单次运行上下文（一次性，用后清空） |

**系统提示词注入顺序（`_build_system()`）：**

```
1. <identity>        — SOUL.md 人格（最顶层，insert(0) 插到最前）
2. 用户 system 字符串
3. <project-context> — 上下文文件（CONTEXT.md > AGENTS.md > CLAUDE.md）
4. <memory>          — 事实记忆
5. <memory-nudge>    — 记忆保存提醒
6. <profile>         — 用户画像
7. <shell-workspace> — 本 run 的 shell 沙箱工作目录（E40-D2；仅真正生效时注入）
8. <skills>          — 自动匹配的技能
```

稳定前缀原则（2026-10-29）：1-6 是跨 run 稳定块，7-8 是 per-run（沙箱路径）/ per-prompt（技能匹配）
易变块。自动前缀缓存（deepseek/openai 等）按字节匹配、从第一个分叉字节起失效，易变块必须整体排在
稳定块之后，否则排在其后的 memory 等稳定内容每次新 run 都吃全价输入。

### middleware.py — 中间件管道

```python
# 类型定义
MiddlewareFn = Callable[[Request, NextFn], Any]

# 组合函数：递归构建中间件链
compose(middlewares, handler) -> NextFn

# 工厂函数：创建重试中间件
make_retry_middleware(max_attempts, base_delay, max_delay) -> MiddlewareFn
```

每个中间件接收 `(Request, NextFn)`，可拦截、修改或短路请求/响应。

### sub.py — 子 Agent

| 组件 | 说明 |
|------|------|
| `SubAgent` | 隔离的 Agent 实例，独立的 Loop + Context；经 `parent_run_id` 继承父 `engine`；可带 `role`（`RoleSpec`：system/allowed_tools/blocked_tools）/`system`/`allowed_tools` 角色化（P1） |
| `SubAgentResult` | 子任务结果（task, output, success, iterations, **run_id**：子 agent 自身 run_id，P5-3 供结构化结果与树形聚合） |
| `run_parallel()` | `asyncio.gather()` 并行运行多个子 Agent |
| `build_subagent_delegates()` | `agent/delegation.py`：为 tools 层组装单任务/并行委派回调（`DelegateOne`/`DelegateMany`），把 `SubAgentResult` 映射为工具层 `SubTaskOutcome`；`AgentLoop._runtime_scope` 每次 run 绑定、退出解绑；`depth` 入参 +1 写入子 Agent（递归深度闸门输入） |

子 Agent 默认带 `ContextCompressor`（短任务走原位压缩），可经 `window_reset` 参数启用跨窗口续跑（长任务场景，P5-2 已交付）。角色化时由父 `engine` 经 `dataclasses.replace` 换角色专属 `PolicyEngine`（allowed_tools/blocked_tools），其余运行时服务（store/ledger/events）复用。
