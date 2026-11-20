---
title: 'Story 68.1 选择并配置文档生成工具'
type: chore
ticket: 1
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
  - 'scripts/build_docs.py'
  - 'mkdocs.yml'
---

## Intent

mkdocs 与 `mkdocs build --strict` 门已就位（票面勘误已认），缺的是「本地一键生成」与「可部署」：
现在只能记得那条命令，且没有把产物推到任何托管面。

**Approach：** 新增 `scripts/build_docs.py`（一次 `mkdocs build --strict` + 产物路径打印 + 缺 mkdocs 的安装诊断），
并在 `mkdocs.yml` 的 `site_dir` 口径上保持 `.heagent/tmp/mkdocs-site`（不入工作树）；
部署形态定 GitHub Pages（见 68.3）。

## Verify

- `python scripts/build_docs.py` 一条命令产出站点，缺依赖时给 `pip install mkdocs` 的显性提示（不 traceback 收场）；
- `mkdocs build --strict` 0 warning；
- 文档版本与代码版本一致：站点页脚/首页显示的版本取自 `heagent.__version__`（单一真源，不手工写）。

## Boundaries

- 不引入 mkdocstrings 等需要额外插件的 API 自动抽取（68.2 用 docstring 契约测试覆盖，不靠插件渲染）。
- 不改 `docs/` 的目录结构。

## Implementation（实测）

- 新增 `scripts/build_docs.py`：一条命令跑 `sys.executable -m mkdocs build --strict`，成功打印产物路径、
  页面数与 `version.txt`；缺 mkdocs 时先 `importlib.util.find_spec` 预检，打印 `Try: pip install mkdocs`、
  退出码 2、无 traceback。
- 版本注入用 mkdocs 官方 `!ENV` 标签（`pyproject` 传递依赖里的 `pyyaml_env_tag`）：脚本以 **AST** 读
  `src/heagent/__init__.py::__version__`（不 import 运行栈），经 `HEAGENT_DOC_COPYRIGHT` / `HEAGENT_DOC_VERSION`
  注入页脚与 `extra`；直接跑 `mkdocs build --strict` 时回退中性文案，原有门不依赖环境变量。
- 实测：`python scripts/build_docs.py` → EXIT=0，`version 0.9.0`，15 个 .html，页脚 `HeAgent v0.9.0`；
  裸 `python3`（无 mkdocs）→ EXIT=2 + 安装提示；`mkdocs build --strict` **0 warning**。
