# Goal 驱动工作流（`/goal`）

> 状态：实现细节参考，自 [`framework.md`](../framework.md) **4.13 / 4.13.1** 迁出（2026-11-24 整理；编号不变，
> 其它文档里「4.13」的引用即指本页）。架构视角（项目定位 / 数据流 / 模块 DAG / 各模块职责与边界）见
> [`framework.md`](../framework.md)，安全立场（canonical）见 [§4.18](../framework.md#418-安全口径canonical)，
> 扩展页总索引见 [`frame/README.md`](README.md)。

## 4.13 Goal 驱动工作流 (`/goal`)

`/goal` 是 CLI 层的机制入口（命令族实现位于 `cli/goal/` 子包）。当前工作流的唯一方法论入口是
`.heagent/skills/he-goal/workflow.md`（属 `he-goal` 包，由 skill catalog 按 id/别名解析）；步骤声明中的 `role` 再解析对应的 `.heagent/skills/*/SKILL.md`。
声明的确定性装载在 `goal/workflow_loader.py`（`read_workflow(package)`：frontmatter 策略、内嵌步骤、
`required_resources` 模板必需性），产出 `engine/workflow_resource.py` 的 `WorkflowResource` 供
`WorkflowRunner` 消费——装载与执行分离，模板文案零代码副本。
**确定性内核与渲染分离（2026-09-21 Phase 3）**：workflow 校验、gate/prompt 装配、story 选择、
checkpoint 恢复（`restore_runner`，恢复顺序与显性失败语义见其 docstring）与推进 use-case
（`advance`/`pause_resume`，用户可见文案以结构化 outcome.messages 携带）收敛在
`goal/application.py`，声明面（包加载/校验、绑定冻结、门禁与 open-question 策略、prompt 装配）
在 `goal/workflow_support.py`（2026-11-17 Story 62.8 拆出，`application` 再导出保导入面）——
两模块均 click-free（架构契约测试钉死 import 图）；`cli/goal/` 子包是渲染薄壳
（messages 逐行 `click.echo(err=True)`）+ 缝宿主（`_goal_session`/`_goal_declarative_prepare`/
`_goal_declarative_advance`/`_goal_runner` 等测试缝原位）+ settings 注入边界。CLI/GUI/cron
三入口仍收敛同一 use-case（GUI 经 `_goal_runner`、cron 经 `_goal_cron_advance`），无复制推进逻辑。

- `/goal <description>` 或 `/goal new <description>` 创建 `_he-output/goals/<goal_id>/brief.md`（只含原始需求）
  和 `current` 指针，然后执行 workflow 的第一个声明步骤；「总结的需求」由 step 01 初步分析后写回同一文档。
  `goal_id` 由 LLM 命名（`goal/naming.py` 一次性 provider 调用生成 kebab-case 名，清洗/校验/`-a`..`-z`
  去重为代码内确定性逻辑）；调用失败或输出非法时 stderr 显性提示并回退固定名 `project`。
  id 字符集锁定 `^[a-z][a-z-]*$`（current 指针校验、cron prompt 解析、旧 job 注销匹配三处下游依赖）。
- `/goal next` 执行一个声明步骤，`story_loop`（当前为 `epics.md`）步骤默认每次只执行一条 Story；
  声明门控并行（Epic 52）授权时一批并发执行（见下「声明门控并行与写集围栏」）。每条 Story（串行）
  或每批（并行，批 = 单 checkpoint 单元）完成后持久化 checkpoint / evidence；`/goal run` 可连续推进，遇到检查点、
  阻塞或失败即停止。
- `/goal status` 只读回显运行状态和目标产物；`/goal reset` 只清除 current 指针并保留目标目录。
- `/goal verify [run]`（Story 51-4）：按步骤 `validation:` 的结构化子句求值——`goal/quality_gates.py`
  的通用求值器把声明子句比对到证据（`goal/evidence.py` 的 `<goal_dir>/evidence/`）、产物文件与只读 Git
  （`goal/git_port.py`），产出结构化通过/失败报告（经 `_echo` 漏斗）。`verify run` 先把声明命令经治理链
  （PolicyEngine → ToolExecutor → SafetyGuard → shell handler）受控重跑并落证据；绝不重跑实现步骤、
  不改 Runner 状态。步骤完成门（`cli/goal/verify.py` 的 `_goal_structured_gate`）复用同一求值器：步骤产物落盘后
  求值，未通过经 `WorkflowRunner` 的 `GATE_FAILED` 事件进 `BLOCKED`。`gate:` 名字由宿主注册表
  （`QUALITY_GATES`，名字 → 语义 + 求值函数分派表）提供，加载期由 `workflow_loader` 校验（未注册或
  声明条件不满足均 fail-loud）。
- `/goal resume [回复]` 记录用户回复并恢复等待中的步骤；`/goal auto [cron]` 通过 JobStore 复用同一推进路径。
- **步骤级审批与决策记录（Story 51-5）**：步骤 frontmatter 可声明 `approval: required`（可带一句
  说明）——该步做完工作后挂起 `WAITING_USER`，完成簿记延后，只有人工决策能推进；未声明的步骤
  零行为变化。「第几步需要审批」只存在于该步声明里，`src/` 无任何按步骤名/序号的审批判断（AD-13）。
  四个事件语义独立（AD-3）：`/goal approve` 接受并落定完成（唯一把该步标记完成的路径；末步批准
  即完成 goal）、`/goal reject <原因>` 驳回（步骤未完成，落 BLOCKED，修订后 `resume` 重跑）、
  `/goal amend <补充>` 带补充重跑（步骤未完成，落 PENDING；补充同时进需求文档「用户补充」段）、
  `/goal resume` 只恢复执行——审批门挂起时被显性拒绝，不隐式等同批准。cron/auto 推进在审批门前
  停下，不自动批准人工 Gate；CLI/GUI 共用 `goal/application.record_decision` 同一应用服务。
  每次决策在 `<goal_dir>/decisions/` 追加一条版本化记录（id、步骤、原文、UTC 时间、影响范围、
  结果状态、审批轮次；成功的 `/goal resume` 亦记一条 RESUME——只标记执行被恢复，不等于批准），
  独占创建、重跑不覆盖历史（`goal/decisions.py`）；`/goal decisions` 只读回显（goal 域锁内读，
  防撕裂读）。审批门挂起状态（`awaiting_approval` + 挂起产物 + 单调审批轮次——轮次进 checkpoint
  幂等键，reject/amend 重跑再挂门不撞 conflict）随 checkpoint 持久化与恢复，跨进程可决策。
- **跨进程互斥（2026-09；2026-10-07 A32② 下沉）**：goal 域互斥本体在 `goal/mutex.goal_mutex()`
  ——进程内 `asyncio.Lock`（快速路径）+ `.heagent/goal.lock` 跨进程文件锁
  （`persist.file_lock`，5s 超时显性失败：手动方收到「另一进程正在推进」提示，cron 下一 tick 自动重试），
  同一 task 内可重入。**变更内核自持**：`goal/application` 的 `advance` / `pause_resume` /
  `record_decision` 三个写方法整段读改写都在锁内（GUI/HTTP 等第二入口直调即得互斥，不依赖
  入口层自觉）；CLI 的 `/goal` 变更入口（new/next/run/resume/reset/cron 推进）仍在外层整段
  持锁组合（`_goal_mutex()` 薄别名）。锁文件刻意保留不删（规避 unlink 竞态）；防「双进程从
  同一状态各自推进后互相覆盖 brief.md」丢进度。只读命令（`/goal status` / `/goal doctor`）
  是无锁快照读，半截文件按「损坏」显性报错。

每个步骤或 Story 都由新的 SubAgent/RunContext 执行。`WorkflowRunner` 负责顺序、输入、输出、checkpoint
和恢复；它不决定 Epic/Story 的拆分方法。

> 状态迁移与中断语义矩阵（S-3）留在 [`framework.md`](../framework.md#4132-状态迁移与中断语义矩阵s-3) 4.13.2——它同时是 `WorkflowEvent` 词表判据的锚点。

**声明门控并行与写集围栏（Epic 52，AD-16..20）**。`max_parallel_stories > 1` 只是授权门的上限，
不等于并发度：每次推进由 `WorkflowRunner._parallel_batch` 从声明（`parallel_group` / `write_set` /
`depends_on` / 上限）与持久态（completed_stories、单向撤销闩 `story_parallel_revoked`）确定性重推导
批成员——批次是推导不是状态，不持久化。授权充要条件为七项全满足（上限 >1、闩未置位、宿主回调实现
三参 `StoryExecutionContext` 契约、同非空 `parallel_group`、`write_set` 非空且批内两两不相交、
`depends_on ⊆ 已完成`（不允许依赖批内成员）、批大小 ≤ 上限），任一不满足即逐字节走既有串行路径。
被授权 Story 的工具写受 per-run write allowlist 预检（`engine/policy.py` 的
`_validate_write_allowlist`：`file_write` / `file_edit` 目标越集 → BLOCKED，走
`PolicyEngine.evaluate() → ToolExecutor → SafetyGuard → handler` 既有治理链，零旁路）。**定位与
path_safety / 工作区围栏同构：纵深防御**（边界地位见 §4.18；shell 路径可绕过，故另有宿主
Git 审计事后检测（`goal/write_audit.py` 的 `_audit_story_writes`，`cli/goal/` 子包负责编排与呈现；2026-11-07 自 `cli/goal.py` 迁入该模块）：per-story 会话前后只读 Git 增量基线，
tracked 增量越出「本 Story 写集 ∪ 兄弟写集 ∪ 宿主自写产物」→ FAILED + `write_violation` → 撤销闩
单向置位（随 checkpoint 持久化，重启后该 Goal 仍串行）；untracked 增量只发警告事件不判负）。
产物豁免同时按**两种参照系**登记：`git diff --name-only` 报**仓库根**相对路径、`git ls-files
--others` 报 **cwd**（= 工作区）相对路径，故产物以工作区相对记入 untracked 豁免、并换算成仓库根
相对（`_git_toplevel` / `_repo_relpath`）后记入 tracked 豁免；工作区恰为仓库根时两式逐字相同
（当前部署，恒等变换），工作区仅为子目录时才真正生效（A43）。
**Δ 是内容级增量**：对 `git diff --name-only` 报出的每条路径取流式 sha256（会话前基线、会话后各一次），
同名路径只有在内容真的变了才算增量——路径集合差集看不见「会话前已脏的集外文件被本 Story 再改」
（路径前后都在 ⇒ 差额恒为空），也放得过「既有脏文件本 Story 没碰」（不该判负）；指纹读不到
（权限 / 中途消失）记空串、按增量处理（方向：多判负、不漏判）（A40）。判负时越集路径 + 基线 revision
进 `workflow_write_audit` 事件**留档**（闩后该 Goal 串行、新基线已含旧违规 ⇒ 该事件是越集写的唯一
持久记录），reason 内附 `git diff <base> -- <path>` / `git restore --source=<base> -- <path>` 的人工
清理指引（自动回滚需会话前快照，属 AD-20 层，A42）。共享工作区里写者**无法归属到某个 Story**
（写集并集对批内每个成员同形 ⇒ 越集写同样会被写者自己的审计判负），故消息与事件如实标注
`shared_workspace` / 「a sibling may be the author」而不是默认归因（A41）。
批内并发走 `gather(return_exceptions=True)`（单成员失败不连坐；步骤级取消取消整批落 PENDING）；
manual 模式 checkpoint 确认每批一次。Story 物理隔离已落地（AD-20 / A41，2026-11-21）：授权并行时该
Story 在确定性路径 `<repo>/.heagent/worktrees/<goal>/<story>` 的 detached worktree 里跑
（`context_dir` 透传 ⇒ 围栏根与写集审计基线都钉 worktree），完成后经临时引用 + cherry-pick 回收提交
（冲突 abort 后显性 FAILED），worktree 在 finally 移除。围栏根换成 worktree 时**运行产物根不跟着搬**：
`RunContext.state_root` 钉容器根（与 `RunStore` / `ExecutionLedger` 同源），工具审计因此落主工作区而不是
随 worktree 移除丢失；run 快照与 ledger 本就读容器根，不受隔离影响。
产物面同理不能靠 cherry-pick：`_he-output/` 是 gitignore 面，故 worktree 移除前由
`goal/worktree.py::promote_goal_products` 把本 Story 自写的增量（untracked / ignored / tracked-modified）
搬回主工作区，未改动的 tracked 旧版本不覆盖主工作区，搬不动即显性 FAILED。

checkpoint id 同时是幂等键（`WorkflowCheckpointStore.save` 对「同 id 不同内容」fail-safe 报错），因此必须是「位置」的
完全函数：`story_loop` 步骤的激活 Story 参与 id —— `<goal>-<run>-step-<N>-story-<index>[-<S-n>]-active-<step>-<status>`。
同一 `(step, story_index)` 槽位确实存在两种快照（「尚未进入首个 Story」与「Story S-1 待执行」），不区分会让 resume
重写被误判为 checkpoint conflict（2026-09-10 修复）。

Goal SubAgent run snapshot 的 `context.metadata` 包含 `goal_id`、`goal_kind`（planning/story）
与框架权威的 `kind=subagent`。metadata 仅用于观测，不能覆盖 PolicyEngine 的授权字段；
无人值守 cron 不提升权限，审批与 sandbox 策略仍由 engine 处理；该层的边界地位见 §4.18。

`workflow.md` 是自包含的声明式入口。其 `on_create` 声明创建规范化 `GoalArtifact` 和 `current` 指针；
每个 inline `## Step NN:` 区块声明 prompt、输入输出和 checkpoint。CLI 只映射已支持的
`persist_goal_identity` 与 `subagent` 声明到确定性操作；成功输出保存为
`step-XX-<step-name>.md`，Story 输出保存到对应的 Story 子目录——`parse_story_list` 从 story list 的
`## E<N> — <标题>` 段落（或 Story 块内的 `父 Epic` 字段，后者优先）解析出 `StorySpec.epic`，产物按
`step-NN-<slug>/epic-<eN>/s-<n>/report.md` 分组（`E1` → `epic-e1`；无 Epic 分组时退化为
`step-NN-<slug>/s-<n>/report.md`）。旧的 imperative goal board 路径不再作为回退。

## 4.13.1 受控 GoalScript（Story 51-7）

步骤 frontmatter 可声明 `executor_mode: script`（缺省 `subagent` = 现状）与
`script_resource: <scripts/ 下的包内相对路径>`；脚本是**包内资源**，经
`SkillPackage.read_script()` 读取，因而复用 manifest.json / manifest.lock 两条内容完整性凭据
（漂移 fail-loud，报 `content hash differs from …`）。声明与派生 revision 同源：未显式声明
`revision` 的包，脚本内容进入 `workflow_revision` 指纹（改脚本 = 流程漂移）。

**⚠️ 边界地位见 §4.18（AD-9 / AD-12）**：脚本在**宿主解释器**内执行，理论上拥有 Python 进程
权限。可用的约束只是「形态 + 资源 + 请求面」，用于约束**可信本地包**的误用，不用于承载
不可信输入；第三方 workflow 包必须先有 OS 级隔离（容器 / VM / firejail）与隔离 worker，
该 worker 不在本 Story 范围。

- **入口单一真源**：`goal/script_loader.py` 的 `SCRIPT_ENTRYPOINT = "build_workflow"`，
  脚本须定义 `async def build_workflow(goal)`；加载期与运行时读同一常量。
- **加载期形态校验（`script_loader.load_script`，AST）**：拒绝 `import`（含 `os`/`sys`/
  `asyncio`/`subprocess`/`socket`/`pathlib`/`urllib` 等）、`while`、除入口外的任何函数定义、
  私有属性访问（`x._y`，含 `_inputs` 这类 facade 内部）、以及 `open`/`eval`/`exec`/
  `compile`/`__import__`/`getattr`/`globals`/`vars` 等能力名。
- **受控 facade（`script_api.GoalScript`）**：只暴露 `step` / `parallel` / `checkpoint` /
  `input` / `artifact` / `decision` / `validate` 七个操作，请求 / 响应一律 Pydantic 模型
  （`ScriptRequest` / `ScriptResponse` / `ScriptExecutionResult`，AD-4）。facade 不持有
  Runner、文件句柄、进程或网络句柄。
- **有界执行（`script_runtime.ScriptRuntime`）**：`max_requests`（facade 计数，超限抛）、
  `max_depth`（AST 嵌套层级）、`timeout_seconds`（`asyncio.wait_for`）。**超时是协作式的**
  ——脚本若在同步 CPU 循环里不让出事件循环，取消不会生效；这正是 §4.18 所述非边界
  的具体含义，故如实声明而不假装挡住。
- **状态变更仍归 Runner（AD-1）**：`WorkflowRunner` 是唯一状态机，脚本不写 checkpoint /
  `workflow.json` / `current`，也不直接改 Runner 状态；执行结果以
  `WorkflowStepResult` 回落到既有推进链，产物仍写 `_goal_output/...` 的声明路径。
- **不绕过质量门、失败有界**：脚本产物落盘后与 subagent 步骤走**同一条**结构化完成门
  （`_goal_structured_gate`，Story 51-4），`validation:` 未过落 `BLOCKED`；脚本抛出的任何
  异常由 `ScriptRuntime` 收敛为有界 `FAILED`（宿主映射为步骤失败），**不打崩 `/goal run`**。

**两阶段提交（A 语义）**：脚本执行期只**声明**，宿主在脚本返回后按声明顺序**提交**。

- 阶段一（脚本执行期）：`input` / `artifact` 是只读操作，**同步作答**；其余五个操作只被
  **校验并记录**（宿主 `_goal_script_declaration_error`），不落任何状态。不可兑现的声明在
  这里就失败（fail-loud）：**未注册门**、**未声明的步骤名**、**自指**的请求当场抛错——
  脚本不会跑完才发现声明无效。
- 阶段二（脚本返回后）：宿主按序提交（`_submit_script_requests`）。`checkpoint` / `decision`
  落本步证据（随 `WorkflowStepResult.evidence` 进 `runner.state.acceptance_evidence`，由
  Runner 持久化）；`validate` 复用 Story 51-4 的求值器跑该命名门，未过 → 该步 `BLOCKED`；
  `step` / `parallel` 收集为**声明的后续步骤计划**（`WorkflowStepResult.requested_steps`）。
- **A1：`WorkflowRunner.run_declared_step(name)`** —— 跑**指名**的已声明步骤（`run_step` 只跑
  `state.active_step`）。状态机仍完全归 Runner：名字必须已声明；**已完成的步骤幂等跳过**
  （不重跑、不写新 checkpoint，用 `WorkflowRunResult.skipped` 显式标明，调用方不去猜 reason
  文案）；只允许**向前**选择；挂起 / 失败 / 已完成时不改状态。脚本因此能条件性地选择后续
  步骤，而步骤顺序权没有离开状态机（AD-1）。
- **A2：`goal/application.advance` 消费计划** —— 计划存在 `WorkflowRunnerState.requested_steps`
  （FIFO，本步声明的排在已有计划之后）并**随 checkpoint 持久化**
  （`WorkflowCheckpoint.requested_steps`，AD-2 修订版允许的可选追加字段，旧 checkpoint 读作
  空计划）：进程重启后仍按同一选择恢复，**不退回声明顺序**。循环每轮取队首交给
  `run_declared_step`；计划被消费一次即出队（含幂等跳过）。
- **有界**：累计计划超过 workflow 的声明步骤数时由 Runner 落 `BLOCKED`（有界失败），不做静默
  截断；被跳过的声明步骤保持未执行（`completed_steps` 出现缺口），`/goal status` 照实投影。
- **已知边界**：脚本可以**声明**一组后续步骤（含用有界 Python 循环声明），但不能**重跑**已完成的
  步骤——那被当作幂等跳过，因此「按状态反复重试某一个声明步骤」不在此设计内。
