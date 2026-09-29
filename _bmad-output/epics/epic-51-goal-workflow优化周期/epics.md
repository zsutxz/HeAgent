---
stepsCompleted: [step-01-validate-prerequisites, step-02-design-epics, step-03-create-stories, step-04-final-validation]
status: final
inputDocuments:
  - docs/goal-optimization-plan.md
  - docs/frame.md
  - _bmad-output/epics/epic-51-goal-workflow优化周期/brief.md
  - _bmad-output/epics/epic-51-goal-workflow优化周期/ARCHITECTURE-SPINE.md
---

# HeAgent - Epic Breakdown（Epic 51：`/goal` 与 workflow 可信交付优化）

## Epic 51

把现有声明式 `/goal` 工作流升级为可预检、可审计、可验证、可审批、可安全扩展的交付系统，
同时保持 `WorkflowRunner`、checkpoint 与旧 Goal 的兼容性。

**交付形态（唯一口径，见 `brief.md` 第 0 节）**：Epic / Story / 步骤 / 门禁 / 角色 / 审批 / 依赖
一律由工作流声明与工作流产物表达；`src/` 只放与任何具体 Epic / Story 无关的通用引擎。
每条 Story 都必须能回答两个问题：

1. **声明面**：这条 Story 给工作流增加了什么声明词汇、什么包内资源、什么 story 文档字段？（主要交付物）
2. **引擎面**：为了让上述声明可执行，通用引擎需要的最小泛化能力是什么？（必须与具体 Epic / Story 无关）

第 2 问答不出「声明层表达不了」的，就不允许动 `src/`。

## Story 列表

| Story | 名称 | 依赖 | 状态 | 声明面（主要交付物） | 引擎面（最小通用能力） |
|---|---|---|---|---|---|
| 51-1 | Goal 预检与统一状态视图 | 无 | done（用户放行 2026-09-29；22 变异体 + 全量门全绿） | `doctor_checks` / `status_fields`：该 workflow 跑哪些预检、展示哪些状态字段（未声明 = 引擎默认集）；预检输入 = `required_resources` / 每步 `role` / 包内 `templates/` | 按声明执行通用检查注册表与字段渲染器；未知取值加载期 fail-loud；状态投影只读持久态（Epic 由 runner 记录并随 checkpoint 持久化） |
| 51-2 | 显式 Workflow 事件与转换表 | 51-1 | review（4 变异体 + 定向门全绿） | workflow 声明用到哪些事件；该步是否需人工介入由该步 `checkpoint` 决定 | 唯一转换表 + 事件发射（观测端口可空；sink 失败不改状态） |
| 51-3 | 结构化执行证据模型 | 51-2 | ready-for-dev | 某步要什么证据写在 `validation:`（命令 / 产物 / Git 路径 / 质量门） | 受治理执行 → 证据记录（cwd、命令摘要、退出码、耗时、输出 digest、失败分类；Git base/head 与变更集） |
| 51-4 | 真实质量 Gate 与 `/goal verify` | 51-3 | ready-for-dev | 门禁规则逐字来自 `validation:`；老包不声明结构化门禁即保持文本门禁 | 通用求值器 + `verify` 只检查或受控重跑，绝不执行实现步骤 |
| 51-5 | 步骤级审批与决策记录 | 51-2 | ready-for-dev | 「这一步要不要人工确认」由该步 frontmatter 声明，不在代码里写死第几步 | 追加式决策日志 + 独立事件（approve / reject / amend / resume 语义不同） |
| 51-6 | 多 workflow 模板与创建时冻结 | 51-4, 51-5 | ready-for-dev | 交付物**就是声明包**（product / engineering / migration / security 等模板包 + 各自 `workflow.md`、步骤、`templates/`） | 创建时把 id / revision / hash 写入 Goal 元数据；恢复时比对，漂移 fail-loud |
| 51-7 | 受控 GoalScript 与 ScriptRuntime | 51-6 | ready-for-dev | 脚本是**包内资源**；可用动作集由声明与 facade 共同界定 | 受控 facade + 限额（步骤 / 深度 / 超时）+ 取消与恢复回到 Runner 事件 |
| 51-8 | Story 依赖图、安全并行、集成验收与文档收口 | 51-3, 51-4, 51-5, 51-6, 51-7 | ready-for-dev | `depends_on` / `parallel_group` / `write_set` 写在 story 文档里；已批准的批次决策持久化 | 通用判定（依赖完成 + 写集不相交 + 无共享单写者产物 + 同 Epic + 独立 checkpoint，任一未知即串行） |

## FR 覆盖

- FR-1 → 51-1
- FR-2 → 51-2
- FR-3 → 51-3
- FR-4 → 51-4
- FR-5 → 51-5
- FR-6 → 51-6
- FR-7 → 51-7
- FR-8/FR-9 → 51-8

## 实施约束

1. Story 51-1 / 51-2 开工前先审查并吸收工作区已有实现（初版已以 `2bcd58c` 提交），不得覆盖既有接线。
2. **声明优先**：每 Story 的「引擎面」改动必须在该 Story 内写明「为什么声明层表达不了」；
   能由新增 frontmatter 键 / 包内资源 / story 字段表达的，改为只交付声明。
3. **新词汇必须通用**：新增的声明词汇对所有 workflow 成立、与具体 Epic 无关、老包不声明时行为不变；
   禁止在 `src/` 里出现具体 Epic 名、Story 名、步骤名或角色名的分支。
4. 每个 Story 的验证命令是规划口径，执行后才能登记实测结果；规划命令引用不存在的文件时按实测更正。
5. `WorkflowRunner`、checkpoint 写入口、工具治理链和 Git 提交授权纪律不可被 Story 局部方案改写。
6. 若 51-7 的宿主解释器脚本模式无法满足安全裁决，则允许只交付可信本地包模式，并把隔离 worker
   明确递延；不得伪称已隔离。
7. 交付完成时须各做一次「只改声明、`src/` 不动」的增量演示（51-6 加一个模板包；51-8 加一个
   Epic / Story / 依赖），作为第 0 节口径的验收证据。
