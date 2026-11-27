# /loop 开发工作流（流程契约）

本文件连同同包 `references/` 下的章节文件是 `/loop` 工作流的**完整可执行契约**与唯一真源（章节归属见「文件地图」）。执行者是主会话 agent（下称**宿主**）：
宿主按本契约逐步驱动流程，每个步骤用一个**全新**的子会话（`task_delegate`）执行；没有 Python
状态机，全部状态由宿主按本契约落盘维护。任何步骤都不得跳过。

**BMAD v7 是规划与实现的唯一正本。** 本工作流不再自建 epic/story 清单：规划产物（initiative 信封、
epic 文件、`tickets.toml`）与 story 状态（plan frontmatter）全部住 goal 目录的票树
（`docs/<goal-id>/tickets/`），由 `.heagent/skills/bmad-agent-po/scripts/tickets.py` 以显式目录读写。
旧口径的 `epics.md` 与 `sprint-status.yaml` **已废弃**，任何步骤都不得再写、也不得再以它们为 story 清单。

本工作流产出的**持久性非代码产物**：规划文档（PRD、架构 spine、epic 文件、`tickets.toml`、plan）
与循环自身的编排产物（需求原文、进度、各步报告）都写入 goal 目录 `docs/<goal-id>/` 之下；源码仍留在
仓库既有位置。全部正文与产物使用中文。

## 文件地图

正文以「章节名」引用的章节按下表定位；子会话需要哪一节，宿主就把该节全文并进任务正文。

| 文件 | 章节 |
|---|---|
| `workflow.md`（本文件） | 「宿主执行循环」「审批门与 checkpoint」「步骤纪律」、Step 01–08 |
| `references/tickets.md` | 「票树接口」「状态与目录约定」 |
| `references/parallel-batch.md` | 「epic 内并行批」 |
| `references/closeout.md` | 「epic 收口三审」「完成即自动提交」「上下文交接与续跑」 |
| `references/commands.md` | 「只读文档审查」 |
| `references/standards.md` | 「全局标准」 |

## 宿主执行循环

1. 读 `docs/current` 与 goal 目录的 `progress.md`，确定状态与下一步；已绑定 initiative
   时同时读 `tickets.py status <goal 目录>` 与 `next <goal 目录>`（story 事实只认脚本）。
2. 取**最小序号的未完成步骤**；Step 07 按「epic 内并行批」组批：默认成批并行（尊重表序与 `after`），组批与兜底判定见该节。
   把该步契约全文 + 输入产物路径（含 `find <goal 目录> <ref>` 给出的 entry / epic 文件 / plan 路径）作为任务
   正文，用 `task_delegate` 开全新子会话执行；子会话默认不写盘：产物正文或报告写在回复里，由宿主落盘；只有 Step 07 实现子会话按 entry 的 `write_set` 写源码、测试与 plan。
3. 子会话返回后，宿主按该步**验收核对**清单核对产出（`command:` 类核对亲自执行，含 `tickets.py` 与
   plan 的 Verification），把最终回复存为该步报告、核对结果写进 `progress.md`；未过按该步处置，不得静默放行。
   **先落盘再继续**：每完成一步（或失败/等待）都要先更新 `progress.md`，再进行下一步。
4. 停止条件：命中审批门 / Step 02 交互轮 / checkpoint / 步骤失败 / waiting_user / 全部步骤完成（状态置 `done`）。
   **除这些门之外不停**：可选问一句的、上一轮已呈报且未被反对的、以及有推荐项的事项，一律按默认值继续并在
   `progress.md` 记「按默认值执行」（需写入 epic 的记成带日期的 `Decision:`），不要为它们另开提问。
5. **entry 完成即续跑，epic 收口不是停止点**：一批 entry 全部置 `built`（串行时即单条）后，按「上下文交接与续跑」
   写交接块，再用 `tickets.py next <goal 目录>` 取下一批（不成批时取 `ready_to_start` 首行）继续——它可能就是
   下一个 epic 的第一条 entry，照常执行，不停下来等「epic 完成确认」。epic 里的 entry 停在 `built`
   （`state = review`）**不阻塞**续跑；`done` 只在 Step 08 的 `approve` 后逐条写。
6. **epic 全部 entry 完成后自动跑收口链**：触发与顺序以「epic 收口三审」为准（判据只认 `tickets.py status`，已完成的镜头跳过）。下一个 epic 的 `after` 未满足时按 `next` 的 `blocked[].waiting_on` 报告并停。

## 审批门与 checkpoint（v7 口径）

- **Step 02 交互轮不是审批门**：它只收敛方向、不产需批准的产物，停下只为拿用户输入；用户回一句就继续，不需要 `approve`。
- **规划审批**：Step 04（epic 拆分）与 Step 06（epic 细化 + story 拆分）产出核对通过后，宿主停下
  向用户展示产出并请求确认；`approve` / `reject <原因>` / `amend <补充>` 三种处置。用户的一「yes」
  同时是**提交票树**的授权（仓库纪律：中文 Conventional Commit，先呈报提交信息与文件清单再执行）。
- **条目级 checkpoint**：entry 上的 `hitl`（需要人操作）、`plan_checkpoint`（计划先由人看）、
  `done_checkpoint`（`built` 后等人放行）由 Step 07 逐条执行，未置位时不要额外加门。
- **最终放行**：Step 08 报告核对通过后停下；`approve` 才把 entry 逐条 `mark <goal 目录> <ref> done`、把 goal
  状态置 `done`，并在决策日志记答复原文。`done` 是人的决定，自动 job 永远不写。
- **用户一句话即放行**：用户以「继续 / 推进 / 按默认值 / `approve`」之类简短表态回应呈报时，视为对**已呈报
  推荐项**的确认与该门的放行——按契约执行（Step 08 则逐条 `mark done` + 状态置 `done`），并把答复原文记入
  决策日志。用户未表态时停在门前，`done` 永不自行写。

- **并行纪律**：默认并行——声明齐全（`parallel_group` + `write_set`）且「七条件」全过的相邻 entry 一律
  成批并行（见「epic 内并行批」）；串行是 fail-closed 兜底，只落声明缺失或条件不过的那几条。`after`
  仍只用于核对顺序合法：任何 entry 的依赖必须由构建顺序更靠前的 entry 或 epic 交付。
- **显性失败**：状态文件缺失或损坏、脚本非零退出、同一子会话任务连续两次失败时，宿主如实报告并停
  （状态置 blocked），不猜测、不伪造进度、不静默跳步。

## 步骤纪律

Step 01 与 Step 02 是**只读**步骤（市场调研与发散构思），不得修改项目实现产物，也不得建票树；
Step 01 的唯一写操作是把初步分析结论写回 `brief.md`；Step 02 的交互轮只写
`step-02-brainstorm-options/report.md` 与 `.heagent/tmp/` 下的 memlog，不改变这条只读边界；
Step 04 是**规划步骤的入口**：产出 PRD 与
epic 拆分（信封 + `[[epic]]` + 薄 epic 文件），只规划不实现。Step 06 是**规划步骤**：细化 epic、
把范围拆成 entry、排定构建顺序、关闭所有核心方案决策；它只规划，不实现。Step 07 是**逐 entry 的
重任务步骤**：在单个子会话内完成一条 entry 的计划、实现、测试与评审，并且是唯一允许创建实现产物、
唯一允许新增或修改测试文件的步骤。Step 08 是**全系统最终验收步骤**：只在全部 entry 完成后运行一次。

Step 07 按各 epic `tickets.toml` 的**表序**、在 `after` 允许的范围内推进：默认**成批并行**（组批与兜底
判定见「epic 内并行批」）；一个子会话仍只处理一条 entry。该 epic 全部 entry 完成后**自动**跑**Epic
收口**（三镜头并行三审 + 回顾 `<E编号>-<slug>-retrospective.md` + 自动提交 + 转下一个 epic，见该步正文与
「epic 收口三审」）；未满足触发条件时不要额外做事。v7 已取消 sprint 概念：需要分批
推进时用 `after` 与 `hitl` 表达，不再引入 sprint 表或「Sprint 收口」。

**产物位置**：规划产物在 initiative（PRD `prd-<slug>/`、架构 `architecture-<slug>/`、epic 文件、
`tickets.toml`、plan、`<E编号>-<slug>-retrospective.md`，延期项在 `brief.md`「延期项」段）；循环报告在
`docs/<goal-id>/step-NN-*/`。任何改动代码的步骤都必须重跑受影响的测试，并写明确切命令
与结果。

每个步骤的执行方法都由「执行角色」指名的 `.heagent/skills/<role>/SKILL.md` 提供（`.claude/skills/`
是上游安装源，其 workflow 类 SKILL.md 依赖 `uv` 渲染，子会话不可直接用）；宿主把该要点并入
子会话任务正文。本文件只维护步骤顺序、输入输出、验收核对、产物位置和工作流特有的边界。

## Step 01: market-research（市场调研）

- 执行角色：`bmad-agent-analyst`
- 输入：用户意图、既有项目上下文
- 产出：市场综述、决策驱动因素、证据缺口（产物存 `step-01-market-research/report.md`）
- 验收核对：最终回复含 `## 需求总结` 段；每条论断都带来源、发布日期与访问日期；缺失的证据一律报为 gap

调研与本目标相关的市场、竞品、替代方案与用户声音证据。以 **headless** 方式工作：不问候、不提问、
不等待用户。

**初步分析：先把需求写清楚。** 这是整个工作流的第一次初步分析，也是唯一允许写入需求文档的步骤。
读宿主给出的 `brief.md` 正文（子会话不读写文件），按顺序收口：

1. `## 原始需求（Original Request）` 段是用户原话，**逐字冻结**——只读，不得改写、删减或美化；
2. 把初步分析后的**总结的需求**写进同一文档的 `## 总结的需求（Derived Requirements）` 段：宿主以回复中的完整段落覆盖占位文本落盘，并逐字核对原始需求段未变。
   写成明确、可验证、无内部矛盾的需求陈述：区分事实与假设、标出仍未解决的开放问题，且不得引入
   用户原话里没有的产品承诺。这是初步理解而非最终 PRD——范围收敛与 Epic 拆分留给后续步骤；
3. 在最终回复里给出 `## 需求总结` 章节，内容与写入需求文档的「总结的需求」一致。

先用 `web_search` 检索，再用 `web_fetch` 抓取被给出或检索到的 URL；仍无法举证的问题一律记为
**gap**，不得用训练数据「补上」。无法举证的论断必须写成未经验证的假设或开放 gap；公开数据稀薄时
如实报「稀薄」。

交付物：市场综述（细分市场、竞品、替代方案、定价与定位证据）、本目标真正依赖的**决策驱动因素**，
以及一份显式的**证据缺口清单**（每个缺口附上能补齐它的来源或查询）。把完整综述作为最终回复返回。

## Step 02: brainstorm-options（发散构思）

- 执行角色：`bmad-brainstorming`
- **交互**：默认**与用户交互**（见本节「交互轮」）；用户当轮说「你自己定 / 不用问我」
  时退化为一次成稿
- 输入：用户意图、市场综述、上一轮用户回复（若有）、`step-02-brainstorm-options/report.md` 的
  `## 待回答的问题` 段
- 产出：选项空间、排序候选方向（产物存 `step-02-brainstorm-options/report.md`）
- 验收核对：至少三条实质性不同的方向，每条都带风险与仍需的证据；报告含 `## 用户输入` 段（逐字摘录
  用户原话，或写「未交互（原因）」）与 `## 待回答的问题` 段（无未答轮次写 `无`）

围绕目标与市场综述主持一次构思会。默认立场 **`Creative Partner`**（既提问也出主意）；用户当轮点名
`Facilitator`（只问、不给主意）或 `Ideate for me`（全自动）时按点名走。越过显而易见的答案，至少切换
两次技法，再收敛成一份排序短名单。

**交互轮（宿主代理往返）。** 子会话是隔离的、没有与用户对话的通道，所以往返由宿主承担：每轮开一个
新子会话，把「用户本轮原话（逐字）+ 已有 memlog 摘要 + 上轮方向」写进任务正文，取回本轮的方向与追问，
再由宿主呈报给用户。

- **轮 0（开局）**：子会话给出一个复合问题（做什么、为什么）与立场、技法批次的推荐（只在这一处允许
  选项式）；宿主呈报后停下等用户回答；
- **轮 1–N（默认 2 轮，用户点名可加到 5）**：每轮产出 3–5 条新方向，外加**一个**主追问（一条消息一个
  问题，不堆多选菜单），宿主呈报后停下；
- **收敛轮**：用户说「够了 / 你来定」或轮数用尽后，子会话出排序短名单、每条的风险与仍需的证据，宿主
  落盘报告并继续 Step 03。

**交互纪律。**

- 每轮结尾必须给「跳过（你来定）」出口；用户任一轮跳过即提前进收敛轮；
- 用户原话逐字记 memlog（`.heagent/tmp/brainstorm-<goal-id>/`，草稿态、不是持久产物），摘要与采纳／
  否决的方向写进报告的 `## 用户输入`；
- 交互轮只写报告与 memlog：不建票树、不改 `brief.md` 冻结段、不碰实现；用户的方向性裁决留到 Step 04
  落成带日期的 `Decision:` 行；
- 未答轮次写进报告的 `## 待回答的问题`，并把 `progress.md` 的当前步骤记成「Step 02 交互轮 N 待用户回复」；
  此后**不注册任何自动 job**（无人接手只会空转）：用户回复即在同一会话继续，或新会话 `/loop next` 读该段续跑
  ——已答就进下一轮，未答就原样重报问题，不重开一轮。

**退化（不交互）路径。** 用户当轮说「你自己定 / 不用问我」时不走交互轮：按
`Ideate for me` 一次成稿，报告 `## 用户输入` 写「未交互（原因）」并记 `Assumption:`。用户中途说「先别
问了」同样立即转收敛轮，不算跳步。

把完整会话输出作为最终回复返回。

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
- 产出：已验证 PRD（`docs/<goal-id>/prd-<slug>/prd-<slug>.md`）、信封段并入
  `docs/<goal-id>/brief.md`、epic 拆分（`docs/<goal-id>/tickets/tickets.toml` 的
  `[[epic]]` + 每个 epic 的薄文件）；本步报告存 `step-04-define-product-scope/report.md`
- 验收核对：产品价值、范围、非目标与决策都是显式的；`tickets.py status <goal 目录>` 能读出全部
  epic 且 `problems` 为空；新 epic 文件带 `refined: false` 且**尚无** Requirements

先按 `bmad-agent-pm` 把需求简报变成**已验证 PRD**：记录假设、优先级、非目标与未决的产品决策。
**不要在这里拆 story**：逐 story 的拆分（`[[entry]]`）在 Step 06 架构确定之后进行。

再按 `bmad-agent-po` 的 `references/slice.md`「Initiative into epics」切片：

- 先定 initiative：goal 与既有 initiative 相关就复用（`progress.md` 的 `- Initiative:` 行写既有
  slug）；无关或没有 initiative 时把信封段写进 goal 的 `brief.md`（写 `## 目标与产出` 段）并建
  `tickets/`；**不产**独立 `initiative-<slug>.md`。
  **不要**写 `[core] active_initiative`、不要写任何 BMad 配置文件：本契约靠显式目录定位票树
  （见「票树接口」），写入配置文件无效且会误导后续步骤；
- 信封的 Requirements 用稳定 `R<n>` id，一行一条，并写明来源（PRD 章节或 brief）；`Done when` 写
  可观察的完成状态；PRD 记进 `sources:`；
- 在 `tickets/tickets.toml` 写 `[[epic]]`（`id` / `slug` / `title` / `description`（完成时是什么
  状态即可）/ `covers`（信封的 `R<n>`）/ 需要时 `after`），**表顺序即构建顺序**；每段标题式正文
  不进 `tickets.toml`；
- 每个新 epic 建 `tickets/<E编号>-<slug>/` 文件夹与薄 epic 文件：Description、Outcome、Boundaries、
  已知的 `Done when`、`parent:` 指向 `brief`、`covers`、`after`、`refined: false`，**不写
  Requirements**；
- 共享决策若不走 `bmad-architecture`，落成 opening epic 里一条 `hitl = true` 的 entry（Step 06 写），
  并给每个采用它的 epic 加 `after`；
- 每个切片决定（含被否掉的建议）记成带日期的 `Decision:` 行写进信封 Notes。

把 PRD 与有序 Epic 提案作为最终回复返回；审批通过后由宿主提交票树（仓库纪律：先呈报提交信息与
文件清单）。

## Step 05: design-architecture（架构设计）

- 执行角色：`bmad-architecture`
- 输入：已验证 PRD、initiative 信封的 Requirements 与 Constraints
- 产出：架构 spine（`docs/<goal-id>/architecture-<slug>/architecture-<slug>.md`，决策带稳定 id 并
  列出刻意留开的项）；本步报告存 `step-05-design-architecture/report.md`
- 验收核对：边界、接口、依赖、不变量与失败处理都是显式的；spine 已被相关 epic 作为
  companion/References 采用

产出精简的技术架构与决策记录。保持模块归属清晰，并记录安全、可靠性、迁移与验证路径。本口径下
spine 只固定「各自独立构建会不一致」的决策；采纳方式是由 epic 文件把它记进 `sources:`/References
（或 `companions:`），不要另建一套架构文档树。

## Step 06: refine-stories（故事细化）

- 执行角色：`bmad-agent-po`
- **审批门：本步产出需用户确认后才能进入下一步**
- 输入：已验证 PRD、epic 拆分、架构 spine
- 产出：细化的 epic（Requirements + `refined: true`）、每个 epic 的 entry 清单
  （`tickets/<E编号>-<slug>/tickets/tickets.toml`）；本步报告存 `step-06-refine-stories/report.md`
- 验收核对：最终回复含 `## Epic 细化` 与 `## Story 拆分` 两章；`tickets.py status <goal 目录>` 的
  `problems` / `unpinned_after` / `undeclared_after` / `order_conflict` 全空；每条 entry 单一目标、
  `verify` 可判定、`after` 由更早工作交付、`covers` 指向所属 epic 的 `R<n>`，且无 `unknown`

这是**规划步骤**：把已验证范围变成「构建顺序明确、依赖有序、验收标准固定」的 entry backlog。
**本步骤不实现任何改动。**

**第一步：细化 epic。** 对每个 `refined: false` 的 epic，按 `references/slice.md`「Refining an epic」：
说清 epic、initiative 与 companion 已经为它的 story 定了什么，把仍开放的点逐条给出处置建议（现在定 /
先做 spike / 留给 story）；然后写 epic 的 Requirements（`R<n>`，引用父级 id）、回读 Outcome 与
`Done when`、置 `refined: true`。open 项的裁决记成带日期的 `Decision:` 行写进 epic Notes。

**编号规则（人读标识）。** 每个 epic 与其 entry 都必须有稳定的人读编号：epic = `E<n>`、entry = `E<n>-S<mm>`，
其中 `n`/`m` 分别取 `tickets.py status` 输出里 `epics[].id` / `tickets[].id`（整数，永不复用）。
字母一律**大写**、场次**两位补零**：写 `E<n>`、`E<n>-S<mm>`，不写 `e<n>`、`E<n>-S<m>`。
编号写三处：`tickets.toml` 的 `code` 字段（`code = "<E编号>"` / `code = "<E编号>-S<mm>"`）、`title` 前缀
（`<E编号> · …` / `<E编号>-S<mm> · …`）、epic 文件 frontmatter 的 `code:`。
工具仍以整数 `id` 生成 `ref`（`1.1`），编号只是人读别名，不参与排序与依赖。

- **文件与目录同样带编号**：epic 目录与里面的同名文件都以编号开头、用 `<e编号>-<slug>`（**目录名里的编号小写**，`code` / `title` 仍大写；如
  `tickets/<e编号>-<slug>/<e编号>-<slug>.md`；目录名即该 epic 的 `slug`，
  `tickets.toml` 的 `slug` 与 epic frontmatter 的 `slug:` 必须与目录名逐字一致）。
  用编号开头的目录需要票树脚本的 `EPIC_RE` 与 `epic_folders()` 同时接受 `<E编号>-…` 与 `epic-…`，
  `tickets_dir()` 也要改成「只有缺 `tickets/` 目录时才判 earlier layout」——重装/升级角色包会覆盖这三处补丁
  （症状：epic 目录不被识别、`status` 读出 0 条，或在 goal 目录旁放已收口目标 `<E编号>-<slug>/` 时误报
  「earlier layout」）。plan 用
  `<E编号>-S<mm>-<kebab 摘要>-plan.md`。`tickets.py` 新生成的 plan 名是
  `<type>-<小写 slug>-plan.md`，**建好后按上面改名即可**——工具是按 plan frontmatter 的 `ticket`
  关联 entry 的，文件名只要 `-plan.md` 结尾就不影响 `status` / `find` / `mark`。
- **续编，不重起**：`n` 取「仓库既有最大 `<E编号>` + 1」，既有 = 仓库里冻结历史用过的编号与各 goal
  已落盘的 `code`；entry 在所属 epic 内从 `S01` 起两位编号（`S01`…），跨 goal 共用同一编号序列；
  已用编号**永不复用**（与整数 `id` 同规则）。

**第二步：排 entry。** 读 epic 文件与它的 `Done when`，把工作拆成 entry，写进该 epic 的
`tickets/tickets.toml`（模板见 `bmad-agent-po/assets/tickets-template.toml`）。每条 entry 至少含：

- `type`（story / spike / bug）、`id`（从 1 起连续、永不复用）、`title`；
- `description`：完成时是什么状态（不是「我想要」句）；
- `verify`：一条可跑或可观察的检查，实现者能自己证明达成；
- `covers`：所属 epic 的 `R<n>`；
- `after`：仅前置（`<epic id>.<entry id>` 或 `<E编号>-<slug>`），顺序靠表序表达；依赖必须由更早的
  entry/epic 交付，不留 `unpinned_after` / `undeclared_after`；
- `hitl`（需要人操作）、`risk`（low/medium/high）；用户要求「先看计划」或 epic 要无人值守构建时加
  `plan_checkpoint` / `done_checkpoint`；`refine = true` 只在用户要求时加；
- 仍开放、必须由人裁决的点写成 `unknown`（一句话用户问题）——**构建前必须清零**，否则 `next` 会把
  它列进 `blocked`。

**并行声明（义务）。** 并行是 Step 07 的默认形态：每条 entry 都默认声明 `parallel_group`（非空组名，
能同批的进同组）与 `write_set`（该 entry 会改的仓库相对路径全清单，含新建文件与测试文件）；不声明的
entry 单条串行兜底，且须在 plan 写明不能并行的原因（带门 / 依赖并发中的 entry / 单条已满负荷）。
`tickets.py` 不读这两个键（不进 `status`），它们是 `/loop` 的组批门控
输入，判定规则见「epic 内并行批」。

**不要**为 entry 预写 leaf 文件（`story.md`）：只有评审、细化或发布时才 `tickets.py pull <epic 目录> <entry id>`。
**不要**引入 sprint：v7 已取消 sprint，构建顺序只由表序与 `after` 决定；需要可演示切片时，在
`## Story 拆分` 里说明每条 epic 收口可演示什么。

**排序与树检查。** 表序即执行顺序：宿主按 epic 表序推进，epic 内按表序组批（默认成批并行、声明缺失或条件不过的条目单条串行），所以按将构建
的顺序写，不留空号、不重复编号。收尾跑 `tickets.py status <goal 目录>`，把 `problems` 提到的问题
逐条修掉再提交审批。

把完整计划作为最终回复返回，必须含两个显式章节：`## Epic 细化`（每个 epic 的 Requirements、Outcome
与 `Done when` 回读结论、遗留决策）与 `## Story 拆分`（逐 entry 清单及其 `verify`、`after`、`risk`、
checkpoint）。**缺任一章即未通过验收核对。**

禁止：实现改动；重新规划 initiative 或 epic 边界（那属于 Step 04 的重切）；写 `epics.md` 或
`sprint-status.yaml`；产出有空号、重复 id 或与表序矛盾的 entry 清单；写出无法验证的
`verify`；留下 `unknown` 未裁决；手写 leaf 文件。

## Step 07: implement-story（实现故事）

- 执行角色：`bmad-build`（本契约唯一的实现角色——全程有人在场，没有无人值守档）
- 输入：`tickets.py find <goal 目录> <ref>` 给出的 entry（或其 leaf 文件）、epic 文件、plan 路径、brief.md
- 产出（每条 entry）：plan 文件（路径取 `find` 的 `plan`，与 `tickets.toml` 同级），frontmatter 的
  `status` 沿 `draft → ready-for-dev → in-progress → in-review → built` 推进；该 epic 全部 entry 完成后
  追加 `<E编号>-<slug>-retrospective.md`
- 验收核对（每条 entry）：plan 含 `## Tasks & Acceptance`、`## Verification` 与实现/评审结论；宿主
  亲自跑完 `## Verification` 的记录命令且结果写入 progress.md；无遗留 Critical 发现
- **产物形态**：每条 entry 只产 **plan**（临时证据可按需落
  `docs/<goal-id>/step-07-implement-story/<ref>/notes.md`），**不再产**旧口径的 `story.md` /
  `implementation.md` / `test-report.md` / `verify-report.md`；命令进 plan 的 `## Verification`，
  结果与结论进 `progress.md`。该 epic 全部 entry 完成后另产 `<E编号>-<slug>-retrospective.md`。

`bmad-build` 是本步骤的实现、测试与评审方法论来源（计划模板在 `.heagent/skills/bmad-build/plan-template.md`，
上游安装源同名文件在 `.claude/skills/bmad-build/`）。
**按批执行（默认并行）**：组批与兜底判定见「epic 内并行批」。每个子会话只处理一条 entry，按表序取 `tickets.py next <goal 目录>` 的
`ready_to_start`（整批按声明序，或仅首行），或按用户点名的 `<ref>`；宿主在任务正文里给出该 entry 全文、epic 文件全文、
`find` 返回的 plan 路径与 `brief.md` 路径，并附上 `after` 所指 entry 的 plan 中 Code Map /
Design Notes / Plan Change Log 作为连续性上下文。开始前必须核对：该 entry 无 `unknown`、无未裁决
的核心 `Ask First`、无竞争方案；发现即 `mark <goal 目录> <ref> blocked --blocked <原因>`，停止并报告。

**状态与证据。** plan 的 `ticket` 必须等于 entry 的 `id`；`baseline_revision` 必须是改动前从版本
控制直接取得的完整规范 id。状态只经 `tickets.py mark <goal 目录> <ref> <status>` 推进，不手改 frontmatter。

**checkpoint。** `plan_checkpoint` → 计划完成后停在
`ready-for-dev`，宿主呈报计划等人放行；`hitl` → 需要人操作的环节由宿主暂停并说明；`done_checkpoint`
→ `built` 后停下等人放行。没人要求的门不要自行加。

**Epic 收口。** 满足触发条件后按「epic 收口三审」「完成即自动提交」「上下文交接与续跑」三节执行。本步只把不属于任何 entry 的真实问题追加到 goal `brief.md`「延期项」段，不扩范围。

**验证工作区约定。** 需要临时副本或夹具（例如变异测试）时，在工作区内创建并读写：
`.heagent/tmp/<goal-id>/<ref>/`（per-entry 子目录；并行批内各条用各自 `<ref>`，天然互不踩踏）。**不要**用 shell 把项目拷到 `%TEMP%` 等工作区
外的路径（会被工作区路径围栏拦下）。要跑脚本就落盘成文件再执行——内联 `python -c` / `node -e`
单行脚本难以审查与复跑，落盘脚本才可审计、可重放（含危险关键词的内联载荷仍会被整条命令扫描拦下，
但良性内联命令本身不禁）。

**开发阶段变更规则。** 如果 Step 07 或 Step 08 发现冻结方案无法满足需求，按以下顺序处理：

1. 停止受影响的 entry：`tickets.py mark <goal 目录> <ref> blocked --blocked <原因>`，不用临时方案替代已选方案；
2. 报告影响范围与需要重新决策的事项；
3. 回到 Step 04 或 Step 06，由 `bmad-agent-po` 重切（必要时先补 `bmad-architecture` 决策），
   `Decision:` 记入 epic Notes；
4. 经用户重新审批后，`mark <goal 目录> <ref> ready-for-dev`（或 `in-progress`）才恢复实现。

不得通过修改 `tickets.toml`、放宽 `verify`、手改 epic Requirements 或在开发对话中口头选型来绕过审批。

## Step 08: system-integration-test（系统集成及测试）

- 执行角色：`bmad-qa-generate-e2e-tests`
- 输入：全部 entry 的 plan（Verification、Auto Run Result、评审发现）、epic 的 `Done when`、
  架构 spine、`tickets.py status` 的现状
- 产出：系统集成报告（`step-08-system-integration-test/report.md`，逐 epic 报告落
  `docs/<goal-id>/tickets/<E编号>-<slug>/<E编号>-<slug>-integration-report.md`）
- **审批门（最终放行 / checkpoint）**：报告核对通过后宿主停下请求确认；`approve` ⇒ 逐 entry
  `tickets.py mark <goal 目录> <ref> done`、`progress.md` 状态置 `done`，并在决策日志记「step-08 checkpoint
  已确认 + 答复原文」；`reject <原因>` ⇒ 针对被驳回项重跑本步
- 验收核对：最终回复含 `## 评审发现`、`## 质量门禁`、`## 系统集成结论` 三段；逐 epic 集成场景与
  跨 Epic 端到端场景都记录确切命令与观察结果，且不存在未决 Critical；构建前 `tickets.py status`
  无 `blocked`、无 `unknown`

`bmad-qa-generate-e2e-tests` 是本步骤的集成与端到端测试方法论来源。全部 entry 完成后只执行一次：
逐 epic 验证跨 story 集成场景，并验证跨 epic 主路径、失败路径与恢复路径。质量门禁用**仓库自己的验证入口**：
以仓库代理协议与构建脚本定义的判据为准——单元测试、构建、静态检查、
设备/集成测试四类，或仓库自己的一键脚本；逐 entry 另以 plan 的 `## Verification` 为准；
**不要照搬其他仓库的命令**。顶层报告给出质量门禁、未决 Critical 与系统级结论。

只允许修复本步骤发现的 Critical 集成缺陷：修完必须重跑受影响命令并把证据补记到该 epic 的 plan 或
integration-report；`tickets.toml` 与已冻结的 epic Requirements 保持只读。没拿到 `approve` 之前，
任何 entry 都不得置 `done`。
