# BMad 设计记录

> 本文是历史设计背景，不是当前实现说明，也不是待办清单。
> 当前 `/goal` 的运行契约见 [`workflow.md`](workflow.md)，代码事实见 [`frame.md`](frame.md)。

## 保留原因

本文件记录 HeAgent 从 BMad 技能包和目标驱动开发方案演进到当前声明式工作流的过程，便于理解
为什么流程由 Markdown 承载、为什么运行机制与方法论分离，以及为什么 `workflow.json` 不能成为第二个状态看板。

## 当前结论

当前实现已经采用以下边界：

```text
用户 /goal
  -> cli_goal.py 读取 .heagent/workflows/workflow.md
  -> WorkflowRunner 校验顺序、输入、输出和 checkpoint
  -> 角色 SKILL.md + 当前步骤上下文注入 SubAgent
  -> 输出保存到 _he-output/goals/<goal-id>/
  -> 下一步骤或下一条 Story
```

- 工作流的步骤、角色、输入输出和检查点由 `.heagent/workflows/workflow.md` 声明。
- 角色的执行方法由 `.heagent/skills/<skill>/SKILL.md` 承载。
- `cli_goal.py` 只做确定性装配、路径约束、状态持久化和错误分支。
- `WorkflowRunner` 只做声明式步骤的顺序推进、Story loop、恢复和 checkpoint。
- Epic/Story 的结构由 `engine/artifacts.py` 与 `.heagent/workflows/templates/` 校验。
- 运行时状态在目标目录的 `checkpoints/` 中；全仓库规划状态仍由 `_bmad-output/sprint-status.yaml` 维护。

## 已落地的设计原则

1. 不在 Python 中复制一套敏捷方法论。改变流程先修改 `workflow.md`。
2. 确定性边界交给代码：顺序、路径、checkpoint、恢复、工具策略和错误状态不能交给 LLM 决定。
3. LLM 负责产出需求、设计、代码和验收证据；代码只校验声明的结构和运行结果。
4. 每个步骤或 Story 使用新的 SubAgent/RunContext；窗口重置只处理上下文，不删除服务端 LLM 缓存。
5. `SafetyGuard`、`PolicyEngine`、交互式审批和默认 sandbox 都是 defense-in-depth，不是 OS 安全边界。

## 历史方案与当前实现的差异

早期方案曾设想 `SkillRunner`、独立的 `WorkflowOrchestrator`、`he-*` canonical skill 迁移、
跨目标 TokenBudgetManager 以及更复杂的阶段状态机。相关设计文字保留在 Git 历史和 `_bmad-output/` 的
Epic/spec 中；当前代码不要根据这些历史段落推断未实现功能。

当前应以以下文件为准：

| 问题 | 当前事实 |
| --- | --- |
| 如何启动工作流 | `.heagent/workflows/workflow.md` |
| 如何推进一步 | `src/heagent/cli_goal.py` + `src/heagent/engine/workflow_runner.py` |
| 如何保存运行状态 | `src/heagent/engine/workflow.py` 的 checkpoint store |
| 如何校验 Goal/Epic/Story | `src/heagent/engine/artifacts.py` |
| 如何查当前架构和缺口 | `docs/frame.md` |
| 如何查历史 Epic/Story | `_bmad-output/README.md` 和 `sprint-status.yaml` |

## 维护规则

- 当前行为变更：先改代码和对应的 `docs/frame.md` / `docs/workflow.md`。
- 工作流方法论变更：改 `.heagent/workflows/workflow.md` 或角色 Skill，不在本文复制一份。
- 历史周期状态：只更新 `_bmad-output/` 的相应产物，不把历史计划改写成当前能力。
- 删除或合并文档时，必须保留一个明确的权威链接，避免出现两个互相漂移的说明。
