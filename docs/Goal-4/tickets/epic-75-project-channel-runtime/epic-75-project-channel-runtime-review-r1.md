---
type: review
code: E75-R1
epic: epic-75-project-channel-runtime
review_loop_iteration: 0
lens: 规格与实现对账（bmad-code-review）
reviewed_at: 2026-11-23
head: da29790d
---

# E75 收口三审 · R1 规格与实现对账

## 范围

**改动面**：`git diff --stat 604b4fb4..HEAD` = 32 文件 / +2411 −74，8 个提交（`0de2a1c3` … `da29790d`）。

- 源码 9 个：`pub/projects.py`(+110)、`network/{ws_protocol,ws_commands,ws_server,ws_host,http_protocol,http_server/pipeline}.py`、
  `cli/{ws_project_adapter,http,http_config}.py`、`web/app.js`(+1)
- 测试 7 个：`tests/network/{test_ws_project_commands(+338),test_ws_project_submit(+109),test_ws_event_contract,test_http_protocol}.py`、
  `tests/{test_ws_project_adapter(+254),test_http_console_project_run(+235),test_project_registry_health(+86),test_cli_http_lifecycle(+110),test_architecture_contracts}.py`
- 基线与文档：`tests/fixtures/contract_baselines/{exception_types,transport_errors}.json`、`docs/{errors,framework}.md`、6 份 plan + epic 文件

**判据来源**：epic 的 R1–R7 / Outcome / Done when / Notes；六份 plan 的 `## Verification`；
`architecture-ws-remote-project-channel.md`（I1/I2/AD-2/错误码表）。

**本轮实跑命令与结果**

| 命令 | 结果 |
|---|---|
| `pytest tests/network tests/test_architecture_contracts.py tests/test_ws_project_adapter.py tests/test_project_registry_health.py tests/test_http_console_project_run.py tests/test_cli_http_lifecycle.py -q` | 792 passed, 1 warning（32.32s） |
| `pytest tests/network -q`（首跑） | 1 failed / 705 passed（`test_build_ws_server_config_autofind_starts_from_ws_port`，端口自动探测用例） |
| 同上单跑 / 二次全跑 | 1 passed / 706 passed（与 plan 声称一致） |
| `pytest tests/test_http_console_project_run.py -q` / `tests/test_cli_http_lifecycle.py -q` | 5 passed / 14 passed（与 plan 同值） |
| `python scripts/contract_snapshot.py --check` | 五份全 `[OK]`，exit 0 |
| `len(list(HttpErrorCode))` | 36（与 `framework.md` 声称一致） |
| 自写探针（真 console + 真 adapter + 坏注册表，仅落 `.heagent/tmp/`） | 见发现 1 / 3 / 12 |

## 发现

| # | 严重度 | 位置 | 现象 | 正确口径 | 谁守着 / 处置 |
|---|---|---|---|---|---|
| 1 | **High** | `pub/projects.py:193-206`（`find` → `load` fail-soft）、`:331-333`（写路径抛 `server_error`）、`cli/http_console.py:786-791`、`network/http_protocol.py:92` | **R5 的「提交径 fail-loud 回 `project_registry_unreadable`」没有生产来源**：`grep PROJECT_REGISTRY_UNREADABLE src/` 只命中枚举、状态表、JS 文案与测试，无任何代码 raise。注册表损坏 ⇒ `find()` fail-soft 空表 ⇒ `_project_entry` 抛 `unknown_project`。探针实测（坏 JSON + 真 console + 真 adapter）：`ensure_available` 与 `start_project_run` 均回 `unknown_project` | 架构文档把「不区分 `unknown_project` 与 `project_registry_unreadable`」列为**被拒替代 (c)**；R5 要求两者可区分 | **无人守**（三处用例全用桩抛该码 ⇒ 假绿）。**当轮落改**：适配器在提交径前置健康探针，`unreadable` ⇒ 抛 `project_registry_unreadable`；补真注册表用例 |
| 2 | Medium | `cli/http.py:377-379`（`lambda: console.registry.health().code`）→ `pub/projects.py:155-172`（`Path.read_text` 同步） | 健康探针在**事件循环里同步读盘**，与控制台 `list_projects` 的 `asyncio.to_thread` 纪律相反；单帧 = 2 次读注册表（list 走线程池 + health 走循环），两次读之间可漂移 ⇒ 帧内容与 `registry_state` 非同源快照 | 探针也 `to_thread`，或由一次读同时给出 entries + state | 无用例真调该闭包。**当轮落改**「`to_thread` 半步」；「单次读单源」进延期项 |
| 3 | Medium | `tests/test_ws_project_adapter.py:105-118`、`tests/test_project_registry_health.py:36-56` | **R1 的「顺序与 `ProjectRegistry.list()` 逐位一致」与「32 上限」缺可执行判据**：adapter 用例只比对假 console 给的顺序；32 边界唯一用例是「33 条 ⇒ unreadable」，没有「恰 32 条全量可见」 | 两项都要能跑 | 无守卫。**当轮落改**：补真注册表顺序用例（`default` 末位 + `last_opened_at` 倒序）与 32 条边界用例 |
| 4 | Medium | `tests/test_http_console_project_run.py:152`、`tests/test_ws_project_adapter.py:54` | **R3 的六项落点只在 console 层被证**：WS 入口（帧 `project_id` → adapter → console）整链无真件用例，adapter→console 只在假 console 上验 ⇒ 「带 `project_id` 的 run 六项落点」是组合推理 | R3 主语是「带 `project_id` 的 run」，应有一例从集合级端点发 `run` 落到项目根 | 无守卫。**进延期项**（端点级 fixture 成本高，与 E76-S05 的 ADR-005 五步串跑同面） |
| 5 | Medium | epic R2 正文；实测 `pub/projects.py:189/215/247/261/359`、`cli/dialogs.py:181`、`cli/slash.py:173` | **R2 票面文字在 HEAD 上为假**：R2 写「`heagent.cli` / `heagent.pub.projects` / `heagent.engine` / `heagent.agent` 恒 0 命中 `is_dir`」，实测 cli 5 处、pub.projects 5 处（全部在 `604b4fb4` 已存在）。真口径是架构 `I2` = 只有 `network/` 0 命中 | 按 I2 写 | **宿主复核纠正**：`network/` 那半**已有**机器守卫（`tests/network/test_ws_error_codes.py:112` 的 AST 断言，E74-S05 交付），评审的「无机器守卫」不成立。**当轮落改**：R2 票面措辞订正进 epic Notes（Requirements 冻结，走 Notes 记口径） |
| 6 | Low | epic R7 正文「两处 `build_ws_servers` 调用（`:449` / `:789`）」；实测 `cli/http.py:492` / `:843` | 票面行号是改动前位置，改后已漂 | 票面写符号定位（`build_http_service` / `http_server_cmd`） | 文档级。**进延期项**（epic Requirements 冻结，走 Step 06 重切才有意义） |
| 7 | Low | epic `## Done when` 第 4 条 vs R5 | epic 自相矛盾：Done when 写「列表**空表**」，R5 写「`list()` 仍回 `default` 一条」。实测帧里是 `['default']` + `registry_state=unreadable` ⇒ 按 R5 落地，Done when 的「空表」为假 | 以 R5 为准 | `tests/test_project_registry_health.py:60-62` 守 R5 口径。**当轮落改**：epic Notes 记口径（不改冻结的 Done when） |
| 8 | Low | `pub/projects.py:208` docstring vs `:222` 实现 | docstring 写「`default` 恒在**首位**」，实现 `return [*registered, entries[0]]` 是**末位**（= N4 口径） | 「`default` 恒在末位」 | 无守卫。**当轮落改**（纯文案） |
| 9 | Low | `story-e75-s06-closeout-plan.md` 两处「四份契约基线」 | 基线自 75.1 起是 **5 份**（含 Epic 70 的 `error_codes.json`），同批 plan 内两套计数 | 统一 5 份 | plan 文本。**当轮落改**（s06 plan 两处） |
| 10 | Low | `tests/network/test_ws_server.py::test_build_ws_server_config_autofind_starts_from_ws_port` | plan 的 `706 passed` 首跑不重现（1 failed / 705 passed），单跑与二次全跑均绿 ⇒ 端口自动探测用例对环境敏感 | 按 `docs/testing.md` 口径登记为环境噪声 | 无守卫。**进延期项**（非本 epic 引入） |
| 11 | Low | `network/ws_server.py:508/622`、`ws_commands.py:113`（`run` 同款另三处） | 拒绝文案逐字复制 3 份 ×（`run` / `projects`），三端点拒绝分支结构同样三份 | 提一个 `_only_on_collection(command)` 帮助函数 | 用例只断言 `in` 子串，文案漂移不会红。**进延期项**（跨 E74/E75 的既有形态） |
| 12 | Low | `cli/ws_project_adapter.py:65-77` | `ensure_available` 借 `get_project_config` ⇒ 每次提交多跑一次 `build_config_report` + 构 per-project 引擎；探针确认无落盘副作用，但这是巧合而非契约 | 把「会构造运行时并读四层配置」写进端口义务 | 无守卫。**进延期项** |

## Requirement 对账表

| Req | 交付证据（代码行 + 判据用例） | 结论 |
|---|---|---|
| **R1** 三键 / `path` 计数 0 / 顺序 / 32 上限 | `ws_protocol.py:215-247`（两个模型，`extra="forbid"`）、`ws_project_adapter.py:43-55`（只取三字段）；判据 `test_ws_project_adapter.py:87-102`、`test_ws_project_commands.py:296-310`。顺序 / 32 上限原无判据（发现 3） | 部分 → **落改后已交付** |
| **R2** 真源不扫描盘 | `network/` 零 `is_dir`（实测 0）、`ws_project_adapter.py` 无 `Path`/`is_dir`；`test_architecture_contracts.py:82-95` 禁 import `pub.projects`、`test_ws_project_adapter.py:240-248`（AST + 文本）。票面另半为假（发现 5） | 部分 → **落改后按 I2 口径成立** |
| **R3** 六项落点全在项目根 | `http_console.py:642-664` / `:794-807`；判据 `test_http_console_project_run.py:130-197`（六项逐项 + 两项目不串味 + 启动根零新增）。WS 端到端缺一例（发现 4） | 已交付（console 层）/ 端到端进延期项 |
| **R4** 会话二分 + 帧无 `session_id` | `http_console.py:809-830`、`SubmittedRun` 两字段、`ws_project_adapter.py:57-63`；判据 `test_http_console_project_run.py:200-220`、`test_ws_project_adapter.py:131-143`、`test_ws_project_submit.py:322-341` | 已交付 |
| **R5** 列表 fail-soft / 提交 fail-loud | 列表径 `pub/projects.py:155-182` + `test_project_registry_health.py` 6 例；提交径原回 `unknown_project`（发现 1） | 部分 → **落改后已交付** |
| **R6** 帧转译单源 | `ws_commands.py:160-177` / `:239-252` / `:196-215`；判据 `test_ws_project_submit.py:178/198`、`test_ws_project_commands.py:214-228`。`cancel_run` 子句按 Notes 裁定不实现 | 已交付（除已裁定子句） |
| **R7** 装配 + 错误码逐字透传 | `cli/http.py:355-380/492/843`、`http_config.py:237/315-319` → `ws_host.py:225/275-296/352-374` → 两端点；`ws_project_adapter.py:31-33`；判据 `test_cli_http_lifecycle.py:474-565`、`test_ws_project_adapter.py:157-196`、`test_ws_project_submit.py:344-372`、`test_http_console_project_run.py:224-238` | 部分（`project_registry_unreadable` 原只在桩上成立）→ **落改后已交付** |

## 落改（当轮）

| 落改 | 文件 | 判据 |
|---|---|---|
| 提交径前置健康探针：`unreadable` ⇒ `HttpRunConflictError(code=project_registry_unreadable)`，**不**退化成 `unknown_project`；探针经 `asyncio.to_thread` 执行 | `src/heagent/cli/ws_project_adapter.py` | `tests/test_ws_project_adapter.py` 新增真注册表两例（坏 JSON ⇒ 两方法同码 / 好注册表 ⇒ 正常提交） |
| 真注册表顺序与 32 上限判据 | `tests/test_ws_project_adapter.py` | `default` 末位 + `last_opened_at` 倒序逐位一致；恰 32 条全量可见 |
| `list()` docstring 口径（`default` 恒在末位） | `src/heagent/pub/projects.py` | 纯文案 |
| s06 plan 基线份数「四份」→「五份」 | `docs/Goal-4/tickets/.../story-e75-s06-closeout-plan.md` | — |

## 结论

**有条件的通过**：阻塞项（发现 1，High）当轮落改并重跑门禁；发现 2/3 的当轮半步落改、发现 5 的口径订正，
发现 4/6/10/11/12 进 `brief.md` 延期项；无遗留 Critical / High。
