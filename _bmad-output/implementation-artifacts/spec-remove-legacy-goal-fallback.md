---
title: '移除不可达的旧 Goal fallback'
type: 'refactor'
created: '2026-09-02'
status: 'done'
review_loop_iteration: 0
baseline_commit: '51a4c56f48b372f3808b7f1638dbd93ef86871c7'
context: ['E:\\AI\\HeAgent\\src\\heagent\\cli.py', 'E:\\AI\\HeAgent\\tests\\test_goal_declarative_workflow.py']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 当前 `/goal` 运行时要求声明式 `workflow.md`，但 cron 入口仍保留仅供旧 goal board 使用的 fallback，并额外保留只服务该 fallback 的技能读取函数，增加死代码和维护歧义。

**Approach:** 删除 `_goal_cron_advance` 的旧 fallback 及其专用 `_goal_skill_text`，声明式 workflow 缺失或无效时沿用现有显性停止与 job 注销行为。

## Boundaries & Constraints

**Always:** 保持声明式 `/goal`、cron 成功推进、完成收口、缺失/无效 workflow 的错误输出和 job 清理行为不变；不迁移测试文件。

**Ask First:** 若发现旧 fallback 有仓内调用方或需要保留兼容 CLI，停止并确认。

**Never:** 不删除仍被声明式路径使用的 `_goal_session`、`_goal_active_md`、`_goal_read_md`、`_goal_auto_remove`；不修改 workflow 状态模型。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|-----------------------------|----------------|
| DECLARATIVE_AUTO | 有效 workflow.md 与 auto job | 执行声明式 step，完成后注销 job | 保持现有结果 |
| MISSING_WORKFLOW | workflow.md 不存在或无效 | 显性停止并注销该 job | 不回退旧 goal board |

</frozen-after-approval>

## Code Map

- `src/heagent/cli.py:1350-1355` — `_goal_skill_text`，仅被 cron fallback 使用。
- `src/heagent/cli.py:1754-1787` — `_goal_cron_advance`，声明式分支后仍保留旧 fallback。
- `tests/test_goal_declarative_workflow.py:82-110` — 声明式 auto 与 cron 收口测试。

## Tasks & Acceptance

**Execution:**
- [x] `src/heagent/cli.py` — 删除 `_goal_skill_text` 与 `_goal_cron_advance` 的旧 fallback，保留声明式错误/收口逻辑 — 消除死代码。
- [x] `tests/test_goal_declarative_workflow.py` — 运行声明式 auto、缺失 workflow 和错误 workflow 测试 — 证明行为保持。

**Acceptance Criteria:**
- Given 有效声明式 workflow，when cron 推进 goal，then 仍执行声明式 step 并在完成或失败时注销 job。
- Given workflow 缺失或无效，when cron 推进 goal，then 显性报错并注销 job，不读取旧 skill 或 goal.txt。

## Verification

**Commands:**
- `pytest tests/test_goal_declarative_workflow.py -q` — expected: 全部通过。
- `ruff check src/heagent/cli.py` — expected: 无 lint 错误。
- `git diff --check` — expected: 无空白错误。

## Suggested Review Order

- 先看 cron 声明式分支与错误收口
  [`cli.py:1754`](../../src/heagent/cli.py#L1754)
- 核对旧 skill fallback 已删除
  [`cli.py:1350`](../../src/heagent/cli.py#L1350)
- 查看声明式 auto 回归测试
  [`test_goal_declarative_workflow.py:82`](../../tests/test_goal_declarative_workflow.py#L82)
