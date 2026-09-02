# HeAgent BMad 敏捷开发系统规划

> 状态：规划与实现对照（核心工作流已交付，本文保留设计背景）
>
> 更新日期：2026-08-31

## 目标

将 BMad 工作流和相关技能迁移到 HeAgent，使 `/goal` 成为目标级敏捷开发流程的启动点，而不是只执行一次 planning 或一条 Story。

目标闭环：

```text
/goal 目标
  -> 需求探索
  -> PRD / Spec
  -> 架构 / UX
  -> Epic / Story
  -> Sprint 计划
  -> Story 实现
  -> 测试 / Code Review
  -> 回顾
  -> Goal 完成
```

## 当前实现基线

- `/goal` 已具备目标目录、`current` 指针、`GOAL.md`、planning 和单 Story 推进能力。
- `SkillStore` 保留学习型 `SKILL.md`；BMad 技能包资源由 `memory/skill_packages.py`、`skill_importer.py` 等运行时组件提供，支持 step 文件、references、templates 和 scripts 的按需安全读取，但目前不提供通用的项目/用户配置合并 API。
- `RunStore`、`WindowReset` 和 `AgentLoop.resume()` 已提供单次 run 的快照和上下文恢复能力。
- BMad 技能清单位于 `_bmad/_config/skill-manifest.csv`；实际安装目录与 manifest 中的逻辑路径需要增加映射层。

## 核心设计原则

1. `/goal` 只负责创建、查询和恢复目标；工作流推进由独立的 `WorkflowOrchestrator` 负责。
2. 确定性逻辑由代码负责：阶段路由、前置条件、状态转换、Token 阈值、幂等和恢复不能交给 LLM 决定。
3. LLM 负责产出需求、设计、代码和证据；系统必须校验产物格式、验收标准和状态变化。
4. 每个工作单元都必须可暂停、可恢复、可审计；错误必须显式暴露，禁止静默跳过。
5. 保持 HeAgent 的异步、Pydantic、ToolRegistry 和 EngineContainer 约定，不从 BMad 直接复制同步运行时。

## 技能系统迁移

新增技能包运行时，和现有学习型技能隔离：

```text
.heagent/
  skills/
    manifest.lock             # BMad 迁移版本和源文件哈希
    he-help/SKILL.md
    he-prd/SKILL.md
    he-build/SKILL.md
    he-*/references/
    he-*/templates/
    he-*/scripts/
    <learned-skill>/SKILL.md  # 现有 SkillStore 技能
```

建议新增组件：

- `SkillCatalog`：扫描 manifest、项目技能和用户技能，支持 HeAgent canonical id（如 `he-prd`）、版本和别名。
- `SkillPackage`：读取 `SKILL.md` 及其资源，所有资源路径必须限制在包根目录内。
- `SkillResolver`：依据用户意图、当前阶段和前置产物确定下一技能；显式技能名优先于自动匹配。
- `SkillRunner`：按 step-file 顺序执行，支持 `waiting_user`、`blocked`、`completed` 和 `failed`。
- BMad 导入器：根据 manifest 将当前 BMad 技能直接导入 `.heagent/skills/`，迁移后的 canonical skill 名称统一使用 `he-` 前缀，并记录版本和源文件哈希。

迁移后的技能统一命名为 `he-<name>`；原始 `bmad-<name>` 只作为来源 ID 或兼容别名解析到对应的 `he-<name>`，不再作为新技能名称。deprecated skill 只保留别名转发，不重复维护实现。资源加载采用按需读取，避免把整个 BMad 技能目录注入每次 LLM 请求。

## 工作流阶段

第一版核心链路：

```text
goal-start
  -> discovery
  -> product-brief / prd / spec
  -> architecture / ux
  -> epics-and-stories
  -> sprint-planning
  -> implementation-readiness
  -> build one story
  -> test
  -> code-review
  -> mark story done
  -> next story
  -> retrospective
  -> goal done
```

异常分支：

- `blocked`：保存阻塞原因，停止自动推进，等待用户处理。
- `correct-course`：记录变更原因，更新计划后回到对应阶段。
- `checkpoint`：展示当前产物、风险和下一步，等待人工确认。
- `failed`：保存异常和现场，不将失败伪装成完成。

## BMad 工作流管理实现参考

BMad 的工作流由技能包、步骤文件、配置清单和产物状态共同组成；HeAgent 的 `/goal` 当前要求一个自包含的 `workflow.md` 作为运行时入口：

```text
SKILL.md
  -> workflow.md（必需的自包含工作流入口；外部 step 文件仅为兼容资源形式）
```

各类文件职责固定如下：

| 文件 | 职责 |
|---|---|
| `SKILL.md` | 技能元数据、激活规则、工作流入口和约束 |
| `workflow.md` | 技能级执行总则、顺序和停止条件 |
| `step-*.md` | 一个可独立执行的微步骤，只加载当前步骤 |
| `references/` | 当前步骤按需读取的参考资料 |
| `templates/` / `assets/` | 产物模板和静态资源 |
| `scripts/` | 确定性辅助脚本，例如配置解析和文档渲染 |
| `manifest.csv` | 技能 ID、阶段、前置/后续关系和输出位置 |
| `customize.toml` | 技能默认配置和可覆盖项 |

HeAgent 迁移后应将这些 Markdown 视为“声明式工作流定义”，由代码解释执行，不把流程规则重新复制到 Python 分支中。

### 工作流启动链

```text
用户输入
  -> CLI 读取 .heagent/workflows/workflow.md
  -> WorkflowRunner 校验并执行当前 inline step
  -> AgentLoop / SubAgent 执行声明
  -> 校验产物和状态
  -> 保存 checkpoint 与运行元数据
  -> 进入下一个 step 或停止等待
```

### SkillRunner 执行规则

`SkillRunner` 每次只负责一个技能的一次运行，必须遵守以下顺序：

1. 校验技能包、版本、资源路径和入口文件。
2. 合并全局配置、项目配置、用户配置和技能配置。
3. 解析当前 `active_step`；没有状态时从第一个 step 开始。
4. 只加载当前 step 文件及其直接引用的资源。
5. 将目标状态、已有产物和当前 step 注入 AgentLoop。
6. 根据 step 结果校验所需产物、验收证据和 `stepsCompleted`。
7. 原子写入 `workflow.json`、产物索引和 checkpoint。
8. 遇到人工菜单、缺失输入、阻塞或错误时停止，不自动跳过。
9. 当前 step 完成后，才能加载下一个 step。

伪代码：

```text
run_skill(skill_id, workflow_state):
    package = catalog.resolve(skill_id)
    config = config_resolver.merge(package, project, user)
    step = package.next_step(workflow_state.active_step)
    context = build_resume_envelope(workflow_state, step, config)
    result = agent_loop.run(step.instructions, context=context)
    validate_step_result(result, step.contract)
    persist_checkpoint(result, workflow_state)
    return next_transition(workflow_state, result)
```

### WorkflowOrchestrator 的职责

`WorkflowOrchestrator` 管理跨技能的目标流程，不能让单个技能自行跳到任意阶段。它需要：

- 根据 `module-help.csv` 和当前产物计算候选技能。
- 校验前置条件，例如没有 PRD 时不能进入架构或 Story 拆分。
- 将 BMad 原始 ID 映射为 `he-*` canonical ID。
- 维护阶段状态：`discovery`、`planning`、`sprint`、`implementation`、`review`、`retrospective`、`done`。
- 在 Story、Epic 和 Goal 边界建立人工检查点。
- 将 `blocked`、`correct-course`、`pause` 和 `resume` 转换为确定性状态迁移。
- 防止已完成 Story 回退，防止同一 step 或工具事务重复提交。

阶段迁移必须由代码校验，例如：

```text
discovery -> planning
  条件：目标范围已确认，且需求产物已落盘

planning -> sprint
  条件：PRD/Spec、架构和 Epic/Story 产物通过检查

sprint -> implementation
  条件：存在 ready-for-dev Story

implementation -> review
  条件：代码、测试结果和 Story 验收证据已落盘

review -> implementation
  条件：审查发现需要修复

review -> done
  条件：审查通过且 Story 状态已更新
```

### 渲染与执行的边界

BMad 原有 `render_skill.py` 负责把配置占位符和引用文件渲染成一个带哈希的工作流快照；HeAgent 迁移时应保留这一职责，但将输出改为 `.heagent/skills/he-*/` 下的可验证版本或运行时缓存。

渲染层负责：

- 配置合并和占位符替换。
- 引用文件收集。
- 绝对路径解析。
- 源文件和输出文件哈希校验。
- 生成不可变快照。

执行层负责：

- 读取当前 step。
- 调用 AgentLoop 和工具链。
- 校验产物和验收条件。
- 保存状态、Token 和 checkpoint。
- 决定下一步迁移。

两层不能混合：渲染器不推进目标状态，LLM 也不能绕过执行器直接改变阶段。

### 人工闸门和失败语义

以下情况必须停止并等待用户或显式恢复命令：

- BMad step 要求用户选择菜单。
- 需求、架构或验收标准存在未解决冲突。
- 生成的产物缺失必需章节或格式不合法。
- Token 分段预算耗尽。
- 工具执行失败、审批拒绝或安全策略阻断。
- Code Review 发现必须修复的问题。

停止时保存：当前技能、当前 step、目标阶段、错误/阻塞原因、已生成产物、验收证据和下一项动作。恢复时从最后一个未完成 step 继续，而不是重新运行整个技能。

## 状态和持久化

目标目录建议扩展为：

```text
_he-output/goals/<goal_id>/
  GOAL.md
  workflow.json
  checkpoints/
  artifacts/
```

状态所有权必须固定：

| 内容 | 权威来源 |
|---|---|
| Goal 描述与 Epic 列表 | `GOAL.md` |
| 当前阶段、技能、step、阻塞原因 | `workflow.json` |
| Epic / Story Sprint 状态 | `sprint-status.yaml` |
| 单次 run 对话和工具快照 | `RunStore` |
| 分段 Token、累计 Token、检查点 | `workflow.json` 与 `checkpoints/` |

`workflow.json` 应使用 Pydantic 模型，例如 `GoalWorkflowState`，包含 `goal_id`、`phase`、`active_skill`、`active_step`、`active_story`、`status`、`segment_index`、`segment_tokens`、`cumulative_tokens`、`artifact_refs` 和 `blocked_reason`。

`GOAL.md` 是 GoalArtifact 的人工编辑入口，只维护 Epic 列表；Epic/Story 状态唯一以 `_bmad-output/sprint-status.yaml` 为准。`workflow.json` 只保存运行时元数据，不能复制状态看板。

## Token 分段与恢复

现有 `WindowReset` 解决上下文窗口占用；目标级 Token 分段由已实现的 `TokenBudgetManager` 与 workflow runner 协作完成：

```text
provider 调用前
  -> 检查本段已用 Token + 本次预计 Token
  -> 达到阈值则先 checkpoint
  -> 生成有限进度摘要
  -> 原子保存 workflow / GOAL / 产物索引
  -> 清理当前 AgentLoop 和消息上下文
  -> 创建新的 run_id 和 AgentLoop
  -> 注入恢复信封
  -> segment_tokens 从 0 重新计算
```

必须区分三类计数：

- `segment_tokens`：当前 LLM 分段预算，切换分段后归零。
- `cumulative_tokens`：整个 Goal 的累计消耗，用于审计和成本统计，不能归零。
- `context_window_usage`：当前请求上下文占用，由 compressor 或 `WindowReset` 管理。

恢复信封只包含目标、阶段、当前 Story/step、`GOAL.md` 状态、验收证据、产物路径、最近 checkpoint 摘要和下一项动作，不重新注入完整历史对话。

摘要失败时使用确定性的状态摘要作为后备，并记录失败原因。正在执行的工具调用不能被伪造为已完成，必须在工具事务结束后 checkpoint。

## CLI 方向

保留现有命令兼容性，并增加目标级控制：

```text
/goal <描述>       创建目标并启动 BMad 路由
/goal status       查看阶段、Story、Token 和 checkpoint
/goal next         推进一个工作单元
/goal run          连续推进，遇到闸门自动停止
/goal pause        主动保存并暂停
/goal resume       从最后 checkpoint 继续
/goal reset        清除 current 指针，保留历史目录
```

## 分阶段实施

> 下列 Phase 0–5 是历史迁移方案，保留用于解释设计来源；当前实现状态以 `src/heagent/engine/workflow.py`、`workflow_runner.py` 和根 `sprint-status.yaml` 为准，不应作为待办清单。

### Phase 0：契约和架构（历史方案）

- 固定技能包、目标状态、checkpoint 和 Token 模型。
- 固定状态所有权和阶段状态机。
- 解决 manifest 与实际技能目录的映射。
- 验收：仅凭持久化文件可以恢复一个目标的完整运行状态。

### Phase 1：BMad 技能包运行时

- 实现 catalog、package、资源加载和导入器。
- 迁移核心 BMad 技能及其 references/templates/scripts。
- 验收：核心技能不依赖硬编码路径即可被发现和执行。

### Phase 2：工作流编排器

- 将 `/goal` 改为工作流启动器。
- 实现阶段路由、前置条件、人工闸门和失败状态。
- 验收：目标可以从 discovery 推进到至少一个完成的 Story。

### Phase 3：目标级 checkpoint/resume

- 实现 `workflow.json`、checkpoint 目录和恢复信封。
- 覆盖 Ctrl+C、进程崩溃、重复执行和断点恢复。
- 验收：重启后不会重复完成 Story 或重复执行已完成工具。

### Phase 4：Token 分段执行

- 实现 `TokenBudgetManager` 和分段事件。
- 达阈值自动保存、清理 LLM 状态并创建新 segment。
- 验收：长目标跨多个 segment 连续完成，segment Token 每次从 0 开始。

### Phase 5：审计、测试和文档

- 完善 CLI、状态展示、日志和成本统计。
- 增加单元、集成、恢复、幂等、安全和 Token rollover 测试。
- 更新 `docs/frame.md`、README 和配置说明。

## 第一版技能范围

优先打通以下核心技能：

```text
he-help
he-product-brief
he-prd
he-architecture
he-ux
he-spec
he-create-epics-and-stories
he-sprint-planning
he-build
he-code-review
he-correct-course
he-retrospective
```

研究、party mode、审稿器和 deprecated shim 在核心链路稳定后接入。

## 必须覆盖的测试

- Skill manifest、版本、别名和目录映射。
- references/templates/scripts 的按需加载和路径穿越防护。
- 阶段状态机的合法转换、非法转换和人工闸门。
- `GOAL.md` 与 `workflow.json` 的状态所有权不漂移。
- Token 阈值触发、分段归零、累计值保留和摘要失败后备。
- Ctrl+C、进程崩溃、重复恢复、工具幂等和已完成 Story 不回退。
- 使用不可信技能内容或工具输出时仍遵守现有 OS 级沙箱安全声明。

## 暂不纳入

- 将 HeAgent 直接改造成多租户 Web 服务。
- 把 LLM 的自然语言输出直接当作状态机状态。
- 一次性迁移所有 BMad 附属技能并同时重写现有 SkillStore。
- 把 `SafetyGuard`、`PolicyEngine` 或交互式审批误当作真正的安全边界。
