---
name: workflow
entrypoint: goal
on_create: persist_goal_identity
step_executor: subagent
required_resources: prompt-template.md, gate-template.md
checkpoint_mode: auto
open_question_mode: default
max_rounds: 10
auto_schedule: "*/15 * * * *"
open_question_default: "有竞争性解释需要干系人拍板时，按推荐默认值推进并显式记录该假设；不要以 waiting_user 收尾。"
open_question_block: "有竞争性解释需要干系人拍板时，以 waiting_user 停下来等用户裁决。"
---

# development workflow（开发工作流）

本文件是声明式 `/goal` 工作流的**完整可执行契约**。CLI 读取本文件、持久化 `on_create` 声明的
goal 身份，并为每个声明步骤调用一个**全新**的 SubAgent 会话；已完成的步骤记入 goal checkpoint
store，任何步骤都不得跳过。

本工作流产出的**持久性非代码产物**（需求、PRD、架构记录、评审、验证报告等）一律写入项目输出
根 `_he-output/` 之下；源代码仍留在仓库既有位置。全部正文与产物使用中文。

## 全局标准

**就绪标准（Ready for Development）**——一份 story 计划同时满足以下六条才算就绪：

- **可执行**：每个任务都有明确文件路径与具体动作；
- **有序**：任务按依赖排序；
- **可测**：验收标准全部可验证（行为类用 Given/When/Then，非行为类用同等可判定的形式）；
- **完整**：没有占位符、TBD 或悬空引用；
- **充分**：没有未解决的已知需求、验收、依赖或实现缺口；
- **自洽**：没有未消解的歧义或内部矛盾。

**范围标准（Scope Standard）**——一条 story 只面向**单一用户可见目标**。多目标指 ≥2 个**顶层
独立可交付物**：各自可被独立评审、测试、合并且互不破坏；不要把同一目标内部的跨层实现细节拆开。
规模建议 900–1600 token 量级：低于 900 易歧义，高于 1600 易让实现会话上下文腐化。**两条都不是
硬闸门**，是需要用户裁决的建议。

**冻结契约（frozen-after-approval）**——`02-epics.md` 里每条 story 的验收标准一经 step 06 写出
即**冻结**：只有人能改，agent 在后续任何步骤中都不得改写验收标准去迁就实现。实现或评审中发现
标准本身有缺陷，按 step 07 的 Epic 收口评审分诊规则（`bad_spec` → 改实现、不改规格）处置，
不得就地改标准。

## 步骤纪律

Step 01 与 step 02 是**只读**步骤（市场调研与发散构思），不得修改项目实现产物；step 01 的唯一写操作
是把初步分析结论写回 goal 目录的 `require.md`（见该步骤正文）。Step 06 是**规划
步骤**：把已验证范围拆成 story、排定工作项顺序、把每条 story 归入恰好一个 sprint，并固定每条
story 的验收标准；它只规划，不实现。Step 07 是**逐 story 的重任务步骤**：单个会话内完成一条
story 的实现、测试与验证，并且是唯一允许创建实现产物、唯一允许新增或修改测试文件的步骤。

Step 07 按 `02-epics.md` 的 `### S-N` 顺序执行；默认每次增量只处理一条 Story，声明并行上限后可在同一 Epic 内批量处理，并在两个收口
点上追加动作：**Sprint 收口**（当前 story 是该 Sprint 最后一条时，跑该 Sprint 的可演示切片并核对
退出准则）与 **Epic 收口评审**（当前 story 是该 Epic 最后一条时，对本 Epic 的全部 story 做一次
对抗式代码评审）；不命中边界时不要额外做事。

Step 08 是**全系统最终验收步骤**：只在全部 story 完成后运行一次，把各 Epic 合起来做系统集成与测试
（逐 Epic 集成场景 + 跨 Epic 端到端 + 全量质量门禁），并给出系统级放行结论。它只能为修复自己报出
的 Critical 集成缺陷而改代码。

**产物按 Epic 分目录**：Epic 在 `02-epics.md` 里以 `## E<N> — <标题>` 分段，story 用 `### S-N`
标题归在所属 Epic 段内；story 级产物落在 `step-07-implement-story/epic-<eN>/s-<n>/`（`E1` →
`epic-e1`），Epic 级报告落在同一 `epic-<eN>/` 目录下。任何改动代码的步骤都必须重跑受影响的测试，
并写明确切命令与结果。

每个步骤的执行方法都由 `role:` 指名的 `.heagent/skills/<role>/SKILL.md` 提供。本文件只维护
步骤顺序、输入输出、检查点、产物位置和工作流特有的边界。

## Step 01: market-research（市场调研）
role: bmad-agent-analyst
input: user intent, existing project context
output: 市场综述, 决策驱动因素, 证据缺口
checkpoint: true
validation: section: 需求总结; 每条论断都带来源、发布日期与访问日期；缺失的证据一律报为 gap

调研与本目标相关的市场、竞品、替代方案与用户声音证据。以 **headless** 方式工作：不问候、不提问、
不等待用户。

**初步分析：先把需求写清楚。** 这是整个工作流的第一次初步分析，也是唯一允许写入 goal 目录需求文档
的步骤。用 `file_read` 读 goal 目录下的 `require.md`（prompt 里的 `Goal directory` 就是 goal 目录），
然后按顺序收口：

1. `## 原始需求（Original Request）` 段是用户原话，**逐字冻结**——只读，不得改写、删减或美化；
2. 把初步分析后的**总结的需求**写进同一文档的 `## 总结的需求（Derived Requirements）` 段：用
   `file_edit` 覆盖那段占位文本（必要时用 `file_write` 重写整份文档，但必须逐字保留原始需求段）。
   写成明确、可验证、无内部矛盾的需求陈述：区分事实与假设、标出仍未解决的开放问题，且不得引入
   用户原话里没有的产品承诺。这是初步理解而非最终 PRD——范围收敛与 Epic 拆分留给后续步骤；
3. 在最终回复里给出 `## 需求总结` 章节，内容与写入 `require.md` 的「总结的需求」一致。

用 `web_fetch` 抓取你被给出的、或你能推导出的 URL；本环境没有网页搜索工具，因此未解问题一律记为
**gap**，不得用训练数据「补上」。无法举证的论断必须写成未经验证的假设或开放 gap；公开数据稀薄时
如实报「稀薄」。

交付物：市场综述（细分市场、竞品、替代方案、定价与定位证据）、本目标真正依赖的**决策驱动因素**，
以及一份显式的**证据缺口清单**（每个缺口附上能补齐它的来源或查询）。把完整综述作为最终回复返回。

## Step 02: brainstorm-options（发散构思）
role: bmad-brainstorming
input: user intent, 市场综述
output: 选项空间, 排序候选方向
checkpoint: true
validation: 至少三条实质性不同的方向，每条都带风险与仍需的证据

围绕目标与市场综述主持一次构思会。以 **「ideate for me」** 立场 headless 工作：不问候、不打开
composer 页面、不等待用户，且**绝不以 waiting_user 收尾**。越过显而易见的答案，至少切换两次技法，
然后收敛成一份排序短名单。

把会话 memlog 放在 `.heagent/tmp/brainstorm-<goal-id>/` 下；它是草稿态，不是持久产物。交付物：
选项空间、带权衡的排序短名单，以及每个方向各自承担的风险与仍需的证据。把完整会话输出作为最终回复
返回。

## Step 03: analyze-requirements（需求分析）
role: bmad-agent-analyst
input: user intent, 市场综述, 选项空间, existing project context
output: 需求简报, 故事拆分
checkpoint: true
validation: 需求有证据支撑且可验证

分析意图，区分事实与假设，识别干系人，产出带验收标准的**需求简报**与 story 粒度的工作拆分。当仍
存在互相竞争的解释时，停下来等用户输入。

## Step 04: define-product-scope（产品范围定义）
role: bmad-agent-pm
input: 需求简报, 市场综述
output: 已验证 PRD, 有序 Epic 提案
checkpoint: true
validation: 产品价值、范围、非目标与决策都是显式的

把需求简报变成**已验证 PRD** 与**有序 Epic 提案**。记录假设、优先级、非目标与未决的产品决策。按
价值与依赖排序 Epic，并在 Epic 层级描述每个 Epic 的目标与范围。**不要在这里拆 story**：逐 story 的
拆分（`### S-1 ...`）在 step 06 架构确定之后进行。把 PRD 与有序 Epic 提案作为最终回复返回。

## Step 05: design-architecture（架构设计）
role: bmad-agent-architect
input: 已验证 PRD
output: 架构, 实现约束
checkpoint: true
validation: 边界、接口、依赖、不变量与失败处理都是显式的

产出精简的技术架构与决策记录。保持模块归属清晰，并记录安全、可靠性、迁移与验证路径。

## Step 06: refine-stories（故事细化）
role: bmad-agent-analyst
input: 已验证 PRD, 有序 Epic 提案, 架构, 实现约束
output: 澄清的实现范围, 迭代计划, 故事拆分
checkpoint: true
validation: section: Story 拆分; section: Sprint 计划; 范围被拆成从 S-1 起按执行顺序连续编号的 story 列表，每条 story 单一目标、验收标准完整、按依赖排序、恰好归属一个 sprint、且归在恰好一个 `## E<N> — <标题>` Epic 段落之下（段内 story 编号连续）

这是**规划步骤**：把已验证范围变成「sprint 细化、依赖有序、验收标准固定」的 story backlog。它的
四项交付物是 story 拆分、sprint 细化、工作项顺序与验收标准。**本步骤不实现任何改动。**

确认本次要改的东西，检视相关上下文，把工作细分成 story。

读取已验证 PRD 与有序 Epic 提案，再读架构及其实现约束。确认改动仍是 PRD 所要求的内容，把范围歧义
收敛成**单一目标**。Epic 层拆分已在 step 04 定下：不要重新规划 Epic。

**Epic 段落与编号。** story 按 Epic 分段：每个 Epic 一段，段标题固定为 `## E<N> — <标题>`（`N`
从 1 起连续，与 step 04 的有序 Epic 提案同序同号），该 Epic 的全部 story 列在这一段内。同一 Epic
的 story 编号必须**连续**（例如 E1 拥有 S-1..S-5，E2 从 S-6 起）：story 归属只由所在 Epic 段落与
`父 Epic` 字段决定，step 07 依此把每条 story 的产物写进对应的 `epic-<eN>/` 目录。

**拆分 story。** 每条 story 用且仅用一个 `### S-1 <标题>` 标题：该标题形式就是 step 07 逐 story
执行的 story 清单（step 08 也读同一文件确认 Epic 顺序），因此保持清单干净——不要用项目符号、表格
或额外装饰。每条 story 必须包含：

- **父 Epic / 优先级 / 依赖**：父 Epic 写 Epic 引用（如 `E1`），优先级写 P0/P1/P2，依赖写 story id 或 none；
- **验收标准**：可验证的 Given/When/Then 条件，或对非行为类标准使用同等可判定的形式；
- **定义完成（DoD）**；
- **代码地图（Code Map）**：与该 story 相关的文件、符号/行锚点、可复用点与只读约束，让人和后续
  步骤不必盲搜代码；
- **边界与约束**：`必须（Always）` / `需先问（Ask First）` / `禁止（Never）` 三层；
- **I/O 与边界矩阵**：当该 story 有有意义的输入/状态场景时给出（场景 / 输入或状态 / 期望输出或
  行为 / 错误处理）；没有有意义的 I/O 场景就**整节删除**，不要写 N/A；
- **验证方式**：确认自己工作的命令或人工检查项；
- **规模说明**：证明它装得进一次「实现—测试—验证」会话。

一条 story 是单一目标、可独立构建、可测试、可验证的，并且完成后仓库仍是可工作的。

**排序工作项。** story 编号就是执行顺序：runner 读取 `### S-N` 清单并严格按数字后缀执行，因此按
将构建的顺序编成 S-1..S-N，不留空号、不重复编号。先依赖后价值：任何 story 都不得依赖更靠后的
story，且你声明的每个依赖要么已存在，要么由编号更小的 story 交付。

**细化 sprint。** 把有序 story 编入 sprint——以「结束时可演示」为界的短增量。每个 sprint 写明目标、
包含的 story、进入准则、退出准则、关闭时可演示的端到端切片，以及它退掉的风险。sprint 成员必须与
story 编号**连续且单调**：sprint 1 放编号最小的 story，sprint 2 接着放，依此类推，因为执行顺序严格
按数字。每条 story 恰好属于一个 sprint，sprint 合起来覆盖全部 story。

把结果写入 goal 目录下的 `02-epics.md`：先按 Epic 分段（`## E<N> — <标题>` 段落，段内为规范的
`### S-N <标题>` story 清单），然后是 `## Sprint 计划` 一节。`02-epics.md` 是后续所有步骤的 story
清单**唯一真源**；step 07 与 step 08 只读不改。**不要**写 `_bmad-output/sprint-status.yaml`：它是
历史规划状态记录，保持只读。

把完整计划作为最终回复返回，必须含两个显式章节：`## Story 拆分`（澄清后的范围，加逐 story 清单及
其验收标准与 DoD）与 `## Sprint 计划`（每个 sprint 的目标、story 集合、进入准则、退出准则与可演示
切片）。**缺任一章即阻塞本步骤。**

禁止：实现改动；重新规划 Epic；产出有空号、重复编号或与执行顺序矛盾的 story 清单；写出无法验证的
验收标准；留下没有 sprint 的 story、没有退出准则的 sprint，或跨越非连续编号的 sprint；写入
`_bmad-output/sprint-status.yaml`。

## Step 07: implement-story（实现故事）
role: bmad-build
input: 澄清的实现范围, 架构
output: 故事实现, 故事定义, 故事测试证据, 故事验证报告
checkpoint: true
story_loop: 02-epics.md
max_parallel_stories: 3
max_iterations: 100
validation: section: 实现摘要; section: 测试证据; section: 验证结论; 本条 story 在这一个步骤内完成实现、测试与验证，且记录下确切命令及其结果

`bmad-build` 是本步骤的实现、测试与验证方法论来源。默认每次只注入一条 Story；当
`max_parallel_stories > 1` 时，仅在同一个 Epic 内以批次方式并发执行，跨 Epic 严格串行，单条失败不取消
同批其他 Story。只实现当前 Story，不得修改冻结的 `02-epics.md`。Story 产物必须写入
`_he-output/goals/<goal-id>/step-07-implement-story/epic-<eN>/s-<n>/`：`story.md`、
`implementation.md`、`test-report.md` 与 `verify-report.md`；CLI 保存该次步骤输出为同目录的
`report.md`。命中 Sprint 或 Epic 的最后一条 Story 时，按 BMad 方法完成相应收口，并将证据写入报告。

**验证工作区约定。** 需要临时副本或夹具（例如变异测试）时，请在工作区内创建并读写：用 `file_write` / `file_read` 操作 `.heagent/tmp/<goal-id>-verify/` 下的文件。**不要**用 shell 把项目拷到 `%TEMP%` 等工作区外的路径（会被工作区路径围栏拦下）。要跑脚本就落盘成文件再执行——内联 `python -c` / `node -e` 单行脚本难以审查与复跑，落盘脚本才可审计、可重放（含危险关键词的内联载荷仍会被整条命令扫描拦下，但良性内联命令本身不禁）。被拦下的命令不产生任何结果，只会白耗迭代预算：本步骤预算已声明为 step 级 `max_iterations: 100`（原子大 Story 不易撞全局 `GOAL_MAX_ITERATIONS` 上限），其验证子代理另受 `SUBAGENT_MAX_ITERATIONS` 约束。

## Step 08: system-integration-test（系统集成及测试）
role: bmad-qa-generate-e2e-tests
input: 故事验证报告, 故事实现, 故事测试证据, 架构, 已验证 PRD
output: 评审报告, 系统集成报告
checkpoint: true
validation: section: 评审发现; section: 质量门禁; section: 系统集成结论; 逐 Epic 集成场景与跨 Epic 端到端场景都记录确切命令与观察结果，且不存在未决 Critical

`bmad-qa-generate-e2e-tests` 是本步骤的集成与端到端测试方法论来源。全部 Story 完成后只执行一次：
逐 Epic 验证跨 Story 集成场景，并验证跨 Epic 主路径、失败路径与恢复路径。逐 Epic 报告写入
`step-08-system-integration-test/epic-<eN>/integration-report.md`；顶层报告给出质量门禁、未决
Critical 与系统级结论。只允许修复本步骤发现的 Critical 集成缺陷；`02-epics.md` 保持只读。
