# Epic 52 产品简报：goal 工作流安全并行 Story 执行器

- 建立：2026-10-09
- 状态：规划完成，未开工
- 编号：Epic 52
- 周期目录：`_bmad-output/epics/epic-52-安全并行story执行周期/`
- 上游：Epic 51（51-8 交付声明面与 fail-closed 串行，把「可验证的隔离执行器」递延为本 Epic）、
  Epic 47-9（历史批次实现，因无可验证写隔离于 ddf39bd 删除）
- 方案事实源：`docs/goal-workflow.md`、`docs/frame.md`

## 0. 总原则：不干涉论证与三层结构

**授权并行的 Story 写集两两不相交 ⇒ 守规矩的 Story 经治理链只写自己的文件，互不触碰对方路径。
shell 绕过围栏写集外属声明违规，由 Git 审计事后检出 → 该 Story 显性 FAILED、可归因、可重跑，
且该 Goal 的并行授权单向撤销（fail-closed 降级串行）。**

真并行 = 三层协同，缺一即回退串行：

1. **声明门控（授权）**：批成员由声明（`parallel_group` / `write_set` / `depends_on` /
   `max_parallel_stories`）与持久态（completed_stories、撤销闩）在每次推进时**确定性重推导**；
2. **写集围栏（预防）**：被授权 Story 的 file 工具写入受 per-run write allowlist 预检，
   越集写入在治理链内被结构化 BLOCKED；
3. **Git 审计（检测）**：Story 完成后由宿主比对 per-story 前后增量与声明写集，
   tracked 越集判负并触发撤销闩。

`max_parallel_stories` 永远只是上限，不是授权（AD-10 延续）。

## 1. 问题陈述

`.heagent/skills/he-goal/workflow.md` Step 07 声明 `max_parallel_stories: 3`，但该字段自 51-8 起是
**死字段**：`goal/workflow_loader.py` 的 `_parallel_limit` 只在 >1 时发 fail-closed 警告
（「declares max_parallel_stories=N, but stories currently run serially…」），引擎无任何消费者。
Story 执行固定串行，声明与行为之间存在显性裂缝——警告正是这道裂缝的每日提醒。

51-8 已交付并行所需的**全部声明面**：story 文档的 `depends_on` / `parallel_group` / `write_set`
三字段解析 + 依赖闸门（依赖未完成/未知 → BLOCKED）。缺的只有一件事：**可验证的写入隔离执行器**。
本 Epic 补齐它，让声明真正生效。

## 2. 产品目标

让 `max_parallel_stories > 1` 的步骤在七项授权条件全部满足时真实并发执行批内 Story，
其余形态逐字节退回现有串行路径；并行不破坏既有恢复语义、逐 Story 事件/证据与 checkpoint 兼容性。

核心结果：

1. 批派生是**纯推导**：同一次推进重跑得出同一批；不持久化批次状态、不加镜像字段（47-9 的 A25/A26 债不复活）。
2. 围栏在治理链内生效：`PolicyEngine.evaluate() → ToolExecutor → SafetyGuard → handler` 零旁路；
   未声明 allowlist 的运行与现状逐字节一致。
3. 审计可信：per-story 前后增量基线（非 HEAD），兄弟写集与宿主自写产物不计入违规；
   tracked 严格判负、untracked 仅警告（he-goal 自身的验证夹具与产物就是未跟踪写入，严格模式必然假失败）。
4. 失败语义显性：批内单 Story 失败不取消同批；写集违规 → 该 Story FAILED + Goal 级并行授权单向撤销；
   撤销的是并发授权，不撤销围栏（串行重跑仍带 allowlist、审计继续）。
5. 老资产零破坏：老回调（两参）、老 checkpoint、老 workflow 包全部按现状语义继续工作。

## 3. 功能范围（逐条标出「声明面」与「引擎面」）

| FR | 能力 | 声明面（主要交付物） | 引擎面（通用能力） |
|---|---|---|---|
| FR-1 | per-run 写集围栏 | （复用 51-8 的 story `write_set` 声明，不新增词汇） | PolicyEngine 路径预检支持 write allowlist（`file_write`/`file_edit` 越集 BLOCKED；目录条目放行子树；缺省 = 现状放行）；SubAgent 增 `write_allowlist` 参数经 RunContext metadata 注入（reserved 防伪造） |
| FR-2 | 批次调度与并行执行语义 | 步骤 `max_parallel_stories` 语义定稿：上限 + 门控开关 | Runner 批派生纯函数（七条件）+ `gather(return_exceptions=True)` 并发 + 按声明序记账/逐成员持久化 + 批=单 checkpoint 单元 + `workflow_story_batch_scheduled` 事件 + 第三参回调签名探测 |
| FR-3 | 宿主写集审计与失败语义 | Step 06 指导 `02-epics.md` 逐 Story 声明三字段与写集完备性 | `StoryExecutionContext` 贯通（batch_members / sibling_write_sets）；宿主 per-story 增量审计（tracked 判负 / untracked 警告 / 非 Git 跳过）；`write_violation` → 撤销闩（checkpoint 追加可选字段） |
| FR-4 | 声明面与文档收口 | `workflow.md` Step 06/07 正文改写（revision bump）；`templates/STORY.md` 字段示例；`docs/frame.md` 事件表与围栏小节；`docs/goal-workflow.md` 并行语义 | `_parallel_limit` 警告改条件说明（INFO）；`test_workflow_resources.py` 断言同步 |
| FR-5 | 集成验收与恢复矩阵 | — | 并行全链样例（调度→围栏→审计→合并→恢复不重跑）；恢复矩阵新增撤销闩与批中间快照形态；架构契约同步；全量质量门 |

## 4. 非目标

- 不实现 Git worktree 物理隔离——本 Epic 只固化写集契约与授权语义，worktree 是后续增强层
  （它改变围栏与审计的实现强度，不改变语义面；untracked 逃逸面在该层天然根治）。
- 不实现 OS 级沙箱 / 容器 worker（AD-12 口径不变：SafetyGuard/PolicyEngine/围栏均非真正安全边界）。
- 不预防 shell 写入——`run_shell` 绕过围栏属声明违规，由审计事后检出，不做 shell 命令写路径解析。
- 不持久化批次状态、不复活 `active_stories` / `story_batches` 类镜像字段。
- 不改审批、门禁、GoalScript、事件转换表的既有语义（批 = 单 checkpoint 单元是唯一语义收紧点，
  见 AD-19）。
- 不自动 Git commit（AD-11 延续）。

## 5. 成功标准

1. 声明不相交写集 + 同组 + 依赖已完成的 Story 峰值并发 ≥ 2；七条件任一不满足时峰值并发 = 1
   且串行路径既有测试零改动通过。
2. 越集 `file_write` / `file_edit` 在治理链内被 BLOCKED，reason 点名路径与写集；无 allowlist 时
   既有 policy 测试全绿（零回归）。
3. tracked 增量越集 → 该 Story FAILED（reason 列出越集路径）+ 撤销闩随 checkpoint 持久化，
   重启后该 Goal 不再并行；兄弟写集内的路径不误伤；untracked 增量只发警告事件。
4. 批内一失败一完成：完成者入账不重跑；失败者 `story_statuses=failed`；步骤 FAILED；
   恢复从首个未完成 Story 起。
5. 步骤级取消 → 整批 PENDING、成员记 cancelled（不谎报 failed）。
6. 老 callback（两参）/老 checkpoint/老 workflow 包按现状语义继续工作；恢复矩阵含撤销闩与
   批中间 RUNNING 快照形态全部可恢复续跑。
7. 只改 story 文档声明（加/去 `parallel_group`）即可翻转批派生结果，`src/` 零改动（51-8 同款验收演示）。

## 6. 风险登记

| # | 风险 | 触发条件 | 缓解 |
|---|---|---|---|
| R1 | 共享工作树质量门互扰（A 的测试读到 B 半成品） | 批内 Story 的验证命令依赖批外/他人文件 | 写集不相交 + 依赖闸门（良构计划下测试只碰自己的文件）；并行 Story 的门命令宿主锁串行化；文档明示残余；worktree 层根治 |
| R2 | shell 绕过围栏 | Story 用 `run_shell` 写集外 tracked 文件 | 定位如实：围栏是纵深防御非安全边界（AD-12 同源）；Git 审计事后检出 → FAILED + 撤销闩 |
| R3 | 审计过度归因（无辜 Story 被污染批连坐判负） | 批内任一成员越集后，后完成审计者的增量含脏路径 | fail-closed 有意为之（污染批不多盖 COMPLETED 章）；reason 列出越集路径供人甄别；重跑成本低 |
| R4 | Provider/引擎组件并发安全 | 3-5 个 SubAgent 会话同时打同一 provider | 既有先例：`run_parallel`、单迭代工具批 gather 均已并发复用；runs/rollout 按 run_id 分片单写者；压力形态纳入 52-5 |
| R5 | goal_mutex 持锁时长拉长 | 批内多条 LLM 长会话期间 cron/另一 CLI 尝试推进 | 既有 5s 超时快速失败 + 下一 tick 重试；批对控制面原子；回调链绝不进入 goal_mutex（跨 task 不重入） |
| R6 | write_set 声明不完备导致假失败 | 模板作者漏报测试文件/验证命令改动的文件 | Step 06 声明指导 + STORY.md 模板提示；串行 Story 不围栏（老 Goal 零破坏）；审计 reason 点名路径便于补声明 |
| R7 | checkpoint id/内容冲突 | 批中间 RUNNING 快照与既有 id 位置重叠 | id 是位置全函数（`_checkpoint_id` docstring 论证）；批快照与串行快照天然错位；52-5 恢复矩阵覆盖 |
| R8 | Windows 并发写同盘（AV/文件锁） | 并行 Story 各写各文件 | 写集两两不相交 ⇒ 路径不重叠；验证工作区按 per-story 子目录约定（`.heagent/tmp/<goal-id>/s-<n>/`） |

## 7. 交付顺序

```text
52-1 写集围栏原语
  → 52-2 批次调度器与 Runner 并行语义
  → {52-3 宿主接线与 Git 审计 ∥ 52-4 声明面与文档收口}
  → 52-5 集成验收与恢复矩阵
```

52-1 先于 52-2（授权并行的前提是预防层存在）；52-3 依赖 52-2 的执行上下文协议；
52-4 只依赖 52-2 的语义定稿，可与 52-3 并行；52-5 收口全链。
