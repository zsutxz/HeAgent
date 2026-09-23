---
canonical_id: he-goal
name: he-goal
description: 多阶段大目标走 /goal 声明式 8 步工作流的触发与引导
tags: [goal, workflow]
created: 2026-09-19
triggers: [多阶段, 一个完整的项目, 做一个完整的项目, 从零做一个, 需求到交付, 端到端交付, 全流程开发, 目标驱动, /goal, goal 工作流, 立项]
negative_triggers: [code review, 代码评审, 技能评审, 重构, refactor]
priority: 3
---

# goal（目标驱动开发工作流）

## 边界

- 本技能只做引导：不代替用户执行 `/goal` 斜杠命令，也不复述工作流契约（契约在本包 `workflow.md` 里）。
- 单点改动、一次性问答、一次探查都不要启动工作流——判据见 Steps 第 1 条。
- 本节也是**刻意保留的额外章节**：正文若只剩 `## Pattern` / `## Steps` 两节，SkillStore 会在技能被
  自动注入时整体重渲染正文（丢掉上面 H1 的注解与 frontmatter 的 `canonical_id`）；保留本节即走
  「只改 frontmatter 计数、正文逐字节保留」的就地路径。代价：`pattern` / `steps` 要改就直接编辑本
  文件，`skill_update` 会拒绝（抛 `SkillRewriteError`，防止静默丢章节）。

## 运行时资源（勿删）

本包除引导正文外还承载 `/goal` 的**运行时契约**——`Settings.goal_workflow_skill` 默认解析到本包
（`canonical_id: he-goal`），CLI 读取下列资源执行工作流：

- `workflow.md` —— 工作流契约：8 步的顺序、`input`/`output`、`checkpoint`、`validation` 门禁、`role`、
  `story_loop`、`max_iterations` 与 frontmatter 策略声明（`max_rounds` / `auto_schedule` /
  `open_question_*`）。**改工作流行为只改这个文件，不改代码。**
- `templates/prompt-template.md`、`templates/gate-template.md` —— 步骤提示词与门禁模板（**硬性运行时依赖**，
  必需性由 `workflow.md` frontmatter 的 `required_resources` 声明，缺失即在加载阶段显性报错；CLI 不内置
  兜底；占位符契约见下方「模板契约」；清理时不要删）。

**模板契约（templates/）**——步骤提示词与门禁文案全部由本包携带，CLI 不内置任何模板兜底。两个模板的
必需性由 `workflow.md` frontmatter 的 `required_resources` 声明：列出的资源缺失（或只剩空白）时加载阶段
即显性报错；未声明而缺失的模板在渲染期显性报错，不以空提示词静默跑步骤。从清单里移除某项则该项退回可选。

- `templates/prompt-template.md` —— 每步发给执行 SubAgent 的提示词骨架；
- `templates/gate-template.md` —— 步骤门禁块骨架，渲染结果填入上者的 `{gate}`。

**可用占位符**（渲染为单遍替换：未知占位符原样保留，字段值里的 `{xxx}` 不会被二次展开）：

`prompt-template.md` —— `{workflow_instructions}`（`workflow.md` 正文）、`{goal}`（目标描述）、`{goal_dir}`、
`{output_root}`、`{step}`（步骤文件名）、`{story_context}`（story 循环上下文，非 story 步骤为空）、
`{role}`（该步骤角色包指令）、`{open_question_policy}`（悬而未决问题的处理策略文案）、`{inputs}`
（声明输入的渲染正文）、`{gate}`（门禁块，无门禁规则的步骤为空）。

`gate-template.md` —— `{sections}`（必含标题清单）、`{acceptance}`（Given/When/Then 要求）、
`{rules}`（该步骤 `validation:` 声明的逐字引用）。

改提示词或门禁文案只改这两个文件；新增字段需先在 CLI 侧扩展装配（字段清单即代码与包的契约面）。
本节是维护者文档，**刻意不放在 `workflow.md` 正文**——那里的内容会整体注入每步提示词。

> **不要用 `skill_delete` / `skill_archive` 删除或归档本包**——那会连同工作流契约一起移走，`/goal`
> 将显性报「workflow.md is required」，且契约需从 git 还原。Curator 的过期归档若命中本包，同样后果。
> `templates/EPIC.md` / `STORY.md` / `GOAL.md` 为结构参考模板，非运行时依赖。

## Pattern

多阶段大目标（从需求到交付的完整项目）走 `/goal` 声明式工作流；单点改动、一次性问答直接做，不要启动工作流。
命令：`/goal new <目标描述>` 启动 · `/goal next` 推进一步 · `/goal run` 连续推进 · `/goal status` 查看进度 ·
`/goal resume <回复>` 恢复并记录回答 · `/goal pause` 暂停 · `/goal auto [cron]` 定时推进 · `/goal reset` 清除当前指针。
工作流共 8 步：市场调研、发散构思、需求分析、产品范围、架构设计、故事细化、逐故事实现、系统集成测试。
持久产物落在 `_he-output/goals/<goal-id>/`；工作流契约（步骤、输入输出、门禁）的唯一权威是
`.heagent/skills/he-goal/workflow.md`，不要在本技能正文里复述或修改它。

## Steps

1. 判断是否真是多阶段目标：只改一处、只答一个问题、只做一次探查都不要启动工作流。
2. 提醒用户用 `/goal new <目标描述>` 启动；agent 不能代替用户执行斜杠命令，也不要伪造执行结果。
3. 用户问进度用 `/goal status`；要一次推多步用 `/goal run`；想无人值守用 `/goal auto`。
4. 步骤停在等用户输入时，提示 `/goal resume <回复>`；回答会写进需求文档的「用户补充」段。
5. 不要手改需求文档（新 goal 为 `brief.md`，存量 goal 沿用 `require.md` / `GOAL.md`）的「原始需求」段，也不要改 `02-epics.md` 里已冻结的验收标准。
6. 中断不会丢进度（checkpoint 在盘）：提示用户 `/goal next` 或 `/goal resume` 续跑即可。
