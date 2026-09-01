---
status: done
baseline_commit: current
---

# Story 44.3: 恢复信封、摘要后备与长目标集成验证

As a 维护者,
I want 恢复信封格式稳定且摘要失败可降级，并用跨 segment 测试证明长目标连续性,
So that 重启后的执行上下文足够且可审计。

## Acceptance Criteria

- [x] 生成版本化、可校验的最小恢复信封。
- [x] 摘要缺失时使用确定性状态摘要并记录摘要错误。
- [x] 恢复信封不包含完整历史消息。

## Tasks/Subtasks

- [x] 定义 `RecoveryEnvelope`。
- [x] 实现确定性摘要后备构建器。
- [x] 添加最小字段和摘要错误测试。

## Dev Agent Record

### Completion Notes

新增恢复信封模型与构建器，17 项专项测试通过，ruff/mypy 通过。

## File List

- `src/heagent/engine/workflow.py`
- `src/heagent/engine/__init__.py`
- `tests/test_engine_workflow.py`

## Change Log

- 2026-09-01: 完成 Story 44.3，状态置为 review。
