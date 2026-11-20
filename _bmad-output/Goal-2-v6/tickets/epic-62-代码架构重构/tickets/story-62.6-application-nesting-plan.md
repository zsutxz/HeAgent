---
title: 'Story 62.6 重构 goal/application.py 多层嵌套'
type: refactor
ticket: 6
created: '2026-11-17'
status: done
baseline_revision: '19668cf5693c79f8cc9cbdf44f38b58bd62ae9ef'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
context:
  - 'docs/frame.md'
  - '_bmad-output/Goal-2-v6/tickets/epic-62-代码架构重构/epic-62-代码架构重构.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 票面预设「多层条件嵌套」需以策略模式/责任链重构。勘测（baseline 19668cf，AST 全函数扫描）判定：**嵌套深度全文件最深 3 层，≤3 已达标**；真实违线是圈复杂度——`_advance_unlocked` cc=21、`_record_decision_unlocked` cc=20（`_advance_checkpoint_decision` cc=10 压线，verify 要求 <10）。

**Ruling（2026-11-17 用户裁定：函数提取拆解）：** 超标根因是 use-case 守卫面宽（每条守卫独立文案）+ 状态派发面宽，非「同一接口多变体」，策略模式/责任链仪式错配。以模块私有辅助函数拆解：

- `_advance_unlocked`（97 行，cc=21）→ 提取 `_advance_run_step`（声明步骤/普通步骤的执行分流，cc=2）+ `_advance_dispatch`（消息附加与状态→终态/继续信号派发，cc=8）；外壳留 bridge 选择、inputs 装配、异常→FAILED 文案、checkpoint 决策调用（cc≈7）
- `_record_decision_unlocked`（88 行，cc=20）→ 提取 `_decision_input_guard`（resume 拒收 + 非空文本守卫，cc=4）+ `_decision_success_message`（用户补充落需求文档的降级警告 + 成功消息组装 + checkpoint 提示，cc=6）；外壳留 restore/守卫校验/三动作派发/append+persist/异常披露（cc≈9）
- `_advance_checkpoint_decision`（cc=10 压线）→ 提取 `_checkpoint_arrived`（步骤/Story 检查点抵达判定，cc=4），caller 降至 ~7

约束：行为零变化（守卫顺序、文案逐字、落账次序「内存态 → 决策落账 → 持久化」不变）；缝零移动（仅 4 处字符串缝 patch 模块属性 `restore_runner`，留模块即不受影响；无类属性缝）；导入面零变化（全部模块私有辅助，无新模块、无再导出面）。

</frozen-after-approval>

## Tasks & Acceptance

**Execution:**

- [x] `src/heagent/goal/application.py` — 新增 14 个模块私有辅助函数；三个超标/压线函数改写为外壳+辅助结构
- [x] 嵌套深度保持 ≤3（辅助函数全部平铺）

**Verification:**

- [x] cc 重扫全文件：所有函数 cc<10（最高 9）
- [x] pytest goal 相关 + ruff check/format + mypy 全绿
- [x] 行为零变化自查：异常类型元组、messages 顺序、落账/持久化次序逐字保持

**Implementation Notes（执行期偏差账）:**

- 辅助函数落位：`_checkpoint_arrived`（cc 4）/`_advance_run_step`（cc 2）/`_blocked_step_messages`（cc 3）/
  `_result_label`（cc 3）/`_advance_dispatch`（cc 8）/`_step_inputs`（cc 3）/`_advance_next`（cc 2）/
  `_is_input_body`（cc 2）/`_matching_checkpoints`（cc 6）/`_runner_from_checkpoint`（cc 1）/
  `_decision_failure_outcome`（cc 2）/`_decision_input_guard`（cc 5）/`_decision_supplement_note`（cc 4）/
  `_decision_success_message`（cc 5）——比 Intent 预估的 5 个多，多出的 9 个用于把三个目标函数压到 7/8/7
- **勘测漏项（执行期补账）**：基线同口径 cc 扫描显示 `dedupe_inputs` cc=11、`restore_runner` cc=10 也超
  verify 的「所有函数 <10」线（Intent 只点名三个）⇒ 一并拆解为 `_is_input_body` 与
  `_matching_checkpoints`+`_runner_from_checkpoint`，现为 9 / 5
- 收口读数（同一 AST 扫描口径，可复现基线 21/20/10）：`_advance_unlocked` 21→7、
  `_record_decision_unlocked` 20→8、`_advance_checkpoint_decision` 10→7、`dedupe_inputs` 11→9、
  `restore_runner` 10→5；全文件最高 cc=9、最大嵌套深度=3
- 零行为变化的三个扣点：① `goal_user_responses` 的 `OSError` 捕获仍只包它自己（`_step_inputs` 只做组装，
  不取数）⇒ `load_project_context()` 抛错仍上抛；② `_advance_next` 把「dispatch=WAITING → checkpoint 决策 →
  None 继续循环」与「dispatch=None 继续循环」合并为同一个 `None` 出参，循环语义逐字等价；③ 决策落账次序
  「内存态 → append → persist_state」留在 `_record_decision_unlocked` 外壳，`_decision_supplement_note`
  仍在落账之后调用（失败只降级为提示）
- 缝零移动：`restore_runner` 仍留模块（4 处 patch 字符串照旧命中）；无类属性缝、无导入面变化（新增
  `GoalWorkflowState`/`WorkflowCheckpoint`/`WorkflowRunResult` 仅模块内类型标注用）
- 实测：`pytest` goal 16 文件 + `tests/test_architecture_contracts.py` → 409 passed；ruff check /
  ruff format --check / mypy 单文件全绿

