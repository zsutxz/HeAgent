---
epic: epic-63-测试体系增强
date: 2026-11-18
verdict: accepted
criteria: declared
headless: false
---

# Epic 63 Retrospective

## Epic summary

**Epic**：epic-63-测试体系增强（R5/R6；src/ 零改动，纯测试体系面）

**票态**：8/8 finished——63.1/63.2/63.3/63.5/63.6/63.7/63.8 `done`（2026-11-18 收口，经 `tickets.py mark`）、63.4 `dropped`（4aaef8f 用户裁定：49 判据已覆盖）。`pending_tickets` 空。

**Plan 区间与证据**：

| Stories | 区间 | 提交 | 变更量 |
|---------|------|------|--------|
| 63.1 | d5e3587..249873d | 249873d | 2 文件 +418 |
| 63.2+63.3 | 249873d..0d13b6c | b787742, 0d13b6c | 4 文件 +616 |
| 63.4+63.5 | 0d13b6c..cab4552 | 4aaef8f, cab4552 | 3 文件 +120 −3 |
| 63.6 | cab4552..0df59ad | 0df59ad | 21 文件 +125 −186 |
| 63.7 | 0df59ad..b75075a | b75075a | 24 文件 +4773 −4623（含 6 个 rename 双计） |
| 63.8 | b75075a..abf96d9 | abf96d9 | 4 文件 +264 −347（净 −83） |

**证据清单**：
- Epic 文件 ✓（R5/R6 + Done when 三款均为 declared；Constraints 含 87% 覆盖率线）
- tickets.toml 八 entry 的 description/verify ✓
- 8 个 plan（status: built/dropped + baseline_revision 全在）✓
- 6 个 git_evidence 区间：8 提交全归因（subject 点名 story）、零 merge、零 binary_revisions ✓
- Run folders：无（63.4 裁定记录在其 plan 内）
- 前 epic retro：epic-62 无 retrospective 文件 → Previous-retro follow-through 记 none
- Session logs：未在树内正式引用（transcript 留存于 ~/.claude/projects，未入档）→ 过程教训分析按窄化记录
- **缺口**：无

## Findings

### 聚合视角（确定性推导）

| # | 视角 | 发现 | 源引用 | 处置 |
|---|------|------|--------|------|
| F1 | 架构增量 | **src/ 零改动**（`git diff --stat d5e3587..abf96d9 -- src/` 为空）——纯测试体系面，无依赖结构变化、无层级违规 | git 区间全量 | accept |
| F2 | 重复地图 | 63.6 删 21 处重复 fixture、63.8 删三簇散测；新增面无跨票重复 helper——63.6 收敛紧随 63.1–63.3 新文件落地，时序良性 | 0df59ad, abf96d9 | accept |
| F3 | 巨类增长 | 新测试文件 334/270/181 行，无超长文件；63.7 的 +4773/−4623 是 4 个 JSON rename 双计噪声，非真实增长 | git_evidence 六区间 | accept |
| F4 | 模式分歧 | 参数化/ids=/fixture 风格与既有 49 个 parametrize 文件先例一致；63.7 引用锚定惯例（`__file__` 仓库根）写入 README 固化 | tests/fixtures/README.md | accept |
| F5 | 规格对齐① | **沙箱降级条款**：Done when 写「沙箱降级测试就位」，63.4 裁定 dropped（既有 test_sandbox_docker.py 49 判据已覆盖 verify 三条款）——as-built 以既有覆盖满足意图，票面 wording 与交付形态分歧 | 4aaef8f + 63.4 plan | accepted deviation（用户裁定在案） |
| F6 | 规格对齐② | **基线条款**：Done when「≥5 条性能基线入 CI」满足——但基线本体（`tests/test_benchmarks.py`，实测 14 条 `-m benchmark` 收集）早于 epic 存在、区间内零触碰，63.5 实际交付 = CI 强制门禁接线；票面「建立核心路径性能基线」措辞与现实错位 | cab4552 + tests/test_benchmarks.py（区间外新增） | spec reconciliation 提案（Phase 4） |
| F7 | 规格对齐③ | **参数化 >30% 条款**：票面与 Done when 均未定义口径；63.8 plan 钉死 touched-scope 口径（78%）并记录不触达簇——口径裁定属实现期补全，非缺陷 | abf96d9 + story-63.8 plan | accepted deviation（口径已文档化） |

### 聚合视角补充

| # | 视角 | 发现 | 源引用 | 处置 |
|---|------|------|--------|------|
| F8 | 治理增量 | `tests/test_fixtures_contract.py` 把「`tests/fixtures/` 是唯一数据宿」从 README 约定升级为**可执行门禁**（stray 非 `.py` 文件即红并点名）——迁移面防回归的核心资产，价值高于单票 verify | `tests/test_fixtures_contract.py:31-54` | accept |
| F9 | 覆盖率条款 | epic constraint「≥87%」实测 **93.04%**（17773 stmts / 1028 miss；分支 4934 / 453 miss）。低覆盖残留在既有面：`tools/sandbox/winjob.py` 40%（Windows 专用）、`tools/mcp/client.py` 79%、`tools/builtins/search.py` 84%——均非本 epic 引入 | `pytest --cov --cov-report=term`（2026-11-18） | accept |

### 透镜发现（代码透镜 · 三镜头）

**收窄记录**：`bmad-review` 未装进 HeAgent 技能库（同步脚本声明不得调用），且本 epic 是 `src/` 零改动的纯测试面 ⇒ 镜头按三向收窄——测试是否**真能红**（verification-gap）、迁移面是否有旧路径残留（adversarial）、新测试的时序稳健性（edge-case）；审查域 = `d5e3587..abf96d9` 全 diff。

- **V1 变异判据（verification-gap）— 三条新测试面全部能红**（retro 现场实测：`src/` 复制到临时树、就地变异、`PYTHONPATH` 指向变异树，活树零改动）
  | 变异 | 目标判据 | 结果 |
  |------|----------|------|
  | 移除 `tool_execution.py:147` 的 `loop.active_tool = ""` | 在途态清空 | 2 failed：`test_inflight_label_and_activity_ledger_at_scale`、`test_cancel_clears_inflight_state` |
  | `ContextCompressor.threshold` 0.8→0.75 + `WindowResetConfig.threshold` 0.6→0.55 | 512K 阈值边界 | 2 failed：`test_just_below_threshold_no_compress`、`test_boundaries` |
  | `asyncio.gather` → 顺序 await | 12 并发真实性 | `test_batch_of_12_runs_concurrently_in_call_order` failed（34.96s，barrier 永不凑满） |
- **V2 迁移面残留（adversarial）— 一处文档面旧路径**：`tests/test_http_web_ui.py:8` 的 docstring 仍写 `tests/js/app_probe.js`，真实路径已迁至 `tests/fixtures/js/app_probe.js`（同文件 `:30` 已改对）。全仓 grep `tests/js` / `tests/contract_baselines` 无其它残留，代码面无断链（`scripts/contract_snapshot.py`、`tests/test_contract_baselines.py` 均指新宿）。→ fix-now（AI-1，已修：docstring 改为 `tests/fixtures/js/app_probe.js`）。
- **V3 常量≠配置（adversarial）**：`tests/test_context_boundary.py:41-46` 把 src 三处默认值复制为模块常量（`MAX_CTX=512_000` ↔ `Settings.max_context_tokens`、`COMPRESS_THRESHOLD=0.8` ↔ `ContextCompressor.__init__` 默认、`MAX_SUMMARY_TOKENS=4096` ↔ 同处），且无显式同源断言——耦合是**隐式**的、靠数值巧合。变异实测三处**均能红**（`threshold` 0.75/0.55 → 2 failed；`max_summary_tokens` 4096→2048 → 2 failed，含 `test_summary_request_stays_bounded_at_scale` 的保留边界标记），故不是漏检缺陷而是**形式缺口**：默认值语义变更（阈值参数化、拆多档）时，没人被提醒同步本文件。→ fix-now（AI-2，已修）。
- **V4 时序稳健性（edge-case）**：`tests/test_tool_concurrency.py:263` 原用 `await asyncio.sleep(_CANCEL_DELAY=0.1)` 后 cancel、`:135` 用 `asyncio.sleep(0.05)` 后断言 12 条台账已登记——固定睡眠在极慢机/高争用下可能先于调度完成，红因会是「还没跑起来」而非缺陷。→ fix-now（AI-3，已修：两处改 `_wait_until(<handler 启动计数> == _BATCH)` 条件等待，`_CANCEL_DELAY` 常量删除；连跑 5 轮全绿 1.04/0.96/0.92/0.95/0.93s）。
- **V5 现状不对称（verification-gap）**：`tests/test_provider_all_fail.py:157-160` 注释钉住「流式路径 `provider.stream` 直调、不经重试中间件，容错只剩 chain 回退」——测试如实反映既有实现（非本 epic 引入，`src/` 零改动）。→ accept（要处置须另立票）。

## Behavior verification

运行时行为已被实际执行，非仅靠测试声明：

- **全量回归 ×2**（63.7 后 `b75075a` 工作树、63.8 后 `abf96d9` 工作树）：两轮均 4451 passed / 6 failed，失败谱完全一致（setup_ws_external 5 CRLF + ws_server 9202 端口噪声，均 stash 对照干净 HEAD 同红的环境失败集）——零新增失败。
- **变异判据活体验证**（63.7 后）：`python scripts/mutation/mutate_contract_snapshot.py` → 2/2 变异体检出，VERDICT PASS——路径迁移后契约判据仍能红。
- **CI 基准门禁本地端到端**（63.5 提交内记录）：过严阈值 → 红 + exit 1；宽松 50% → 绿；首次无基线只落盘不比较。
- **参数化合并零丢失实测**（63.8）：`--collect-only` 32 用例收集数 = 原散测总数；25/32 nodeid 含 `[`。
- **覆盖率门限实跑**（2026-11-18，Py3.11 venv，`pytest --cov --cov-report=term -q`）：`TOTAL 17773 stmts / 1028 miss / 4934 分支 / 453 miss → 93%`，日志明确 `Required test coverage of 87.0% reached. Total coverage: 93.04%` ⇒ epic constraint 满足；同轮 4417 passed / 51 skipped / 5 failed，5 红全为 `test_setup_ws_external` CRLF 环境失败（与既有记录同谱；`ws_server` 9202 端口噪声本轮未复现）。
- **契约面复跑**（2026-11-18）：`test_architecture_contracts` + `test_deferred_id_registry` + `test_deferred_ledger` + `test_release_workflow_contract` → **62 passed / 1 skipped**，`src/` 零改动下依赖边界与台账 ID 守恒均未被测试面改动波及。
- **本 retro 变异组 ×3**：见 Findings · V1 表（在途态清空 2 红 / 阈值默认值 2 红 / 并发→串行 1 红），活树零改动（`git status` 仅本文件未跟踪）。
- **新测试面耗时实测**：`test_context_boundary` + `test_tool_concurrency` + `test_provider_all_fail` + `test_fixtures_contract` → 30 passed / 6.24s；最慢单例 2.99s（`test_run_raises_and_emits_structured_run_failed`，AgentLoop 全链 + 4 次真实 backoff，非固定 sleep）。

Session 级端到端冒烟（`heagent` 命令运行）未在本周期执行——本周期 src/ 零改动，CLI 行为面不变，窄化记录在案。

## Previous-retro follow-through

none——前 epic（epic-62-代码架构重构）无 retrospective 文件，无 action items 可查落点。

## Action items

**全部已落地（2026-11-18，用户指令「全修」—— 超出 retro 默认 propose-only 边界，特此记录）。**

| # | 类型 | 内容 | 落地证据 | 状态 |
|---|------|------|----------|------|
| AI-1 | remediation | `tests/test_http_web_ui.py:8` docstring 旧路径 → `tests/fixtures/js/app_probe.js` | 该文件 134 passed / 34 skipped（含 node 面） | **applied** |
| AI-2 | remediation | `tests/test_context_boundary.py` 新增 `TestConstantsMatchSourceDefaults`，把 `MAX_CTX`/`COMPRESS_THRESHOLD`/`MAX_SUMMARY_TOKENS`/`RESET_THRESHOLD` 四处与源码默认值（`Settings.model_fields` / 实例属性）钉同源 | 变异 `max_summary_tokens` 4096→2048 → 该用例与 `test_summary_request_stays_bounded_at_scale` 双双红（判据有效）；正常树 15 passed | **applied** |
| AI-3 | remediation | `tests/test_tool_concurrency.py` 两处裸 `asyncio.sleep` → `_wait_until(handler 启动计数 == _BATCH)`；`_CANCEL_DELAY` 删除 | 连跑 5 轮 7 passed（1.04/0.96/0.92/0.95/0.93s），无抖 | **applied** |
| AI-4 | process lesson | 「标准值同源」写入 `tests/fixtures/README.md`「约定」节（点名 `TestConstantsMatchSourceDefaults` 为先例） | `test_fixtures_contract` 绿（README 全域登记判据通过） | **applied** |
| AI-5 | spec reconciliation | `epic-63-测试体系增强.md` 的 Done when 三条各补 as-built 注记（沙箱降级=既有 49 判据 / 基线本体 14 条早存在 / 参数化口径 touched-scope 78%） | epic 文件已改（retro 默认不改 epic 文件，此处按用户指令例外） | **applied** |

**门禁复核（修复后）**：定向面 `test_tool_concurrency` + `test_context_boundary` + `test_http_web_ui` + `test_fixtures_contract` → **134 passed / 34 skipped**；全量 `pytest -q` → **4418 passed / 51 skipped / 5 failed**（5 红全为 `test_setup_ws_external` CRLF 环境失败，与基线同谱，零新增失败）；`ruff check` + `ruff format --check`（`src tests scripts`，432 files）全绿；`src/` 未改动（mypy 面不变）。

## Decision records

三条**均已批准并落盘**（2026-11-18 用户批准；落 `_bmad-output/decisions/`——本轮用户口径：所有文档放 `_bmad-output`，不新建 `docs/decisions/`；索引见该目录 `README.md`）：

| ADR | 决策 | 文件 | 来源 | approval |
|-----|------|------|------|----------|
| ADR-001 | CI 基准回归强制门禁（`--benchmark-compare-fail=mean:10%` + 嵌套 glob 死分支修复） | `decisions/adr-benchmark-regression-gate.md` | plan `story-63.5-…`，commit `cab4552` | **approved** |
| ADR-002 | 测试数据唯一宿 `tests/fixtures/` + 三条可执行判据 | `decisions/adr-test-data-single-home.md` | plan `story-63.7-…`，commit `b75075a` | **approved** |
| ADR-003 | 参数化覆盖率口径 = touched-scope（78%） | `decisions/adr-parametrize-coverage-scope.md` | plan `story-63.8-…`，commit `abf96d9` | **approved** |

- **不提案**：63.4 dropped（一次性裁定，完整记录在 plan 的 `<frozen-after-approval>` 块内，不满足「hard to reverse」门槛）。
- `_bmad-output/README.md` 的目录结构与「先看什么」表已登记 `decisions/` 入口。

## Acceptance verdict

**accepted**（criteria: **declared**）—— 2026-11-18 收口时由初判 `accepted-with-open-items` 升格：AI-1…AI-5 全部落地、无 deferred finding、8/8 票 finished。

- **pending_tickets = 空**：8 票全 finished（7 `done`（2026-11-18 `tickets.py mark`）+ 63.4 `state=dropped`），机器裁定不落在 `rejected`。
- **Done when 三条**：
  - ① 大上下文 / 并发 / Provider 失败 / 沙箱降级就位——3 条新测试面（`test_context_boundary` 15 例 / `test_tool_concurrency` 7 例 / `test_provider_all_fail` 8 例，含参数化），沙箱降级以既有 `test_sandbox_docker.py` 49 判据满足（63.4 dropped，用户裁定在案）⇒ **满足（含一项 accepted deviation）**。
  - ② ≥5 条性能基线入 CI——实测 14 条 `-m benchmark` 收集，CI `compare-fail=mean:10%` 强制门禁（`cab4552`），本地端到端验证红/绿两向 ⇒ **满足**（基线本体早于 epic，措辞错位见 AI-5）。
  - ③ conftest fixture ≥10 / `tests/fixtures/` 建立 / 参数化 >30%——4 个 canonical fixture + 21 处重复定义收敛（`0df59ad`）、`tests/fixtures/` 三域 + 三条可执行判据（`b75075a`）、参数化 78%（touched-scope，`abf96d9`）⇒ **满足**。
- **Constraints**：覆盖率 93.04% ≥ 87% ✓；架构契约 62 passed / 1 skipped ✓；`src/` 零改动 ⇒ 依赖 DAG / Pydantic 口径 / 安全机制未被触及 ✓。
- **未闭合 findings**：无——V2/V3/V4 已按 AI-1/AI-2/AI-3 修复并各自留下复验证据（变异红 / 连跑 5 轮）；V5 为既有实现不对称，accept；F5/F6/F7 的措辞对账已按 AI-5 写入 epic 文件。剩余 open items 只属治理动作（ADR 批准、票态收口、epic 62 补 retro）。
- **门禁证据汇总**：全量 `--cov` 轮 4417 passed / 51 skipped / 5 failed（全 `test_setup_ws_external` CRLF 环境失败）；契约面 62 passed；新增面 30 passed / 6.24s；变异组 3/3 检出。

## Open questions

- **epic-62 无 retrospective 文件**（7 票仍停在 `built` / `state=review`，62.5 dropped）——本 epic follow-through 因此记 `none`。epic 62 是否补 retro / 补收口，影响后续 retro 的 follow-through 链完整性；建议在 epic 64 开工前补。
- AI-5 已按用户指令直接改 `epic-63-测试体系增强.md`（默认 retro 不改 epic 文件）——是否还需在 epic 收口时补一条 poc 记录以留存该例外的授权来源。
- 下一步票：epic 63 已收口（7 票 `done`），initiative 内下一批只有 `epic-64-…64.14` 等 planned 票，无 `after` 依赖阻塞（`tickets.py next` 可解析）。

## Assumptions

交互式运行，无 headless 假设记录。
