---
epic: epic-68-文档与API
date: 2026-11-18
verdict: accepted-with-open-items
criteria: declared
headless: false
---

# Epic 68 Retrospective

> 路径约定：`tickets/story-68.*` 均相对 `_bmad-output/Goal-2-v6/tickets/epic-68-文档与API/`；
> 其余路径相对仓库根。实测为收口现场取证（2026-11-18，容器内 `.heagent/tmp/py311-venv-linux/bin/python`）。

## Epic summary

**Epic**：epic-68-文档与API（R8；3 story，全部新建）

**票态**：3/3 `done`，无 `dropped`。

| Entry | 交付 | 提交 |
|---|---|---|
| 68.1 文档生成工具 | `scripts/build_docs.py`（strict + AST 读版本 + 缺 mkdocs 安装诊断） | `31dfb55` |
| 68.2 docstring 覆盖 | `tests/test_api_docstrings.py`（12 个核心模块，99 处缺失补到 0，14 例） | `0302daa` |
| 68.3 自动生成与部署 | `.github/workflows/docs.yml`（构建 + Pages 发布，独立 workflow 不破 INV-9 的 8 job） | `31dfb55` |

## 收口现场修掉的两处静默失效

1. **部署分支与仓库事实不一致**：`docs.yml` 的 `push.branches` / deploy 的 `if` 只认 `main` / `master`，
   而本仓远端默认分支是 `feat/module-integration`（`origin/HEAD` 指向它，`ci.yml` 的一等分支也是它）
   ⇒ 日常推送下**构建跑了、发布被 `if` 静默跳过**，谁也不会收到告警。处置：两个分支列表都补
   `feat/module-integration`，并在注释里写明「两处不同步就会静默失效」。
2. **缺 `site_url`**：Pages 的 canonical 链接与 sitemap 没有真源。处置：`mkdocs.yml` 补
   `site_url: https://zsutxz.github.io/HeAgent/`。

## 门禁实测

```text
python -m mkdocs build --strict            → 0 warning（1.18 s）
python scripts/build_docs.py               → 构建成功，version 0.10.0，15 个 .html
pytest tests/test_api_docstrings.py -q     → 14 passed
pytest tests/test_release_workflow_contract.py -q → 9 passed / 1 skipped（INV-9 ci.yml job 数仍 8）
pytest -q                                  → 5208 passed / 51 skipped / 30 deselected / 1 xfailed
```

## 决策与刻意不做的事

- **不引 mkdocstrings**（68.1 Boundaries）：站点只承仓库内文档 + docstring 契约测试。理由是
  `network/` 与 `pub/` 的公开面本来就需要「散文式为什么/边界」而不是签名清单；机械渲染只会把
  没有信息的 `Args:` / `Returns:` 段落灌进仓库。
- **docstring 判据要求「非空 + 首行不是占位」而不要求 `Args:` / `Returns:` / `Raises:` 段**：
  本仓风格是散文式，参数由类型注解表达。
- **入口层（`cli/`、`gui/`）不在范围**：可读性由 CLI 输出与测试覆盖。
- **不新开 `ci.yml` 的 job**：INV-9 钉死 8 个 job，部署面只能另起 `docs.yml`。

## Open questions / 残留（已登记台账）

1. **A64（2026-11-18 闭合，用户裁定「开启」）｜Epic 68 的「API 文档」没有渲染产物**：Epic `Outcome` 写
   「MkDocs API 文档覆盖全部公开 API 并自动部署」，而原实现只有 docstring 存在性 ratchet。用户裁定**补渲染**
   后按「包页 + `show_submodules`」交付：
   - `docs/api/` 13 页（索引 + 12 个核心包），正文由 `mkdocstrings` 从 docstring 生成 —— 不做逐模块页，
     包内新增模块自动被 `show_submodules` 展开，避免「每加一个模块补一个 md 壳」的两份事实；
   - `mkdocs.yml` 加 `plugins`（search + mkdocstrings python handler，`filters: ["!^_"]` 只渲染公开成员、
     `docstring_style: google`、`show_source: false`），nav 增「API 参考」节；
   - 构建期依赖不进依赖树：`pip install mkdocs "mkdocstrings[python]"`；`scripts/build_docs.py` 预检三者并给
     安装提示，`ci.yml` 的 docs step 与 `docs.yml` 同步装；
   - 判据 `tests/test_api_docs_pages.py`（4 例：包页集合 == `src/heagent/` 非入口层包 / 每页一个
     `::: heagent.<pkg>` 且开 `show_submodules` / nav 登记全部页面 / 索引逐个链接）；
   - 站点侧实测 `mkdocs build --strict` 0 warning、28 页、4.3 s。
   闭合正文见 `_bmad-output/retrospective-all-cycles.md` §三。
2. **A65｜Pages 前置设置未验证**：仓库 Settings → Pages 的 Source 必须选 “GitHub Actions”，
   且从未跑过一次真实 `workflow_dispatch`。闭合判据 = run 绿 + `page_url` 可访问。
3. **版本注入只在 `scripts/build_docs.py` 路径生效**：裸跑 `mkdocs build --strict`（CI 的 docs 门）时
   `!ENV` 回退到中性文案 ⇒ 门禁不依赖环境变量，但也就**不校验**版本注入是否工作。属有意取舍。
