---
type: review
code: E78-R
epic: epic-78-open-items-followthrough
lenses: ["规格对账", "不变量与守卫反脆弱", "三镜头对抗（契约 / 并发 / 文档）"]
reviewed_at: 2026-11-24
head: dca89eef
verdict: 通过
---

# E78 收口三审（单文档 · 三镜头）

> 形态变更：用户 2026-11-24 裁定「三审合并为一个文档，以后也一样」⇒ 本轮起三镜头写在同一份报告里，
> 不再拆 `-review-r1/r2/r3.md`。历史 epic 的三份保持原样不动。

## 范围

对象 = **未提交工作树**（`HEAD dca89eef` + 16 项改动）：E78 三条 entry 的代码 / 脚本 / 台账正文，以及
`docs/framework.md` 模块行与 E77 回顾的收口句。

| 命令 | 结果 |
|---|---|
| `pytest -q`（全量，带 node） | **5910 passed / 17 skipped / 30 deselected / 1 xfailed / 0 failed**（322s） |
| `pytest tests/test_web_search_smoke_script.py tests/test_ws_submission_cache.py tests/test_ws_project_adapter.py tests/test_deferred_id_registry.py tests/test_docs_links.py -q` | 65 passed |
| `python scripts/web_search_smoke.py --self-check` | exit 0 |
| `python scripts/web_search_smoke.py`（隔离 cwd、无 key） | exit 2，提示含 `WEB_SEARCH_API_KEY` |
| `ruff check` / `ruff format --check`（539 files）/ `mypy src`（242 files） | 全绿 |
| `python scripts/contract_snapshot.py --check` | 五份全 `[OK]`（本轮零基线漂移） |
| `python -m mkdocs build --strict` | exit 0、WARNING 0 |
| `.heagent/skills/loop/scripts/{contract_check,selfcheck}.py` | PASS / PASS=17 FAIL=0（本轮改过 closeout.md） |

## 镜头一 · 规格对账

| 规格条目 | 判据 | 实测 | 判定 |
|---|---|---|---|
| R1 两条事件名与 reason 固定 | `caplog` 断言 | `idempotency_evicted reason=capacity` / `idempotency_dropped reason=failed\|cancelled` 各恰一条 | ✅ |
| R1 日志只带 `project_id` | 断言日志正文 | 正文含 `project_id=p1234abc`，**不含** `req-old`/`req-live` | ✅ |
| R1 TTL 清理静默 | `caplog` 零事件 | 过期后同键 reserve ⇒ 0 条 `idempotency_\*` | ✅ |
| R2 四段判据 + 退出码契约 | 子进程实测 | `--self-check` exit 0；无 key exit 2；`--help` exit 0 | ✅ |
| R2 key 永不打印 | 静态断言 + 输出核对 | 只出现「已配置（长度 N）/未配置」；取 key 行与输出行不重合 | ✅ |
| R3 三条操作卡 | `grep -c 操作卡` == 3 | 3 命中（A55 / A67 / A76） | ✅ |
| R3 活动条数 / ID 集合不变 | 台账守卫 | `test_deferred_id_registry.py` 12 passed；仍 4 条、`A55 A65 A67 A76` | ✅ |
| Done-when 4 条 | 见上表 | 全部成立 | ✅ |

**镜头一发现：0 条**（无「规格说要、代码没做」的空洞；两处实质问题在镜头二被他证出来）。

## 镜头二 · 不变量与守卫反脆弱

七条注入反证（每条都「红 → 复原 → 绿」）：

| # | 守卫 | 注入 | 结果 |
|---|---|---|---|
| A | `test_capacity_eviction_is_observable_without_leaking_the_request_id` | 删掉 `idempotency_evicted` 那行 logger | **1 failed** |
| B | `test_cancelled_owner_is_marked_as_cancelled_in_the_window_log` | 取消路径 `reason=\"cancelled\"` 写死成 \"failed\" | **1 failed** |
| C | `test_expired_entry_cleanup_stays_silent` | TTL 清理也打一条 `reason=ttl` | **1 failed** |
| D | `test_the_key_is_never_interpolated_into_an_output_line` | 段 1 的 note 里塞 `key={api_key}` | **1 failed** |
| E | 同 A 的「无 request_id」断言 | evicted 日志加 `request_id=%s` | **1 failed** |
| F | 新增 `test_entry_parser_does_not_count_a_forged_line_inside_a_snippet` | `_split_entries` 退回「按行首 `[n]` 数行」 | **1 failed** |
| G | 段 2 的「0 条不判 FAIL」 | 还原成 `seg.check(bool(results), …)` | 由 `test_empty_result_is_reported_but_is_not_a_failure` 的静态断言拦住 |

### 发现 M-1（Medium，已落改）冒烟会把多行摘要误计成条目 ⇒ 假 FAIL

- 位置：原 `scripts/web_search_smoke.py` 的 `_segment_tool`（按 `line.startswith(\"[\")` 数条目）。
- 实测（探针）：5 条真实结果，第 5 条摘要里带第二行 `[9] …`（Tavily 摘要常含换行）⇒ 解析出 **6 条**，
  在 `max_results=5` 下会被判 FAIL。**假阳性正好挡在 A55 的闭合路径上**：一个正常检索结果会让
  「冒烟不通过」，而人只会去查引擎。
- 处置：**已落改**——改为「按空行分块 + 块首行匹配 `^\[n\] \S`」的 `_split_entries`（摘要里的伪造行
  留在自己的块内，不会造出新条目；围栏 warning 块因首行不匹配自然被排除），并补两例（伪造行 / warning 块）。

### 发现 M-2（Medium，已落改）段 2 的文案与判据自相矛盾

- 位置：`_segment_engine` 的 `seg.check(bool(results), \"引擎返回非空结果（空结果在 A55 口径下不算失败…）\")`。
- 现象：文案自己说「0 条不算失败」，代码却把它记成 FAIL ⇒ 一次「确实无匹配」的查询会让整轮冒烟红，
  使用者分不清「引擎坏了」与「这个词没结果」。
- 处置：**已落改**——0 条改走 `note`（打印「不判 FAIL，但 A55 闭合前需人工确认查询词」），
  真失败仍由引擎异常 / 条目数超钳位承担。

## 镜头三 · 三镜头对抗（契约 / 并发 / 文档）

- **契约面**：本轮不新增错误码、不动帧面、不动基线（`contract_snapshot --check` 五份 `[OK]`、零 diff）；
  两条新日志事件名无 allowlist 守卫（本仓对 `ws event=` 名一贯不设白名单，与 `project_service_ignored`
  同档）⇒ 无契约面缺口。
- **并发面**：1️⃣ 日志只在「真的删掉一个键」时打（`drop` 先判 `pop` 返回值），重复 drop 不刷第二条 2️⃣
  TTL 清理静默（避免逐请求噪声）3️⃣ 淘汰日志的 `entries=` 取删除后的长度，读起来是「剩下多少」而不是
  「淘汰前多少」（文案已按此写）4️⃣ `reserve` 仍是同步、无 await，A9③ 老坑未复发。
- **文档面**：`docs/framework.md` 模块行的两条事件名与代码逐字一致；`_bmad-output/open-items.md` 三条操作卡
  的命令（`--query` / `--max-results` / `--self-check` / `netstat -ano` + `findstr`）都在脚本 `--help`
  或系统命令里实测可用；E77 回顾的「可观察但未做」已改成已补并保留原文；`closeout.md` 的三审形态同步为单文档。

### 发现 L-1（Low，记录不改）无 key 时报告里有 `[FAIL]` 标记，退出码却是 2

- 现象：段 1 的 `check(configured)` 在无 key 时判 FAIL，而整轮退出码是 `2`（前提缺失）。
- 判定：语义以**退出码**为准（`1` 判据失败 / `2` 前提缺失），且 stderr 已明确写「前提缺失…」；
  改成 `[SKIP]` 会让「配置检查没过」这件事在报告里消失，反而更差。记录不改。

## 落改清单（本轮 6 处）

1. `scripts/web_search_smoke.py`：新增 `_split_entries` + `_ENTRY_HEADER`，`_segment_tool` 改用块级解析（M-1）。
2. `scripts/web_search_smoke.py`：段 2 的 0 条从 `check` 改 `note`（M-2）。
3. `tests/test_web_search_smoke_script.py`：+3 例（伪造行 / 围栏 warning 块 / 0 条不判 FAIL）。
4. `.heagent/skills/loop/references/closeout.md`：三审产物改**单文档三镜头**（用户裁定，历史不动）。
5. `docs/framework.md`：模块行补两条事件名（entry 内已计划的落点，随三审复核确认）。
6. `_bmad-output/open-items.md`：三条操作卡（entry 内已计划，随三审复核确认命令可用）。

## 结论

| 镜头 | Critical | High | Medium | Low | 结论 |
|---|---|---|---|---|---|
| 一 · 规格对账 | 0 | 0 | 0 | 0 | 通过 |
| 二 · 不变量与守卫反脆弱 | 0 | 0 | **2** | 0 | 有条件的通过（2 条当轮落改，7 条注入反证全红→绿） |
| 三 · 三镜头对抗 | 0 | 0 | 0 | **1** | 通过（Low 记录不改） |

**总体：通过**。E78 三条 entry 的规格全部成立，判据有牙（注入即红），文档与代码逐字对读无漂移。
