---
id: 47-8
title: Step 07 同 Epic 并行参数
status: done
parent_epic: E47
priority: P0
depends_on: none
---

# 47-8 Step 07 同 Epic 并行参数

## 用户故事

作为工作流维护者，我希望在 Step 07 声明同一 Epic 的最大并行 Story 数量，以便控制吞吐并保持旧配置的串行兼容。

## 范围

- 增加 `max_parallel_stories` 步骤参数。
- 缺省值为 `1`；允许值为整数 `1..5`。
- 非法值在工作流加载时显式失败，不静默修正。
- 参数只限制同一个 Epic 内的并发度，不允许跨 Epic 并发。

## 验收标准

- Given Step 07 未声明参数，when 工作流加载，then `max_parallel_stories == 1`。
- Given 参数为 `1`、`3` 或 `5`，when 工作流加载，then 解析成功并保留整数值。
- Given 参数小于 `1`、大于 `5`、非整数或空值，when 工作流加载，then 抛出明确的工作流契约错误。

## DoD

- `WorkflowStepResource` 有类型化字段和范围校验。
- 外部步骤文件与 inline workflow 两种加载路径行为一致。
- 有解析和边界测试，未改变已有串行 Story 行为。

## 代码地图

- `src/heagent/memory/skill_packages.py`：工作流步骤模型与 frontmatter 解析。
- `tests/test_workflow_resources.py`：声明加载与非法参数测试。

## 验证

- `pytest tests/test_workflow_resources.py -q`
