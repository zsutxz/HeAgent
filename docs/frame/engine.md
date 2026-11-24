# 运行时引擎（`engine/`）

> 状态：实现细节参考，自 [`framework.md`](../framework.md) **4.12** 迁出（2026-11-24 整理；编号不变，
> 其它文档里「4.12」的引用即指本页）。架构视角（项目定位 / 数据流 / 模块 DAG / 各模块职责与边界）见
> [`framework.md`](../framework.md)，安全立场（canonical）见 [§4.18](../framework.md#418-安全口径canonical)，
> 扩展页总索引见 [`frame/README.md`](README.md)。

## 4.12 运行时引擎 (`engine/`)

`EngineContainer`（DI 容器）注入 `AgentLoop`，工具执行走**策略门控**：`PolicyEngine` 裁决 → `ToolExecutor` 分发 → `SafetyGuard` 检查。子 Agent 经 `parent_run_id` 继承父 `engine`。

| 模块 | 说明 |
|------|------|
| `container.py` | `EngineContainer` — DI 容器，`default(workspace_root=)` 装配全部服务；`create_run_context` 含 FR-1 沙箱会话目录解析（根锚定 workspace_root 回退链，开关开启时写 `metadata["sandbox_workspace"]`、关闭时清除预含键，失败显性抛异常） |
| `context.py` | `RunContext`（run_id/session_id/parent_run_id/workspace_root/**state_root**/iteration/metadata）、`RunStatus`；`workspace_root` = 围栏基线，`state_root` = 运行产物落盘根（`None` 回退前者，worktree 隔离时钉容器根）；终态唯一写入口 `RunContext.mark_terminal`（Phase 2 C2：RUNNING→COMPLETED/FAILED 合法、终态再写显性失败；`touch` 是裸 setter 仅供迭代期刷新。取消路径不写终态——status 保持 RUNNING 可 resume） |
| `approval.py` | `ApprovalHandler` 协议 + `ApprovalDecision`/`ApprovalRequest` + `ConsoleApprovalHandler`/`DenyAllApprovalHandler` — 交互式审批闭环（Epic 29） |
| `tasks.py` | 后台任务进度注册表（四态 + 百分比单调 + TTL/条数淘汰；生产者侧 `TaskScope`，查询侧经入口层注入 `GET /api/tasks`；Story 64.11） | 新增 |
| `hooks.py` | `HookConfig`/`HookManager` — 用户可配置事件钩子（PreToolUse/PostToolUse/SessionStart/SessionEnd，Epic 32）；PostToolUse 的**非空 stdout 进对话上下文**（以工具结果附注形态追加，单条 ≤2000 / 单次调用累计 ≤4000 字符，超限显式截断标记；注入点在 ledger 记账之后 ⇒ 幂等缓存只存原始工具输出） |
| `policy.py` | `PolicyEngine` — 准入 allowlist/blocklist、MCP 门控、工作区路径围栏、审批/沙箱裁决 |
| `executor.py` | `ToolExecutor` — 按 verdict 分发；内部串行 `SafetyGuard.check()`；sandbox 路径默认 Passthrough，可注入后端；FR-1 会话目录经 `bind_sandbox_workspace` 送达；FR-2 后端强度档位经 `_runner_tier()` 查询并随 emit 事件 `sandbox_tier` 可观测（机制见 `docs/sandbox.md`；拆分见 §4.4 的 `tools/sandbox/` 说明） |
| `store.py` | `RunStore` — `.heagent/runs/` 运行快照（async I/O + 原子写），`build_run_tree()` 按 `parent_run_id` 聚合；`prune(retention_days=)` 按 mtime 轻量回收过期快照 + 配套 `.lock` + `<run_id>/` 产物目录（不 load Pydantic），由 `prune_runs_once()` 在全新 run 启动时触发一次 |
| `ledger.py` | `ExecutionLedger` — `.heagent/ledger/` 幂等与租约（async I/O），防 window_reset 重发 + 防并发/重入；`heartbeat()` 由在途续租原语 `renew_lease_while_active`（本模块单源；`agent/tool_execution._renew_ledger_lease` 是其工具在途缝包装）与 `LedgerAudit`（audit-only 记账，`ToolExecutor.execute(audit=...)` 的可选审计面，幂等去重禁用）调用，使「过期 RUNNING = 孤儿」成为 prune 的可靠判据 |
| `observability.py` | `EventBus`/`EngineEvent`/`LoggingObserver` — 运行时事件发布；`LoggingObserver` 经 `safe_logging.safe_log` 落日志（日志故障不改写调用方），并对 `target`/`details` 做启发式脱敏（`redact_secrets`/`redact_mapping`）；`EventBus.emit` 的观察者兜底同样走 `safe_log` |
| 其余七个模块 | `checkpoint.py` / `state_machine.py` / `story_batch.py` / `workflow_resource.py` / `workflow_runner.py` / `workflow_events.py` / `workflow_transition.py`——职责见 4.13 与对应模块页（本表不重复，避免两处漂移） |

**已完成：**

- **策略门控链**：`PolicyEngine.evaluate()` → `ToolExecutor.execute()` → `SafetyGuard.check()`，串行执行，职责分离
- **角色化 + checkpoint-resume**：supervisor 委派角色化 `SubAgent`，结构化结果写 `metadata['completed_steps']`；`window_reset` 清窗重建 + `resume`/`resume_stream` 跨窗口续跑；`build_run_tree()` 树形聚合；Schema 级工具隐藏
- **持久化健壮性**：store/ledger 全部 async I/O + 原子写 + 损坏 JSON 容错；可选跨进程文件锁（`EngineContainer(enable_file_locks=True)`）
- **日志卫生（2026-09-23）**：`pub/safe_logging` 两层防线——插桩/best-effort 路径逐调用点 `safe_log`；入口层（CLI/GUI）配置 logging 时调 `install_logging_fault_guard()`，把 `logging.Handler.handle` 包一层（失败仍走 stdlib `handleError` 诊断，但不向业务传播），故运行栈任意 `logger.*` 不再中断 run。同时 `LoggingObserver` 对 `target`/`details` 按凭证形态掩码——日志行不再出现 `API_KEY=…`/`sk-…` 原文。**残留**：宿主在守卫安装前打日志、或自行还原 `Handler.handle`（`safe_logging.ORIGINAL_HANDLER_HANDLE`）时不在此保证内。**行格式**（Epic 65）：`LOG_FORMAT=json` 时三个装配点（CLI stderr+文件 / GUI 文件 / HTTP 复用 CLI）共用 `pub/log_config.make_formatter` 的 `JsonFormatter`——单行 JSON，`extra=` 注入落 `context`、异常落 `exc_info`；默认 `text` 与历史输出逐字一致（`runtime_stats` 采集器解析两种格式：text 按行正则、json 按 `timestamp`/`logger`/`message`；text 行形状仍不得漂移） |

**已知限制：**

- **Sandbox 后端**：`execute_in_sandbox()` 默认 Passthrough 透传；`FirejailBackend` 仅隔离 shell 子进程、非完美边界（机制见 `docs/sandbox.md`）
- **安全边界**：SafetyGuard / PolicyEngine / sandbox 三层的边界地位见 §4.18。
