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

## 验收标准

- Story 支持 `depends_on`、`parallel_group`、`write_set`。
- 依赖未完成、写集重叠、共享单写者产物或元数据不足时自动串行。
- 并行 Story 各有独立 checkpoint 与 Evidence；单个失败不取消已安全启动的兄弟，但批次 Gate 不通过。
- 恢复不重复已完成 Story，也不因配置变化扩大并行度。
- 存量 `brief.md`、`require.md`、`GOAL.md`、旧 checkpoint 和旧 workflow 可恢复。
- 样例 Goal 完成 doctor、审批、证据 Gate、workflow 冻结、脚本步骤和安全并行。
- CLI、GUI、cron 对同一状态和决策结果一致。
- `docs/frame.md`、`docs/goal-optimization-plan.md`、工作流资源和架构契约同步。

## 任务

- [ ] 扩展 Story 解析模型并实现依赖/写集判定。
- [ ] 将并行判定结果写入可观测事件与报告。
- [ ] 新增集成样例与旧资产恢复矩阵。
- [ ] 运行对抗式代码评审并修复 Critical/High。
- [ ] 运行全量质量门、记录实测数字，完成 retrospective。

## 验证命令（规划，执行时亲跑）

```bash
pytest tests/test_goal_*.py tests/test_workflow_*.py -q
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
