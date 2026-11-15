# 47-10 故事报告

## 实现摘要

Checkpoint 新增活动 Story 列表和逐 Story 状态，兼容旧 `active_story` 快照；批次恢复不会重复已完成 Story。

## 测试证据

相关回归：73 passed；定向最终回归：34 passed。`ruff check`、`mypy`、`git diff --check` 均通过。

## 验证结论

通过。成功、失败和恢复状态均可持久化；Step 08 集成边界保持不变。

