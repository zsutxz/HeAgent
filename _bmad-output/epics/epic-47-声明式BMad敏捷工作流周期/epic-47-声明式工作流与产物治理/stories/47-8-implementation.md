# 47-8 实现说明

`WorkflowStepResource` 新增 `max_parallel_stories`，默认值为 `1`，模型范围限制为 `1..5`。
外部 step frontmatter 和 inline workflow 均通过同一严格解析规则处理；非法值会抛出
`SkillWorkflowError`，不进行静默纠正。默认值确保未声明并行参数的既有工作流继续串行执行。

