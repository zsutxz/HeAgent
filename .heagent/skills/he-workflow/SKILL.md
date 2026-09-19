---
canonical_id: he-workflow
name: he-workflow
description: /goal 声明式开发工作流包：8 步契约、步骤提示词模板与门禁模板
version: 1.0.0
---

# he-workflow（/goal 声明式开发工作流包）

本目录是 `/goal` 的工作流**包**，位于技能库 `.heagent/skills/` 下：`/goal` 命令族按 id 解析本包
并读取 `workflow.md` 执行。启动方式（`/goal new|next|run|status|pause|resume|auto|reset`）由 CLI
固定提供，不随包变化。

> **不要用 `skill_delete` / `skill_archive` 删除它。** 本包同时承载工作流契约与运行时模板；
> 被删除或归档后 `/goal` 会显性报「workflow.md is required」，但工作流定义需要从 git 还原。
>
> 本 frontmatter **有意不声明 `triggers` / `tags`，正文也没有 `## Pattern` 段**：这样技能自动
> 匹配永远命中不了它，工作流契约不会被整份塞进无关对话的 system prompt。请勿为了「能被搜索到」
> 补上这些字段。

包内资源：

- `workflow.md` —— 工作流契约：frontmatter 声明（`checkpoint_mode`、`open_question_mode`、
  `max_rounds`、`auto_schedule`、`open_question_default`、`open_question_block`）与 8 个步骤的
  顺序、`input`/`output`、`checkpoint`、`validation` 门禁、`role`、`story_loop`、`max_iterations`。
  **改工作流行为只改这个文件，不改代码。**
- `templates/prompt-template.md` —— **运行时依赖**：每个步骤的提示词模板。占位符：
  `{workflow_instructions}` `{goal}` `{goal_dir}` `{output_root}` `{step}` `{story_context}`
  `{role}` `{open_question_policy}` `{inputs}` `{gate}`。
- `templates/gate-template.md` —— **运行时依赖**：门禁提示块模板。占位符：
  `{sections}` `{acceptance}` `{rules}`。
- `templates/{EPIC,GOAL,STORY}.md` —— 参考模板：Goal/Epic/Story 的结构骨架，不被运行时代码读取。

## templates/ 下有两类文件，不要同等对待

| 文件 | 性质 | 删除后果 |
| --- | --- | --- |
| `prompt-template.md`、`gate-template.md` | **运行时依赖**，每次步骤执行都被读取 | 不报错，但**静默退回 CLI 内置兜底模板**（行为悄悄变化） |
| `EPIC.md`、`GOAL.md`、`STORY.md` | 文档参考 | 无影响（无代码读取） |

清理 `templates/` 前请先确认两个运行时模板不在删除范围内；
`src/heagent/cli_goal.py` 里的同名默认值是兜底，不是可替代的副本——
修改模板后如发现行为没变，先确认读到的确实是包内文件。

## 修改建议

- 改步骤顺序、门禁、策略参数：改 `workflow.md`（并同步 `docs/workflow_intro.md`）。
- 改提示词或门禁文案：改 `templates/` 下两个运行时模板；
  占位符拼写错误会把占位符原样留在提示词里，改完请用一个步骤实跑确认。
- 换一份完全不同的工作流：另建一个包（声明自己的 `canonical_id`），
  用 `GOAL_WORKFLOW_SKILL=<包 id>` 指过去，无需改代码。
