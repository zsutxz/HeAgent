# 47-9 故事报告

## 实现摘要

Runner 在同一 Epic 内按上限批量并发 Story；跨 Epic 严格串行；单条异常不会取消同批其他 Story。

## 测试证据

`pytest tests/test_story_loop.py -q`：通过。覆盖并发上限、跨 Epic 顺序、串行兼容和失败隔离。

## 验证结论

通过。缺少 Epic 标识时回退到既有串行路径。

