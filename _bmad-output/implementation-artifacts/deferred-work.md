- source_spec: `_bmad-output/epics/epic-47-声明式BMad敏捷工作流周期/epic-47-声明式工作流与产物治理/stories/47-1-artifact-hierarchy-contract.md`
  summary: 修复 Windows Hook 超时路径未及时回收子进程导致的长时间阻塞。
  evidence: 全量 pytest 中 `tests/test_hooks.py::TestHookTimeout::test_timeout_blocks_and_returns_promptly` 失败，超时路径耗时约 10 秒；本 Story 未修改 hooks.py 或相关执行逻辑。
