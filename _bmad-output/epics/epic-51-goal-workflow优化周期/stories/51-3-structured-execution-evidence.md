---
id: 51-3
title: 结构化执行证据模型
status: ready-for-dev
parent_epic: E51
priority: P0
depends_on: [51-2]
blocks: [51-4, 51-8]
created: '2026-09-29'
---

# Story 51-3：结构化执行证据模型

## 用户故事

作为交付审核者，我希望 Story 报告能引用真实命令和 Git 变更证据，以便“测试通过”不是模型自述。

## 验收标准

- 新增 Pydantic `EvidenceRecord`、`CommandEvidence`、`GitEvidence`、`QualityGateEvidence`。
- 成功、失败、超时、取消、策略阻断均形成明确证据。
- 命令证据含 cwd、退出码、耗时、命令摘要、输出 digest/有界脱敏摘要和失败分类。
- Git 证据含 base/head、tracked diff、未跟踪文件；不执行 commit。
- Evidence 与 `goal_id/story_id/workflow_id/revision` 绑定，不能跨 Story 冒用。
- 明文凭证不进入 evidence；输出有大小上限。
- Markdown 报告只能引用 evidence id，不能构造等价原始 dict 伪装。

## 任务

- [ ] 在 `goal/evidence.py` 定义版本化模型与持久化位置。
- [ ] 从现有受治理执行结果生成证据，不新增绕过 ToolExecutor 的命令入口。
- [ ] 接入 Git 只读工具或等价只读端口生成变更集。
- [ ] 增加 evidence 与报告互相定位、跨 Story 拒绝、脱敏和上限测试。
- [ ] 变异验证退出码、cwd、Story 绑定与脱敏守卫。

## 验证命令（规划，执行时亲跑）

```bash
pytest tests/test_goal_evidence.py tests/test_tool_executor.py tests/test_safe_logging.py -q
pytest tests/test_architecture_contracts.py -q
ruff check src tests
mypy src
mypy src --platform linux
```
