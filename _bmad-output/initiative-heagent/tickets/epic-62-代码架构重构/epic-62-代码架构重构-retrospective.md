---
epic: epic-62-代码架构重构
date: 2026-11-18
verdict: accepted
criteria: declared
headless: false
---

# Epic 62 Retrospective

## Epic summary

**Epic**：epic-62-代码架构重构（R1 拆大文件 / R3 去重、降嵌套、消魔法数字；纯 `src/` 结构面，行为零变化）

**票态**：8 票 = 62.4 `done` + 62.5 `dropped` + 62.1 / 62.2 / 62.3 / 62.6 / 62.7 / 62.8 `built` / state=`review`
（`tickets.py status` 实测 `counts = {"total": 8, "review": 6, "done": 1, "dropped": 1}`）。
**本 retro 的收口动作 = 把这 6 票置 `done`**；票态写入由 orchestrator 执行 `tickets.py mark`——本 retro 唯一可写文件是本文，故不落票态、不改 `tickets.toml`、不改 `epic-overview.md`。

**收口依据（6 票共性）**：

| 依据 | 内容 | 源 |
|------|------|----|
| plan 状态 | 6 票 frontmatter `status: built`；`review: quick` / `review_source: pinned` / `lenses_ran: [quick]` | `story-62.*-plan.md` 头部（4–15 行区） |
| 评审记录 | 仅 62.1 有 `## Review Triage Log`（F1–F7：F1 驳倒、F2/F3/F4 已修、F5/F6/F7 defer）；其余 5 票无 triage 条目 | `story-62.1-network-http-server-py-plan.md:109-117`；其余票 `grep -c Triage` = 0 |
| 落地提交 | 每票可定位到单一提交，且提交 subject 点名 story（下表） | `git log --oneline 2e3b7e2..d5e3587` |
| 交付 vs verify | 「每文件 <1000 行」「导入面零变化」「相关测试通过」逐条对账（见 F1 / F4） | 各 plan `Tasks & Acceptance` |
| 门禁 | `pytest -q` = **4809 passed / 51 skipped / 25 deselected**（2026-11-18 实测，265s）；`ruff check` + `ruff format --check`（455 文件）全绿；`mypy src`（219 源文件）无报错；`bandit -r src/ -ll` = Medium 0 / High 0 | 待 orchestrator 替换 |
| 覆盖率 | **93.41%**（19360 stmts / 1053 miss；2026-11-18 实测，gate 87%）（epic Constraints 线 = 87%） | 待 orchestrator 替换 |

**Plan 区间与证据**：

| 票 | 区间（plan `baseline_revision`..落地提交） | 提交 | 变更量 |
|----|------|------|--------|
| 62.4（v6 期） | 无 baseline 记账（plan 自述未推断） | `e3554e3`（2026-11-11） | 16 文件 +1901 −1480 |
| 62.1 | `2e3b7e2`..`8a18a46` | `8a18a46`（2026-11-15） | 22 文件 +2429 −2031 |
| 62.1 修复轮 | `8a18a46`..`6224a15`（票外补丁） | `6224a15`（2026-11-15） | 6 文件 +67 −18 |
| 62.2 | `6959a73`..`8928115` | `8928115`（2026-11-17） | 21 文件 +2126 −1701 |
| 62.3 | `8928115`..`19668cf` | `19668cf`（2026-11-17） | 11 文件 +817 −557 |
| 62.5 | `19668cf`（勘测基线） | 无提交（dropped） | 0 |
| 62.6 | `19668cf`..`f32acc7` | `f32acc7`（2026-11-17） | 3 文件 +325 −120 |
| 62.7 + 62.8 | `f32acc7`..`d5e3587` | `d5e3587`（2026-11-18） | 37 文件 +1059 −686 |

**每票交付**（一句话 + 落地提交 + 关键判据）：

| 票 | 一句话交付 | 提交 | 关键判据（测试文件 / 命令） |
|----|-----------|------|------------------------------|
| 62.1 | `network/http_server.py` 1913 行 → 11 模块内聚子包，最大 `service.py` 548 行 | `8a18a46` | `tests/network/test_http_server.py`、`tests/network/test_http_run_service.py`、`tests/test_contract_baselines.py` |
| 62.2 | `cli/goal.py` 1636 行 → `cli/goal/` 五文件（`commands` 834 / `execution` 536 / `verify` 323 / `messages` 30 / `__init__` 237） | `8928115` | `tests/test_goal*.py`、`tests/test_architecture_contracts.py::test_cli_package_layout_is_pinned` |
| 62.3 | `engine/workflow_runner.py` 1343 → `workflow_runner` 924 + `state_machine` 368 + `story_batch` 171（另 `observability._emit_step_event`） | `19668cf` | `tests/test_workflow_runner.py`、`tests/test_workflow_transition_reason.py`、`tests/test_story_parallel_scheduling.py` |
| 62.4 | `config/catalog.py` 1350 行 → 9 子模块包，最大 `report.py` 307 行 | `e3554e3` | `tests/test_config_catalog.py` |
| 62.5 | dropped：勘测证伪「会话管理可共享」前提，零代码变更 | 无 | plan `Ruling Record`（`story-62.5-…-plan.md` frozen 块后一节） |
| 62.6 | `goal/application.py` 14 个模块私有辅助拆解，三处超标/压线函数 cc 21/20/10 → 7/8/7（972→1067 行） | `f32acc7` | `tests/test_goal_decisions.py`、`tests/test_architecture_contracts.py` |
| 62.7 | `ruff.toml` 启用 `PLR2004` + 22 处提常量 + 就地 `# noqa: PLR2004`（比较运算魔法值清零） | `d5e3587`（与 62.8 同提交） | `ruff check --select PLR2004 src`（本 retro 实测 `All checks passed`）、`tests/test_contract_baselines.py` |
| 62.8 | `goal/application.py` 1067→768 + 新 `goal/workflow_support.py` 340；`cli/http.py` 1014→706 + 新 `cli/http_config.py` 336 | `d5e3587` | `tests/test_goal_declarative_workflow.py`、`tests/test_cli_http.py`、`tests/test_cli_http_lifecycle.py`、`scripts/contract_snapshot.py --check` |

> 62.8 的行数是 plan 记账（提交时点）；本 retro 实测 HEAD `goal/application.py` 771 / `cli/http.py` 771（epic 收口后的增长，`git show HEAD:<path> | wc -l`）。

**证据清单**：

- Epic 文件 ✓（`covers: [R1, R3]`；Done when 三条；Constraints 含 DAG、`network/` 红线、契约测试、87% 覆盖率、性能 ≤5% 降幅）
- `tickets/tickets.toml` 八 entry ✓（62.8 `v6_key = ""` = 执行期新立票，其余七条带 v6_key）
- 8 个 plan ✓（7 个有 `status`；62.4 为 migration-1 写的「最小 plan」，无 Tasks/Verification 节）
- 提交归因：`2e3b7e2..d5e3587` 共 21 提交、**零 merge**（`git log --merges … | wc -l` = 0），其中 6 个拆分/重构提交 + 1 个票外修复提交（`6224a15`）+ 1 个 v6 期 catalog 提交（`e3554e3`）；区间内其余 13 个为 Epic 61 收尾与文档提交
- 现状核实：`ls src/heagent/network/http_server/` 13 个 `.py`（拆时 11，`endpoints_tasks.py` 后加）、`config/catalog/` 9、`cli/goal/` 5、`engine/{state_machine,story_batch}.py`、`goal/workflow_support.py`、`cli/http_config.py`
- 行数现状：HEAD 全仓**无 >1000 行文件**，最大 `cli/interactive.py` 995；800–1000 区间 6 个文件（见 F2）
- 契约基线 4 份（`tests/fixtures/contract_baselines/{exception_types,public_exports,transport_errors,transport_routes}.json`；Epic 63.7 后自 `tests/contract_baselines/` 迁址）
- Run folders：无
- Session logs：未在树内正式引用（transcript 在 `~/.claude/projects`，未入档）→ 过程教训按窄化记录
- **缺口**（写稿时点；收口的四项已由 orchestrator 当场闭合，见方括号注记）：① 62.1 triage 的三条 defer（F5 / F6 / F7）无台账承接；② 62.4 plan 缺 build record 与 `baseline_revision`；③ 62.1 记载的 `docs/frame.md` 三处漂移（F10 / V1）**[收口时已改：§4.17 传输层行、§4.1 子模块表 `goal/` + `port_finder.py`、§4.1 功能表 `http_*.py` 口径]**；④ 6 票票态与 `epic-overview.md:35` 的「未收口」标记 **[收口时已改：6 票 `tickets.py mark … done`，overview 该行改 ✅]**；⑤ 本 retro 写稿时未跑全量 pytest——**门禁实测由 orchestrator 回填**（见下方「门禁」行）

## Findings

### 聚合视角（确定性推导）

| # | 视角 | 发现 | 源引用 | 处置 |
|---|------|------|--------|------|
| F1 | 交付体量 | 六面全部落地且每面最大文件远低于红线：1913→11 模块（最大 548）、1636→5 文件（最大 834）、1343→924/368/171、1350→9 文件（最大 307）、1067→768+340、1014→706+336 | 各拆分前体量实测 `git show <commit>^:<path> \| wc -l`；提交 `e3554e3`/`8a18a46`/`8928115`/`19668cf`/`d5e3587`；现体量 `wc -l` | accept |
| F2 | 现状核实 | HEAD 实测全仓最大文件 `cli/interactive.py` **995 行**（余量 5 行），800–1000 区间 6 个（`interactive` 995 / `workflow_runner` 924 / `workflow_loader` 875 / `ws_server` 863 / `goal/commands` 834 / `http_console` 829） | `git ls-tree -r HEAD -- src/heagent` 逐文件 `wc -l`（2026-11-18） | accept（Next#1/#2/#3） |
| F3 | 判据缺失 | epic Outcome「单文件均低于 1000 行」**无任何可执行判据**：`tests/` 内无文件行数断言（`grep -rn "def test_.*file_size\|行数\|line_count" tests/` 未命中此类守卫），全靠 plan 里手工 `wc -l` 记账 | `tests/test_architecture_contracts.py`（无长度断言）；`story-62.8-…-plan.md` Verification 首条 `wc -l` | fix-now → Next#1 |
| F4 | 规格对齐 | 7 票里 **5 票票面前提被勘测推翻**，全部经用户裁定改向：62.2 票面两文件布局否决（goal/ 是 click-free 域内核）／62.3 票面「提取至 state_machine.py」的命名被现状否定（纯表已住 `workflow_transition.py`）／62.5 判「不做」／62.6 票面「多层嵌套 + 策略模式」→ 实测嵌套已 ≤3、真违线是 cc／62.7 票面「506 处裸数字全部收敛」→ 改门禁化 | 各 plan `Intent` 的 `Ruling`/`Approach` 段（`story-62.2-…:26`、`-62.3-…:25`、`-62.5-…`、`-62.6-…:31`、`-62.7-…:21-40`） | accepted deviation（裁定在案，逐票见 `## Decisions`） |
| F5 | 自反缺口 | 62.6 的「辅助函数拆解」把 `goal/application.py` 从 972 推到 **1067**，自身制造了新超标（该票 frozen intent 明禁新模块），于是执行期新立 62.8 补硬缺口 | `git show f32acc7^:src/heagent/goal/application.py \| wc -l` = 972；`git show d5e3587^:…` = 1067；`story-62.8-…-plan.md:22-27`；`tickets.toml` id=8 `v6_key=""` | accept（已由 62.8 闭合） |
| F6 | 收口欠账（元教训） | epic 交付完成 ≠ 票态收口：6 票在 `built`/`review` 挂了三天（62.1 落 2026-11-15、62.7/62.8 落 2026-11-18、收口 2026-11-18），期间唯一提醒载体是 `epic-overview.md` 的一行 ⏳——**该机制本身有效**，但「谁在何时把它翻成 ✅」没有触发条件 | `_bmad-output/epic-overview.md:35`（原文：「⏳ **Epic 62 代码架构重构（未收口）**：6 票停在 `built`/state=`review`…无 retrospective 文件——补 retro 与票态收口是开 Epic 64 前的待办（见 Epic 63 retro「Open questions」）」）；Epic 63 retro「Open questions」首条 | accept（本 retro 即处置；机制建议见 D9 / Next#7） |
| F7 | 迁移票凭据 | 62.4 是唯一 `done` 却**无 build record** 的票：plan 自述「sprint-status.yaml 无改进计划键（grep=0）」「baseline_revision 未推断、不记载」，凭据为归档 epics.md 勘误；本 retro 在 git 面补到落地提交 `e3554e3`（2026-11-11） | `story-config-catalog-split-plan.md:1-20`；`git show --stat e3554e3` | accept（归因补全；baseline 可由 `e3554e3^` 反推，本 retro 不回填 plan） |

### 聚合视角补充

| # | 视角 | 发现 | 源引用 | 处置 |
|---|------|------|--------|------|
| F8 | 拆包代价①（再导出税） | 「导入面零变化」的持久成本是三个 `__init__` 的转发清单：`http_server/__init__.py` 17 条、`config/catalog/__init__.py` 60 条、`cli/goal/__init__.py` 75 条 `X as X` 语句——此后每新增公开符号都要同步该面 | `grep -c " as " src/heagent/{network/http_server,config/catalog,cli/goal}/__init__.py`（2026-11-18 实测 17/60/75） | accept（结构性成本，非缺陷） |
| F9 | 拆包代价②（文档同步面） | 每拆包都要重算 `docs/frame.md` 的归属与锚点行号：62.2 七处、62.3 四面（模块总表 / 目录树两行 / 转换表 14 格锚点 / 中断语义表）、62.8 八处 | `story-62.2-…-plan.md:63`（「docs/frame.md 七处口径」）、`story-62.3-…-plan.md:52-68`（「frame.md 同步面」条目）、`story-62.8-…-plan.md` Implementation Notes | accept（Next#4） |
| F10 | 遗留观察不是台账 | 62.1 Implementation Notes 的「遗留观察」记了 `docs/frame.md` 三处旧单文件形态，但**没有进 `open-items.md`**，因此 epic 收口时（HEAD `369e849`）`docs/frame.md:1323` 仍写单文件 `network/http_server.py`；实际是工作树一条未提交改动才改成子包口径 | `story-62.1-…-plan.md`「遗留观察（不属本 story 范围，未动）」；`git show HEAD:docs/frame.md \| grep -n "http_server\.py"` → :1323；`git diff docs/frame.md`（未提交，修同一行） | fix-now → Next#4 |
| F11 | 契约集成点①（快照脚本硬编码路径） | 快照脚本按**单文件路径**声明模块时，拆包即红：`config/catalog.py` 硬编码在拆包后 `FileNotFoundError`（提交信息自陈），故 `e3554e3` 引入 `expand_modules` 支持单文件/目录双形态；62.1 再为此加 `_http_server_files`（`HTTP_SERVER_PACKAGE = "src/heagent/network/http_server"`，注释写明「自 62.1 起是子包」） | `e3554e3` 提交信息「scripts/contract_snapshot.py：PUBLIC_MODULES 支持单文件/目录双形态（新增 expand_modules，原硬编码 config/catalog.py 在拆包后会 FileNotFoundError）」；`scripts/contract_snapshot.py:51`（`expand_modules`）、`:69`（`_http_server_files`）、`:84`（子包注释） | accept |
| F12 | 契约集成点②（架构白名单/布局判据） | 拆包的第二类必改点是布局白名单：62.2 从 `test_cli_package_layout_is_pinned` 期望表删 `goal` 条目、把 `test_entrypoints_do_not_duplicate_runtime_store_paths` 切 glob；`catalog` 拆包时 `test_shared_layer_layout_is_pinned` 被拆成「平铺模块 + 子包」两组断言，`test_config_catalog` 的依赖判据改 `rglob`（否则拆包后读不到文件且**子模块整体漏检**） | `tests/test_architecture_contracts.py:735-757`（`test_cli_package_layout_is_pinned`）、`:635-642`（glob 形态 + `cli/http_config.py`）、`:678-686`（catalog 单文件/子包双形态）、`:780-786`（`config_packages == ["catalog"]`）；`e3554e3` 提交信息「test_catalog_has_no_runtime_imports 改 rglob，否则拆包后 FileNotFoundError 且子模块漏检」 | accept（守卫退化面已逐处收口） |
| F13 | 假红实例（守卫被动退化） | 真实发生过的「守卫假红」：`scripts/mutation/mutate_contract_snapshot.py` 的组件复制清单仍指已删的 `http_server.py`，`is_file()` 静默跳过 ⇒ 组件副本缺整包 ⇒ `--check` 抛 `FileNotFoundError` ⇒ 变异判据 FAIL **掩盖真实原因**；`6224a15` 改 copytree 整包复制 | `story-62.1-…-plan.md:112`（triage F2，判「属实」）；`git show --stat 6224a15`（4 源文件 + 脚本/测试） | accept（已修） |
| F14 | 实测反例①（抽常量削弱契约扫描） | 把 `http_server/app.py` 的 `status_code=405` 抽成常量后，`transport_errors.json` 的 `status_source` 从 `call_site_literal` 退化为 `None` ⇒ 契约基线立刻红 ⇒ 协议状态码必须留在调用点作字面量 | `story-62.7-…-plan.md` Implementation Notes「首轮实测的两处反例」①；`src/heagent/network/http_server/app.py:134,141`（现存 `# noqa: PLR2004`） | accept（口径已写进 62.7 Intent 三分法） |
| F15 | 实测反例②（常量命名撞残留判据） | `network/origin.py` 把上限常量命名为 `_MAX_TCP_PORT` 时触发 `test_live_files_hold_no_reference_to_the_removed_tcp_entry`（大小写不敏感匹配 `TCP_`）⇒ 改名 `_MAX_PORT_NUMBER` | `story-62.7-…-plan.md` Implementation Notes 反例② | accept |
| F16 | 实测反例③（`__all__` 污染异常快照） | 给 `goal/application.py` 加 `__all__` 后，`scripts/contract_snapshot.py::collect_exceptions` 把 `__all__` 里的类一并计入异常快照——7 个非异常类被塞进 `exception_types.json`（+44 行）；改用 PEP 484 显式别名（`import X as X`）+ `ruff.toml` 的 `PLC0414` per-file 豁免后快照零漂移 | `story-62.8-…-plan.md` Implementation Notes「踩坑记录（口径副作用）」；同 plan Tasks 的 `ruff.toml` 豁免条目 | accept |
| F17 | 评审/记账强度不均 | 收口依据的强度实际不齐：62.1 有 7 条 triage（含 3 条 defer），62.2 只有 `Plan Change Log` 一条，62.3/62.5/62.6/62.7/62.8 仅 frontmatter `review: quick`；另 62.7 记账「noqa 7 处」，但其自列清单逐项相加 = 8，实测 `grep -c "noqa: PLR2004" src/` = 8 | `grep -c "Triage\|review_loop"` 逐 plan；`story-62.7-…-plan.md` Tasks 第 3 条；`grep -rn "noqa: PLR2004" src/ \| wc -l` = 8（2026-11-18） | accept（口径微差，不影响门禁：`ruff check --select PLR2004 src` 实测 0 命中） |

### 透镜发现（quick 档 · 三向收窄）

**收窄记录**：6 票 plan 的 `lenses_ran` 均为 `[quick]`（`review: quick` / `review_source: pinned`），本 epic 无 code-review 多镜头记录 ⇒ 本 retro 补三向核查，审查对象 = 交付形态而非行为（epic 全部为纯搬移）。

- **V1 文档面漂移（adversarial）**：HEAD `docs/frame.md:1323` 的「传输层」行仍把 `network/http_server.py` 当单文件描述——62.1 的遗留观察在 epic 收口时点仍未闭合，且**无台账条目承接**（`open-items.md` 未登记）。→ fix-now（Next#4；工作树未提交改动已修同一行，需随该批次提交）。
- **V2 判据有效性（verification-gap）**：`<1000 行` 这条 epic Outcome 无门禁（同 F3），本 epic 唯一常驻的结构约束是 `PLR2004`（`ruff.toml:16`，注释点名 Story 62.7）。无判据可变异 ⇒ 缺口在门禁侧而非实现侧。→ fix-now（Next#1）。
- **V3 常量≠配置（adversarial）**：抽常量的边界被契约扫描反向约束——协议状态码保持调用点字面量（F14）、命名不得撞既存残留判据（F15）、再导出优先 PEP 484 别名而非 `__all__`（F16）。三例均在 plan 里留了实测记录。→ accept（口径已文档化）。
- **V4 票态凭据不对称（verification-gap）**：62.4 的 `done` 无 build record（F7）、其余 5 票无 triage（F17）⇒ 同批 6 票 `done` 的凭据强度高于 62.4 既有 `done`、低于 62.1。→ accept（本 retro 已补齐归因与 commit 映射）。

## Previous-retro follow-through

前 epic = epic-61-web-search（retro `accepted-with-open-items`，2026-11-16）。其「Open questions」三条在 Epic 62 的落点：

| # | Epic 61 开放问题 | Epic 62 是否触及 | 证据 |
|---|------------------|------------------|------|
| 1 | tools 计数口径 29 = `ToolRegistry` 注册数；纳入 MCP 桥接工具后需再校 | **未触及**：62.7 只改 `tools/builtins/cron.py`、`tools/builtins/web_search_engine.py` 的常量，不增删注册 | `story-62.7-…-plan.md` Tasks 常量清单 |
| 2 | deferred 批（C4/C5/A11/E7）是否升 `open-items.md` 台账条目 | **未推进**，且新增同类口子：62.1 triage 又产生 3 条 defer（F5 `/loop` v7 引用悬空、F6 `workflow.md` 参数契约失真、F7 `70f1484` 无票树 coverage），同样无台账承接 | `story-62.1-…-plan.md:115-117` |
| 3 | A5 张力（工具面 `RuntimeError` vs 引擎 `ToolError`）维持惯例 | **未触及**：本 epic 无行为/异常面改动 | `git log 2e3b7e2..d5e3587 -- src/heagent/tools/`（仅 62.7 常量行） |

结论：**0/3 推进**——Epic 62 是纯结构面，与 Epic 61 三条开放问题无交集；但第 2 条被 Epic 62 扩了口子（defer 叠加到 6 条口径，仍全部待裁定）。

## Decisions

**票内裁定（均以 plan 的 `<frozen-after-approval>` 块留档，本 retro 不新建文件）**：

| # | 决策 | 批准 | 落点 | 状态 |
|---|------|------|------|------|
| D1 | 62.2 采用 A 方案：`cli/goal/` 同名子包四模块，否决票面两文件布局（goal/ 是 click-free 域内核） | 2026-11-16 用户 | `story-62.2-…-plan.md` Intent + Plan Change Log | 已执行（`8928115`） |
| D2 | 62.3 采用 A 方案 + 两档补齐（`state_machine` / `story_batch`），`workflow_transition.py` 纯表原地不动 | 2026-11-17 用户三次裁定 | `story-62.3-…-plan.md` Intent | 已执行（`19668cf`） |
| D3 | 62.5 改判「不做」：勘测证伪共享前提，零代码变更 | 2026-11-17 用户 | `story-62.5-…-plan.md` Ruling Record | 已闭合（dropped） |
| D4 | 62.6 用函数提取拆 cc，不用策略模式/责任链（守卫面宽，非同接口多变体） | 2026-11-17 用户 | `story-62.6-…-plan.md` Intent Ruling | 已执行（`f32acc7`） |
| D5 | 62.7 不做一次性魔法数字清扫，改 `PLR2004` 常驻门禁 + 口径三分 | 2026-11-17 用户「按你建议」 | `story-62.7-…-plan.md` Intent Ruling | 已执行（`d5e3587`；`ruff.toml:16`） |
| D6 | 62.8 执行期新立票补 epic Outcome 硬缺口（先拆 `application`/`http`，再收 62.7 口径） | 2026-11-17 用户「按你建议」 | `story-62.8-…-plan.md` Intent Ruling；`tickets.toml` id=8 | 已执行（`d5e3587`） |

**本 retro 的处置决定**：

- **D7 收口**：6 票置 `done`（依据见 Epic summary 表）——**已执行**（2026-11-18，orchestrator 逐票 `tickets.py mark <ref> done`；`tickets.py status` 实测 `{total: 8, done: 7, dropped: 1}`）。
- **D8 不补 ADR**：D1–D6 均为「票内方案取舍」，已在 plan frozen 块留档；`_bmad-output/initiative-heagent/decisions/` 本轮不新增文件（ADR 门槛是 hard-to-reverse 的跨周期契约；若认定 D5 的 `PLR2004` 属此类，可补 `adr-magic-value-gate.md`——**待用户裁决**）。
- **D9 缺口不自行改台账**：F10 的 `frame.md` 漂移与 62.1 的三条 defer 建议入 `open-items.md`，但本轮禁改 ⇒ 列 Next 交 orchestrator。

## Next

62 收口后仍未做（全部为实测项，不含推测）：

1. **`<1000 行` 无门禁**（F3 / V2）：建议加一条文件行数契约测试（如「`src/heagent/**/*.py` 逐文件 ≤1000，超限点名」）。当前 HEAD 最大 `cli/interactive.py` 995 行——**余量 5 行**；工作树一条未提交的 Epic 64 改动已把它推到 1026（`wc -l` 实测），即该不变量随时会破且无人报警。
2. **`network/http_server/service.py` 仍偏大**：548 行 = 该包 13 个模块总量（2601 行）的 21%，是包内最大单文件（`wc -l` 实测）。若继续拆，下一刀切 `service`（运行服务聚合面）。
3. **`cli/goal/commands.py` 834 行**：62.2 时 829、现 834，为 `cli/goal/` 子包最大；距红线 166 行。
4. **`docs/frame.md:1323` 传输层行**（HEAD 实测）仍是单文件口径，已被工作树未提交改动修正 ⇒ 随该批次提交即闭合；同批应把 62.1 的「遗留观察」写进 `open-items.md`，否则同类漂移还会丢（F10）。
5. **62.1 triage 的三条 defer**（`/loop` v7 的 `sync_roles.py` 悬空引用、`workflow.md` 的 `pull` 参数契约失真、`70f1484` 无票树 coverage）——无台账承接，建议一并入 `open-items.md` 待裁定（`story-62.1-…-plan.md:115-117`）。
6. **62.4 的 build record 缺口**（F7）：`baseline_revision` 未记载，可由 `e3554e3^` 反推回填；属票树可核验性，不影响交付事实。
7. ~~**`epic-overview.md:35` 的 ⏳ 行**待 orchestrator 改 ✅~~ → **已改**（2026-11-18，同批新增 Epic 64 已收口行）；仍建议给「收口触发」补一条机制（例：最后一个 entry 落 `built` 即生成 retro 待办），否则 F6 的欠账会重演。
