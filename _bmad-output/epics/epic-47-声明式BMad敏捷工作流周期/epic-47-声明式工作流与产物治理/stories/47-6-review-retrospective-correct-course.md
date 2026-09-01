---
title: 'Close the Agile review retrospective and correction loop'
type: 'feature'
status: 'done'
epic: 47
story: 6
---

# Story 47-6: Review、Retrospective、Correct Course

## Acceptance Criteria

- [x] Review 发现问题时 Story 可回到 implementation 并保留证据。
- [x] Epic 完成后生成基于证据的 retrospective。
- [x] 重大变更能生成 correct-course 记录并回到正确阶段。

## Verification

- `pytest tests/test_agile_closure.py tests/test_engine_workflow.py tests/test_workflow_runner.py -q --basetemp E:/AI/HeAgent/workflow_test_tmp47_6` -- 30 passed.
- `ruff check src tests` -- passed.

## Dependencies

47-5
