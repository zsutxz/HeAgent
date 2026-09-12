# 47-9 实现说明

`WorkflowRunner` 增加受 `max_parallel_stories` 限制的 Story 批次执行。Runner 从第一个未完成
Epic 中按 Story 顺序选取批次，使用 `asyncio.gather` 并发调用独立 callback；当前 Epic 未完成前
不会选择下一个 Epic。默认上限为 1 时仍走原有逐 Story 路径。

