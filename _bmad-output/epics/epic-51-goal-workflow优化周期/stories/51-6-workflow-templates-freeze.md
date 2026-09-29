---
id: 51-6
title: 多 workflow 模板与创建时冻结
status: ready-for-dev
parent_epic: E51
priority: P1
depends_on: [51-4, 51-5]
blocks: [51-7, 51-8]
created: '2026-09-29'
---

# Story 51-6：多 workflow 模板与创建时冻结

## 用户故事

作为不同类型任务的使用者，我希望产品、工程、迁移和安全任务可选择合适流程，同时所有流程仍由同一 Runner 执行。

## 验收标准

- 创建 Goal 时可选择受支持的 workflow 包。
- workflow id、revision/hash 在创建时写入元数据并冻结。
- 执行中资源漂移、缺失或 hash 不匹配时显式阻断，不静默切换。
- 老 Goal 没有新元数据时按兼容规则绑定 `he-goal`。
- workflow 包只能声明步骤/Gate/角色/资源，不得自带第二状态机或直接执行工具。
- doctor 能预检所选 workflow 的完整依赖。

## 任务

- [ ] 扩展创建命令和 Goal 元数据。
- [ ] 复用 SkillPackage manifest/lock 完整性通道。
- [ ] 增加 product/engineering/migration/security 包或最小可验证样例。
- [ ] 补旧 Goal 兼容、漂移阻断和创建时冻结测试。
- [ ] 更新使用文档，说明 workflow 不可在运行中静默切换。

## 验证命令（规划，执行时亲跑）

```bash
pytest tests/test_goal_workflow_selection.py tests/test_workflow_loader.py tests/test_skill_packages.py -q
pytest tests/test_goal_application.py tests/test_architecture_contracts.py -q
ruff check src tests
mypy src
mypy src --platform linux
```
