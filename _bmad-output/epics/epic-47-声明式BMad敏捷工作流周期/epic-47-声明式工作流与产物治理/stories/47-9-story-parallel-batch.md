---
id: 47-9
title: Step 07 同 Epic Story 批次并行
status: done
parent_epic: E47
priority: P0
depends_on: 47-8
---

# 47-9 Step 07 同 Epic Story 批次并行

## 用户故事

作为目标工作流执行者，我希望同一 Epic 中互不依赖的 Story 按配置并发执行，同时保证 Epic 之间严格串行。

## 范围

- 以 `StorySpec.epic` 分组；每次只选择第一个未完成 Epic。
- 在该 Epic 内最多启动 `max_parallel_stories` 个 Story callback。
- 结果按 Story 顺序稳定收集；单个 callback 异常不取消同批其他 Story。
- 缺少 Epic 标识时保持旧串行兼容，不把未知 Story 混入并行批次。

## 验收标准

- Given 同一 Epic 有 3 条 ready Story 且上限为 2，when 执行批次，then 同时运行数不超过 2，并在两批完成。
- Given 还有未完成的 E1 Story，when E2 Story 已 ready，then E2 不会启动。
- Given 同批一条 Story 失败，when 批次结束，then 其他 Story 的成功结果保留，失败结果显式返回。
- Given 上限为 1，when 执行 Story loop，then 行为与当前逐 Story 串行一致。

## DoD

- `WorkflowRunner` 支持批次执行入口并保留 `run_step` 兼容行为。
- 调度不跨 Epic，不依赖模型决策。
- 有并发上限、Epic 串行、稳定顺序和部分失败测试。

## 代码地图

- `src/heagent/engine/workflow_runner.py`：Story 分组、批次选择和异步执行。
- `tests/test_story_loop.py`：并发行为与失败隔离测试。

## 验证

- `pytest tests/test_story_loop.py -q`
