# /loop 开发工作流（流程契约）

本文件是 `/loop` 工作流的**完整可执行契约**与唯一真源。执行者是主会话 agent（下称**宿主**）：
宿主按本契约逐步驱动流程，每个步骤用一个**全新**的子会话（`task_delegate`）执行；没有 Python
状态机，全部状态由宿主按本契约落盘维护。任何步骤都不得跳过。

**BMAD v7 是规划与实现的唯一正本。** 本工作流不再自建 epic/story 清单：规划产物（initiative 信封、
epic 文件、`tickets.toml`）与 story 状态（plan frontmatter）全部住 **active initiative 的票树**，
由 `_bmad/method/scripts/tickets.py` 读写。v6 的 `epics.md` 与 `_bmad-output/sprint-status.yaml`
**已废弃**（前者随 v6 归档在 `initiative-*/` 根，2026-11-20 自 archive-v6/ 上移），任何步骤都不得再写、也不得再以它们为
story 清单。

本工作流产出的**持久性非代码产物**：规划文档（PRD、架构 spine、epic 文件、`tickets.toml`、plan）
写入 active initiative；循环自身的编排产物（需求原文、进度、各步报告）写入 `_he-output/works/`
之下。源代码仍留在仓库既有位置。全部正文与产物使用中文。

## 票树接口（BMAD v7）

工具统一前缀：`python {project-root}/_bmad/method/scripts/tickets.py --project-root {project-root}`
（脚本需要 PyYAML；本机没有 `uv`，用装了 PyYAML 的解释器直接跑，例如项目 venv）。未设 `active_initiative` 时必须显式给
`<dir>`（`_bmad-output/initiative-<slug>`），否则脚本报 `no active initiative`。

- **布局**：`{output_folder}/initiative-<slug>/` 是 initiative 根，`output_folder` 默认
  `{project-root}/_bmad-output`；`active_initiative` 读 `_bmad/custom/config.user.toml` 的 `[core]`
  （该文件是个人配置、gitignore、不入库）。
  - `initiative-<slug>/initiative-<slug>.md`——信封：Requirements（`R<n>` 稳定 id）、Constraints、
    `Done when`、Boundaries、`sources:`（PRD 等）、`companions:`；
  - `initiative-<slug>/tickets/tickets.toml`——`[[epic]]` 表，**表顺序即构建顺序**；
  - `initiative-<slug>/tickets/epic-<slug>/epic-<slug>.md`——epic 文件；薄 epic 带
    `refined: false`（只同意边界、尚未细化），细化后写 Requirements 并置 `refined: true`；
  - `initiative-<slug>/tickets/epic-<slug>/tickets/tickets.toml`——该 epic 的 `[[entry]]`
    （`type` = story / spike / bug），同样表顺序即构建顺序；
  - plan——`tickets.py find <ref>` 返回的绝对路径 `plan`（与 `tickets.toml` 同级，如
    `story-62.1-...-plan.md`），**plan frontmatter 的 `status` 是 story 状态的唯一真源**；
  - epic 收口——回顾报告 `epic-<slug>-retrospective.md` 落 epic 文件夹；跨 story 延期项住
    `initiative-<slug>/deferred-work.md`（`source_plan` / `summary` / `evidence`）。
- **命令**：`status <dir>`（`tickets` 行：`ref` / `status` / `state` / `risk` / `hitl` / `after`，
  顶层 `counts` / `epics` / `unpinned_after` / `undeclared_after` / `order_conflict`）、
  `next <dir>`（`ready_to_refine` / `ready_to_start` / `in_progress` / `blocked` 分组，行上可能带
  `plan_checkpoint` / `done_checkpoint` / `drift`，`blocked` 行带 `waiting_on` / `blocked_reason` /
  `unknown`）、`find [<dir>] <ref>`（单票：`story_file` / `epic_file` / `plan` / `description` /
  `verify`）、`pull <dir> <id>`（给 entry 拉出 leaf 文件，只在评审/细化/发布时需要；与 `find` 不同，
  `dir` **必填、不回落** active initiative——`pull 62.1` 会缺参报错）、
  `mark [<dir>] <ref> <status>`（把状态写进 plan，repo store 唯一合法写法）、`move`（换文件夹，
  id 不复用）。
- **状态阶梯**：`draft → ready-for-dev → in-progress → in-review → built → done`，另有 `blocked` /
  `dropped`。**build 只到 `built`；`done` 只能由人或编排器写。**
- **角色技能根**：`.heagent/skills/<role>/SKILL.md`（HeAgent 适配版：v7 角色方法已预渲染进包内，
  无需再跑渲染器）。`.claude/skills/<role>/` 是 v7 官方安装源，且
  `bmad-build` / `bmad-build-auto` / `bmad-agent-po` / `bmad-qa-generate-e2e-tests` /
  `bmad-code-review` / `bmad-retrospective` 的 SKILL.md 只是「跑 `uv run render_skill.py`」的启动器
  ——本机无 `uv`，子会话**不可**直接用。仅当 `.heagent/skills/` 缺该角色时，才回退读
  `.claude/skills/<role>/` 的 `workflow.md` 与 `step-*.md` 原文。
  **同步命令**：`python scripts/sync_bmad_role_skills.py`（`.claude/skills` 更新后重跑一次即可；
  `--check` 只自检不写盘）。
- **清单真源**：一条 epic 的 story 清单只有它的 `tickets/tickets.toml`（表序即执行序）；plan 与
  leaf 文件是逐条产物，不是清单。
- **三条禁令**：状态一律经 `mark` 写，不手改 plan frontmatter；已批准的 entry 与 epic
  Requirements 不手改（要改走重切）；`id` / `ref` / plan 路径一律取脚本输出，不自行发明。

## 状态与目录约定

- **根目录**：`_he-output/works/`（与旧 `/goal` 的 `_he-output/goals/` 完全隔离，互不读写）。
- **current 指针**：`_he-output/works/current`，内容是当前 goal 的目录名；`reset` 删除它，
  goal 目录保留。无活动 goal 时指针不存在。
- **goal 目录**：`_he-output/works/<goal-id>/`（`<goal-id>` 为英文 slug，冲突时追加 `-a`/`-b`…）：
  - `brief.md`——需求文档：`## 原始需求（Original Request）` 段是用户原话，**逐字冻结**；
    `## 用户补充（User Responses）` 段记录后续回答；模板见本包 `templates/GOAL.md`；
  - `progress.md`——本工作流的编排状态唯一真源（格式见下）；**它不记 story 状态**，story 状态只
    从 `tickets.py status` 读；
  - `step-NN-<名称>/report.md`——各步报告；本工作流不再产生 `epics.md`。
- **goal ↔ initiative 绑定**：goal 目录的 `progress.md` 记 `- Initiative: initiative-<slug>` 一行，
  Step 04 首次写定，其后所有步骤按它定位票树；`Step 01`～`03` 只读，不建票树。
- **progress.md 骨架**（宿主创建并持续维护）：

  ```markdown
  # goal 进度：<goal-id>

  - 目标：<标题>
  - Initiative：initiative-<slug>（Step 04 写定）
  - 状态：<running | waiting_user | paused | blocked | done>
  - 当前步骤：<step-NN 或 none>

  ## 步骤状态

  | 步骤 | 名称 | 状态 | 产物 |
  |---|---|---|---|
  | 01 | market-research | pending | |

  ## Epic 与 entry（Step 06 后维护，状态抄自 `tickets.py status`）
  （形如 `- E62 epic-代码架构重构：7 entry，6 planned / 1 built`；逐条明细不抄，读脚本）

  ## 决策日志（追加式，只增不改）
  - <日期时间> <动作> <步骤/ref>：<内容>

  ## 开放问题
  - <问题 → 处置>
  ```

## 宿主执行循环

1. 读 `_he-output/works/current` 与 goal 目录的 `progress.md`，确定状态与下一步；已绑定 initiative
   时同时读 `tickets.py status <initiative>` 与 `next <initiative>`（story 事实只认脚本）。
2. 取**最小序号的未完成步骤**；Step 07 内取 `next` 的 `ready_to_start` 首行（尊重表序与 `after`）。
   把该步契约全文 + 输入产物路径（含 `find <ref>` 给出的 entry / epic 文件 / plan 路径）作为任务
   正文，用 `task_delegate` 开全新子会话执行；子会话默认视为只读执行环境，任务不得以其拥有
   `file_write`、`file_edit` 或目录创建能力为前提。
3. 子会话返回后，宿主按该步**验收核对**清单核对产出（`command:` 类核对由宿主亲自执行，含
   `tickets.py` 与 plan 的 Verification），再由宿主把子会话最终回复保存为该步报告；不得要求子会话
   自行落盘。核对结果写入 progress.md。
4. **更新 progress.md 再继续或停下**——每完成一步（或一步失败/等待）都必须先落盘再进行下一步。
5. 停止条件：命中审批门 / checkpoint / 步骤失败 / waiting_user / 全部步骤完成（状态置 done）。

## 审批门与 checkpoint（v7 口径）

- **规划审批**：Step 04（epic 拆分）与 Step 06（epic 细化 + story 拆分）产出核对通过后，宿主停下
  向用户展示产出并请求确认；`approve` / `reject <原因>` / `amend <补充>` 三种处置。用户的一「yes」
  同时是**提交票树**的授权（仓库纪律：中文 Conventional Commit，先呈报提交信息与文件清单再执行）。
- **条目级 checkpoint**：entry 上的 `hitl`（需要人操作）、`plan_checkpoint`（计划先由人看）、
  `done_checkpoint`（`built` 后等人放行）由 Step 07 逐条执行，未置位时不要额外加门。
- **最终放行**：Step 08 报告核对通过后停下；`approve` 才把 entry 逐条 `mark <ref> done`、把 goal
  状态置 `done`，并在决策日志记答复原文。`done` 是人的决定，自动 job 永远不写。
- **串行纪律**：entry 严格逐条串行执行（本工作流不提供并行授权与写集审计）；`after` 只用于核对
  顺序合法：任何 entry 的依赖必须由构建顺序更靠前的 entry 或 epic 交付。
- **显性失败**：状态文件缺失或损坏、脚本非零退出、同一子会话任务连续两次失败时，宿主如实报告并停
  （状态置 blocked），不猜测、不伪造进度、不静默跳步。

## 只读文档审查

`review [step]` 是独立于 8 步推进循环的只读动作，不是新增工作流步骤。无参数时审查当前 goal 的全部
状态与产物；带参数时可限定 `step-01` 至 `step-08`、某个 epic/`ref` 或具体 Story。

审查范围至少包括：

- `current` 指针、`progress.md` 状态与产物存在性是否一致；`- Initiative:` 行指向的票树是否存在；
- 各步骤必需章节、审批门和输入/输出引用是否完整；
- `tickets.py status` / `next` 的 `unpinned_after` / `undeclared_after` / `order_conflict` / `drift`
  与任何 `problems` 是否为空，plan `status` 与 progress 的记载是否一致；
- epic `refined` 标记、`covers` 指向的 `R<n>` 是否真实存在、entry 的 `after` 是否都由更早的工作交付；
- 是否存在越过审批门、修改冻结的 epic Requirements 或 plan `<frozen-after-approval>` 段、悬空引用
  或跨产物矛盾；是否残留 `unknown` 或 `blocked` 却当作可构建；
- 报告中的测试、性能、硬件和验证结论是否有明确证据，是否把计划命令写成已执行结果。

审查纪律：

- 只读 `current`、`progress.md`、票树与相关产物；必要的检查命令由宿主执行。
- 不委派实现型子会话。
- 不修改代码、文档、状态、审批记录、entry 勾选或任何项目文件。
- 不推进步骤，也不改变当前状态。
- 每条发现必须包含：位置、证据、严重度（Critical/High/Medium/Low）和建议处置。
- `review` 是 goal 文档/状态审查，不等于代码评审；代码评审走 `bmad-code-review`。

## cron 自动推进

`auto [cron]` 用 cron 工具注册一个按表达式触发的 job，其 prompt 固定为以下模板（`auto off` 注销
prompt 以「推进 goal」开头的 job）：

> 推进 goal：读 `_he-output/works/current` 指向 goal 的 progress.md、brief.md 与 `- Initiative:` 行，
> 跑 `tickets.py next <initiative>`，用 `bmad-build-auto` 构建 `ready_to_start` 顺序里的第一条 entry。
> 遇到 `hitl` / `plan_checkpoint` / `done_checkpoint` / `blocked` / `unknown` 时不要推进，原样报告
> 等待项；任何情况下都不要把 entry `mark done`。

无人值守的边界：`bmad-build-auto` 不提问，任何不明确一律在 plan 里记 `blocked` + 原因后停；它需要
subagents，且需要干净工作树。

## 全局标准

**就绪标准（Ready for Development）**——一条 entry 同时满足以下七条才算就绪：

- **可执行**：plan 里每个任务都有明确文件路径与具体动作；
- **有序**：任务按依赖排序，entry 排在表序与 `after` 允许的位置；
- **可测**：`verify` 与验收标准全部可验证（行为类用 Given/When/Then，非行为类用同等可判定的形式），
  实现者能自己证明达成而不必指代码；
- **完整**：没有占位符、TBD 或悬空引用，没有未 `pull` 就被引用的 leaf 文件；
- **充分**：没有未解决的已知需求、验收、依赖或实现缺口；
- **自洽**：没有未消解的歧义或内部矛盾；所有会影响产品范围、架构、数据格式、验收标准或实现路线的
  方案均已完成选择并记录（`Decision:` 行进 epic 的 Notes）；
- **已决策**：不存在未裁决的 `unknown`、`Ask First`、竞争方案或需要开发阶段再向用户询问的核心选型；
  这些事项必须在 Step 06 审批前关闭，否则 `next` 会把该 entry 列在 `blocked`。

**范围标准（Scope Standard）**——一条 entry 只面向**单一用户可见目标**。多目标指 ≥2 个**顶层
独立可交付物**：各自可被独立评审、测试、合并且互不破坏；不要把同一目标内部的跨层实现细节拆开。
规模建议 900–1600 token 量级：低于 900 易歧义，高于 1600 易让实现会话上下文腐化。**两条都不是
硬闸门**，是需要用户裁决的建议。

**冻结契约（frozen-after-approval）**——Step 06 审批前必须完成所有影响产品范围、架构、接口、
数据格式、依赖、资源边界、验收标准或实现路线的方案决策，并写入 epic 的 Requirements/Notes 与 plan
的 `<frozen-after-approval>` 段。用户批准后，epic Requirements、`Done when`、已选方案与 plan 的
Intent/Boundaries **冻结**：只有人能改，agent 在后续任何步骤中都不得改写、替换或重新选择它们去迁就
实现。实现或评审中发现规格本身有缺陷，必须停止受影响 entry（`mark <ref> blocked --blocked <原因>`），
报告影响并回到相应规划或审批环节；不得在 Step 07 临时向用户征询核心方案，也不得绕过审批直接改规格。
仅不影响外部契约的内部实现细节可由实现 Agent 自主决定。

## 步骤纪律

Step 01 与 Step 02 是**只读**步骤（市场调研与发散构思），不得修改项目实现产物，也不得建票树；
Step 01 的唯一写操作是把初步分析结论写回 `brief.md`。Step 04 是**规划步骤的入口**：产出 PRD 与
epic 拆分（信封 + `[[epic]]` + 薄 epic 文件），只规划不实现。Step 06 是**规划步骤**：细化 epic、
把范围拆成 entry、排定构建顺序、关闭所有核心方案决策；它只规划，不实现。Step 07 是**逐 entry 的
重任务步骤**：在单个子会话内完成一条 entry 的计划、实现、测试与评审，并且是唯一允许创建实现产物、
唯一允许新增或修改测试文件的步骤。Step 08 是**全系统最终验收步骤**：只在全部 entry 完成后运行一次。

Step 07 按各 epic `tickets.toml` 的**表序**、在 `after` 允许的范围内**串行**执行，每次一个子会话
只处理一条 entry；命中 epic 的最后一条时追加**Epic 收口**（代码评审 + 回顾
`epic-<slug>-retrospective.md`），不命中时不要额外做事。v7 已取消 sprint 概念：需要分批推进时用
`after` 与 `hitl` 表达，不再引入 sprint 表或「Sprint 收口」。

**产物位置**：规划产物在 initiative（PRD `prd-<slug>/`、架构 `architecture-<slug>/`、epic 文件、
`tickets.toml`、plan、`epic-<slug>-retrospective.md`、`deferred-work.md`）；循环报告在
`_he-output/works/<goal-id>/step-NN-*/`。任何改动代码的步骤都必须重跑受影响的测试，并写明确切命令
与结果。

每个步骤的执行方法都由「执行角色」指名的 `.heagent/skills/<role>/SKILL.md` 提供（`.claude/skills/`
是 v7 安装源，其 workflow 类 SKILL.md 依赖 `uv` 渲染，子会话不可直接用）；宿主把该要点并入
子会话任务正文。本文件只维护步骤顺序、输入输出、验收核对、产物位置和工作流特有的边界。

## Step 01: market-research（市场调研）

- 执行角色：`bmad-agent-analyst`
- 输入：用户意图、既有项目上下文
- 产出：市场综述、决策驱动因素、证据缺口（产物存 `step-01-market-research/report.md`）
- 验收核对：最终回复含 `## 需求总结` 段；每条论断都带来源、发布日期与访问日期；缺失的证据一律报为 gap

调研与本目标相关的市场、竞品、替代方案与用户声音证据。以 **headless** 方式工作：不问候、不提问、
不等待用户。

**初步分析：先把需求写清楚。** 这是整个工作流的第一次初步分析，也是唯一允许写入需求文档的步骤。
用 `file_read` 读任务正文给出的 `brief.md` 路径，按顺序收口：

1. `## 原始需求（Original Request）` 段是用户原话，**逐字冻结**——只读，不得改写、删减或美化；
2. 把初步分析后的**总结的需求**写进同一文档的 `## 总结的需求（Derived Requirements）` 段：用
   `file_edit` 覆盖那段占位文本（必要时用 `file_write` 重写整份文档，但必须逐字保留原始需求段）。
   写成明确、可验证、无内部矛盾的需求陈述：区分事实与假设、标出仍未解决的开放问题，且不得引入
   用户原话里没有的产品承诺。这是初步理解而非最终 PRD——范围收敛与 Epic 拆分留给后续步骤；
3. 在最终回复里给出 `## 需求总结` 章节，内容与写入需求文档的「总结的需求」一致。

用 `web_fetch` 抓取你被给出的、或你能推导出的 URL；本环境没有网页搜索工具，因此未解问题一律记为
**gap**，不得用训练数据「补上」。无法举证的论断必须写成未经验证的假设或开放 gap；公开数据稀薄时
如实报「稀薄」。

交付物：市场综述（细分市场、竞品、替代方案、定价与定位证据）、本目标真正依赖的**决策驱动因素**，
以及一份显式的**证据缺口清单**（每个缺口附上能补齐它的来源或查询）。把完整综述作为最终回复返回。

## Step 02: brainstorm-options（发散构思）

- 执行角色：`bmad-brainstorming`
- 输入：用户意图、市场综述
- 产出：选项空间、排序候选方向（产物存 `step-02-brainstorm-options/report.md`）
- 验收核对：至少三条实质性不同的方向，每条都带风险与仍需的证据

围绕目标与市场综述主持一次构思会。以 **「ideate for me」** 立场 headless 工作：不问候、不打开
composer 页面、不等待用户，且**绝不以等待用户收尾**。越过显而易见的答案，至少切换两次技法，
然后收敛成一份排序短名单。

把会话 memlog 放在 `.heagent/tmp/brainstorm-<goal-id>/` 下；它是草稿态，不是持久产物。交付物：
选项空间、带权衡的排序短名单，以及每个方向各自承担的风险与仍需的证据。把完整会话输出作为最终回复
返回。

## Step 03: analyze-requirements（需求分析）

- 执行角色：`bmad-agent-analyst`
- 输入：用户意图、市场综述、选项空间、既有项目上下文
- 产出：需求简报、工作拆分建议（产物存 `step-03-analyze-requirements/report.md`）
- 验收核对：需求有证据支撑且可验证

分析意图，区分事实与假设，识别干系人，产出带验收标准的**需求简报**与 story 粒度的工作拆分建议
（这是 Step 04/06 的输入，不落票树）。当仍存在互相竞争的解释时，把竞争解释与各自的默认处置写进
报告的开放问题清单，交由宿主按审批门规则处理。

## Step 04: define-product-scope（产品范围定义）

- 执行角色：`bmad-agent-pm`（PRD）→ `bmad-agent-po`（epic 切片）
- **审批门：本步产出需用户确认后才能进入下一步**
- 输入：需求简报、市场综述、brief.md
- 产出：已验证 PRD（`{initiative}/prd-<slug>/prd-<slug>.md`）、initiative 信封
  （`initiative-<slug>/initiative-<slug>.md`）、epic 拆分（`{initiative}/tickets/tickets.toml` 的
  `[[epic]]` + 每个 epic 的薄文件）；本步报告存 `step-04-define-product-scope/report.md`
- 验收核对：产品价值、范围、非目标与决策都是显式的；`tickets.py status <initiative>` 能读出全部
  epic 且 `problems` 为空；新 epic 文件带 `refined: false` 且**尚无** Requirements

先按 `bmad-agent-pm` 把需求简报变成**已验证 PRD**：记录假设、优先级、非目标与未决的产品决策。
**不要在这里拆 story**：逐 story 的拆分（`[[entry]]`）在 Step 06 架构确定之后进行。

再按 `bmad-agent-po` 的 `references/slice.md`「Initiative into epics」切片：

- 先定 initiative：goal 与本项目现有 initiative 相关就复用（`progress.md` 的 `- Initiative:` 行写
  既有 slug）；无关或没有 active initiative 时新建 `initiative-<slug>/` 信封 + `tickets/`，并按
  `bmad` 技能的 `references/initiative.md` 口径把 `[core] active_initiative` 写进
  `_bmad/custom/config.user.toml`（个人配置、gitignore、不入库）；
- 信封的 Requirements 用稳定 `R<n>` id，一行一条，并写明来源（PRD 章节或 brief）；`Done when` 写
  可观察的完成状态；PRD 记进 `sources:`；
- 在 `tickets/tickets.toml` 写 `[[epic]]`（`id` / `slug` / `title` / `description`（完成时是什么
  状态即可）/ `covers`（信封的 `R<n>`）/ 需要时 `after`），**表顺序即构建顺序**；每段标题式正文
  不进 `tickets.toml`；
- 每个新 epic 建 `tickets/epic-<slug>/` 文件夹与薄 epic 文件：Description、Outcome、Boundaries、
  已知的 `Done when`、`parent:` 指向 initiative、`covers`、`after`、`refined: false`，**不写
  Requirements**；
- 共享决策若不走 `bmad-architecture`，落成 opening epic 里一条 `hitl = true` 的 entry（Step 06 写），
  并给每个采用它的 epic 加 `after`；
- 每个切片决定（含被否掉的建议）记成带日期的 `Decision:` 行写进信封 Notes。

把 PRD 与有序 Epic 提案作为最终回复返回；审批通过后由宿主提交票树（仓库纪律：先呈报提交信息与
文件清单）。

## Step 05: design-architecture（架构设计）

- 执行角色：`bmad-architecture`
- 输入：已验证 PRD、initiative 信封的 Requirements 与 Constraints
- 产出：架构 spine（`{initiative}/architecture-<slug>/architecture-<slug>.md`，决策带稳定 id 并
  列出刻意留开的项）；本步报告存 `step-05-design-architecture/report.md`
- 验收核对：边界、接口、依赖、不变量与失败处理都是显式的；spine 已被相关 epic 作为
  companion/References 采用

产出精简的技术架构与决策记录。保持模块归属清晰，并记录安全、可靠性、迁移与验证路径。v7 口径下
spine 只固定「各自独立构建会不一致」的决策；采纳方式是由 epic 文件把它记进 `sources:`/References
（或 `companions:`），不要另建一套架构文档树。

## Step 06: refine-stories（故事细化）

- 执行角色：`bmad-agent-po`
- **审批门：本步产出需用户确认后才能进入下一步**
- 输入：已验证 PRD、epic 拆分、架构 spine
- 产出：细化的 epic（Requirements + `refined: true`）、每个 epic 的 entry 清单
  （`tickets/epic-<slug>/tickets/tickets.toml`）；本步报告存 `step-06-refine-stories/report.md`
- 验收核对：最终回复含 `## Epic 细化` 与 `## Story 拆分` 两章；`tickets.py status <initiative>` 的
  `problems` / `unpinned_after` / `undeclared_after` / `order_conflict` 全空；每条 entry 单一目标、
  `verify` 可判定、`after` 由更早工作交付、`covers` 指向所属 epic 的 `R<n>`，且无 `unknown`

这是**规划步骤**：把已验证范围变成「构建顺序明确、依赖有序、验收标准固定」的 entry backlog。
**本步骤不实现任何改动。**

**第一步：细化 epic。** 对每个 `refined: false` 的 epic，按 `references/slice.md`「Refining an epic」：
说清 epic、initiative 与 companion 已经为它的 story 定了什么，把仍开放的点逐条给出处置建议（现在定 /
先做 spike / 留给 story）；然后写 epic 的 Requirements（`R<n>`，引用父级 id）、回读 Outcome 与
`Done when`、置 `refined: true`。open 项的裁决记成带日期的 `Decision:` 行写进 epic Notes。

**第二步：排 entry。** 读 epic 文件与它的 `Done when`，把工作拆成 entry，写进该 epic 的
`tickets/tickets.toml`（模板见 `bmad-agent-po/assets/tickets-template.toml`）。每条 entry 至少含：

- `type`（story / spike / bug）、`id`（从 1 起连续、永不复用）、`title`；
- `description`：完成时是什么状态（不是「我想要」句）；
- `verify`：一条可跑或可观察的检查，实现者能自己证明达成；
- `covers`：所属 epic 的 `R<n>`；
- `after`：仅前置（`<epic id>.<entry id>` 或 `epic-<slug>`），顺序靠表序表达；依赖必须由更早的
  entry/epic 交付，不留 `unpinned_after` / `undeclared_after`；
- `hitl`（需要人操作）、`risk`（low/medium/high）；用户要求「先看计划」或 epic 要无人值守构建时加
  `plan_checkpoint` / `done_checkpoint`；`refine = true` 只在用户要求时加；
- 仍开放、必须由人裁决的点写成 `unknown`（一句话用户问题）——**构建前必须清零**，否则 `next` 会把
  它列进 `blocked`。

**不要**为 entry 预写 leaf 文件（`story.md`）：只有评审、细化或发布时才 `tickets.py pull <epic-dir> <id>`
（`<epic-dir>` 是 epic 目录、`<id>` 是 entry 的 id；不是 `pull <ref>`）。
**不要**引入 sprint：v7 已取消 sprint，构建顺序只由表序与 `after` 决定；需要可演示切片时，在
`## Story 拆分` 里说明每条 epic 收口可演示什么。

**排序与树检查。** 表序即执行顺序：宿主按 epic 表序、epic 内 entry 表序严格串行执行，所以按将构建
的顺序写，不留空号、不重复编号。收尾跑 `tickets.py status <initiative>`，把 `problems` 提到的问题
逐条修掉再提交审批。

把完整计划作为最终回复返回，必须含两个显式章节：`## Epic 细化`（每个 epic 的 Requirements、Outcome
与 `Done when` 回读结论、遗留决策）与 `## Story 拆分`（逐 entry 清单及其 `verify`、`after`、`risk`、
checkpoint）。**缺任一章即未通过验收核对。**

禁止：实现改动；重新规划 initiative 或 epic 边界（那属于 Step 04 的重切）；写 `epics.md` 或
`_bmad-output/sprint-status.yaml`；产出有空号、重复 id 或与表序矛盾的 entry 清单；写出无法验证的
`verify`；留下 `unknown` 未裁决；手写 leaf 文件。

## Step 07: implement-story（实现故事）

- 执行角色：`bmad-build`（人在场）／`bmad-build-auto`（`/loop auto` 无人值守）
- 输入：`tickets.py find <ref>` 给出的 entry（或其 leaf 文件）、epic 文件、plan 路径、brief.md
- 产出（每条 entry）：plan 文件（路径取 `find` 的 `plan`，与 `tickets.toml` 同级），frontmatter 的
  `status` 沿 `draft → ready-for-dev → in-progress → in-review → built` 推进；epic 最后一条完成时
  追加 `epic-<slug>-retrospective.md`
- 验收核对（每条 entry）：plan 含 `## Tasks & Acceptance`、`## Verification` 与实现/评审结论；宿主
  亲自跑完 `## Verification` 的记录命令且结果写入 progress.md；无遗留 Critical 发现

`bmad-build` 是本步骤的实现、测试与评审方法论来源（计划模板在 `.heagent/skills/bmad-build/plan-template.md`，
v7 安装源同名文件在 `.claude/skills/bmad-build/`）。
**严格串行**：每个子会话只处理一条 entry，按表序取 `tickets.py next <initiative>` 的
`ready_to_start` 首行，或按用户点名的 `<ref>`；宿主在任务正文里给出该 entry 全文、epic 文件全文、
`find` 返回的 plan 路径与 `brief.md` 路径，并附上 `after` 所指 entry 的 plan 中 Code Map /
Design Notes / Plan Change Log 作为连续性上下文。开始前必须核对：该 entry 无 `unknown`、无未裁决
的核心 `Ask First`、无竞争方案；发现即 `mark <ref> blocked --blocked <原因>`，停止并报告。

**状态与证据。** plan 的 `ticket` 必须等于 entry 的 `id`；`baseline_revision` 必须是改动前从版本
控制直接取得的完整规范 id。状态只经 `tickets.py mark <ref> <status>` 推进，不手改 frontmatter。

**checkpoint。** `plan_checkpoint` → 计划完成后停下（`bmad-build-auto` 用「Halt after planning」停在
`ready-for-dev`），宿主呈报计划等人放行；`hitl` → 需要人操作的环节由宿主暂停并说明；`done_checkpoint`
→ `built` 后停下等人放行。没人要求的门不要自行加。

**Epic 收口。** 当前 entry 是该 epic 最后一条、且 epic 全部 entry 达到 `built`/`in-review`/`done` 时：
用 `bmad-code-review` 对本 epic 全部改动做一次对抗式评审（build 内已跑 thorough 时可省），再用
`bmad-retrospective` 产出 `epic-<slug>-retrospective.md`；本步发现的**不属于任何 entry** 的真实问题
按 `source_plan` / `summary` / `evidence` 追加到 `{initiative}/deferred-work.md`，不要顺手扩范围。

**验证工作区约定。** 需要临时副本或夹具（例如变异测试）时，在工作区内创建并读写：
`.heagent/tmp/<goal-id>/<ref>/`（per-entry 子目录）。**不要**用 shell 把项目拷到 `%TEMP%` 等工作区
外的路径（会被工作区路径围栏拦下）。要跑脚本就落盘成文件再执行——内联 `python -c` / `node -e`
单行脚本难以审查与复跑，落盘脚本才可审计、可重放（含危险关键词的内联载荷仍会被整条命令扫描拦下，
但良性内联命令本身不禁）。

**开发阶段变更规则。** 如果 Step 07 或 Step 08 发现冻结方案无法满足需求，按以下顺序处理：

1. 停止受影响的 entry：`tickets.py mark <ref> blocked --blocked <原因>`，不用临时方案替代已选方案；
2. 报告影响范围与需要重新决策的事项；
3. 回到 Step 04 或 Step 06，由 `bmad-agent-po` 重切（必要时先补 `bmad-architecture` 决策），
   `Decision:` 记入 epic Notes；
4. 经用户重新审批后，`mark <ref> ready-for-dev`（或 `in-progress`）才恢复实现。

不得通过修改 `tickets.toml`、放宽 `verify`、手改 epic Requirements 或在开发对话中口头选型来绕过审批。

## Step 08: system-integration-test（系统集成及测试）

- 执行角色：`bmad-qa-generate-e2e-tests`
- 输入：全部 entry 的 plan（Verification、Auto Run Result、评审发现）、epic 的 `Done when`、
  架构 spine、`tickets.py status` 的现状
- 产出：系统集成报告（`step-08-system-integration-test/report.md`，逐 epic 报告落
  `{initiative}/tickets/epic-<slug>/epic-<slug>-integration-report.md`）
- **审批门（最终放行 / checkpoint）**：报告核对通过后宿主停下请求确认；`approve` ⇒ 逐 entry
  `tickets.py mark <ref> done`、`progress.md` 状态置 `done`，并在决策日志记「step-08 checkpoint
  已确认 + 答复原文」；`reject <原因>` ⇒ 针对被驳回项重跑本步
- 验收核对：最终回复含 `## 评审发现`、`## 质量门禁`、`## 系统集成结论` 三段；逐 epic 集成场景与
  跨 Epic 端到端场景都记录确切命令与观察结果，且不存在未决 Critical；构建前 `tickets.py status`
  无 `blocked`、无 `unknown`

`bmad-qa-generate-e2e-tests` 是本步骤的集成与端到端测试方法论来源。全部 entry 完成后只执行一次：
逐 epic 验证跨 story 集成场景，并验证跨 epic 主路径、失败路径与恢复路径。质量门禁用本仓现行命令
（`pytest`、`ruff check`、`ruff format --check`、`mypy src`、`bandit -r src/ -ll`，或
`python scripts/quality_gate.py`）。顶层报告给出质量门禁、未决 Critical 与系统级结论。

只允许修复本步骤发现的 Critical 集成缺陷：修完必须重跑受影响命令并把证据补记到该 epic 的 plan 或
integration-report；`tickets.toml` 与已冻结的 epic Requirements 保持只读。没拿到 `approve` 之前，
任何 entry 都不得置 `done`。
