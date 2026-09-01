---
title: "Story 42.5 兼容回归与运行时集成验证"
type: feature
created: "2026-09-01"
status: done
---

## 已交付

- 验证 `SkillStore` CRUD、关键词匹配和技能工具行为未改变。
- 验证 `AgentLoop` 技能自动匹配、系统提示词注入和空技能行为保持兼容。
- 验证 `/goal` 固定路径读取、缺失错误和原有子命令行为保持兼容。
- 增加 `tests/__init__.py`，修复既有测试跨模块 fixture 导入缺少包标记的问题。

## 验证结果

- `pytest tests/test_memory.py tests/test_skill_tools.py tests/test_agent_loop.py tests/test_goal_command.py`：115 通过。
- `pytest tests/test_epic35.py`：7 通过。
- Epic 42 专项回归（导入器、技能包、记忆和技能工具）：75 通过，2 跳过。
- `ruff check src/heagent/memory tests`：通过。
- `mypy src/heagent/memory`：通过。

全量测试仍有一个与 Epic 42 无关的 Windows hook 超时回收问题：`tests/test_hooks.py::TestHookTimeout::test_timeout_blocks_and_returns_promptly`，超时命令未在 5 秒内回收。该问题不涉及本 Epic 的代码路径。
