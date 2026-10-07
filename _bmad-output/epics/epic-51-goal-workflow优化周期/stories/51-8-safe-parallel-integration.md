---
id: 51-8
title: Story 依赖图、安全调度、集成验收与文档收口
status: in-progress
parent_epic: E51
priority: P1
depends_on: [51-3, 51-4, 51-5, 51-6, 51-7]
blocks: []
created: '2026-09-29'
---

# Story 51-8：Story 依赖图、安全调度、集成验收与文档收口

## 用户故事

作为 Goal 负责人，我希望并行只在依赖和写集可证明安全时发生，并用完整回归证明新能力不破坏旧 Goal。

## 声明面（主要交付物）

- story 文档（`02-epics.md` 的 `### S-N` 段内）新增字段：**`depends_on`**、**`parallel_group`**、**`write_set`**。
  - 未声明 `write_set` = 写集未知 = **串行**（不猜、不推断）。这是 AD-10 的声明形态。
- `max_parallel_stories` 只表达**上限**，永远不是安全证明。
- 当前宿主回调没有可验证的写入隔离，因此 `parallel_group` / `write_set` 仅作声明元数据；
  执行器固定每次运行一条 Story，并在下一条开始前持久化 checkpoint / evidence。
- **验收演示（第 0 节口径）**：改动 Story 的依赖 / 写集（**只改文档**）即可改变解析出的声明，
  `src/` 零改动；声明本身不得提升并行度。

## 引擎面（最小通用能力）

- Story 解析模型补三个字段（缺省为空 → 串行），由既有 `parse_story_list` 扩展，不另造解析器。
- 通用执行规则：依赖必须已完成；任一未知或未完成依赖即 `BLOCKED`。即使写集声明不相交，
  没有隔离执行器也保持串行。
- 每条 Story 的 started / completed / failed 事件、checkpoint 与 evidence 仍独立记录。
- **为什么声明层表达不了**：依赖是否已经完成属于 Runner 持久态，必须由通用状态机判定；
  `parallel_group` / `write_set` 不能证明回调实际写入隔离，故不能授权并发。

## 验收标准

- Story 支持 `depends_on`、`parallel_group`、`write_set`。
- 依赖未完成或未知时不运行；其余形态（包括写集不相交）固定一次一条 Story。
- 每条 Story 各有 checkpoint、证据与 started / completed / failed 事件；恢复不重复已完成 Story。
- 存量 `brief.md`、`require.md`、`GOAL.md`、旧 checkpoint 和旧 workflow 可恢复。
- 样例 Goal 完成 doctor、审批、证据 Gate、workflow 冻结、脚本步骤和 fail-closed Story 调度。
- CLI、GUI、cron 对同一状态和决策结果一致。
- `docs/frame.md`、`docs/goal-optimization-plan.md`、工作流资源和架构契约同步。
- **只改 story 文档即可改变依赖闸门的结果**（以实测增量作为证据）；写集声明不得提升并行度。

## 任务

- [x] 扩展 Story 解析模型（`depends_on` / `parallel_group` / `write_set`；缺省为空）。
- [x] 实现依赖闸门与逐 Story 事件 / checkpoint；写集不作为并行授权。
- [ ] 新增集成样例与旧资产恢复矩阵。
- [ ] 收口台账中的验证重跑观测、异常路径持久化与重复执行问题。
- [ ] 运行对抗式代码评审、全量质量门并完成 retrospective。

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
