---
id: 51-5
title: 步骤级审批与决策记录
status: done
parent_epic: E51
priority: P1
depends_on: [51-2]
blocks: [51-6, 51-8]
created: '2026-09-29'
baseline_commit: 37dfd4a0fafa6521a29fb3b5c07cd0beba6e26d4
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

- [x] 在声明模型与加载器补 `approval:` 词汇（缺省 = 不需要审批；非法值 fail-loud；空白 / `none` / `null` 声明同样 fail-loud）。
- [x] 定义决策记录模型与追加式存储 / 读取协议（工作流产物位置：`<goal_dir>/decisions/`，`goal/decisions.py`）。
- [x] 扩展事件与 transition 语义，避免入口层直接写状态（承接 51-2 的收敛结果：新增 `APPROVAL_REQUIRED` / `USER_APPROVE` / `USER_REJECT` / `USER_AMEND` 四事件与五条转换）。
- [x] 在 `goal/application.py` 实现决策应用服务（AD-14 证明：见「引擎面」末条；`record_decision` + `pause_resume` 的 RESUME 记录）。
- [x] CLI 输出继续走 `_echo`，GUI sink 行为一致（新命令全走 `_echo` 漏斗；`/goal decisions` 读取在 goal 域锁内防撕裂读）。
- [x] 增加拒绝后重跑、修订保留、cron 禁止自动批准和历史不覆盖测试（含并发批次挂门、旧 checkpoint 兼容、审批轮次幂等键）。
- [x] 负向验证：把 `resume` 当 `approve`、cron 自动批准、历史被覆盖时新测试精确变红（2026-09-30 实测五条变异各自精确红，见下）。

## 验证记录（2026-09-30 实测）

```bash
# 定向（story 规划命令按实际文件更正后的等价集，全部通过）
.venv/Scripts/python.exe -m pytest tests/test_goal_decisions.py tests/test_goal_declarative_workflow.py \
  tests/test_goal_message_sink.py tests/test_workflow_runner.py tests/test_workflow_resources.py \
  tests/test_workflow_transition.py tests/test_events_jsonl.py tests/test_goal_status_view.py -q
# → 240 passed
# 全量：3503 passed, 14 skipped（含 51-5 新增 tests/test_goal_decisions.py 48 例）
# ruff check src tests → All checks passed！；ruff format src tests → 无剩余改动
# mypy src / mypy src --platform linux → Success: no issues found in 161 source files（双平台）
```

负向验证（变异即红，逐条实测后还原）：

| 变异 | 精确变红的测试 |
| --- | --- |
| `WorkflowRunner.resume` 去掉审批门守卫（resume 当 approve） | `test_resume_at_an_approval_gate_is_refused`（仅此一条红） |
| `_advance_checkpoint_decision` 去掉门守卫（cron/自动推进批准） | `test_auto_advance_never_approves_the_gate`（仅此一条红） |
| `DecisionStore` 独占创建 `open("x")` → `open("w")`（历史可覆盖） | `test_exclusive_create_closes_the_race_window`（仅此一条红） |
| checkpoint 幂等键的审批轮次退回「仅挂起时」判据（审查 #1 死锁回归） | `test_history_survives_reject_rerun_and_a_second_decision`（仅此一条红） |
| 删除 CLI prepare 的审批门分流（门上指 resume） | `test_goal_next_at_the_gate_names_the_decision_not_resume`（仅此一条红） |

## Suggested Review Order

**声明面：approval: 词汇**

- 步骤审批声明解析：空白 / none / null 声明一律 fail-loud，不静默吞门
  [`workflow_loader.py:176`](../../../../src/heagent/goal/workflow_loader.py#L176)

**引擎面：状态机与事件**

- 审批门挂起更新（单点清场 active_story，决策归因不漂移）
  [`workflow_runner.py:823`](../../../../src/heagent/engine/workflow_runner.py#L823)

- checkpoint 幂等键：approval_round > 0 即进 id（二轮决策不死锁）
  [`workflow_runner.py:1001`](../../../../src/heagent/engine/workflow_runner.py#L1001)

**引擎面：决策记录存储**

- 版本化决策记录（id/步骤/原文/UTC/影响范围/结果 + approval_round）
  [`decisions.py:65`](../../../../src/heagent/goal/decisions.py#L65)

- 追加式存储：独占创建、schema 门、路径安全 id
  [`decisions.py:187`](../../../../src/heagent/goal/decisions.py#L187)

**应用服务与 CLI**

- record_decision：append 先于 persist（决策先落账再落盘），resume 拒绝为决策
  [`application.py:641`](../../../../src/heagent/goal/application.py#L641)

- status 投影：awaiting_approval 分流推荐决策命令（不再指 resume）
  [`status_view.py:120`](../../../../src/heagent/goal/status_view.py#L120)

**外围：测试与文档**

- 48 条判据（二轮 reject/amend store 级、Story 挂门、cron 禁批、五变异锚点）
  [`test_goal_decisions.py:1`](../../../../tests/test_goal_decisions.py#L1)
