---
title: 'Story 65.2 配置 PR 自动测试'
type: chore
ticket: 2
created: '2026-11-18'
status: done
baseline_revision: 'ae831fe'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
followup_recommended: false
context:
  - '.github/workflows/ci.yml'
  - 'tests/test_ci_gate_parity.py'
---

## Intent

**Problem（勘差结论）：** `ci.yml` 的 `on:` 已含裸 `pull_request:`（无分支过滤），PR 上实际会跑
`lint` / `test`（3 OS × 4 Python）/ `coverage` / `benchmark` / `goal-smoke` / `dependency-review`——
「PR 自动测试」主体早已成立。票面写的「unit + integration + benchmark 全量」有一处**刻意偏离**：
`integration` job 带 `if: github.event_name == 'workflow_dispatch'`，因为它要真实
`OPENAI_API_KEY` / `ANTHROPIC_API_KEY`，而 fork PR 拿不到 secret（跑了也只会是跳过或空跑）。

缺口同样是「没有判据」：日后给 `pull_request:` 加分支过滤、或给某个测试 job 加 `if:` 事件过滤，
PR 门禁会静默变窄；反过来把 integration 顺手拉进 PR 会得到一片假绿/假红。

**Approach：** 在 `tests/test_ci_gate_parity.py` 追加两条断言：

- `test_pull_request_runs_the_test_surface`：`pull_request:` 必须存在且**不带** `branches:` 过滤；
  `test` / `coverage` / `benchmark` / `goal-smoke` 四个 job 不得出现 `if:`；
- `test_integration_tests_stay_manual_only`：`integration` 的 `if:` 必须含 `workflow_dispatch`、不含 `pull_request`。

## Verify

- `pytest tests/test_ci_gate_parity.py -q` → 6 passed（含本 story 两例）。
- CI job 集合不变（8 job），分支保护本身属仓库设置、不在代码内，票面「失败阻止 merge」的代码侧口径
  = gate 必跑 + 失败即红，由上面两条断言与既有 lint/test 失败语义共同保证。

## Boundaries

- 不改 `integration` 的触发面（密钥可得性没变）。
- 不引入 `pull_request_target`（会带来 fork 代码 + 写权限组合的安全面）。
