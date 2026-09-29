---
id: 51-8
title: Story 依赖图、安全并行、集成验收与文档收口
status: ready-for-dev
parent_epic: E51
priority: P1
depends_on: [51-3, 51-4, 51-5, 51-6, 51-7]
blocks: []
created: '2026-09-29'
---

# Story 51-8：Story 依赖图、安全并行、集成验收与文档收口

## 用户故事

作为 Goal 负责人，我希望并行只在依赖和写集可证明安全时发生，并用完整回归证明新能力不破坏旧 Goal。

## 声明面（主要交付物）

- story 文档（`02-epics.md` 的 `### S-N` 段内）新增字段：**`depends_on`**、**`parallel_group`**、**`write_set`**。
  - 未声明 `write_set` = 写集未知 = **串行**（不猜、不推断）。这是 AD-10 的声明形态。
- 已批准的并行批次决策作为**工作流产物**持久化（不是配置），恢复时只能复用或收缩。
- `max_parallel_stories`（既有词汇）只表达**上限**，永远不是安全证明。
- **验收演示（第 0 节口径）**：改动一个 Epic 的依赖 / 写集（**只改文档**）即可改变并行批次，
  `src/` 零改动。

## 引擎面（最小通用能力）

- Story 解析模型补三个字段（缺省为空 → 串行），由既有 `parse_story_list` 扩展，不另造解析器。
- 通用判定：依赖完成 + 写集不相交 + 无共享单写者产物 + 同 Epic + 独立 checkpoint / evidence、
  恢复不扩大并行度；任一条件未知即串行。
- 并行判定结果写入可观测事件与报告。
- **为什么声明层表达不了**：判定需要读取已完成 Story 的证据与 pending 批次状态；声明只能给出
  依赖与写集。判定器是通用算法，与具体 Epic / Story 无关。

## 验收标准

- Story 支持 `depends_on`、`parallel_group`、`write_set`。
- 依赖未完成、写集重叠、共享单写者产物或元数据不足时自动串行（含「写集未声明」）。
- 并行 Story 各有独立 checkpoint 与证据；单个失败不取消已安全启动的兄弟，但批次 Gate 不通过。
- 恢复不重复已完成 Story，也不因配置变化扩大并行度。
- 存量 `brief.md`、`require.md`、`GOAL.md`、旧 checkpoint 和旧 workflow 可恢复。
- 样例 Goal 完成 doctor、审批、证据 Gate、workflow 冻结、脚本步骤和安全并行。
- CLI、GUI、cron 对同一状态和决策结果一致。
- `docs/frame.md`、`docs/goal-optimization-plan.md`、工作流资源和架构契约同步。
- **只改 story 文档即可改变并行批次**（以实测增量作为证据）。

## 任务

- [ ] 扩展 Story 解析模型（`depends_on` / `parallel_group` / `write_set`，缺省为空即串行）。
- [ ] 实现依赖 / 写集判定并写入可观测事件与报告。
- [ ] 新增集成样例与旧资产恢复矩阵。
- [ ] 运行对抗式代码评审并修复 Critical / High。
- [ ] 全量质量门、记录实测数字，完成 retrospective。

## 验证命令（规划，执行时亲跑；引用不存在的文件按实测更正）

```bash
pytest tests/test_goal_declarative_workflow.py tests/test_workflow_runner.py tests/test_story_loop.py -q
pytest tests/test_architecture_contracts.py -q
pytest
ruff check src tests
ruff format --check src tests
mypy src
mypy src --platform linux
```

## 收口纪律

- 不自动 commit。
- 未亲跑的命令不得写成通过。
- 全量验证若受本机环境影响，必须做基线对照并如实记录。
