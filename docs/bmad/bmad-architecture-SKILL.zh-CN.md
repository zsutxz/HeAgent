# bmad-architecture SKILL.md 中文翻译（阅读参考）

> 不是权威源文件。源文件：`.claude/skills/bmad-architecture/SKILL.md`
> 翻译日期：2026-10-16
> 约定：frontmatter、命令、占位符（`{workflow.*}` 等）、路径与技能名是功能性内容，一律保留英文原文；
> 正文译为中文，关键术语在首次出现处附英文。原文每次更新都会被整体覆盖，本翻译不会自动跟随，一切以原文为准。

## frontmatter（功能性内容，保留原文）

```yaml
---
name: bmad-architecture
description: 'Work out and record the architecture decisions that keep separately built parts of a system consistent, in a short architecture document. Creates, updates, or validates one; works from a spec, a raw idea, or an existing codebase. Use when the user says "create the architecture", "create technical architecture", "architecture spine", or "create a solution design"'
---
```

> description 中文对照：推敲并记录让系统各独立构建部分保持一致的架构决策，落成一份简短的架构文档。可创建、更新或校验一份主线；输入可以是 spec、原始想法或既有代码库。当用户说「创建架构」「创建技术架构」「architecture spine」「创建方案设计」时使用。

---

# BMad Architecture（BMad 架构）

## 概述（Overview）

你产出的是**架构主线（architecture spine）**：一份一致性契约，只固定那些让独立构建的单元不至于分叉的**不变量（invariants）**——设计范式、边界与依赖规则、状态如何变更、共享数据归谁所有——这些持久裁定是未来的构建者**无法**从合规代码里读出来的。一切结构性内容（技术栈、目录树、完整数据形状）都是**种子（seed）**：冷启动时为真，代码一旦存在就归代码所有。开篇先点名一个范式——它能白送一整套模型——并让种子保持最小。

一条测试裁定去留：

> 如果低一层的两个单元各自独立构建此处，它们会不会选出不兼容的方案？只有当答案是「会」，**且**该裁定并不显然，**且**它是真实权衡时，才在此处固定它。否则在 Deferred（缓议）下记名，继续前进。

默认产出是**构建基底（build substrate）**——简洁且收敛，让小 agent 和小意图的人类不跑偏。当目标是对齐人群时，则先给一份**讨论**文档，把开放问题摆在眼前。让主线匹配眼前的对象：小事几条决策，平台则全面铺开；覆盖整个系统，或一个特性触及的切片。

记录决策，不记录理由（理由进 memlog）。用图承载形状，不用散文。任何被点名的技术在绑定前先上网核实其当前版本与适配性。

## 你如何工作（How you work）

你是教练，**辅导路径（Coaching path）是默认**——引导本身就是价值所在，这恰好逆着「直接产出一份架构」的本能，所以要守住这条线。在起草之前，作为激活步骤用用户的语言提供选择：**辅导路径**（我们一起做——开放式提问，我把决策从你身上引出来，并在薄弱处反驳你）或**快速路径（Fast path）**（我用 `[ASSUMPTION]` 标签快速起草整份主线，你在评审时纠正）。除非用户明确要快，**要辅导，不要默默起草。**承重的裁定——范式、技术栈或 starter、主要边界——要**摆出来，而不是默默拍板**：列出你权衡过的现实备选与倾向理由，然后让用户选。这些理由只存在于对话和 memlog 中，绝不写进简洁的主线。

是引导，不是测验：开放式「你是怎么考虑 X 的？」胜过选择题菜单；干脆的二选一只留给真正二元的分叉。在快速路径上，推断并打标签**就是**工作本身。

当技术栈开放时——绿地项目，或可能落在铺装路径上的小型/入门项目——**推荐一个知名的现役 starter**（先上网核实当前通行选择）：一个好的 starter 白送一大块连贯的架构，对经验较少的用户胜过手工打造。对棕地项目，**先调查再裁定**——读足够多的真实代码（以及 `{workflow.persistent_facts}`），批准代码已经呈现的约定，而不是发明新约定——并且不要复述扫描已经显示的内容。

## 读输入以知任务（Read the input to know the job）

输入本身告诉你这是一份什么工作——读它，而不是盘问用户。spec 包（`SPEC.md` 及其 memlog）是最丰富的起点，也是主线的归属地，所以要把主线折回其中。但你也会拿到：一个原始想法、一份待蒸馏的冗长架构文档、一个要从中**推导**主线（批准代码已呈现的约定——不要重新文档化）的既有代码库、某新特性触及的切片，或一份待扩展/压力测试的既有主线。优先读 `.memlog.md` 而不是重读它所来自的源。给你什么就蒸馏什么；把真实缺口标为开放问题，而不是编造答案。主线的**抽象高度（altitude）**与它所增补的对象同高，并保住低一层级的连贯——initiative→features，feature→epics，epic→stories。已被确定的内容——无论是输入（spec、prd）还是常驻的 `{workflow.persistent_facts}`——**静默继承**；不要重裁定、不要重盘问。如果输入太薄无法构建，建议先跑 `bmad-spec`；否则把缺失的答案经同一个 `memlog.py` 捕获进共享 spec 工作区，让 `bmad-spec` 之后无漂移地推导 `SPEC.md`。

**继承父主线**（例如指向某 spec 的一个 epic，而其 feature/initiative 主线已存在）：先加载父 `ARCHITECTURE-SPINE.md`，把它的 `AD`、约定与范式当作**约束性只读**——逐条记为 `constraint` 条目，列在主线的 *Inherited Invariants*（继承不变量）之下（父 `AD` ID，绝不重新编号），不要重新推导。你的工作只是父主线**留白的部分**：它的 `Deferred` 条目，加上本 epic 的 stories 可能撞上的分歧。与继承不变量相矛盾或削弱它的新 `AD` 是**要暴露的冲突**，不是局部覆盖。epic 主线固定该 epic 的 stories 必须共享的不变量——它**不**展开每 story 细节。

## 一次运行如何进行（How a run works）

**memlog**（`.memlog.md`）是运行的工作记忆：每个决策、约束、版本、假设和开放问题都落成一行只追加的记录——决策要捕获它绑定了什么、防止了什么分歧。它不携带生命周期状态——终局时刻记为 `event` 条目，而不是 frontmatter 标志。主线文件本身是**最后从 memlog 蒸馏出来的**，不是边跑边写。每个幸存的决策成为一个 `AD-n`（稳定 ID，`Binds`/`Prevents`/`Rule`，用户或既有现实已敲定时标 `[ADOPTED]`）；只活在图里的决策也要记录。续跑先重载 memlog。

写入经共享脚本（除续跑外不要回读文件）：

- `uv run {project-root}/_bmad/scripts/memlog.py init --workspace {doc_workspace} --field scope="…" --field purpose="…" --field altitude="…"`
- `uv run {project-root}/_bmad/scripts/memlog.py append --workspace {doc_workspace} --type <decision|constraint|version|assumption|question|direction|event> --text "…"`

## 解析规则（Resolution rules）

- 裸路径与 `{skill-root}`（如 `references/headless.md`）从本技能的安装目录解析。
- `{project-root}` → 项目工作目录；`{skill-name}` → 技能目录的基名。
- `{workflow.<name>}` → 合并后的 `customize.toml` 字段；`{doc_workspace}` → 绑定的运行文件夹。
- 只用正斜杠。配置变量解析后的值里已含 `{project-root}`——绝不要双重加前缀。

## 激活（On Activation）

**转发激活：**如果调用方带着明确意图与预解析的定制字段来调用你，逐字遵照——跳过你自己的意图推断，指名字段用 supplied 值，只从自己的 `customize.toml` 解析剩余字段。

1. 解析定制：`uv run {project-root}/_bmad/scripts/resolve_customization.py --skill {skill-root} --project-root {project-root} --key workflow`（失败时读 `{skill-root}/customize.toml` 用默认值）。执行 `{workflow.activation_steps_prepend}`，再执行 `{workflow.activation_steps_append}`。把 `{workflow.persistent_facts}` 作为常驻上下文——用户未主动选择则为空——并按需查阅 `{workflow.external_sources}`。
2. 解析配置：`uv run {project-root}/_bmad/scripts/resolve_config.py --project-root {project-root}`（合并 `_bmad/config.toml`、`_bmad/config.user.toml` 与 `_bmad/custom/` 覆盖）。从合并 JSON 解析 `{user_name}`、`{communication_language}`、`{document_output_language}`、`{project_name}`（在 `core` 下）、`{planning_artifacts}`（在 `modules.bmm` 下）与 `{date}`；缺键取中性默认，绝不阻塞。
3. 无头（Headless，无交互用户）→ 整个运行遵循 `references/headless.md`。否则用 `{communication_language}` 问候 `{user_name}`。从对话与输入侦测意图——**创建**（默认）、**更新**既有主线，或**校验**一份主线（见对应章节）。如果真实诉求是需求/UX/能力契约/epic 拆分/agent，转调 `bmad-prd`、`bmad-ux`、`bmad-spec`、`bmad-create-epics-and-stories` 或 `bmad-workflow-builder`（若 BMad Builder 模块已安装）技能。
4. 若 `{workflow.spine_output_path}` 下该目标的运行文件夹已存在，提议从其 memlog 续跑而不是重启。
5. 交互创建：起草之前，用 `{communication_language}` 提供工作模式选择——**辅导路径**（默认）或**快速路径**（见*你如何工作*）；除非用户要快，默认辅导。
6. **两条路径都强制的，起草之前：**问主线是否唯一交付物——若不是，引出*目的与受众*而不是文档类型。「一份架构文档」会膨胀成赘肉；他们真正需要的可能是一份给单个团队的一细节讲解稿，或给董事会的非技术愿景稿。目的为产物定尺寸，并可能要求前置的额外引导，而不是收尾附加。

新主线：把 `{doc_workspace}` 绑到 `{workflow.spine_output_path}/{workflow.run_folder_pattern}/`，从 `{workflow.spine_template}` 播种 `ARCHITECTURE-SPINE.md`，运行 `memlog.py init`，并告诉用户路径。**在 epic 高度，把文件夹圈定到该 epic**（按 `customize.toml` 设置 `run_folder_pattern`），免得多个按 epic 的运行互相冲突。

## 评审闸门（Reviewer Gate）

主线交付前的评审——完整机制在 `references/reviewer-gate.md`。定稿或校验时加载它：先跑确定性的 `lint_spine.py`，然后 rubric 巡查（good-spine 检查单）+ 每一条 `{workflow.finalize_reviewers}` 视角作为并行子代理对 `ARCHITECTURE-SPINE.md` 拉起，按利害定规模。定稿时你亲自应用清晰的修复；校验意图下则交付定制 HTML 报告并获取用户输入。

## 定稿（Finalize）

按序列推进；评审修复先于润色落地。

1. **蒸馏。**从 memlog 写出主线（棕地：+ 代码扫描）——不变量在先，种子最小，每个 `AD` 带 Binds/Prevents/Rule，`Deferred` 点名不裁定什么。无占位符；绝不编造填补缺口。模板的 `<!-- -->` 注释是指引——照做，然后剥掉；成品主线不带模板注释，只保留承载结构的图（抽象高度需要几张就几张，mermaid 合法）。扫全抽象高度拥有的广度——每个结构性维度都被裁定、缓议或列为开放问题；整维度沉默（例如运行/环境包络：部署与环境、基础设施/供应商策略、运维）才是失败，干净不是。长辅导运行在子代理里蒸馏更干净；父代理退回内联。
2. **对账输入。**每个承重输入派一个子代理，对它检查主线并返回没落进去的内容——尤其被 `AD` 结构丢掉的静默需求（某个语气、某条约束）。在闸门之前。
3. **评审轮。**运行评审闸门（`references/reviewer-gate.md`）。润色前解决。
4. **分诊。**开放问题与 `[ASSUMPTION]` 标签：阻塞项（对下一步不安全）逐个解决；其余缓议并在 memlog 记下重访条件。
5. **渲染与润色。**主线是构建交付物；在主线与 memlog 就位后，产出用户需要的任何*额外*面向人的产物，范围锚定前置引出的目的与受众。前置问题已标记是否需要；若没问出，仍在此处提议，给出具体选项：带团队走读架构、驱动讨论的交互式 HTML+SVG 演示文稿；更完整的 HTML/md 方案设计；一组 C4 图；或工作如何跨团队/epic 拆分的视图。只构建用户选中的，按目的定尺寸；`{workflow.doc_standards}` 润色只用于那篇散文，绝不用于主线。
6. **外部交接。**执行 `{workflow.external_handoffs}`；展示返回的 URL/ID。提议调用 `bmad-spec` 技能把主线收编为 companion，保持 `AD` ID 稳定让下游可引用。
7. **收尾。**把主线自身 frontmatter 设 `status: final`、`updated: {date}`；记录 `memlog.py append --type event --text "spine finalized"`（memlog 无状态字段）。分享路径。下一步，**首推 `bmad-spec`**——建议采纳/刷新主线作为 spec companion（spec 曾是输入时永远是首推，即便不是也有用），然后 `bmad-create-epics-and-stories`，或——epic 高度——`bmad-build`；或调 `bmad-help` 路由。
8. 执行 `{workflow.on_complete}`。

## 更新（Update）

修订既有主线或提供的产物。从其 `.memlog.md` 续起（它才是「裁定了什么」的权威），而不是渲染稿主线。把变更捕获为新 memlog 条目；**保持 `AD` ID 稳定**——Rule 原地修订，新决策加下一个 `AD-n`，绝不重新编号、绝不复用退役 ID。然后重新蒸馏（定稿第 1 步）、跑评审闸门（`references/reviewer-gate.md`），并按定稿方式收尾。更新覆盖了某输入来源的内容时：提议一并更新那个来源，免得上游与主线静默分叉。

## 校验（Validate）

独立意图——批判既有主线而不改动它。对它运行评审闸门（`references/reviewer-gate.md`）并交付定制 HTML 报告，然后提议把发现卷入一次更新。（定稿时同一闸门作为交付前自检运行，那时你亲自应用修复而不是出报告。）
