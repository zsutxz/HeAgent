---
title: 'MCP __aexit__ 关停硬上界（transport close hang 兜底）'
type: 'feature'
created: '2026-07-10'
status: 'done'  # 2026-07-10 交付：pytest 531 绿（+4 新）/ ruff 零新增 / mypy 干净（__aexit__ 关停硬上界落地）
baseline_commit: 'c90c8ff'
review_loop_iteration: 0
context:
  - '{project-root}/docs/frame.md'
  - '{project-root}/CLAUDE.md'
  - '{project-root}/src/heagent/tools/mcp/manager.py'
  - '{project-root}/tests/test_mcp_manager.py'
  - '{project-root}/_bmad-output/patches/deferred-work.md'  # 2026-07-01 FR-3 review · __aexit__ gather 无超时条
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `MCPClientManager.__aexit__` set 各 stop 事件后 `await asyncio.gather(*self._server_tasks, return_exceptions=True)`，每个 `_server_loop` task 在 finally 内 `await cm.__aexit__(...)`（transport context 退出 = 关闭 session / 终止 stdio 子进程 / 关 HTTP 连接）。当 **stdio 子进程忽略 SIGTERM** 或 **HTTP 远端不 FIN** 时，该 `cm.__aexit__` 无限阻塞 → gather 永不返回 → `__aexit__` 无上界 → **进程退出挂死**（需 OS SIGKILL 兜底）。这是 `deferred-work.md` 2026-07-01 FR-3 review 的 pre-existing LOW-MED 项，spec FR-3 显式未覆盖（"非 FR-3 引入"）。

**Approach:** 给 `__aexit__` 一个**整体关停硬上界**：抽出 `_await_shutdown(tasks)` helper，用 `asyncio.wait(tasks, timeout=shutdown_timeout)` 两轮——首轮超时则**取消未完成 task**（cancel 注入其 finally，中断挂死的 `cm.__aexit__`），二轮短等让被取消 task 的 finally 收尾；二轮仍超时则记 ERROR 放弃。保证 `__aexit__` 在 ~2×`shutdown_timeout` 内必返回，绝不无限阻塞。`_server_loop` 内部零改动（cancel 经 asyncio 自然注入其 finally）。

## Boundaries & Constraints

**Always:**
- **作用点仅** `MCPClientManager.__aexit__`（抽出 `_await_shutdown` helper）+ 构造期新增 `shutdown_timeout` 参数 + 模块常量 `_DEFAULT_SHUTDOWN_TIMEOUT`。`_server_loop` / `_transport_and_session` / `_watch` / `_connect_all` **零改动**（cancel 经 asyncio 注入 task 的 finally，无需改其内部）。
- **语义 = 超时即取消**（forceful）：首轮 `asyncio.wait` 超时 → 对未完成 task 调 `task.cancel()` → 二轮 bounded `wait` 让被取消 task 的 finally（`cm.__aexit__` 被 CancelledError 中断）收尾。**不留僵尸 task**（不 "log-and-leave"）。
- **绝不无限阻塞**：`__aexit__` 最坏 ~2×`shutdown_timeout` 必返回（首轮 + 二轮各 bounded）；二轮仍超时则记 ERROR 并放弃等待（task 已 cancel，余下收尾交由 GC / OS 进程退出兜底）。
- **单 task 异常不传播**：`asyncio.wait` 不传播 task 内异常（等同原 `gather(..., return_exceptions=True)` 语义）——某 server 关闭异常不影响其它 / 不逸出 `__aexit__`。
- **`_unregister_all()` 仍最先执行**（`__aexit__` 现有顺序不动）：工具摘除在 gather/wait 之前，挂死不影响工具已注销的不变量。
- **可配 + 默认值**：`shutdown_timeout: float = _DEFAULT_SHUTDOWN_TIMEOUT`（=5.0s），对齐既有 `connect_timeout` / `health_check_interval` 的「模块常量 + 构造参数」模式；5.0 与 sandbox `_REAP_WAIT_TIMEOUT` 一致（graceful 关停 ~秒级，挂死即 force-cancel）。
- **构造期校验** `shutdown_timeout > 0`：非正值会让首轮 `wait` 立即返回（全部 pending）→ 不给任何 task graceful 关停机会即强制取消（与 `health_check_interval <= 0` 误判同构）。fail-closed：`raise ValueError`。
- 数据沿用现有类型（无新 Pydantic 模型）；不引入原始 dict。

**Ask First:**
- **默认 `shutdown_timeout` 取值（5.0s）**——graceful 关停的硬上界。5.0 匹配 sandbox `_REAP_WAIT_TIMEOUT` 与「秒级关停」惯例，且仅 forceful 边界（正常关闭的 task 早已完成、不受影响）。若某些重运行时 stdio server 关闭 >5s，可构造期调大或调默认。默认 5.0，实现后视实跑调整。
- **是否把 `shutdown_timeout` 做成可配参数（vs 仅模块常量）**——我选可配（对齐 `connect_timeout`/`health_check_interval` 两兄弟参数 + 测试可直传短值免 monkeypatch）。若认为 API 面已够、不愿再加参数，可退为仅模块常量（测试 monkeypatch）。

**Never:**
- **不改 `_server_loop` / `_transport_and_session` / `_watch`**——cancel 经 asyncio 注入 task finally 即可，作用点单一集中在 `__aexit__`。
- **不做 per-server 超时**——整体一个关停 deadline 足够（per-server 是 over-engineering；某 server 慢不阻塞其它 server 的 task 完成，`asyncio.wait` 的 done/pending 自然分离）。
- **不 "log-and-leave" 留僵尸 task**——超时必须 cancel（否则挂死 task 的 `cm.__aexit__` 仍阻塞 event loop，与「进程退出无上界」原病同构）。
- **不把二轮 wait 设为无界**——二轮同样 bounded，否则被取消 task 若 finally 内仍有不可中断段会重新挂死。
- **不吞 `CancelledError`**——`_server_loop` finally 的 `except Exception` 本就不捕 CancelledError（BaseException），保持取消信号传播（与近期 sandbox CancelledError 硬化立场一致）。
- **不触碰 item D（handler ToolError 封装）**——item D 经研究已确认崩溃前提被 executor 兜底，另起 Resolution 关闭，与本 spec 正交。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|----------------------------|----------------|
| 正常关停（零回归） | 所有 transport `cm.__aexit__` 正常返回（< timeout） | 首轮 `wait` 内全部 done、无 pending → 不 cancel、不告警、`__aexit__` 正常返回 | N/A |
| transport close 挂死（核心修复） | 某 task 的 `cm.__aexit__` 无限阻塞（stdio 忽略 SIGTERM / HTTP 不 FIN） | 首轮 `wait` 超时 → WARNING + cancel 该 task → 二轮 `wait` 内被取消 task 收尾完成 → `__aexit__` 在 ~timeout 内返回 | CancelledError 存于 task，不逸出 |
| 二轮仍挂死（极端） | 被 cancel 的 task finally 内有不可中断段，二轮 `wait` 亦超时 | ERROR 日志（N 个 task 仍未退出）+ 放弃等待；`__aexit__` 在 ~2×timeout 内返回 | task 已 cancel，余交 GC/OS |
| 单 server 关闭异常 | 某 task `cm.__aexit__` 抛 Exception（非 CancelledError） | 该 task 在首轮 done（异常存于 task）；`asyncio.wait` 不传播，不影响其它 task / 不逸出 `__aexit__` | 异常吞于 task（既有 `except Exception` 已 WARNING） |
| 混合：一挂死一正常 | server A 的 `cm.__aexit__` 正常、B 挂死 | A 的 task 首轮 done；B 超时 cancel；A 不受影响（done/pending 分离） | 仅 B 被 cancel |
| `shutdown_timeout<=0` | 构造期传 0 / 负值 | `raise ValueError`（fail-closed，对齐 health_check_interval） | ValueError |
| 空 server 配置 | `MCPConfig()` 无 server | `self._server_tasks` 为空 → `_await_shutdown` 早返回（`if not tasks`），无 `asyncio.wait` 空集 ValueError | N/A |

</frozen-after-approval>

## Code Map

- `src/heagent/tools/mcp/manager.py` —
  - 新增模块常量 `_DEFAULT_SHUTDOWN_TIMEOUT: float = 5.0`（紧邻 `_DEFAULT_CONNECT_TIMEOUT` / `_DEFAULT_HEALTH_CHECK_INTERVAL`）。
  - `__init__` 加参数 `shutdown_timeout: float = _DEFAULT_SHUTDOWN_TIMEOUT` + `if shutdown_timeout <= 0: raise ValueError(...)`（对齐 health_check_interval 校验块）+ `self._shutdown_timeout = shutdown_timeout`。
  - `__aexit__`：`if self._server_tasks:` 块内 `await asyncio.gather(*self._server_tasks, return_exceptions=True)` 改为 `await self._await_shutdown(self._server_tasks)`（顺序不变：`_unregister_all` → set stops → bounded await → clear）。
  - 新增 `async def _await_shutdown(self, tasks: list[asyncio.Task[None]]) -> None:`：`if not tasks: return`；首轮 `_, pending = await asyncio.wait(tasks, timeout=self._shutdown_timeout)`；`if not pending: return`；WARNING + 对 pending 逐个 `task.cancel()`；二轮 `_, still_pending = await asyncio.wait(tasks, timeout=self._shutdown_timeout)`；`if still_pending: logger.error(...)`。docstring 说明两轮 + 永不无限阻塞 + 不传播 task 异常。
  - 模块 docstring（FR-1~5 生命周期段）补一句：`__aexit__` 关停带硬上界（transport close hang 兜底）。
- `tests/test_mcp_manager.py` — 加回归测试（复用既有 `_patch_transport` / `StubSession` / `ToolRegistry()` 模式）：
  - `test_aexit_bounded_when_transport_close_hangs`：fake_transport 的 `yield` 后 `await asyncio.Event().wait()`（永不返回 = 模拟 transport close 挂死）；`shutdown_timeout=0.05`；用 `asyncio.wait_for(async with ..., timeout=2.0)` 包住——未修则挂死触发测试 TimeoutError，修后 ~0.05s 返回；断言 WARNING 日志（caplog）+ 工具已注销（`_unregister_all` 先于 hang）。
  - `test_aexit_clean_close_no_spurious_cancel`：正常 fake_transport（yield 后正常返回）；断言 `__aexit__` 正常完成、无 "关停超时" WARNING、无 "二次超时" ERROR（零回归：happy path 不被误 cancel）。
  - `test_shutdown_timeout_must_be_positive`：`MCPClientManager(MCPConfig(), shutdown_timeout=0)` 与 `=-1` 各 `pytest.raises(ValueError)`（对齐 `test_health_check_interval_must_be_positive`）。
  - `test_aexit_mixed_hang_and_clean_server`：server A 正常、B 挂死；断言 A 的工具注销、`__aexit__` bounded 返回、仅 B 被 cancel（混合 done/pending 分离）。
- `_bmad-output/patches/deferred-work.md` — 2026-07-01 FR-3 review 的「`__aexit__` gather 无超时」条补 Resolution（指向本 spec）+ 顺带把「handler 未把 in-flight call_tool 封 ToolError」条关为「executor 已兜底」（item D，研究证实崩溃前提失效）。
- `docs/frame.md` / `CLAUDE.md` — 若已知缺口表 / MCP 生命周期描述有「`__aexit__` 可阻塞 / 关停无上界」相关表述，同步更新（预计仅 frame.md 4.11 / 已知缺口表一句）。

## Tasks & Acceptance

**Execution:**
- [x] `src/heagent/tools/mcp/manager.py` -- `_DEFAULT_SHUTDOWN_TIMEOUT` 常量 + `__init__` 参数与校验 + `__aexit__` 调 `_await_shutdown` + `_await_shutdown` 两轮 helper + 模块 docstring -- 核心硬上界
- [x] `tests/test_mcp_manager.py` -- 4 例回归（hang bounded / clean 零回归 / 校验 / 混合）-- 验证意图
- [x] `pytest tests/test_mcp_manager.py -v` -- 15 passed（11 既有 + 4 新）
- [x] `pytest` -- 531 passed 零回归 + `ruff check src tests` 零新增 + `mypy src` 干净
- [x] `_bmad-output/patches/deferred-work.md` -- item A Resolution + item D 关闭 -- 诚实记账
- [x] `docs/frame.md` / `CLAUDE.md` -- 评估后无 stale「__aexit__ 可阻塞 / 关停无上界」表述（frame.md 仅 line 501「退出时 unregister+优雅关闭」仍准确；该缺口从未进已知缺口表，只在 deferred-work.md）→ 按 spec 条件性「若涉则同步」跳过，surgical

**Acceptance Criteria:**
- AC1: Given 某 server task 的 transport `cm.__aexit__` 无限阻塞，when `__aexit__` 执行（`shutdown_timeout=0.05`），then `__aexit__` 在 ≤2.0s 内返回（非挂死），且发出 "MCP 关停超时" WARNING、该 task 被 cancel。
- AC2: Given 所有 server transport 正常关闭（远 < timeout），when `__aexit__` 执行，then 无 "关停超时" WARNING、无 "二次超时" ERROR、所有 task 正常 done（零回归，未被误 cancel）。
- AC3: Given `shutdown_timeout` 传 0 或负值，when 构造 `MCPClientManager`，then `raise ValueError`（fail-closed）。
- AC4: Given server A 正常关闭、B 挂死，when `__aexit__` 执行，then A 的 task 正常 done、B 被 cancel、`__aexit__` bounded 返回（done/pending 分离，单 server 挂死不阻塞其它）。
- AC5: Given `pytest` 全量，then 全绿（MCP manager + mapping + engine + safety 零回归）；`ruff check src tests` / `mypy src` 无新增问题。
- AC6: Given `__aexit__` 任意路径，then 永不在 `await` 上无限阻塞（最坏 ~2×`shutdown_timeout` 返回或记 ERROR 放弃）——核心不变量。

## Design Notes

**为何 `asyncio.wait` 而非 `gather + wait_for`：** `asyncio.wait(tasks, timeout=T)` 返回 `(done, pending)` 且**超时不自动 cancel**（`wait_for` 会 cancel 被包裹的 future）——正好契合「先看谁没退出、再显式 cancel 并记名」的语义，且天然不传播 task 内异常（等同原 `gather(return_exceptions=True)`）。`wait_for(gather(...))` 路径下 cancel 经 gather 传播（依赖「cancel gather future → 取消所有 children」这条 asyncio 语义），虽正确但隐式；`asyncio.wait` + 显式 `task.cancel()` 更可读、不依赖传播细节（CLAUDE.md 显性失败）。

**为何两轮 wait（非单轮 cancel 后即返回）：** 首轮 cancel 后，被取消 task 的 finally（`cm.__aexit__` 被 CancelledError 中断）仍需一个 await tick 跑完——若不 await 即返回，这些 task 残留为「已 cancel 但 finally 未收尾」，event loop 退出前可能触发 "Task was destroyed but it is pending" 或 transport 半关。二轮 bounded wait 让它们干净收尾；若 finally 内有不可中断段致二轮也超时，记 ERROR 放弃（task 已 cancel，最坏余交 OS 进程退出兜底）——这是「绝不无限阻塞」与「尽量干净」的平衡。

**为何整体一个 deadline（非 per-server）：** `asyncio.wait` 的 done/pending 天然分离——先完成的 task 进 done（不受 timeout 惩罚），只有真挂死的进 pending 被 cancel。per-server 超时是 over-engineering：单 server 慢不会拖累其它 server 的 task 完成（它们早已 done）。整体 deadline = 「全部 task 的 graceful 关停宽限」，语义清晰、实现最简。

**为何可配（参数）而非仅常量：** 既有 `connect_timeout` / `health_check_interval` 均为「模块常量 + 构造参数」双形态——第三者 `shutdown_timeout` 沿用同模式保持一致；且测试可直传 `shutdown_timeout=0.05` 免 monkeypatch 模块常量。

**与近期 sandbox 硬化的同构：** sandbox `_kill_and_reap` 用 `asyncio.wait_for(proc.wait(), timeout=_REAP_WAIT_TIMEOUT)` 给子进程回收硬上界（D-state hang 兜底）；本 spec 给 MCP transport 关闭同样硬上界（stdio/HTTP hang 兜底）。两者同属「不可靠外部子进程/连接的关停必须有上界」立场，timeout 取值一致（5.0s）。

**CancelledError 传播不破坏既有语义：** `_server_loop` finally 的 `except Exception`（manager.py:154）本就不捕 `CancelledError`（BaseException）；cancel 注入后 `CancelledError` 经 finally 逸出 task，`asyncio.wait` 将其存于 task（done）不传播——与近期 sandbox「取消信号优先传播」立场一致，无需改 `_server_loop`。

## Verification

**Commands:**
- `pytest tests/test_mcp_manager.py -v` -- expected: 4 例新测试全绿 + 既有 manager 测试零回归
- `pytest` -- expected: 全量绿（MCP + engine + safety 零回归）
- `ruff check src tests` -- expected: 无新增问题
- `mypy src` -- expected: 无新增类型错误

**Manual sanity（可选）：** 临时构造一个 stdio server（`sleep infinity` 类）连入，`async with MCPClientManager(...)` 退出观察是否在 ~`shutdown_timeout` 内返回（非挂死）——真实 transport 路径，本地 Linux/firejail 才有意义；Windows 本机仅跑单测。
