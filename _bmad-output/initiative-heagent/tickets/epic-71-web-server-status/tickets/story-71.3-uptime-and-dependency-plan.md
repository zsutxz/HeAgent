---
title: 'Story 71.3 uptime 与依赖态'
type: feature
ticket: 3
created: '2026-11-19'
status: built
baseline_revision: '6345abd'
route: full
route_source: auto
risk: low
review: thorough
review_source: auto
lenses_ran: ['edge-case-hunter(inline)', 'verification-gap']
review_loop_iteration: 0
followup_review_recommended: true
context:
  - 'src/heagent/cron/jobs.py'
  - 'src/heagent/cli/http_status.py'
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** `/api/status` 不知道进程活了多久，也不知道工作区的依赖态（cron 作业、技能数、记忆条数）——这些过去只能 `grep` 日志或人工数文件。

**Approach:** `HttpServer.start()` 成功后记录启动时刻（uptime 用单调钟、展示用 UTC 墙钟），入口层把进程工作区的 cron 作业与技能/记忆计数一并投影；依赖态读盘走来源侧 5 秒缓存，端点本身仍只读内存。

## Boundaries & Constraints

**Always:**
- 未启动时 `uptime_seconds` / `started_at` 为 `null`（0 会被读成「刚启动」）。
- cron 只报**进程工作区**那份 `jobs.json`（服务端不知道前端选中哪个项目），**没有**「下次触发」字段。
- 依赖态逐项 fail-soft：单个坏条目 / 单个文件读失败只降级该项，绝不让整条状态 500。
- 落盘时间戳是 naive UTC ⇒ 下发前补时区，避免客户端按本地时解释。

**Never:**
- 不在端点里读盘（缓存在来源侧）；不改 `/api/health`；不新增依赖；不引入调度器运行态字段。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| STARTED | listener 已 `start()` | `uptime_seconds` 单调递增，`started_at` 带时区 | 无 |
| NOT_STARTED | 未启动 | 两者皆 `null` | 无 |
| JOBS_PRESENT | 工作区 `jobs.json` 有 1 条 | `cron_jobs` 一条，`last_run` 带 `Z` | 无 |
| JOBS_ABSENT | 无 `jobs.json` | `cron_jobs == []`，仍 200 | 无 |
| JOBS_MALFORMED | 空 id 条目 + 好条目 | 只丢坏条目，好条目照常出现 | 不 500 |
| CACHE_WINDOW | 缓存窗口内改盘 | 读数不变；过期后重新读 | 无 |

</intent-contract>

## Code Map

- `src/heagent/network/http_server/listener.py` -- `start()` 成功点写 `_started_monotonic` / `_started_at_wall`，暴露 `uptime_seconds` / `started_at`。
- `src/heagent/network/http_protocol.py` -- `CronJobInfo`（无 `next_run`）与 `StatusResponse` 的 `started_at` / `uptime_seconds` / `cron_jobs` / `skill_count` / `memory_facts`。
- `src/heagent/cli/http_status.py` -- `_parse_iso`（naive → UTC）、`_dependency` 5 秒缓存、`_cron_jobs` / `_skill_count` / `_memory_facts`（逐项 fail-soft，存储实例只建一次）。
- `src/heagent/cli/http.py` -- 两处装配传 `workspace_root`。
- `tests/test_http_status_api.py::TestDependencyState` -- 覆盖 I/O Matrix 全部行 + 装配级依赖态断言。

## Tasks & Acceptance

**Execution:**
- [x] `listener.py` -- 启动时刻与两个属性 -- uptime 需要单调钟。
- [x] `http_protocol.py` -- 依赖态模型与字段 -- 协议封闭性。
- [x] `cli/http_status.py` -- 解析/缓存/计数 -- 读盘只在来源侧。
- [x] `cli/http.py` -- `workspace_root` 透传 -- 两处装配点。
- [x] `docs/frame.md` / epic 残差 -- 口径同步（进程工作区、无 next_run）。

**Acceptance Criteria:**
- Given 已启动的 listener, when 连读两次, then `uptime_seconds` 严格递增且首次 > 0。
- Given 未启动, when 读 status, then 两个时间字段为 `null`。
- Given `jobs.json` 里是 naive UTC 时间戳, when 读 status, then `last_run` 以 `Z` 结尾。
- Given 一条畸形作业 + 一条正常作业, when 读 status, then 200 且只出现正常那条。

## Implementation Notes

- 实现顺序：listener 启动时刻 → 协议模型 → 来源侧解析/缓存/计数 → 两处装配透传 `workspace_root` → 用例与文档。
- **实测修正 ticket 口径**：ticket 写「当前选中项目的 jobs.json」，但服务端不知道前端选中的项目（选择只是本页状态）⇒ 报**进程工作区**那一份，并同步 epic 残差与 `docs/frame.md`。
- **评审发现的两处真实缺陷**：① `cron/jobs.py` 落盘 `last_run` 是 **naive UTC**（`strftime("%Y-%m-%dT%H:%M:%S")`），原实现原样下发会让客户端按本地时解释（CST 差 8 小时）；② fail-soft 只包住 `list_jobs()`，畸形条目的投影会抛 `ValidationError` 把整条状态变成 500 —— 二者均已修并各配用例。
- `SkillStore` / `FactStore` 实例在来源里只建一次：`SkillStore` 的同名遮蔽告警按**实例**去重，每次刷新新建会每 5 秒刷一批 WARNING。

## Plan Change Log

## Review Triage Log

### 2026-11-19 — Review pass
- verdicts: 7 findings — high 0, medium 3, low 4, false 0, maybe-false 0
- findings:
  - `[medium]` `[patch]` **verification gap**：`workspace_root` 两处装配接线无断言（漏传则三项恒 0/空、响应仍 200）— 装配级用例先造 tmp 工作区（`jobs.json` + 2 条记忆）再断言 `memory_facts == 2` 与 `cron_jobs` 含 `job-1`；变异验证：删 `workspace_root=` ⇒ RED。
  - `[medium]` `[patch]` **verification gap**：`uptime_seconds` 只断言「非 None 且 >= 0」，恒返回 0.0 也能过 — 改为连读两次断言严格递增；变异验证：操作数写反 ⇒ RED。
  - `[medium]` `[patch]` **verification gap**：真实 `last_run` 落盘形态（naive UTC）未被覆盖，前端会把时间读错 8 小时 — `_parse_iso` 补 `tzinfo=UTC`，加 naive 夹具用例断言 `…Z`；变异验证：去掉补时区 ⇒ RED。
  - `[low]` `[patch]` `_cron_jobs` 的投影在 try 之外，空 id 条目会让整条状态 500 — 投影移入 try 且过滤空 id/空 cron；加「坏条目 + 好条目」用例；变异验证：去掉过滤 ⇒ RED。
  - `[low]` `[patch]` 每 5 秒新建 `SkillStore` 会重复刷同名遮蔽 WARNING — 存储实例在来源里只建一次。
  - `[low]` `[edged]`（内联 edge 检查）`uptime_seconds` 用 `max(..., 0.0)` 会把符号错误抹成合法值 — 由「严格递增」用例守住（同上）。
  - `[low]` `[defer→已就地修正]` ticket 的「当前选中项目」口径与服务端能力不符 — 改为进程工作区，并同步 epic 残差与 frame.md（属规格修正，不是代码缺陷）。

## Auto Run Result

- **实现**：`/api/status` 增 `started_at` / `uptime_seconds` / `cron_jobs` / `skill_count` / `memory_facts`。
- **文件**：`src/heagent/network/http_server/listener.py`、`src/heagent/network/http_protocol.py`、`src/heagent/cli/http_status.py`、`src/heagent/cli/http.py`、`tests/test_http_status_api.py`、`tests/fixtures/contract_baselines/{public_exports,exception_types}.json`、`docs/frame.md`、epic 信封残差。
- **评审处置**：patch 6 条（medium 3 / low 3），1 条属规格修正；无 reject / defer（`false` 0）。
- **后续评审建议**：`true` —— 本轮新增/加强的 4 条用例只经自我变异验证，未经第二双眼睛复核。
- **验证**：`pytest`（`tests/network` + 相关套件 **807 passed**）；四份契约快照 `[OK]`；`ruff check` / `ruff format --check` / `mypy src` 全绿；变异验证 5/5 RED。
- **残差**：`skill_count` 只数技能包条目（同名按全局优先去重），不区分来源根；`memory_facts` 是 `MEMORY.md` 的 `- ` 行数，不含归档目录。
