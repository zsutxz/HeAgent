# 事件契约（`events/`）

> 状态：实现细节参考，自 [`framework.md`](../framework.md) **4.15 / 4.12 事件传输** 迁出（2026-11-24 整理；编号不变，
> 其它文档里「4.15」的引用即指本页）。架构视角（项目定位 / 数据流 / 模块 DAG / 各模块职责与边界）见
> [`framework.md`](../framework.md)，安全立场（canonical）见 [§4.18](../framework.md#418-安全口径canonical)，
> 扩展页总索引见 [`frame/README.md`](README.md)。

## 4.15 事件契约 (`events/`)

机器可读运行事件（JSONL）的对外契约。`RunEvent` 顶层 **11 字段**由黄金测试
（`tests/test_events_jsonl.py::_EXPECTED_FIELDS`）锁死、`SCHEMA_VERSION="2"`（v2，2026-09-22
Phase 5 C1：+`duration_ms`/`error_kind`；旧 rollout 缺省读、新字段被旧码 `extra=ignore`）。
`kind` 是开集（`KNOWN_KINDS` 仅文档/黄金测试依据，不过滤）。

| 字段 | 语义 |
| --- | --- |
| `schema_version` / `seq` / `ts` / `run_id` / `iteration` | 协议版本、sink 内单调序号、秒精度 ISO 时间、run/迭代关联 |
| `kind` / `tool` / `target` | 事件名（引擎事件名同形）/ 工具名 / 作用对象摘要 |
| `duration_ms` | 耗时（整数毫秒，`perf_counter` 源头测量）；0=未计时 |
| `error_kind` | 失败分类（封闭映射：`timeout`/`cancelled`/`policy_denied`/`safety_blocked`/`tool_error`/`exception` 兜底；映射单点 `protocol.error_kind_for`） |
| `details` | 自由扩展 dict（与工具返回同等不可信） |

逐 kind 发射点与 details 约定（发射点把 `duration_ms`/`error_kind` 放 `EngineEvent.details`，
由 `from_engine_event` 提升到顶层并摘除——EngineEvent 模型与 GUI 消费面不动）：

| kind | 发射点 | details 关键键 | duration/error_kind |
| --- | --- | --- | --- |
| `run_started` / `run_paused` / `run_resumed` | `agent/run_lifecycle.py` | `stream`/`session_id`/`resume`/委派键 | — |
| `run_completed` | `run_lifecycle.finish_run` | `answer_length` | duration（run 全程） |
| `run_failed` | `run_lifecycle.on_run_failed` | `error` | duration（缺省由 `run_elapsed_ms(loop)` 现算——facade `_on_run_failed` 路径 2026-09-23 前恒 0）+ error_kind |
| `iteration_started` | `agent/context_runtime.py` | — | — |
| `provider_call_started` / `provider_call_completed` | `agent/loop.py` | `message_count,estimated_tokens` / `model,finish_reason,actual_tokens` | completed 带 duration（中间件链整体） |
| `tool_call_started` / `tool_call_completed` / `tool_call_failed` / `tool_call_blocked` | `engine/executor.py`（`_emit_tool_event` 单点） | `mode`（+sandbox_profile/tier）/`content_length`/`error`/`reason` | completed/failed 带 duration；failed 带 error_kind |
| `context_compressed` / `window_reset` | `agent/context_runtime.py` | `before,after` | — |
| `workflow_step_started` / `workflow_step_completed` / `workflow_step_failed` | `engine/workflow_runner`（`emit` 注入端口，缺省 None=不发） | `step,story`（+`result`/`error`） | 三种带 duration；failed 带 error_kind。串行逐条各发一组（`story` 非空）；声明门控并行批（Epic 52）= 单组形状：`started` 一条（story=批首成员）+ 批收口一条（story 空），逐成员归因走 `workflow_story_batch_scheduled` |
| `workflow_story_batch_scheduled` | `engine/workflow_runner`（`_gather_story_batch`，Epic 52 Story 52-2） | `step,members,limit`（`story` 为空） | 授权批派发时发一条：批成员 id 与声明上限 |
| `workflow_write_audit` | `goal/write_audit.py`（`_emit_write_audit_event`，Epic 52 Story 52-3；2026-11-07 随写审计家族自 `cli/goal.py` 迁入） | `step,story,untracked` / `skipped` / `violations,base,shared_workspace` | 宿主 Git 写集审计的观测事件：`untracked=[...]` 为警告（不判负）；`skipped=git_unavailable` 为非 Git 跳过说明；`violations=[...]` + `base`（基线 revision）+ `shared_workspace` 为**判负留档**（闩后串行重跑的新基线已含旧违规，事件是唯一持久记录；`shared_workspace=true` 表示批内写者无法归属到本 Story，A41/A42）；emit 异常隔离 |
| `workflow_approved` / `workflow_rejected` / `workflow_amended` | `engine/workflow_runner`（审批决策方法，Story 51-5） | `step`（+`reason`：拒绝理由 / 修订补充） | — |
| `workflow_gate_evaluated` | `cli/goal/verify.py`（`_emit_goal_gate_event`，Story 51-8 收口 51-4 递延） | `step,story,source,verdict,failed,clause_errors,rerun,rerun_evidence,reused_commands` | 完成门（`source=completion_gate`）与 `/goal verify`（`source=verify_run`）每次结构化求值各发一条，带 duration；emit 异常隔离 |
| `dream_start` / `dream_end`、`cron_job_*` | `memory/dream.py`、`cron/scheduler.py`（开集现状收编） | `success` 等 | — |
| `assistant_message`（传输层补充） | `events/sink.py` | `content` | — |

**持久化影响**：rollout 落盘 `<rollout_dir>/<run_id>/rollout.jsonl`（逐事件 append+close，
crash 前缀可回放）；`heagent replay` 人读渲染有值时追加 `[Nms]` / `error_kind=`；
黄金测试改字段须 bump `SCHEMA_VERSION` 并同步 `_EXPECTED_FIELDS`。
workflow 事件经 `goal/application.advance(emit=...)` 透传、`cli.goal._workflow_event_emitter`
绑 `EngineContainer.events` 总线；emit 异常隔离（warning，不改变业务控制流）。

**事件域分型与分发语义（2026-11-06，dsh 对标采纳）**：HeAgent 事件分**两域一约定**——
- **运行事实域**（持久）：`RunEvent` JSONL（本节前两表）——`rollout.jsonl` append-only、crash 前缀可回放；只在挂了 sink 的入口存在（`EVENTS_ROLLOUT_ENABLED` / `--json`；交互 REPL 默认不挂 ⇒ 57-4 口径：交互模式的观察只能走 EventBus 直订阅）。
- **进程观察域**（易失）：`EventBus`（`engine/observability.py`）同步按序派发给观察者、有界保留最近 200 条（`retain`）；不落盘、不回放，丢失即丢失（缓冲窗口内 `recent_events` 可查）。
- **消费隔离约定**：EventBus 观察者异常逐个捕获记录（不影响其他观察者、不向发布方传播）；workflow `emit` 注入端口异常隔离同口径（warning，不改业务控制流）。
分发词汇：**观察**（EventBus 订阅，改不了流）/ **拦截**（agent middleware，不在 events/ 域）/ **扇出**（同步扇出、独立异常域）。事件无 nack/重投/补偿——持久域靠 append-only 回放，观察域以有界缓冲为界。

---

### 事件传输：JSONL / rollout（`events/`）

对外的**机器可读契约**（对齐 Codex 的 `--json` 事件流）。事件源仍是引擎事件总线（`observability.py`），
`events/` 只做「映射 + 序列化 + 落盘」，**不重复插桩**：

| 入口 | 说明 |
|------|------|
| `RunEvent` / `SCHEMA_VERSION` | 单条事件（`seq` 单调递增 / `ts` / `run_id` / `iteration` / `kind` / `tool` / `target` / `details`）；字段集由 `schema_version` 锚定，改字段须 bump 版本并更新黄金测试 |
| `from_engine_event()` | `EngineEvent` → `RunEvent`；**开集** `kind`（沿用引擎事件名，引擎新增事件无需改协议）；`KNOWN_KINDS` 仅作文档与测试依据，**不作**过滤 |
| `JsonlSink` | 观察者：写 stdout（`--json`）与/或 `<cwd>/.heagent/runs/<run_id>/rollout.jsonl`（`EVENTS_ROLLOUT_ENABLED`，默认关闭）。`handle` 由总线**同步**派发，故只做「序列化 + 一次 write/flush」，不压缩不轮转；写盘失败仅告警，不打断 run；每 run 一个文件 ⇒ 单写者，无需跨进程锁 |
| `assistant_message` | 传输层补充的**唯一**非引擎事件：CLI 在 run 结束后交回最终答案（引擎侧无对应事件） |
| `read_rollout()` / `render_event()` | 读回 JSONL（坏行跳过并告警——crash 截断的尾行不毁整次回放）/ 渲染人读单行 |

**CLI 契约**：`heagent run "…" --json` 时 **stdout 只出 JSONL**（`run_started` 开头、`run_completed`/`run_failed` 收尾、`assistant_message` 交回答案），横幅 / 用量 / 活动回顾等人读信息一律走 stderr，故可直接管道消费；`heagent replay <file> [--json]` 回放。两个动作**互不隐式耦合**：`--json` 不落盘（可自行重定向），落盘不要求输出到 stdout。

**订阅点**：单次模式与**交互 REPL** 都在引擎构造后经同一个 `cli/composition.py::_build_event_sink` 订阅——`--json` 只决定 stdout 流，`EVENTS_ROLLOUT_ENABLED` 只决定落盘；长驻 REPL 每轮 run 落一个分片（sink 逐事件 open/close，不持有常驻句柄）。REPL 没有 `--json`，故其 sink 恒不含 stdout 流（活动台账 A44，2026-11-02 闭合）。**网页入口**（`cli/http_console.HttpAgentHandler`）同样在构造时订阅，且 `root=` 传**项目根**——多项目控制台下进程 cwd 不等于项目根，按 cwd 落盘会把 A 项目事件写进 B 项目；此前 handler 自建 engine 却从不订阅 ⇒ 该开关在网页入口曾是死键（活动台账 A35 前置缺口，2026-11-05 闭合，判据 `tests/test_http_events_rollout.py`）。

**不可信性**：JSONL 的 `target` / `details` 携带命令与工具原始输出（含 MCP / 远端内容），与工具返回**同等不可信**，不得因「结构化」提升信任；rollout 属项目内部状态（`.heagent/` 已 gitignore，path_safety 亦设内部状态读拒），不得改写到可提交路径。
