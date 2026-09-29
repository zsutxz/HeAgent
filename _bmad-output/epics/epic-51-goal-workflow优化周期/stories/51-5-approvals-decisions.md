---
id: 51-5
title: 步骤级审批与决策记录
status: ready-for-dev
parent_epic: E51
priority: P1
depends_on: [51-2]
blocks: [51-6, 51-8]
created: '2026-09-29'
---

# Story 51-5：步骤级审批与决策记录

## 用户故事

作为用户，我希望批准、拒绝、修订和普通恢复具有不同语义，以便关键产品 / 架构决策不会被一次模糊的 resume 自动跨过。

## 声明面（主要交付物）

- 步骤 frontmatter 新增 **`approval: required`**（可带一句说明，如 `approval: required 架构冻结前需人工确认`）。
  - 未声明 = 该步不需要人工确认（**老包零行为变化**）。
  - 该步到达检查点时进入 `WAITING_USER`，且**只有人工决策**能推进。
- 决策记录是**工作流产物**（落在 goal 目录下），随 goal 一起持久化与恢复，不写进 workflow 包。
- 「第几步需要审批」只存在于该步的声明里 —— `src/` 中不得出现任何步骤名 / 步骤序号的审批判断（AD-13）。

## 引擎面（最小通用能力）

- 声明解析：`approval:` 进入 `WorkflowStepResource`；值非法时加载期 fail-loud。
- 追加式决策日志：每次 approve / reject / amend / resume 一条记录，重跑不覆盖历史。
- 独立事件：`approve`、`reject`、`amend`、`resume` 语义不同，不得互相顶替（AD-3）。
- CLI/GUI/cron 共用 `goal/application.py` 的同一应用服务；cron 不得自动批准人工 Gate。
- **为什么声明层表达不了**：决策记录是运行期事实（含时间、原文、影响范围），声明只能表达
  「要不要审批」；追加式存储与事件语义属引擎不变量。

## 验收标准

- workflow step 可声明 `approval: required`；未声明的步骤行为不变。
- 支持 `/goal approve`、`/goal reject <原因>`、`/goal amend <补充>`、`/goal decisions`。
- 决策记录包含 id、步骤、原文、时间、影响范围和结果，并追加式保存。
- reject / amend 不把步骤标记完成；重跑保留历史决策。
- `/goal resume` 保持兼容，但不能隐式等同批准。
- cron 不得自动批准人工 Gate；CLI / GUI / cron 共用同一应用服务。
- `src/` 中不存在按步骤名 / 序号判断是否审批的分支。

## 任务

- [ ] 在声明模型与加载器补 `approval:` 词汇（缺省 = 不需要审批；非法值 fail-loud）。
- [ ] 定义决策记录模型与追加式存储 / 读取协议（工作流产物位置）。
- [ ] 扩展事件与 transition 语义，避免入口层直接写状态（承接 51-2 的收敛结果）。
- [ ] 在 `goal/application.py` 实现决策应用服务（AD-14 证明：见「引擎面」末条）。
- [ ] CLI 输出继续走 `_echo`，GUI sink 行为一致。
- [ ] 增加拒绝后重跑、修订保留、cron 禁止自动批准和历史不覆盖测试。
- [ ] 负向验证：把 `resume` 当 `approve`、cron 自动批准、历史被覆盖时新测试精确变红。

## 验证命令（规划，执行时亲跑；引用不存在的文件按实测更正）

```bash
pytest tests/test_goal_decisions.py tests/test_goal_declarative_workflow.py tests/test_goal_message_sink.py -q
pytest tests/test_workflow_runner.py tests/test_workflow_resources.py -q
ruff check src tests
ruff format --check src tests
mypy src
mypy src --platform linux
```
