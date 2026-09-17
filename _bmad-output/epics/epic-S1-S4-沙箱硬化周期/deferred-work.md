# Epic S1–S4 沙箱硬化周期遗留项台账（deferred-work）

> **归并来源**：`_bmad-output/patches/_meta/deferred-work.md`（原跨周期技术债台账，2026-09-15 整理后退役并删除）。
> **归档规则**：按条目**归属的 epic** 归档（本周期 = sandbox 域，含 engine sandbox 后端）；「闭合者」注明实际完成它的 epic / 补丁 spec / commit。
> **只登记已闭合项**——原始长文历史不再保留，结论全部指向代码、测试与 commit。
> **活动（未闭合）遗留项**仍在 [`implementation-artifacts/deferred-work-archive.md`](../../implementation-artifacts/deferred-work-archive.md)。
>
> **立场不变**：以下全部为 defense-in-depth 硬化，**非完美边界**——`FirejailBackend` 仅隔离 `shell`
> 子进程、`WinJobBackend` 无文件系统/网络隔离、file/memory 等宿主进程内 I/O 工具不受覆盖，
> **须整体 OS 级沙箱兜底**（见 `docs/frame.md` 第五章已知缺口）。

## 状态总览

| ID | 条目 | 状态 | 闭合者 |
|----|------|------|--------|
| S-D1 | `spec-engine-sandbox-backend` 评审 4 项 `defer` | 4 项全部闭合（含 1 项**勘误：早已交付**） | `spec-sandbox-timeout-validation` + S1–S4 交付（`5a4a29e` / `6e526c9`） |
| S-D2 | `spec-sandbox-timeout-validation` 评审 1 项 `defer` | 已修复 | `spec-sandbox-cancel-signal-preservation` |
| S-D3 | `spec-sandbox-cancel-signal-preservation` 评审 3 项 `defer` | 3 项全部修复 | `spec-sandbox-reap-robustness` |
| S-D4 | 沙箱执行的资源限额（内存/CPU） | 已闭合（2026-09-17；进程数限额另立活动条目） | 优化批次 2（`0582a03`） |
| S-D5 | Firejail 高级隔离参数（--seccomp / --caps） | 已闭合（2026-09-17，`SANDBOX_PROFILES` 声明、默认关闭） | 优化批次 2（`0582a03`） |
| S-D6 | per-tool 粒度的 firejail 参数 | 已闭合（2026-09-17，`SANDBOX_TOOL_PROFILES` 两段组合） | 优化批次 2（`0582a03`） |

---

## S-D1 `spec-engine-sandbox-backend` 评审 4 项 `defer`

- **来源**：step-04 review of `spec-engine-sandbox-backend`（2026-07-09，blind hunter + edge case hunter + acceptance auditor，commit `4a8bf17`）。AC1–AC8 全通过、无约束违反；4 项 classified `defer`（pre-existing / test quality），3 项 patch 另记 spec。

| # | 发现 | 结论与证据 |
|---|------|-----------|
| a | `CancelledError` 中断 `communicate()` 泄漏子进程——`_run_subprocess_shell`/`_run_subprocess_exec` 仅 `except TimeoutError`，外层 task 取消（budget 超 / window reset / SubAgent abort）时 proc 无 kill 无 wait，泄漏子进程 + FD（pre-existing） | **已修复**（2026-07-09）。两 helper 加 `except asyncio.CancelledError: await _kill_and_reap(proc); raise`（与超时 kill 同 hunk），取消时亦 kill+wait。回归 `tests/test_sandbox.py::TestPassthroughRunner::test_cancel_kill_and_reap`（fake proc 阻塞 `communicate`，取消后断言 kill+wait 被调用） |
| b | 超时 kill 不杀进程组——`proc.kill()` 仅 SIGKILL 直系子进程，`sh -c "sleep 1000 &"` 的后台子孙被 init 收养、存活（pre-existing） | **勘误（2026-09-15）：该项早已交付，原「deferred to Linux env / 标记关闭」记载作废。** 逐条核对代码确认：①`_run_subprocess_shell`/`_run_subprocess_exec` 在 `sys.platform == "linux"` 时置 `start_new_session=True`（子进程自成进程组）；②`_kill_and_reap` 在 Linux 上以 `os.killpg(proc.pid, SIGKILL)` 杀**整组**，并**有意不经 `os.getpgid`**——避免「子进程已退出 + PID 被 OS 回收 → `getpgid` 返回他人 pgid → `killpg` 误杀无关进程组」的 PID 复用竞态；③原担心的「Passthrough 与 Firejail 两路径行为不同」**不成立**：`FirejailBackend.run` 最终同样调 `_run_subprocess_exec`，两路径共用同一 kill/reap 实现。交付于 `5a4a29e`（S1–S4），竞态修正于 `6e526c9`（代码审查 7 个 HIGH）。证据：`src/heagent/tools/sandbox.py:184,188,206,230`；`tests/test_sandbox.py::test_kill_and_reap_linux_uses_proc_pid_directly`（钉 `platform=linux`，断言 `os.getpgid` 从未被调用、`os.killpg` 恰以 `(proc.pid, SIGKILL)` 调用一次）+ 该文件与 `tests/test_coverage_sandbox.py` 的 `os.killpg` no-op 隔离夹具 |
| c | `timeout <= 0` 无校验——`shell(command, timeout=120)` 不校验正性，LLM 传 0/负值 → spawn 后 `wait_for` 立即 TimeoutError → 竞态 kill 未启动的进程（pre-existing） | **已修复**（`spec-sandbox-timeout-validation`，D3+D4 bundle）。入口加 `_validate_timeout(timeout)` 守卫，选定 **raise 而非 clamp**（匹配 `config.py shell_timeout ge=1` 惯例 + 显性失败）；code review 后**拓宽为正整数校验**：`isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0` 一律 `raise ValueError`（fail-closed——拦 None/str/float/bool/nan/inf，避免 `<=` 对非数值抛 TypeError、`nan` 绕过破坏 asyncio timer 堆全序）；两 helper 共享单一守卫（顺带 dedup）。证据：`src/heagent/tools/sandbox.py:197`；`tests/test_sandbox.py::test_timeout_zero_raises_before_spawn` / `::test_timeout_negative_raises_before_spawn`（Passthrough + Firejail 两路径，match 锁 `got <值>$`）+ `::test_timeout_non_int_raises_before_spawn`（参数化 None/str/float/bool/nan）+ 端到端 `::test_invalid_timeout_becomes_error_toolresult`（AC5，ValueError 经 executor `except Exception` → `is_error` ToolResult） |
| d | `test_firejail_argv` 的 mock result-shape 断言弱（test quality）——`_FakeProc.returncode=0` 为类属性、`communicate` 硬编码，`"exit_code=0" in result` 对 fake 恒真 | **已修复**（2026-07-09）。`_FakeProc.returncode` 改为 per-instance（`__init__` 置 `None`，`communicate` 内 `self.returncode = 42`），断言由 `"exit_code=0"` 改为 `"exit_code=42"` → 现验证 `_run_subprocess_exec` 在 `communicate` **完成后**才读 `proc.returncode`（若提前读得 `None` → 断言红），非同义反复。证据：`tests/test_sandbox.py:79,440` |

---

## S-D2 `spec-sandbox-timeout-validation` 评审 1 项 `defer`

- **来源**：step-04 review of `spec-sandbox-timeout-validation`（2026-07-09）。AC1–AC6 全满足；4 项 `patch` 已落地，1 项 `defer`（pre-existing adjacent），2 项 dismissed（推测性，无现存绕过）。
- **发现**：`_kill_and_reap` 在 `except CancelledError` 块内自身抛异常会**吞掉原始取消信号**——`except asyncio.CancelledError: await _kill_and_reap(proc); raise` 中若 reap 自身抛错（`proc.kill()` 抛非 `ProcessLookupError`，或内层 `await proc.wait()` 又被取消），块尾裸 `raise` 不执行，原始 `CancelledError` 被 reap 路径异常替换 → 与 D1「CancelledError 清理」意图相悖，可能破坏 budget / window-reset / SubAgent-abort 清理。
- **结论**：**已修复**（2026-07-10，补丁 spec `_bmad-output/epics/epic-S1-S4-沙箱硬化周期/spec-sandbox-cancel-signal-preservation.md`，D-1）。
  - **关键语义勘误**：原建议 `try: await _kill_and_reap(proc) finally: raise` **实证无效**——finally 内裸 `raise` 会抬升 try 体内 in-flight 异常，`CancelledError` 沦为 `__context__`；正确机制是 `except BaseException: logger.debug(..., exc_info=True); raise`（吞掉 reap 异常 → 回到外层 `except CancelledError` 语境 → 重抛原始取消信号）。两 helper 同改（patch D-1-A 顺带补 observability：reap 失败记 debug 日志 + 补模块缺失的 `logging.getLogger(__name__)`）。
- **证据**：`tests/test_sandbox.py::test_cancel_survives_reap_error`（Passthrough + Firejail 两路径）断言取消后 task 抛 `CancelledError` 而非 reap 的 `PermissionError`。

---

## S-D3 `spec-sandbox-cancel-signal-preservation` 评审 3 项 `defer`

- **来源**：step-04 review of `spec-sandbox-cancel-signal-preservation`（2026-07-10，commit 前的 D-1 改动）。AC1–AC6 全满足；1 项 `patch` 已落地（D-1-A observability），3 项 `defer`（pre-existing / spec 显式 deferred）。三项全部集中在 `tools/sandbox.py` 的 `_kill_and_reap` 与两 helper 的 `except TimeoutError` 块。
- **结论**：**三项全部修复**（2026-07-10，补丁 spec `_bmad-output/epics/epic-S1-S4-沙箱硬化周期/spec-sandbox-reap-robustness.md`）。

| # | 发现 | 结论与证据 |
|---|------|-----------|
| 1 | `TimeoutError` 路径 reap 抛错会**替换超时返回串**——`except TimeoutError: await _kill_and_reap(proc); return _TIMEOUT_RESULT` 未对称加 reap 保护，若 reap 抛 `PermissionError` 该异常替换「Command timed out」上抛（经 executor `except Exception` 转成 `is_error` ToolResult，错误消息不对但循环不中断） | **已修复**：加 `try: await _kill_and_reap(proc) except Exception: logger.debug("timeout cleanup: ...", exc_info=True)` 后仍 `return _TIMEOUT_RESULT`。**细化于原建议**：用 `except Exception`（**非** `BaseException`）——放行 re-entrant `CancelledError`（reap 期间任务被取消时取消信号仍上抛，延续 D-1「取消传播优先」）；与 D-1 的 `except BaseException` 不对称但正当（超时路径要返回结果，取消路径要传播取消）。证据：`tests/test_sandbox.py::test_timeout_reap_failure_returns_timeout_result`（Passthrough + Firejail，fake `wait()` raise `RuntimeError`，断言返回超时串 + `timeout cleanup` 日志） |
| 2 | `await proc.wait()` 在 D-state 永久 hang——`_kill_and_reap` 的 wait 在子进程处于不可中断内核态时不返回也不抛，`suppress(BaseException)` 只吞异常、对 hang 无能为力 → `except CancelledError` 块卡在 reap、裸 `raise` 永不执行，取消信号被**永久阻塞**（比替换更坏） | **已修复**：`await asyncio.wait_for(proc.wait(), timeout=_REAP_WAIT_TIMEOUT)`，新增模块常量 `_REAP_WAIT_TIMEOUT = 5.0`。D-state 永久 hang 现有硬上界，超时逸出的 `TimeoutError` 由调用方保护（超时路径 item 1 返回超时串、取消路径 D-1 传播取消）。证据：`src/heagent/tools/sandbox.py:140,194`；`tests/test_sandbox.py::test_reap_wait_is_bounded`（monkeypatch `_REAP_WAIT_TIMEOUT=0.05`，fake `wait()` sleep 1000 模拟 D-state，经 cancel 路径触发；断言 task 在 `< 2.0s` 内结束而非 hang + `cancel cleanup` 日志证明 `wait_for` 兜住后放弃 reap） |
| 3 | `proc.kill()` 权限失败致子进程 + pipe FD 泄漏——抛非 `ProcessLookupError`（如 `PermissionError`；Windows `TerminateProcess` 对已退出进程亦可能抛 `ERROR_ACCESS_DENIED`）时逃出 `suppress(ProcessLookupError)`，`await proc.wait()` 不执行 | **已修复**：`proc.kill()` 包进 `try/except BaseException`（记 `kill failed` debug 日志）后**仍执行**带硬上界的 `wait`——kill 与 wait 解耦。**关键耦合**：item 3（解耦）只在 item 2（wait 硬上界）存在时才安全——kill 失败 → 子进程可能不死 → `wait()` 等其自然退出（可能永不返回）→ 须 item 2 的 `wait_for` 兜底；故两者同批在 `_kill_and_reap` 内修。**副作用**：kill 的 `PermissionError` 现被内部吞掉、不再逸出 caller，故 D-1-A 测试载体从 `kill→PermissionError` 迁移为 `wait→RuntimeError`。证据：`tests/test_sandbox.py::test_kill_failure_still_waits`（Passthrough + Firejail，fake `kill()` raise `PermissionError`，断言 `proc.waited=True` + `kill failed` 日志） |

- **同构关闭**：本周期补齐 sandbox 侧后，另两处同构关停硬上界分别在 `epic-11-18-MCP集成周期/deferred-work.md`（E11-D1a，MCP `__aexit__`）与 `epic-01-10-主线规划周期/deferred-work.md`（E10-D1，`CronScheduler.stop`）——「不可靠外部子进程/连接/任务的关停必须有上界」立场（timeout 统一 5.0s）**三处补齐完毕**。

---

## S-D4 沙箱执行的资源限额

- **来源**：`brief.md`「### Deferred（未来考虑）：沙箱执行的资源限额」；2026-09-17 第二轮优化批次闭合（commit `0582a03`）。
- **问题**：沙箱 shell 无内存/CPU 上界，LLM 触发的大内存或长 CPU 命令可拖垮宿主。
- **结论**：**已闭合**。新增 `SANDBOX_MEMORY_LIMIT_MB` / `SANDBOX_CPU_SECONDS`（默认 0=关闭，默认行为逐字节不变）：firejail 映射 `--rlimit-as` / `--rlimit-cpu`（profile 参数后、`--` 前）；WinJob 映射 `JOB_OBJECT_LIMIT_JOB_MEMORY` / `JOB_OBJECT_LIMIT_PROCESS_TIME`（与恒开 KILL_ON_JOB_CLOSE 按位或，复用既有内联结构体零新增）。**触发即显性失败**（子进程被终止 → 非零退出码经正常结果回传，对齐超时 `exit_code=-1` 先例），不静默截断。进程数限额未做→另立活动条目（`implementation-artifacts/deferred-work-archive.md`，fork bomb 现由 `_DANGEROUS_PATTERNS` 启发式覆盖）。
- **证据**：`tests/test_sandbox_mode.py::TestSandboxHardeningConfig` / `::TestFirejailResourceLimitsArgv`（argv 位置与默认零参数）；`tests/test_coverage_sandbox.py::TestWinJobBackend::test_run_applies_resource_limits`（Windows 真跑断言 flags 与限额值）。

## S-D5 Firejail 高级隔离参数（--seccomp / --caps）

- **来源**：`brief.md`「### Deferred（未来考虑）」；2026-09-17 第二轮优化批次闭合（commit `0582a03`）。
- **问题**：无 `--seccomp` / `--caps` 等高级参数，隔离强度停留在 `--private` + `--net=none` + 进程组 kill。
- **结论**：**已闭合**。新增 `SANDBOX_PROFILES`（JSON：profile 名 → firejail 参数表，如 `{"default": ["--seccomp", "--caps.drop=all"]}`）经 `EngineContainer.default()` 传入 `FirejailBackend.profiles`——勘察确认此前生产装配下 `profiles` 恒空（仅测试/库消费者手工注入）；高级参数由此声明、**默认关闭**（冻结边界满足）；坏 JSON/坏条目告警丢弃（对齐 `routing_pool_map` 容错）。
- **证据**：`tests/test_sandbox_mode.py::TestSandboxHardeningWiring::test_profiles_flow_into_firejail_backend`。

## S-D6 per-tool 粒度的 firejail 参数

- **来源**：`brief.md`「### Deferred（未来考虑）」；2026-09-17 第二轮优化批次闭合（commit `0582a03`）。
- **问题**：参数集只到 profile 粒度——给单工具加参数必须新建 profile。
- **结论**：**已闭合**。新增 `SANDBOX_TOOL_PROFILES`（JSON：工具名 → profile 名）叠加进 `PolicyEngine.sandbox_profiles`（`container.default()` 注入），与 `SANDBOX_PROFILES` 两段配置组合即得 per-tool 参数差异——不引入新抽象（对齐 epic 边界「不引入 SandboxProfile 类」），fail-safe 阻断契约未动（executor 双重授权复核与 `context_grants_sandbox` 无 context 恒 False 均原样）。
- **证据**：`tests/test_sandbox_mode.py::TestSandboxHardeningWiring::test_tool_profiles_update_policy_mapping`（verdict 联动断言）。
