# Epic 51 架构脊柱：`/goal` 与 workflow 可信交付优化

- 建立：2026-09-29；同日按「交付一律由工作流声明表达」的口径重整
- 状态：冻结（freeze）
- 输入：`docs/goal-workflow.md`、`docs/frame.md`、现有 `/goal` 代码与测试

## 0. 架构范式

**声明即行为：单一状态机 + 通用解释器 + 声明驱动的 Gate。**

```text
workflow.md / step-NN-*.md / templates/      ← 声明面（唯一权威：Epic/Story/步骤/门禁/角色/审批）
        02-epics.md / story 文档             ← 工作流产物（Epic/Story 清单、依赖、写集、验收标准）
                        ↓
        Workflow loader / 声明校验器          ← 引擎面：读声明、校验、缺省语义
                        ↓
        WorkflowRunner（唯一状态机）
                        ↓
        WorkflowCheckpointStore（唯一状态持久化）
                        ↓
        执行端口 → AgentLoop → PolicyEngine → ToolExecutor → SafetyGuard → handler
                        ↓
        证据记录 → 声明驱动的 Gate → 报告 / 控制面（只投影事实）
```

`src/` 只放与任何具体 Epic / Story 无关的通用引擎：**读声明并校验** → **执行状态机** →
**原子持久化** → **经治理链执行工具** → **把声明中的事实投影成用户可见状态**。

## 1. 不变量

| ID | 规则 | 防止的分歧 |
|---|---|---|
| AD-1 | `WorkflowRunner` 是唯一状态机；workflow、CLI、GUI、cron、脚本都不得自行推进状态。 | 多套恢复语义和直接状态赋值 |
| AD-2 | `WorkflowCheckpointStore` 是唯一 checkpoint 写入口；只允许**追加带默认值的可选字段**，不得改名、改语义或强制迁移（旧 checkpoint 必须照常加载）。 | 双写与存量 Goal 失效 |
| AD-3 | 状态变化统一为 `transition(source, event)`；非法组合抛 `WorkflowTransitionError`。 | 条件分支漂移与静默修正 |
| AD-4 | 跨模块状态、证据、决策与脚本请求均使用 Pydantic 模型，不传原始 dict。 | 协议漂移与弱类型恢复 |
| AD-5 | 报告与证据分离。只有受治理执行路径生成的 Evidence 才能满足命令 / Git / 质量 Gate。 | Markdown 伪造「已测试」 |
| AD-6 | 工具执行链保持 `PolicyEngine.evaluate()` → `ToolExecutor` → `SafetyGuard.check()` → handler。 | workflow 或脚本绕过治理 |
| AD-7 | CLI、GUI、cron 共用 `goal/application.py` 的确定性用例；入口层只适配输入输出。 | 三入口语义分叉 |
| AD-8 | workflow 在 Goal 创建时冻结标识与 revision/hash；恢复时资源漂移 fail-loud。 | 运行中静默换流程 |
| AD-9 | GoalScript 默认关闭，仅可信本地包可启用；它不是安全边界。 | 任意 Python 被误当沙箱 |
| AD-10 | 不能证明并行安全就串行；`max_parallel_stories` 不是安全证明。 | 写集冲突和顺序依赖 |
| AD-11 | 不自动 commit；Git 只作为变更与基线证据，提交需用户明确确认。 | 未授权版本操作 |
| AD-12 | OS 容器 / VM / firejail 才是真正安全边界。 | 对内置治理的错误安全承诺 |
| AD-13 | **声明即行为**：Epic / Story / 步骤 / 门禁 / 角色 / 审批 / 依赖 / 交付顺序只存在于声明与工作流产物；`src/` 不得出现具体 Epic 名、Story 名、步骤名或角色名的分支逻辑。 | 把流程知识烧进代码，改流程必须改代码 |
| AD-14 | **新词汇才动代码**：任何 `src/` 改动必须先在该 Story 内证明「声明层表达不了」；新增声明词汇必须对所有 workflow 通用、与具体 Epic 无关、老包不声明时行为不变。 | 为单个 Epic 开专用分支 / 专用模块 |
| AD-15 | **投影只读事实**：视图、报告与 Gate 只能投影声明与已记录的事实；缺失即留空并显式说明，不得推断层级、补齐字段或静默回退。 | 为了让界面好看而伪造状态 |

## 2. 声明层：词汇表与归属

声明面的载体固定为三类：`workflow.md` 的 frontmatter、每步的 frontmatter（内嵌于 `## Step NN:` 或独立
`step-NN-*.md`）、以及工作流产物文档（`02-epics.md` / story 文档）。

| 词汇 | 载体 | 现状 | 归属 Story |
|---|---|---|---|
| `steps` / `input` / `output` / `next` / `checkpoint` / `validation` / `role` / `story_loop` / `max_parallel_stories` / `max_iterations` | 步骤 frontmatter | 已存在 | — |
| `required_resources` / `checkpoint_mode` / `open_question_mode` / `max_rounds` / `auto_schedule` / `on_create` / `step_executor` / `entrypoint` | workflow frontmatter | 已存在 | — |
| `templates/prompt-template.md` / `templates/gate-template.md` | 包内资源 | 已存在 | — |
| `doctor_checks` / `status_fields`（预检项清单与状态字段清单） | workflow frontmatter | 已存在 | — |
| `validation:` 的结构化证据子句（命令 / 产物 / Git 路径 / 质量门） | 步骤 frontmatter | 已存在 | — |
| `approval:`（该步是否需要人工确认） | 步骤 frontmatter | 已存在 | — |
| workflow `revision`（或由包内容推导的 hash） | workflow frontmatter / 包元数据 | 已存在 | — |
| `executor_mode: script` 与包内 `scripts/` 资源 | 步骤 frontmatter + 包内资源 | 已加（声明 / 加载 / 受限 facade / 限额 / A1 Runner 步骤端口 + A2 持久化计划） | 51-7 |
| `depends_on` / `parallel_group` / `write_set` | story 文档 | 已加；当前仅依赖闸门，写集不授权并发 | 51-8 |

规则：新增词汇一律加在**上表载体**内，不新增平行的顶层配置；同一事实只能有一处声明。

## 3. 状态与事件

- 外部状态保持：`PENDING`、`RUNNING`、`WAITING_USER`、`BLOCKED`、`FAILED`、`COMPLETED`。
- 事件至少包括：`START`、`STEP_COMPLETED`、`CHECKPOINT_REQUIRED`、`USER_RESUME`、`USER_PAUSE`、
  `INPUT_MISSING`、`GATE_FAILED`、`EXECUTOR_FAILED`、`FINAL_STEP_COMPLETED`、`CANCELLED`。
- **事件集是通用词汇**：具体 workflow 用到哪些事件，由它自己声明的 `checkpoint` / `validation` /
  `story_loop` 触发条件决定；代码里不得出现「第 7 步要审批」这类知识（AD-13）。
- **当前 Epic 是 runner 的事实**：story 循环在调度每条 story 时记下它所属的 Epic，并随 checkpoint
  持久化（`WorkflowCheckpoint.active_epic`，可选字段）。视图只投影它，**不回读 story 文档、不推断层级**
  （AD-15）；旧 checkpoint 缺该字段时显示「未知」，恢复后仍为空 —— 不猜。
- 每个状态赋值必须能追溯到一个事件；不存在「为了掩盖失败而直接写 `PENDING`」的路径。
- 观测 sink 失败只记 warning，不改变状态机结果。

## 4. Evidence 与 Gate（声明驱动）

- 某一步要什么证据，写在**该步**的 `validation:` 里；引擎只提供通用求值器与记录模型。
- 命令证据至少包含：工作目录、命令摘要、退出码、耗时、输出 digest / 有界脱敏摘要、失败分类。
- Git 证据至少包含：base / head 与变更文件集（只读查询，不自动 commit）。
- Gate 规则：
  - 缺证据不能用报告文本补齐（AD-5）；
  - 失败 / 超时 / 取消 / 策略阻断均有显式证据；
  - **步骤未声明结构化门禁时保持文本门禁行为**（老包零改动）；
  - 声明的结构化子句非法时 fail-loud，不静默回退旧语义。

## 5. 审批与 workflow 冻结

- `approve`、`reject`、`amend`、`resume` 是不同事件，语义不可互相顶替。
- 「这一步要不要人工确认」由该步 `approval:` 声明；cron 不得自动批准人工 Gate。
- 决策记录追加式保存，重跑不得覆盖历史；决策是**记录**，不是对声明的事后改写。
- workflow 标识与 revision / hash 在创建时写入 Goal 元数据；恢复时比对，漂移 fail-loud；
  老 Goal 缺字段时按兼容规则绑定 `he-goal`，**不在只读路径改写原件**。

## 6. GoalScript 边界

- 脚本与工作流一样是**包内资源**；可用动作集由声明与 facade 共同界定。
- 允许：声明步骤、受控并行、checkpoint、读取已登记输入 / 产物、记录假设、请求决策、调用受控验证器。
- 禁止：直接写 checkpoint / workflow / current、直接文件写、`run_shell`、子进程、裸网络、Git commit、
  访问 AgentLoop / PolicyEngine 内部状态。
- 第一阶段在宿主解释器运行时只支持可信本地包，并强制资源完整性校验、步骤 / 深度 / 超时上限。
  第三方脚本必须等待隔离 worker；该 worker 不在本 Epic 的强制交付范围（AD-9、AD-12）。

## 7. 安全并行

- Story 元数据：`depends_on`、`parallel_group`、`write_set`（写在 story 文档里）。
- 当前宿主执行器固定逐条 Story：依赖完成才可执行，未知或未完成依赖即 `BLOCKED`；每条先持久化
  checkpoint / evidence 再开始下一条。`parallel_group` / `write_set` 是可审计声明，但不是写入隔离边界。
- 真正并行必须先提供可验证的隔离执行器；在此之前不得持久化虚假的「已批准批次」或按配置扩大并行度。

## 8. 兼容性

- 继续支持 `brief.md`、`require.md`、`GOAL.md`。
- Phase 1 不迁移 checkpoint JSON；新增字段必须有缺省值与旧读路径。
- 老 workflow 包不声明新增词汇时，一律退回现状语义（文本门禁、无审批、无脚本、串行）。
- 新增 schema 时必须有版本、旧读、新写门槛、失败不覆盖原件与回滚说明。

## 9. 引擎面落位

引擎面**不是**按 Story 铺模块，而是收在一小组通用解释器里；落点按 Story 追加，且每处都必须通过 AD-14 的证明。

```text
src/heagent/engine/
  workflow_resource.py       # 声明模型（上表词汇的单一真源）
  workflow_loader?           # 实际在 goal/workflow_loader.py（声明 → 模型，含缺省与校验）
  workflow_runner.py         # 唯一状态机
  workflow_transition.py     # 唯一转换表（通用事件词汇）
  checkpoint.py              # 唯一持久化

src/heagent/goal/
  doctor.py                  # 声明 → 结构化报告（只读；检查项全部从声明推导）
  status_view.py             # 状态 → 视图投影（纯投影，零 IO）
  application.py             # CLI-free 确定性用例
  （51-4）通用门禁求值器      # 只解释 validation 的结构化子句
  （51-5）追加式决策日志      # 只记录事件，不改声明
  （51-6）创建时冻结 meta     # 只写 id/revision/hash
  （51-7）受控 facade         # 只把脚本请求映射回 Runner 与治理链
```

- `engine/` 不得导入 `goal/` 或入口层；`goal/` 可依赖 `engine/`；`cli/goal.py` 只负责命令分发和渲染。
- **checkpoint 目录的唯一解析点**是 `checkpoint_store(goal_dir)`；预检方经
  `WorkflowCheckpointStore.base_dir` 取同一目录（不另算一份，否则「报告可写、实际写别处」）。
- 51-6 的**主要交付物是声明包**（模板 workflow 包），其引擎面可能是零 —— 只要既有的包装载与冻结能力够用。
- 反例（禁止）：`if step.name == "step-07-..."`、`if workflow.name == "he-goal"`、按 Epic 编号分支、
  为某个风险等级硬编码门禁文案。

## 10. 验证纪律

- 每个 Story 必须有正向测试、负向验证和必要的变异体；改 `engine/` 或包依赖时同步
  `tests/test_architecture_contracts.py`。
- 验证数字只能来自亲跑命令；规划命令引用不存在的文件时按实测更正。
- **AD-13 / AD-14 的验收方式**：每个交付 Story 演示一次「只改声明、`src/` 不动」的增量
  （51-6 加一个模板包；51-8 加一个 Epic / Story / 依赖）；以及一条判据：`src/` 中不得出现
  具体 Epic 名、步骤名、角色名的分支字面量。
- 最终质量门：相关 pytest、全量 pytest、ruff lint / format、`mypy src` 与 `mypy src --platform linux`。
