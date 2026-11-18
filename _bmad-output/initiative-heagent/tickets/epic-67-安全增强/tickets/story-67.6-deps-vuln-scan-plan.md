---
title: 'Story 67.6 集成依赖漏洞扫描'
type: feature
ticket: 6
created: '2026-11-18'
status: done
baseline_revision: '0b1b156'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
followup_recommended: false
context:
  - '.github/workflows/ci.yml'
  - 'scripts/quality_gate.py'
  - 'tests/test_ci_gate_parity.py'
---

## Intent

CI 已有 `pip-audit` 步骤，但报告不落盘、不导出，也无法在本地门复现同一判定。

**Approach：** CI 的 pip-audit 步骤显式 `--strict --format json --output pip-audit.json`
（高危即失败），并把报告作为 artifact 上传；`scripts/quality_gate.py` 增加可选 `audit` 门
（默认不跑，避免本地无网即红）。

## Verify

- CI 里 pip-audit 步骤含 `--strict` 与 `--output`，报告 artifact 上传；
- 本地 `python scripts/quality_gate.py --with-audit` 能跑同一命令（无网时给出明确跳过/失败原因）；
- 门禁契约测试（`tests/test_ci_gate_parity.py`）仍绿（新增步骤不破坏映射表）。

## Boundaries

- 不更换扫描器（不引入 safety，避免重复）。
- 不把网络依赖的扫描放进默认本地门。

## Implementation（实测）

- 落点：CI `lint` job 的 pip-audit 步骤改为 `pip-audit --strict -r requirements.lock --format json --output pip-audit.json`，
  并新增 `Upload pip-audit report`（`if: always()`，artifact `pip-audit-report`）；去掉 ``continue-on-error``——
  依赖有漏洞即红，报告留证。
- 输入改用 `requirements.lock`（67.10）：当前环境是 editable 安装，`--strict` 会把 skip 判 fatal，锁文件是精确可复现输入。
- 本地：`scripts/quality_gate.py --with-audit` 跑同一参数面；默认门不含它（需联网索引）。`pip-audit.json` 进 `.gitignore`。
- 实测：`pytest tests/test_ci_gate_parity.py tests/test_quality_gate.py tests/test_release_workflow_contract.py -q` 全绿（job 数仍 8）。
