# `/goal` 现状、使用方式与优化方案

> 文档类型：架构与产品优化方案。
>
> 适用范围：HeAgent 当前 `/goal` 声明式目标工作流，以及与 Codex、Claude Code 类 coding agent 的能力对照。
>
> 本文是现状分析和优化路线，不表示方案已经实现。
>
> 本文档已合并原 `goal-workflow-runtime-solution.md`，现为 `/goal` 与 workflow 优化的唯一方案文档。

## 1. 执行摘要

`/goal` 是 HeAgent 的目标驱动开发入口。它不是普通的长 prompt，也不是简单地连续调用多个 Agent；它由以下部分组成：

```text
用户 /goal 命令
    ↓
cli/goal.py：命令分发、CLI/GUI/cron 适配、Goal 互斥锁
    ↓
goal/workflow_loader.py：解析 workflow.md
    ↓
WorkflowResource：结构化工作流定义
    ↓
goal/application.py：确定性推进用例
    ↓
engine/workflow_runner.py：步骤/Story 状态机
    ↓
SubAgent：每个步骤使用独立执行会话
    ↓
AgentLoop：Provider ↔ Tool 执行循环
    ↓
PolicyEngine → ToolExecutor → SafetyGuard → handler
    ↓
checkpoint / workflow.json / Markdown 产物 / 事件
```

当前 `/goal` 已经具备以下工程能力：

- 声明式工作流；
- 8 步开发流程；
- 步骤级输入、输出、角色、门禁和 checkpoint；
- 每步新的 SubAgent 会话；
- Story loop；
- 同 Epic 内有界并行 Story；
- 文件 checkpoint 和进程重启恢复；
- `/goal next`、`run`、`status`、`pause`、`resume`、`reset`、`auto`；
- CLI、GUI、cron 共用同一推进用例；
- 跨进程互斥；
- 用户补充和需求文档持久化；
- 步骤事件和运行观测。

但它目前更接近“严格的 AI 项目流程引擎”，还不是完整的“证据驱动软件交付系统”。最重要的优化方向不是继续增加步骤，而是把以下事实纳入状态机和 gate：

- 真实执行过哪些命令；
- 真实修改了哪些文件；
- 测试、lint、类型检查是否真的通过；
- 当前代码变更是否属于当前 Story；
- 哪些内容需要用户批准；
- 哪些假设是自动接受的；
- 并行 Story 是否真的没有写集冲突。

推荐总路线：

```text
Phase 0：预检和状态可视化
Phase 1：显式状态事件与转换表
Phase 2：结构化执行证据和真实质量门禁
Phase 3：步骤级审批与多种工作流模板
Phase 4：受控脚本化
Phase 5：安全并行与项目级控制面
```

其中 Phase 0–2 是最高优先级；不建议一开始直接开放任意 Python 工作流脚本。

## 2. 当前实现详解

### 2.1 工作流定义的唯一入口

默认工作流包是：

```text
.heagent/skills/he-goal/
```

核心契约：

```text
.heagent/skills/he-goal/workflow.md
```

工作流由 `Settings.goal_workflow_skill` 指定，默认使用 `he-goal`。加载过程不是简单读取文本，而是：

```text
SkillCatalog
    → SkillResolver
    → SkillPackage
    → read_workflow()
    → WorkflowResource
```

加载器会检查：

- workflow 是否存在；
- frontmatter 是否合法；
- 步骤是否存在；
- 步骤文件名是否符合 `step-NN-*.md`；
- 步骤编号是否从 1 开始连续；
- 步骤是否重复；
- `next` 是否引用已声明步骤；
- `checkpoint_mode` 是否为合法值；
- `open_question_mode` 是否为合法值；
- `required_resources` 声明的资源是否存在且非空；
- 资源引用是否越出技能包根目录。

工作流资源模型位于：

```text
src/heagent/engine/workflow_resource.py
```

核心模型包括：

```python
class WorkflowStepResource(BaseModel):
    index: int
    name: str
    instructions: str
    input: str = ""
    output: str = ""
    next: str | None = None
    checkpoint: str = ""
    validation_rules: str = ""
    role: str = ""
    story_loop: str = ""
    max_parallel_stories: int = 1
    max_iterations: int = 0
```

以及：

```python
class WorkflowResource(BaseModel):
    name: str
    instructions: str
    steps: list[WorkflowStepResource]
    entrypoint: str = ""
    on_create: str = "persist_goal_identity"
    step_executor: str = "subagent"
    checkpoint_mode: CheckpointMode = ""
    open_question_mode: OpenQuestionMode = ""
    max_rounds: int = 10
    auto_schedule: str = ""
```

### 2.2 默认八步流程

当前 `he-goal/workflow.md` 声明的默认流程为：

| 步骤 | 名称 | 作用 | 写入边界 |
|---|---|---|---|
| 01 | `market-research` | 市场、竞品、替代方案、证据缺口 | 只允许把初步需求分析写回需求文档 |
| 02 | `brainstorm-options` | 发散多个方向并排序 | 不改实现产物 |
| 03 | `analyze-requirements` | 梳理需求、假设、干系人和 Story 方向 | 不改实现产物 |
| 04 | `define-product-scope` | 形成 PRD、范围、非目标和 Epic 提案 | 不拆最终 Story |
| 05 | `design-architecture` | 设计架构、接口、边界、失败处理和验证路径 | 不实现功能 |
| 06 | `refine-stories` | 细化 Epic、Story、Sprint 和验收标准 | 只规划，不实现 |
| 07 | `implement-story` | 逐 Story 实现、测试和验证 | 唯一常规代码修改步骤 |
| 08 | `system-integration-test` | Epic 集成、跨 Epic E2E、质量门禁 | 只允许修复自身发现的 Critical 集成缺陷 |

这个划分的价值在于把“想做什么”和“怎么实现”分开：

```text
需求理解
    → 产品范围
    → 架构约束
    → Story 计划
    → 逐 Story 实现
    → 系统集成验收
```

### 2.3 Goal 创建过程

执行：

```text
/goal new <目标描述>
```

或：

```text
/goal <目标描述>
```

主要过程：

1. 调用 `goal/naming.py` 生成 Goal ID。
2. 对模型返回值清洗并校验 kebab-case。
3. 发生重名时使用 `-a` 到 `-z` 后缀尝试分配。
4. 在 `_he-output/goals/<goal-id>/` 创建目标目录。
5. 写入 `brief.md`。
6. 写入 `## 原始需求（Original Request）`。
7. 写入派生需求占位符。
8. 记录 `checkpoint-workspace.txt`。
9. 写入 `_he-output/goals/current`。
10. 自动推进第一个步骤。

需求文档新目标使用：

```text
brief.md
```

存量目标兼容：

```text
require.md
GOAL.md
```

`goal/document.py` 会优先选择当前存在的文档，不会把同一个 Goal 拆成两份。

### 2.4 命令分发

入口主要位于：

```text
src/heagent/cli/goal.py
```

支持的命令：

```text
/goal <description>
/goal new <description>
/goal next
/goal status
/goal run
/goal resume [回复]
/goal pause
/goal reset
/goal auto [cron]
```

命令分发的关键点：

- 不存在活动 Goal 时拒绝推进；
- `workflow.md` 缺失时显性失败；
- 不再静默回退到旧的 legacy board；
- CLI/GUI 输出通过 `_echo` 统一出口；
- GUI 可通过 message sink 接收 Goal 消息；
- cron 调度复用同一 Goal 推进路径。

### 2.5 确定性用例层

核心用例位于：

```text
src/heagent/goal/application.py
```

它是 click-free 的确定性内核，主要负责：

- 工作流校验；
- checkpoint 恢复；
- checkpoint 工作区绑定；
- prompt 装配；
- gate 预提示；
- 输入去重；
- Story 读取和路径安全检查；
- `advance()`；
- `pause_resume()`；
- 输出结构化 `GoalAdvanceOutcome`。

这层不直接写 stderr，不导入 `click`，因此可以被：

- CLI；
- GUI；
- cron；
- 将来的 HTTP 或库调用方；

共用。

### 2.6 SubAgent 执行模型

每个工作流步骤由新的 SubAgent 会话执行。

调用链大致是：

```text
_goal_execute_step()
    → _goal_session()
    → SubAgent(...)
    → AgentLoop
    → Provider
    → Tool calls
```

每次步骤执行会注入：

- Goal ID；
- 工作流步骤；
- 当前 Story；
- 角色用途；
- 工作流说明；
- 用户原始意图；
- 用户补充；
- 已完成步骤输出；
- 项目上下文；
- gate 要求；
- open-question 策略。

每个步骤拥有新会话的好处：

- 防止所有阶段共享一个不断膨胀的上下文；
- 让每个步骤具有清晰的职责边界；
- 便于按步骤恢复；
- 便于统计步骤和 Story 级耗时、结果和失败。

代价是：

- 跨步骤信息必须通过产物和输入显式传递；
- 上一步遗漏关键内容可能导致下一步理解不完整；
- 文档输入过大时仍可能产生 token 压力；
- 步骤间动态推理能力不如单会话自然。

### 2.7 Prompt 和 gate 装配

工作流包携带：

```text
templates/prompt-template.md
templates/gate-template.md
```

Prompt 会注入：

- workflow instructions；
- goal；
- goal directory；
- output root；
- 当前 step；
- story context；
- role instructions；
- open-question policy；
- 输入产物；
- gate。

gate 会把 `validation:` 中声明的章节和 Given/When/Then 要求提前告诉执行 Agent。

执行结束后，`WorkflowRunner` 再进行实际校验。也就是说：

```text
执行前提示门禁
    +
执行后验证门禁
```

不是只依赖模型自觉。

### 2.8 `WorkflowRunner` 状态机

实现位置：

```text
src/heagent/engine/workflow_runner.py
```

状态类型位于：

```text
src/heagent/engine/checkpoint.py
```

状态包括：

```text
PENDING
RUNNING
WAITING_USER
BLOCKED
FAILED
COMPLETED
```

`run_step()` 的基本流程：

```text
检查是否已完成
    ↓
检查当前是否 WAITING/BLOCKED/FAILED
    ↓
取得 active_step
    ↓
检查输入
    ↓
解析 Story loop
    ↓
调用 callback
    ↓
验证 callback 返回类型
    ↓
验证输出 gate
    ↓
更新步骤或 Story 状态
    ↓
持久化 checkpoint
    ↓
返回 WorkflowRunResult
```

普通步骤的状态变化：

```text
PENDING
  ├─ 输入缺失 → BLOCKED
  ├─ 执行失败 → FAILED
  ├─ 输出 gate 失败 → BLOCKED
  ├─ 成功且有 checkpoint → WAITING_USER
  ├─ 成功且还有后续步骤 → PENDING(active_step + 1)
  └─ 最后一步成功 → COMPLETED
```

恢复路径：

```text
WAITING_USER ─┐
BLOCKED       ├─ /goal resume → PENDING
FAILED        ┘
```

当前 Runner 还处理：

- Story 顺序推进；
- Story 输出保存；
- 已完成 Story 去重；
- 同一 Epic 内的 bounded parallel batch；
- 批内单个 Story 失败而不取消其他 Story；
- Story gate 验证；
- workflow step 事件；
- 状态恢复后的配置一致性检查。

### 2.9 Checkpoint 持久化

主要模型：

```python
WorkflowCheckpoint
GoalWorkflowState
```

存储：

```text
.heagent/checkpoints/<goal-id>/*.json
_he-output/goals/<goal-id>/workflow.json
```

CheckpointStore 负责：

- JSON 模型读取；
- 损坏文件显性失败；
- Goal ID 一致性；
- checkpoint ID 路径安全；
- 相同 ID 的幂等冲突检测；
- 原子写入；
- 聚合工作流状态写入；
- 进程内锁。

恢复策略不是简单选择最新文件，而是优先按照：

```text
active_step + active_skill + status
```

匹配聚合状态和 checkpoint。状态不匹配时显性抛错，避免静默从错误位置重建。

### 2.10 跨进程互斥

`cli/goal.py` 中的 `_goal_mutex()` 组合：

```text
asyncio.Lock
    +
.heagent/goal.lock 文件锁
```

覆盖 Goal 状态变更入口：

- new；
- next；
- run 内的推进；
- resume；
- reset；
- cron 推进。

目的：避免两个 CLI、CLI 与 GUI、手动与 cron 同时读取旧状态并互相覆盖。

## 3. 标准使用方式

### 3.1 新建目标

```text
/goal new 做一个本地优先的个人知识库，支持 Markdown、全文检索和 AI 问答
```

适用于从需求到交付的完整任务。

不建议把以下任务放进 `/goal`：

```text
修一个 typo
查一个函数
解释一个错误
修改一处配置
```

### 3.2 单步推进

```text
/goal next
```

适合每完成一个阶段或 Story 后人工检查。

### 3.3 连续推进

```text
/goal run
```

适合：

- 工作流已经成熟；
- 当前阶段风险较低；
- 用户希望连续完成多个自动步骤。

不适合在产品范围、架构和 Story 冻结阶段无审查地长时间运行。

### 3.4 查看状态

```text
/goal status
```

当前主要查看：

- 已完成步骤数；
- 当前状态；
- 当前活动步骤；
- 是否等待用户。

### 3.5 回复等待状态

```text
/goal resume 先支持 Windows 和 macOS，Linux 放到第二期
```

这会把回复持久化到 Goal 文档，然后恢复当前活动步骤。

### 3.6 暂停

```text
/goal pause
```

适用于：

- 需要人工审查当前方向；
- 暂时没有 Provider 或网络；
- 要先修改输入文档；
- 要暂时停止自动推进。

### 3.7 自动推进

```text
/goal auto
/goal auto */30 * * * *
/goal auto off
```

默认工作流的 cron 是：

```text
*/15 * * * *
```

自动推进不会因为无人值守而自动提升工具权限，也不会绕过 Engine 的治理链。

### 3.8 重置当前指针

```text
/goal reset
```

只清除当前 Goal 指针，不删除 Goal 目录和历史产物。

### 3.9 推荐的实际操作节奏

产品型 Goal 建议：

```text
/goal new ...
/goal status
/goal next          # Step 01
/goal next          # Step 02
/goal next          # Step 03
/goal resume ...    # 如果遇到需求裁决
/goal next          # Step 04
/goal next          # Step 05
/goal next          # Step 06
```

Step 06 生成并冻结 Story 后，再考虑：

```text
/goal run
```

实现阶段建议每个 Sprint 或每个 Epic 收口检查一次：

```text
/goal status
检查 git diff
检查 Story 报告
检查测试证据
/goal next
```

## 4. 与 Codex、Claude Code 的对照

### 4.1 先明确产品定位差异

三者不是完全相同的产品：

- `/goal`：项目生命周期和交付治理；
- Codex 类工具：通用代码任务执行和仓库修改；
- Claude Code 类工具：终端内通用 coding agent，强调上下文、工具、Skills、子代理和开发工作流。

更准确的比较不是“谁替代谁”，而是：

```text
Codex/Claude Code = 通用执行引擎与 coding agent 体验
HeAgent /goal     = 有持久计划、阶段门禁和交付证据的项目流程层
```

### 4.2 能力对照

| 维度 | HeAgent `/goal` | Codex 类体验 | Claude Code 类体验 |
|---|---|---|---|
| 主要单位 | Goal → Step → Epic → Story | 任务/会话/代码变更 | 任务/会话/子代理/Skill |
| 规划 | 8 步强约束流程 | 更灵活，计划随任务演进 | 计划、上下文和用户协作较灵活 |
| 长期状态 | 文件 checkpoint + workflow.json | 通常偏会话和任务状态 | 会话、项目上下文、Skill、hooks 组合 |
| 需求冻结 | 原始需求、Story AC 可冻结 | 多依赖用户和任务约定 | 可通过计划和用户确认实现 |
| 执行反馈 | 步骤/Story 事件和报告 | 强调 diff、命令和测试反馈 | 强调终端工具反馈和工作区修改 |
| 工具治理 | PolicyEngine → Executor → SafetyGuard | 取决于运行环境和审批设置 | 取决于权限模式、hooks、sandbox 和配置 |
| 工作流扩展 | workflow.md、角色 Skill | 命令、配置、任务方式 | Skills、commands、hooks、subagents、MCP |
| 自动调度 | 内置 cron `/goal auto` | 通常不是核心任务交互 | 通常不是核心 Goal 调度能力 |
| 产物组织 | 明确的 Goal/Step/Epic/Story 目录 | 常以代码 diff 和任务结果为中心 | 常以仓库、会话和报告为中心 |
| 适应简单任务 | 偏重 | 好 | 好 |
| 适应复杂项目治理 | 强 | 需要外部流程 | 需要外部流程或团队约定 |

### 4.3 `/goal` 的优势

#### 需求和交付边界更明确

`/goal` 把以下边界写进工作流：

- 原始需求逐字冻结；
- Step 01 负责初步需求总结；
- Step 06 冻结 Story 验收标准；
- Step 07 才允许常规实现；
- Step 08 只允许修复自身发现的 Critical 集成缺陷。

这能减少“实现过程中修改目标”的漂移。

#### 失败可以原位恢复

普通聊天式 Agent 往往依赖上下文记忆继续；`/goal` 则把以下状态落盘：

- active step；
- active story；
- completed steps；
- completed stories；
- outputs；
- checkpoint；
- 用户补充；
- 失败原因。

#### 方法论可以通过 Skill 包升级

步骤角色、prompt 模板、gate 模板和工作流契约可以随着 Skill 包调整，而不是全部硬编码到 CLI。

#### 多入口一致性

CLI、GUI 和 cron 共享 `goal/application.py` 的确定性推进逻辑，避免三套工作流行为漂移。

### 4.4 `/goal` 的不足

#### 对小任务太重

默认 8 步流程适合立项型工作，不适合普通工程修改。

#### 自动 checkpoint 可能跳过高价值人工决策

当前默认：

```yaml
checkpoint_mode: auto
open_question_mode: default
```

这可能让模型在用户尚未确认 PRD、架构和 Story 时继续推进。

#### 文本报告不等于真实证据

当前 gate 主要检查 Markdown 结构和内容。模型可以输出：

```markdown
## 测试证据
pytest ... 通过
```

但报告本身不能证明命令真的执行过。

#### 并行 Story 的安全条件还不够强

`max_parallel_stories` 只表示并行数量，不自动证明 Story 的文件写集不相交。

#### 状态转换没有独立事件模型

当前逻辑散落在 `WorkflowRunner`、`goal/application.py` 和 `cli/goal.py`。增加更多状态后，条件分支会膨胀。

#### `/goal status` 信息不足

用户目前难以在一个命令中看到：

- 当前 Story；
- 当前 Epic；
- 测试状态；
- 未决问题；
- 自动接受的假设；
- Git 变更；
- 最近一次失败原因；
- 下一步准确动作。

## 5. 优化目标

### 5.1 产品目标

优化后的 `/goal` 应该满足：

1. 简单任务不被 8 步流程拖慢。
2. 复杂任务仍有持久的计划、状态和恢复能力。
3. 用户可以在关键阶段做明确审批。
4. 每个 Story 的完成有真实工具证据，而不是只有模型报告。
5. 自动推进不会突破权限、范围和质量门禁。
6. 并行只发生在可证明安全的任务之间。
7. CLI、GUI、cron 和未来 HTTP 使用同一领域模型。
8. 不可信 workflow 或脚本不会被误当作安全边界。

### 5.2 架构原则

#### 原则一：状态机只有一个

```text
WorkflowRunner = 唯一状态机运行时
```

任何脚本、GUI、cron、CLI 都不能各自维护一份进度。

#### 原则二：声明和执行分离

```text
workflow.md / GoalScript = 声明和扩展
WorkflowRunner            = 执行、恢复和持久化
```

#### 原则三：报告和证据分离

```text
Markdown report = 给人读
EvidenceRecord = 给系统验证
```

#### 原则四：用户审批是结构化事件

不要只把用户回复拼接进 prompt，应记录：

- decision id；
- 决策类型；
- 作用步骤；
- 用户原文；
- 发生时间；
- 影响范围；
- 是否改变工作流分支。

#### 原则五：脚本扩展不能越过治理链

所有文件写、命令执行、Provider 调用、网络访问都必须通过受控端口。

## 6. 优化方案总览

### Phase 0：预检与控制面

先解决“用户不知道当前 Goal 是否能跑、跑到哪、下一步是什么”。

新增：

```text
/goal doctor
/goal report
/goal changes
```

不改变状态机，不改变 checkpoint 格式。

### Phase 1：显式状态事件和转换表

新增：

```python
WorkflowEvent
WorkflowTransition
WorkflowTransitionError
```

把当前条件分支收敛为可校验的转换表。

### Phase 2：真实执行证据

新增：

```python
EvidenceRecord
CommandEvidence
GitEvidence
QualityGateEvidence
```

把命令退出码、耗时、Git base/head、变更文件和质量门禁纳入状态。

### Phase 3：步骤级审批和工作流模板

引入：

- 步骤级 checkpoint 策略；
- 产品型、工程型、迁移型、安全型工作流；
- `approve`、`reject`、`amend`；
- 对未决问题和自动假设的清晰展示。

### Phase 4：受控脚本化

增加 `GoalScript` 和 `ScriptRuntime`，但不允许脚本直接控制状态持久化或工具执行。

### Phase 5：安全并行和项目控制面

增加：

- Story dependency graph；
- `write_set`；
- 并行前冲突检查；
- 不能证明安全时自动串行；
- 更完整的 CLI/GUI/JSON 控制面。

## 7. Phase 0：预检与控制面

### 7.1 `/goal doctor`

检查项目：

- `GOAL_WORKFLOW_SKILL` 是否可解析；
- `workflow.md` 是否完整；
- `required_resources` 是否满足；
- 每个 `role` Skill 是否存在；
- 模板是否非空；
- checkpoint 目录是否可读写；
- 当前 Goal 文档是否有效；
- provider 是否可构造；
- 当前工作区是否存在冲突性未提交变更；
- 是否有足够的工具权限；
- cron 是否启用；
- 脚本模式是否被禁用；
- manifest/lock 内容完整性是否通过。

输出分级：

```text
PASS
WARN
FAIL
```

禁止把 warning 伪装成成功。

### 7.2 `/goal status` 升级

建议输出：

```text
Goal: local-knowledge-base
State: RUNNING
Progress: 6/8 steps

Current:
- Step: 07 implement-story
- Epic: E2 Search
- Story: S-5 Full-text index
- Status: waiting_user
- Reason: test evidence is incomplete

Delivery:
- Stories: 4/9 completed
- Last test: failed
- Last command: pytest tests/test_search.py -q
- Open decisions: 2
- Auto assumptions: 3
- Deferred items: 1

Next:
- /goal resume <decision>
- /goal verify
```

实现上建议由 `GoalStatusView` Pydantic 模型提供统一数据，而不是让 CLI 直接拼接多个 JSON 文件。

### 7.3 `/goal report`

支持：

```text
/goal report
/goal report --json
```

报告包括：

- Goal 元数据；
- workflow 版本/hash；
- Step 时间线；
- Story 进度；
- checkpoint；
- 未决决策；
- 假设；
- 测试和质量门禁；
- Git 变更；
- Deferred work；
- 当前推荐动作。

## 8. Phase 1：显式化状态机

### 8.1 新增事件模型

建议：

```python
class WorkflowEvent(StrEnum):
    START = "start"
    INPUT_MISSING = "input_missing"
    STEP_COMPLETED = "step_completed"
    CHECKPOINT_REQUIRED = "checkpoint_required"
    GATE_FAILED = "gate_failed"
    EXECUTOR_FAILED = "executor_failed"
    USER_PAUSE = "user_pause"
    USER_RESUME = "user_resume"
    FINAL_STEP_COMPLETED = "final_step_completed"
    CANCELLED = "cancelled"
```

### 8.2 转换表

| 来源状态 | 事件 | 目标状态 |
|---|---|---|
| `PENDING` | `START` | `RUNNING` |
| `PENDING` | `INPUT_MISSING` | `BLOCKED` |
| `RUNNING` | `STEP_COMPLETED` | `PENDING` |
| `RUNNING` | `CHECKPOINT_REQUIRED` | `WAITING_USER` |
| `RUNNING` | `GATE_FAILED` | `BLOCKED` |
| `RUNNING` | `EXECUTOR_FAILED` | `FAILED` |
| `RUNNING` | `CANCELLED` | `PENDING` |
| `RUNNING` | `FINAL_STEP_COMPLETED` | `COMPLETED` |
| `WAITING_USER` | `USER_RESUME` | `PENDING` |
| `BLOCKED` | `USER_RESUME` | `PENDING` |
| `FAILED` | `USER_RESUME` | `PENDING` |
| `PENDING`/`RUNNING` | `USER_PAUSE` | `WAITING_USER` |

转换表只负责状态，不负责副作用。

### 8.3 代码改造边界

第一步不要改 checkpoint 外部格式，只做内部收敛：

1. 新增 `workflow_events.py`；
2. 新增 `workflow_transition.py`；
3. 将 `run_step()` 中的状态赋值集中到 transition 函数；
4. `goal/application.py` 的 pause/resume 也调用同一转换入口；
5. CLI 只负责把用户动作映射成事件；
6. 为每个合法转换补测试；
7. 为非法转换补负向测试。

### 8.4 验收标准

- 现有 Goal 行为不变；
- 旧 checkpoint 可恢复；
- 不存在无记录的状态赋值；
- 非法转换显性失败；
- 状态事件可被事件总线观测；
- 去掉转换校验后新增负向测试精确变红。

## 9. Phase 2：真实执行证据

### 9.1 为什么必须做

当前 Markdown 报告只能说明 Agent 声称做了什么，不能证明：

- 命令是否真的运行；
- 命令是否在正确工作区运行；
- 退出码是否为 0；
- 测试是否覆盖当前变更；
- Git diff 是否符合 Story 范围。

对于“从需求到交付”的 `/goal`，这是最大的可信度缺口。

### 9.2 EvidenceRecord

建议新增 Pydantic 模型：

```python
class CommandEvidence(BaseModel):
    command: str
    exit_code: int
    duration_ms: int
    stdout_digest: str = ""
    stderr_digest: str = ""
    cwd: str

class GitEvidence(BaseModel):
    base: str
    head: str
    changed_files: list[str]
    untracked_files: list[str]

class QualityGateEvidence(BaseModel):
    name: str
    status: Literal["passed", "failed", "skipped"]
    command_evidence: list[str]
    reason: str = ""

class EvidenceRecord(BaseModel):
    schema_version: str = "1"
    goal_id: str
    workflow_id: str
    workflow_revision: str
    step: str
    story_id: str | None = None
    commands: list[CommandEvidence] = []
    git: GitEvidence | None = None
    quality_gates: list[QualityGateEvidence] = []
```

文件位置：

```text
_he-output/goals/<goal-id>/step-07-implement-story/epic-<eN>/s-<n>/evidence.json
```

### 9.3 命令执行原则

命令必须通过现有工具执行路径，不允许让报告字符串冒充结果。

命令证据至少记录：

- 原始命令或经过安全规范化的命令；
- 工作目录；
- 退出码；
- 开始/结束时间或耗时；
- stdout/stderr 摘要或 digest；
- 是否因超时、取消或策略阻断结束。

不建议把完整 stdout 默认复制到 Goal 报告，避免：

- 凭证泄漏；
- 工具输出过大；
- prompt 和产物无限膨胀。

### 9.4 gate 由文本扩展到结构化验证

兼容现有：

```yaml
validation: section: 测试证据
```

新增：

```yaml
validation:
  sections:
    - 实现摘要
    - 测试证据
    - 验证结论
  artifacts:
    required:
      - implementation.md
      - test-report.md
      - verify-report.md
  commands:
    - pytest tests/test_goal_application.py -q
  git:
    forbid_paths:
      - .env
      - .heagent/memory/**
```

规则：

- 缺少指定证据则不能通过；
- 命令退出码非 0 则 gate 失败；
- 命令未执行不能由 Markdown 报告补齐；
- gate 失败进入 `BLOCKED`；
- gate 不得降低全局安全策略。

## 10. Phase 3：步骤级审批和工作流模板

### 10.1 当前问题

当前工作流全局使用：

```yaml
checkpoint_mode: auto
open_question_mode: default
```

这适合无人值守推进，但不适合高风险产品决策。

### 10.2 步骤级策略

建议支持：

```yaml
checkpoint: approval_required
```

或者：

```yaml
checkpoint:
  mode: approval_required
  summary:
    - 产品价值
    - 非目标
    - 关键风险
    - 未决决策
```

建议默认必须人工确认的节点：

- Step 04：产品范围；
- Step 05：架构方案；
- Step 06：Story 和验收标准。

Step 01 和 Step 02 可以默认自动推进；Step 07 是否自动推进由项目配置决定。

### 10.3 新的用户命令

建议增加：

```text
/goal approve
/goal reject <原因>
/goal amend <补充>
/goal decisions
```

语义：

- `approve`：批准当前 checkpoint；
- `reject`：保持当前步骤，记录拒绝原因；
- `amend`：记录补充并要求重新执行当前步骤；
- `decisions`：列出所有未决和已决策项。

不建议继续让 `/goal resume <任意文本>` 同时承担“恢复、批准、否决、补充需求”四种语义。

### 10.4 多种工作流模板

当前 8 步流程偏产品立项。建议拆成多个工作流包：

```text
he-goal-product
he-goal-engineering
he-goal-migration
he-goal-security
```

建议：

| 工作流 | 步骤重点 |
|---|---|
| product | 调研 → 构思 → 需求 → 范围 → 架构 → Story → 实现 → 集成 |
| engineering | 代码库勘察 → 影响分析 → 设计 → Story → 实现 → 回归 |
| migration | 现状盘点 → 兼容矩阵 → 试迁移 → 批量迁移 → 回滚演练 |
| security | 威胁建模 → 攻击面 → 修复计划 → 修复 → 攻击性验证 |

入口可以是：

```text
/goal new --workflow he-goal-engineering <目标>
```

工作流选择必须在 Goal 创建时固定并写入元数据，不能在中途静默更换。

## 11. Phase 4：受控脚本化

### 11.1 为什么不先做

脚本化最容易被误解成“把流程写成 Python 就解决了”。实际上任意脚本会带来：

- 任意文件读写；
- 任意子进程；
- 任意网络访问；
- 直接篡改状态；
- 绕过工具审批；
- 难以恢复的内存状态；
- 第三方 workflow 包代码执行风险。

所以脚本化必须建立在 Phase 1 的显式事件和 Phase 2 的证据模型上。

### 11.2 受控 Script API

示意：

```python
async def build_workflow(goal: GoalScript) -> None:
    inspection = await goal.step(
        name="inspect",
        role="bmad-agent-analyst",
        output="inspection.md",
        validation=["section: 现状", "section: 风险"],
    )

    await goal.checkpoint(
        name="approve-design",
        summary=["架构边界", "数据流", "主要风险"],
    )

    await goal.step(
        name="design",
        role="bmad-agent-architect",
        inputs=[inspection],
    )
```

允许：

- 声明步骤；
- 引用受控产物；
- 条件判断已持久化结果；
- 有界循环；
- 请求 checkpoint；
- 请求验证；
- 记录假设和用户决策。

禁止：

- 直接写 checkpoint；
- 直接写 `workflow.json`；
- 直接改 `current`；
- 任意 `Path.write_text`；
- 任意 shell/subprocess；
- 直接调用 Provider；
- 直接修改 PolicyEngine；
- 直接 commit。

### 11.3 脚本恢复原则

脚本可能在每次恢复时从入口重新执行，因此：

- 不能把 Python 局部变量当作进度；
- 所有进度必须经 Runner 持久化；
- 条件分支必须基于持久化输入、产物或 decision record；
- 非幂等动作必须由宿主提供幂等键；
- 脚本必须有最大步骤数、最大深度和总时限；
- 超时和取消必须生成 checkpoint；
- 恢复不能自动跳过未完成步骤。

### 11.4 脚本安全姿态

第一阶段只允许可信本地 workflow 包。

后续如果支持第三方脚本，必须引入：

```text
Host process
    ⇄ 受限 RPC/JSONL
Sandboxed script worker
```

脚本 worker 不能直接接触宿主 checkpoint 目录，所有状态更新由宿主验证后提交。

无论如何，仍需 OS 级沙箱。HeAgent 内置 SafetyGuard、PolicyEngine 和 sandbox 不是安全边界。

## 12. Phase 5：安全并行 Story

### 12.1 当前问题

```yaml
max_parallel_stories: 3
```

只说明并发数量，不说明：

- Story 是否互相依赖；
- 是否修改同一文件；
- 是否共享同一配置；
- 是否会产生顺序依赖；
- 是否可以安全合并。

### 12.2 Story 计划增加写集

Step 06 为每条 Story 生成：

```yaml
parallel_group: e1-search
write_set:
  - src/heagent/search/**
  - tests/test_search.py
depends_on:
  - S-2
```

Runner 并行前检查：

- 依赖已完成；
- 写集不相交；
- 不共享受保护的单写者文档；
- 归属同一 Epic；
- checkpoint ID 独立；
- 当前工作区状态允许并行。

任何无法证明安全的组合自动串行。

### 12.3 后续 worktree

第一阶段不立即引入 Git worktree。

如果写集检测仍不足，再考虑：

```text
每条并行 Story 一个临时 worktree
    ↓
独立测试
    ↓
统一冲突检查
    ↓
集成分支验证
```

但这会增加：

- Windows 文件句柄问题；
- 临时 worktree 清理；
- 子进程生命周期；
- 用户可见 diff 组织；
- 合并失败恢复。

不应作为第一批改动。

## 13. 代码与文件改造计划

### 13.1 Phase 0 文件

建议新增：

```text
src/heagent/goal/status_view.py
src/heagent/goal/doctor.py
src/heagent/goal/report.py
```

入口修改：

```text
src/heagent/cli/goal.py
```

测试：

```text
tests/test_goal_status_view.py
tests/test_goal_doctor.py
tests/test_goal_report.py
```

### 13.2 Phase 1 文件

建议新增：

```text
src/heagent/goal/workflow_events.py
src/heagent/goal/workflow_transition.py
```

修改：

```text
src/heagent/engine/workflow_runner.py
src/heagent/goal/application.py
src/heagent/cli/goal.py
```

测试：

```text
tests/test_goal_transitions.py
tests/test_goal_workflow_events.py
```

同时更新：

```text
tests/test_architecture_contracts.py
```

如果新增解析器或跨包依赖，必须同步架构契约。

### 13.3 Phase 2 文件

建议新增：

```text
src/heagent/goal/evidence.py
src/heagent/goal/quality_gates.py
```

可能修改：

```text
src/heagent/engine/workflow_resource.py
src/heagent/engine/workflow_runner.py
src/heagent/tools/call_summary.py
src/heagent/cli/goal.py
```

测试：

```text
tests/test_goal_evidence.py
tests/test_goal_quality_gates.py
```

### 13.4 Phase 3 文件

建议新增：

```text
src/heagent/goal/decisions.py
```

修改：

```text
src/heagent/goal/application.py
src/heagent/cli/goal.py
src/heagent/engine/workflow_resource.py
```

Skill 包新增工作流资源，而不是把流程分支写进 CLI。

### 13.5 Phase 4 文件

建议新增：

```text
src/heagent/goal/script_api.py
src/heagent/goal/script_loader.py
src/heagent/goal/script_runtime.py
```

相关测试：

```text
tests/test_goal_script_api.py
tests/test_goal_script_runtime.py
tests/test_goal_script_security.py
```

在脚本模式实现前，必须先阅读并遵守项目安全声明，不得把 Python 脚本执行误称为 sandbox。

## 14. 质量门禁与负向验证

每个阶段都必须遵守“先跑后写”和负向验证纪律。

### 14.1 Phase 0

正向：

```text
/goal doctor 能正确识别有效包、缺失角色、缺失模板、不可写 checkpoint
```

负向：

- 删除角色包时 doctor 不得仍报 PASS；
- 损坏 workflow 时 doctor 不得仍报 PASS；
- 不可写状态目录时不能继续执行。

### 14.2 Phase 1

正向：

- 每个合法转换通过；
- 每个现有 CLI 操作仍得到相同结果；
- 旧 checkpoint 可以恢复。

负向：

- 删除非法转换拒绝逻辑后测试必须变红；
- 绕过 transition 函数的直接状态赋值应被架构测试或静态检查发现；
- 把 `BLOCKED` 直接改成 `COMPLETED` 必须变红。

### 14.3 Phase 2

正向：

- 真实成功命令生成 exit code 0 证据；
- 真实失败命令生成非零证据；
- Story 报告与 evidence 可以互相定位。

负向：

- 只写 Markdown、不执行命令时不能通过命令 gate；
- 把失败退出码改成 0 的变异体必须变红；
- 把错误工作目录改成目标目录时测试必须变红。

### 14.4 Phase 4

正向：

- 脚本条件分支可以恢复；
- 取消后状态可继续；
- 重复执行不会重复完成同一 checkpoint。

负向：

- 脚本直接写 checkpoint 必须被拒；
- 脚本直接启动子进程必须被拒；
- 脚本直接改 `current` 必须被拒；
- 超出最大步骤数必须失败；
- 脚本包资源 hash 漂移必须显性失败。

## 15. 兼容性和迁移策略

### 15.1 旧 Goal

必须继续支持：

- `brief.md`；
- `require.md`；
- `GOAL.md`；
- 旧 checkpoint；
- 旧的 `workflow.json` 聚合状态。

不要通过重命名文件强制迁移存量 Goal。

### 15.2 旧 workflow 包

没有新增字段时使用现有默认值：

```text
executor_mode = declarative
checkpoint = 当前兼容语义
validation = 当前字符串解析语义
```

新增结构化字段采用向后兼容解析：

- 新字段缺失时回到旧行为；
- 新字段非法时显性失败；
- 不能把非法新配置静默解释成旧配置。

### 15.3 checkpoint 版本

Phase 1 不改外部 JSON 格式。

Phase 2 以后如需新增 evidence 或 decision 字段，建议：

```text
schema_version
```

并提供：

- 旧版本读取；
- 新版本只在明确迁移后写入；
- 迁移失败 fail-loud；
- 不覆盖原始 checkpoint；
- 迁移测试和回滚说明。

## 16. 实施优先级

### P0：可信度和可恢复性

1. `/goal doctor`；
2. `/goal status` 升级；
3. `WorkflowEvent` 和 transition table；
4. 状态转换黄金测试；
5. 结构化 Story/Goal 报告。

### P1：交付证据

1. `EvidenceRecord`；
2. 命令退出码和耗时记录；
3. Git 变更集；
4. 真实质量 gate；
5. `/goal verify`。

### P1：人工决策

1. Step 04/05/06 步骤级审批；
2. `approve/reject/amend`；
3. decisions 记录；
4. 自动假设清单。

### P2：体验和覆盖面

1. 工程型 workflow；
2. 迁移型 workflow；
3. 安全型 workflow；
4. `/goal report --json`；
5. GUI Goal 控制面。

### P2：高级扩展

1. `GoalScript`；
2. 写集和依赖检查；
3. 条件分支；
4. 安全并行；
5. 隔离 worker。

## 17. 产品裁决清单

实现前需要用户或项目维护者明确：

1. Step 04、05、06 是否默认改为人工审批？建议是。
2. 脚本模式是否默认关闭？建议是。
3. 是否只允许项目管理员安装的 workflow 包启用脚本？建议第一阶段是。
4. 质量 gate 中的命令是否由 workflow 声明，还是由项目级配置声明？建议第一阶段只允许可信 workflow。
5. 是否引入工程型、迁移型和安全型 Goal 包？建议是，不把所有目标强行套进产品流程。
6. 是否允许 `/goal run` 在实现阶段自动跨越多个 Story？建议提供项目级开关，默认一次一条 Story。
7. 并行 Story 第一阶段是否只做写集检测？建议是，不立即引入 worktree。
8. 是否接受后续隔离 worker 来执行不可信脚本？如果要支持第三方脚本，建议必须接受。

## 18. 最终推荐方案

推荐的目标形态：

```text
简单工程任务
    → 普通 Agent Loop

复杂工程任务
    → he-goal-engineering

产品立项任务
    → he-goal-product

迁移任务
    → he-goal-migration

安全整改任务
    → he-goal-security

所有工作流
    → 同一个 WorkflowRunner
    → 同一个 CheckpointStore
    → 同一个工具治理链
    → 同一套 EvidenceRecord
```

最终边界：

```text
workflow.md / GoalScript = 方法和流程表达
WorkflowRunner           = 状态、转换、恢复和推进
CheckpointStore          = 唯一持久化入口
EvidenceRecord           = 真实执行证据
ToolExecutor             = 工具执行治理
Git                      = 用户确认后的版本交付
OS sandbox               = 真正安全边界
```

最优先的工程动作不是“把 `/goal` 改成脚本”，而是：

1. 先让状态转换可观测、可验证；
2. 再让 Story 完成依赖真实命令和 Git 证据；
3. 再增加关键阶段的人工审批；
4. 最后才增加受控脚本化和安全并行。

这样可以在不破坏现有 Goal 和 checkpoint 兼容性的前提下，逐步把 `/goal` 从“严格流程编排器”提升为“可恢复、可审计、可验证的软件交付工作流”。


---

# 附录 A：工作流运行时与受控脚本化专项设计（原独立方案全文）

> 本附录保留原专项方案的完整技术细节。与正文重复处，以正文的 Phase 0–5 路线和 Epic 51 规划为准；涉及 GoalScript、ScriptRuntime、安全边界和恢复语义的细节以本附录为补充。

> 状态：方案设计，尚未实现。
>
> 目标：保留 `WorkflowRunner` 作为 `/goal` 的可信状态机运行时，同时提供受控的脚本化工作流能力。脚本可以表达条件、循环和领域逻辑，但不得直接接管状态持久化、checkpoint、工具治理或安全策略。

## 1. 决策摘要

### 1.1 采用的方案

采用四层结构：

```text
workflow.md / 受控 GoalScript
        ↓
WorkflowCompiler / ScriptAdapter
        ↓
WorkflowRunner（唯一状态机运行时）
        ↓
CheckpointStore + SubAgent + PolicyEngine/ToolExecutor/SafetyGuard
```

- `workflow.md` 继续作为默认的声明式工作流格式。
- 新增受控的 Python `GoalScript` API，解决声明式 DSL 难以表达的条件分支、循环和动态输入问题。
- `WorkflowRunner` 继续负责状态转换、输入检查、Story loop、gate、checkpoint、恢复、幂等和事件。
- 脚本不得直接写 `workflow.json`、checkpoint JSON、Goal current 指针或工具结果。
- 脚本中的 Agent 执行必须经过入口层注入的执行端口，最终仍进入既有工具治理链：

```text
PolicyEngine.evaluate()
    → ToolExecutor
    → SafetyGuard.check()
    → handler
```

### 1.2 不采用的方案

不采用“shell/Makefile 串联多个 prompt 并把文件存在性当作状态”的方案，原因是它无法可靠覆盖：

- `WAITING_USER`、`BLOCKED`、`FAILED` 的恢复语义；
- Story 级 checkpoint 和部分并行失败；
- checkpoint 幂等冲突检测；
- 跨进程锁和原子落盘；
- 工具在途保护；
- 统一事件和审计；
- 不绕过安全治理。

不允许脚本直接修改 `WorkflowRunnerState` 或手写 checkpoint 作为正常扩展方式。

## 2. 现状与问题

### 2.1 当前代码事实

状态机已在代码中实现：

- `src/heagent/engine/workflow_runner.py`
  - `WorkflowRunner.run_step()`：执行活动步骤、验证结果、推进状态；
  - `_step_advance_update()`：普通步骤推进；
  - `_story_advance_update()`：Story loop 推进；
  - `_run_story_batch()`：同一 Epic 内的有界并行 Story；
  - `resume()`：从等待、阻塞或失败状态恢复；
  - `_validate_state()`：恢复后的基础状态校验。
- `src/heagent/engine/checkpoint.py`
  - `WorkflowStatus`：`PENDING`、`RUNNING`、`WAITING_USER`、`BLOCKED`、`FAILED`、`COMPLETED`；
  - `WorkflowCheckpointStore`：原子落盘、损坏检测、Goal 归属检查、幂等冲突检测。
- `src/heagent/goal/application.py`
  - `advance()`：装配输入、选择 Story、调用 Runner、处理 checkpoint 决策；
  - `pause_resume()`：命令边界的暂停/恢复。
- `src/heagent/cli/goal.py`
  - CLI/GUI/cron 的入口适配、消息渲染、Goal 互斥锁和 SubAgent 执行缝。

### 2.2 当前不足

1. 状态转换通过条件分支表达，没有独立的事件模型和可审计 transition table。
2. 声明式 `workflow.md` 对动态分支、循环和运行时决策的表达能力有限。
3. 如果直接允许任意 Python 脚本，会产生任意文件、进程、网络和状态篡改面。
4. 当前步骤报告偏文本化，真实命令、Git 变更和质量门禁还没有统一的结构化证据模型。
5. 并行 Story 主要按 `max_parallel_stories` 控制，缺少计划期写集和依赖证明。

## 3. 目标与非目标

### 3.1 目标

- 保持已有 `workflow.md` 的兼容性。
- 让脚本能够表达：
  - 条件分支；
  - 有界循环；
  - 动态输入；
  - 用户审批点；
  - 自定义验证逻辑。
- 让所有脚本执行仍经过统一状态机和安全治理。
- 让同一工作流可由 CLI、GUI、cron 和未来 HTTP/库入口运行。
- 让恢复行为在 Python 进程重启后保持一致。
- 为后续结构化执行证据、状态图校验和 `/goal doctor` 留出接口。

### 3.2 非目标

- 不在本方案中实现任意 Python 沙箱。
- 不把 `SafetyGuard`、`PolicyEngine` 或 HeAgent 内置 sandbox 宣称为 OS 安全边界。
- 不实现自动 Git commit。
- 不允许脚本默认绕过审批、workspace 围栏或 MCP 限制。
- 不立即重写现有 `he-goal` 工作流。
- 不引入第二套 checkpoint 格式。

## 4. 目标架构

### 4.1 模块布局

建议新增模块：

```text
src/heagent/goal/
├── application.py              # 现有 use-case
├── document.py                 # 现有 Goal 文档层
├── naming.py                   # 现有命名层
├── workflow_loader.py          # 现有声明式装载
├── workflow_events.py          # 新：状态事件与转换模型
├── workflow_transition.py      # 新：统一转换表与校验
├── script_api.py               # 新：受控 GoalScript API
├── script_loader.py             # 新：脚本发现、元数据和入口校验
└── script_runtime.py            # 新：脚本适配到 WorkflowRunner
```

`engine/` 继续持有与入口无关的通用状态机和 checkpoint：

```text
src/heagent/engine/
├── workflow_runner.py          # 状态机唯一运行时
├── workflow_resource.py        # 工作流资源模型
└── checkpoint.py               # 持久化模型与存储
```

### 4.2 入口关系

```text
cli/goal.py
    ├─ workflow.md → workflow_loader → WorkflowResource
    └─ script.py   → script_loader → GoalScriptDefinition
                                      ↓
                              ScriptRuntime / WorkflowRunner
```

脚本运行时不能反向导入 `cli`、`gui` 或具体 Provider。执行端口由入口层注入，遵守当前架构依赖方向。

## 5. 状态事件模型

### 5.1 新增事件类型

建议增加内部事件枚举：

```python
class WorkflowEvent(StrEnum):
    START = "start"
    STEP_COMPLETED = "step_completed"
    CHECKPOINT_REQUIRED = "checkpoint_required"
    USER_RESUME = "user_resume"
    USER_PAUSE = "user_pause"
    INPUT_MISSING = "input_missing"
    GATE_FAILED = "gate_failed"
    EXECUTOR_FAILED = "executor_failed"
    FINAL_STEP_COMPLETED = "final_step_completed"
    CANCELLED = "cancelled"
```

事件只描述“发生了什么”，不携带可执行权限。

### 5.2 标准转换表

| 当前状态 | 事件 | 目标状态 | 说明 |
|---|---|---|---|
| `PENDING` | `START` | `RUNNING` | 开始执行当前步骤 |
| `PENDING` | `INPUT_MISSING` | `BLOCKED` | 必需输入不存在 |
| `RUNNING` | `STEP_COMPLETED` | `PENDING` | 已完成且还有后续步骤 |
| `RUNNING` | `CHECKPOINT_REQUIRED` | `WAITING_USER` | 步骤完成但需要用户确认 |
| `RUNNING` | `GATE_FAILED` | `BLOCKED` | 输出不满足门禁 |
| `RUNNING` | `EXECUTOR_FAILED` | `FAILED` | 执行端失败 |
| `RUNNING` | `FINAL_STEP_COMPLETED` | `COMPLETED` | 最后一步完成 |
| `WAITING_USER` | `USER_RESUME` | `PENDING` | 用户同意或补充信息后恢复 |
| `BLOCKED` | `USER_RESUME` | `PENDING` | 用户确认重新执行活动步骤 |
| `FAILED` | `USER_RESUME` | `PENDING` | 用户明确允许重试 |
| `PENDING` / `RUNNING` | `USER_PAUSE` | `WAITING_USER` | 用户主动暂停 |

非法转换必须抛出 `WorkflowTransitionError`，不得静默修正。

### 5.3 迁移策略

第一阶段不改变外部状态值，也不改变 checkpoint JSON 结构。

- 先将现有条件分支提取为内部 `transition(source, event)` 函数。
- 用现有 `WorkflowStatus` 值映射事件。
- 增加黄金测试锁定合法转换。
- 后续再考虑把 `last_event`、`transition_reason` 写入 checkpoint。

这样可以降低存量 Goal 的恢复风险。

## 6. 受控 `GoalScript` API

### 6.1 脚本包格式

脚本作为工作流包资源的一部分，而不是任意 cwd 文件：

```text
.heagent/skills/<workflow-id>/
├── SKILL.md
├── workflow.md
├── templates/
└── scripts/
    └── workflow.py
```

`workflow.md` 声明脚本模式：

```yaml
entrypoint: goal
executor_mode: script
script: scripts/workflow.py
required_resources: prompt-template.md, gate-template.md, scripts/workflow.py
```

旧包没有 `executor_mode` 时默认使用现有声明式模式，保证兼容。

### 6.2 脚本入口

脚本只暴露一个受控入口：

```python
async def build_workflow(goal: GoalScript) -> None:
    await goal.step(
        name="inspect",
        role="bmad-agent-analyst",
        output="inspection.md",
        validation=["section: 现状", "section: 风险"],
    )

    if goal.output_exists("inspection.md"):
        await goal.step(
            name="design",
            role="bmad-agent-architect",
            inputs=["inspection.md"],
            checkpoint="approval_required",
        )
```

这是示意接口，正式实现前必须先固定 Pydantic/协议模型和安全边界。

### 6.3 允许的 API

`GoalScript` 只允许以下类别：

- `step(...)`：声明或请求执行一个受控步骤；
- `parallel(...)`：声明一组经过写集检查的并行步骤；
- `checkpoint(...)`：创建用户审批点；
- `input(...)`：读取受控输入；
- `output_exists(...)`：查询已登记产物；
- `read_artifact(...)`：读取当前 Goal 已登记的产物；
- `record_assumption(...)`：记录可审计假设；
- `require_decision(...)`：进入 `WAITING_USER`；
- `validate(...)`：调用受控验证器。

### 6.4 禁止的 API

脚本 API 不提供：

- `write_checkpoint()`；
- `set_state()`；
- `set_active_step()`；
- `write_current_pointer()`；
- `run_shell()`；
- `spawn_process()`；
- `open_network()`；
- `commit_git()`；
- 任意 `Path` 写入；
- 任意 `asyncio.create_subprocess_*()`；
- 直接访问 `AgentLoop.engine`、`PolicyEngine` 内部状态或 Ledger。

需要读写文件、执行命令或调用 Agent 时，必须通过现有受治理端口完成。

## 7. ScriptRuntime 设计

### 7.1 核心职责

`ScriptRuntime` 是脚本和 `WorkflowRunner` 之间的适配器，负责：

1. 加载并校验脚本入口。
2. 创建受控 `GoalScript` facade。
3. 把 `goal.step()` 转换为 `WorkflowStepResource` 和 callback。
4. 把脚本抛出的受控决策转换为 `WorkflowStepResult`。
5. 让所有状态改变通过 `WorkflowRunner.run_step()` 完成。
6. 捕获脚本异常并映射为 `FAILED`，不允许直接篡改状态。
7. 将脚本版本、资源 hash 和工作流 id 写入运行元数据。

### 7.2 不允许脚本自行控制恢复

脚本在一次恢复执行中可能从头重新运行，因此 API 必须幂等：

- 已完成的步骤由 Runner 判定并跳过；
- 脚本不能以 Python 局部变量作为唯一进度来源；
- 动态分支的结果必须写入受控输出或 decision record；
- 分支条件必须基于已持久化输入和产物；
- 未持久化的随机值、时间值和内存变量不得决定不可逆副作用。

### 7.3 有界执行

脚本包必须声明：

```yaml
script_max_steps: 100
script_max_depth: 8
script_timeout_seconds: 300
```

所有上限由宿主运行时强制执行，不能由脚本运行时修改。

脚本异常、超时或取消的默认语义：

```text
当前活动步骤保持不变
→ 状态 FAILED 或 WAITING_USER（按取消来源决定）
→ 写入 checkpoint
→ 不自动跳过步骤
```

## 8. 安全边界

受控脚本不是安全边界。

- Skill 包内容本身仍是不可信输入；
- Python 脚本如果在宿主解释器内运行，理论上拥有 Python 进程权限；
- `SafetyGuard`、`PolicyEngine`、内置 sandbox 仍只是 defense-in-depth；
- 脚本工作流必须在容器、VM 或 firejail 等 OS 级隔离中运行；
- 不可信 workflow 包不能在宿主环境直接启用脚本模式。

建议分两阶段：

### 阶段 A：可信本地脚本

- 只允许项目管理员安装的 workflow 包；
- 脚本资源必须经过现有 SkillPackage manifest/lock 完整性校验；
- 运行前执行包依赖和资源预检；
- 文档明确脚本不是安全边界。

### 阶段 B：隔离脚本执行

- 脚本在独立 worker 进程或 OS sandbox 中运行；
- 通过 JSONL/RPC 只暴露 `GoalScript` 协议；
- worker 无法直接接触 checkpoint 目录；
- 宿主负责验证每个操作请求并提交状态；
- 这是后续安全专项，不与第一阶段绑定交付。

## 9. 结构化执行证据

脚本化不应只增加灵活性，还应强化可验证交付。

每个实现 Story 建议新增：

```text
_he-output/goals/<goal-id>/step-07-implement-story/epic-e1/s-1/evidence.json
```

建议模型：

```json
{
  "schema_version": "1",
  "goal_id": "demo",
  "story_id": "S-1",
  "workflow_id": "he-goal",
  "workflow_revision": "sha256:...",
  "git_base": "abc123",
  "git_head": "def456",
  "changed_files": [
    "src/example.py",
    "tests/test_example.py"
  ],
  "commands": [
    {
      "command": "pytest tests/test_example.py -q",
      "exit_code": 0,
      "duration_ms": 1200,
      "stdout_digest": "sha256:..."
    }
  ],
  "quality_gates": {
    "tests": "passed",
    "ruff": "passed",
    "mypy": "passed"
  }
}
```

注意：这不是本方案第一阶段的强制实现项，但应在 `WorkflowStepResult` 和未来 gate DSL 中预留接口。

## 10. 声明式 gate 扩展

当前 gate 主要验证 Markdown 标题。后续建议兼容现有字符串规则，并新增结构化形式：

```yaml
validation:
  sections:
    - 实现摘要
    - 测试证据
    - 验证结论
  artifacts:
    required:
      - implementation.md
      - test-report.md
      - verify-report.md
  commands:
    - pytest tests/test_goal_application.py -q
  git:
    forbid_paths:
      - .env
      - .heagent/memory/**
```

执行规则：

- 结构化 gate 由宿主解析；
- 命令必须走现有工具治理链；
- 命令结果写入结构化证据；
- 报告文本不能伪造命令结果；
- gate 失败进入 `BLOCKED`，不推进活动步骤；
- 不允许 workflow 包自行降低宿主质量门禁。

## 11. 并行 Story 安全策略

`max_parallel_stories` 不能单独证明并行安全。

Step 06 生成的 Story 计划应增加：

```yaml
parallel_group: e1-ui
write_set:
  - src/heagent/web/**
  - tests/test_http_web_ui.py
depends_on:
  - S-2
```

当前 Runner 只把依赖完成作为执行前置：依赖未知或未完成即阻断。`write_set`、同 Epic 与独立
checkpoint 是可审计的规划信息，但不能证明宿主回调的实际写入隔离，因此即使声明不相交也固定逐条执行。

在提供可验证的隔离执行器（例如独立 worktree + 受控合并）之前，不做写集冲突推断、不持久化并行批次，
也不允许 `max_parallel_stories` 提升并行度。

## 12. CLI 与运维接口

建议按阶段增加以下命令：

```text
/goal doctor
```

检查：

- workflow 包和角色包是否存在；
- 模板和脚本资源是否完整；
- manifest/lock 是否通过；
- checkpoint 目录是否可写；
- 当前 provider 是否可用；
- 工作区是否存在危险状态。

```text
/goal changes
```

显示：

- 当前 Story 的 Git base/head；
- 变更文件；
- 未跟踪文件；
- 测试和质量门禁结果；
- 与 Story 写集不一致的变更。

```text
/goal verify
```

重新执行当前 Story 声明的结构化验证，不重新执行实现步骤。

```text
/goal report [--json]
```

输出 Goal 级摘要：

- 步骤与 Story 进度；
- 当前阻塞原因；
- 待用户决策；
- 假设和证据；
- 测试与质量门禁；
- Git 变更摘要。

不增加自动 commit 命令。提交仍需用户明确确认，并遵循项目现有提交纪律。

## 13. 分阶段实施计划

### Phase 1：状态机显式化，零行为变化

范围：

- 新增 `WorkflowEvent`；
- 新增 transition table 和非法转换错误；
- 将 `WorkflowRunner` 现有条件分支映射到统一 transition 函数；
- 增加状态转换黄金测试；
- 保持现有 checkpoint JSON 字段和外部命令行为不变。

验收：

- 现有 `/goal` 测试全部保持通过；
- 每个合法状态转换有正向测试；
- 每个非法转换至少有一个负向测试；
- 去掉 transition 校验时，新增测试精确变红；
- 旧 Goal 可以恢复。

### Phase 2：`/goal doctor` 与结构化执行证据

范围：

- 新增 `EvidenceRecord` Pydantic 模型；
- 为受治理命令记录退出码、耗时和摘要；
- 新增 `/goal doctor`；
- 新增 `/goal changes` 和 `/goal verify` 的只读/验证能力；
- 报告继续保留 Markdown，结构化证据作为并行产物。

验收：

- 报告不能伪造一个没有实际执行记录的成功命令；
- 失败命令能阻止 Story 通过 gate；
- 变更文件可与 Story 写集对比；
- 不读写凭证和内部状态的禁止路径。

### Phase 3：受控 ScriptRuntime

范围：

- 增加 `script_loader.py`、`script_api.py`、`script_runtime.py`；
- 支持 `executor_mode: script`；
- 脚本只能调用受控 `GoalScript` API；
- 脚本错误、超时、取消均经 Runner 产生状态和 checkpoint；
- 脚本资源接入 SkillPackage 完整性校验。

验收：

- 一个包含条件分支的脚本可恢复运行；
- 进程重启后不会依赖脚本局部变量恢复；
- 脚本不能直接写 checkpoint/current/workflow.json；
- 脚本中的 Agent/tool 调用仍进入既有治理链；
- 脚本超限会有界失败；
- 恶意或越界资源引用被拒绝。

### Phase 4：结构化 gate 与安全并行

范围：

- 扩展 validation DSL；
- 接入真实命令证据；
- Step 06 生成 Story `write_set` 和依赖；
- 无法证明安全时自动串行；
- 增加 `/goal report --json`。

验收：

- 缺少实际命令证据不能通过要求命令的 gate；
- 写集相交时不并行；
- 并行失败可独立恢复；
- JSON 报告与 checkpoint 状态一致。

## 14. 需要用户裁决的产品问题

以下问题在实现前必须明确：

1. `executor_mode: script` 是否只对本地可信 workflow 包开放？
2. 脚本模式默认是否关闭，必须显式启用？建议默认关闭。
3. Step 04、05、06 是否默认改为人工审批，而不是沿用当前 `auto`？建议至少 Step 06 默认审批。
4. 结构化命令 gate 是否允许 workflow 包声明命令，还是只允许项目级可信工作流声明？建议第一阶段只允许可信包。
5. 是否需要 Git worktree 隔离并行 Story？建议第一阶段先做写集检测，暂不引入 worktree。
6. 脚本运行是否允许联网？建议默认不允许，必须经过已有网络工具和策略。
7. 是否接受后续引入隔离 worker？如果目标是运行第三方脚本，这是必要方向。

## 15. 推荐的第一步实现边界

不要一开始同时实现脚本、复杂 DSL、并行 worktree 和网页控制台。

建议第一步只做：

```text
Phase 1：WorkflowEvent + transition table + 黄金测试
```

理由：

- 不改变用户工作流；
- 不改变 checkpoint 格式；
- 能先把当前隐含状态机显式化；
- 为脚本适配器提供稳定事件和转换接口；
- 能用现有测试做回归证明；
- 失败时容易回滚。

之后再落地 `EvidenceRecord`，最后才开放 `GoalScript`。

## 16. 结论

`WorkflowRunner` 不应被脚本替代。

推荐的长期形态是：

```text
脚本 / Markdown = 描述和扩展工作流
WorkflowRunner = 唯一状态机和恢复内核
CheckpointStore = 唯一状态持久化入口
ToolExecutor = 唯一工具执行治理入口
OS sandbox = 真正安全边界
```

这能同时获得：

- 声明式工作流的可读性；
- Python 脚本的表达力；
- 状态机的可恢复性；
- 现有工具治理的安全一致性；
- 后续结构化证据和并行控制的扩展空间。
