---
id: 52-5
title: 集成验收与恢复矩阵
status: planned
parent_epic: E52
priority: P1
depends_on: [52-2, 52-3, 52-4]
blocks: []
created: '2026-10-09'
---

# Story 52-5：集成验收与恢复矩阵

## 用户故事

作为 Goal 负责人，我希望用完整回归证明并行执行、围栏、审计、失败降级与恢复在真实 goal 目录形态下
协同工作且旧资产无损。

## 范围

- `tests/test_story_scheduling_integration.py` 扩展：
  - **并行全链样例**：依赖闸门 → 批调度（`workflow_story_batch_scheduled`）→ 并发执行（围栏生效）→
    逐成员 checkpoint（RUNNING 中间快照）→ 审计 → 合并输出（声明序）→ 恢复不重跑；
  - **批内 1 失败 → resume → 重推导跳过已完成 → 批重组**全路径；
  - 恢复矩阵参数化新增形态：含 `story_parallel_revoked` 闩的 checkpoint、批中间 RUNNING 快照。
- `tests/test_architecture_contracts.py` 同步（pub 新模型依赖方向、engine 不导入 goal）。
- 并发压力形态：3+ SubAgent 并发复用 provider/engine 的冒烟（R4）。
- 全量质量门 + 对抗式代码评审 + retrospective。

## 验收标准

1. 并行全链样例通过，事件序列完整（scheduled → 逐成员 started/completed → 审计 → 步骤收口）。
2. 恢复矩阵（as-is / 含 `story_batches` 旧字段 / 极简旧形 / 含 revoked / 批中间快照）全部可恢复续跑，
   恢复不重复已完成 Story。
3. 架构契约全绿；`src/` 无 Epic / Story 专用分支字面量。
4. 全量 `pytest` + `ruff check` + `ruff format --check` + `mypy src`（双平台）亲跑留痕，实测数字
   写回本文件（51-8 同款「实测证据」节）。
5. 对抗式评审无未处置的 CRITICAL / HIGH。

## 任务

- [ ] 并行全链集成样例（TDD）。
- [ ] 恢复矩阵扩展 + 批失败重组路径。
- [ ] 架构契约同步 + 压力冒烟。
- [ ] 全量质量门亲跑 + 实测证据登记。
- [ ] 对抗式评审与 retrospective。

## 验证命令（规划，执行时亲跑）

```bash
pytest tests/test_story_scheduling_integration.py tests/test_architecture_contracts.py -q
pytest
ruff check src tests
ruff format --check src tests
mypy src
mypy src --platform linux
```
