---
title: 'Migrate and customize key BMad agents'
type: 'feature'
status: 'done'
epic: 47
story: 2
baseline_commit: '5775334'
context:
  - 'E:/AI/HeAgent/AGENTS.md'
  - 'E:/AI/HeAgent/_bmad/_config/skill-manifest.csv'
  - 'E:/AI/HeAgent/.agents/skills/bmad-agent-pm/SKILL.md'
  - 'E:/AI/HeAgent/.agents/skills/bmad-agent-analyst/SKILL.md'
  - 'E:/AI/HeAgent/.agents/skills/bmad-agent-architect/SKILL.md'
  - 'E:/AI/HeAgent/.agents/skills/bmad-agent-ux-designer/SKILL.md'
  - 'E:/AI/HeAgent/.agents/skills/bmad-agent-dev/SKILL.md'
---

# Story 47-2: 关键 BMad Agent 迁移

## Acceptance Criteria

- [x] PM、Analyst、Architect、UX、Dev 五个角色各有独立可读的本地 `SKILL.md`。
- [x] 每个 Agent 声明输入、输出、职责边界、检查清单和停止条件。
- [x] BMad source ID 与 HeAgent canonical ID 可追踪，资源读取受包根目录围栏保护。

## Tasks

- [x] `.heagent/skills/he-agent-pm/` -- 复制并定制 BMad PM skill，声明 Goal/PRD/Epic 输入输出与决策边界。
- [x] `.heagent/skills/he-agent-analyst/` -- 复制并定制 Analyst skill，声明需求澄清、验收标准和 Story 拆分职责。
- [x] `.heagent/skills/he-agent-architect/` -- 复制并定制 Architect skill，声明架构不变量、依赖和设计产物。
- [x] `.heagent/skills/he-agent-ux/` -- 复制并定制 UX skill，声明用户流程、状态和异常路径产物。
- [x] `.heagent/skills/he-agent-dev/` -- 复制并定制 Dev skill，声明 Story 实现、测试和 Definition of Done。
- [x] `tests/test_bmad_agent_packages.py` -- 验证五个包的 frontmatter、canonical/source ID、角色边界和资源路径安全。

## Definition Of Done

- [x] 五个 Agent 包可被 SkillCatalog 发现
- [x] source ID、canonical ID 和 aliases 可追踪
- [x] 角色 skill 不直接推进 Goal phase
- [x] 测试、ruff 和 mypy 通过

## Dev Agent Record

### Completion Notes

- 从 `_bmad/_config/skill-manifest.csv` 对应 BMad Agent skill 迁移并定制 PM、Analyst、Architect、UX、Dev 五个本地包。
- 每个包保留 `source_id`，使用 `he-agent-*` canonical ID 和 aliases，并声明输入、输出、职责、决策边界、检查清单和停止条件。
- 所有角色明确不得推进 Goal phase；资源读取继续由 SkillPackage 根目录围栏保护。

### Verification Evidence

- `pytest tests/test_bmad_agent_packages.py -q --basetemp E:/AI/HeAgent/workflow_test_tmp47_2` -- 11 passed。
- `ruff check src tests` -- passed。
- `python -m compileall -q src tests` -- passed。
- `mypy src` -- passed，98 source files。

## Dependencies

47-1
