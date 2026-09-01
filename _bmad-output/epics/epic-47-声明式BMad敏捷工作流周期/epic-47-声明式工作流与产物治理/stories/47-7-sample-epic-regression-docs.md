---
title: 'Validate sample Epic and close documentation'
type: 'feature'
status: 'done'
epic: 47
story: 7
---

# Story 47-7: 样例 Epic、回归测试和文档

## Acceptance Criteria

- [x] 一个两 Story 样例 Epic 可从规划跑到 done。
- [x] 覆盖产物契约、gate、review 回退、checkpoint/resume 和旧模式回归。
- [x] `docs/frame.md`、使用文档和 Epic 总览与实现一致。

## Verification

- `pytest tests/test_goal_epic_story_smoke.py tests/test_goal_declarative_workflow.py tests/test_artifact_contracts.py tests/test_agile_closure.py -q --basetemp E:/AI/HeAgent/workflow_test_tmp47_7` -- 12 passed.
- `ruff check src tests` -- passed.

## Dependencies

47-6
