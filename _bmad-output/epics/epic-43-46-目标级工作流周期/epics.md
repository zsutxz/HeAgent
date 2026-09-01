---
stepsCompleted: [step-01-validate-prerequisites, step-02-design-epics, step-03-create-stories, step-04-final-validation]
inputDocuments:
  - '{project-root}/_bmad-output/deferred-work.md'
  - '{project-root}/docs/bmad-heagent-plan.md'
  - '{project-root}/docs/frame.md'
  - '{project-root}/_bmad-output/epics/epic-42-BMad技能包运行时周期/epics.md'
---

# heagent - Epic Breakdown

## Overview

本周期承接 Epic 42 的技能包运行时，规划目标级 BMad 工作流的编排、恢复、Token 分段、运维收尾，以及技能资源并发替换风险评估。

## Requirements Inventory

### Functional Requirements

FR1: 实现 `WorkflowOrchestrator`，负责目标级阶段路由、前置条件校验、人工检查点和 `blocked/failed` 状态。
FR2: 实现目标级 `workflow.json`、checkpoint、暂停/恢复及幂等持久化。
FR3: 实现 `TokenBudgetManager`，支持分段预算、阈值触发 rollover、恢复信封，并区分当前段与累计消耗。
FR4: 完善目标级 CLI、审计与成本统计，补齐单元/集成/恢复/幂等/安全/Token 测试及架构文档。
FR5: 对技能包资源读取在并发文件替换下的 TOCTOU 风险完成独立评估，形成是否需要 OS/文件描述符级方案的结论。

### NonFunctional Requirements

NFR1: 阶段路由、状态迁移、Token 阈值、幂等和恢复由确定性代码控制，不能由 LLM 决定。
NFR2: 所有工作单元可暂停、可恢复、可审计；错误、阻塞、审批拒绝和 Token 耗尽必须显式失败。
NFR3: 恢复不能重复完成 Story 或重复执行已完成工具；进行中的工具事务不得伪造为完成。
NFR4: 保持现有异步、Pydantic、模块依赖边界及 `/goal`、`SkillStore`、`AgentLoop` 兼容性。
NFR5: 恢复信封只注入必要状态摘要，不重新注入完整历史；摘要失败使用确定性后备并记录原因。
NFR6: 路径围栏与技能/工具内容仍是 defense-in-depth，不得宣称为 OS 级安全边界。

### Additional Requirements

- 交付依赖顺序为 Epic 43 → Epic 44 → Epic 45；Epic 46 与主线正交。
- `GOAL.md` 拥有 Goal/Story 看板状态；`workflow.json` 仅拥有阶段、技能、step、Token 和恢复元数据。
- 复用 `RunStore`、`WindowReset`、`AgentLoop.resume()`、`atomic_write_text` 和 `EngineContainer`，不复制现有持久化或执行机制。
- 正在执行的工具调用必须先完成事务再 checkpoint；不得以 checkpoint 伪造工具成功。
- 摘要、恢复和审计错误必须携带目标、阶段、run/segment 和原因，禁止静默跳过。
- Epic 46 首先交付评估与决策记录；只有评估确认后，才允许另立实现 Story。

### UX Design Requirements

（无独立 UX 设计契约；本周期主要为后端运行时与 CLI 运维能力。）

### FR Coverage Map

FR1: Epic 43 - 目标级阶段编排、前置条件、人工闸门和失败状态
FR2: Epic 43 - workflow.json、checkpoint、暂停恢复和幂等持久化
FR3: Epic 44 - Token 分段预算、自动 rollover 和恢复信封
FR4: Epic 45 - 目标级 CLI、审计、成本统计、测试和文档收尾
FR5: Epic 46 - 技能资源读取 TOCTOU 风险评估和方案决策

## Epic List

### Epic 43: 可控的目标工作流推进与恢复

用户可以从 `discovery` 开始推进目标，系统按确定性阶段规则校验前置产物、执行人工 checkpoint，并在暂停、失败或重启后从最后未完成工作单元恢复；`GOAL.md` 与运行时状态各自保持明确所有权。
**FRs covered:** FR1, FR2

### Epic 44: 跨上下文的长目标连续执行

用户可以运行超出单次上下文窗口的长目标，系统在预算达到阈值前保存检查点、生成恢复信封、创建新 segment，并保留累计 Token 与成本审计数据。
**FRs covered:** FR3

### Epic 45: 目标级运维、审计与质量收口

维护者可以通过目标级 CLI 查看阶段、Story、checkpoint、Token 和成本信息，并以完整测试、文档和真实冒烟证明整个闭环可维护、可审计、可回归。
**FRs covered:** FR4

### Epic 46: 技能资源并发替换安全评估

维护者可以获得技能包资源读取 TOCTOU 风险的明确结论、威胁边界和后续决策，并在支持的平台获得最终路径组件的 descriptor 加固；中间目录、snapshot 与 OS sandbox 仍需后续实现。
**FRs covered:** FR5

## Epic 43: 可控的目标工作流推进与恢复

用户可以从 `discovery` 开始推进目标，系统按确定性阶段规则校验前置产物、执行人工 checkpoint，并在暂停、失败或重启后从最后未完成工作单元恢复；`GOAL.md` 与运行时状态各自保持明确所有权。
**FRs covered:** FR1, FR2

### Story 43.1: 目标工作流状态模型与确定性迁移

As a 框架维护者,
I want 用 Pydantic 模型表达目标阶段、活动技能、活动 step、状态和阻塞原因，并由代码校验合法迁移,
So that LLM 输出不能绕过工作流边界或伪造完成状态。

**Acceptance Criteria:**

**Given** 一个新目标，**When** 创建工作流状态，**Then** 默认从 `discovery` 和未运行状态开始，并包含 `goal_id`、`phase`、`active_skill`、`active_step`、`active_story`、`status` 和 `artifact_refs` 等结构化字段。
**Given** 合法迁移（如 `discovery -> planning`、`review -> done`），**When** 编排器请求迁移，**Then** 状态被更新并保留迁移原因和时间信息。
**Given** 非法回退、未知阶段或未满足前置条件，**When** 请求迁移，**Then** 返回显式错误，原状态不变且不会写入完成标记。
**Given** `GOAL.md` 含 Story 看板状态，**When** 更新运行时状态，**Then** 不复制或改写 Story checkbox；看板状态仍由 `GOAL.md` 拥有。

### Story 43.2: 阶段路由、前置条件与人工闸门

As a 目标执行者,
I want 系统依据当前产物和阶段选择下一个 `he-*` 技能，并在需要确认、缺少产物或发生阻塞时停下,
So that 目标按 BMad 顺序推进且每个决策点可由人检查。

**Acceptance Criteria:**

**Given** 当前阶段和已落盘产物，**When** 请求下一工作单元，**Then** `WorkflowOrchestrator` 通过 `SkillResolver` 计算唯一候选并生成确定性迁移，不允许技能自行跳阶段。
**Given** 缺少 PRD/Spec、架构或 ready Story，**When** 请求进入依赖阶段，**Then** 状态变为 `blocked`，错误包含缺失产物和下一项动作。
**Given** step 要求用户菜单或 Epic/Story 边界检查，**When** 技能返回等待信号，**Then** 状态变为 `waiting_user`，保存当前 step、提示和恢复位置，不加载后续 step。
**Given** 技能 ID 使用 `bmad-*` 别名，**When** 路由解析，**Then** 映射到唯一 `he-*` canonical ID；显式技能名优先于自动匹配。

### Story 43.3: Workflow checkpoint、暂停恢复与幂等提交

As a 目标执行者,
I want 工作流状态和每次运行的 checkpoint 原子保存，并能从最后一个未完成单元恢复,
So that 进程崩溃、Ctrl+C 或重复恢复不会重复完成 Story 或工具事务。

**Acceptance Criteria:**

**Given** 工作单元完成且工具事务已结束，**When** 保存 checkpoint，**Then** 原子写入 `workflow.json` 与 `checkpoints/`，记录状态、产物引用、验收证据、下一动作和 run 标识。
**Given** 工作单元正在执行工具，**When** 收到暂停、取消或进程退出信号，**Then** 只保存可确认的现场，不把进行中的工具标为成功。
**Given** 已存在相同 run/step 的 checkpoint，**When** 重复提交或恢复，**Then** 操作幂等，不能重复执行已完成事务或回退已完成 Story。
**Given** 重新启动目标，**When** 读取损坏、缺失或版本不兼容的状态文件，**Then** 显式返回目标和文件原因，保留现场并进入 `failed`/`blocked`，不静默重置。

## Epic 44: 跨上下文的长目标连续执行

用户可以运行超出单次上下文窗口的长目标，系统在预算达到阈值前保存检查点、生成恢复信封、创建新 segment，并保留累计 Token 与成本审计数据。
**FRs covered:** FR3

### Story 44.1: 分段 Token 预算与确定性阈值

As a 长目标执行者,
I want 系统分别记录当前 segment、Goal 累计和上下文窗口 Token，并在预计超阈值前发出 rollover 决策,
So that 长目标不会因窗口耗尽而丢失状态或超出预算。

**Acceptance Criteria:**

**Given** provider 调用前有当前用量和预计用量，**When** `TokenBudgetManager` 检查预算，**Then** 按配置阈值确定继续或 rollover，不调用 LLM 代替判断。
**Given** segment rollover，**When** 新 segment 创建，**Then** `segment_tokens` 从 0 重新计算，`cumulative_tokens` 保留完整累计值，`context_window_usage` 独立记录。
**Given** 缺失、负数或不一致的 Token 计数，**When** 更新预算，**Then** 显式失败并记录 segment、run 和原始计数，不继续执行。

### Story 44.2: 自动 rollover 与新运行上下文

As a 长目标执行者,
I want 达到阈值时自动 checkpoint、清理当前 AgentLoop 并启动新 run,
So that 目标可以跨多个上下文连续推进而不重复工作。

**Acceptance Criteria:**

**Given** 预算检查触发 rollover，**When** 当前工具事务已完成，**Then** 保存工作流 checkpoint、生成新 `run_id`，关闭旧上下文并创建新的 AgentLoop。
**Given** rollover 发生在工具调用中，**When** 工具尚未返回，**Then** 延迟切换直到事务结束，不伪造工具结果、不重复提交。
**Given** 新 AgentLoop 启动，**When** 注入恢复上下文，**Then** 只包含目标、阶段、当前 Story/step、验收证据、产物引用、最近 checkpoint 摘要和下一动作。
**Given** 新 run 初始化失败，**When** rollover 收尾，**Then** 状态变为 `failed` 并保存旧 run、目标和失败原因，允许显式 resume 重试。

### Story 44.3: 恢复信封、摘要后备与长目标集成验证

As a 维护者,
I want 恢复信封格式稳定且摘要失败可降级，并用跨 segment 测试证明长目标连续性,
So that 重启后的执行上下文足够且可审计。

**Acceptance Criteria:**

**Given** checkpoint 存在，**When** 构建恢复信封，**Then** 生成版本化、可校验的 Pydantic 结构，引用路径和下一动作完整。
**Given** LLM 进度摘要生成失败或超时，**When** 构建信封，**Then** 使用确定性的状态摘要作为后备，并记录摘要失败原因。
**Given** 一个目标跨越至少两个 segment，**When** 完成恢复并继续推进，**Then** 目标阶段和 Story 进度连续、累计 Token 单调增加、segment Token 从零开始。
**Given** 重复 resume 请求，**When** 读取同一 checkpoint，**Then** 返回同一恢复结果或明确冲突，不创建重复完成记录。

## Epic 45: 目标级运维、审计与质量收口

维护者可以通过目标级 CLI 查看阶段、Story、checkpoint、Token 和成本信息，并以完整测试、文档和真实冒烟证明整个闭环可维护、可审计、可回归。
**FRs covered:** FR4

### Story 45.1: 目标级 CLI 控制与状态展示

As a 框架使用者,
I want 通过 `/goal status`、`/goal next`、`/goal run`、`/goal pause` 和 `/goal resume` 控制目标并看到当前状态,
So that 不需要直接编辑运行时文件也能安全推进或暂停目标。

**Acceptance Criteria:**

**Given** 活跃目标，**When** 执行 status，**Then** 展示 phase、active skill/step/story、workflow 状态、checkpoint、segment/cumulative Token 和阻塞原因。
**Given** 执行 next 或 run，**When** 编排器返回 waiting、blocked、failed 或 done，**Then** CLI 原样回显状态、原因和下一项动作，不静默继续。
**Given** 执行 pause 或 resume，**When** 状态迁移完成，**Then** checkpoint 先落盘再回显结果；无活跃目标或状态损坏时显示可定位错误。
**Given** 旧有非 goal CLI/cron 路径，**When** 执行回归命令，**Then** 行为与现状保持兼容。

### Story 45.2: 运行审计、成本统计与可观测查询

As a 维护者,
I want 按 goal、run、segment 和阶段查询运行事件与 Token 成本,
So that 可以解释一次目标执行消耗了什么、在哪里暂停或失败。

**Acceptance Criteria:**

**Given** 每次 run 或 segment 完成、暂停、失败或 rollover，**When** 写入观测事件，**Then** 事件包含 goal、run、segment、phase、status、Token 和错误字段。
**Given** 用户按 goal 或 run 查询，**When** CLI/观测接口读取事件，**Then** 返回稳定排序的记录和累计成本，不修改权威 workflow 状态。
**Given** 观测写入失败，**When** 主工作流继续或停止，**Then** 按既定 fail-safe 语义显式记录失败，不伪造审计完整性。

### Story 45.3: 全量质量门、文档同步与真实冒烟

As a 项目维护者,
I want 用测试、lint、类型检查、文档和真实小目标冒烟验证闭环,
So that 新运行时交付可信且架构文档不会落后于实现。

**Acceptance Criteria:**

**Given** Epic 43–44 的实现完成，**When** 运行 pytest、ruff 和 mypy，**Then** 新增状态迁移、恢复、幂等、Token rollover、安全边界和兼容性测试通过，既有回归不降级。
**Given** 代码行为或状态所有权变化，**When** 更新文档，**Then** `docs/frame.md`、README、`deferred-work.md` 和 consolidated overview 一致描述阶段、checkpoint、Token 与安全边界。
**Given** 可用 LLM 凭据或 StubProvider，**When** 执行至少两 Story 的小目标冒烟，**Then** 能从规划推进到完成或显式 blocked，并留下可恢复 checkpoint 与审计证据。

## Epic 46: 技能资源并发替换安全评估

维护者可以获得技能包资源读取 TOCTOU 风险的明确结论、威胁边界和后续决策；若评估确认需要加固，再形成独立的 OS/文件描述符级实现入口。
**FRs covered:** FR5

### Story 46.1: 技能资源 TOCTOU 威胁评估与决策记录

As a 安全维护者,
I want 评估包根校验与资源读取之间的并发替换窗口，并记录可验证的缓解决策,
So that 后续实现不会把用户态路径检查误认为完整安全边界。

**Acceptance Criteria:**

**Given** `SkillPackage` 的路径解析、符号链接和资源读取流程，**When** 建立威胁模型和竞态测试，**Then** 明确攻击窗口、受影响资源、当前防护和不可覆盖的 OS 边界。
**Given** 候选方案（文件描述符打开、目录句柄、复制快照或 OS 沙箱），**When** 比较正确性、跨平台可行性、性能和兼容性，**Then** 输出带条件、成本和残余风险的决策记录。
**Given** 评估未证明某方案可行，**When** 更新规划，**Then** 保留现有路径围栏语义，不声称已完成 TOCTOU 防护，并将实现拆为后续明确 Story。
**Given** 评估产物完成，**When** 维护者复核，**Then** `deferred-work.md`、`docs/frame.md` 和 Epic 42 资源安全说明引用同一结论，避免重复或矛盾描述。

### Story 46.2: 技能资源安全打开加固

通过已打开的文件描述符读取资源，在支持的平台为最终路径组件启用 `O_NOFOLLOW` 并拒绝非普通文件；不支持该能力的平台保留兼容回退，并显式记录中间目录竞态和 OS 边界。

**FRs covered:** FR5

**Acceptance Criteria:**

**Given** 有效的 UTF-8 技能资源，**When** 读取入口或任一附属资源，**Then** 通过一个已打开 descriptor 返回与既有 API 一致的内容和错误语义。
**Given** 最终解析文件在打开前被替换为符号链接，**When** 平台支持 `O_NOFOLLOW`，**Then** 显式拒绝读取且不返回包外内容。
**Given** 平台或文件系统不支持 `O_NOFOLLOW`，**When** 读取资源，**Then** 保留兼容行为并记录保护不可用，不声称完整 TOCTOU 防护。
