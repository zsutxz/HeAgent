---
title: 'Story 42.1 技能包模型与资源路径安全'
type: 'feature'
created: '2026-08-31'
status: 'done'
baseline_commit: '3c4faeba720c45236ec734718a67bd39340cab9e'
review_loop_iteration: 0
context:
  - 'E:\\AI\\HeAgent\\docs\\frame.md'
  - 'E:\\AI\\HeAgent\\_bmad-output\\epics\\epic-47-声明式BMad敏捷工作流周期\\bmad-heagent-plan.md'
  - 'E:\\AI\\HeAgent\\_bmad-output\\epics\\epic-42-BMad技能包运行时周期\\epics.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** HeAgent 当前 `SkillStore` 只能读取单个 `SKILL.md`，没有可验证的技能包模型，也不能安全按需读取 step、references、templates、assets 或 scripts。

**Approach:** 新增独立的 `SkillPackage` 模型和资源访问 API。包根目录先规范化，所有入口、step 和附属资源都通过同一根目录围栏解析；缺少入口、非法路径或越界符号链接显式失败。实现位于 `memory`，不依赖 `agent`，并保留现有 `SkillStore` API。

## Boundaries & Constraints

**Always:** 使用 Pydantic 模型；资源按需读取；包根使用 `resolve_under_root` 语义；错误包含技能 ID、资源路径和原因；只读取当前请求的资源。

**Ask First:** 若必须改变 `SkillStore` 公共 API、修改 `/goal` 固定路径行为或引入新依赖，停止并请求确认。

**Never:** 不实现 catalog、resolver、runner、manifest importer 或 Goal 编排；不允许绝对路径、`..` 越界或越界符号链接；不把整包内容注入 AgentLoop；不把路径校验描述为 OS 级安全边界。

## I/O & Edge-Case Matrix

| 场景 | 输入 / 状态 | 期望行为 | 错误处理 |
|---|---|---|---|
| 正常入口 | 包根含 `SKILL.md` | 返回入口文本和元数据 | N/A |
| 按需资源 | 请求包内相对 step/reference | 只读取该文件 | 缺失时显式报错 |
| 路径越界 | 绝对路径或 `../secret` | 拒绝读取 | 抛出可诊断包资源错误 |
| 符号链接越界 | 包内链接指向包根外 | 拒绝读取 | 抛出路径安全错误 |
| 缺入口 | 无 `SKILL.md` | 包不可用 | 不生成空包 |

</frozen-after-approval>

## Code Map

- `src/heagent/memory/skills.py:28-176` -- 现有 `SkillContent`/`SkillStore` CRUD 和 `SKILL.md` 兼容格式；保持公共行为不变。
- `src/heagent/memory/skills.py:282-337` -- 轻量 frontmatter 解析器；可复用字段语义，但新模型不得修改旧解析契约。
- `src/heagent/tools/path_safety.py:54-70` -- `resolve_under_root` 根目录围栏算法；包根先 `resolve()`，可选资源用 `strict=False`。
- `src/heagent/engine/persist.py:112-145` -- 原子持久化工具；本 Story 不新增锁文件，但测试/模型应遵循现有编码和错误风格。
- `tests/test_memory.py:10-110` -- 现有 SkillStore 回归测试，作为零回归基线。

## Tasks & Acceptance

**Execution:**
- [x] `src/heagent/memory/skill_packages.py` -- 定义 `SkillPackage`、包元数据模型和资源错误类型；实现入口、step、references/templates/assets/scripts 的按需读取及根目录校验。
- [x] `tests/test_skill_packages.py` -- 添加正常读取、缺入口、缺资源、绝对路径、路径穿越、符号链接越界和按需读取测试。
- [x] `tests/test_memory.py` -- 运行并必要时补充现有 SkillStore 兼容回归，不改变旧 API 语义。

**Acceptance Criteria:**

- Given 合法包根含 `SKILL.md`，when 创建 `SkillPackage` 并读取入口，then 返回入口文本和结构化元数据。
- Given 请求包内相对 step 或 reference，when 读取资源，then 只打开该资源，不扫描或加载其他文件。
- Given 资源为绝对路径、包含 `..` 越界或经符号链接逃逸，when 读取，then 拒绝并返回包含技能 ID、路径和原因的显式错误。
- Given 包缺少 `SKILL.md` 或资源不存在，when 校验/读取，then 抛出可诊断错误，不生成空内容。
- Given 现有 SkillStore 和 AgentLoop 技能注入测试，when 运行回归，then 原有行为全部保持通过。

## Design Notes

`SkillPackage` 只负责包边界、入口元数据和资源读取，不负责技能发现、别名解析或执行推进。资源路径统一先拒绝绝对路径，再基于已解析包根调用 `resolve_under_root`；这样可复用项目既有围栏语义，同时避免接入 `check_read_denied` 对本地技能目录的内部状态限制。

## Verification

**Commands:**
- `pytest tests/test_skill_packages.py tests/test_memory.py tests/test_skill_tools.py` -- expected: 全部通过。
- `ruff check src/heagent/memory/skill_packages.py tests/test_skill_packages.py tests/test_memory.py` -- expected: 无 lint 错误。
- `mypy src/heagent/memory/skill_packages.py` -- expected: 类型检查通过。

## Dev Agent Record

### Implementation Plan

- 以 Pydantic 模型承载技能包元数据和入口结果。
- 统一通过已解析包根和 `resolve_under_root` 解析资源，额外拒绝 POSIX/Windows 绝对路径与父目录片段。
- 通过 `Path.is_file()` 和解析后的路径检查阻断缺失资源与越界符号链接，保持 `SkillStore` 独立不变。

### Completion Notes

- 新增 `SkillPackage`、`SkillPackageMetadata`、`SkillPackageEntry` 及可诊断错误类型。
- 支持入口、step、references、templates、assets、scripts 的按需读取和 frontmatter 元数据解析。
- 覆盖正常读取、缺失、跨平台绝对路径、路径穿越、符号链接逃逸和 lazy read 测试。
- 验证结果：目标回归 `49 passed, 1 skipped`；全量回归 `1343 passed, 4 skipped, 14 deselected`；全仓库 ruff 和 mypy 均通过。Windows 环境不支持创建符号链接的测试按条件跳过。

## File List

- `src/heagent/memory/skill_packages.py`
- `tests/test_skill_packages.py`
- `_bmad-output/epics/epic-42-BMad技能包运行时周期/stories/42-1-skill-package-model-resource-safety.md`

## Change Log

- 2026-08-31：完成 Story 42.1 技能包模型、按需资源读取和路径安全实现，状态更新为 review。

## Suggested Review Order

**包边界与路径校验**

- 先查看不可变包边界与统一资源读取入口，理解安全约束。
  [`skill_packages.py:55`](../../../../src/heagent/memory/skill_packages.py#L55)

- 检查跨平台绝对路径、父目录片段与根目录围栏的组合校验。
  [`skill_packages.py:118`](../../../../src/heagent/memory/skill_packages.py#L118)

- 检查入口和资源读取错误是否保留技能 ID、路径及明确原因。
  [`skill_packages.py:76`](../../../../src/heagent/memory/skill_packages.py#L76)

**按需资源与元数据**

- 检查目录辅助方法如何限制 references/templates/assets/scripts，避免重写危险输入。
  [`skill_packages.py:104`](../../../../src/heagent/memory/skill_packages.py#L104)

- 检查 frontmatter 元数据解析及版本、标签返回结构。
  [`skill_packages.py:144`](../../../../src/heagent/memory/skill_packages.py#L144)

**验证覆盖**

- 查看正常读取、错误诊断、路径越界、符号链接和 lazy read 测试。
  [`test_skill_packages.py:20`](../../../../tests/test_skill_packages.py#L20)
