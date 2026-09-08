# 当前敏捷工作流

本文只描述当前代码已经支持的声明式 `/goal` 工作流。可执行契约的唯一来源是项目内的
[`.heagent/workflows/workflow.md`](../.heagent/workflows/workflow.md)；本文是面向维护者的导航和边界说明，不复制那份契约。

## 权威关系

| 内容 | 唯一权威 | 代码职责 |
| --- | --- | --- |
| 工作流步骤、角色、输入输出、检查点 | `.heagent/workflows/workflow.md` | 读取、解析、校验并按声明执行 |
| 步骤方法论 | 步骤声明的 `role` 对应 `.heagent/skills/*/SKILL.md` | 把声明和上下文交给 SubAgent |
| Goal 身份与工作流产物 | `_he-output/goals/<goal-id>/` | 创建目录、保存输出、恢复 checkpoint |
| Goal/Epic/Story 结构契约 | `src/heagent/engine/artifacts.py` 与 `.heagent/workflows/templates/` | 解析和校验结构 |
| 运行时进度与恢复 | `<goal-dir>/checkpoints/` 下的 `workflow.json` | 保存状态，不取代规划看板 |
| 全仓库 Epic/Story 状态 | `_bmad-output/sprint-status.yaml` | 规划历史的状态记录；不是 `/goal` 运行时状态 |

代码不应重新实现一套 Epic/Story 方法论。新增阶段、角色、产物或验收规则时，优先修改
`workflow.md` 或对应 Skill；只有新增确定性执行机制时才修改 Python。

## 当前步骤

项目默认工作流目前包含六步：

1. `analyze-requirements`：分析需求并产出可验证的需求与故事拆分。
2. `define-product-scope`：形成 PRD 和有序 Epic/Story 提案。
3. `design-experience`：形成 UX、流程和可访问性要求。
4. `design-architecture`：形成架构、边界、约束和决策记录。
5. `clarify-and-route`：确认实现范围，不修改实现代码。
6. `implement-and-verify`：由 `bmad-agent-dev` 按 `story_loop: 02-epics.md` 每次实现一条 Story 并验证。

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
├── GOAL.md                         # Goal 身份和原始需求
├── 02-epics.md                    # 工作流声明的 Epic/Story 输入
├── step-01-...md                   # 非 Story 步骤输出
├── step-06-implement-and-verify/
│   └── s-1/report.md               # 每条 Story 的实现与验收报告
└── checkpoints/                    # WorkflowRunner 运行时 checkpoint
```

`.heagent/workflows/templates/` 提供 Goal、Epic、Story 的结构模板。历史规划、验收和 retrospective
仍归档在 `_bmad-output/`，不应被当作当前运行时配置。

## 修改工作流的规则

- 变更流程顺序或阶段职责：修改 `.heagent/workflows/workflow.md`。
- 变更角色执行方法：修改 `.heagent/skills/<skill>/SKILL.md`。
- 变更产物字段或父子关系：同步修改 `engine/artifacts.py`、模板和测试。
- 变更恢复、checkpoint、路径安全或工具执行：修改 `src/heagent/` 机制代码，并同步 `docs/frame.md`。
- 不要在 `cli_goal.py` 增加与 `workflow.md` 平行的业务流程分支。
