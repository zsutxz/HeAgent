# Epic 51 产品简报：`/goal` 与 workflow 可信交付优化

- 建立：2026-09-29；同日按「交付一律由工作流声明表达」的口径重整
- 状态：实施中；51-1~51-7 已完成，51-8 正在收口
- 编号：Epic 51
- 周期目录：`_bmad-output/epics/epic-51-goal-workflow优化周期/`
- 上游：Epic 47 声明式 BMad 工作流、Epic 50 控制面与工程化经验
- 方案事实源：`docs/goal-optimization-plan.md`

## 0. 总原则：交付由工作流声明表达，不写进代码

**Epic、Story、步骤、门禁、角色、审批、依赖、交付顺序——一律由工作流声明与工作流产物表达；
`src/` 只放与任何具体 Epic / Story 无关的通用引擎。**

### 声明面（唯一权威；改行为只改这里）

- `.heagent/skills/<workflow>/workflow.md` —— 步骤顺序与每步契约：`steps`、`input`/`output`/`next`、
  `checkpoint`、`validation`、`role`、`story_loop`、`max_parallel_stories`、`max_iterations`、
  `required_resources`、`checkpoint_mode`、`open_question_mode`、`max_rounds`、`auto_schedule`。
- 同包的 `step-NN-*.md` 与 `templates/{prompt-template,gate-template}.md` —— 每步提示词与门禁文案。
- 工作流产物 —— `brief.md`（需求）、`02-epics.md` 与 story 文档（Epic / Story 清单、依赖、写集、验收标准）。

### 引擎面（通用解释器）

只提供与具体内容无关的五件事：**读声明并校验** → **执行状态机** → **原子持久化** →
**经治理链执行工具** → **把声明中的事实投影成用户可见状态**。
`src/` 里不得出现具体 Epic 名、Story 名、步骤名或角色名的分支逻辑。

### 判定规则（新代码的准入条件）

任何 `src/` 改动都必须先回答：**「这件事声明层为什么表达不了？」** 答不出就不许加。
能靠新增 frontmatter 键、新增包内资源、新增 story 文档字段表达的，一律走声明。

### 推论（可验收的形态）

- 新增一个 Epic / Story / 步骤 / 门禁 / 角色 / 依赖，只需改声明与文档：既有词汇够用时 `src/` **零改动**。
- 只有需要**新词汇**时才可能动代码；新词汇必须①对所有 workflow 通用、②与具体 Epic 无关、
  ③缺省行为不变（老包不声明就退回现状语义）、④在 Story 里写明「声明层表达不了」的证明。

## 1. 产品目标

把 `/goal` 从「可恢复的严格流程编排器」升级为「可预检、可审计、可验证、可审批、可安全扩展的软件交付工作流」，
且升级方式本身遵守第 0 节：**能力来自声明，而不是来自为某个 Epic 写的代码**。

核心结果：

1. 运行前能回答「工作流是否完整、角色和模板是否可用」——答案全部由声明与包内资源推导。
2. 状态变化由显式事件和唯一转换表驱动，非法转换 fail-loud——事件与转换是通用词汇，不含具体流程知识。
3. Story 完成必须有真实命令、Git 变更和质量门禁证据，Markdown 报告不能冒充证据——要什么证据由 `validation:` 声明。
4. 用户批准、拒绝、修订和普通恢复具有不同语义并可追溯——某一步是否需要人工确认由该步声明。
5. 多种 workflow 模板继续共用一个 `WorkflowRunner`——模板本身就是声明包。
6. 受控脚本和安全调度只能建立在前述治理能力之上——脚本是包内资源，依赖与写集声明写在 story 文档里。

## 2. 当前基线

现有 `/goal` 已具备：声明式八步流程、步骤 / Story gate、checkpoint、恢复、逐 Story fail-closed 调度、
CLI / GUI / cron 共用推进用例、跨进程互斥与步骤事件。

**它已经证明第 0 节可行**：今天改流程行为就是改 `.heagent/skills/he-goal/workflow.md`（含内步骤契约）、
改提示词与门禁文案就是改同包模板——`src/` 不动。本 Epic 只是把这条既有事实推广到证据、门禁、
审批、模板、脚本与并行。

## 3. 功能范围（逐条标出「声明面」与「引擎面」）

| FR | 能力 | 声明面（主要交付物） | 引擎面（通用能力） |
|---|---|---|---|
| FR-1 | Goal 预检与统一状态视图 | `doctor_checks` / `status_fields`：该 workflow 跑哪些预检、展示哪些状态字段（未声明 = 引擎默认集）；预检输入 = `required_resources`、每步 `role`、包内 `templates/` | 「按声明 → 结构化报告（`pass`/`warn`/`fail`）」+「按声明 → 状态投影」；未知取值加载期 fail-loud；投影只读持久态（Epic 由 runner 记录并随 checkpoint 持久化，不读文档） |
| FR-2 | 显式 Workflow 事件与转换表 | workflow 声明用到哪些事件；某步是否需要人工介入由该步 `checkpoint` 决定 | 唯一转换表 + 事件发射（观测端口可空，sink 失败不改状态） |
| FR-3 | 结构化执行证据 | 某步要什么证据写在 `validation:`（命令 / 产物 / Git 路径 / 质量门） | 受治理执行 → 证据记录（cwd、命令摘要、退出码、耗时、输出 digest、失败分类；Git base/head 与变更集） |
| FR-4 | 真实质量 Gate 与 `/goal verify` | 门禁规则逐字来自 `validation:`；老包不声明结构化门禁则保持文本门禁 | 通用求值器 + `verify` 只检查或受控重跑，绝不执行实现步骤 |
| FR-5 | 步骤级审批与决策记录 | 「这一步要不要人工确认」由该步 frontmatter 声明，不在代码里写死第几步 | 追加式决策日志 + 独立事件（approve / reject / amend / resume 语义不同） |
| FR-6 | 多 workflow 模板与创建时冻结 | 交付物**就是声明包**（product / engineering / migration / security 等模板包） | 创建时把 id / revision / hash 写入 Goal 元数据；恢复时比对，漂移 fail-loud |
| FR-7 | 受控 GoalScript | 脚本是**包内资源**；可用动作集由声明与 facade 共同界定 | 受控 facade + 限额（步骤 / 深度 / 超时）+ 取消与恢复回到 Runner 事件 |
| FR-8 | Story 依赖图、写集与安全调度 | `depends_on` / `parallel_group` / `write_set` 写在 story 文档里 | 依赖闸门 + 每次一条 Story；写集是声明而非隔离边界，真并行前一律 fail-closed |
| FR-9 | 兼容性、集成验收与文档收口 | 旧 `brief.md` / `require.md` / `GOAL.md`、旧 checkpoint、旧 workflow 包继续可用（不迁移 JSON 形状） | 老声明缺字段时的缺省语义 + 文档收口只报未同步项，不碰受保护文件 |

## 4. 非目标

- 不把 Epic / Story / 步骤 / 门禁 / 角色 / 审批 / 依赖写进 Python。
- 不为某一个 Epic 或某一种流程在 `src/` 里开专用分支或专用模块。
- 不用脚本替代 `WorkflowRunner`。
- 不引入第二套 checkpoint 格式或第二个状态机。
- 不开放任意 Python 脚本作为默认能力。
- 不自动 Git commit；提交仍须用户明确确认。
- 不把 `SafetyGuard`、`PolicyEngine`、内置 sandbox 或 GoalScript facade 宣称为安全边界。
- 第一阶段不引入 Git worktree；写集无法证明安全时自动串行。

## 5. 成功标准

1. `/goal doctor` 对缺失角色、模板、资源漂移和不可用状态根给出结构化结果，且只读；检查项由 workflow 声明，
   未知取值在加载期 fail-loud。
2. 合法转换有黄金测试；非法转换保持原状态并抛类型化错误。
3. 未实际执行的命令不能通过要求命令证据的 Gate。
4. 旧 `brief.md` / `require.md` / `GOAL.md`、旧 checkpoint 和旧 workflow 包可继续恢复。
5. CLI、GUI、cron 对同一 Goal 使用同一状态 / 决策模型。
6. 脚本不能直接写 checkpoint、current 指针或绕过工具治理链。
7. 依赖不满足或未知时不得执行；即使写集声明不相交，也不得在未隔离的宿主回调中并行。
8. **新增一个 Epic / Story / 步骤 / 门禁 / 角色 / 依赖时，只需要改声明与文档**；证明方式是演示一次
   「只改声明、`src/` 不动」的增量（51-6 的模板包与 51-8 的集成验收各做一次）。

## 6. 交付顺序

```text
51-1 预检与状态视图
  → 51-2 显式事件与转换表
  → 51-3 结构化执行证据
  → 51-4 真实质量 Gate
  → 51-5 审批与决策记录
  → 51-6 多 workflow 模板与冻结
  → 51-7 受控脚本运行时
  → 51-8 安全并行、集成验收与文档收口
```

51-3 与 51-5 可在 51-2 完成后并行设计，但 51-4 依赖 51-3；51-7 必须等待证据、审批和 workflow 冻结语义稳定。
