# Epic 51 Deferred Work

> 归档来源：`implementation-artifacts/deferred-work-archive.md` 的 A25、A26、A27、A28、A33。以下条目均已闭合，保留摘要和证据入口；当前活动项无。

| ID | 主题 | 结论 | 主要证据 |
| --- | --- | --- | --- |
| A25 | checkpoint id 中已删除并行批次后缀 | 删除运行期分支；旧格式容忍读，新写入格式不冲突 | `tests/test_story_loop.py::test_legacy_parallel_checkpoint_id_recovers_and_rewrites_new_format` |
| A26 | `active_stories` 镜像字段 | 三个状态模型删除镜像字段，消费方现场派生，旧盘键容忍读 | `tests/test_story_scheduling_integration.py` |
| A27 | CLI 与 Runner 重复的事件隔离包装 | 收敛为 Runner 单一包装，CLI 只传扩展字段 | `tests/test_workflow_runner.py::test_emit_isolation_covers_hostile_duck_step_and_story` |
| A28 | `/goal verify` 手写台账审计生命周期 | `LedgerAudit` 下沉到 engine，覆盖续租、完成、失败和策略阻断 | `tests/test_engine_p0.py::test_audit_covers_the_policy_blocked_path`、`TestLedgerAudit` |
| A33 | `artifact_refs` 镜像与 dispatch 前导重复 | 镜像字段删除，dispatch 统一使用 `_goal_bound_workflow()` | Goal CLI/锁/决策回归测试 |

详细当前行为见 [`docs/frame.md`](../../../docs/frame.md) 和 [`docs/goal-workflow.md`](../../../docs/goal-workflow.md)；历史完整证据由提交记录和测试保留。
