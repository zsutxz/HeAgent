# Epic 1–10 周期遗留项台账（deferred-work）

> **归并来源**：`_bmad-output/patches/_meta/deferred-work.md`（原跨周期技术债台账，2026-09-15 整理后退役）。
> **归档规则**：按条目**归属的 epic** 归档；「闭合者」注明实际完成它的 epic / 补丁 spec / commit。
> **只登记已闭合项**——原始长文历史不再保留，结论全部指向代码、测试与 commit。
> **活动（未闭合）遗留项**仍在 [`implementation-artifacts/deferred-work.md`](../../implementation-artifacts/deferred-work.md)（工作流 append-only 入口）。
> 立场不变：本文件涉及的安全相关结论均为 defense-in-depth，**非真正安全边界**，须 OS 级沙箱兜底。

## 状态总览

| ID | 归属 | 条目 | 状态 | 闭合者 |
|----|------|------|------|--------|
| E1-D1 | Epic 1 基础设施与 LLM 通信 | ProviderChain 对已包装 `ProviderError` 双层重包 | 已修复 2026-06-19 | P0 技术债收尾 spec |
| E1-D2 | Epic 1 | 流式 backstop 丢失最后错误上下文 | 已修复 2026-06-20 | P0 技术债收尾 spec |
| E4-D1 | Epic 4 记忆巩固（Dreaming） | AC6 端到端：`web_fetch` 返回未接 `guard_content` | 已修复 2026-08-19 | Epic 35 |
| E4-D2 | Epic 4 | Dreaming 对抗审查 3 个 LOW defer | 三项全部修复 2026-08-12 | `spec-dreaming-defer-cleanup` |
| E5-D1 | Epic 5 上下文与子 Agent | SubAgent 共享 `SkillStore` 写竞态 | **核实不成立，关闭** 2026-06-19 | P0 技术债收尾 spec |
| E10-D1 | Epic 10 定时调度 | `CronScheduler.stop()` 关停无上界 | 已修复 2026-07-11 | `spec-cron-stop-timeout` |
| E10-D2 | Epic 10 | `cron/expr` 范围+步进分支诊断不可读 | 已修复 2026-08-19 | Epic 35 |

---

## Epic 1 · Provider 与容错

### E1-D1 ProviderChain 对已包装 `ProviderError` 双层重包

- **来源**：`spec-p0-provider-hardening` 评审（2026-06-19，盲审 + 边界 hunter，classified `defer`）。
- **问题**：P0-2 让 provider 源头把 SDK 异常包装成 `ProviderError` 后，`chain.send/stream` 的 `except Exception` 仍二次包装 → `ProviderError → __cause__ → ProviderError → __cause__ → 原始 SDK 异常`。分类 / `status_code` 仍正确（duck-type 透过提取），仅 traceback 多一层、组合层 `__cause__` 不再是原始 SDK 异常。
- **结论**：**已修复**（2026-06-19）。`chain.py` 以 `_raise_provider_error(error) -> NoReturn` 取代 `_wrap_error`——已是 `ProviderError` 则原样 `raise`（保留既有 cause 链），否则 `raise wrap_provider_error(error) from error`；4 个调用点统一替换，send 的死代码 backstop 也由裸 `RuntimeError` 改为 `ProviderError`（遵守「禁止裸 Exception」契约）。
- **证据**：`src/heagent/providers/chain.py:25`；`tests/providers/test_chain.py::test_send_no_double_wrap_on_inner_provider_error`、`::test_stream_no_double_wrap_on_inner_provider_error`。

### E1-D2 流式 backstop 丢失最后错误上下文

- **来源**：E1-D1 同一 backstop 区域的评审发现（2026-06-19）。
- **问题**：`ProviderChain.stream` 末尾兜底 `raise ProviderError("All providers failed for stream")` 不跟踪 `last_error`（流式路径在可回退错误时仅 `break`）→ 所有 provider 流式均失败时抛出的异常无 `status_code`、无 `__cause__`；`send()` 版 backstop 已正确委托 `_raise_provider_error(last_error)`，流式版未对称实现。仅影响罕见全失败路径的错误信息精度。
- **结论**：**已修复**（2026-06-20）。`stream` 循环跟踪 `last_error`，末尾 `if last_error is not None: _raise_provider_error(last_error)`，与 `send` 对称，保留状态码与 cause。
- **证据**：`src/heagent/providers/chain.py:165`；`tests/providers/test_chain.py::test_stream_all_fail_preserves_last_error_status`。

---

## Epic 4 · 记忆巩固（Dreaming）

### E4-D1 AC6 端到端：`web_fetch` 返回路径未接 `guard_content`

- **来源**：`spec-dreaming-memory-consolidation` AC6（2026-08-11 human renegotiate 降级为「函数级复用」），端到端接入 defer。
- **问题**：仅 MCP 工具返回经 `mapping.bridge_result` 走注入围栏；内置 `web_fetch`（`tools/builtins/web.py`）handler 返回路径未接入 → dreamer 无人监督联网的返回内容直接进 LLM 上下文，prompt injection 无围栏。（缓解：`dream_enabled` 默认 False，opt-in；dreamer 工具白名单最小化。）
- **结论**：**已修复**（2026-08-19，Epic 35）。`web_fetch` handler 返回前调 `guard_content(text)`（复用 `tools/mcp/mapping.guard_content`，与 `bridge_result` 对齐），命中内置注入签名则加 warning 标记后**透传**（`is_error=False`，不阻断）。web_fetch 信任模型与 MCP 工具收敛一致。
- **证据**：`src/heagent/tools/builtins/web.py:183`；`tests/test_epic35.py::TestWebFetchGuardContent`。
- **立场**：标记仅 observable defense-in-depth，变形攻击仍会漏过（FN 由测试锁定），**非真正边界**。

### E4-D2 Dreaming 对抗审查 3 个 LOW defer

- **来源**：`spec-dreaming-memory-consolidation` step-04 双 hunter 对抗审查（2026-08-12），3 项均判 low、非阻断。
- **闭合者**：补丁 spec `_bmad-output/patches/memory/spec-dreaming-defer-cleanup.md`（一会话一 spec，inline 对抗审查 clean）。

| # | 发现 | 结论与证据 |
|---|------|-----------|
| a | `memory/dream.py` → `cron.scheduler` 横向 DAG 边：伸手进 `CronScheduler._matches` 私有静态做 cron 校验（coupling smell，DAG 图无此边） | 抽**纯叶子** `heagent/cron/expr.py`（`cron_matches`，零 heagent 导入），`dream.py` 改 import 该函数、不再绑定 `CronScheduler`；`CronScheduler._matches` 降为薄委托（`scheduler.py:208`）以保 `test_cron.py` 16 处调用零回归 |
| b | `DreamScheduler._await_stop` 超时分支孤儿 task（`if pending:` 仅记 ERROR，未置 `_task = None`、未取回 exception → 可能触发 "Task exception was never retrieved"） | 补 `task.add_done_callback(_retrieve_task_exception)` + `self._task = None`；`CronScheduler._await_stop` 同构同修。`_retrieve_task_exception` 带 cancelled 守卫——`task.exception()` 对 cancelled task 会抛 `CancelledError`（`dream.py:63`、`scheduler.py:211`） |
| c | `_run_dream` 的 `CancelledError` 分支总标 `aborted=True`，无法区分 `stop()` 取消 vs 子任务内部自取消（审计精度） | 按 `self._running` 区分：`aborted=not self._running`（stop 取消）、`internal_cancel=self._running`（内部自取消）；取消信号仍 `raise`。不变量来自 `stop()` 首行置 `_running=False` 后才 cancel（单线程 asyncio 无竞态） |

- **落点说明**：解析器选 `cron/expr.py` 而非原建议的 `tools/cron_expr.py`——解析器零 heagent 导入、自然属 `cron` 包；`cron → tools`（原建议）反让 cron 为拿自家解析器而依赖 tools，更别扭。`memory → cron.expr` 是对纯叶子的正当依赖，类比 `engine.persist`。
- **证据**：`src/heagent/cron/expr.py`、`src/heagent/cron/scheduler.py:97,208,211`、`src/heagent/memory/dream.py:45,63,215`；`tests/test_cron.py` / `tests/test_cron_range.py` / `tests/test_dream.py` 新增 7 例（expr 独立可用 + 纯叶子无 heagent 导入 / `dream.py` 不再 import `CronScheduler` / 两处 `_await_stop` 超时清 `_task` 且挂 callback / `_retrieve_task_exception` 三态契约 / `_run_dream` 两种取消语义）。

---

## Epic 5 · 上下文与子 Agent

### E5-D1 SubAgent 共享 `SkillStore` 写竞态（核实不成立）

- **来源**：`spec-5-1-subagent-context-injection` step-04 评审（2026-06-18，edge case hunter，classified `defer`；spec 显式排除解决此项）。
- **原判**：`task_parallel` 下多个 SubAgent 共享同一注入的 `SkillStore`，各自 `_build_system()` → `record_usage()` → `save()` → 写同一 `SKILL.md`；`asyncio.gather` 下并发 parse→+1→save 会丢更新或交错写。
- **结论**：**核实不成立，关闭**（2026-06-19）。`record_usage`/`save` 是无 `await` 的同步方法（`write_text` 同步 I/O），`_build_system` 整段同步 → 单线程 asyncio 下两个 SubAgent 的调用必然串行，不存在丢失更新/交错写。**未引入 `asyncio.Lock`**——其 `acquire` 是 awaitable，同步方法内无法使用；`threading.Lock` 在单线程无意义。
- **证据**：`tests/test_sub_agent.py::TestParallel::test_parallel_shared_skillstore_no_lost_usage_update` 锁定「并发不丢更新」不变量；若未来 SkillStore 方法 async 化（届时 `read_text`/`write_text` 须 async）引入真正 `await` 交错，该测试将变红提醒重新评估并发安全。
- **跨 epic 教训**：**edge case hunter 会误判并发竞态**——审查发现要先核实是否真有 `await` 交错，再定级。

---

## Epic 10 · 定时调度

### E10-D1 `CronScheduler.stop()` 关停无上界

- **来源**：`spec-mcp-shutdown-timeout`（commit `109df37`）code review 指出的**同构兄弟缺口**（2026-07-11，review agent 提出）。
- **问题**：`stop()` 在 `_running = False` 后对未完成 task `task.cancel()` + `with contextlib.suppress(asyncio.CancelledError): await self._task`，该 `await` 无硬上界。`_tick_loop` 卡在 `_check_and_execute` → `_execute_job` → `await loop.run(job.prompt)`（`AgentLoop.run`）的不可中断 await 点时，cancel 注入的 `CancelledError` 被吞 → task 不退出 → `stop()` 无限阻塞。唯一调用方是 CLI 交互模式 `finally`（进程退出路径）→ 挂死 = 进程退出挂死，需 OS SIGKILL 兜底。
- **结论**：**已修复**（补丁 spec `_bmad-output/patches/cron/spec-cron-stop-timeout.md`）。抽 `_await_stop(task)`：保留原「立即 cancel」语义（cron 停止求快；`_tick_loop` 多在 `asyncio.sleep(tick_seconds)`，graceful 窗口反增延迟），`task.cancel()` 后单轮 `asyncio.wait({task}, timeout=stop_timeout)`——**最坏 `stop_timeout` 必返回，绝不无限阻塞**。`stop_timeout` 为构造参数（默认 `_DEFAULT_STOP_TIMEOUT=5.0`，对齐 MCP `_DEFAULT_SHUTDOWN_TIMEOUT` / sandbox `_REAP_WAIT_TIMEOUT`），`<=0` 构造期 raise；移除原 `contextlib.suppress`（`asyncio.wait` 不传播 task 内异常，比原 suppress 更宽）与不再需要的 `import contextlib`。
- **证据**：`src/heagent/cron/scheduler.py:78,81`；`tests/test_cron.py::test_stop_timeout_must_be_positive`、`::test_stop_bounded_when_tick_hangs`（用 `asyncio.wait_for(body, 2.0)` 做挂死探测器）、`::test_stop_clean_no_error_on_sleep`。
- **同构三处**（「不可靠外部子进程 / 连接 / 任务的关停必须有上界」，timeout 统一 5.0s）：sandbox reap（D-state，见 `epic-S1-S4-沙箱硬化周期/deferred-work.md` S-D3）+ MCP `__aexit__`（见 `epic-11-18-MCP集成周期/deferred-work.md` E11-D1a）+ 本项。**最后一块同构缺口补齐完毕**。

### E10-D2 `cron/expr` 范围+步进分支诊断信息不友好

- **来源**：`spec-dreaming-defer-cleanup` 的 /code-review（2026-08-12，AST 比对 + `git show` 确认逐字搬迁）。
- **问题**：`cron/expr.py` 的「范围+步进」分支（`"/" in part and "-" in part`）对畸形输入如 `*/5-10` 抛内部 `ValueError: not enough values to unpack`，而非域级 `Invalid cron field expression`。**功能安全**——仍是 `ValueError`、仍被 per-job handler 捕获，对任何合法 cron 语法无影响，仅病态输入的诊断可读性。
- **结论**：**已修复**（2026-08-19，Epic 35）。范围+步进分支在 `range_part.split("-", 1)` 解包前先校验 `"-" not in range_part`，命中则抛域级 `Invalid cron field expression`。
- **证据**：`src/heagent/cron/expr.py`；`tests/test_epic35.py::TestCronMalformedRangeStep`。
