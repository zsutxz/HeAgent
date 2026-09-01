---
title: 'Generic workflow runner and artifact gates'
type: 'feature'
status: 'backlog'
epic: 47
story: 4
---

# Story 47-4: 通用 WorkflowRunner 与阶段 Gate

## Acceptance Criteria

- [ ] Runner 一次只执行一个 step，并按 Markdown 声明顺序推进。
- [ ] 输入、输出、章节、验收和 Definition of Ready/Done 均可验证。
- [ ] checkpoint、waiting_user、blocked、failed 均可恢复且不伪造完成。

## Dependencies

47-2, 47-3
