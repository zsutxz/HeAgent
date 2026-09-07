---
title: '目标创建需求问卷交互'
type: 'feature'
created: '2026-09-07'
status: 'done'
review_loop_iteration: 0
baseline_commit: 'e8d38872548d75bbf588674a1242819b74cb770a'
context: ['E:/AI/HeAgent/src/heagent/cli.py', 'E:/AI/HeAgent/src/heagent/engine/workflow_runner.py', 'E:/AI/HeAgent/src/heagent/engine/workflow.py', 'E:/AI/HeAgent/tests/test_goal_declarative_workflow.py']
---

<frozen-after-approval reason="human-owned intent - do not modify unless human renegotiates">

## Intent

**Problem:** `/goal` 创建游戏目标时，需求澄清依赖模型自由提问，无法稳定收集对手类型、平台、规则和首版能力，导致目标可能在缺少关键产品决策时继续执行。

**Approach:** 在声明式 goal 的首次分析前增加确定性的需求问卷。交互终端逐题询问 Q1-Q4；含 AI 时追加难度和最长思考时间；答案持久化到 `GOAL.md`，并注入首个工作流步骤。非交互环境不猜测答案，目标保持可恢复的 `waiting_user`，用户可用 `/goal resume` 提交完整回答。

## Boundaries & Constraints

**Always:** 默认问卷仅在新建 goal 且尚无问卷答案时运行；所有回答写入现有 Goal 文档；选项输入必须校验；标准完整规则与简化 MVP、平台和对手类型必须明确；AI 追问仅在选择人机或两者时出现；自动 checkpoint 模式不能绕过未完成问卷。

**Ask First:** 无。

**Never:** 不把问卷答案放入独立状态文件；不让模型决定是否缺少这些关键字段；不在非 TTY 下隐式选择默认项；不改变已有 goal 的恢复语义和工作流顺序。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 交互新建 | 新 goal、TTY 可用 | 依次显示 Q1-Q4，必要时显示 AI 追问，保存完整答案后执行第 1 步 | 非法选项重新询问；Ctrl+C 保留目标并停止 |
| 非交互新建 | 新 goal、stdin 非 TTY | 不调用模型步骤，状态为 waiting_user，输出完整问卷格式和 `/goal resume` 提示 | 缺少回答显式阻塞 |
| resume 回答 | waiting_user goal，回复包含 Q1-Q4 | 解析并校验答案，写入 Goal 文档后继续第 1 步 | 格式/选项非法则保持 waiting_user 并指出缺失项 |
| 含 AI | Q1 选择人机或两者 | 追加基础难度和最长思考秒数问题并持久化 | 时间必须为非负数字；难度不能为空 |
| 已有答案 | GOAL.md 已有完整问卷 | 不重复询问，直接按现有状态恢复 | 损坏答案显式失败，不覆盖历史 |

</frozen-after-approval>

## Code Map

- `src/heagent/cli.py` -- goal 新建、resume、TTY 判断、回答持久化与步骤输入组装。
- `src/heagent/engine/workflow_runner.py` -- 保持现有 waiting_user/blocked 状态机，仅复用其持久化。
- `src/heagent/engine/workflow.py` -- 现有 WorkflowStatus 与 checkpoint 语义，作为恢复边界。
- `tests/test_goal_declarative_workflow.py` -- goal 声明式路由、checkpoint 和 resume 回归测试。

## Tasks & Acceptance

**Execution:**
- [x] `src/heagent/cli.py` -- 读取 Markdown 问卷定义、通用校验、内存收集、持久化和 resume 解析，并在首次步骤前强制完成 -- 防止关键需求缺失。
- [x] `.heagent/workflows/workflow.md` -- 定义游戏目标问卷、条件 AI 追问和数值约束 -- 使产品规则脱离 CLI 代码。
- [x] `tests/test_goal_declarative_workflow.py` -- 覆盖 TTY 问卷、AI 追问、非 TTY 阻塞、resume 完整/非法回答和不重复询问 -- 验证交互边界。

**Acceptance Criteria:**
- Given 新 goal 且 stdin 为 TTY，when 执行 `/goal new 做个太空游戏`，then 逐题询问并把答案写入 `GOAL.md` 后才运行第 1 步。
- Given Q1 选择人机或两者，when 问卷继续，then 追加基础难度和最长思考时间问题。
- Given stdin 非 TTY，when 创建 goal，then 不调用 SubAgent，状态保持 `waiting_user` 并显示可复制的问卷和 `/goal resume` 用法。
- Given waiting_user goal，when `/goal resume` 提供合法 Q1-Q4 回答，then 答案持久化且只执行一次第 1 步。
- Given 非法或不完整回答，when resume，then 保持 waiting_user，指出具体字段，不覆盖已有合法答案。

## Design Notes

问卷答案使用 `## 用户补充（User Responses）` 下的结构化 `### Questionnaire` 区块保存；普通 resume 文本仍按历史 Response 追加。解析优先读取问卷区块，避免把自然语言误识别为已完成问卷。

## Verification

**Commands:**
- `pytest tests/test_goal_declarative_workflow.py -q` -- expected: all goal workflow tests pass。
- `ruff check src/heagent/cli.py tests/test_goal_declarative_workflow.py` -- expected: no violations。

## Suggested Review Order

**Workflow Contract**

- Product questions live with the workflow.
  [`workflow.md:21`](../../.heagent/workflows/workflow.md#L21)

**Generic Runtime**

- Parse and validate Markdown declarations.
  [`cli.py:1035`](../../src/heagent/cli.py#L1035)

- Collect answers only in memory before persistence.
  [`cli.py:1147`](../../src/heagent/cli.py#L1147)

- Gate the first workflow step on a completed questionnaire.
  [`cli.py:1368`](../../src/heagent/cli.py#L1368)

**Verification**

- Cover non-TTY, resume, conditional questions, and invalid answers.
  [`test_goal_declarative_workflow.py:374`](../../tests/test_goal_declarative_workflow.py#L374)
