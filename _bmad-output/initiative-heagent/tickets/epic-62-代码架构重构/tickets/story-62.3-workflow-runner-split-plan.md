---
title: 'Story 62.3 拆分 engine/workflow_runner.py'
type: refactor
ticket: 3
created: '2026-11-17'
status: done
baseline_revision: '89281157340c85347d37be57818044d818f905ba'
route: full
route_source: auto
risk: medium
review: quick
review_source: pinned
lenses_ran: [quick]
context:
  - 'docs/frame.md'
  - '_bmad-output/initiative-heagent/tickets/epic-62-代码架构重构/epic-62-代码架构重构.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `engine/workflow_runner.py` 1343 行，超单文件 <1000 行红线（NFR3），是 epic-62 第三顺位拆分对象。

**Approach（2026-11-17 用户三次裁定）:** ① A 方案——新建 `engine/state_machine.py`（状态模型 `WorkflowRunnerState` + 结果模型 `WorkflowStepResult`/`WorkflowRunResult` + 纯推导层 `_transition_fields`/`_callback_event`/`_cancel_or_failure_event` + 四个 update builder + 决策应用纯函数（pause/resume/approve/reject/amend 内核）+ `WorkflowGateError` + `_bounded_reason`/`_MAX_REASON_CHARS`/`_CANCEL_EXCEPTIONS` + `_checkpoint_declared`/`_references` + `_validate_state`/`_is_done`/`_stop_event`）。`workflow_transition.py` 纯表原地不动（单一真源不合并）。② 缺口补齐——`_emit_step_event` 观测隔离包装迁 `engine/observability.py`（真域=观测，与 elapsed_ms 同居；runner、`cli/goal/verify.py`、`goal/write_audit.py` 三方共享面经 workflow_runner 再导出零变化）。③ 终局补齐——决策包装内联 emit 比预算多 ~44 行，新建 `engine/story_batch.py` 收 story 并行批派生/收集（`_parallel_batch`/`_execution_context`/`_gather_story_batch`）与回调调用契约（`_invoke_callback`/`_accepts_execution`/`_accepts_story`/`_positional_arity`+位置参数常量）及写集词法（`write_set_parts`/`write_set_entries_overlap`，write_audit 经 runner 再导出面保消费）。终局行数：runner 924 / state_machine 368 / story_batch 171，全部 <1000 ✓。票面「提取至 state_machine.py」之下的命名被现状否定：纯转换表已住 workflow_transition.py（25 条转换独立测试），本票实际工作 = 推导层/决策层/模型提取 + <1000 达标。

## Boundaries & Constraints

**Always:**

- 公开导入面零变化：engine/__init__、goal/{status_view,workflow_loader,write_audit}、cli/goal/verify 与 15 个测试文件的 `heagent.engine.workflow_runner` 导入面经再导出保面
- `persist_state` 留 WorkflowRunner 类方法（test_goal_decisions.py:676 对象缝红线）；pause/resume/approve/reject/amend 公开 API 留类上（薄包装 + 文档串）
- 行为零变化：决策包装的 emit 时序 / reason 边界（reject 收敛落状态+事件同值、amend 状态清空+事件原文）/ deep copy 时序逐字保持；`_absorb_step_exception` 的状态写留 runner
- 契约测试同步：`test_transition_fields_helper_is_the_only_status_writer` 只换解析路径为 state_machine.py（AST 断言逐字成立：helper 单 return 字面 dict、`transition(state.status, event)`、args[1]=="event"、`_bounded_reason` 收敛）；`_emit_step_event` 观测面判据不动（runner 内调用点保留）；状态直写扫描（rglob SRC）自动覆盖新模块
- frame.md 同步：模块总表、目录树、转换表锚点列（搬移后的真实行号）
- 本机 Windows：pytest 不带 --cov

**Never:**

- `workflow_transition.py` 不动（纯表单一真源，不合并进 state_machine）
- 不顺手做票外重构：run_step / _settle_story_batch / _persist / _checkpoint_id 编排与持久化面不搬移
- 不改任何 monkeypatch 缝语义：本票唯一缝 = persist_state 对象缝（类属性补丁），搬移面不触它

</frozen-after-approval>

## Code Map（搬移账）

被拆对象 1343 行，分五簇（行号为 baseline 8928115 时点）：

| 簇 | baseline 行号 | 去向 |
| --- | --- | --- |
| 状态机头块：`_MAX_REASON_CHARS`/`_CANCEL_EXCEPTIONS`/`_bounded_reason` | L38-57 | state_machine |
| 观测隔离包装 `_emit_step_event` | L77-108 | observability（真域） |
| 模型簇：GateError L123-124 / State L127-170 / StepResult L173-184 / RunResult L187-205 / combine L231-240 / story_reset L243-251 | — | state_machine |
| 推导层：`_transition_fields` L835-850 / `_callback_event` L916-925 / `_absorb` 事件选择 L861 | — | state_machine（`_absorb` 状态写留 runner） |
| update builder 簇 L1072-1166 + `_checkpoint_declared` L1218-1219 + `_references` L1314-1316 | — | state_machine（builder 增 state/total_steps 参数） |
| 决策层：pause L899-914 / resume L927-951 / approve L953-972 / reject/amend L974-991 / `_decision_update` L993-1011 | — | 内核纯函数进 state_machine，包装留类 |
| 判定纯函数：`_validate_state` L331-340 / `done` L328-329 / `_stop` 事件选择 L1055-1057 | — | state_machine（`_validate_state`/`_is_done`/`_stop_event`） |
| 留 runner：`_positional_arity` 簇 L60-74 / `required_sections` L111-120 / write_set L213-228 / callback 类型别名 L208-210 / run_step / run_declared_step / story 批簇 L503-776 / `_stop`/`_refuse_oversized_plan` / persist 簇 L1019-1270 / 静态校验 L1306-1343 | — | 原地 |

**缝与消费面账：**

- 唯一 monkeypatch 缝：`monkeypatch.setattr(WorkflowRunner, "persist_state", broken)`（test_goal_decisions.py:676）→ persist_state 留类方法，缝不动
- 测试缝重定向 2 处：test_workflow_transition_reason.py:128,137 `runner._transition_fields(event...)` → `_transition_fields(runner.state, event...)`（方法→模块纯函数）；`runner._absorb_step_exception` 调用（test_workflow_runner.py:540,550）不动（方法留 runner）
- 再导出面（workflow_runner 保面）：GateError/State/StepResult/RunResult（engine/__init__、goal/*、15 测试文件）、`_bounded_reason`/`_MAX_REASON_CHARS`/`_CANCEL_EXCEPTIONS`（test_workflow_runner.py:16、test_workflow_transition_reason.py:25-30,325）、`_emit_step_event`（cli/goal/verify.py:16、goal/write_audit.py:23、test_workflow_runner.py:16）
- 契约测试两处：`test_architecture_contracts.py:1002` 路径换 state_machine.py；:1033 error_kind 判据零改动
- frame.md 同步面：L956 模块总表、L1065-1085 转换表锚点列、L1653 目录树（锚点行号按拆后实际重算）

## Tasks & Acceptance

**Execution:**

- [x] `src/heagent/engine/state_machine.py` — 新建：模型簇 + 纯推导层 + builder 簇 + 决策内核 + 判定纯函数，正文 span 逐字节搬移 + 增 state/total_steps 参数（368 行）
- [x] `src/heagent/engine/story_batch.py` — 新建（裁定③）：批派生/收集 + 回调调用契约 + 写集词法（171 行）
- [x] `src/heagent/engine/observability.py` — `_emit_step_event` 迁入（verbatim，32 行）
- [x] `src/heagent/engine/workflow_runner.py` — 删搬移块、调用点改模块函数调用、薄决策包装、`__all__` 再导出面（924 行）
- [x] `tests/test_architecture_contracts.py` — 唯一状态写点判据解析路径换 state_machine.py；error_kind 判据零改动（runner 调用点保留）
- [x] `tests/test_workflow_transition_reason.py` — 缝重定向 4 处 `runner._transition_fields(...)` → `_transition_fields(runner.state, ...)`
- [x] `tests/test_story_parallel_scheduling.py` + `tests/test_story_write_audit.py` — `WorkflowRunner._accepts_execution` 类属性引用 ×5 → story_batch 模块函数（勘测期遗漏、执行期补账的缝）
- [x] `tests/contract_baselines/exception_types.json` — 重打（GateError 等模块归属随迁 state_machine）
- [x] `docs/frame.md` — 模块总表（五→七）+ 目录树两行 + 转换表锚点列 14 格 + 中断语义表锚点

**Verification:**

- [x] wc -l：workflow_runner.py 924 / state_machine.py 368 / story_batch.py 171，全部 <1000 ✓
- [x] pytest 全量（不带 --cov）：4421 passed / 16 skipped / 6 failed——6 败全为已判环境产物（test_setup_ws_external ×5 净 HEAD 基线同红 verify_baseline VERDICT: environmental；test_ws_server ×1 本地 .env 端口污染在案），零回归
- [x] ruff check + ruff format --check + mypy（207 文件）全绿
- [x] 导入面零变化实证：engine/__init__、goal/{status_view,workflow_loader,write_audit}、cli/goal/verify 导入行未动；模块图身份断言（runner._parallel_batch is story_batch._parallel_batch 等）通过；persist_state 类属性缝在位

**Implementation Notes（执行期裁定与偏差账）:**

- 布局演进三次用户裁定（见 Intent）；②③两档均为行数账驱动的补齐，执行时序：state_machine 构建先落 → observability → 调用点改写 → story_batch（账差 61 行后追加）
- 搬移方法：state_machine/story_batch 正文按 git HEAD span 逐字节提取 + 机械替换参数化（`self.state`→`state`、`self._x`→`_x`、staticmethod 装饰器摘除），非手打转写
- 决策包装比预算胖 ~44 行的根因：`_decision_update` 内联后 reject/amend 各自带完整 emit 块（原共享包装拆成两份）；kernel 保持零 emit（决策观测端口留在 runner 包装）
- 契约测试两处落位：唯一状态写点判据改读 state_machine.py（AST 断言逐字未动，`transition(state.status, event)` 的 args[1] 仍为字面 `event`）；error_kind 判据因 runner 内 `_emit_step_event` 调用点保留而零改动
- pyproject 无需改动（coverage omit 无 engine/workflow_runner 条目）；engine/__init__ 经 workflow_runner 再导出面零变化
