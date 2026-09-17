# 当前敏捷工作流

本文只描述当前代码已经支持的声明式 `/goal` 工作流。可执行契约的唯一来源是项目内的
[`.heagent/workflows/workflow.md`](../.heagent/workflows/workflow.md)；本文是面向维护者的导航和边界说明，不复制那份契约。

## 权威关系

| 内容 | 唯一权威 | 代码职责 |
| --- | --- | --- |
| 工作流步骤、角色、输入输出、检查点 | `.heagent/workflows/workflow.md` | 读取、解析、校验并按声明执行 |
| 步骤方法论 | 每个步骤均由 `role:` 指向 `.heagent/skills/*/SKILL.md` | 把声明和上下文交给 SubAgent |
| Goal 身份与工作流产物 | `_he-output/goals/<goal-id>/` | 创建目录、保存输出、恢复 checkpoint |
| Goal/Epic/Story 结构契约 | `src/heagent/engine/artifacts.py` 与 `.heagent/workflows/templates/` | 解析和校验结构 |
| 运行时进度与恢复 | `<goal-dir>/checkpoints/` 下的 `workflow.json` | 保存状态，不取代规划看板 |
| 全仓库 Epic/Story 状态 | `_bmad-output/sprint-status.yaml` | 规划历史的状态记录；不是 `/goal` 运行时状态 |

**`sprint-status.yaml` 的写权限**：`_bmad-output/sprint-status.yaml` 是规划历史的状态记录，仓库内**只读**。
`/goal` 的步骤 06 在正文与 `Never` 列表里明令不得写入；`bmad-build`（显式调用时）本会经
`sync-sprint-status.md` 推进 Story 状态（`in-progress` → `review`）并把父 Epic 从 `backlog` 抬起，
本项目已在 `_bmad/custom/bmad-build.toml` 用一条 `persistent_facts` 覆盖该子步骤，使它同样跳过写入
（删除该文件即可恢复 bmad-build 的同步行为）。`src/` 下没有任何代码读写该文件；
`validate_sprint_status_path()` 只做「状态校验必须指向这一个权威文件」的校验。

代码不应重新实现一套 Epic/Story 方法论。新增阶段、角色、产物或验收规则时，优先修改
`workflow.md` 或对应 Skill；只有新增确定性执行机制时才修改 Python。

## 当前步骤

项目默认工作流目前包含八步：

1. `market-research`：由 `bmad-agent-analyst` 产出市场、竞品、替代方案与用户证据摘要，以及决策驱动和证据缺口（只读、headless）。
2. `brainstorm-options`：由 `bmad-brainstorming` 以 headless「ideate for me」立场发散并收敛出候选方向排序（只读）。
3. `analyze-requirements`：分析需求并产出可验证的需求与初步 story-sized 拆分（正式 Story 清单由 step 06 产出）。
4. `define-product-scope`：形成 PRD 和有序 Epic 提案（Epic 级，不做 Story 拆分）。
5. `design-architecture`：形成架构、边界、约束和决策记录。
6. `refine-stories`：**规划步骤**——确认实现范围，拆分 Story，细化 Sprint（每个 Sprint 的目标、Story 集合、进入/退出准则、可演示切片与退掉的风险），排定工作项先后（Story 编号即执行顺序），并固定每个 Story 的验收标准与 DoD；写入 `02-epics.md` 的 `## E<N>` 分段 + `### S-N` 清单 + `## Sprint 计划`，不改实现代码。
7. `implement-story`：由 `bmad-build` 执行的**重任务步骤**（`story_loop: 02-epics.md`）。每次只实现一个 Story，并产出实现、测试与验证证据；它是唯一创建实现产物、唯一新增或修改测试文件的步骤。
8. `system-integration-test`：由 `bmad-qa-generate-e2e-tests` 执行的**全系统最终验收步骤**，只在全部 Story 完成后运行一次，覆盖逐 Epic 集成与跨 Epic 端到端测试，并给出质量门禁结论。

**写权限边界**：步骤 01–02 只读；步骤 06 只写规划产物（`02-epics.md`），不改代码；步骤 07 是唯一
创建实现产物、唯一新增或修改测试文件的步骤（实现、测试、验证三阶段都在这一步内完成；Sprint 收口
与 Epic 收口评审也在这一步的边界增量内完成，评审只可为修复自己报告的 Critical 与规格偏离改代码）；
步骤 08 只做最小集成修复，不重新设计实现。任何改代码的步骤都必须重跑受影响测试并写明确切命令与
结果。这条边界由步骤正文声明，代码不做强制校验。

**验证工作区约定**：步骤 07/08 需要临时副本或夹具（如变异测试）时，在工作区内的`.heagent/tmp/<goal-id>-verify/` 下用 `file_write` / `file_read` 构造与回滚；不要用 shell 把项目拷到 `%TEMP%` 等工作区外路径（会被工作区路径围栏拦下），也不要写 `python -c` / `node -e` 内联单行脚本（会被 `SafetyGuard` 判为危险命令）——要跑脚本就落盘成文件再执行。被拦命令不产生结果，只会白耗迭代预算（步骤 07 用 `GOAL_MAX_ITERATIONS`，其验证子代理用 `SUBAGENT_MAX_ITERATIONS`）。

## 敏捷环节与机械保证

「每个 Story 都有开发、测试、验证」「每个 Sprint 都有退出验证」「每个 Epic 都有集成测试」不是正文里的口号，而是由声明和运行时
校验共同约束的：

| 敏捷环节 | 工作流体现 | 机械保证 |
| --- | --- | --- |
| Story 拆分 + Sprint 计划 | 步骤 06（规划步骤，只写 `02-epics.md`） | `validation` 强制输出含 `## Story 拆分` 与 `## Sprint 计划` 两个章节；Story 编号从 S-1 连续且即执行顺序（`parse_story_list` 按编号后缀排序），Sprint 成员须与编号连续单调，Story 须归在 `## E<N> — <标题>` Epic 段内且段内编号连续 |
| Story 开发 + 测试 + 验证 | 步骤 07（`story_loop`，重任务） | 每 Story 独立 checkpoint；`validation` 一次强制三个章节：`## 实现摘要` / `## 测试证据` / `## 验证结论`，缺一即 BLOCKED |
| Sprint 退出验证 | 步骤 07（该 Sprint 最后一条 Story 的增量内） | 步骤正文要求跑该 Sprint 的可演示切片、核对进入与退出准则，并把结果写进该增量的 `## 收口结论` |
| Epic 收口评审（代码评审） | 步骤 07（该 Epic 最后一条 Story 的增量内） | 评审范围是整条 Epic（不是单条 Story）；报告落 `epic-<eN>/review-report.md`，含 `## 评审发现` 与 frontmatter `review_loop_iteration`（>5 即 HALT）；`## 评审发现` / `## 收口结论` 由步骤正文要求返回（非 `section:` 门禁，因 `section:` 门禁按 Story 逐条校验，无法只对收口增量生效） |
| Epic 集成测试 + 系统集成测试 | 步骤 08（全部 Story 完成之后，只运行一次） | `validation` 强制输出含 `## 评审发现` / `## 质量门禁` / `## 系统集成结论` 三个章节，缺一即 BLOCKED；逐 Epic 子报告 `epic-<eN>/integration-report.md` + 顶层索引 |

`validation` 里的 `section: <标题>` 由 `WorkflowRunner._validate_output` 机械校验：输出缺少该 Markdown
标题即判为 BLOCKED，不会静默推进。唯一解析入口是 `required_sections()`（`engine/workflow_runner.py`）；
`_goal_declarative_prompt` 会在派发步骤**之前**把同一批标题写进 prompt 的 "Gate requirements" 段（并声明
标题须独占一行、不得改后缀），使执行者动手前就知道自己会被哪些标题判定——门禁本身仍然只在步骤返回后
机械校验，不因 prompt 提示而放宽。所有步骤均由 `role:` 指向相应的
`.heagent/skills/<role>/SKILL.md`。

这些步骤不是 Python 中的固定状态机。`WorkflowRunner` 只负责顺序、输入缺失、输出结果、checkpoint
和恢复；`cli_goal.py` 负责确定性装配和 SubAgent 调用。

## 运行方式

```text
/goal <目标>       创建目标并执行 workflow.md 的第一步
/goal new <目标>   显式创建目标
/goal next         推进一个声明步骤或一条 Story
/goal run          连续推进，遇到 checkpoint/阻塞即停止
/goal status       查看当前状态和产物
/goal pause        保存并暂停
/goal resume       记录用户回复并继续
/goal auto [cron]  注册 cron 自动推进
/goal reset        清除 current 指针但保留目标目录
```

每个步骤或 Story 都启动新的 SubAgent/RunContext。上下文窗口重置、ledger 幂等、PolicyEngine、工具
执行和 OS 沙箱属于运行机制；它们不决定 Epic/Story 如何拆分。

## 产物布局

```text
_he-output/goals/<goal-id>/
├── GOAL.md                              # Goal 身份和原始需求
├── 02-epics.md                          # 由 step 06 写入的 Epic/Story 清单（## E<N> 分段 + ### S-N，编号即执行顺序）+ ## Sprint 计划
├── step-01-market-research.md           # 市场调研摘要与证据缺口
├── step-02-brainstorm-options.md        # 头脑风暴与候选方向
├── step-03-...md                        # 其余非 Story 步骤输出
├── step-07-implement-story/
│   ├── index.md                         # 顶层索引（最后一条 Story 之后写：Epic 总览 + 逐 Story 表格）
│   └── epic-e1/                         # 按 Epic 分组（E1 -> epic-e1）
│       ├── review-report.md             # Epic 收口评审报告（该 Epic 最后一条 Story 的增量内写）
│       └── s-1/
│           ├── story.md                 # 该 Story 的验收契约（逐字定义）
│           ├── implementation.md        # 改动清单与决策
│           ├── test-report.md           # 测试证据（验收标准到测试的映射、命令与结果）
│           ├── verify-report.md         # 自验证判定（逐条验收标准的证据）
│           └── report.md                # CLI 写入的步骤输出（含三个强制章节）
├── step-08-system-integration-test.md   # 系统集成与测试报告（含三个强制章节）
├── step-08-system-integration-test/
│   └── epic-e1/integration-report.md    # 每个 Epic 的集成测试报告（全部 Story 之后）
└── checkpoints/                         # WorkflowRunner 运行时 checkpoint
```

`.heagent/workflows/templates/` 提供 Goal、Epic、Story 的结构模板。历史规划、验收和 retrospective
仍归档在 `_bmad-output/`，不应被当作当前运行时配置。

## 修改工作流的规则

- 变更流程顺序或阶段职责：修改 `.heagent/workflows/workflow.md`。
- 新增或重排步骤：在 `workflow.md` 加 `## Step NN: name` 区块，`NN` 必须从 1 连续递增；每个步骤的
  `role:` 必须指向已安装的 `.heagent/skills/<role>/SKILL.md`——指向不存在的包会在执行到该步骤时硬失败
  （不是降级）；
  `input:` 的每个引用必须是 CLI 注入键（`user intent` / `user responses` / `existing project context`）
  或前序步骤 `output:` 声明的名字，否则该步骤会被判为 BLOCKED。
- Story 编号就是执行顺序：`parse_story_list` 按 `S-<n>` 后缀排序，因此 `02-epics.md` 的 Story 编号必须从
  S-1 连续、无重复，Sprint 成员必须与编号连续单调；否则 Sprint 划分与实际执行顺序错位。步骤 07 读取该
  文件，不得修改。
- Epic 段落与编号：`02-epics.md` 里每个 Epic 用 `## E<N> — <标题>` 段（`N` 从 1 连续、与有序 Epic 提案
  同序同号），该 Epic 的 Story 用 `### S-N` 全部列在这一段内且编号连续。Story 归属只由所在 Epic 段落与
  Story 块内的 `父 Epic` 字段（后者优先）决定，它同时决定产物目录名 `epic-<eN>/`；交叉或错号会让分组
  静默错位。
- 声明 `story_loop: <artifact>` 的步骤会按该产物里的 Story 列表逐条展开，每条 Story 独立 checkpoint；
  产物落到 `<goal-dir>/step-NN-<slug>/epic-<eN>/s-<n>/report.md`（`parse_story_list` 归一化 Epic 引用为
  `E<N>`，无 Epic 分组的产物退化为 `<goal-dir>/step-NN-<slug>/s-<n>/report.md`）。未声明 `story_loop`
  的步骤只运行一次，需要按 Epic 分片时由步骤正文要求逐 Epic 产出子报告（如步骤 08）。
- 收口动作不是独立步骤：Sprint 收口与 Epic 收口评审由步骤 07 的正文按「当前 Story 是否落在边界上」
  判定并执行，因为它们共享 Story 循环的会话与 checkpoint。`section:` 门禁按每条 Story 逐次校验，无法
  只对收口增量生效，故这两个章节靠步骤正文要求 + 步骤 08 复核。
- 重任务步骤可用 `max_iterations: <1..1000>` 覆盖该步骤的 SubAgent 迭代预算（缺省继承
  `Settings.goal_max_iterations`）；原子大 Story 建议显式放宽，撞上限会让整步/整批以 `failed` 收场。
- 遗留项台账由 bmad-build 模板写入 `_bmad-output/implementation-artifacts/deferred-work-archive.md`（goal 内的
  Epic 级台账落在 `_he-output/goals/<goal-id>/step-*/…/deferred-work.md`）；`/deferred` 是它的 reader，
  会列出全部台账的条目数与最新条目。
- 需要机械保证的验收证据，用 `validation: section: <标题>; <说明>` 声明——`WorkflowRunner` 会校验输出
  是否包含该 `## <标题>`（必须是独占一行、无后缀的 `## 标题`；`## 标题（S-1）` 照样判缺失）。这些标题会由
  `_goal_declarative_prompt` 先注入步骤 prompt 的 "Gate requirements" 段，执行者无需猜测门禁标题。不要在
  `validation` 里使用 `given` 一词，除非确实要求输出符合 Given/When/Then 格式。
- 变更角色执行方法：修改 `role:` 指向的 `.heagent/skills/<skill>/SKILL.md`；`workflow.md` 仅维护步骤
  的声明、边界与产物约束。
- 变更产物字段或父子关系：同步修改 `engine/artifacts.py`、模板和测试。
- 变更恢复、checkpoint、路径安全或工具执行：修改 `src/heagent/` 机制代码，并同步 `docs/frame.md`。
- 重排已有步骤编号会让存量未完成 goal 的 checkpoint 索引错位；改动前先确认没有活跃 goal 指针。
- 不要在 `cli_goal.py` 增加与 `workflow.md` 平行的业务流程分支。
