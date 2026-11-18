---
title: 'Story 68.2 为核心模块补充 docstring'
type: chore
ticket: 2
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
  - 'tests/test_api_docstrings.py'
  - 'src/heagent/pub/'
  - 'src/heagent/network/'
---

## Intent

核心模块的公开 API 大多已有散文式 docstring，但**没有判据**：新增公开符号漏写文档不会红，
也不清楚覆盖面。票面要求「公开 API docstring 补齐、格式符合工具要求」。

**Approach：** 把「公开 API」定义成可枚举的集合，并落成 ratchet 测试
`tests/test_api_docstrings.py`：`src/heagent/` 下除入口层（`cli/`、`gui/`）外，模块级非下划线
函数/类 + 类的非下划线方法（含 property、pydantic 钩子、Protocol 声明）都必须有非空 docstring，
且首行不是 `TODO`/`FIXME` 这类占位。

刻意**不**要求 `Args:` / `Returns:` / `Raises:` 段：本仓 docstring 是散文式（写「为什么/边界」），
参数细节由类型注解表达；机械补段落会与既有风格冲突且不增加信息。

## Verify

- `pytest tests/test_api_docstrings.py -q` → 14 passed（缺失清单从 99 处降到 0）；
- 判据自带「扫描面非空」守卫（`pub/` 至少 20 个公开符号），避免目录改名后退化成假绿；
- 只加 docstring，不改任何函数签名/逻辑：全量 `pytest -q` → 5203 passed；
  `ruff check` / `ruff format --check` / `mypy src` 全绿。

## Boundaries

- 入口层（`cli/`、`gui/`）不在范围内（可读性由 CLI 输出与测试覆盖）。
- 不引入 mkdocstrings 自动抽取（68.1 的站点只承仓库内文档 + 这份契约测试）。
- 发现的「行为本身说不清」的函数只补事实描述，不借机改逻辑。

## Implementation（实测）

- 判据：`tests/test_api_docstrings.py`（14 例）——99 个缺失公开符号补到 0；扫描面 = 12 个核心模块
  （agent/config/context/cron/engine/events/memory/network/providers/pub/skills/tools）。
- 补充分布：`pub/workspace.py` 15 个路径 property、`pub/projects.py` 7 个登记表方法、
  `network/ws_server.py` 10 个 Protocol 声明、`skills/skill_packages.py` 9 个资源读取/判定方法、
  `tools/sandbox/*` 13 个 `run` 与 bind/get/reset 钩子、`network/http_console_protocol.py` 等其余 45 处。
- 实测：`pytest tests/test_api_docstrings.py -q` → 14 passed；全量 `pytest -q` → 5203 passed；
  `ruff check` / `ruff format --check`（499 files）/ `mypy src`（229 files）全绿。

