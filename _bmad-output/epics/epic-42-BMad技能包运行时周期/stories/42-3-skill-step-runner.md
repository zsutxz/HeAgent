---
title: "Story 42.3 单技能步骤运行器"
type: feature
created: "2026-09-01"
status: done
---

## 目标

为声明式技能提供确定性、可恢复的单步运行器。每次调用只加载并执行当前步骤；等待、阻塞和失败结果保留当前步骤，不会静默推进。

## 已交付

- 新增 `SkillStep`、`SkillStepResult` 和可序列化的 `SkillRunnerState` 模型。
- 新增 `SkillRunner`，显式支持 `pending`、`waiting_user`、`blocked`、`completed`、`failed` 状态。
- 通过现有 `SkillPackage` 根目录围栏校验步骤路径。
- 支持异步和同步回调、终态幂等，以及非法状态显式报错。
- 增加暂停/恢复、顺序推进、非法索引和失败保留的边界测试。

## 验证

- `pytest tests/test_skill_packages.py tests/test_memory.py tests/test_skill_tools.py`: 68 passed, 2 skipped.
- `ruff check src/heagent/memory/skill_packages.py tests/test_skill_packages.py`: passed.
- `mypy src/heagent/memory/skill_packages.py`: passed.
- Full suite reached 633 passed before two unrelated existing `tests.test_epic35` failures caused by `ModuleNotFoundError: tests`.
