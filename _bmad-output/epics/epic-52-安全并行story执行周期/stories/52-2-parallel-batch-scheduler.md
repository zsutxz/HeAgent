---
id: 52-2
title: 批次调度器与 Runner 并行执行语义
status: review
parent_epic: E52
priority: P1
depends_on: [52-1]
blocks: [52-3, 52-4, 52-5]
created: '2026-10-09'
---

# Story 52-2：批次调度器与 Runner 并行执行语义（本 Epic 核心）

## 用户故事

作为 Goal 负责人，我希望 Runner 在七项授权条件全部满足时确定性推导并行批、并发执行、按声明序记账，
任一条件不满足即逐字退回串行。

## 引擎面（主要交付物；声明层表达不了的证明）

依赖是否已完成属 Runner 持久态，批的并发执行与单 checkpoint 单元语义是通用状态机能力——51-8 已证明
声明层表达不了（"依赖闸门必须由通用状态机判定"），并发调度是其直接延伸。

- `src/heagent/pub/types.py`：新增 `StoryExecutionContext(BaseModel)`
  （`story_id` / `parallel` / `write_allowlist` / `batch_members` / `sibling_write_sets`）。
- `src/heagent/engine/workflow_runner.py`：
  - 批派生纯函数 `_parallel_batch(step, specs, callback) -> list[StorySpec]`（七条件，脊柱 §2）；
  - `WorkflowStepResult.write_violation: bool = False`、`WorkflowRunnerState.story_parallel_revoked:
    bool = False`、`WorkflowRunResult.executed_stories: list[str] = []`（全部追加带默认值）；
  - `run_step` 并行路径：`asyncio.gather(*[callback(step, s, ctx)], return_exceptions=True)` →
    **按声明序**逐成员记账（completed_stories / story_outputs / story_statuses / story_index）+
    逐成员 `_persist`（RUNNING 中间快照）→ **单次终态转换**（全 COMPLETED →
    CHECKPOINT_REQUIRED / STEP_COMPLETED / FINAL_STEP_COMPLETED；有异常 → EXECUTOR_FAILED +
    重抛声明序首个异常；有非 COMPLETED 结果 → `_callback_status` 映射）；
  - `_accepts_execution(callback)`：`inspect.signature` 位置参数 ≥3（仿 `_accepts_story`）；
  - `write_violation=True` 结果 → 置撤销闩（单向不可复位）随 `_persist` 落盘；
  - 批前发 `workflow_story_batch_scheduled` 事件（members + basis）。
- `src/heagent/engine/checkpoint.py`：`WorkflowCheckpoint.story_parallel_revoked: bool = False`
  + `from_checkpoint` 映射（AD-2 追加式）。

## 验收标准

1. `tests/test_story_batch_safety.py:56` 翻转：声明不相交 → `peak == 2`、seen 顺序符合声明序、
   逐成员 checkpoint 链递增。
2. 七条件逐一的反例（含两参老回调、revoked 闩、写集相交、依赖批内成员、超上限）均 `peak == 1`
   且串行路径既有测试零改动通过。
3. 批内一失败一完成：完成者入账、失败者 `story_statuses=failed`、步骤 FAILED、`story_index`
   停首个未完成、重启恢复不重跑完成者。
4. 步骤级取消 → 整批 PENDING、未落账成员记 `cancelled`（不谎报 failed）。
5. `write_violation=True` → 闩置位并持久化；恢复后同 Goal 仍串行；闩不撤销围栏（串行重跑仍带 allowlist）。
6. 末条 Story 在批内 → 步骤收口 / 审批门语义与串行一致；manual 模式确认从每 Story 一次收紧为每批一次。
7. 乱序完成时 `story_outputs` 合并序 = 声明序。
8. `workflow_story_batch_scheduled` 事件含 members 与依据；观测 sink 失败不改状态。

## 任务

- [x] TDD：先写 `tests/test_story_parallel_scheduling.py`（RED：收集期 ImportError → 逐步 GREEN）。
- [x] 实现 pub 模型 + runner 并行路径 + checkpoint 字段（GREEN：20/20）。
- [x] 翻转 `test_story_batch_safety.py:56`（峰值 1→2 + 批中间快照链）/ 重写 `:107`（老回调串行
      语义锁定）；`test_workflow_runner.py` 两个旧 `test_parallel_batch_*` 改名
      `test_single_story_*` 保留（单 story 批 = 串行路径，断言不变）。

## 实现修正记录（TDD 过程中抓出的设计缺口，均已有测试锁定）

1. **run_step 守卫漏撤销闩**：`story_parallel_revoked` 检查原计划放 `_parallel_batch` 内，实际落
   run_step 前置守卫（闩命中 → execution=None + 串行）。
2. **有洞恢复回摆**：批内失败允许 completed 有洞（S-2✓/S-1✗），story_index 必须显式回摆到
   **首个未完成**（原单调推进会让恢复跳过违规者 S-1）；`_story_advance_update` 同步补
   「越过已完成」循环 + 全完成即收口判定（无洞历史下零迭代，51-8 行为逐字节不变）。
3. **varargs 不算实现契约**：`*_rest` 宽签名（如测试桩 `_complete(_step, *_rest)`）不得借
   varargs 意外获得并发授权——`_accepts_execution` 只数**显式**位置参数 ≥3（fail-closed）。

## 验证命令（规划，执行时亲跑）

```bash
pytest tests/test_story_parallel_scheduling.py tests/test_story_batch_safety.py tests/test_story_loop.py tests/test_workflow_runner.py -q
pytest tests/test_architecture_contracts.py -q
pytest
ruff check src tests
ruff format --check src tests
mypy src
mypy src --platform linux
```

## 实测证据（2026-10-09，本机亲跑；环境已无并发进程，全量干净）

```text
pytest tests/test_story_parallel_scheduling.py -q → 20 passed
story 域 6 文件（batch_safety/story_loop/workflow_runner/parallel_scheduling/
  scheduling_integration/write_allowlist）→ 89 passed
goal_decisions 并入后 → 125 passed
ruff check src tests → All checks passed!
ruff format --check src tests → 315 files already formatted
mypy src → Success: no issues found in 164 source files
pytest tests/test_architecture_contracts.py -q → 30 passed
pytest -q（全量）→ 3660 passed, 0 failed, 14 skipped, 18 deselected
```

全量数字对账：51-8 基线 3603 + 52-1 新增 15 + 52-2 新增 25（含参数化反例 5 例）+ 零回归翻转 ≈ 3660。
52-1 期间的 22 个 goal.lock 环境失败已随并发进程结束消失（本轮干净复现 0 failed）。
