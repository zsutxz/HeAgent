---
stepsCompleted: [step-01-validate-prerequisites, step-02-design-epics, step-03-create-stories, step-04-final-validation]
status: final
inputDocuments:
  - docs/goal-workflow.md
  - docs/frame.md
  - _bmad-output/epics/epic-52-安全并行story执行周期/brief.md
  - _bmad-output/epics/epic-52-安全并行story执行周期/ARCHITECTURE-SPINE.md
  - _bmad-output/epics/epic-51-goal-workflow优化周期/stories/51-8-safe-parallel-integration.md
---

# HeAgent - Epic Breakdown（Epic 52：goal 工作流安全并行 Story 执行器）

## Epic 52

把 Story 51-8 递延的「可验证隔离执行器」补齐：让 `max_parallel_stories > 1` 在七项授权条件全部满足时
真实并发执行批内 Story（声明门控 + 写集围栏 + Git 审计三层），其余形态逐字节退回现有串行路径，
老回调 / 老 checkpoint / 老 workflow 包零破坏。

**不干涉论证（唯一口径，见 `brief.md` 第 0 节）**：授权并行的 Story 写集两两不相交 ⇒ 守规矩 Story
互不触碰；shell 绕过属声明违规，由审计事后检出 → 显性 FAILED + Goal 级并行授权单向撤销。
`max_parallel_stories` 永远只是上限，不是授权。

## Story 列表

| Story | 名称 | 依赖 | 状态 | 声明面（主要交付物） | 引擎面（最小通用能力） |
|---|---|---|---|---|---|
| 52-1 | 写集围栏原语 | 无 | review（2026-10-09 域内验证全绿；全量 22 失败为并发进程持锁环境噪声，stash 基线证明与改动无关） | （复用 story `write_set` 声明，零新增词汇） | PolicyEngine 路径预检支持 per-run write allowlist（`file_write`/`file_edit` 越集 BLOCKED、目录条目放行子树、缺省 = 现状放行）；SubAgent 增 `write_allowlist` 参数经 RunContext metadata 注入（reserved 防伪造） |
| 52-2 | 批次调度器与 Runner 并行语义 | 52-1 | review（2026-10-09 全量 3660 passed 干净全绿；三处设计缺口 TDD 抓出修正） | `max_parallel_stories` 语义定稿：上限 + 门控开关 | `StoryExecutionContext` 模型；批派生七条件纯函数 + gather 并发 + 按声明序记账/逐成员持久化 + 批=单 checkpoint 单元 + 撤销闩 + `workflow_story_batch_scheduled` 事件 + 第三参签名探测 |
| 52-3 | 宿主接线：执行上下文贯通、Git 审计与失败语义 | 52-1, 52-2 | planned | Step 06 写集完备性声明指导（随 52-4 文档一并定稿措辞） | StepExecutor 透传 execution；宿主 per-story 前后增量审计（tracked 判负 / untracked 警告 / 非 Git 跳过）+ `workflow_write_audit` 事件 + `write_violation` → 撤销闩 + 并行质量门锁串行化 |
| 52-4 | 声明面收口：loader 提示、技能包与文档 | 52-2（可与 52-3 并行） | planned | `workflow.md` Step 06/07 正文改写 + revision bump "2"；`templates/STORY.md` 三字段示例与写集完备性提示；验证工作区 per-story 子目录约定；`docs/frame.md` 事件表与围栏小节；`docs/goal-workflow.md` 并行语义 | `_parallel_limit` 警告改条件说明 INFO；`test_workflow_resources.py` 断言同步 |
| 52-5 | 集成验收与恢复矩阵 | 52-2, 52-3, 52-4 | planned | — | 并行全链集成样例（调度→围栏→审计→合并→恢复不重跑）；恢复矩阵 +revoked/+批中间快照形态；架构契约同步；全量质量门亲跑留痕 + 对抗式评审 |

## FR 覆盖

- FR-1 → 52-1
- FR-2 → 52-2
- FR-3 → 52-3
- FR-4 → 52-4
- FR-5 → 52-5

## 实施约束

1. 交付顺序 `52-1 → 52-2 → {52-3 ∥ 52-4} → 52-5`；52-1 必须先于 52-2（授权并行的前提是预防层存在）。
2. **授权七条件是脊柱**（`ARCHITECTURE-SPINE.md` §2）：任何实现不得增删条件或改变 fail-closed 回退方向；
   派生结果为 1 时必须逐字节走既有串行路径。
3. 批次成员**只推导不持久化**（AD-16）；checkpoint 唯一允许的新字段是 `story_parallel_revoked`（AD-2）。
4. 回调链（SubAgent 会话、质量门、审计）绝不进入 `goal_mutex`；批成员回调不得触碰 runner 状态
   （记账只在按声明序的后处理段做）。
5. 围栏走既有治理链零旁路（AD-6/AD-17）；禁止为围栏新建第二套文件工具通道。
6. 审计基线是 per-story 会话前后增量，**不得**用 HEAD diff（前序 Story 写入未提交，会误伤）。
7. 每个 Story 验证命令是规划口径，执行后才能登记实测结果；引用不存在的文件按实测更正。
8. 改 `engine/` 依赖方向或新增 pub 模型时同步 `tests/test_architecture_contracts.py`。
9. 52-4 改技能包必须 bump `revision`（he-goal 冻结契约），并在 story 内演示一次「只改声明、`src/`
   零改动」的批派生翻转（AD-13/14 验收）。
