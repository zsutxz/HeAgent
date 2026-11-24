---
type: review
code: E77-R2
epic: epic-77-remote-contract-hardening
review_loop_iteration: 0
lens: 不变量与守卫反脆弱（宿主自扫 + 五条注入反证）
reviewed_at: 2026-11-24
head: 669ed177
---

# E77 收口三审 · R2 不变量与守卫反脆弱

## 范围

宿主自扫（不委派），对象 = `request_id` 幂等窗口的**并发面**：在途合流 / 取消路径 / 窗口淘汰 /
失败移出，以及这些语义是否真有判据。配套再核三条结构不变量：传输层不认识幂等窗口、帧面封闭集
未被放宽、失败路径不缓存。

## 守卫反证（五条：注入 → 红 → 复原 → 绿）

| # | 守卫 | 注入 | 结果（红） | 复原后 |
|---|---|---|---|---|
| A | 新增 `test_cancelling_one_joiner_does_not_cancel_the_other`（合流者不连坐） | `ws_project_adapter.py:107` 的 `await asyncio.shield(future)` → `await future` | **1 failed**（兄弟合流者收到 `CancelledError`） | **35 passed** |
| B | 新增 `test_expired_in_flight_entry_is_never_evicted`（在途项不因过期被踢） | `ws_submission_cache.py:63` 去掉 `future.done() and` | **1 failed** | **5 passed** |
| C | `test_run_frame_carries_an_opaque_request_id_and_does_not_strip_it` | `_OPTIONAL_FRAME_FIELDS` 去掉 `request_id` | **4 failed**（旧帧被判 `malformed`） | **54 passed** |
| D | `test_failure_is_not_cached_so_the_retry_can_start_again` | 适配器失败分支的 `self._submissions.drop(key)` 删掉 | **1 failed** | **35 passed** |
| E | 「传输层不认识幂等窗口」（结构不变量） | 静态判据：`grep -rn "SubmissionCache\|ws_submission_cache" src/heagent/network/` | **0 命中**（窗口只在 `cli/`） | —（无需注入） |

结论：A/B 是本轮**新补**的守卫，注入即红、复原即绿，不是恒真断言；C/D 证明 R1 既有判据对
「可选性」与「失败不缓存」两处语义是真的有牙。

## 发现

### R2-M-1（Medium，已落改）`asyncio.shield` 零判据，且 docstring 写的失败模式是错的

- 位置：`src/heagent/cli/ws_project_adapter.py:97-99`（原 docstring）、`:107`（shield）、`:121`（守卫）。
- 现象一：把 `await asyncio.shield(future)` 改成 `await future` 后，**原有 34 例全绿** —— 这条
  「必须的」写法此前没有任何判据。
- 现象二：原 docstring 称「否则合流者被取消会把共享 `Future` 一起取消、owner 的 `set_result` 就撞
  `InvalidStateError`」。**实测不成立**：`if not future.done()` 守卫（`:121`）已经把 `InvalidStateError`
  挡掉，owner 照常返回；真正被破坏的是**兄弟合流者**——它收到 `CancelledError` 而不是结果
  （反证 A 的失败信息即此）。
- 处置：**已落改**——store 的正确理由写进 docstring（连坐取消），并按实测场景补
  `test_cancelling_one_joiner_does_not_cancel_the_other`（`tests/test_ws_project_adapter.py:483`）：
  三个同键调用中取消一个，其余两个仍拿到同一个 `run_id`、控制台仍只被调 1 次。

### R2-M-2（Medium，已落改）在途项会被 TTL / 容量淘汰踢出 ⇒「在途合流」有静默空洞

- 位置：`src/heagent/cli/ws_submission_cache.py:61-73`。
- 实测（脚本探针，两条都命中）：
  - 同一 `(project_id, request_id)` 在**第一个提交仍在途**时把单调时钟推进 61s，第二次 `reserve`
    返回 `is_owner=True`、`future is not` 前一个 ⇒ **同键会二次真提交**；
  - `max_entries=2` 时三条在途，最旧的在途项被容量淘汰 ⇒ 该键再来也是 `is_owner=True`。
- 判定：与字面上的「60s 窗口」不矛盾，但与 docstring 承诺的「在途合流」冲突——窗口的用途是
  **成功重放**，在途项过期没有任何收益（它的键还在用着）。
- 处置：**已落改**，两条边界都钉成显式口径：
  - 过期扫描只清 `future.done()` 项（在途一条都不踢）；
  - 容量满时先淘汰**已完成**的旧项，全是在途才退化为按插入序淘汰最旧一条（内存有界优先于合流）。
  - 判据 = 新增 `tests/test_ws_submission_cache.py`（5 例：在途不因 TTL 被踢 / 完成后 60s 重放 /
    容量优先淘汰已完成 / 全在途退化淘汰最旧 / `drop` 幂等）。
  - 文档同批：`docs/framework.md:168`（模块表行）与 `:1405`（提交 run 行）写明「TTL 从提交开始计时、
    在途项不因过期被踢、容量满优先淘汰已完成项」。

### R2-L-1（Low，已落改成「显性边界」）同键不同 prompt 静默重放第一次结果

- 位置：`SubmissionCache.reserve` 的键 = `(project_id, request_id)`，不含 prompt 摘要。
- 判定：不视为缺陷——键是客户端的**不透明承诺**（「我重试的是那一次提交」），服务端比对载荷会造出
  「同键不同载荷 ⇒ 报什么码」这类没有需求支撑的新契约面。
- 处置：把它写成显式边界而不是留白——适配器 docstring 与 `docs/framework.md:1405` 各一句
  「键不含 prompt，同键不同 prompt 重放第一次结果」。

### R2-L-2（Low，记录不改）owner 被取消时合流者拿 `CancelledError`（无错误帧）

- 位置：`ws_project_adapter.py` 的 `except asyncio.CancelledError` 分支。
- 判定：**刻意**——owner 的被取消不等于提交失败，给合流者造一个假结果比断连更糟；且连接层把
  `CancelledError` 当「本连接结束」处理，客户端行为是「该次提交没有 ack」，与既有「提交失败不做
  原子性保证」口径一致。风险等级低，因为窗口内同键提交本就来自同一客户端的重试。
- 处置：无落改，docstring 已写明「owner 被取消则连坐取消」。

## 结论

**有条件的通过**：Critical 0 / High 0 / **Medium 2** / Low 2。两条 Medium 均当轮落改并配注入反证；
落改后新增 6 例判据（5 例窗口单测 + 1 例连坐取消），全量 `pytest` 5899 passed / 0 failed。
