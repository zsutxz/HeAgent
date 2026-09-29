---
id: 51-2
title: 显式 Workflow 事件与转换表
status: in-progress
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
- 工具执行链与 checkpoint 写入口保持唯一（AD-1 / AD-2 / AD-6），本 Story 不改 checkpoint JSON 形状。

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

- [ ] 修正 `workflow_runner.py` 的异常路径：取消/异常走显式事件，不用直写 `PENDING`。
- [ ] 把 `application.pause_resume` 的状态变化改走 `transition()`（非法暂停 fail-loud）。
- [ ] 统一普通步骤、Story batch、resume、pause 与 stop 路径。
- [ ] 增加合法矩阵、非法矩阵、旧 checkpoint 恢复和观测 fail-soft 测试。
- [ ] 负向验证：删除非法转换拒绝、绕过 transition、把 `BLOCKED` 改 `COMPLETED` 时精确变红。

## 验证命令（规划，执行时亲跑；引用不存在的文件按实测更正）

```bash
pytest tests/test_workflow_transition.py tests/test_workflow_runner.py tests/test_engine_checkpoint.py -q
pytest tests/test_goal_declarative_workflow.py tests/test_architecture_contracts.py -q
ruff check src tests
ruff format --check src tests
mypy src
mypy src --platform linux
```
