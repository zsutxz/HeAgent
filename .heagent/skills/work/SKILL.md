---
name: work
description: 目标驱动开发（声明式 8 步工作流）：/work 命令与多阶段大目标的触发与执行
triggers: [/work, work 工作流]
negative_triggers: [/goal_old, code review, 代码评审, 技能评审, 重构, refactor]
---

# work（目标驱动开发工作流）

## Pattern

多阶段大目标（从需求到交付的完整项目）走 `/work` 工作流；单点改动、一次性问答直接做，不要启动工作流。
本技能是 `/work` 命令的执行契约：命令把参数交给你，你按本技能与同包 `workflow.md` 自主驱动整个流程
（无 Python 状态机，状态全靠文件）。工作流共 8 步：市场调研、发散构思、需求分析、产品范围、架构设计、
故事细化、逐故事实现、系统集成测试。

与旧 `/goal_old` 的隔离：旧命令由 Python 状态机驱动，状态在 `_he-output/goals_old/`；本命令的状态在
`_he-output/works/`，两者互不兼容、互不迁移。不要把旧 goal 目录当本命令的状态读写，反之亦然。

**本包目录 `work/`（canonical id `he-work`）不要改回 `goal`/`goal_new`/`goal2`。** 包 id 取 meta.yaml 的
`canonical_id`（缺省回落目录名），须带 `he-`/`bmad-` 前缀，否则整包无法解析。目录若叫 `goal`，id 会
兜底成 `he-goal`，与旧包 `goal_old/` 同 id 冲突并遮蔽，`/goal_old` 失效。`SKILL.md` 的 `name` 只作
别名来源，不参与 id 校验。命令名与包目录名是两回事。

## 参数路由

按第一个参数分派（`$ARGUMENTS` 由命令注入；无参数 = 打印用法与当前状态）：

| 参数 | 动作 |
|---|---|
| `<目标描述>` 或 `new <描述>` | 新建 goal：建目录与状态文件，执行 Step 01 |
| `next` | 推进下一步（当前步未完成时先完成它） |
| `run` | 连续推进直到审批门、失败或完成 |
| `status` | 读 progress.md 报告进度（步骤状态、story 勾选、等待项） |
| `review [step]` | 只读审查当前 goal 的状态、文档和产物一致性；可限定步骤或 Story，不推进流程 |
| `pause` | 状态改 paused，报告恢复方式 |
| `resume <回复>` | 记录用户回答进决策日志，恢复 waiting_user 的步骤 |
| `approve` / `reject <原因>` / `amend <补充>` | 处理等待审批的步骤（语义见 workflow.md 审批门） |
| `decisions` | 回显 progress.md 决策日志 |
| `auto [cron]` / `auto off` | 用 cron 工具注册/注销自动推进 job（prompt 模板在 workflow.md） |
| `reset` | 清除 current 指针（goal 目录保留） |

## 执行总则

1. **先读契约**：任何动作前先读本包 `workflow.md`——它是流程唯一真源，本技能正文不复述流程细节。
2. **状态先读后写**：每次调用先读 `_he-output/works/current` 与 goal 目录的 `progress.md`，
   再做动作、再更新状态；绝不凭记忆续跑。
3. **每步全新子会话**：用 `task_delegate` 执行步骤，任务正文 = 该步契约全文 + 输入产物路径；子会话最终回复由你保存为该步产物文件。子会话默认视为只读执行环境，**不得假设拥有 `file_write`、`file_edit` 或目录创建能力，也不要要求子会话自行落盘**；它必须在最终回复中返回完整的步骤产物正文或实现/验证报告。
4. **宿主验收与落盘**：子会话返回后，由你按该步「验收核对」清单核对（需要跑命令就自己跑），再由主会话写入或更新项目文件，并把核对结果写进 `progress.md`；未过按该步处置，不得静默放行。
5. **审批门停下问**：声明 `approval` 的步骤完成后停下向用户提问，答复写入决策日志后再继续。
6. **只读文档审查**：`review [step]` 只读取 `current`、`progress.md` 和相关产物，检查状态、章节、依赖、审批门、冻结契约和跨产物一致性；不委派实现型子会话，不修改任何项目文件，不改变步骤状态、审批状态或 Story 勾选。每条发现必须包含位置、证据、严重度和建议处置；`review` 不等于代码评审。
7. **显性失败**：状态文件缺失/损坏、步骤反复失败时如实报告并停，不猜测、不伪造进度。

## Steps

1. 判断是否真是多阶段目标：只改一处、只答一个问题、只做一次探查都不要启动工作流。
2. 用户问进度用 `/work status`；要审查文档和状态用 `/work review [step]`；要一次推多步用 `/work run`；想无人值守用 `/work auto`。
3. 步骤停在等用户输入时，提示 `/work resume <回复>`；回答会记入决策日志并写入需求文档的用户补充段。
4. 不要手改 `brief.md` 的「原始需求」段，也不要改 `epics.md` 里已冻结的验收标准。
5. 中断不丢进度（progress.md 在盘）：提示 `/work next` 或 `/work resume` 续跑即可。
