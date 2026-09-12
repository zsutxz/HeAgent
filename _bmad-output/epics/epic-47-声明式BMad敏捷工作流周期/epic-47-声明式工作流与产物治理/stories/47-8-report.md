# 47-8 故事报告

## 实现摘要

新增 `max_parallel_stories` 声明，默认 1，严格限制为 1..5；外部 step 与 inline workflow 一致解析。

## 测试证据

`pytest tests/test_workflow_resources.py -q`：通过。覆盖默认值、合法边界和非法输入。

## 验证结论

通过。未声明参数的既有工作流保持串行兼容。

