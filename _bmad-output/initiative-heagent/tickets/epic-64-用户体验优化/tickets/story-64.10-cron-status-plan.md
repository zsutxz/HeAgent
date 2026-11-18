---
title: 'Story 64.10 实现 Cron 任务状态查询'
type: feature
ticket: 10
created: '2026-11-18'
status: built
baseline_revision: '8026aa9'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
review_loop_iteration: 0
followup_recommended: false
context:
  - 'src/heagent/cron/jobs.py'
  - 'src/heagent/cron/scheduler.py'
---

## Intent

**Problem:** 票面要求 `heagent cron status` 可查定时任务状态（运行/成功/失败、最后与下次执行时间、失败错误信息）。
现状三处缺口：

- **没有命令**：`heagent` 的子命令只有 `run` / `init` / `doctor` / `replay` / `gui` / `http-server`，
  cron 的管理面只存在于 agent 工具层（`tools/builtins/cron.py` 的 `cron_list`），必须在会话里问模型；
- **结果不落盘**：`CronScheduler._execute_job` 成功/失败都只更新 `last_run`（一个时刻），
  失败信息只进 `engine.events`（`cron_job_failed`）与进程日志——进程退出后「上次为什么失败」不可追；
- **下次执行时间算不出来**：`cron/expr.py` 只提供「某时刻是否匹配」（`cron_matches`），
  没有「下一次是何时」，展示侧无从下手。

**Approach:**

① `cron/jobs.py` 扩四个**可选**执行状态字段（`last_status` / `last_started` / `last_success` / `last_error`），
旧 `jobs.json` 缺这些键照常加载、旧版 heagent 读新文件忽略多余键（pydantic 默认 `extra="ignore"`）；
`last_run` 语义不变——仍是「一次执行**结束**的时刻」。
② `CronScheduler._execute_job` 在开始/成功/失败三处各写一次状态（running → success / failed），
失败信息取「异常类型: 首行」，截断 200 字符。
③ 新增 `cron/status.py`：`next_fire()`（下次触发时刻，与执行器逐字段同语义）+ 展示状态派生
（never / unknown / running / success / failed / interrupted）+ 状态快照模型。
④ 新增 `cli/cron_cmd.py`：`heagent cron status`（明细）与 `heagent cron list`（一行一条），
均支持 `--json` 与三档退出码。

**时间口径（本票最易踩的坑，落进输出与 docstring）：** cron 表达式按**宿主本地时**求值
（`_check_and_execute` 用 `datetime.now()`），而 `last_run` 系列按 **UTC** 落盘且无时区后缀、
格式与本地时无法分辨。展示侧一律双标：UTC 值带 `Z` 并附本地换算，`next_run` 标 `local`
并附同一时刻 UTC。

## Boundaries & Constraints

**Always:**
- `jobs.json` 向后兼容：新增字段全部可选、有默认值；旧文件缺字段不报错，新文件被旧代码读取也不报错。
- 只读命令：`cron status` / `cron list` **不改写** `jobs.json`、不启 `CronScheduler`、不调模型。
- 状态真源单一：`last_status` 只由 `CronScheduler._execute_job` 写；`status.py` 只派生**展示**状态
  （never / unknown / interrupted 不落盘）。
- `next_fire()` 的语义必须等于执行器（`cron_matches`，五字段 **AND**），不采用 Vixie cron 的
  「日与周同时受限取 OR」约定——展示要等于真正会触发的时刻。
- `last_error` 只留「异常类型: 首行」并截断（`ERROR_MAX_CHARS = 200`）；成功即清空（只描述「最近一次」）。
- 空 job 列表给可读输出；`--json` 必须是合法 JSON 数组（错误情形给错误信封对象 + 退出码 2）。

**Never:**
- 不改 `last_run` 的既有语义（不把「开始时刻」写进去），不重排「ledger.complete 先、last_run 后」。
- 不引入新依赖（click + 标准库 + `heagent.cron` / `heagent.pub`）。
- `cli/cron_cmd.py` 不导入 `agent` / `engine`（入口层只读 cron 域与 pub 路径，不需要运行栈）。
- 不把「展示状态」写进 `jobs.json`（旧版 heagent 会把它当未知值）。

## Code Map

- `src/heagent/cron/jobs.py`（改）— `CronRunStatus`（落盘值域 running/success/failed）+ `CronJob` 四个
  可选状态字段；`_load_all` 对**非对象条目**按损坏计数（原先 `CronJob(**1)` 抛 `TypeError` 直接打崩读取方）。
- `src/heagent/cron/status.py`（新建）— `CronJobState`（展示状态）/ `CronJobStatus`（快照模型）/
  `next_fire()` / `format_failure()` / `parse_utc()` / `resolve_state()` / `build_status()` / `build_statuses()`。
- `src/heagent/cron/scheduler.py`（改）— `_execute_job` 三处写状态（running+last_started / failed+last_error /
  success+last_success+清 error）；`_iso_now` 改模块级导入（原两处函数内导入）。
- `src/heagent/cli/cron_cmd.py`（新建）— `cron_cmd` 命令组 + `status_cmd` / `list_cmd` + 渲染与退出码。
- `tests/test_cli_cron_status.py`（新建）— 41 例：next_fire 对拍、状态派生、调度器落盘、CLI 全形态。
- 复用事实源：`cron/expr.py::_parse_field`（字段语法与区间必须与调度同一份实现）、
  `pub/workspace.py::WorkspacePaths.cron_file`（默认 jobs 文件路径，不硬编码 `.heagent/cron/jobs.json`）、
  `tools/builtins/cron.py::cron_list` 的展示口径（prompt 截 40 字符、损坏条数提示）。
- 待 orchestrator 集成（本 lane 不改）：`cli/console.py` 尾部注册、`tests/test_architecture_contracts.py`
  的 cli 布局白名单、`docs/frame.md` 子模块表与目录树。

## Tasks & Acceptance

**Execution:**
- [x] `cron/jobs.py` — 可选状态字段 + `CronRunStatus` + 非对象条目容错 — 向后兼容
- [x] `cron/status.py` — `next_fire` + 展示状态派生 + 快照模型 — 状态真源映射
- [x] `cron/scheduler.py` — 三处写状态 — 结果落盘
- [x] `cli/cron_cmd.py` — `cron status` / `cron list` + `--json` + 退出码 — 命令面
- [x] `tests/test_cli_cron_status.py` — 41 例 — 判据
- [ ] `cli/console.py` + `tests/test_architecture_contracts.py` + `docs/frame.md` — 共享文件，交 orchestrator

**Acceptance Criteria:**
- Given 一条成功的 job，when `heagent cron status`，then 该 job 显示 `success`、`last ok` 时刻（UTC + 本地换算）
  与 `next run`（本地时 + UTC + 相对剩余），退出码 0。
- Given 一条失败的 job，when `heagent cron status`，then 显示 `failed` 与 `error: RuntimeError: …`（异常类型 + 首行），
  退出码 1。
- Given 一条从未执行的 job，when `heagent cron status`，then 显示 `never` 且无 last/error 行，退出码 0。
- Given 旧版 `jobs.json`（无状态字段），when 任意子命令，then 正常加载：有 `last_run` 报 `unknown`、
  无 `last_run` 报 `never`，不报错。
- Given `--json`，when 解析，then 是合法 JSON 数组，每项含
  `id/prompt/cron/status/last_run/last_error/last_success/next_run/next_run_utc/seconds_until_next`。
- Given 空 job 列表，when `cron status`，then 输出「no jobs scheduled + jobs 文件路径」而非空白；
  `--json` 输出 `[]`。
- Given 执行中的 job（runner 尚未返回），when 读 `jobs.json`，then `last_status == "running"` 且 `last_started` 非空、
  `last_run` 仍为空。
- Given 一条 cron 表达式 `0 0 30 2 *`（永不触发），when 状态展示，then `next_run` 为 `null` 并给
  `next_run_note = "no fire time within 366 days"`，不抛异常。

## Implementation Notes

- **状态机**（落盘三值）`running` → `success` / `failed`；`running` 滞留超过
  `RUNNING_STALE_AFTER = 6h`（与 `engine/store.close_stale_running` 同阈值）在展示层降级为
  `interrupted`——进程中途退出不会永远显示「运行中」。
- **两个时间戳分工**：`last_started` 判「卡住的 running」，`last_run` 判「上次何时跑过」。
  把开始时刻写进 `last_run` 会破坏既有的「结束时刻」语义，故新增字段而不是复用。
- **`next_fire` 实现**：复用 `cron/expr.py::_parse_field` 展开五个字段，日/月/周先整日筛选、
  命中日再按小时/分钟集合取最小候选（`0 9 * * *` 一次即命中，不会逐分钟空转 366 天）。
  与执行器的等价性由测试**逐分钟暴力对拍** `cron_matches` 钉住（含 `*/15`、`5-10`、`0 0 1 * *`、
  `30 2 * * 1`、周日 `0`/`7` 别名）。
- **退出码三档**：0 = 无 failed；1 = 有 job 最近一次 failed；2 = `jobs.json` 整体不可解析（损坏/非列表）——
  `--json` 此时给 `{"error": …, "jobs_file": …}` 信封而不是空数组，避免脚本把「读不出来」当「没有任务」。
- **顺手修的一个崩溃点**：`JobStore._load_all` 原先只捕 `ValidationError`，列表元素是数字/字符串时
  `CronJob(**1)` 抛 `TypeError` 穿透到调用方（`cron_list` 工具与调度 tick 都会中招）。改为非对象条目
  按损坏计数跳过（`corruption_count` 口径不变，`-1` 仍表示整个文件坏）。
- **只读性**：CLI 只调 `JobStore.list_jobs()`；测试用「读前/读后 `jobs.json` 字节相等」钉住。
- **默认路径**：`WorkspacePaths.from_root(Path.cwd()).cron_file`（与 CLI 启动口径一致：在项目根运行），
  `--jobs-file` 覆盖；不硬编码 `.heagent/cron/jobs.json`（避免与 `WorkspacePaths` 双写路径）。
- **输出通道**：人读报告走 stdout（本命令主产物需可管道/重定向，与 `replay` 同档；`doctor` 走 stderr 是
  因为它是诊断）；`--json` 亦走 stdout，两者互斥。

## Verification

**Commands:**
- `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/test_cli_cron_status.py -q` -- 41 passed
- `.heagent/tmp/py311-venv-linux/bin/python -m pytest tests/test_cron.py tests/test_cron_range.py tests/test_cron_notify.py tests/test_coverage_cron_tools.py tests/test_dream.py tests/test_engine_p0.py -q`
  -- 103 + 68 passed（本 lane 改动波及的既有 cron 面）
- `.heagent/tmp/py311-venv-linux/bin/python -m ruff check <本 lane 五个文件>` -- All checks passed
- `.heagent/tmp/py311-venv-linux/bin/python -m ruff format --check <同上>` -- 5 files already formatted
- `.heagent/tmp/py311-venv-linux/bin/python -m mypy src` -- Success: no issues found in 216 source files
- `tests/test_architecture_contracts.py` -- 37 passed / 1 failed（`test_cli_package_layout_is_pinned`：
  白名单缺 `cron_cmd`，属共享文件，待 orchestrator 插入）

## Review Triage Log

- 2026-11-18 quick lens：本票无代码 patch。以下为实测确认与留待项。
- false：scheduler 的成功/失败两条路径都写终态并显式覆盖 `last_error`（不留永久 `running`；进程被杀走
  `interrupted` 降级）；`last_run`(UTC) 与 cron 表达式(宿主本地时) 双列标注、未混用；旧 `jobs.json`
  直接可读（新字段全可选、`extra=ignore`）；非对象条目降级为「跳过 N 条」而不是整份读失败。
- 留待裁决（两条，均未改代码）：
  - `jobs.json` **整体不可读**（权限 / IO 错误）时 CLI 打印「no jobs scheduled」且退出码 0，与
    `cron_cmd.status` docstring 承诺的「2 = jobs.json 不可解析」不符——根因在 `JobStore.list()` 把
    `OSError` 与「空列表」合并，改动会影响 `cron_list` 工具的既有口径。
  - `--json` 路径不输出「跳过 N 条」信息，脚本消费方无法察觉部分条目被跳过。
