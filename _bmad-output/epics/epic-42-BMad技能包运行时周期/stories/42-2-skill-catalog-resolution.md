---
title: 'Story 42.2 技能目录发现与 canonical/alias 解析'
type: 'feature'
created: '2026-08-31'
status: 'done'
baseline_commit: '0e84d5fb21780d440690f20c38f94273e0f777cb'
review_loop_iteration: 0
context:
  - 'E:\\AI\\HeAgent\\docs\\frame.md'
  - 'E:\\AI\\HeAgent\\_bmad-output\\epics\\epic-47-声明式BMad敏捷工作流周期\\bmad-heagent-plan.md'
  - 'E:\\AI\\HeAgent\\_bmad-output\\epics\\epic-42-BMad技能包运行时周期\\epics.md'
---

<frozen-after-approval reason="human-owned intent - do not modify unless human renegotiates">

## Intent

**Problem:** HeAgent 已能读取单个技能包，但还不能从 manifest、项目技能目录和用户技能目录建立稳定索引，也不能把 `bmad-*` 兼容别名确定性解析到唯一的 `he-*` 包。

**Approach:** 在 `memory` 层增加只读 `SkillCatalog` 与 `SkillResolver`，扫描显式来源目录中的合法 `SKILL.md` 包，解析 canonical/source/version/availability 元数据，并以显式 ID 优先、冲突显式失败的规则提供确定性解析。保留现有 `SkillStore` API，不接入 AgentLoop 或执行编排。

## Boundaries & Constraints

**Always:** 使用 Pydantic 模型承载跨模块数据；扫描结果按 canonical ID 稳定排序；包目录先 `resolve()`，资源和入口校验复用 `SkillPackage`；缺失或非法入口、canonical/alias 冲突必须返回带 ID 和路径的诊断错误；只扫描调用方明确提供的来源目录，不递归读取包内其他资源。

**Ask First:** 若实现需要改变 `SkillStore` 公共方法签名、AgentLoop 技能注入、`/goal` 固定路径或引入新的第三方依赖，停止并请求确认。

**Never:** 不实现 runner、workflow 状态机、manifest importer/lock 文件或自动执行；不允许绝对路径、父目录穿越或符号链接越过包根；不静默选择冲突候选；不把原始 `dict` 作为模块间契约。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|-----------------------------|----------------|
| HAPPY_PATH | 一个或多个来源目录含合法 `SKILL.md` | 返回稳定的 `SkillCatalogEntry` 列表，暴露 `he-*` canonical、source ID、版本和可用性 | N/A |
| ALIAS_RESOLVE | 请求 `he-prd` 或 `bmad-prd` | 两个 ID 解析到同一唯一包；显式 ID 优先自动匹配 | 未找到或多候选时抛出可诊断解析错误 |
| INVALID_PACKAGE | 来源条目缺少 `SKILL.md` 或入口元数据非法 | 条目标记不可用或从索引排除，其他合法条目仍可用 | 错误包含技能 ID、包路径和原因 |
| CONFLICT | canonical 或 alias 指向不同包 | 不返回任一候选 | 抛出明确冲突错误，列出冲突 ID/路径 |

</frozen-after-approval>

## Code Map

- `src/heagent/memory/skill_packages.py` -- 复用 `SkillPackage` 的根目录归一化、入口读取、metadata 解析和资源边界；新增索引对象不得复制路径围栏逻辑。
- `src/heagent/memory/skills.py` -- 既有 `SkillStore` CRUD、列表和关键词匹配 API；仅作为兼容回归基线，不修改其公共语义。
- `_bmad/_config/skill-manifest.csv` -- BMad 来源清单，字段含 source ID、描述、模块和逻辑路径；catalog 接受调用方提供的已映射目录，不在本 story 实现导入/物化。
- `src/heagent/tools/path_safety.py:resolve_under_root` -- 统一路径围栏算法；catalog 只接受已解析的包根并依赖 `SkillPackage` 做入口安全校验。
- `tests/test_skill_packages.py` -- 现有包边界和错误诊断测试；扩展或并列测试应保持其 lazy-read 与零回归约束。
- `tests/test_memory.py` -- `SkillStore` CRUD/匹配回归测试，验证新索引不会改变旧技能行为。

## Tasks & Acceptance

**Execution:**
- [x] `src/heagent/memory/skill_packages.py` -- 增加 `SkillCatalogEntry`、catalog 扫描和 resolver 确定性解析模型/API，复用 `SkillPackage`，并为不可用/冲突候选提供显式错误。
- [x] `tests/test_skill_packages.py` -- 覆盖多来源稳定索引、`he-*`/`bmad-*` 别名解析、显式优先、冲突、入口缺失和非法 metadata。
- [x] `tests/test_memory.py` -- 运行既有 `SkillStore` 回归，必要时补充 catalog 与旧 API 隔离断言。

**Acceptance Criteria:**
- Given 多个来源目录含合法包，when catalog 扫描，then 返回按 canonical ID 稳定排序且包含 source ID、版本和 availability 的索引。
- Given 请求 `he-name` 或其 `bmad-name` 别名，when resolver 解析，then 两者指向同一唯一 `SkillPackage`，显式 ID 不被自动匹配覆盖。
- Given canonical/alias 冲突、入口缺失或元数据非法，when 扫描或解析，then 显式失败并包含技能 ID、路径和原因，不静默选择候选。
- Given 现有 `SkillStore` 和 AgentLoop 技能测试，when 运行完整回归，then CRUD、关键词匹配和系统提示词注入行为保持通过。

## Design Notes

catalog 的职责是建立可观察索引，resolver 的职责是确定性选择；二者不执行技能。来源优先级只用于明确的同 ID 冲突诊断，不用于静默覆盖；相同 canonical 仅在包根完全相同且别名一致时去重。

## Verification

**Commands:**
- `pytest tests/test_skill_packages.py tests/test_memory.py tests/test_skill_tools.py` -- expected: all tests pass.
- `ruff check src/heagent/memory/skill_packages.py tests/test_skill_packages.py tests/test_memory.py` -- expected: no lint errors.
- `mypy src/heagent/memory/skill_packages.py` -- expected: type check passes.

## Suggested Review Order

**目录边界与索引**

- 扫描显式来源并排除归档目录
  [`skill_packages.py:229`](../../src/heagent/memory/skill_packages.py#L229)

- 将入口元数据映射为稳定标识
  [`skill_packages.py:249`](../../src/heagent/memory/skill_packages.py#L249)

**解析与诊断**

- canonical 优先且别名失败可诊断
  [`skill_packages.py:309`](../../src/heagent/memory/skill_packages.py#L309)

- 覆盖冲突和不可用包边界
  [`test_skill_packages.py:157`](../../tests/test_skill_packages.py#L157)
