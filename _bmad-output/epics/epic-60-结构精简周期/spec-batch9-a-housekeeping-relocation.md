---
title: '批次 9 卡 A：housekeeping 整模块迁出 cli（迁回顶层）'
type: 'refactor'
created: '2026-11-06'
status: 'done'
route: 'oneshot'
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 保留策略家族（3 个 prune 实现 + `run_housekeeping` 编排，344 行）住在 `src/heagent/cli/housekeeping.py`——业务规则住在入口层包，违背「入口层调一切但不持业务规则」的 DAG 语义；且该模块本就非入口模块（docstring 自称「CLI 辅助层」），2026-09-26 七个平铺 cli*.py 收编入包时被裹挟入 cli/。

**Approach:** 行为零变化的纯文件搬移：`src/heagent/cli/housekeeping.py` → `src/heagent/housekeeping.py`（顶层模块，2026-09-26 迁入 cli/ 前的原住址），缝与契约引用随迁同步，`test_architecture_contracts.py` 两个受影响断言同步，frame.md 路径引用与目录树同步。

</frozen-after-approval>

## Implementation Notes

<!-- Agent-owned. Append-only during implementation: decisions made, files touched, surprises encountered. Leave empty at planning time; oneshot 路线：调查结论全部内联在本节，实施时不再重复调查。 -->

**调查结论（2026-11-06，HEAD 83b2f22）：**

- 模块自述「属于 CLI 辅助层（与 cli.py 同侧），不参与 engine 依赖 DAG」——非入口模块，09-26 收编时被裹挟。本次迁回顶层是 09-26 收编的**细化**（入口模块留 cli/，辅助模块迁回），不是推翻该裁定。
- 全调用方清单（grep 全仓核实）：`tests/test_housekeeping.py`（:19 `from heagent.cli import housekeeping as hk`、:23 四符号导入、:236 patch 字符串、:1 docstring、7 处 caplog logger 名 `heagent.cli.housekeeping` :212/330/347/434/446/460/488）；`src/heagent/gui/cli.py:80`、`src/heagent/cli/console.py:73`（均 `from heagent.cli.housekeeping import prune_runtime_artifacts_best_effort`）；`cli/console.py:70` docstring 路径引用。
- 唯一 patch 缝：test_housekeeping.py:236 patch 字符串 `heagent.cli.housekeeping.run_housekeeping` → 迁后 `heagent.housekeeping.run_housekeeping`。
- `logging.getLogger(__name__)` ⇒ 搬移后 logger 名变 `heagent.housekeeping` ⇒ **7 处 caplog logger 字符串必须随迁**（漏一处即红，是本卡的最小天然验收）。
- 受影响契约测试两处：`test_entrypoints_do_not_duplicate_runtime_store_paths`（:621 列表项 "cli/housekeeping.py" → "housekeeping.py"，模块路径前缀 SRC 不变）、`test_cli_package_layout_is_pinned`（:704-720 pinned 15 名列表删 "housekeeping"）。
- frame.md 同步三处：:468 `cli/housekeeping.prune_sandbox_dirs` 路径引用 → `housekeeping.prune_sandbox_dirs`；:1528 cli 目录树行删除（「2026-09-26 自顶层迁入」注明迁回 2026-11-06）；:161 模块表行「顶层 housekeeping.py」迁回后自愈（不动）。
- 落点理由（防再漂移）：pub 不可行（import 扇出 config+context+pub+tools，pub 是最底层）；顶层模块身份：文件在 `src/heagent/` 根，`__name__` = `heagent.housekeeping`。
- 验收门：pytest 全量（不带 cov，唯一已知环境红 test_build_ws_server_config_maps_settings_and_overrides 在案）+ ruff check + ruff format --check + mypy src。
- 提交呈报制：信息+文件清单待用户明确同意。

**实施记录（2026-11-06）：** git mv 落位 + 13 处同步补丁全中；目标测试 60 passed + ruff/format/mypy 清；全量 4311 passed（唯一红=在案环境红）。

**实施勘误（Blind Hunter 审查后）：** 前期 grep 模式 `cli\.housekeeping`（转义点号）漏掉斜杠形态 `cli/housekeeping` 的 5 处文档/docstring 引用（session.py:4,34 / container.py:421 / frame.md:1486,785 / sandbox.md:146）——已全部随迁修正，仓内陈旧路径引用 grep 归零。

## Review Triage Log

| # | 发现 | 裁定 | 依据 |
|---|---|---|---|
| 1 | src 三处 docstring 陈旧 `cli/housekeeping` 路径 | high→已修 | 同步漏网（grep 模式漏斜杠形态），补丁修正 |
| 2 | frame.md:1486/:785 陈旧引用 | high→已修 | 同上；:785 系模块列举非路径，改列举项 |
| 3 | docs/sandbox.md:146 不在调用方清单 | high→已修 | docs 全目录未入前期 grep 面，补丁修正 |
| 4 | 契约覆盖回归：迁出 `heagent.cli` 包根伞后反向依赖断言形式绕过 | high→已修 | 实证：_ENTRY_LAYER_MODULES 按 `_heagent_root` 包根匹配；按 goal 先例显式登记 `heagent.housekeeping`（含三行理由注释） |
| 5 | frame.md 树注释「不参与 engine 依赖 DAG」与契约新状态矛盾 | medium→已修 | 与 #4 同根：登记契约表后旧口径失真，改「下层不得反向导入」 |
| 6 | frame.md:161 历史表行迁移后错位 | low→已修 | 行内注「2026-11-06 迁回顶层」保历史 |
| 7 | console/gui 调用方 scope 注释漏两类目标 | low→已修（用户裁定改判） | 两处注释补齐五类目标口径 |
| 8 | 模块自称「CLI 辅助层」与新住址矛盾 | low→已修(并入#5) | docstring 重写为「启动期维护模块」契约口径 |
| 9 | prune_runtime_artifacts_sync RuntimeError 兜底 4 键 dict | medium→已修（用户裁定改判） | 兜底补第 5 键 containers:0 + 新增兜底形状钉测试（事件循环内 RuntimeError 路径零覆盖→已钉） |
| 10 | 测试 docstring「三类」实为五类 | low→已修 | 该行在本卡改动面上，顺手修正 |
| 11 | spec 调查清单不完整 + 未跟踪 | medium→已修 | 本节勘误补记；spec 随本卡提交（implementation-artifacts 有 tracked 先例） |
| 12 | 测试文件 hk 别名+直导入双行冗余 | low→已修（用户裁定改判） | 17 个调用点统一走 hk. 别名，直导入行删除 |

