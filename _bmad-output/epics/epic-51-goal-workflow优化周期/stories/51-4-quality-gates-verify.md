---
id: 51-4
title: 真实质量 Gate 与 goal verify
status: ready-for-dev
parent_epic: E51
priority: P0
depends_on: [51-3]
blocks: [51-6, 51-8]
created: '2026-09-29'
---

# Story 51-4：真实质量 Gate 与 `/goal verify`

## 用户故事

作为 Goal 负责人，我希望完成判定依赖真实 Evidence，以便未运行测试或运行失败的 Story 不能推进。

## 验收标准

- workflow 可声明必需产物、命令、Git 路径和质量门。
- 声称命令通过但没有匹配 `CommandEvidence` 时 Gate 失败。
- 非零退出码、错误 cwd、过期证据或证据不属于当前 Story 时进入 `BLOCKED`。
- `/goal verify` 只重跑/检查声明的验证，不重新执行实现步骤，不伪造完成状态。
- 旧 workflow 未声明结构化 Gate 时保持原文本 Gate 行为。
- workflow 不能降低宿主强制质量门或绕过工具治理链。

## 任务

- [ ] 扩展 `WorkflowStepResource` 的向后兼容 validation 模型。
- [ ] 新增 `goal/quality_gates.py`。
- [ ] 实现 `/goal verify` 与结构化报告。
- [ ] 增加缺证据、失败证据、错误归属、旧语义兼容测试。
- [ ] 负向验证“只写 Markdown 就通过”的变异体必须红。

## 验证命令（规划，执行时亲跑）

```bash
pytest tests/test_goal_quality_gates.py tests/test_goal_evidence.py tests/test_workflow_loader.py -q
pytest tests/test_engine_workflow.py tests/test_architecture_contracts.py -q
ruff check src tests
mypy src
mypy src --platform linux
```
