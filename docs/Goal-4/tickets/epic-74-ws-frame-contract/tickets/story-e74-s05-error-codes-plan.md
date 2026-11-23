---
ticket: 5
ref: 74.5
code: E74-S05
epic: epic-74-ws-frame-contract
status: built
baseline_revision: ae1809f90636366018ece3304efe9a9098ecff27
risk: low
hitl: false
covers: ["R4", "R7"]
---

# E74-S05 · 错误码台账与哑传输边界收口

## Tasks & Acceptance

- [x] 新增 `tests/network/test_ws_error_codes.py`（17 例，**零 src 改动**）：
  - [x] 七条 code（`unknown_project` / `project_unavailable` / `project_busy` / `run_conflict` / `total_inflight_limit` / `unknown_run` / `invalid_request`）逐条断言是 `HttpErrorCode` **既有**成员；
  - [x] 每条 code 在 `transport_errors.json` 的 `entries` 或 `unmapped_codes` 里有对应项（逐条读基线，不硬编码清单）；
  - [x] `network/` 对 `heagent.cli` / `heagent.config` / `heagent.pub.projects` / `heagent.engine` / `heagent.agent` 的**导入面**零命中（AST，含 `TYPE_CHECKING` 分支）；
  - [x] `network/` 里 `is_dir` 零命中（项目解析由注入端口负责，传输层不碰文件系统）；
  - [x] WS 侧五个模块（`ws_server` / `ws_commands` / `ws_protocol` / `ws_host` / `ws_auth`）都不导入 `network/http_server`（同层互不依赖，新拆出的 `ws_commands` 也在内）。

验收（对应 entry 的 `verify`）：
- 反射断言七条 code 的集合 ⊆ `HttpErrorCode` 全绿。
- 每条 code 在 `transport_errors` 基线里有条目。
- `network/` 的导入面与 `is_dir` 判据零命中。
- `pytest tests/test_architecture_contracts.py -q` 全绿（本 entry 未改任何边界）。

## Verification

| 命令 | 结果 |
|---|---|
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network/test_ws_error_codes.py tests/test_architecture_contracts.py -q` | **56 passed** |
| `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/network tests/test_architecture_contracts.py -q` | **709 passed, 1 warning** |
| `.heagent/tmp/py311-venv-linux/bin/ruff check src tests` | All checks passed |
| `.heagent/tmp/py311-venv-linux/bin/ruff format --check src tests` | 499 files already formatted |
| `.heagent/tmp/py311-venv-linux/bin/python -m mypy src` | Success: no issues found in 239 source files |

## Code Map

- `tests/network/test_ws_error_codes.py`（新）—— 2×7 参数化（既有成员 / 基线条目）+ 3 条边界判据。
- 未改任何 `src/` 文件。

## Design Notes

- **入口口径修正（与 entry 描述不符，已按正确口径实现）**：entry 的 `verify` 要求「`network/` 内六条 `content_search` 断言 0 命中」。实测 `heagent.config` 在 `network/` 有 **5** 处、`heagent.engine` 有 **4** 处命中，全部是 docstring/注释里的**说明性引用**（如 `http_console_protocol.py` 的「镜像 ``heagent.config.catalog`` 的同名常量」、`endpoints_tasks.py` 的「不得 import ``heagent.engine.tasks``」）。按纯文本搜会把正当注释判成违规，也无法表达「不得导入」这条真正的不变量 ⇒ 改成 **AST 导入面断言**（runtime 与 `TYPE_CHECKING` 一并覆盖），`is_dir` 则保持文本断言（实测 0 处）。同一条不变量在 `tests/test_architecture_contracts.py::FORBIDDEN_RUNTIME_IMPORTS` 有等价的全包断言，本判据是它在 WS 面附近的就近钉子，不是第二份真源。
- **为什么逐条读基线而不是硬编码**：`transport_errors.json` 的条目里带 `status`，硬编码 code 列表会在 76.6 重生成快照时悄悄失配；读基线则「条目存在」这件事永远是现测。
- **新模块也纳入边界判据**：74.3 拆出的 `network/ws_commands.py` 是新文件，最容易在「同层传输模块互不依赖」上漏检，所以本 entry 把五个 WS 模块一起列进 `test_network_still_has_no_http_transport_import_cycle`。
- **零 src 改动是结论，不是省事**：E74 引入的两条判定路径全部复用既有错误码与既有端口，这正是 epic R4 要求的「不新增错误码、不重生成快照」；若断言发现缺项，按 entry 描述应中止交 E75/E76 处置——实测无缺项。

## Plan Change Log

- 2026-11-23：宿主直接实现（预期零 src 改动、单文件测试）。首轮 `ruff check` 报一处 E501，`ruff format` 折行后复跑全绿；`pytest tests/network` 基线由 692 升到 709（新增 17 例）。
