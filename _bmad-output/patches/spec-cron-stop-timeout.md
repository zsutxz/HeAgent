---
title: 'CronScheduler.stop 关停硬上界（tick 执行 hang 兜底，MCP __aexit__ 同构）'
type: 'feature'
created: '2026-07-11'
status: 'done'  # 2026-07-11 交付：pytest 534 绿（531+3 新零回归）/ ruff 零新增 / mypy 干净（CronScheduler.stop 关停硬上界落地）
baseline_commit: 'a7b3158'
review_loop_iteration: 0
context:
  - '{project-root}/docs/frame.md'
  - '{project-root}/CLAUDE.md'
  - '{project-root}/src/heagent/cron/scheduler.py'
  - '{project-root}/src/heagent/cli.py'  # stop() 唯一调用方——交互模式 finally 进程退出路径
  - '{project-root}/tests/test_cron.py'
  - '{project-root}/_bmad-output/patches/spec-mcp-shutdown-timeout.md'  # 同构先例（commit 109df37）
  - '{project-root}/src/heagent/tools/mcp/manager.py'  # _await_shutdown 参照
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `CronScheduler.stop()`（scheduler.py:48-55）在 `self._running = False` 后，对未完成 task `task.cancel()` + `with contextlib.suppress(asyncio.CancelledError): await self._task`——该 `await` **无硬上界**。`_tick_loop` 卡在 `await self._check_and_execute()`（→ `_execute_job` → `await loop.run(job.prompt)` 即 `AgentLoop.run`）时，若其内部存在**不可中断的 await 点**（provider 请求 shield 了 cancel / 某工具执行 shield / 任意不响应取消的 awaitable），cancel 注入的 `CancelledError` 被吞 → task 不退出 → `await self._task` 无限阻塞 → `stop()` 无上界。

`stop()` 的唯一调用方是 `cli.py:264-266` 交互模式的 `finally` 块（`await scheduler.stop()`），即**进程退出路径**——挂死 = 进程退出挂死、需 OS SIGKILL 兜底。这是 `commit 109df37`（MCP `__aexit__` 关停硬上界）code review 时指出的**兄弟缺口**，两处 `task.cancel()` + 裸/半裸 `await` 结构同构，pre-existing LOW-MED（与 MCP 原病同档：关停挂死，触发需「job 执行中遇不可中断 await」这一非默认路径）。

**Approach:** 给 `stop()` 一个**关停硬上界**：保留原「立即 cancel」语义（cron 后台调度停止求快，`_tick_loop` 绝大多数时间在 `asyncio.sleep(tick_seconds=60s)`，graceful 窗口等不到自然退出反增延迟），仅把裸 `await self._task` 换成**单轮 bounded 收尾**——`task.cancel()` 后 `asyncio.wait({task}, timeout=stop_timeout)`：task 响应取消则一个 tick 内 done、`wait` 立即返回；task 挂死则 `wait` 等 `stop_timeout` 后返回 pending → 记 ERROR 放弃（task 已 cancel）。最坏 `stop_timeout` 必返回，绝不无限阻塞。`_tick_loop` / `_check_and_execute` / `_execute_job` **零改动**（cancel 经 asyncio 自然注入）。

## Boundaries & Constraints

**Always:**
- **作用点仅** `CronScheduler.stop()`（抽出 `_await_stop` helper）+ 构造期新增 `stop_timeout` 参数 + 模块常量 `_DEFAULT_STOP_TIMEOUT`。`_tick_loop` / `_check_and_execute` / `_execute_job` / `_matches` **零改动**（cancel 经 asyncio 注入 `_tick_loop` 的 await 点，无需改其内部）。
- **保留「立即 cancel」语义**（不改成 MCP 式 graceful 优先两轮）：`_tick_loop` 绝大多数时间在 `asyncio.sleep(tick_seconds)`，graceful 窗口（≤stop_timeout）等不到 sleep 结束回 `while` 检查 `_running`，首轮必超时 → 反比立即 cancel 多等一个 `stop_timeout`。立即 cancel 中断 sleep 即干净退出，是 cron 场景的合理行为（与 MCP transport close 需 graceful 不同）。
- **绝不无限阻塞**：`stop()` 最坏 `stop_timeout` 必返回（cancel 后单轮 bounded `wait`）；超时则记 ERROR 并放弃等待（task 已 cancel，余下收尾交由 GC / OS 进程退出兜底）。
- **不传播 task 异常**：`asyncio.wait` 不传播 task 内异常（含 `CancelledError`）——比原 `contextlib.suppress(asyncio.CancelledError)` 更宽（连非 cancel 异常也隔离），`stop()` 永不逸出 task 内异常。故移除原 `contextlib.suppress(...)` 与不再需要的 `import contextlib`。
- **可配 + 默认值**：`stop_timeout: float = _DEFAULT_STOP_TIMEOUT`（=5.0s），对齐 MCP `_DEFAULT_SHUTDOWN_TIMEOUT` / sandbox `_REAP_WAIT_TIMEOUT` 的「秒级关停硬上界」惯例（graceful ~秒级，挂死即记 ERROR 放弃）。
- **构造期校验** `stop_timeout > 0`：非正值会让 `asyncio.wait(timeout=)` 立即返回（task 仍 pending）→ 不给 cancel 任何收尾机会即 ERROR 放弃（与 MCP `shutdown_timeout <= 0` 同构误用）。fail-closed：`raise ValueError`。
- 数据沿用现有类型（无新 Pydantic 模型）；不引入原始 dict。

**Ask First:**
- **默认 `stop_timeout` 取值（5.0s）**——关停收尾的硬上界。5.0 匹配 MCP `shutdown_timeout` / sandbox `_REAP_WAIT_TIMEOUT` 的三处统一取值（「不可靠子进程/连接/任务的关停必须有上界」立场），且仅 forceful 边界（正常 task 响应 cancel 在 ms 级 done、不受 timeout 惩罚）。默认 5.0，实现后视实跑调整。
- **是否把 `stop_timeout` 做成可配参数（vs 仅模块常量）**——我选可配（对齐 MCP `shutdown_timeout` + 测试可直传 `stop_timeout=0.05` 免 monkeypatch 模块常量）。若认为 `CronScheduler` 构造参数已够、不愿再加，可退为仅模块常量（测试 monkeypatch）。

**Never:**
- **不改 `_tick_loop` / `_check_and_execute` / `_execute_job`**——cancel 经 asyncio 注入 task 的 await 点即可，作用点单一集中在 `stop()`。
- **不改成 MCP 式「先 graceful wait 再 cancel」两轮**——cron 场景的 graceful 窗口对 sleep-dominant 的 `_tick_loop` 无意义（见 Always 第 2 条）；立即 cancel 是原行为且更合适。**问题与 MCP 同构，解按场景适配**（核心立场一致：关停必须有上界）。
- **不 "log-and-leave" 留活 task**——超时必记 ERROR 并放弃（task 已 cancel，不会留阻塞 event loop 的活 task；与 MCP 「不 log-and-leave」立场一致，cron 单轮即可达成）。
- **不把 `wait` 设为无界**——必须 `timeout=`，否则 task 不响应取消时重新挂死（与原病同构）。
- **不吞 `CancelledError` 之外的取消信号**——`asyncio.wait` 自然隔离 task 异常，`stop()` 永不抛 task 内异常（含 `CancelledError`）。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|----------------------------|----------------|
| 正常关停·task 在 sleep（最常见，零回归） | `stop()` 时 `_tick_loop` 在 `asyncio.sleep(tick_seconds)` | `cancel` 中断 sleep → `_tick_loop` 一个 tick 内 done → `wait` 立即返回（不待 timeout）、无 ERROR | `CancelledError` 存于 task，不逸出 |
| 正常关停·task 在执行 job | `stop()` 时 `_tick_loop` 在 `_check_and_execute` 且响应取消 | `cancel` 中断 job → task done → `wait` 立即返回、无 ERROR | ledger lease 未正常 complete/fail（等过期），既有行为不变 |
| job 执行 hang（核心修复） | `AgentLoop.run` 内不可中断 await，`cancel` 被吞、task 不退出 | `wait` 等 `stop_timeout` 后返回 pending → ERROR 日志 → `stop()` 在 ~`stop_timeout` 返回 | task 已 cancel，余交 GC/OS |
| `stop_timeout<=0` | 构造期传 0 / 负值 | `raise ValueError`（fail-closed，对齐 MCP `shutdown_timeout`） | ValueError |
| task 未启动 / 已 done | `self._task is None` 或 `.done()` | 跳过 `wait`，仅记 "Cron scheduler stopped" | N/A |
| 重复 stop | `stop()` 后再调 | `self._task.done()` 真 → 跳过 `wait`，幂等 | N/A |

</frozen-after-approval>

## Code Map

- `src/heagent/cron/scheduler.py` —
  - 新增模块常量 `_DEFAULT_STOP_TIMEOUT: float = 5.0`（紧邻 `logger` 定义后，对齐 MCP `_DEFAULT_SHUTDOWN_TIMEOUT` 位置惯例）。
  - `__init__` 加参数 `stop_timeout: float = _DEFAULT_STOP_TIMEOUT` + `if stop_timeout <= 0: raise ValueError(...)`（对齐 MCP `shutdown_timeout` 校验块）+ `self._stop_timeout = stop_timeout`。
  - `stop()`：保留 `self._running = False`；`if self._task and not self._task.done():` 块内由 `task.cancel()` + `contextlib.suppress(asyncio.CancelledError): await self._task` 改为 `await self._await_stop(self._task)`；`logger.info("Cron scheduler stopped")` 不变。docstring 补硬上界 + 与 MCP 同构说明。
  - 新增 `async def _await_stop(self, task: asyncio.Task[None]) -> None:`：`task.cancel()`；`_, pending = await asyncio.wait({task}, timeout=self._stop_timeout)`；`if pending: logger.error(...)`。docstring 说明单轮 bounded 收尾 + 永不无限阻塞 + 不传播 task 异常。
  - 移除 `import contextlib`（全文件仅 `stop()` 用过 `contextlib.suppress`，改后无引用；ruff 会报 unused import）。
- `tests/test_cron.py` — 加 3 例回归（自带 `_StubProvider`，满足 `BaseProvider` Protocol 结构；空 `JobStore` 不触发 job 执行，stub 不被真正调用）：
  - `test_stop_timeout_must_be_positive`：`CronScheduler(store, _StubProvider(), stop_timeout=0)` 与 `=-1` 各 `pytest.raises(ValueError)`（对齐 `test_shutdown_timeout_must_be_positive`）。
  - `test_stop_bounded_when_tick_hangs`：`stop_timeout=0.05`；monkeypatch `scheduler._check_and_execute` 为「吞 CancelledError 的挂起协程」（`try: await event.wait() except CancelledError: await event.wait()`——捕取消后继续挂起 = 模拟不响应 cancel）；`await scheduler.start()` + 小 sleep 让 `_tick_loop` 进入挂起协程；`await asyncio.wait_for(scheduler.stop(), timeout=2.0)`——未修则裸 `await` 挂死触发外层 `TimeoutError`，修后 ~0.05s 返回；断言 ERROR 日志（caplog）含「关停超时」。
  - `test_stop_clean_no_error_on_sleep`：`stop_timeout=1.0`（宽裕）；`start()` + 小 sleep 让 `_tick_loop` 进入 `asyncio.sleep`；`await scheduler.stop()`；断言 `self._task.done()`、无「关停超时」ERROR（零回归：sleep 中断路径不被误判）。
- `_bmad-output/patches/deferred-work.md` — 新增条目登记此兄弟缺口（Source = MCP `__aexit__` 硬上界 commit `109df37` 的 code review 兄弟发现），直接带 Resolution 指向本 spec。
- `docs/frame.md` / `CLAUDE.md` — 评估：frame.md 4.7（line 426-434）scheduler 描述简洁、无关停行为；line 725 `finally: scheduler.stop()` 仍准确；CLAUDE.md「已知缺口」段未列 cron stop。**无 stale「stop 可阻塞 / 关停无上界」表述** → 按 spec 条件性「若涉则同步」跳过，surgical。

## Tasks & Acceptance

**Execution:**
- [x] `src/heagent/cron/scheduler.py` — `_DEFAULT_STOP_TIMEOUT` 常量 + `__init__` 参数与校验 + `stop()` 调 `_await_stop` + `_await_stop` 单轮 helper + 移除 `import contextlib` — 核心硬上界
- [x] `tests/test_cron.py` — 3 例回归（校验 / hang→bounded 挂死探测器 / clean 零回归）+ `_StubProvider` — 验证意图
- [x] `pytest tests/test_cron.py -v` — 既有全绿 + 3 新增
- [x] `pytest` — 全量零回归 + `ruff check src tests` 零新增 + `mypy src` 干净
- [x] `_bmad-output/patches/deferred-work.md` — 新增兄弟缺口条目 + Resolution — 诚实记账

**Acceptance Criteria:**
- AC1: Given `_tick_loop` 卡在不可中断 await（cancel 被吞、task 不退出），when `stop()`（`stop_timeout=0.05`），then `stop()` 在 ≤2.0s 内返回（非挂死），且发出「关停超时」ERROR。
- AC2: Given task 在 `asyncio.sleep` / 正常执行且响应取消，when `stop()`，then task 快速 done、无「关停超时」ERROR（零回归，happy path 不被误判）。
- AC3: Given `stop_timeout` 传 0 或负值，when 构造 `CronScheduler`，then `raise ValueError`（fail-closed）。
- AC4: Given `pytest` 全量，then 全绿（cron + agent loop + engine 零回归）；`ruff check src tests` / `mypy src` 无新增问题。
- AC5: Given `stop()` 任意路径，then 永不在 `await` 上无限阻塞（最坏 `stop_timeout` 返回或记 ERROR 放弃）——核心不变量。

## Design Notes

**为何单轮「立即 cancel + bounded 收尾」而非 MCP 两轮「graceful 优先」：** MCP 的首轮 graceful `wait`（不 cancel）给 transport 正常关闭窗口——stdio/HTTP close 通常 ms 级，几乎总能在窗口内 graceful 退出，免 force-cancel 致 transport 半关，故 graceful 优先有价值。cron 的 `_tick_loop` 绝大多数时间在 `asyncio.sleep(tick_seconds=60s)`，graceful 窗口（≤`stop_timeout`）等不到 sleep 结束回 `while` 检查 `_running`（要等满 `tick_seconds`），首轮必超时 → 反比立即 cancel 多等一个 `stop_timeout`。故 cron 保留原「立即 cancel」语义（中断 sleep 即干净退出），仅把裸 `await` 换成 bounded `wait`。**两者核心立场一致**：不可靠外部子进程/连接/任务的关停必须有上界，`timeout` 取值一致（5.0s）；**解按场景适配**（MCP graceful 优先 / cron 立即 cancel），非盲目复制。

**为何 `asyncio.wait` 而非 `asyncio.wait_for`：** `asyncio.wait_for(fut, timeout)` 在超时时会 **cancel 被包裹的 future**——这里已显式 `task.cancel()`，再用 `wait_for` 是重复 cancel 且语义混淆（「我已 cancel，只想 bounded 等收尾」）。`asyncio.wait({task}, timeout=T)` 返回 `(done, pending)` 且**超时不自动 cancel**、不传播 task 内异常——正合「显式 cancel 一次 + bounded 看是否收尾 + 不逸出异常」。

**为何移除 `contextlib.suppress(asyncio.CancelledError)`：** `asyncio.wait({task})` 把 task 内异常（含 `CancelledError`）存于 task 对象、不传播给调用方，`stop()` 永不逸出 task 异常——比原 `suppress(CancelledError)` 更宽（连非 cancel 异常也隔离），且语义更清晰（不依赖 `suppress` 吞特定异常）。移除后 `import contextlib` 全文件无引用，一并删（ruff unused import）。

**与 MCP / sandbox 的三处同构：** sandbox `_kill_and_reap`（`wait_for(proc.wait(), timeout=_REAP_WAIT_TIMEOUT)`，D-state reap hang，commit 见 deferred-work.md）+ MCP `__aexit__`（`_await_shutdown` 两轮，transport close hang，commit `109df37`）+ 本 spec `CronScheduler.stop`（`_await_stop` 单轮，job 执行 hang）——三者同属「不可靠外部子进程/连接/任务的关停必须有上界」立场，`timeout` 统一 5.0s。本 spec 是该立场的第三处补齐，**消除 code review 指出的最后一个同构兄弟缺口**。

**CancelledError 传播不破坏既有语义：** `_tick_loop` 的 `except Exception`（scheduler.py:61）本就不捕 `CancelledError`（BaseException）；`stop()` 的 `task.cancel()` 注入后，`CancelledError` 经 `_tick_loop` 逸出 task，`asyncio.wait` 将其存于 task（done）不传播——与近期 sandbox / MCP「取消信号优先传播」立场一致，无需改 `_tick_loop`。

## Verification

**Commands:**
- `pytest tests/test_cron.py -v` — expected: 既有全绿 + 3 例新测试全绿
- `pytest` — expected: 全量绿（cron + agent loop + engine 零回归）
- `ruff check src tests` — expected: 无新增问题（含确认 `import contextlib` 移除后无 unused）
- `mypy src` — expected: 无新增类型错误

**Manual sanity（可选）：** 临时构造一个 `_check_and_execute` 挂起的 scheduler（或一个会 shield cancel 的 cron job），`start()` 后 `await scheduler.stop()` 观察是否在 ~`stop_timeout` 内返回（非挂死）——真实路径需可 shield cancel 的 job，本地手动验证；CI/单测已用挂死探测器覆盖。
