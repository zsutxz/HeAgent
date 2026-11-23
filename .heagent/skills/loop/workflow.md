# /loop 开发工作流（流程契约）

本文件是 `/loop` 工作流的**完整可执行契约**与唯一真源。执行者是主会话 agent（下称**宿主**）：
宿主按本契约逐步驱动流程，每个步骤用一个**全新**的子会话（`task_delegate`）执行；没有 Python
状态机，全部状态由宿主按本契约落盘维护。任何步骤都不得跳过。

**BMAD v7 是规划与实现的唯一正本。** 本工作流不再自建 epic/story 清单：规划产物（initiative 信封、
epic 文件、`tickets.toml`）与 story 状态（plan frontmatter）全部住 goal 目录的票树
（`Docs/<goal-id>/tickets/`），由 `.heagent/skills/bmad-agent-po/scripts/tickets.py` 以显式目录读写。
旧口径的 `epics.md` 与 `sprint-status.yaml` **已废弃**，任何步骤都不得再写、也不得再以它们为 story 清单。

本工作流产出的**持久性非代码产物**：规划文档（PRD、架构 spine、epic 文件、`tickets.toml`、plan）
与循环自身的编排产物（需求原文、进度、各步报告）都写入 goal 目录 `Docs/<goal-id>/` 之下；源码仍留在
仓库既有位置。全部正文与产物使用中文。

## 票树接口（BMAD v7）

工具统一前缀：`python .heagent/skills/bmad-agent-po/scripts/tickets.py`（脚本需要 PyYAML；环境无 `uv`
时直接用装了 PyYAML 的解释器跑，不要写 `uv run`）。**BMad 配置与脚本住 `.heagent/config/`，但票树不读
它们**：`find_project_root()` 只认「含 `_bmad/` 的目录」、`central_config()` 只读
`_bmad/scripts/config_utils.py`，这两条默认路径在按本契约布局的仓库里不成立，因此**每条命令都必须带显式目录**
——`locate_dir()` 在 `folder.is_dir()` 为真时把 `root` 置 `None`、`bases` 置空，整条 config 分支不执行。
别加 `--project-root`，别指望 `active_initiative` 自动选树。

- **布局**：goal 目录本身就是 initiative 根（`Docs/<goal-id>/`）：
  - `Docs/<goal-id>/brief.md`——需求真源兼信封：原始需求（冻结）+ Requirements（`R<n>` 稳定 id）、
    Constraints、`Done when`、Boundaries、延期项、决策记录；**不产**独立 `initiative-<slug>.md`；
  - `Docs/<goal-id>/tickets/tickets.toml`——`[[epic]]` 表，**表顺序即构建顺序**；
  - `Docs/<goal-id>/tickets/<E编号>-<slug>/<E编号>-<slug>.md`——epic 文件；薄 epic 带
    `refined: false`（只同意边界、尚未细化），细化后写 Requirements 并置 `refined: true`；
  - `Docs/<goal-id>/tickets/<E编号>-<slug>/tickets/tickets.toml`——该 epic 的 `[[entry]]`
    （`type` = story / spike / bug），同样表顺序即构建顺序；
  - plan——`tickets.py find <goal 目录> <ref>` 返回的绝对路径 `plan`（与 `tickets.toml` 同级，如
    `story-<ref>-…-plan.md`），**plan frontmatter 的 `status` 是 story 状态的唯一真源**；
  - epic 收口——回顾报告 `<E编号>-<slug>-retrospective.md` 落 epic 文件夹；跨 story 延期项写
    goal 的 `brief.md`「延期项」段（记 `source_plan` / `summary` / `evidence`），**不产** `deferred-work.md`。
- **命令**（`<init>` = `Docs/<goal-id>`，`<epic-dir>` = `<init>/tickets/<E编号>-<slug>`）：
  `status <init>`（`tickets` 行：`ref` / `status` / `state` / `risk` / `hitl` / `after`，
  顶层 `counts` / `epics` / `unpinned_after` / `undeclared_after` / `order_conflict`）、
  `next <init>`（`ready_to_refine` / `ready_to_start` / `in_progress` / `blocked` 分组，行上可能带
  `plan_checkpoint` / `done_checkpoint` / `drift`，`blocked` 行带 `waiting_on` / `blocked_reason` /
  `unknown`）、`find <init> <ref>`（单票：`story_file` / `epic_file` / `plan` / `description` /
  `verify`）、`pull <epic-dir> <entry id>`（**例外：epic 目录 + 纯 entry id**，不是 `1.1`；只在评审/
  细化/发布时需要）、`mark <init> <ref> <status>`（把状态写进 plan，repo store 唯一合法写法）、
  `move <from> <ref> <to>`（换文件夹，id 不复用）。
- **状态阶梯**：`draft → ready-for-dev → in-progress → in-review → built → done`，另有 `blocked` /
  `dropped`。**build 只到 `built`；`done` 只能由人或编排器写。**
- **角色技能根**：`.heagent/skills/<role>/SKILL.md`（适配版：方法正文已预渲染进包内，无需再跑渲染器）。
  `.claude/skills/<role>/` 是上游安装源，其 SKILL.md 可能只是 `uv run render_skill.py` 的启动器——
  环境无 `uv` 时子会话**不可**直接用；仅当 `.heagent/skills/` 缺该角色时，才回退读它的
  `workflow.md` 与 `step-*.md` 原文。
  **同步命令**：上游的 `scripts/sync_bmad_role_skills.py` 不一定随检出提供；缺角色时手工复制并核对 frontmatter。
  **角色正文里的脚本调用**：一律走 `python .heagent/config/scripts/<name>.py`（`resolve_config` /
  `resolve_customization` / `memlog` / `render_skill`，需 python ≥3.11）；`uv run …` 换成 `python …`，
  `{output_folder}` = `Docs`、`{active_initiative}` = goal 目录名。
- **自检**：`python .heagent/skills/loop/scripts/selfcheck.py` 在隔离目录里跑一遍
  `new-goal` → Step04 → Step06 → Step07（mark/find/pull/move），断言 17 项；退出码 0 = 全通。
  改动票树工具、契约或模板后先跑它，再谈推进。
- **清单真源**：一条 epic 的 story 清单只有它的 `tickets/tickets.toml`（表序即执行序）；plan 与
  leaf 文件是逐条产物，不是清单。
- **三条禁令**：状态一律经 `mark` 写，不手改 plan frontmatter；已批准的 entry 与 epic
  Requirements 不手改（要改走重切）；`id` / `ref` / plan 路径一律取脚本输出，不自行发明。

## 状态与目录约定

- **根目录**：`Docs/`；goal 目录直接位于其下（`Docs/<goal-id>/`）。旧 `/goal` 的 `_he-output/goals/`
  与之完全隔离、互不读写；仓库可在 `Docs/README.md` 写自己的状态根导航。
- **current 指针**：`Docs/current` 写当前 goal 目录相对 `Docs/` 的路径（新文档根如 `push-inbox`；同一文档根下按代分目录如
  `aihome-client/goal-3`）（`reset` 只删指针、保留目录；无活动 goal 时不存在）。
  指针目录必须有 `tickets/` 票树，否则 `status` / `next` 只读出一棵空树。
- **起跑**：`python .heagent/skills/loop/scripts/new-goal.py <goal-id> --title <标题> [--request <用户原话>] [--envelope]` 建骨架（`brief.md` / `progress.md` / `tickets/tickets.toml` / `Docs/current`），只建骨架不写 Requirements 与 entry；`--root <DIR>` 供空跑验证，`--no-current` 不写指针。
- **goal 目录**：`Docs/<goal-id>/`（`<goal-id>` 为英文 slug，冲突时追加 `-a`/`-b`…）：
  - `brief.md`——**需求真源**（需求侧只有这一份）：`## 原始需求（Original Request）` 段是用户原话，
    **逐字冻结**；`## 总结的需求（Derived Requirements）` 段由 Step 01 写；`R<n>` / `Done when` /
    `Constraints` / 延期项 / 决策记录也住这里；epic / entry 清单不写在这里（住 `tickets/`）。
    骨架见本包 `templates/BRIEF.md`——它与 `templates/PROGRESS.md` 同属**脚本渲染模板**（占位符
    `{title}` / `{request}` / `{goal_id}` / `{today}` / `{initiative}`），`EPIC.md` / `STORY.md`
    才是人写参考模板；
  - `progress.md`——编排状态唯一真源（格式见本包 `templates/PROGRESS.md`，占位符 `{goal_id}` /
    `{title}` / `{today}` / `{initiative}` 由 `new-goal.py` 渲染，手写时替换成实际值；该段
    `- Epic 与 entry` 写成 `- <E编号> <epic slug>：N entry，X planned / Y built`）。**它不记
    story 状态**（只从 `tickets.py status` 读）；每个交接点覆盖重写其中的 `## 交接块（下一轮入口）`，
    历史留在 `## 决策日志`。
  - `step-NN-<名称>/report.md`——各步报告；本工作流不再产生 `epics.md`。
  - **复用已有目录**：仓库已有 goal 目录（含已收口目标、冻结历史材料）时，沿用同一结构、常规命名；
    其中的冻结历史文件**只读**，不得被改写，也不作当前 story 清单或编排状态。
- **goal ↔ initiative 绑定**：goal 目录**就是** initiative 根（`Docs/<goal-id>/`），goal 目录的
  `progress.md` 另记 `- Initiative: initiative-<slug>` 一行（`sources:` / `companions:` 引用用），
  Step 04 首次写定，其后所有步骤按它定位票树；`Step 01`～`03` 只读，不建票树。

## 宿主执行循环

1. 读 `Docs/current` 与 goal 目录的 `progress.md`，确定状态与下一步；已绑定 initiative
   时同时读 `tickets.py status <goal 目录>` 与 `next <goal 目录>`（story 事实只认脚本）。
2. 取**最小序号的未完成步骤**；Step 07 内按 `next` 的 `ready_to_start` 组批（尊重表序与 `after`）：声明齐全且七条件全过时成批并行，否则只取首行。
   把该步契约全文 + 输入产物路径（含 `find <ref>` 给出的 entry / epic 文件 / plan 路径）作为任务
   正文，用 `task_delegate` 开全新子会话执行；子会话默认视为只读执行环境，任务不得以其拥有
   `file_write`、`file_edit` 或目录创建能力为前提。
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
6. **epic 全部 entry 完成后自动跑收口链**：`tickets.py status <goal 目录>` 显示该 epic 全部 entry 都达
   `built` / `in-review` / `done` 即触发（**不要求本批含最后一条**——跨会话续跑、上一轮只差收口时同样触发；
   开工先看 `tickets/<E编号>-<slug>/` 下已有的 `-review-r1.md` / `-review-r2.md` / `-review-r3.md` 与
   `-retrospective.md`，已完成的轮次跳过）：三审（`R1` → 修 → `R2` → 修 → `R3` → 修）→ 回顾（含 `## 三审记录`）
   → 过「完成即自动提交」判据后 `git commit`（`<type>(<e编号>): <标题>，<E编号> 收口`）→ 交接块 →
   `tickets.py next` 取**下一个 epic** 的第一条 entry，或 `none（转 Step 08）`。整条链**自动执行、不呈报等人、
   不是审批门**；下一个 epic 的 `after` 未满足时按 `next` 的 `blocked[].waiting_on` 报告并停；缺报告、有未落改
   Critical/High、脚本非零退出即按显性失败停。

## epic 内并行批（parallel batch）

同 epic 内互不冲突的 entry 可以**成批并行**：宿主一次开多个子会话跑实现，批末由宿主**串行**收口门禁、
`mark`、提交与交接。默认仍是逐条串行——只有声明齐全且七条件全过才成批，任一不满足即 fail-closed 退回
逐条串行。

**声明（Step 06 写，可选）。** 要参与并行的 entry 在所属 epic 的 `tickets/tickets.toml` 里加两个键：

- `parallel_group`：非空组名，同组条目才可以成批；缺省 = 不参与并行，零开销；
- `write_set`：该 entry 会改的**全部**仓库相对路径（新建文件、测试文件、fixture 都要列），必须完备。

`tickets.py` 不读这两个键（不进 `status` / `find`），它们是本契约的门控输入：宿主直接读该 epic 的
`tickets.toml` 判定，不自行发明第三处声明。

**七条件**（全过才成批；成员按 `next` 的 `ready_to_start` 表序取相邻条目）。

- 同 epic、`parallel_group` 相同且非空——跨 epic 不成批（epic 是 `after` 与收口的边界）；
- 成员 `write_set` 非空、两两不相交（派生产物见「批级共享写集」）；
- 成员的 `after` 已全部交付，且**不依赖批内其他成员**（依赖并发中的 entry 不可证安全）；
- 成员都没有 `hitl` / `plan_checkpoint` / `done_checkpoint`——带门的一律单条串行走；
- 成员都没有 `unknown`、未裁决的核心 `Ask First` 与竞争方案；
- 批大小 ≤ 3（默认上限；用户点名更多最多 5，写集仍须两两不相交）；
- 宿主能让门禁串行跑：本仓源码树、容器 workspace 与设备腿都只有一份，**并行只发生在实现阶段**；
  做不到就退回串行。

**执行形态。**

1. 宿主用 `task_parallel` 一次开 N 个子会话，每条正文与该条单跑时逐字相同（entry 全文、epic 文件
   全文、`find` 的 plan 路径、`after` 所指 plan 的 Code Map / Design Notes / Plan Change Log），
   另加一句「本批并行、只准写 `write_set` 内的路径」；
2. 子会话返回后逐条核对产物；有写权限的子会话按各自 `write_set` 写盘，宿主批末跑一次
   `git status --porcelain` 做**写集审计**：出现「本批写集 ∪ 宿主自写产物」之外的 tracked 改动，
   该条判失败并**撤销本 epic 的并行授权**（此后一直串行到 epic 收口）；untracked 只记警告（夹具与新
   产物本就是未跟踪写入）；
3. 实现全部落盘后宿主**串行**跑门禁：先逐条跑各自 `## Verification`（批内共享的仓库四件套只跑一次），
   结果按 entry 分行写进 `progress.md` 与各自 plan；
4. 门禁不过只回退该条：`git checkout -- <该条 write_set 内的 tracked 路径>` 并删掉它新建的文件，其余
   条照常收口；同一条连续两轮仍失败即 `mark <ref> blocked`，按显性失败处理；
5. 逐条 `mark <status>`（各 plan 是不同文件，互不干扰），再按声明序**逐条提交**：每次 `git add` 只装该
   条的 `write_set` 与 plan，禁 `-A` / `.`。

**批级共享写集。** 派生文档与守卫基线天然被多条 entry 牵连（`Docs/aihome-client/framework.md` 的模块
规模表、`ChatViewModelSizeTest` 上限、注释与配色守卫）：它们**不算写集相交**，而是由宿主在批末按落盘
后的实测数字统一重算一次，作为批收尾提交（`docs(<e编号>): 批内派生文档重算`），实测值记 `progress.md`。

**批是一次 checkpoint 单元。** 带门成员不进批（七条件第 4 条），所以批内没有逐条等人的门；人工确认
按批一次，不按条拆。**交接点也从「每条 entry」改为「每批」**：批内不写交接块、不注册 cron；批末
（全部提交后）按「上下文交接与续跑」写一次，`- 本轮结论` 记整批，`- 下一条` 取下一批。

## epic 收口三审（epic review sweep）

**触发与自动性。** 触发条件 = 该 epic 全部 entry 都达到 `built` / `in-review` / `done`，只认
`tickets.py status <goal 目录>`——**不看「本批是否含最后一条」**（跨会话续跑、上一轮只差收口时，下一轮
一开工就补跑）。满足即**自动开跑：不呈报、不等确认、不是审批门**；这套流程幂等，开工先看
`tickets/<E编号>-<slug>/` 下已有哪些 `-review-rN.md` 与 `-retrospective.md`，已完成的轮次不重跑。

**三审前先换一次上下文。** epic 全部 entry 达标后，先按「完成即自动提交」提交这批 entry，再按
「上下文交接与续跑」写交接块，然后把三审交给**新会话**开跑（默认注册一次性 cron；用户自己接手时是
`/clear` + `/loop next`）——实现轮的上下文（试错过程、门禁输出、被否掉的方案）对评审只是噪声，带着
它审自己刚写完的代码，会系统性地漏掉「按意图该有而没有」这类缺口。三审链本身在新会话里**连跑到底**
（`R1` → 修 → `R2` → 修 → `R3` → 修 → 回顾 → 提交），中途不再换会话、不呈报、不等确认。

每个 epic 收口**必须做三次审查**，一次一轮、串行推进（上一轮的修复落盘后才开下一轮）：不是三次
同题重复，而是三个不同视角各查一遍。三份报告 + 回顾里的记录齐了，epic 才算收口；缺一份即未收口。

- **`R1` 规格与实现对账**（执行角色 `bmad-code-review`）：本 epic 全部改动 vs epic Requirements /
  `Done when` / 各 plan 的 `<frozen-after-approval>` 与 `## Verification`。查「实现是否真的交付了规格」
  与「验证结论是否有证据」，不做风格挑刺。发现按 Critical / High / Medium / Low 分档，逐条给
  `文件:行` + 当前行为 + 正确口径 + 谁守着。
- **`R2` 不变量与守卫反脆弱**（宿主自扫 + 反证）：查安全与不变量（凭据/明文/日志脱敏/错误分类/
  端点判定）、跨产物一致性（`framework.md` 数字与磁盘、活文档口径）、以及**守卫本身是否有牙**——
  至少对一条关键守卫做「注入一处违规 → 必须判红 → 复原 → 必须转绿」的反证（`CleartextCopyTest` /
  `ConfigSurfaceBoundaryTest` / `FrameworkNumbersTest` 这类源码扫描守卫尤其要验）。常量断言恒真、
  锚点随行尾或文案漂移、只看回执不看落盘，都记 Medium 以上。
- **`R3` 三镜头对抗式评审**（技能 `code_review`）：按该技能的三个镜头各跑一遍、独立成段记发现——
  **对抗式**（默认假设改动有问题，找「缺什么」而不是「错什么」，至少 10 条具体发现，提不出要说明理由）、
  **边界追踪**（沿真实调用链追空值/空集合/上限/超时/取消/重试/部分失败/顺序依赖/类型边界，每条问
  「会不会崩、会不会静默错、有没有测试」）、**验证缺口**（对照验收标准找「声称通过但没有证据」：
  只测 happy path、断言实现细节、改了实现没改测试、用覆盖率顶行为验证）。定级用该技能的
  high / medium / low（high = 必须修，等同 Critical），**不得**把 Critical 写成 Warning。
  `R1` 以规格与契约为轴、`R2` 以不变量与守卫为轴、`R3` 以「缺什么 + 边界 + 验证缺口」为轴：
  三者是并列镜头，重叠是信号，**不得**用其中一轮的结论顶替另外两轮。

**`R3` 的调用与 v7 适配**（技能正文按 v6 产物写的，落盘时按下面映射，别照 v6 路径找文件）：

- 调用：`skill_load code_review` → 按它在**本 goal 的 v7 面**执行——评审对象 = 本 epic 全部 entry 的
  plan（含 `## Verification`）+ epic 文件 + 合并 diff，**不采信**实现/测试报告与自验证结论，亲自读
  diff、亲自跑命令核对数字；不得把范围缩到单条 entry；
- 产物：报告落 `<E编号>-<slug>-review-r3.md`（不是技能原文的 `review-report.md`），frontmatter 记
  `review_loop_iteration`；延期项落 goal 的 `brief.md`「延期项」段（不是 `deferred-work.md`）；
- **不改** `epics.md` / epic Requirements / plan 的冻结段（v7 下 epic Requirements 同样冻结；`bad_spec`
  发现走 `mark <ref> blocked` + 回 Step 04/06 重切，不在评审里改规格）；
- 回环上限：同一 epic 内「回到实现重新推导」累计 5 次即停并升级给人；
- 技能不可用（`skill_load code_review` 失败）时按 gap 处置：交接块「未关闭的门」写 `R3 未执行（gap：
  code_review 技能不可用）` + 记 `brief.md`「延期项」，**不**伪造结论、**不**拿 `bmad-code-review`
  顶替 R3（那是 R1 的镜头）；`/loop auto` 下登记完继续收口，不停等人。

**产物与落点。** 三份报告落 epic 文件夹：`tickets/<E编号>-<slug>/<E编号>-<slug>-review-r1.md`、
`…-review-r2.md`、`…-review-r3.md`；每份含 `## 范围`（改动的文件面与判据来源、本轮用的技能名）、`## 发现`
（分档表：严重度 / 位置 / 现象 / 处置）、`## 结论`（通过 / 有条件的通过 / 未执行（gap））。
`<E编号>-<slug>-retrospective.md` 必须带 `## 三审记录` 段，逐轮一行写明轮次、结论、发现计数与
落改去向；`progress.md` 决策日志追加一行（三轮结论 + Critical/High 的落改或 `blocked` 处置）。

**发现怎么处置。** Critical / High：当轮落改并重跑受影响门禁，改不动就 `mark <ref> blocked --blocked <原因>`
按显性失败停；Medium / Low：进延期项（`brief.md`「延期项」）或对应 plan 的评审记录，**不**在本轮扩范围。
三审的发现**一律不得**只写在对话里：至少落到一份报告或 plan，否则视为未审。

**与收口、提交的顺序。** `R1` → 修 → `R2` → 修 → `R3` → 修 → 回顾（`<E编号>-<slug>-retrospective.md`，
含 `## 三审记录`）→ 「完成即自动提交」的判据 → 提交 → 交接 → `tickets.py next` 取**下一个 epic**。
有未落改的 Critical/High 时按显性失败停，不进入提交。

## 完成即自动提交（completion commit）

「做完了」不等于「已落盘」：完成判据一过就**自动 `git commit`**，不再逐轮征询（`CLAUDE.md` 的「提交与汇报」
把 `/loop` 通过完成判据列为唯一允许自动提交的场景，其余场景仍先呈报）。顺序固定为**先提交、再交接、后换会话**，
交接块里的「本轮结论」才对得上 HEAD。

- **触发点**：一批 entry 全部置 `built` 之后（串行时即单条）；epic 则由全部 entry 达到 `built` 后**自动开跑
  三审**，**三审报告（`R1`/`R2`/`R3`）与回顾报告（含 `## 三审记录`）都落盘之后**提交（epic 收口的提交必须有
  这三份报告；缺一份不提交，改为按显性失败停并报告缺口）。提交后不停：写交接块，再用 `tickets.py next` 转下一个 epic。
- **提交前必过的判据**（缺一项就**不提交**，把缺口写进交接块）：plan `status` 已是 `built`；plan 的
  `## Verification` 有本轮实测命令与结果；`progress.md` 记了结论（失败轮次同样记）；epic 末条另有
  `<E编号>-<slug>-review-r1.md`、`-review-r2.md`、`-review-r3.md` 与带 `## 三审记录` 的
  `<E编号>-<slug>-retrospective.md`；动过 Android 代码时 `:app:testDebugUnitTest` 与 `:app:lintDebug` 通过。
- **提交信息**：中文 Conventional Commit；entry 用 `<type>(<e编号>-s<mm>): <标题>`（scope 小写，如
  `feat(e13-s01): …`），epic 收口用 `<type>(<e编号>): <标题>，<E编号> 收口`；一次提交只装一条 entry 及其配合产物，
  文档与源码同批，不跨 entry 混装；并行批按声明序逐条提交（写集互不相交，可安全逐条 `git add`）。
- **只暂存本批显式文件**：逐条 `git add <path>`，**禁止** `git add -A` / `git add .`；工作树里别人的未提交改动
  只列出、不碰、不 stash；提交后 `git show --stat HEAD` 复核装进的文件与预期一致。
- **不 `git push`**、不改写历史；提交被钩子拦截或冲突时按显性失败处理：如实报告并停，不带病交接。
- **用户当轮说了「先呈报 / 别提交」**：以用户为准，本轮不提交，把待提交清单写进交接块留给下一轮。

## 上下文交接与续跑（context handoff）

一条 entry 的实现细节（改过的文件、试错过程、门禁输出）只对那条 entry 有用；留在对话里，后面的
entry 反而读不到真正需要的上下文。所以**完成一批 entry（串行时即一条）与完成一个 epic 都是交接点，不是停止点**：
plan 置 `built`（或 epic 收口回顾落盘）之后，先按「完成即自动提交」提交，再写交接块，再继续。

**交接块**：覆盖写活动 goal 的 `progress.md` 的 `## 交接块（下一轮入口）`（不是追加，历史留决策日志），
五项缺一不可：

- `- 下一条：<ref> <E编号>-S<mm>（<epic slug>）`——取 `tickets.py next` 的下一批（串行时即 `ready_to_start` 首行）；
  没有可开工的 entry 写 `- 下一条：none（转 Step 08）`；
- `- 票树实测：counts {…} / problems 空 / longest_remaining_chain …`——现测抄录，不凭记忆；
- `- 必读：<plan 路径> · <epic 文件> · <epic 回顾>`——下一轮真正要读的文件清单；
- `- 未关闭的门：<审批门 / checkpoint / 待用户裁决项>`——没有就写 `无`；
- `- 本轮结论：<一两行>`——只留影响后续 entry 的事实（新增守卫、接口改动、门禁新基线），不复述过程。

**交接后一律换新会话（默认自动）**：agent **不能**调用客户端的 `/clear`（那是输入框里的斜杠命令，
工具集里没有等价能力），所以「清空 context」在本契约里的落法是**注册一次性 cron job**——job 触发即新会话，
等价于 clear 后自动开工：

- **换会话的时点**：每条 entry 完成之后，以及每个 epic **开跑三审之前**——`R1`–`R3` 与回顾之间不换会话，
  三审要一口气跑完。entry 之间换会话是甩掉试错噪声，三审前那次换会话是让评审从零读 diff。
- **默认**（`next` / `run` / `auto` 下的每条 entry 与每个 epic 收口开跑三审之前）：写完交接块立刻注册一次性 cron，
  `recurring: false`、`schedule` 用 `* * * * *`（下一个整分钟触发），prompt 只写
  「读 `Docs/current` 指向 goal 的 `## 交接块` 与 `tickets.py next`，继续 Step 07」，不带本次对话内容；
  注册完即收官本轮，回复里写明 job 与「下一轮入口」。
- **cron 不做的事（如实说）**：它只把下一轮交给新的执行入口，**不保证清空当前这轮对话的 context**；
  真正的 context 清零只有两条——用户在输入框敲 `/clear`，或另开新会话。所以注册 cron 之后，
  回复里必须同时给出「想立刻清零就 `/clear` + `/loop next`，并先删掉这个 job」。
- **注册前先 `cron_list`**：已有同 prompt 的 loop job 就复用、不重复注册；同一条交接只留一个 job。
- **不该注册**（这些门之后没人接手只会空转，按人工续跑收官，并删掉遗留 loop job）：下一条是
  `hitl` / `plan_checkpoint` / `done_checkpoint`、Step 08 放行前、显性失败、需要用户裁决、Step 02 交互轮待用户回复。
- **用户接手**（说「我来 / 先别自动」）：写完交接块收官，提示「新会话继续：`/loop next`」；
  用户自己 `/clear` + `/loop next` 与 cron 等价——此时先 `cron_remove` 已注册的 loop job，
  避免两条会话同时推进（一次只跑一批，见「并行纪律」）。

**纪律**：交接块是唯一跨会话载体（不依赖上一会话记忆，也不得为保住上下文而不写）；交接不改变状态机
（不提前写 `done`、不跳过 plan 推进与 `## Verification` 实测）；「下一条」与 `tickets.py next` 现测不一致时
以脚本为准并就地改正；每轮开工先按 `next` 校准 `progress.md` 头部的「当前步骤」行。

## 审批门与 checkpoint（v7 口径）

- **Step 02 交互轮不是审批门**：它只收敛方向、不产需批准的产物，停下只为拿用户输入；用户回一句就继续，不需要 `approve`。
- **规划审批**：Step 04（epic 拆分）与 Step 06（epic 细化 + story 拆分）产出核对通过后，宿主停下
  向用户展示产出并请求确认；`approve` / `reject <原因>` / `amend <补充>` 三种处置。用户的一「yes」
  同时是**提交票树**的授权（仓库纪律：中文 Conventional Commit，先呈报提交信息与文件清单再执行）。
- **条目级 checkpoint**：entry 上的 `hitl`（需要人操作）、`plan_checkpoint`（计划先由人看）、
  `done_checkpoint`（`built` 后等人放行）由 Step 07 逐条执行，未置位时不要额外加门。
- **最终放行**：Step 08 报告核对通过后停下；`approve` 才把 entry 逐条 `mark <ref> done`、把 goal
  状态置 `done`，并在决策日志记答复原文。`done` 是人的决定，自动 job 永远不写。
- **用户一句话即放行**：用户以「继续 / 推进 / 按默认值 / `approve`」之类简短表态回应呈报时，视为对**已呈报
  推荐项**的确认与该门的放行——按契约执行（Step 08 则逐条 `mark done` + 状态置 `done`），并把答复原文记入
  决策日志。用户未表态时停在门前，`done` 永不自行写。

- **并行纪律**：默认逐条串行；只有声明齐全（`parallel_group` + `write_set`）且「七条件」全过才成批并行
  （见「epic 内并行批」），任一不满足即 fail-closed 退回串行。`after` 仍只用于核对顺序合法：任何
  entry 的依赖必须由构建顺序更靠前的 entry 或 epic 交付。
- **显性失败**：状态文件缺失或损坏、脚本非零退出、同一子会话任务连续两次失败时，宿主如实报告并停
  （状态置 blocked），不猜测、不伪造进度、不静默跳步。

## 只读文档审查

`review [step]` 是独立于 8 步的只读动作，不是工作流步骤：无参数审查当前 goal 全部状态与产物，
可限定 `step-01`…`step-08`、某个 epic / `ref` 或具体 entry。审查范围至少包括：

- `current` 指针、`progress.md` 状态与产物存在性、`- Initiative:` 行指向的票树是否一致；
- 各步骤必需章节、审批门、输入/输出引用是否完整；
- `tickets.py status` / `next` 的 `problems` / `unpinned_after` / `undeclared_after` / `order_conflict` /
  `drift` 是否为空，plan `status` 与 `progress.md` 的记载是否一致；
- epic 的 `refined`、`covers` 指向的 `R<n>`、entry 的 `after` 是否都由更早的工作交付；
- 是否越过审批门、越过分批纪律（写集相交仍成批、越集写未撤销授权）、改动冻结段、留悬空引用或跨产物矛盾，是否把 `unknown` / `blocked` 当作可构建；
- 报告中的测试、性能、硬件与验证结论是否有证据，是否把计划命令写成已执行结果。

纪律：只读（必要的检查命令由宿主执行），不委派实现型子会话，不改任何文件、状态、审批记录或勾选，
不推进步骤；每条发现给位置、证据、严重度（Critical/High/Medium/Low）与建议处置；`review` 是 goal
文档/状态审查，不等于代码评审——代码评审走「epic 收口三审」：`R1` = `bmad-code-review`（规格与契约轴）、
`R2` = 不变量与守卫反脆弱（含注入反证）、`R3` = 技能 `code_review` 的三镜头（对抗 / 边界 / 验证缺口）。

## cron 自动推进

`auto [cron]` 用 cron 工具注册一个按表达式触发的 job，其 prompt 固定为以下模板（`auto off` 注销
prompt 以「推进 goal」开头的 job）：

> 推进 goal：读 `Docs/current` 指向 goal 的 progress.md、brief.md 与 `- Initiative:` 行，
> 跑 `tickets.py next <goal 目录>`，用 `bmad-build-auto` 构建 `ready_to_start` 的并行批（批内一条 entry 一个子会话；不成批时只取首行）。
> 遇到 `hitl` / `plan_checkpoint` / `done_checkpoint` / `blocked` / `unknown` 时不要推进，原样报告
> 等待项；任何情况下都不要把 entry `mark done`。

无人值守也按同一组批规则：写集相交、带 checkpoint 或需人操作时一律退回逐条串行。无人值守的边界：`bmad-build-auto` 不提问，任何不明确一律在 plan 里记 `blocked` + 原因后停；它需要
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
Step 01 的唯一写操作是把初步分析结论写回 `brief.md`；Step 02 的交互轮只写
`step-02-brainstorm-options/report.md` 与 `.heagent/tmp/` 下的 memlog，不改变这条只读边界；
Step 04 是**规划步骤的入口**：产出 PRD 与
epic 拆分（信封 + `[[epic]]` + 薄 epic 文件），只规划不实现。Step 06 是**规划步骤**：细化 epic、
把范围拆成 entry、排定构建顺序、关闭所有核心方案决策；它只规划，不实现。Step 07 是**逐 entry 的
重任务步骤**：在单个子会话内完成一条 entry 的计划、实现、测试与评审，并且是唯一允许创建实现产物、
唯一允许新增或修改测试文件的步骤。Step 08 是**全系统最终验收步骤**：只在全部 entry 完成后运行一次。

Step 07 按各 epic `tickets.toml` 的**表序**、在 `after` 允许的范围内推进：默认**串行**，声明齐全且
七条件全过的相邻 entry 成批**并行**（见「epic 内并行批」），一个子会话仍只处理一条 entry。该 epic 全部
entry 完成后**自动**跑**Epic 收口**（三审 + 回顾 `<E编号>-<slug>-retrospective.md` + 自动提交 + 转下一个
epic，见该步正文与「epic 收口三审」）；未满足触发条件时不要额外做事。v7 已取消 sprint 概念：需要分批
推进时用 `after` 与 `hitl` 表达，不再引入 sprint 表或「Sprint 收口」。

**产物位置**：规划产物在 initiative（PRD `prd-<slug>/`、架构 `architecture-<slug>/`、epic 文件、
`tickets.toml`、plan、`<E编号>-<slug>-retrospective.md`，延期项在 `brief.md`「延期项」段）；循环报告在
`Docs/<goal-id>/step-NN-*/`。任何改动代码的步骤都必须重跑受影响的测试，并写明确切命令
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
- **交互**：默认**与用户交互**（见本节「交互轮」）；`/loop auto`、cron 触发或用户当轮说「你自己定」
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
  此后**不注册 cron**（无人接手只会空转）：用户回复即在同一会话继续，或新会话 `/loop next` 读该段续跑
  ——已答就进下一轮，未答就原样重报问题，不重开一轮。

**退化（不交互）路径。** `/loop auto`、cron 触发，或用户当轮说「你自己定 / 不用问我」时不走交互轮：按
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
- 产出：已验证 PRD（`Docs/<goal-id>/prd-<slug>/prd-<slug>.md`）、信封段并入
  `Docs/<goal-id>/brief.md`、epic 拆分（`Docs/<goal-id>/tickets/tickets.toml` 的
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
- 产出：架构 spine（`Docs/<goal-id>/architecture-<slug>/architecture-<slug>.md`，决策带稳定 id 并
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

**并行声明（可选）。** 计划在 Step 07 与同 epic 其他 entry 并行构建的条目，在该 entry 上加
`parallel_group`（非空组名）与 `write_set`（该 entry 会改的仓库相对路径全清单，含新建文件与测试文件）；
不写的 entry 一律串行、零开销。`tickets.py` 不读这两个键（不进 `status`），它们是 `/loop` 的组批门控
输入，判定规则见「epic 内并行批」。

**不要**为 entry 预写 leaf 文件（`story.md`）：只有评审、细化或发布时才 `tickets.py pull <epic 目录> <entry id>`。
**不要**引入 sprint：v7 已取消 sprint，构建顺序只由表序与 `after` 决定；需要可演示切片时，在
`## Story 拆分` 里说明每条 epic 收口可演示什么。

**排序与树检查。** 表序即执行顺序：宿主按 epic 表序推进，epic 内按表序组批（默认逐条串行、可成批并行），所以按将构建
的顺序写，不留空号、不重复编号。收尾跑 `tickets.py status <goal 目录>`，把 `problems` 提到的问题
逐条修掉再提交审批。

把完整计划作为最终回复返回，必须含两个显式章节：`## Epic 细化`（每个 epic 的 Requirements、Outcome
与 `Done when` 回读结论、遗留决策）与 `## Story 拆分`（逐 entry 清单及其 `verify`、`after`、`risk`、
checkpoint）。**缺任一章即未通过验收核对。**

禁止：实现改动；重新规划 initiative 或 epic 边界（那属于 Step 04 的重切）；写 `epics.md` 或
`sprint-status.yaml`；产出有空号、重复 id 或与表序矛盾的 entry 清单；写出无法验证的
`verify`；留下 `unknown` 未裁决；手写 leaf 文件。

## Step 07: implement-story（实现故事）

- 执行角色：`bmad-build`（人在场）／`bmad-build-auto`（`/loop auto` 无人值守）
- 输入：`tickets.py find <goal 目录> <ref>` 给出的 entry（或其 leaf 文件）、epic 文件、plan 路径、brief.md
- 产出（每条 entry）：plan 文件（路径取 `find` 的 `plan`，与 `tickets.toml` 同级），frontmatter 的
  `status` 沿 `draft → ready-for-dev → in-progress → in-review → built` 推进；该 epic 全部 entry 完成后
  追加 `<E编号>-<slug>-retrospective.md`
- 验收核对（每条 entry）：plan 含 `## Tasks & Acceptance`、`## Verification` 与实现/评审结论；宿主
  亲自跑完 `## Verification` 的记录命令且结果写入 progress.md；无遗留 Critical 发现
- **产物形态**：每条 entry 只产 **plan**（临时证据可按需落
  `Docs/<goal-id>/step-07-implement-story/<ref>/notes.md`），**不再产**旧口径的 `story.md` /
  `implementation.md` / `test-report.md` / `verify-report.md`；命令进 plan 的 `## Verification`，
  结果与结论进 `progress.md`。该 epic 全部 entry 完成后另产 `<E编号>-<slug>-retrospective.md`。

`bmad-build` 是本步骤的实现、测试与评审方法论来源（计划模板在 `.heagent/skills/bmad-build/plan-template.md`，
上游安装源同名文件在 `.claude/skills/bmad-build/`）。
**按批执行（默认串行）**：声明齐全且七条件全过的相邻 entry 成批并行（见「epic 内并行批」）；每个子会话只处理一条 entry，按表序取 `tickets.py next <goal 目录>` 的
`ready_to_start`（整批按声明序，或仅首行），或按用户点名的 `<ref>`；宿主在任务正文里给出该 entry 全文、epic 文件全文、
`find` 返回的 plan 路径与 `brief.md` 路径，并附上 `after` 所指 entry 的 plan 中 Code Map /
Design Notes / Plan Change Log 作为连续性上下文。开始前必须核对：该 entry 无 `unknown`、无未裁决
的核心 `Ask First`、无竞争方案；发现即 `mark <ref> blocked --blocked <原因>`，停止并报告。

**状态与证据。** plan 的 `ticket` 必须等于 entry 的 `id`；`baseline_revision` 必须是改动前从版本
控制直接取得的完整规范 id。状态只经 `tickets.py mark <goal 目录> <ref> <status>` 推进，不手改 frontmatter。

**checkpoint。** `plan_checkpoint` → 计划完成后停下（`bmad-build-auto` 用「Halt after planning」停在
`ready-for-dev`），宿主呈报计划等人放行；`hitl` → 需要人操作的环节由宿主暂停并说明；`done_checkpoint`
→ `built` 后停下等人放行。没人要求的门不要自行加。

**Epic 收口。** 该 epic 全部 entry 达到 `built`/`in-review`/`done` 时**自动开跑**（判定只认 `tickets.py status`，
不以「本批含最后一条」为前提；开工先按报告存在性跳过已完成的轮次）：先按「epic 收口三审」跑
**`R1` → 修 → `R2` → 修 → `R3` → 修** 三轮审查（`R1` 即 `bmad-code-review` 的对抗式评审；build 内跑过
thorough 也**不**能省掉这一轮），三份报告落 epic 文件夹；再用 `bmad-retrospective` 产出
`<E编号>-<slug>-retrospective.md` 并在其中写 `## 三审记录`；本步发现的**不属于任何 entry** 的真实问题按
`source_plan` / `summary` / `evidence` 追加到 goal 的 `brief.md`「延期项」段，不要顺手扩范围。
收口产物落盘后**不停、不等确认**：过「完成即自动提交」的判据即提交本次 epic 收口（`<type>(<e编号>): <标题>，
`<E编号> 收口`；三份报告缺一份不提交，按显性失败停），再按「上下文交接与续跑」写交接块，然后用
`tickets.py next <goal 目录>` 取**下一个 epic** 的第一条 entry（没有则 `none（转 Step 08）`）继续。
三审期间不提交、不写 `done`；有未落改的 Critical/High 时按显性失败停。

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
4. 经用户重新审批后，`mark <ref> ready-for-dev`（或 `in-progress`）才恢复实现。

不得通过修改 `tickets.toml`、放宽 `verify`、手改 epic Requirements 或在开发对话中口头选型来绕过审批。

## Step 08: system-integration-test（系统集成及测试）

- 执行角色：`bmad-qa-generate-e2e-tests`
- 输入：全部 entry 的 plan（Verification、Auto Run Result、评审发现）、epic 的 `Done when`、
  架构 spine、`tickets.py status` 的现状
- 产出：系统集成报告（`step-08-system-integration-test/report.md`，逐 epic 报告落
  `Docs/<goal-id>/tickets/<E编号>-<slug>/<E编号>-<slug>-integration-report.md`）
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
