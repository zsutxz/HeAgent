---
id: 51-1
title: Goal 预检与统一状态视图
status: ready-for-dev
parent_epic: E51
priority: P0
depends_on: []
blocks: [51-2, 51-3, 51-5]
created: '2026-09-29'
---

# Story 51-1：Goal 预检与统一状态视图

## 用户故事

作为 `/goal` 使用者，我希望在执行前知道 workflow、角色、模板和状态目录是否可用，并在执行中看到统一状态，以便失败发生在可定位的预检阶段。

## 现有工作区基线

当前未提交改动已包含 `src/heagent/goal/doctor.py`、`tests/test_goal_doctor.py` 与 `/goal doctor` 初版。实现时必须先评审并增量完善，不得重写覆盖。

## 验收标准

- 有效 workflow、必需资源、角色包和状态目录可用时返回结构化 PASS。
- 缺失角色、模板、资源 hash 漂移或不可写 checkpoint 目录时返回结构化问题列表。
- doctor 只读，不推进状态、不写 checkpoint、不改 Goal 文档。
- `GoalStatusView` 展示当前 Step/Epic/Story、状态、阻塞原因、未决决策、最近失败和推荐命令。
- CLI、GUI、cron 消费同一个 Pydantic 状态模型。
- `/goal doctor` 的用户输出必须走 `_echo` 漏斗。

## 任务

- [ ] 将 doctor 返回值从字符串列表升级为 Pydantic 报告模型，同时保留稳定的人类可读渲染。
- [ ] 补齐 workflow 必需资源、角色资源完整性、checkpoint 可写性与工作区危险状态检查。
- [ ] 新增 `goal/status_view.py`，从 Runner/checkpoint 投影统一状态。
- [ ] 为 CLI 命令、GUI sink 与 cron 路径补一致性测试。
- [ ] 做负向验证：移除角色/模板/hash 校验/可写性检查时新测试精确变红。

## 验证命令（规划，执行时亲跑）

```bash
pytest tests/test_goal_doctor.py tests/test_goal_status_view.py tests/test_goal_message_sink.py -q
pytest tests/test_goal_application.py tests/test_architecture_contracts.py -q
ruff check src tests
ruff format --check src tests
mypy src
mypy src --platform linux
```
