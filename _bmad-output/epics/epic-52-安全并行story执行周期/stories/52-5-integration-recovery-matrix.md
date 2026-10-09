---
id: 52-5
title: 集成验收与恢复矩阵
status: review
parent_epic: E52
priority: P1
depends_on: [52-2, 52-3, 52-4]
blocks: []
created: '2026-10-09'
---

## 实测证据（2026-10-09，Windows 10 / Python 3.13 venv）

- `pytest tests/test_story_scheduling_integration.py` → **10 passed**（51-8 四形态矩阵 + 新增
  revoked-latch 形态、并行全链样例、RUNNING 快照恢复、R4 冒烟）。
- `pytest` 全量 → **3675 passed, 14 skipped**（52-3 新增 11、52-4 翻转 1、52-5 新增 4）。
- `ruff check src tests` → All checks passed；`ruff format --check src tests` → 316 files formatted。
- `mypy src`（win32）→ no issues（164 files）；`mypy src --platform linux` → no issues。
- `pytest tests/test_architecture_contracts.py` → 30 passed（engine 不导入 goal 由
  `FORBIDDEN_RUNTIME_IMPORTS["engine"]` 既有钉子覆盖，本周期 import 方向全合法，无需新增钉子）。
- src 分支字面量扫描：`parallel_group` 命中均为声明词汇的通用门控/解析逻辑，无 Epic/Story 专用分支。

## 抓出的真缺口（52-5 的存在价值）

- **批中间 RUNNING 快照不可恢复**（矩阵新形态 RED 实证）：进程死在批结算中段时，最新盘上快照
  status=RUNNING，而转换表无 RUNNING 再入口（`START` 只接 PENDING）→ 恢复路径 `running + start`
  显性崩溃。修复：`WorkflowRunner.from_checkpoint` 将 RUNNING 快照**归一化为 PENDING**（确定性
  崩溃恢复语义：盘上 RUNNING 只可能意味着进程死在步骤中段；归一化后批派生跳过已完成成员续跑，
  注释显性说明非静默兜底）。引擎级唯一改动，`src/` 零 Epic 专用分支。

## 交付记录

- `tests/test_story_scheduling_integration.py` 扩展四块：并行全链样例（依赖闸门 → 批调度事件 →
  应用桥透传执行上下文 → 宿主围栏参数 + Git 审计事件 → 快照链 → 声明序合并 → 恢复不重跑）、
  RUNNING 快照恢复（新形态 TDD 抓出上缺口）、恢复矩阵 revoked-latch 形态、R4 并发冒烟
  （3 SubAgent 复用同一 provider + EngineContainer，峰值并发 ≥2 断言）。
- 批内失败重组路径由 52-2 判据文件锚定（`test_single_failure_does_not_cancel_batch_and_resume_rederives`），
  本文件不重复。
- 对抗式评审与 retrospective 待跑（与 52-1..52-4 一同处置）。

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
