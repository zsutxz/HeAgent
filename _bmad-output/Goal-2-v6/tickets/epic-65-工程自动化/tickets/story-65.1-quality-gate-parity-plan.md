---
title: 'Story 65.1 配置 GitHub Actions 质量门禁'
type: chore
ticket: 1
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
  - 'scripts/quality_gate.py'
  - 'tests/test_ci_gate_parity.py'
---

## Intent

**Problem（勘差结论：本 entry 由「建设」降级为「勘差 + ratchet」）：** GitHub Actions 早已存在
（`ci.yml` 8 job + `codeql.yml`），票面「自动运行 `scripts/quality_gate.py`」按字面已经过度——
CI 没有调用那个脚本，而是在 `lint` / `coverage` / `goal-smoke` 三个 job 里**分别**执行同一批命令。

真正的缺口不是「有没有门」，而是**本地门与 CI 之间没有判据**：

- 本地 7 门（`contract snapshot` / `goal smoke` / 回归+覆盖率 / ruff check / ruff format / mypy / bandit）
  与 CI 的承接关系全靠人记；
- 代码注释里记着一次实测事故——本地门曾缺 bandit，「本地全绿、CI 全红」无从察觉；
- 反向也成立：CI 独有的 pip-audit / `mkdocs build --strict` 被删掉同样不会红。

**Approach：** 新增 `tests/test_ci_gate_parity.py`，把「本地门 → (CI job, 命令片段)」写成显式映射表，
断言三件事：

1. 映射表与 `quality_gate.COMMANDS` 的 label 集合**相等**（加门不接线 / 删门留死条目都红）；
2. 每条映射的命令片段在声明的 job 里**真的以完整片段形态出现**（右侧须为空白或行尾——
   否则 `mypy src/gov` 这类收窄会被子串匹配放过去）；
3. CI 独有两门（依赖漏洞扫描 / 文档构建）保持在位。

`quality_gate.py` 按文件路径用 `importlib` 加载（`scripts/` 不是包），不复制它的命令清单。

## Verify

- `pytest tests/test_ci_gate_parity.py -q` → 6 passed。
- 变异实测（改完立刻还原，还原后复跑仍 6 passed）：
  - `mypy src` → `mypy src/heagent`：`test_mapped_ci_commands_really_run` 红（**第一版用纯子串匹配时没红**，
    据此加了右侧边界）；
  - `bandit -r src/ -ll` → `true`：同一条断言红。
- `pytest tests/test_release_workflow_contract.py -q` 不受影响（`test_ci_job_count_is_pinned` 仍 8 job——
  本 story 只在既有 job 里加 step）。

## Boundaries

- **不改成 CI 直接跑 `quality_gate.py`**：本地门含 900s 超时守卫与 `--cov` 重跑，矩阵里重复跑一遍是浪费；
  CI 的分工（lint 失败即短路、coverage 单平台、benchmark 依赖 test）是有意设计。本 story 只补判据。
- **不新增 job**：`INV-9`（job 数恒为 8）由 `test_release_workflow_contract.py` 钉住。
- 断言走文本切块，不解析 YAML（与既有发布契约同一立场：要钉的是仓库里那几行）。
