---
title: 'Phase 2 AgentLoop façade 化'
type: 'refactor'
created: '2026-09-21'
status: 'done'
baseline_commit: 'a8ae5a6'
review_loop_iteration: 0
context: ['{project-root}/AGENTS.md', '{project-root}/docs/frame.md', '{project-root}/_bmad-output/implementation-artifacts/arch-optimization-cycle-plan.md']
---

<frozen-after-approval reason="用户已授权执行 Phase 2">

## Intent

问题：`agent/loop.py` 1,199 物理行，混合 run 生命周期、stream、resume、pause/steering、工具批处理、上下文重置与运行后产物；行为契约难以局部验证（test.md §2.3 P0）。

方案：按 test.md §3.3 拆分表把策略组拆为 sibling 模块函数，`AgentLoop` 收缩为 façade + 依赖注入；pause/steering/follow-up 统一为可测试的消息端口；终态收敛到唯一 reducer；GUI loop 工厂与 `cli._build_loop` 合并（Phase 1 遗留）。

## Boundaries & Constraints

始终：行为不变优先——先移动并保留兼容导出，每次只改一个边界；工具链顺序 `PolicyEngine.evaluate() → ToolExecutor → SafetyGuard.check() → handler` 不变；`AgentLoop` 公共接口 `run()/run_stream()/resume()/resume_stream()/pause()/unpause()/is_paused()` 签名与语义不变；sub.py 模块级 `from heagent.agent.loop import AgentLoop` 依赖保持可用（loop.py 不得模块级导入 sub，TYPE_CHECKING 维持现状）。

需要协商：公共方法签名变化、`AgentState`/`_ResumeState`/`_RunInit` 位置移动影响测试导入。

禁止：本阶段不改序列化格式与事件 schema（归 Phase 5）；不引入新第三方依赖；不修改 `agent/tool_execution.py` 的模块级缝（`_LEDGER_LEASE_*`/`_renew_ledger_lease` 被测试 patch，读取点必须留在原模块）；不把 `docs/test.md` 加入 Git。

## I/O & Edge-Case Matrix

| 场景 | 输入 | 预期 | 错误处理 |
| --- | --- | --- | --- |
| 兼容导入 | 既有测试/调用方 `from heagent.agent.loop import AgentLoop` | 不变；被移方法在 façade 上保留同名委托 | 禁止一次性删除旧实现 |
| 取消传播 | run 中途 task cancel / BudgetExceeded / provider 异常 | 终态由唯一 reducer 写入一次，持久化与事件顺序不变 | 不吞异常，不重复写终态 |
| 暂停/steering | pause 期间 poll steering/follow-up 注入 | 端口语义与现行为一致，端口可独立 fake 测试 | 等待可被取消 |
| 压缩/重置互斥 | compressor 与 window_reset 同传 | 构造期报错（D3 决策维持） | 显性失败 |
| 工厂合并 | CLI/GUI/cron 各入口创建 loop | 共用同一 loop 工厂，观察者/审批/生命周期差异留在入口 | 不共享可变 run 状态 |

## Code Map

- `src/heagent/agent/loop.py`（1,199 行）：拆出后 façade 预期 ≤500 行；保留 `__init__` 装配、`_runtime_scope`、`_emit`、`_ensure_run_context` 与公共入口委托。
- 新 `src/heagent/agent/run_lifecycle.py`：`_init_or_resume`/`_init_new_run`/`_finish_run`/`_persist_and_cache`/`_on_run_failed`/`_start_run_record`/`_checkpoint`——模块级函数首参 `loop: AgentLoop`（TYPE_CHECKING 导入，避免运行期环）。
- 新 `src/heagent/agent/context_runtime.py`：`_maybe_compress`/`_maybe_window_reset`/`_begin_iteration`/`_append_assistant_message`/`_append_tool_result`/`_add_usage`。
- 新 `src/heagent/agent/stream_runtime.py`：`run_stream` 流式骨架（noqa: C901 热点）。
- 新 `src/heagent/agent/resume_runtime.py`：`_build_resume_state` 及 resume 支撑；`_ResumeState`/`_RunInit`/`_delegation_details` 随迁，loop.py re-export。
- 新 `src/heagent/agent/message_ports.py`：steering/follow-up poll+inject、pause/unpause/`_wait_if_paused`——端口协议化，可注入 fake 测试。
- `src/heagent/agent/tool_execution.py`：已承担 tool_batch 主体，loop 内 `_execute_tools` 等薄委托去留以行数/清晰度为准；模块级缝不动。
- `src/heagent/cli.py` `_build_loop` + `src/heagent/gui/__init__.py`：合并为共享 loop 工厂（wiring 或 cli 内），入口差异参数化。
- 测试缝核查结论：`loop.py` 无字符串路径 patch 缝；`tool_execution` 模块级 patch 已列禁止项。

## Tasks & Acceptance

- [x] C1 模块路径拆分：run_lifecycle / context_runtime / stream_runtime / resume_runtime / message_ports 五组函数迁出，façade 保留同名委托与兼容导出；行为不变，既有 agent/streaming/window reset/session resume/steering 测试原样通过。（2026-09-21 完成：façade 1,199 → 707 行；定向测试 389 passed，见 test.md §11）
- [x] C2 状态收口：终态（COMPLETED/FAILED）只由一个 reducer 写入（`RunContext.mark_terminal`，engine/context.py）；新增状态转换契约测试 `tests/test_run_status_contract.py`（4 reducer 单元 + 3 loop 行为，取消路径语义显性钉死）。C2 完成时如实修正任务前提：`RunStatus` 仅 RUNNING/COMPLETED/FAILED 三值，cancelled/waiting_approval 终态不存在（见 Spec Change Log）；「散落布尔」枚举结果为空——pause 已是 asyncio.Event 端口（C1 迁 message_ports），展示态是 run 级重置而非布尔，布尔清理早在 P1-P5 周期完成。
- [x] C3 入口装配收口（形态调整见 Change Log）：`wiring.ensure_runtime_config`（engine 快照读回收窄单点）+ `wiring.build_cron_job_runner`（cli/gui 两处逐字镜像的 cron `_run_job` 合并，goal 分支短路 + 一次性 loop）+ GUI cron_store 统一到 CLI 语义（`cron_enabled=False` → None，cron 工具不激活——经用户批准的行为变化）+ 新增 `tests/test_wiring_loop_helpers.py`（4 例）。主 loop 工厂**未**全量合并：两入口每个旋钮均有真实产品差异（session/上下文策略/soul/retry/context_dir），参数化合并产出 17 参 + 4 布尔旗巨函，比两个显式构造点更难读。
- [ ] `docs/frame.md` 同步模块地图与调用链；`docs/test.md` 记录执行结果与遗留。

验收：Given 既有全部 agent 相关测试，When 在拆分后运行，Then 原样通过且无跳过；Given 新增状态契约测试，When 构造四终态场景，Then 每场景终态写点唯一；Given façade，When 统计行数与分支数，Then 较基线（1,199 行 / `run_stream` C901）下降且可读性不降；quality_gate 全量通过（覆盖率 ≥87%）。

## Spec Change Log

- 2026-09-21：spec 创建（draft）。拆分序遵循 test.md §3.3 原则：C1 只动模块路径，C2 再收状态模型，不并行。
- 2026-09-21：用户批准冻结并执行。入口全量门禁暴露 Phase 1 两笔欠账（sub_agent 元数据断言回归 `23ef756` 修复；cli/gui S101 assert 改显性 raise），随后 C1 完成。偏差如实记录：① façade 707 行 > 预估 500——`__init__` 装配 docstring 与留守核心方法（`_call_provider`/`_runtime_scope`/`_emit` 等）体量超预估，test.md 验收（行数/分支数下降且可读性不降）满足；② `AgentState`/`_RunInit`/`_ResumeState`/`_delegation_details` 落位 `run_lifecycle.py`（lifecycle/resume 需运行期构造，且不得反向导入 loop），loop.py 经 `__all__` 显式再导出（mypy no_implicit_reexport 与 ruff PLC0414 的交集解）；③ C1 范围内新增 run_lifecycle 依赖方向铁律并写入模块 docstring。

- 2026-09-21：C2 完成，任务前提如实修正：① `RunStatus` 仅 RUNNING/COMPLETED/FAILED 三值——spec 任务文本沿写 test.md 的「cancelled/waiting_approval 终态」在枚举中不存在；终态写点勘察确认恰好两处（finish_run/on_run_failed），已收敛到 `RunContext.mark_terminal`（engine/context.py）唯一 reducer：RUNNING→终态合法、终态再写 RuntimeError 显性失败、非终态入参 ValueError。② 「散落布尔标志」枚举为空：pause 已是 asyncio.Event 端口（C1 迁 message_ports），展示态（active_tool/tool_activity）是 run 级重置而非布尔——布尔清理在 P1-P5 周期已完成，test.md 前提基于旧文件静态阅读。③ 取消传播边界显性化：CancelledError 不被 `except Exception` 捕获、不写终态，status 保持 RUNNING 可 resume——由 `test_run_status_contract.py::test_cancelled_run_keeps_running_status` 钉死；审批等待不结束 run（阻塞在工具执行内），无独立终态。④ 新增架构契约：五个策略模块运行期禁止导入 loop façade（`test_architecture_contracts.py`，AST 全路径扫描）。⑤ 架构契约红线自检：tests patch 面未受影响（类级 `__init__` spy 与实例级 patch 均兼容）。

- 2026-09-21：C3 完成，形态相对任务文本调整并留档：任务原文「GUI 主 loop 构造并入共享工厂；差异以参数表达」在实现勘察后**否决全量合并**——通读 cli `_build_loop` 与 `gui_main` 后确认两入口在每个旋钮上都是真实产品差异（CLI 有 session/上下文策略/soul/retry 中间件/cwd 锚定，GUI 均无；cron 调度器门条件也不同），参数化合并 = 17 参 + 4 布尔旗巨函，违背验收「不以牺牲可读性为目标」。落地为三缝收口：① `wiring.ensure_runtime_config`（读回收窄单点，替换两入口的重复三分支）；② `wiring.build_cron_job_runner`（两处逐字镜像的 `_run_job` 合并——GUI 注释自认「镜像 cli.py」，正是漂移温床；goal 分支短路 + 一次性 loop 语义逐字保留）；③ GUI `job_store` 从无条件创建改为 `cron_enabled` 门控（**经用户批准的装配漂移修正**：cron 关闭时 GUI 不再激活 cron 工具，与 CLI 一致），scheduler 门随之加 `job_store is not None`。新增 `tests/test_wiring_loop_helpers.py`（ensure_runtime_config 两态 + runner goal/普通双分支）。验收「架构契约测试维持」由 C2 的策略模块环依赖契约一并覆盖。

## Design Notes

迁移函数首参显式传 `loop`，跨模块私有访问限于 agent 包内；mixin 方案因 self 类型联动与 mypy 复杂度弃用。`AgentState`/`_ResumeState`/`_RunInit` 保持 dataclass 例外惯例。消息端口先以最小协议抽取（poll/inject 各一），不引入事件总线等新抽象——那是「每次只改一个边界」的越界。

## Verification

- `python -m pytest tests/test_agent_loop.py tests/test_streaming.py tests/test_window_reset.py tests/test_steering_followup.py tests/test_plan_mode.py tests/test_agent_delegation.py tests/test_sub_agent.py tests/test_subagent_budget.py tests/test_subagent_role.py tests/test_approval.py tests/test_hooks.py tests/test_events_jsonl.py tests/test_architecture_contracts.py -q`
- `python scripts/quality_gate.py` 全量。
- `ruff check src tests scripts`、`ruff format --check src tests`、`mypy src`。

## 执行记录（自 docs/test.md 迁入，2026-09-22 归档）

### Phase 2 执行记录（已完成）

spec：`_bmad-output/implementation-artifacts/phase2-loop-facade.md`。基线提交 `a8ae5a6`。

### 入口全量门禁（2026-09-21）

Phase 1 遗留的「下阶段入口先跑一次全量」执行，抓到两笔欠账并修复：

1. `test_sub_agent.py::test_role_metadata_is_observable_and_caller_metadata_wins` 失败——Phase 1 在 `engine.create_context` 写入 `sandbox_decision` 治理键后，该测试 metadata 全量相等断言被打破（定向组 glob `subagent_*` 未覆盖 `test_sub_agent.py`）。按「测试验证意图」改为按键断言，注明基础设施键不属于角色/调用方契约。提交 `23ef756`。
2. `ruff check` S101 两处——Phase 1 提交 `ca81123` 在 `cli.py:206`、`gui/__init__.py:68` 用 `assert` 收窄 `engine.runtime_config` 类型；上一会话「ruff check 通过」申报对这两行不准确。改为 `if resolved is None: raise RuntimeError(...)`（显性失败 + `pragma: no cover`），mypy 收窄语义不变。

修复后全量门禁：2024 passed、9 skipped、14 deselected，覆盖率 91.02%；ruff/format/mypy 通过（详见本轮提交记录）。

### C1 模块路径拆分（已完成）

`agent/loop.py` 1,199 → 707 行（façade：装配 + 公共入口委托 + 留守核心方法），策略迁出五个 sibling 模块：

| 新模块 | 行数 | 承载 |
| --- | --- | --- |
| `agent/run_lifecycle.py` | 387 | 状态数据类（AgentState/_RunInit/_ResumeState）+ `_delegation_details` + 初始化分叉 + 非流式循环体 `execute_run` + 终结/失败收尾 + run_store 检查点 |
| `agent/stream_runtime.py` | 172 | 流式循环体 `stream_run`（noqa: C901 随迁） |
| `agent/context_runtime.py` | 150 | 迭代控制/消息追加/add_usage/压缩/窗口重置 |
| `agent/message_ports.py` | 118 | steering/follow-up poll+inject + pause/unpause/wait_if_paused |
| `agent/resume_runtime.py` | 49 | `build_resume_state` 快照重建 |

关键落位决策：状态数据类在 `run_lifecycle.py`（lifecycle/resume 需运行期构造且不得反向导入 loop）；loop.py 以 `__all__` 显式再导出（mypy `no_implicit_reexport` × ruff `PLC0414` 交集解）；`_delegation_details` 测试导入路径经 re-export 保持。所有迁移函数以 `loop` 为首参（TYPE_CHECKING 引用 AgentLoop），策略模块运行期不导入 loop。

### C1 验证

| 检查 | 结果 |
| --- | --- |
| 定向第一批（agent_loop / streaming / window_reset / steering_followup / plan_mode） | 90 passed |
| 定向第二批（delegation / sub_agent×3 / approval / hooks / events_jsonl / runtime_config / architecture_contracts / engine_p0 / call_summary / dream / run_store_prune / gui_goal / compressor） | 299 passed, 1 skipped（textual 守卫） |
| `ruff check src tests scripts` / `ruff format` | 通过 |
| `mypy src` | 118 文件通过 |
| `scripts/quality_gate.py` 全量 | 待 C1 提交后执行（见下） |

### C2 状态收口（已完成）

- `RunContext.mark_terminal`（`engine/context.py`）：终态唯一 reducer——RUNNING→COMPLETED/FAILED 合法；终态再写 `RuntimeError`（显性失败，不静默覆盖）；非终态入参 `ValueError`。`touch` 保持裸 setter 供迭代期刷新；src 内 `touch(status=` 现仅剩 reducer 内部一处。
- `run_lifecycle.py` 的 `finish_run`/`on_run_failed` 改经 reducer 写终态（替换原两处 `touch(status=...)`）。
- 新增 `tests/test_run_status_contract.py`：4 个 reducer 单元契约 + 3 个真实 loop 行为契约（成功恰一次 COMPLETED / 失败恰一次 FAILED / 取消不写终态且 status 保持 RUNNING 可 resume——现状语义显性钉死）。
- 新增架构契约 `test_architecture_contracts.py::test_loop_strategy_modules_do_not_runtime_import_loop_facade`：五个策略模块运行期禁止导入 loop façade（AST 按完整模块路径扫描；包级规则表粒度不够，单列）。
- 任务前提修正（详见 spec Change Log）：`RunStatus` 无 cancelled/waiting_approval；「散落布尔」枚举为空（pause 已是 Event 端口、展示态是 run 级重置）。

### C3 入口装配收口（已完成，形态调整）

spec 任务原文「GUI 主 loop 工厂并入共享工厂」实现勘察后**否决全量合并**（17 参 + 4 布尔旗巨函，见 spec Change Log），改为三缝收口：

- `wiring.ensure_runtime_config(engine)`：engine 快照读回收窄单点，替换 cli/gui 两处重复的 None 守卫三分支。
- `wiring.build_cron_job_runner(...)`：cli `_build_loop._run_job` 与 `gui_main._run_job`（GUI 注释自认「镜像 cli.py」）的逐字合并——goal 分支短路 `_goal_cron_advance`、普通 prompt 一次性 loop，参数透传（CLI 传 soul/compressor/window_reset/cwd，GUI 不传）。
- **GUI cron_store 统一到 CLI 语义（行为变化，用户批准）**：`job_store = JobStore() if config.cron_enabled else None`——cron 关闭时 GUI 不再激活 cron 工具（此前无条件创建属装配漂移：工具可见但无调度器驱动）；scheduler 门随之加 `job_store is not None`。
- 新增 `tests/test_wiring_loop_helpers.py`（4 例：ensure_runtime_config 两态、runner goal/普通双分支）。
- cli.py 顶部 `cli_goal` 导入收窄为 `_goal_runner`（goal cron 函数改由 wiring 惰性导入，规避 wiring↔cli_goal 模块级环）。

### 待办（本阶段后续）

- [x] C2 状态收口：终态唯一 reducer + 状态转换契约测试。
- [x] C3 入口装配收口：ensure_runtime_config + build_cron_job_runner + GUI cron_store 统一。
- [x] 架构契约测试扩展：断言策略模块运行期禁止导入 `heagent.agent.loop`。
