# /loop 契约 · 票树与目录

> 本文件是 `workflow.md` 拆出的章节，与它同属流程真源；章节归属见 `workflow.md` 的「文件地图」。

## 票树接口（BMAD v7）

工具统一前缀：`python .heagent/skills/bmad-agent-po/scripts/tickets.py`（脚本需要 PyYAML；环境无 `uv`
时直接用装了 PyYAML 的解释器跑，不要写 `uv run`）。**BMad 配置与脚本住 `_bmad/`，但票树不读
它们**：`find_project_root()` 只认「含 `_bmad/` 的目录」、`central_config()` 只读
`_bmad/scripts/config_utils.py`，这两条默认路径在按本契约布局的仓库里不成立，因此**每条命令都必须带显式目录**
——`locate_dir()` 在 `folder.is_dir()` 为真时把 `root` 置 `None`、`bases` 置空，整条 config 分支不执行。
别加 `--project-root`，别指望 `active_initiative` 自动选树。

- **布局**：goal 目录本身就是 initiative 根（`docs/<goal-id>/`）：
  - `docs/<goal-id>/brief.md`——需求真源兼信封：原始需求（冻结）+ Requirements（`R<n>` 稳定 id）、
    Constraints、`Done when`、Boundaries、延期项、决策记录；**不产**独立 `initiative-<slug>.md`；
  - `docs/<goal-id>/tickets/tickets.toml`——`[[epic]]` 表，**表顺序即构建顺序**；
  - `docs/<goal-id>/tickets/<E编号>-<slug>/<E编号>-<slug>.md`——epic 文件；薄 epic 带
    `refined: false`（只同意边界、尚未细化），细化后写 Requirements 并置 `refined: true`；
  - `docs/<goal-id>/tickets/<E编号>-<slug>/tickets/tickets.toml`——该 epic 的 `[[entry]]`
    （`type` = story / spike / bug），同样表顺序即构建顺序；
  - plan——`tickets.py find <goal 目录> <ref>` 返回的绝对路径 `plan`（与 `tickets.toml` 同级，如
    `story-<ref>-…-plan.md`），**plan frontmatter 的 `status` 是 story 状态的唯一真源**；
  - epic 收口——回顾报告 `<E编号>-<slug>-retrospective.md` 落 epic 文件夹；跨 story 延期项写
    goal 的 `brief.md`「延期项」段（记 `source_plan` / `summary` / `evidence`），**不产** `deferred-work.md`。
- **命令**（`<init>` = `docs/<goal-id>`，`<epic-dir>` = `<init>/tickets/<E编号>-<slug>`）：
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
  **角色正文里的脚本调用**：一律走 `python _bmad/scripts/<name>.py`（`resolve_config` /
  `resolve_customization` / `memlog` / `render_skill`，需 python ≥3.11）；`uv run …` 换成 `python …`，
  `{output_folder}` = `docs`、`{active_initiative}` = goal 目录名。
- **自检**：`python .heagent/skills/loop/scripts/selfcheck.py` 在隔离目录里跑一遍
  `new-goal` → Step04 → Step06 → Step07（mark/find/pull/move），断言 17 项；退出码 0 = 全通。
  改动票树工具、契约或模板后先跑它，再谈推进。
- **清单真源**：一条 epic 的 story 清单只有它的 `tickets/tickets.toml`（表序即执行序）；plan 与
  leaf 文件是逐条产物，不是清单。
- **三条禁令**：状态一律经 `mark` 写，不手改 plan frontmatter；已批准的 entry 与 epic
  Requirements 不手改（要改走重切）；`id` / `ref` / plan 路径一律取脚本输出，不自行发明。

## 状态与目录约定

- **根目录**：`docs/`；goal 目录直接位于其下（`docs/<goal-id>/`）。旧 `/goal` 的 `_he-output/goals/`
  与之完全隔离、互不读写；`docs/` 同时是 mkdocs 的 `docs_dir`，`tests/test_docs_links.py` 会校验其中全部 `*.md` 的相对链接与锚点：goal 产物里的链接必须指向真实存在的文件。
- **current 指针**：`docs/current` 写当前 goal 目录相对 `docs/` 的路径（新文档根如 `push-inbox`；同一文档根下按代分目录如
  `aihome-client/goal-3`）（`reset` 只删指针、保留目录；无活动 goal 时不存在）。
  指针目录必须有 `tickets/` 票树，否则 `status` / `next` 只读出一棵空树。
- **起跑**：`python .heagent/skills/loop/scripts/new-goal.py <goal-id> --title <标题> [--request <用户原话>]` 建骨架（`brief.md` / `progress.md` / `tickets/tickets.toml` / `docs/current`），只建骨架不写 Requirements 与 entry；`--root <DIR>` 供空跑验证，`--no-current` 不写指针。
- **goal 目录**：`docs/<goal-id>/`（`<goal-id>` 为英文 slug，冲突时追加 `-a`/`-b`…）：
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
- **goal ↔ initiative 绑定**：goal 目录**就是** initiative 根（`docs/<goal-id>/`），goal 目录的
  `progress.md` 另记 `- Initiative: initiative-<slug>` 一行（`sources:` / `companions:` 引用用），
  Step 04 首次写定，其后所有步骤按它定位票树；`Step 01`～`03` 只读，不建票树。
