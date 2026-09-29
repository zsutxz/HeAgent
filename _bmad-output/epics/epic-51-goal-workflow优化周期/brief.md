# Epic 51 产品简报：`/goal` 与 workflow 可信交付优化

- 建立：2026-09-29
- 状态：规划完成，待按 Story 实施
- 编号：Epic 51
- 周期目录：`_bmad-output/epics/epic-51-goal-workflow优化周期/`
- 上游：Epic 47 声明式 BMad 工作流、Epic 50 控制面与工程化经验
- 方案事实源：`docs/goal-optimization-plan.md`

## 1. 产品目标

把 `/goal` 从“可恢复的严格流程编排器”升级为“可预检、可审计、可验证、可审批、可安全扩展的软件交付工作流”。

核心结果：

1. 运行前能回答“工作流是否完整、角色和模板是否可用”。
2. 状态变化由显式事件和转换表驱动，非法转换 fail-loud。
3. Story 完成必须有真实命令、Git 变更和质量门禁证据，Markdown 报告不能冒充证据。
4. 用户批准、拒绝、修订和普通恢复具有不同语义并可追溯。
5. 多种 workflow 模板继续共用一个 `WorkflowRunner`。
6. 受控脚本和安全并行只能建立在前述治理能力之上。

## 2. 当前基线

现有 `/goal` 已具备：声明式八步流程、步骤/Story gate、checkpoint、恢复、同 Epic 有界并行、CLI/GUI/cron 共用推进用例、跨进程互斥与步骤事件。

当前工作区已开始但尚未提交的实现属于本 Epic 的 51-1/51-2：

- `/goal doctor` 初版；
- `WorkflowEvent`；
- 显式 transition table；
- `WorkflowRunner` 的部分状态迁移接线。

## 3. 功能范围

- FR-1：Goal 预检与统一状态视图。
- FR-2：显式 Workflow 事件和唯一转换表。
- FR-3：结构化执行证据模型。
- FR-4：真实质量 Gate 与 `/goal verify`。
- FR-5：步骤级审批和决策记录。
- FR-6：多 workflow 模板与创建时冻结。
- FR-7：受控 GoalScript/ScriptRuntime。
- FR-8：Story 依赖图、写集证明与安全并行。
- FR-9：兼容性、集成验收与文档收口。

## 4. 非目标

- 不用脚本替代 `WorkflowRunner`。
- 不引入第二套 checkpoint 格式或第二个状态机。
- 不开放任意 Python 脚本作为默认能力。
- 不自动 Git commit；提交仍须用户明确确认。
- 不把 `SafetyGuard`、`PolicyEngine`、内置 sandbox 或 GoalScript facade 宣称为安全边界。
- 第一阶段不引入 Git worktree；写集无法证明安全时自动串行。

## 5. 成功标准

1. `/goal doctor` 对缺失角色、模板、资源漂移和不可用状态根给出结构化结果，且只读。
2. 合法转换有黄金测试；非法转换保持原状态并抛类型化错误。
3. 未实际执行的命令不能通过要求命令证据的 Gate。
4. 旧 `brief.md` / `require.md` / `GOAL.md`、旧 checkpoint 和旧 workflow 包可继续恢复。
5. CLI、GUI、cron 对同一 Goal 使用同一状态/决策模型。
6. 脚本不能直接写 checkpoint、current 指针或绕过工具治理链。
7. 写集重叠、依赖不满足或元数据不足时不得并行。

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
