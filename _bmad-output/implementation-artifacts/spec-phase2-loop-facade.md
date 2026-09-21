---
title: 'Phase 2 AgentLoop façade 化'
type: 'refactor'
created: '2026-09-21'
status: 'draft'
baseline_commit: 'a8ae5a6'
review_loop_iteration: 0
context: ['{project-root}/AGENTS.md', '{project-root}/docs/frame.md', '{project-root}/docs/test.md']
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
- [ ] C3 入口工厂合并：GUI 主 loop 构造并入共享工厂；CLI/GUI/cron 差异以参数表达；架构契约测试维持。
- [ ] `docs/frame.md` 同步模块地图与调用链；`docs/test.md` 记录执行结果与遗留。

验收：Given 既有全部 agent 相关测试，When 在拆分后运行，Then 原样通过且无跳过；Given 新增状态契约测试，When 构造四终态场景，Then 每场景终态写点唯一；Given façade，When 统计行数与分支数，Then 较基线（1,199 行 / `run_stream` C901）下降且可读性不降；quality_gate 全量通过（覆盖率 ≥87%）。

## Spec Change Log

- 2026-09-21：spec 创建（draft）。拆分序遵循 test.md §3.3 原则：C1 只动模块路径，C2 再收状态模型，不并行。
- 2026-09-21：用户批准冻结并执行。入口全量门禁暴露 Phase 1 两笔欠账（sub_agent 元数据断言回归 `23ef756` 修复；cli/gui S101 assert 改显性 raise），随后 C1 完成。偏差如实记录：① façade 707 行 > 预估 500——`__init__` 装配 docstring 与留守核心方法（`_call_provider`/`_runtime_scope`/`_emit` 等）体量超预估，test.md 验收（行数/分支数下降且可读性不降）满足；② `AgentState`/`_RunInit`/`_ResumeState`/`_delegation_details` 落位 `run_lifecycle.py`（lifecycle/resume 需运行期构造，且不得反向导入 loop），loop.py 经 `__all__` 显式再导出（mypy no_implicit_reexport 与 ruff PLC0414 的交集解）；③ C1 范围内新增 run_lifecycle 依赖方向铁律并写入模块 docstring。

- 2026-09-21：C2 完成，任务前提如实修正：① `RunStatus` 仅 RUNNING/COMPLETED/FAILED 三值——spec 任务文本沿写 test.md 的「cancelled/waiting_approval 终态」在枚举中不存在；终态写点勘察确认恰好两处（finish_run/on_run_failed），已收敛到 `RunContext.mark_terminal`（engine/context.py）唯一 reducer：RUNNING→终态合法、终态再写 RuntimeError 显性失败、非终态入参 ValueError。② 「散落布尔标志」枚举为空：pause 已是 asyncio.Event 端口（C1 迁 message_ports），展示态（active_tool/tool_activity）是 run 级重置而非布尔——布尔清理在 P1-P5 周期已完成，test.md 前提基于旧文件静态阅读。③ 取消传播边界显性化：CancelledError 不被 `except Exception` 捕获、不写终态，status 保持 RUNNING 可 resume——由 `test_run_status_contract.py::test_cancelled_run_keeps_running_status` 钉死；审批等待不结束 run（阻塞在工具执行内），无独立终态。④ 新增架构契约：五个策略模块运行期禁止导入 loop façade（`test_architecture_contracts.py`，AST 全路径扫描）。⑤ 架构契约红线自检：tests patch 面未受影响（类级 `__init__` spy 与实例级 patch 均兼容）。

## Design Notes

迁移函数首参显式传 `loop`，跨模块私有访问限于 agent 包内；mixin 方案因 self 类型联动与 mypy 复杂度弃用。`AgentState`/`_ResumeState`/`_RunInit` 保持 dataclass 例外惯例。消息端口先以最小协议抽取（poll/inject 各一），不引入事件总线等新抽象——那是「每次只改一个边界」的越界。

## Verification

- `python -m pytest tests/test_agent_loop.py tests/test_streaming.py tests/test_window_reset.py tests/test_steering_followup.py tests/test_plan_mode.py tests/test_agent_delegation.py tests/test_sub_agent.py tests/test_subagent_budget.py tests/test_subagent_role.py tests/test_approval.py tests/test_hooks.py tests/test_events_jsonl.py tests/test_architecture_contracts.py -q`
- `python scripts/quality_gate.py` 全量。
- `ruff check src tests scripts`、`ruff format --check src tests`、`mypy src`。
