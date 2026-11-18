---
title: 'Story 68.3 配置自动化文档生成流程'
type: chore
ticket: 3
created: '2026-11-18'
status: done
baseline_revision: 'b4d0e79'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
followup_recommended: false
context:
  - '.github/workflows/docs.yml'
  - 'mkdocs.yml'
---

## Intent

`ci.yml` 的 8 个 job 里只有 docs build 门，没有部署；且 INV-9 钉死 `ci.yml` job 数恒为 8。

**Approach：** 新增独立 workflow `.github/workflows/docs.yml`：main push（文档/源码变更）触发
`mkdocs build --strict` 后经 GitHub Pages 发布（`actions/deploy-pages`）；不新增 `ci.yml` 里的 job。

## Verify

- `docs.yml` 在 main push 上触发，权限最小（`pages: write` / `id-token: write`），只用官方 pages action；
- 构建失败即不部署（build 与 deploy 分两个 step/job，deploy 依赖 build）；
- `tests/test_release_workflow_contract.py` 的 INV-9（`ci.yml` job 数 = 8）仍绿；
- 文档与代码版本一致：站点版本由 `heagent.__version__` 注入（与 68.1 同一口径）。

## Boundaries

- 不引入第三方部署服务（Read the Docs 需要外部账号）。
- 不在 PR 上部署（只在 main）。

## Implementation（实测）

- 新增 `.github/workflows/docs.yml`（不动 `ci.yml`）：`push` 到默认分支（含 `master`）+ 路径过滤
  （docs/**、mkdocs.yml、src/**、scripts/build_docs.py）+ `workflow_dispatch`；workflow 级权限最小
  （contents: read / pages: write / id-token: write）；`concurrency: group: pages`。
- `build` job 跑 strict 构建 + `upload-pages-artifact`；`deploy` job `needs: build` + `environment: github-pages`
  用 `actions/deploy-pages`；`if` 限定只在默认分支发布。
- 实测：`pytest tests/test_release_workflow_contract.py -q` → 9 passed, 1 skipped（INV-9 ci.yml job 数仍 8）；
  `tests/test_ci_gate_parity.py` → 8 passed。
- 仓库设置前提：GitHub Pages 的 Source 需选 “GitHub Actions” 才可部署。
