# Spec：CancelledError 清理不吞取消信号（D-1）

## source
- 路线来源：用户于「bmad 继续开发」方向选择中选定「D-1 reap 吞取消信号」（一会话一 spec）。
- 根因：`deferred-work.md`「Deferred from: code review of spec-sandbox-timeout-validation (2026-07-09)」剩 1 项 `defer`（pre-existing adjacent）：
  - **D-1**：`_run_subprocess_shell` / `_run_subprocess_exec` 的 `except asyncio.CancelledError: await _kill_and_reap(proc); raise`——若 `_kill_and_reap` 自身抛异常（`proc.kill()` 抛非 `ProcessLookupError`，或内层 `await proc.wait()` 又被取消），块尾裸 `raise` 不执行，原始 `CancelledError` 被 reap 路径异常替换 → **取消信号丢失**。外层 task 取消（budget 超限 / window reset / SubAgent abort）依赖 `CancelledError` 上抛以触发各层 finally 清理，丢失会破坏这些清理语义。D1（2026-07-09）引入此 `except CancelledError` 块时遗留，非本次 diff 引入。

## 关键语义勘误（先读后写 / 实证）
deferred-work 原建议 fix 为 `try: await _kill_and_reap(proc) finally: raise`——**经实证该写法无效**：

```python
except asyncio.CancelledError:
    try:
        await _kill_and_reap(proc)   # 抛 RuntimeError
    finally:
        raise   # ← 实证：重新抛出 RuntimeError（finally 内裸 raise 抬升 try 体内 in-flight 异常），
                #   CancelledError 沦为 RuntimeError.__context__，取消信号照样丢失
```

CPython 语义：`finally` 块在 try 体内异常 in-flight 时执行，裸 `raise` 抬升的是该 in-flight 异常，**不是**外层 `except` 正在处理的 `CancelledError`。原建议与当前 buggy 写法结果一致（实证：`scenario_try_finally` 与 `scenario_current_buggy` 均抛 RuntimeError）。

**正确机制**：吞掉 reap 的异常后，让裸 `raise` 回到外层 `except CancelledError` 语境（此时当前异常恢复为 `CancelledError`）。实证两等价写法均重新抛出 `CancelledError`：

- `with suppress(BaseException): await _kill_and_reap(proc)` 后裸 `raise`（选定，与本文件 `_kill_and_reap` 内既有 `suppress(ProcessLookupError)` 风格一致）
- `try: ... except BaseException: pass` 后裸 `raise`

`suppress(BaseException)` 对 reap 抛 `RuntimeError` **或** re-entrant `CancelledError`（wait 又被取消）均正确吞掉、抛回原始取消（实证：`suppress_form` / `suppress_recancel` 均抛 `CancelledError`）。

## in scope（做）
1. **D-1 修复**：`_run_subprocess_shell`（`tools/sandbox.py:94-96`）与 `_run_subprocess_exec`（`tools/sandbox.py:113-115`）的 `except asyncio.CancelledError` 块改为 `with suppress(BaseException): await _kill_and_reap(proc)` 后裸 `raise`——确保 reap 失败时原始 `CancelledError` 仍上抛。两 helper 对称改（与 D1 引入时的对称结构一致）。
2. **D-1 回归测试**：`tests/test_sandbox.py` 新增 `test_cancel_survives_reap_error`（`TestPassthroughRunner` + `TestFirejailBackend` 各一），用 fake proc 的 `kill()` 抛非 `ProcessLookupError`（逃出 `_kill_and_reap` 的 `suppress(ProcessLookupError)`），断言取消后 task 抛 `CancelledError` 而非 reap 异常。
3. **文档**：`deferred-work.md` 关闭 D-1 Resolution（含语义勘误说明）。

## out of scope（不做 / deferred）
- ❌ `TimeoutError` 路径的 reap 异常处理（`except TimeoutError: await _kill_and_reap(proc); return ...`）——该路径 reap 抛错会替换超时返回串，但**不涉及取消信号**（无 `CancelledError` 需保护），正交于 D-1，另记。
- ❌ `try/finally: raise` 方案——实证无效（见「关键语义勘误」），不采纳 deferred-work 原建议。
- ❌ 收窄 `suppress(BaseException)` 为 `suppress(Exception)`——reap 路径 re-entrant `CancelledError`（wait 又被取消）属 `BaseException`，须一并吞掉才能保证取消信号优先；保持 `BaseException`，并在 docstring 注明「取消清理优先于 reap 错误上报」的有意取舍。
- ❌ D2 进程组 kill（`start_new_session`+`os.killpg`，Linux-only）——Windows 开发机无法验证，仍 deferred。

## AC（验收）
- **AC1**：取消清理时若 `_kill_and_reap` 抛异常（fake `kill()` 抛非 `ProcessLookupError`），`_run_subprocess_shell` 经取消后 task 抛 `CancelledError`（非 reap 异常）。
- **AC2**：`_run_subprocess_exec`（经 `FirejailBackend` + fake `create_subprocess_exec`）对称满足 AC1。
- **AC3**：正常取消路径（reap 成功）行为不变——既有 `test_cancel_kill_and_reap` 仍绿（kill+wait 被调用、抛 `CancelledError`）。
- **AC4**：超时路径（`TimeoutError`）与正常完成路径行为不变——既有 `test_timeout` / `test_echo_and_exit_code` / `test_nonzero_exit` / firejail argv 测试绿。
- **AC5**：pytest 全绿 / ruff 零新增 / mypy clean。

## 约束（硬）
- DAG：改动限于 `tools/sandbox.py`（runner 层），不引入 `engine` 依赖（engine 依赖 tools，反向禁止）。
- 不改 `_kill_and_reap` 签名/内部逻辑（`suppress(ProcessLookupError)` + `await proc.wait()` 不变）——D-1 在调用方（两 helper 的 `except` 块）加保护，不改被调方。
- 两 helper 对称改（shell + exec），不引入单一 chokepoint 重构（out of scope，YAGNI）。
- 不新增异常类型：`suppress` + 既有裸 `raise`，无新语义。

## 立场（不变）
取消信号（`CancelledError`）是长跑 agent 的正常控制流契约（budget/window-reset/SubAgent-abort 清理依赖它上抛）。reap 清理是 best-effort：reap 失败（kill 权限 / wait 再取消）**绝不可**替换取消信号。选定 `suppress(BaseException)` 即声明「取消传播优先于 reap 错误上报」——遵循 CLAUDE.md「显性失败」的反面平衡：此处「失败」应大声表现为**取消**（它才是上层期望的信号），而非一个意外的 reap `RuntimeError`。reap 的真实 bug 若需独立诊断，应另走日志/observability，不在取消路径上抢夺信号。

## Review Findings（2026-07-10，bmad-code-review on working-tree D-1）

三层对抗式审查（Blind Hunter / Edge Case Hunter / Acceptance Auditor）。**Acceptance Auditor：AC1–AC5 全 PASS、硬约束全 PASS、out-of-scope 无泄漏**（pytest 500 passed / ruff clean / mypy clean 复核）。Blind Hunter 独立回退 buggy commit 实证两新测试 RED、修复后 GREEN；核心语义勘误（`try/finally: raise` 无效 / `suppress`+裸 `raise` 正确 / re-entrant cancel 仍抛原始）经三方复核无误。

### patch（1 项）

- [x] [Review][Patch] **D-1-A reap 失败零 observability**（blind+edge，MED）[`src/heagent/tools/sandbox.py:99-101,123-125`]：`suppress(BaseException)` 吞掉 reap 异常（PermissionError/KeyboardInterrupt/未来 D2 killpg 失败）却**无任何日志**，子进程+pipe FD 泄漏对运维完全不可诊断。两 hunter 独立给同一建议：块内加 debug 日志。修：模块顶部补 `logger = logging.getLogger(__name__)`（**sandbox.py 当前无 logger，违反 CLAUDE.md「每个模块 logger」，顺带合规**），两 `except CancelledError` 块由 `with suppress(BaseException)` 改 `try/except BaseException: logger.debug(..., exc_info=True)`（语义等价、取消信号仍上抛），加测试断言 debug 日志产出。 **已落地（2026-07-10）**：`logger.debug("cancel cleanup: _kill_and_reap failed; subprocess/pipe may leak", exc_info=True)`，`TestPassthroughRunner.test_cancel_survives_reap_error` 加 `caplog` 断言 debug 日志产出。pytest 500 passed / ruff clean / mypy clean。

### defer（3 项，pre-existing / spec 显式 deferred，记 deferred-work.md）

- [x] [Review][Defer] **TimeoutError 路径 reap 抛错替换超时串**（blind+edge，LOW）[`src/heagent/tools/sandbox.py:91-93,115-117`] — spec out-of-scope #1 明确 deferred，不涉取消信号。
- [x] [Review][Defer] **`wait()` D-state 永久 hang**（edge，LOW）[`src/heagent/tools/sandbox.py:59`] — 极端内核态 hang，suppress 无能为力，pre-existing，正交。
- [x] [Review][Defer] **`kill()` 权限失败致子进程+FD 泄漏**（blind，LOW）[`src/heagent/tools/sandbox.py:51-59`] — inherent「杀不掉」限制，调用方不可修；patch D-1-A 的日志部分缓解其可诊断性。
