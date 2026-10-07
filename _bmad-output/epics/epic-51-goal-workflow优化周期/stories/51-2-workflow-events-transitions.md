---
id: 51-2
title: 显式 Workflow 事件与转换表
status: done
parent_epic: E51
priority: P0
depends_on: [51-1]
blocks: [51-3, 51-5]
created: '2026-09-29'
---

# Story 51-2：显式 Workflow 事件与转换表

## 用户故事

作为维护者，我希望所有状态变化都经单一事件转换表完成，以便恢复、审批、失败和并行路径不会出现互相矛盾的状态语义。

## 声明面（主要交付物）

**本 Story 不新增声明词汇**，这是刻意结论而非遗漏：

- 事件集与转换表属于**引擎不变量**（AD-3），Markdown 声明表达不了「什么状态 + 什么事件 → 什么状态」的全局一致性。
- 具体 workflow 用到哪些事件，仍由**既有词汇**决定：某步能否等待用户 = 该步声明的 `checkpoint`；
  输入缺失 = 该步声明的 `input`；门禁失败 = 该步声明的 `validation`；故事循环 = `story_loop`。
- 因此本 Story 的 声明面 = 「确认既有词汇足以表达全部触发条件」；若发现某个触发条件无处声明，
  才允许按 AD-14 引入新词汇，并在本 Story 内写明证明。

## 引擎面（最小通用能力）

- 唯一转换表 + 类型化非法转换错误（`WorkflowTransitionError`）；每个状态赋值可追溯到一个事件。
- 补齐 `CANCELLED` 语义（取消是有明确终态的事件，不得用直写 `PENDING` 掩盖）。
- 观测事件发射：观测端口可空、sink 失败只 warning、绝不改变状态机结果。
- 工具执行链与 checkpoint 写入口保持唯一（AD-1 / AD-2 / AD-6）；本 Story 不改字段语义，若新增字段只允许追加带默认值的可选字段。

## 现状审查发现（2026-09-29 实读代码，待本 Story 处置）

初版（已提交 `2bcd58c`）具备事件枚举、唯一转换表与部分接线，但存在**绕过转换表的直接状态写入**
（全仓扫描 `"status": WorkflowStatus` / `status=WorkflowStatus.` 后，仅以下两处不经 `transition()`）：

1. `src/heagent/engine/workflow_runner.py` 的 `run_step()` 异常分支 —— 步骤回调抛 `BaseException`（含取消）时
   `self.state = self.state.model_copy(update={"status": WorkflowStatus.PENDING})` 后原样 `raise`
   （2026-09-29 定位时为第 440 行；此处按符号引用，行号会随改动漂移）。
   这是「用直接写 `PENDING` 掩盖失败」的实例：`RUNNING → PENDING` 在表里只能由 `STEP_COMPLETED` 达成，
   此处既不产生事件也不留可追溯记录；且 `CANCELLED` 在 `_TRANSITIONS` 里**没有任何条目**
   （现有测试 `test_undefined_transition_fails` 反而把「全部状态 + CANCELLED 必须抛」钉成了契约）。
2. `src/heagent/goal/application.py` 的 `pause_resume()` 暂停分支 —— 直接写 `status=WAITING_USER`
   （2026-09-29 定位时为第 575 行）。
   按表 `USER_PAUSE` 只允许从 `PENDING` / `RUNNING` 出发；当前实现从 `BLOCKED` / `FAILED` 暂停也会
   静默变成 `WAITING_USER`（非法转换被静默修正，而 AC 要求 fail-loud）。

处置口径：两处都属既有行为，修改时须保持旧 checkpoint 可恢复（AD-2 修订版：只允许**追加带默认值的
可选字段**，不得改名 / 改语义 / 强制迁移），并为「非法转换被拒绝」补负向判据（去掉拒绝即精确变红）。

已由 51-1 先行落定的相关事实（**勿重复实现**）：`WorkflowRunnerState.active_epic` 与
`WorkflowCheckpoint.active_epic` 已存在（story 循环处记录，可选字段，旧 checkpoint 缺它就为空）；
`/goal status` 由此成为纯持久态投影、不读文档。本 Story 若继续加状态字段，按 AD-2 修订版追加可选字段即可。

## 验收标准

- 合法状态转换仅由单一 `_TRANSITIONS` 表定义；`src/` 中不存在任何绕过它的状态赋值。
- 非法转换抛 `WorkflowTransitionError`，原 checkpoint 状态不被覆盖。
- 回调异常、取消、Gate 失败、输入缺失、最终完成均有明确事件。
- 现有 checkpoint JSON 不迁移即可恢复。
- 每次转换产生可观测事件；观测失败不改变状态结果。
- 架构判据能发现新增的绕过转换表的直接状态写入。

## 任务

- [x] 修正 `workflow_runner.py` 的异常路径：取消/异常走显式事件，不用直写 `PENDING`。
- [x] 把 `application.pause_resume` 的状态变化改走 `transition()`（非法暂停 fail-loud）。
- [x] 统一普通步骤、Story batch、resume、pause 与 stop 路径。
- [x] 增加合法矩阵、非法矩阵、旧 checkpoint 恢复和观测 fail-soft 测试。
- [x] 负向验证：4 条变异体（删除取消转换、恢复直接 PENDING、绕过 pause transition、取消降级为 executor failure）全部精确变红。

### Review Findings（2026-09-29，bmad-code-review 4 层审查；同日全部 patch 修复并验证）

- [x] [Review][Decision] USER_PAUSE / USER_RESUME 转换无可观测事件 — **已修**（用户选「本轮补齐」）：新增 `WorkflowRunner.pause(emit)` / `resume(emit=)` 发射 `workflow_paused` / `workflow_resumed`，`_advance_checkpoint_decision` 透传 emit；sink 抛错由 `_emit_step_event` fail-soft 隔离 [src/heagent/engine/workflow_runner.py]
- [x] [Review][Patch] AC-6 架构判据缺失：**已修** — `test_workflow_state_writes_go_through_the_transition_table` 以 AST 扫描 src/ 全部 `model_copy(update={"status": ...})`，值必须为 `transition(...)` 或命中白名单（`_callback_status` / `next_status`）；变异验证：临时直写文件精确变红 [tests/test_architecture_contracts.py]
- [x] [Review][Patch] 并行 story 批次异常/取消不经转换表：**已修** — 批级 `except BaseException` 与串行共用 `_absorb_step_exception`（取消 → CANCELLED → PENDING，其余 → EXECUTOR_FAILED → FAILED）；变异验证：移除调用后并行取消测试精确变红 [src/heagent/engine/workflow_runner.py]
- [x] [Review][Patch] 取消路径 reason 空串：**已修** — `_absorb_step_exception` 以 `str(exc) or event.value` 兜底（取消 → `cancelled`）[src/heagent/engine/workflow_runner.py]
- [x] [Review][Patch] FAILED runner 上 pause 行为翻转无测试固化：**已修** — 补 FAILED 负向（状态不被覆盖）+ PENDING happy-path（PAUSED + WAITING_USER 持久化）+ RUNNING 态经表暂停共 3 测试 [tests/test_goal_declarative_workflow.py]
- [x] [Review][Patch] 设计文档 §8.2 转换表缺 `(RUNNING, CANCELLED) → PENDING` 行：**已修** [docs/goal-workflow.md]
- [x] [Review][Patch] 新导入绕过 engine 门面：**已修** — pause 逻辑内聚进 `WorkflowRunner.pause()` 后，application.py 不再需要 `workflow_events` / `workflow_transition` 导入，两条绕过导入删除 [src/heagent/goal/application.py]
- [x] [Review][Defer] 异常路径转换后不持久化（重启后 restore 复活 RUNNING）[src/heagent/engine/workflow_runner.py:439] — deferred, pre-existing；建议并入 51-3 证据模型
- [x] [Review][Defer] KeyboardInterrupt / SystemExit 被归类 EXECUTOR_FAILED（CLI 侧视为用户中断，语义不对称）[src/heagent/engine/workflow_runner.py:440] — deferred, pre-existing
- [x] [Review][Defer] except 内 transition() 理论上可抛 WorkflowTransitionError 掩盖原异常（已核实当前回调拿不到 runner 引用，不可达）[src/heagent/engine/workflow_runner.py:444] — deferred, pre-existing
- [x] [Review][Defer] COMPLETED 且 phase 未走完的 runner 暂停会落入非法转换异常路径 [src/heagent/goal/application.py:576] — deferred, pre-existing
- [x] [Review][Defer] reason 无长度上限直通持久化字段（既有行为，HTTP 事件侧已有 16384 截断纪律）[src/heagent/engine/workflow_runner.py:444] — deferred, pre-existing
- [x] [Review][Defer] workflow_step_failed 事件不带驱动转换的事件类型；last_event / transition_reason checkpoint 字段未实现 [src/heagent/engine/workflow_runner.py:446] — deferred, pre-existing（计划 §后续 story 已登记）

## Review 修复实测证据（2026-09-29，本机亲跑）

```text
pytest tests/test_workflow_transition.py tests/test_workflow_runner.py tests/test_goal_declarative_workflow.py \
  tests/test_story_loop.py tests/test_architecture_contracts.py tests/test_engine_checkpoint.py -q
→ 151 passed

pytest -q（全量）          → 3278 passed, 14 skipped, 18 deselected, 8 warnings in 148.40s
ruff check src tests       → All checks passed!
ruff format --check src tests → 297 files already formatted
mypy src                   → Success: no issues found in 157 source files

负向变异（本机亲跑）：
  A. 新增绕过 transition() 的直写文件 → 架构判据精确变红；删除后恢复绿
  C. 移除 Story 执行异常路径的 `_absorb_step_exception` 调用 → 取消状态测试精确变红；内存备份还原无损
```

## 实测证据（2026-09-29，本机亲跑）

```text
pytest tests/test_workflow_transition.py tests/test_workflow_runner.py tests/test_engine_checkpoint.py \
  tests/test_goal_declarative_workflow.py tests/test_architecture_contracts.py -q
→ 123 passed

pytest -q（全量）                            → 3271 passed, 14 skipped, 18 deselected, 8 warnings in 148.10s
ruff check src tests                         → All checks passed!
ruff format --check src tests                → 297 files already formatted
mypy src / mypy src --platform linux         → 157 files，均 no issues
python .heagent/tmp/neg51_2.py              → 4/4 变异体精确变红
```

实现要点：

- `RUNNING + CANCELLED → PENDING` 进入唯一 `_TRANSITIONS` 表；取消仍原样上抛，但不再绕过状态机。
- 普通回调异常走 `RUNNING + EXECUTOR_FAILED → FAILED`，保留原异常上抛与 `workflow_step_failed` 观测。
- `pause_resume()` 使用 `transition(..., USER_PAUSE)`；`BLOCKED` / `FAILED` 暂停现在显式失败且不覆盖原状态。
- 旧 checkpoint 通过新增可选字段兼容规则恢复；未改变既有字段语义。

## 验证命令（规划，执行时亲跑；引用不存在的文件按实测更正）

```bash
pytest tests/test_workflow_transition.py tests/test_workflow_runner.py tests/test_engine_checkpoint.py -q
pytest tests/test_goal_declarative_workflow.py tests/test_architecture_contracts.py -q
ruff check src tests
ruff format --check src tests
mypy src
mypy src --platform linux
```
