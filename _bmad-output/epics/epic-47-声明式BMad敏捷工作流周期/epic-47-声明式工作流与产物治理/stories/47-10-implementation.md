# 47-10 实现说明

checkpoint 新增 `active_stories` 与 `story_statuses`，Runner 状态保留旧 `active_story` 以兼容历史快照。
批次启动先持久化 running 状态；每条 Story 完成、失败或输出校验失败后分别记录状态和结果。
恢复时从 `completed_stories` 与 `story_outputs` 继续，已完成 Story 不会重复调用 callback。

