---
stepsCompleted: [step-01-validate-prerequisites, step-02-design-epics, step-03-create-stories, step-04-final-validation]
inputDocuments:
  - '{project-root}/_bmad-output/epics/epic-47-声明式BMad敏捷工作流周期/bmad-heagent-plan.md'
  - '{project-root}/docs/frame.md'
  - '{project-root}/docs/design.md'
  - '{project-root}/_bmad-output/epics/epic-41-目标驱动开发周期/epics.md'
  - '{project-root}/_bmad-output/epics/epic-41-目标驱动开发周期/epic-41-context.md'
---

# heagent - Epic Breakdown

## Overview

本文件记录 HeAgent 将 BMad 目标级敏捷工作流承载到现有异步 Agent 框架的需求、Epic 与 Story 拆分，供后续开发和验收使用。

## Requirements Inventory

### Functional Requirements

FR1: 技能运行时必须从 BMad manifest、项目技能目录和用户技能目录发现技能包，并提供稳定的索引。
FR2: 技能必须使用 `he-<name>` canonical ID；原始 `bmad-<name>` 作为来源 ID 或兼容别名解析到唯一 canonical 技能，显式技能名优先于自动匹配。
FR3: 技能包必须包含可解析的 `SKILL.md`，并支持按需读取 workflow、step、references、templates、assets 和 scripts 等直接资源。
FR4: 所有技能资源路径解析后必须限制在包根目录内；绝对路径、路径穿越和越界符号链接必须被拒绝。
FR5: 技能运行时必须按 step 顺序推进单个技能运行，支持 `waiting_user`、`blocked`、`completed` 和 `failed` 状态，不能自动跳过未完成步骤。
FR6: BMad 导入器必须根据 manifest 映射实际源目录，复制或物化 canonical 技能包，并记录版本、来源路径和源文件哈希。
FR7: 导入必须幂等；相同源哈希不重复写入，源文件缺失、manifest 重复或锁文件损坏必须显式失败。
FR8: 新运行时必须与现有 `SkillStore` 的 CRUD、关键词匹配和 AgentLoop 技能注入行为兼容，不删除或重命名学习型技能。

### NonFunctional Requirements

NFR1: 跨模块数据使用 Pydantic 模型；库代码遵守 Python 3.11+、异步 I/O、标准 logging 和 120 列规范。
NFR2: `memory` 技能模块不得反向导入 `agent`；运行器通过协议/回调与 AgentLoop 组合，保持现有模块 DAG。
NFR3: 技能内容、工具输出和外部 MCP 均视为不可信；路径围栏是 defense-in-depth，不得被描述为 OS 级安全边界。
NFR4: 资源采用按需加载，不能把整个 BMad 技能目录注入每次 LLM 请求；错误和阻塞原因必须可诊断、可审计。
NFR5: 现有行为必须零回归；新增目录映射、别名、路径安全、状态机、导入锁和损坏输入均需单元测试。
NFR6: 方法论保持声明式：工作流顺序和 step 约束由 Markdown/配置定义，不能复制成散落的 Python 特殊分支。

**资源读取竞态说明（Epic 46.1）：** `SkillPackage` 的 `resolve_under_root` 围栏仍拒绝绝对路径、路径穿越
和解析后越界符号链接，但“解析/检查 -> `read_text()`”之间的文件替换窗口已由特征测试证实。该围栏是
defense-in-depth，不是 OS 安全边界；descriptor-relative/目录句柄、导入 snapshot 或 OS sandbox 的加固
不在 Epic 42 运行时实现内，须以后续独立 story 评估和交付。

### Additional Requirements

- 复用 `tools.path_safety.resolve_under_root` 的根目录围栏语义；包根先 `resolve()`，可选资源使用非严格解析，禁止 startswith 等弱校验。
- 复用 `engine.persist.atomic_write_text` 原子写入锁文件；跨模块状态模型不可使用原始 dict。
- `_bmad/_config/skill-manifest.csv` 是来源清单，manifest 中逻辑路径可能缺失；导入器必须报告缺失，不能静默生成空技能。
- `_bmad/scripts/render_skill.py` 已提供引用收集、包根校验和哈希思路，可提炼为库能力但不能依赖其 CLI 运行时。
- 现有 `.heagent/skills/<name>/SKILL.md`、`.archive/` 和 SkillStore 工具 API 属兼容边界；`/goal` 当前固定路径行为在运行时迁移完成前保持不变。
- 目标级编排、workflow.json、checkpoint、TokenBudgetManager、CLI 收尾和全量文档属于后续独立 Epic，不在本次技能运行时 Epic 内强耦合实现。
- 项目设计强调学习价值、模块边界、声明式扩展和可恢复可观测状态；HeAgent 不是生产级安全边界或多租户服务。

### UX Design Requirements

UX-DR1: 技能列表和解析结果必须同时展示 canonical ID、来源 ID/别名、版本和可用性，缺失入口或源文件时给出可定位错误。
UX-DR2: 用户显式指定 `bmad-*` 或 `he-*` 时必须确定性解析到同一技能；自动匹配不得覆盖显式选择。
UX-DR3: step 需要用户输入、被阻塞或失败时，运行时必须返回明确状态和下一步动作，不能静默继续。
UX-DR4: 资源读取按需执行，错误信息应包含技能 ID、相对资源路径和拒绝原因，便于 CLI/GUI 展示。

### FR Coverage Map

FR1: Epic 42 - 技能来源扫描与稳定索引
FR2: Epic 42 - `he-*` canonical ID 与 `bmad-*` 兼容别名
FR3: Epic 42 - `SKILL.md`、step 和附属资源按需加载
FR4: Epic 42 - 包根目录路径围栏与越界拒绝
FR5: Epic 42 - 单技能 step 顺序与显式状态迁移
FR6: Epic 42 - manifest 导入、来源元数据和哈希锁
FR7: Epic 42 - 导入幂等、缺失源和损坏输入诊断
FR8: Epic 42 - 既有 SkillStore、AgentLoop 和 `/goal` 兼容回归

## Epic List

### Epic 42: 可安装、可验证的声明式技能包运行时

用户可以将受支持来源的 BMad 技能安装为 `he-*` 包，使用 canonical ID 或兼容别名发现技能，安全地按需读取当前 step 与资源，并获得可恢复但不自动跳步的单技能执行状态。
**FRs covered:** FR1, FR2, FR3, FR4, FR5, FR6, FR7, FR8

实现顺序：先建立包模型和路径安全，再加入 catalog/resolver 与 runner，最后接入 manifest importer 和兼容回归。manifest 源缺失必须可诊断；Goal 编排、workflow.json、checkpoint 和 Token 分段属于后续 Epic。

## Epic 42: 可安装、可验证的声明式技能包运行时

用户可以将受支持来源的 BMad 技能安装为 `he-*` 包，使用 canonical ID 或兼容别名发现技能，安全地按需读取当前 step 与资源，并获得可恢复但不自动跳步的单技能执行状态。
**FRs covered:** FR1, FR2, FR3, FR4, FR5, FR6, FR7, FR8

### Story 42.1: 技能包模型与资源路径安全

作为框架使用者，我希望技能包能安全读取入口、step 和附属资源，以便声明式技能不会越过包根访问任意文件。
**FRs covered:** FR3, FR4
**UX-DRs covered:** UX-DR4

**Acceptance Criteria:**

**Given** 合法包根目录和 `SKILL.md`，**When** 创建 `SkillPackage` 并读取入口或当前 step，**Then** 返回结构化元数据和对应文本，未读取无关资源。
**Given** 资源引用为绝对路径、包含 `..` 越界或通过符号链接逃逸包根，**When** 请求读取，**Then** 拒绝操作并返回包含技能 ID、相对路径和原因的显式错误。
**Given** 包缺少 `SKILL.md`，**When** 校验包，**Then** 包标记为不可用且错误可诊断，不生成空技能。

### Story 42.2: 技能目录发现与 canonical/alias 解析

作为框架使用者，我希望从 manifest、项目技能和用户技能中按 canonical ID 或兼容别名找到技能，以便显式选择稳定且可预测。
**FRs covered:** FR1, FR2
**UX-DRs covered:** UX-DR1, UX-DR2

**Acceptance Criteria:**

**Given** 多个来源包含合法技能包，**When** `SkillCatalog` 扫描，**Then** 建立稳定索引并暴露 `he-*` canonical ID、来源 ID、版本和可用性。
**Given** 请求 `he-prd` 或 `bmad-prd`，**When** `SkillResolver` 解析，**Then** 两者指向同一唯一包，显式 ID 优先于自动匹配。
**Given** canonical/alias 冲突、入口缺失或元数据非法，**When** 解析候选，**Then** 返回明确冲突/不可用错误，不静默择一。

### Story 42.3: 单技能 step runner

作为技能运行时调用者，我希望一次只推进一个 step 并获得明确状态，以便人工输入、阻塞和失败都能暂停并恢复。
**FRs covered:** FR5
**UX-DRs covered:** UX-DR3

**Acceptance Criteria:**

**Given** 当前 step 尚未完成，**When** runner 执行一次并收到 callback 结果，**Then** 只加载该 step，状态转换为 `waiting_user`、`blocked`、`completed` 或 `failed` 之一。
**Given** 当前 step 返回等待用户或阻塞，**When** 再次查询 runner，**Then** 保留 active step 和原因，不自动加载下一 step。
**Given** runner 被调用但状态或 step 序号非法，**When** 校验输入，**Then** 显式失败且不伪造完成结果；实现不反向导入 `agent`。

### Story 42.4: BMad manifest 导入与版本哈希锁

作为项目维护者，我希望把可用 BMad 技能导入本地 `he-*` 包并记录来源，以便升级、审计和重复执行可控。
**FRs covered:** FR6, FR7

**Acceptance Criteria:**

**Given** manifest 条目的源文件和包资源存在，**When** importer 执行，**Then** 物化 canonical 包并在 `manifest.lock` 记录源路径、版本和源文件哈希。
**Given** 相同源哈希已锁定，**When** 重复导入，**Then** 不重复写入且锁内容稳定。
**Given** 当前 manifest 逻辑源路径缺失、条目重复或锁文件损坏，**When** 导入，**Then** 显式报告具体条目和原因，不生成空包或覆盖有效锁。

### Story 42.5: 兼容回归与运行时集成验证

作为维护者，我希望新技能包运行时不破坏现有技能和 Goal 入口，以便可以逐步启用 BMad 能力。
**FRs covered:** FR8
**UX-DRs covered:** UX-DR1, UX-DR2, UX-DR3, UX-DR4

**Acceptance Criteria:**

**Given** 现有 `SkillStore` 技能和 AgentLoop 自动匹配配置，**When** 运行完整回归测试，**Then** CRUD、关键词匹配和系统提示词注入行为保持通过。
**Given** `.heagent/skills/goal/SKILL.md` 存在或缺失，**When** 执行现有 `/goal` 命令，**Then** 固定路径读取、显式缺失错误和原有子命令行为不变。
**Given** catalog/package/runner/importer 的边界测试执行，**When** 运行 lint 和类型检查，**Then** 新增测试覆盖路径越界、别名冲突、状态失败、源缺失和导入幂等，且质量门通过。
