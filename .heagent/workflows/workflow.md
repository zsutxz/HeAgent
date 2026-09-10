---
name: workflow
entrypoint: goal
on_create: persist_goal_identity
step_executor: subagent
checkpoint_mode: auto
open_question_mode: default
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

Step 01 与 step 02 是**只读**步骤（市场调研与发散构思），不得修改项目实现产物。Step 06 是**规划
步骤**：把已验证范围拆成 story、排定工作项顺序、把每条 story 归入恰好一个 sprint，并固定每条
story 的验收标准；它只规划，不实现。Step 07 是**逐 story 的重任务步骤**：单个会话内完成一条
story 的实现、测试与验证，并且是唯一允许创建实现产物、唯一允许新增或修改测试文件的步骤。

Step 07 按 `02-epics.md` 的 `### S-N` 顺序逐 story 执行，每次增量只处理一条 story，并在两个收口
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

Step 07 与 step 08 的**角色契约内联在本文件中**：它们不声明 `role:`，也不依赖任何外部 skill 包。
其余步骤把方法论委派给 `role:` 指名的 `.heagent/skills/<role>/SKILL.md`。

## Step 01: market-research（市场调研）
role: bmad-agent-analyst
input: user intent, existing project context
output: 市场综述, 决策驱动因素, 证据缺口
checkpoint: true
validation: 每条论断都带来源、发布日期与访问日期；缺失的证据一律报为 gap

调研与本目标相关的市场、竞品、替代方案与用户声音证据。以 **headless** 方式工作：不问候、不提问、
不等待用户。

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
input: 澄清的实现范围, 架构
output: 故事实现, 故事定义, 故事测试证据, 故事验证报告
checkpoint: true
story_loop: 02-epics.md
validation: section: 实现摘要; section: 测试证据; section: 验证结论; 本条 story 在这一个步骤内完成实现、测试与验证，且记录下确切命令及其结果

这是**逐 story 的重任务步骤**：一个会话内实现当前 story、拥有它的测试，并按它自己的验收契约完成
验证。它是唯一允许创建实现产物、唯一允许新增或修改测试文件的步骤。它还在所属 Sprint / Epic 的
收口增量里承担 Sprint 退出验证与 **Epic 级代码评审**；全系统的集成与测试留给 step 08。

每次增量**只实现一条 story**：由 CLI 注入的当前 story。不要实现其他 story，也不要提前构建后续
story。

**产物目录（按 Epic 分组）**：本步骤的产物写入
`_he-output/goals/<goal-id>/step-07-implement-story/epic-<eN>/s-<n>/`——`<eN>` 是当前 story 在
`02-epics.md` 中的父 Epic 引用小写（`E1` → `epic-e1`），`<n>` 是 story 编号。CLI 已把本增量的
`report.md` 写入该目录；`story.md`、`implementation.md`、`test-report.md`、`verify-report.md`
必须写在同一目录下。若 `02-epics.md` 没有 Epic 分段（既无 `## E<N>` 段也无 `父 Epic` 字段），退化
为 `step-07-implement-story/s-<n>/`。

**立场**：你是这一条 story 的实现者、测试者与第一验证者。三个阶段都不可选、也不可互相合并——没有
你亲自产出的证据的阶段等于不存在，被你跳过的阶段是本步骤的**失败**而不是捷径。

**冻结契约**：先按 `02-epics.md` **逐字**写出当前 story 的定义——id、标题、父 Epic、sprint、
优先级、依赖、验收标准与 DoD——到 `step-07-implement-story/epic-<eN>/s-<n>/story.md`，并补上代码地图、边界与
约束（必须 / 需先问 / 禁止）、I/O 与边界矩阵（若有）、验证方式。它是后续每个阶段、每个步骤读取的
**验收契约**，因此不得与 `02-epics.md` 漂移。写出后即**冻结**：只有人能改，你不得在本步骤内改写
验收标准。若 `02-epics.md` 缺少上述某节，由你依据 PRD、架构与代码库补齐，并在该节标注 `derived`；
不得因缺节停工，也不得凭空发明需求。

Phase 1 — 实现。按架构与已验证 PRD 构建改动。保持最小、遵循既有模块边界与约定，并让仓库保持可
导入、可静态检查。把改动文件、你做出的决策、以及未能完成的部分写入
`step-07-implement-story/epic-<eN>/s-<n>/implementation.md`。

Phase 2 — 测试。把 `story.md` 的每条验收标准映射到至少一个**实际执行过的**测试，并覆盖这些标准
隐含的边界、空值、错误、重试与权限路径，同时覆盖 DoD。在仓库既有测试目录下、按既有框架/命名/
fixture 约定新增或扩展测试；**不得为了让测试通过而改产品代码**。先跑本 story 的聚焦测试，再跑
相关回归套件，并为每次运行记录**确切命令行与观察到的结果**——计数、失败数，以及任何失败输出。
**永远不要**削弱、跳过或删除既有断言来换取绿色；若既有测试本身有错，说明理由并记录。若
`story.md` 含 I/O 与边界矩阵，逐行核对每个矩阵行都有至少一个覆盖其期望行为的测试，且该测试**实际
跑过并通过**：存在但未运行（未注册、被过滤、跳过、禁用）算缺失；测试与矩阵冲突时**永远改代码，
不改期望**；矩阵行本身有歧义时停下问人。把标准到测试的映射、命令及其结果、以及残余覆盖缺口写入
`step-07-implement-story/epic-<eN>/s-<n>/test-report.md`。

Phase 3 — 验证。重读实际 diff 与你刚写的测试文件，**自己**重跑命令，并逐条判定每条验收标准为
通过 / 不通过 / 无法验证，并给出具体证据：命令输出、文件与行号，或观察到的行为。同时判定 DoD、
确认改动没有越出 story 范围，并检查该 story 本不打算改动的行为是否出现回归。**无法举证的验收标准
判为不通过，不是「假定通过」。** 发现 Critical 缺陷时施加最小修复、重跑受影响测试并记录。把逐条
判定表（标准 / 判定 / 证据）、你重跑的命令与残余风险写入
`step-07-implement-story/epic-<eN>/s-<n>/verify-report.md`。

**Phase 4 — 收口（仅当本增量命中边界时执行）**

先判定本增量是否落在边界上：读 `02-epics.md`，找出当前 story 所属的 Sprint 与 Epic——若它是该
Sprint 的最后一条 story，执行 **Sprint 收口**；若它是该 Epic 的最后一条 story，执行 **Epic 收口
评审**。两者可以同时命中，都不可省略；不命中边界时不要臆造收口动作。

**Sprint 收口**：跑该 Sprint 的可演示切片、核对进入与退出准则，把结果记入 `## 收口结论`。退出准则
不通过是本增量的 Critical 缺陷。

**Epic 收口评审**：对本 Epic 的**全部 story** 做一次对抗式代码评审——这是本工作流的代码评审关口，
step 08 不再逐 story 评审。评审报告写入本步骤目录下的 `epic-<eN>/review-report.md`，必须含
`## 评审发现` 章节与 frontmatter `review_loop_iteration`（缺省 0）。评审契约如下：

- **立场**：你是对抗式评审者，不是自己前几个阶段的辩护人。实现报告、测试报告与自验证判定都是
  **待核验的主张**；结论只能来自你亲自读过的合并 diff 和你亲自跑过的命令。评审与实现同处一个会话，
  因此必须把它当作**事后审计**：先切换立场、从合并 diff 与重跑命令出发，不得采信自己先前写下的结论。
- **三个镜头**（各自独立成段记录）：①**对抗式**——找「缺什么」而不只是「错什么」，默认这份改动有
  问题再去证明它；关注未处理的分支、静默吞掉的异常、被绕过的校验、假设了却未验证的前提、并发与
  重入、资源释放、错误路径的日志与返回值、被删掉的守卫、新增的隐式耦合。②**边界追踪**——沿真实
  调用链追踪，而不是只读 diff 片段（空值 / 空集合 / 单元素 / 上限 / 超时 / 取消 / 重试 / 部分失败 /
  顺序依赖 / 类型边界 `0`、`-1`、`None`、`""`、极大值）；每条边界问三件事：会不会崩、会不会静默
  错、有没有测试。③**验证缺口**——对照验收标准找「声称通过但没有证据」的地方：断言只覆盖 happy
  path、断言实现细节而非可观察行为、改了实现却没改对应测试、测试被跳过 / 削弱 / 删除、用覆盖率数字
  替代行为验证。
- **定级前先读代码**：打开每条发现所在的源码、调用点与守卫，不得只看 diff hunk 定级。
- **分诊（按顺序执行）**：①**去重**——只合并「同一主张且同一所需动作」的发现，其余逐条独立评估，
  不得因为某条相关发现被驳回就驳回另一条；②**定级**——按对**最终消费者**的后果定级（`high` 不可容忍＝Critical、
  必须修复 / `medium` 可容忍 / `low` 无影响或仅观感），**忽略**你自己前几阶段给出的等级；③**归类**
  （每条恰好一类）——`intent_gap`（本改动引起、但意图不完整无法消解；除非只有唯一读法，不要推断
  意图）/ `bad_spec`（本改动直接偏离规格；在它和 `patch` 之间犹豫时优先 `bad_spec`）/ `patch`
  （无需人工输入即可琐碎修复）/ `defer`（非本 Epic 引起的既有问题；在它和 `reject` 之间犹豫时优先
  `reject`）/ `reject`（噪声，静默丢弃）；④**处置**——`intent_gap` 标 `blocked` 交人裁决，不要猜；
  `bad_spec` **不要改 `02-epics.md`**，施加使实现与规格一致的最小修复并写一条规格缺陷记录（触发
  发现、应改的规格条目、避免的已知坏态、KEEP 指令）；`patch` 就地修复并重跑受影响测试；`defer`
  向 `deferred-work.md` **追加**一条（`source_spec` / `summary` / `evidence`，不改既有条目、不查
  重）；`reject` 静默丢弃。
- **删除检查**：若合并 diff 删除了有意义的代码，确认被删除的行为或契约要么已被重新建立，要么被
  有意退役。
- **只做最小修复**：Critical 就地最小修复并重跑受影响测试；跨 Epic 的回归可以记录，但除非是
  Critical，留给拥有它的 story。
- **回环上限**：每发生一次「需回到实现阶段重新推导」的情形，把 `review-report.md` frontmatter 的
  `review_loop_iteration` 加一；超过 **5** 即 HALT 升级给人。

把完整的逐 story 报告作为最终回复返回，必须含三个显式章节：`## 实现摘要`（改动文件、如何触发
改动、残余风险）、`## 测试证据`（标准到测试映射、确切命令及结果、覆盖缺口）与 `## 验证结论`（逐条
判定表与总体结论）。**缺任一章即阻塞本步骤。** 命中收口边界时**再追加** `## 评审发现`（该 Epic
的发现、严重度与处置）与 `## 收口结论`（Sprint / Epic 的退出判定与证据）。这两个章节是正文要求
而非 `section:` 门禁——`section:` 门禁按每条 story 逐次校验，无法只对收口增量生效——因此 step 08
会复核它们是否存在且自洽。

禁止：在没有产生结果的那条命令的情况下宣称某阶段通过；改写验收标准去匹配已实现的代码；把失败
测试报成警告、把跳过测试报成通过；未重跑命令就宣称自己的工作已验证；实现另一条 story、扩大
story 范围；跳过收口增量（Sprint / Epic 边界）的验证或评审；把收口评审写成对自己前几阶段结论的复述；
对 Epic 收口评审报出的 Critical 不做最小修复就放行；修改 `02-epics.md`。

最后一条 story 完成后，写出本步骤顶层文档 `step-07-implement-story/index.md` 作为索引：逐 Epic
总览（Epic / 包含的 story / 收口评审结论 / 是否有未决 Critical）+ 逐 story 表格（story / 所属
Epic / 改动文件 / 通过标准数 / 结论），链接每个 `epic-<eN>/s-<n>/` 下的 `story.md`、
`implementation.md`、`test-report.md`、`verify-report.md` 以及 `epic-<eN>/review-report.md`，
然后同步更新 `GOAL.md` 的 Epics 段。`GOAL.md` 只管 Epic；story 状态活在逐
story 产物里，`02-epics.md` 在 step 06 写出后保持只读。

## Step 08: system-integration-test（系统集成及测试）
input: 故事验证报告, 故事实现, 故事测试证据, 架构, 已验证 PRD
output: 评审报告, 系统集成报告
checkpoint: true
validation: section: 评审发现; section: 质量门禁; section: 系统集成结论; 逐 Epic 集成场景与跨 Epic 端到端场景都记录确切命令与观察结果，且不存在未决 Critical

这是**全系统最终验收步骤**，只运行一次（不按 story、也不按 Epic 展开各自的检查点）：全部 story
实现完毕、每个 Epic 都通过收口评审之后，把各 Epic 合起来当作一个系统来验证。它不重新设计实现，
只做最小修复，并给出系统级放行结论。

**前置核对（逐 Epic，按 `02-epics.md` 的 Epic 出现顺序）**：核对进入证据——
`step-07-implement-story/epic-<eN>/s-<n>/` 下的 `story.md`、`implementation.md`、
`test-report.md`、`verify-report.md`，以及 `epic-<eN>/review-report.md` 的 `## 评审发现`；并确认
没有未解决的 Critical 发现。缺产物或存在未决 Critical 发现即该 Epic **失败**——如实报告，不要绕过
继续。

**逐 Epic 集成**：为每个 Epic 设计并运行**只有该 Epic 的 story 合起来时才成立**的集成场景：跨
story 流程、模块边界、真实入口（CLI / API / 公开接口）以及穿过它们的数据。优先端到端执行已交付
代码，而不是重复测 story 内部。把每个 Epic 的报告写入本步骤目录下的
`epic-<eN>/integration-report.md`。

**系统级集成与测试**：跨 Epic 端到端——把全部 Epic 合起来，按真实用户旅程跑通主路径，并至少覆盖
失败路径、边界输入与中断 / 恢复路径。凡「各 Epic 单独通过、合起来才暴露」的问题都属于本步骤的
发现；优先真实入口而非单元级重测。

**质量门禁**：跑全量测试套件与项目质量门禁（lint、format、类型检查）。记录**确切命令与观察到的
结果**（计数、失败数、失败输出），不得只写「通过」。

**Critical 处置**：出现 Critical 集成缺陷时施加最小修复、重跑受影响测试、重跑相关集成场景，并记为
「在 step 08 修复；集成已重跑」。不要重新设计实现，也不要为了拿到绿色结论而削弱场景或门禁。

**判定与索引**：逐 Epic 给 pass / fail 与证据，再给系统级总体结论、未覆盖的场景与残余风险；
**不要把失败软化成警告**。写出本步骤顶层文档作为索引：逐 story 表（story / 各严重度发现数 / 处置
状态）+ 逐 Epic 表（Epic / story / 集成场景 / 结论）+ 系统级门禁结果，并更新 `GOAL.md` 的 Epics
段以反映评审与集成结论。`GOAL.md` 只管 Epic，`02-epics.md` 全程只读。

把完整报告作为最终回复返回，必须含三个显式章节：`## 评审发现`（逐 Epic 集成与系统级测试中发现的
问题，带严重度、证据与处置）、`## 质量门禁`（确切命令与观察到的结果）与 `## 系统集成结论`（逐
Epic 结论 + 系统级判定 + 未覆盖场景与残余风险）。**缺任一章即阻塞本步骤。**

禁止：不重跑命令就采信 step 07 的报告；因为各 story、各 Epic 单独通过就宣称系统已集成；跳过某个
Epic，或在第一个失败的 Epic 之后就停下而不报告其余 Epic；把未测的路径当作通过；为了拿到绿色结论
而削弱场景或门禁；修改 `02-epics.md`。
