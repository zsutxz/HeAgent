---
id: 51-5
title: 步骤级审批与决策记录
status: ready-for-dev
parent_epic: E51
priority: P1
depends_on: [51-2]
blocks: [51-6, 51-8]
created: '2026-09-29'
---

# Story 51-5：步骤级审批与决策记录

## 用户故事

作为用户，我希望批准、拒绝、修订和普通恢复具有不同语义，以便关键产品/架构决策不会被一次模糊的 resume 自动跨过。

## 验收标准

- workflow step 可声明 `approval_required`。
- 支持 `/goal approve`、`/goal reject <原因>`、`/goal amend <补充>`、`/goal decisions`。
- 决策记录包含 id、步骤、原文、时间、影响范围和结果，并追加式保存。
- reject/amend 不把步骤标记完成；重跑保留历史决策。
- `/goal resume` 保持兼容，但不能隐式等同批准。
- cron 不得自动批准人工 Gate；CLI/GUI/cron 共用同一应用服务。

## 任务

- [ ] 定义 Pydantic `GoalDecision` 与存储/读取协议。
- [ ] 扩展事件与 transition 语义，避免入口层直接写状态。
- [ ] 在 `goal/application.py` 实现决策应用服务。
- [ ] CLI 输出继续走 `_echo`，GUI sink 行为一致。
- [ ] 增加拒绝后重跑、修订保留、cron 禁止自动批准和历史不覆盖测试。

## 验证命令（规划，执行时亲跑）

```bash
pytest tests/test_goal_decisions.py tests/test_goal_application.py tests/test_goal_message_sink.py -q
pytest tests/test_engine_workflow.py -q
ruff check src tests
mypy src
mypy src --platform linux
```
