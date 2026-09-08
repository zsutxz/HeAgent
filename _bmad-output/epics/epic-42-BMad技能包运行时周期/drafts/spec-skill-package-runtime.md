---
title: '技能包运行时'
type: 'feature'
created: '2026-08-31'
status: 'draft'
review_loop_iteration: 0
context:
  - 'E:\\AI\\HeAgent\\docs\\frame.md'
  - 'E:\\AI\\HeAgent\\_bmad-output\\epics\\epic-47-声明式BMad敏捷工作流周期\\bmad-heagent-plan.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 当前 `SkillStore` 只支持单个 `SKILL.md` 的学习型技能，无法发现 BMad manifest、读取 step/references/templates/scripts，也没有 canonical ID、版本或来源校验，导致 `/goal` 只能硬编码路径。

**Approach:** 新增独立的技能包运行时：从 manifest、项目技能和用户技能建立可验证目录；以 `he-*` 为 canonical ID、保留 `bmad-*` 别名；按需读取入口和资源；提供确定性的解析、单步运行状态和导入锁文件，同时保持现有 `SkillStore` CRUD 与自动匹配行为不变。

## Boundaries & Constraints

**Always:** 使用 Pydantic 模型承载跨模块数据；所有资源路径解析后必须位于包根目录；显式技能 ID 优先于自动匹配；导入记录源路径、版本/来源标识和文件哈希；只加载当前 step 及其直接引用；错误显式返回，不静默回退；新模块不得从 `agent/` 反向导入。

**Ask First:** 无额外决策；若实现中发现必须改变现有 `SkillStore` 公共 API 或 `/goal` 行为，先停止并请求确认。

**Never:** 不复制整套 BMad 同步运行时；不把原始 dict 作为模块间契约；不允许 `..`、绝对路径或符号链接越过包根；不一次性把整个技能目录注入 LLM；不删除或重命名现有学习型技能。

## I/O & Edge-Case Matrix

| 场景 | 输入 / 状态 | 期望行为 | 错误处理 |
|---|---|---|---|
| 正常发现 | 合法 manifest，入口和资源均在包根 | 返回 `he-*` 包及 `bmad-*` 别名 | N/A |
| 显式别名 | 请求 `bmad-prd` | 解析到唯一 `he-prd` | 别名冲突显式失败 |
| 缺入口 | 包目录无 `SKILL.md` | 包不可用且不进入候选 | 返回可诊断错误 |
| 路径越界 | step 引用 `../secret` 或绝对路径 | 拒绝读取 | 返回路径安全错误 |
| 导入重复 | 相同源哈希已在 `manifest.lock` | 幂等跳过并保留锁记录 | 锁损坏则显式失败 |

</frozen-after-approval>

## Code Map

- `src/heagent/memory/skills.py:28-176` -- 现有 `SkillContent`/`SkillStore` CRUD、入口文件格式和兼容边界；不得破坏其 API。
- `src/heagent/memory/skills.py:282-337` -- 当前轻量 frontmatter/正文解析器；新包解析可复用字段语义，但需独立支持 BMad 元数据。
- `src/heagent/cli.py:954-1052,1331-1418` -- `/goal` 当前固定读取 `.heagent/skills/goal/SKILL.md` 的路径和错误语义；本故事只提供可注入运行时，不直接重写 goal 编排。
- `_bmad/_config/skill-manifest.csv` -- BMad 技能来源清单，包含 canonicalId、描述、模块和逻辑路径；导入器必须解析并校验路径。
- `src/heagent/tools/path_safety.py:120-180` -- 工作区路径围栏约定；包资源校验应采用同类 `resolve/is_relative_to` 防御。
- `tests/test_memory.py:10-115`、`tests/test_skill_tools.py:1-145` -- 现有技能行为回归测试位置。

## Tasks & Acceptance

**Execution:**
- [ ] `src/heagent/memory/skill_packages.py` -- 定义 `SkillManifestEntry`、`SkillPackage`、`SkillCatalog`、`SkillResolver`、`SkillRunner` Pydantic/运行时模型，提供发现、别名解析、资源按需读取和 step 状态迁移。
- [ ] `src/heagent/memory/skill_importer.py` -- 解析 manifest，映射实际源路径到 `he-*` 目录，校验包根和文件哈希，幂等写入 `.heagent/skills/manifest.lock`。
- [ ] `tests/test_skill_packages.py` -- 覆盖发现、别名优先级、缺入口、路径穿越、按需资源和 runner 状态/错误语义。
- [ ] `tests/test_skill_importer.py` -- 覆盖 manifest 映射、哈希锁、重复导入和非法源路径。

**Acceptance Criteria:**
- Given 合法 BMad manifest 和技能目录，当 catalog 扫描时，then 返回可用 `he-*` 包并可由原始 `bmad-*` 别名唯一解析。
- Given step 引用包外路径，当资源读取时，then 操作被拒绝且错误包含越界路径，不读取目标文件。
- Given runner 当前 step 未完成，当运行一次后，then 只加载该 step，状态可序列化为 `waiting_user`、`blocked`、`completed` 或 `failed`，且不会自动跳步。
- Given 已存在相同源哈希的锁记录，当重复导入时，then 不重复复制并保持锁文件内容稳定。
- Given 现有 SkillStore 测试集，当运行回归测试时，then 原有 CRUD、匹配和 AgentLoop 技能注入行为全部保持通过。

## Design Notes

`SkillCatalog` 只负责索引和解析元数据，`SkillPackage` 负责包根内资源访问，`SkillResolver` 负责确定性 ID/阶段候选，`SkillRunner` 只推进一个技能的一次 step；导入器负责物化和锁定来源。这样可以让后续 `WorkflowOrchestrator` 注入 runner，而不让技能包自行改变 Goal 阶段。

## Verification

**Commands:**
- `pytest tests/test_skill_packages.py tests/test_skill_importer.py tests/test_memory.py tests/test_skill_tools.py` -- expected: 全部通过。
- `ruff check src/heagent/memory tests/test_skill_packages.py tests/test_skill_importer.py` -- expected: 无 lint 错误。
- `mypy src/heagent/memory/skill_packages.py src/heagent/memory/skill_importer.py` -- expected: 类型检查通过。
