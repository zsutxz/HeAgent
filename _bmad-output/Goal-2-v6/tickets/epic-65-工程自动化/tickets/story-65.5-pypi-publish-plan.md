---
title: 'Story 65.5 实现 PyPI 发布自动化'
type: chore
ticket: 5
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
  - 'tests/test_release_workflow_contract.py'
  - 'tests/test_ci_gate_parity.py'
---

## Intent

**Problem（勘差结论）：** 发布自动化已经落地——`release` job 做 `python -m build` → `twine check` →
`pypa/gh-action-pypi-publish`（OIDC Trusted Publisher，零 secret），另有 GHCR + Docker Hub 多架构推送；
触发面（`v*` tag / `workflow_dispatch`）、审批门（`environment: release`）、零 secret（`id-token: write`）
三要素已由 `tests/test_release_workflow_contract.py` 钉住。

票面 verify 里**唯一没兑现的一件是「失败时发送通知」**：job 挂了以后 run 页面只剩一屏红字，
而失败时最要紧的判读是「PyPI 有没有已经吃下这个版本号」——PyPI 不允许同版本重传，判错方向就只能改版本。

**Approach：** 在 `release` job 末尾加 `if: failure()` 的 `Release failure summary` step：

- 写 `$GITHUB_STEP_SUMMARY`（run 页面直接可读），内容 = 失败版本号 + 两条重跑前必核事项
  （PyPI 是否已占用该版本 / 两处版本真源是否仍一致）+ run 链接；
- 通知通道**复用 GitHub 自带的工作流失败邮件**，不引入外部 webhook secret
  （引入 secret 会让「零 secret 发布」这条契约失真）。

判据：`tests/test_ci_gate_parity.py::test_release_failure_is_surfaced` 断言该 step 存在且写 summary。

## Verify

- `pytest tests/test_ci_gate_parity.py tests/test_release_workflow_contract.py -q` → 15 passed / 1 skipped。
- 只加 step、不新增 job ⇒ `test_ci_job_count_is_pinned`（8 job）保持绿。

## Boundaries

- 不改成 merge 自动发版（Step 04 决策 Q2 已作废该验收标准）。
- 不引入 Slack / 邮件 webhook：需要新 secret，与 OIDC 零 secret 口径冲突，收益不抵破坏契约。
- 不动 `twine check` / digest 锁定 / 多架构推送路径。
