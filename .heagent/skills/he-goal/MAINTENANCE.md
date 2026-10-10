# he-goal 维护者文档

本文件是维护者文档：运行时不解析、不注入 LLM 上下文。`SKILL.md` 正文只含 Pattern/Steps（可被
`skill_update` 无损重渲染）；本文件不在其渲染范围内，契约说明改动请直接编辑本文件。

## 运行时资源（勿删）

本包除引导正文外还承载 `/goal` 的**运行时契约**——`Settings.goal_workflow_skill` 默认解析到本包
（本包 `meta.yaml` 声明 `canonical_id: he-goal`），CLI 读取下列资源执行工作流：

- `workflow.md` —— 工作流契约：8 步的顺序、`input`/`output`、`checkpoint`、`validation` 门禁、`role`、
  `story_loop`、`max_iterations` 与 frontmatter 策略声明（`max_rounds` / `auto_schedule` /
  `open_question_*`）。**改工作流行为只改这个文件，不改代码。**
- `templates/prompt.md`（步骤提示词骨架）与 `templates/gate.md`（门禁块骨架，渲染结果填入上者的
  `{gate}`）—— 两个文件的**文件名由 `workflow.md` frontmatter 声明**（`prompt_template:` /
  `gate_template:`，声明驱动，代码不携带固定文件名）。声明即承诺：指名文件缺失（或只剩空白）在
  加载阶段显性报错；不声明则该模板视为不携带，渲染期用到时显性报错，不以空提示词静默跑步骤。
  CLI 不内置模板兜底。
- `templates/EPIC.md` / `STORY.md` / `GOAL.md` —— 结构参考模板，非运行时依赖。

**模板占位符**（渲染为单遍替换：未知占位符原样保留，字段值里的 `{xxx}` 不会被二次展开）：

- `templates/prompt.md` —— `{workflow_instructions}`（`workflow.md` 正文）、`{goal}`（目标描述）、
  `{goal_dir}`、`{output_root}`、`{step}`（步骤文件名）、`{story_context}`（story 循环上下文，非
  story 步骤为空）、`{role}`（该步骤角色包指令）、`{open_question_policy}`（悬而未决问题的处理
  策略文案）、`{inputs}`（声明输入的渲染正文）、`{gate}`（门禁块，无门禁规则的步骤为空）。
- `templates/gate.md` —— `{sections}`（必含标题清单）、`{acceptance}`（Given/When/Then 要求）、
  `{rules}`（该步骤 `validation:` 声明的逐字引用）。

改提示词或门禁文案只改这两个文件；新增字段需先在 CLI 侧扩展装配（字段清单即代码与包的契约面）。

## 保护约束

- **不要用 `skill_delete` / `skill_archive` 删除或归档本包**——那会连同工作流契约一起移走，`/goal`
  将显性报「workflow.md is required」，且契约需从 git 还原。Curator 的过期归档若命中本包，同样后果。
- `meta.yaml` 的运行时使用计数由自动注入维护；`workflow.md` frontmatter 的 `revision` 是声明
  revision，改包契约必须同步推进它。
