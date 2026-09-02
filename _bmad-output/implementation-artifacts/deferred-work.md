- source_spec: `_bmad-output/epics/epic-47-声明式BMad敏捷工作流周期/epic-47-声明式工作流与产物治理/stories/47-1-artifact-hierarchy-contract.md`
  summary: 修复 Windows Hook 超时路径未及时回收子进程导致的长时间阻塞。
  evidence: 全量 pytest 中 `tests/test_hooks.py::TestHookTimeout::test_timeout_blocks_and_returns_promptly` 失败，超时路径耗时约 10 秒；本 Story 未修改 hooks.py 或相关执行逻辑。
- source_spec: `_bmad-output/implementation-artifacts/spec-documentation-cleanup.md`
  summary: 审查并优化源码模块拆分与跨模块职责边界。
  evidence: 本次整理范围包含代码和模块拆分；为降低文档整理首轮的变更面，延后到独立阶段处理。
- source_spec: `_bmad-output/implementation-artifacts/spec-documentation-cleanup.md`
  summary: 整理测试文件分组、命名、重复覆盖与覆盖缺口。
  evidence: 本次整理范围包含测试文件；测试结构与代码拆分存在耦合，延后到代码模块阶段同步处理。
- source_spec: none
  summary: 整理测试文件分组、命名、重复覆盖与覆盖缺口。
  evidence: 本轮按用户选择先处理代码模块拆分，测试结构作为独立阶段推进，避免测试迁移与生产代码重构同时扩大回归面。
