---
title: 'Integrate Goal CLI with Epic Story Sprint workflow'
type: 'feature'
status: 'backlog'
epic: 47
story: 5
---

# Story 47-5: `/goal` 接入 Goal/Epic/Story/Sprint

## Acceptance Criteria

- [ ] `/goal new|next|run|status|pause|resume|audit` 支持 declarative workflow。
- [ ] 新模式按 Epic、Sprint、Story 和 gate 推进，旧 GOAL.md-only 模式保持兼容。
- [ ] 并发、Ctrl+C、cron 和恢复不会重复完成 Story。

## Dependencies

47-4
