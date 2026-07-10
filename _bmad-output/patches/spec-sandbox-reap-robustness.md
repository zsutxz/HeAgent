# Spec：sandbox reap 鲁棒性收尾（D-1 余波 · 3 项 LOW）

## source
- 路线来源：用户于「bmad 继续开发」方向选择中选定「沙箱 reap 鲁棒性收尾」（一会话一 spec）。
- 根因：`deferred-work.md`「Deferred from: code review of spec-sandbox-cancel-signal-preservation (2026-07-10)」剩 3 项 `defer`（pre-existing / spec 显式 deferred），全部集中在 `src/heagent/tools/sandbox.py` 的 `_kill_and_reap` 与两 helper 的 `except TimeoutError` 块：
  - **item 1**：`except TimeoutError: await _kill_and_reap(proc); return _TIMEOUT_RESULT`（`sandbox.py:95-97,126-128`）未对称加 reap 保护——reap 抛错替换超时返回串上抛，调用方收到 `PermissionError` 而非「Command timed out」（错误消息不对，循环不中断）。与刚修的 `CancelledError` 路径（D-1）处理不对称。
  - **item 2**：`_kill_and_reap` 的 `await proc.wait()`（`sandbox.py:63`）在子进程处不可中断内核态（Linux D-state / pipe transport 对端 hang）时不返回也不抛——`suppress(BaseException)` 只吞异常、对 hang 无能为力，整个 `except` 块卡在 reap，取消信号/超时串被永久阻塞（比 D-1「reap 抛错替换」更坏的形态）。
  - **item 3**：`_kill_and_reap` 的 `proc.kill()`（`sandbox.py:61-62`）抛非 `ProcessLookupError`（如 `PermissionError`）时逃出 `suppress(ProcessLookupError)`，`await proc.wait()` 不执行 → 子进程未杀未 reap、pipe transport 在 GC 前保持打开。inherent「杀不掉」限制。

## 关键设计决策（先读后写 / 契约选定）

### 决策 1：item 2 与 item 3 耦合，须同批修
item 3 的「kill 失败仍 wait」只有在 item 2 的「wait 有硬上界」存在时才安全：kill 失败 → 子进程未被杀 → `wait()` 等其自然退出（可能永不返回）→ 必须 `wait_for` 兜底。故两者同在 `_kill_and_reap` 内修，互为前提。

### 决策 2：`_kill_and_reap` 契约选 Y（reap 仍可抛），不选 X（best-effort 永不抛）
两种候选契约：
- **契约 X**：`_kill_and_reap` 吞一切（kill 失败 + D-state 超时 + re-entrant cancel），永不抛永不 hang → caller 全简化，D-1 的 `except BaseException` 沦为死代码。
- **契约 Y（选定）**：`_kill_and_reap` **吞 kill 失败**（item 3，局部关注：kill 权限失败不阻断 wait），但**让 wait 失败逸出**（item 2 的 D-state `TimeoutError` + re-entrant `CancelledError`），由调用方 `except` 保护。

选 Y 的理由：不重写刚提交的 D-1（其 `except BaseException` 仍有效非死代码——catch 新增的 D-state `TimeoutError` 与 re-entrant cancel）；item 1 在 TimeoutError caller **对称**加保护，契合本仓库「成对路径要对称」教训（iteration.md 教训 3）；职责清晰——kill 是局部 best-effort，wait 失败语义（D-state / 取消）是调用方的事。

### 决策 3：item 1 用 `except Exception`（非 `BaseException`）——放行取消信号
deferred-work 原建议 item 1 用 `except BaseException`。**本 spec 细化为 `except Exception`**：

- item 3 已在 `_kill_and_reap` 内部吞掉 kill 的 `PermissionError`（原 deferred note 的触发例子），故 item 1 caller 实际要兜的是 wait 侧逸出的失败：D-state `TimeoutError`（`Exception` 子类）与 re-entrant `CancelledError`（`BaseException`，非 `Exception`）。
- `except Exception`：吞可恢复的 reap 失败（D-state / `RuntimeError`）返回超时串；**放行 re-entrant `CancelledError`**（任务在 timeout-handler reap 期间被取消时取消信号仍上抛）——延续 D-1「取消传播优先」立场。
- 与 D-1 的 `except BaseException` 不对称，但**正当**：CancelledError 路径须 catch re-entrant cancel 后 bare-raise 恢复原始取消（BaseException 正确）；TimeoutError 路径要返回结果但放行取消（Exception 正确）。冲突在注释里显式暴露（CLAUDE.md「暴露冲突而非折中」），不融合。

## in scope（做）
1. **item 2 + item 3（`_kill_and_reap` 内）**：`await proc.wait()` → `await asyncio.wait_for(proc.wait(), timeout=_REAP_WAIT_TIMEOUT)`；kill 的 `try/except BaseException` 吞权限失败后**仍执行 wait**（解耦），记 debug 日志（observability）。新增模块常量 `_REAP_WAIT_TIMEOUT = 5.0`（秒，SIGKILL 后子进程应毫秒级退出，5s 兜 D-state）。
2. **item 1（两 helper 的 `except TimeoutError` 块）**：`_run_subprocess_shell` 与 `_run_subprocess_exec` 对称加 `try: await _kill_and_reap(proc) except Exception: logger.debug(...)`，reap 非取消失败仍 `return _TIMEOUT_RESULT`。
3. **D-1-A 测试载体迁移**：`test_cancel_survives_reap_error`（Passthrough + Firejail）原用 kill→`PermissionError` 触发 reap 抛错；item 3 后 kill 失败被内部吞、不再逸出 caller，改用 **wait 侧抛错**（fake `wait()` raise `RuntimeError`）——更贴近 D-1 真正关注的 reap 异常场景，断言不变（取消存活 + debug 日志）。
4. **回归测试**：新增 item 1（reap 失败仍返回超时串，Passthrough + Firejail）、item 2（wait 硬上界防 D-state hang）、item 3（kill 失败仍 wait，Passthrough + Firejail）。
5. **文档**：`deferred-work.md` 关闭 3 项 Resolution。

## out of scope（不做 / deferred）
- ❌ 不改两 helper 的 `except asyncio.CancelledError` 块——D-1（commit `0872c06`）仍有效，其 `except BaseException` 现顺带 catch item 2 新增的 D-state `TimeoutError`（bare-raise 恢复原始取消，语义不变）。
- ❌ 不选契约 X（`_kill_and_reap` 全 best-effort 永不抛）——会令 D-1 caller 保护沦为死代码、重写刚提交设计，违反「surgical changes」。
- ❌ D2 进程组 kill（`start_new_session` + `os.killpg`，Linux-only）——Windows 开发机无法验证，仍 deferred。
- ❌ 不把 `_REAP_WAIT_TIMEOUT` 做成用户可配（YAGNI，无调参需求）；测试经 monkeypatch 注入小值。
- ❌ 不专门处理「cancel 恰在 timeout-handler reap 期间到达」的极罕见 race（item 1 用 `except Exception` 已让该场景的取消上抛，进一步精细化无收益）。

## AC（验收）
- **AC1**：item 1——TimeoutError 路径 reap 抛非取消异常（fake `wait()` raise `RuntimeError`）时，runner **返回**超时串（含 `timed out`），不上抛 `RuntimeError`；且记 debug 日志（`timeout cleanup`）。Passthrough 路径。
- **AC2**：item 1——`_run_subprocess_exec`（Firejail + fake exec）对称满足 AC1。
- **AC3**：item 2——reap 的 `wait()` 永不返回（fake `wait()` sleep 1000s 模拟 D-state）时，`_REAP_WAIT_TIMEOUT`（monkeypatch 小值）硬上界生效：task 不 hang、在界内结束（经 cancel 路径触发，reap 逸出 `TimeoutError` → D-1 catch → 取消上抛）。
- **AC4**：item 3——`proc.kill()` 抛非 `ProcessLookupError`（fake `PermissionError`）时，`proc.wait()` **仍被调用**（`proc.waited` 为 True），且记 `kill failed` debug 日志。Passthrough + Firejail 两路径。
- **AC5**：D-1 不回归——既有 `test_cancel_kill_and_reap`（正常 cancel：kill+wait 被调用、抛 `CancelledError`）仍绿；迁移后的 `test_cancel_survives_reap_error`（wait 侧抛错载体）仍断言取消存活 + debug 日志。
- **AC6**：超时 / 正常完成 / firejail argv 既有测试不回归（`test_timeout` / `test_echo_and_exit_code` / `test_nonzero_exit` / `test_run_invokes_firejail_with_expected_argv`）。
- **AC7**：pytest 全绿 / ruff 零新增 / mypy clean。

## 约束（硬）
- DAG：改动限于 `tools/sandbox.py` + `tests/test_sandbox.py`，不引入 `engine` 依赖（engine 依赖 tools，反向禁止）。
- 不改 `CommandRunner` Protocol / `PassthroughRunner` / `FirejailBackend` / RuntimeSlot 注入——reap 鲁棒性是 helper 内部关注，对外契约（`run() -> str`）不变。
- 两 helper 的 TimeoutError 块对称改（shell + exec），不引入单一 chokepoint 重构（YAGNI）。
- 不新增异常类型；复用 `asyncio.wait_for` 的 `TimeoutError` + 既有 `logging.getLogger(__name__)`。

## 立场（不变）
reap（SIGKILL + 回收）是 **best-effort 清理**：它的失败（kill 权限 / D-state / re-entrant cancel）**绝不可**替换上层期望的控制流信号——TimeoutError 路径期望「返回超时串」，CancelledError 路径期望「取消上抛」。item 2 的硬上界把「reap 永久 hang」这一最坏形态（信号被阻塞而非替换）也纳入 best-effort 语义。`except Exception`（item 1）vs `except BaseException`（D-1）的不对称，是「返回结果」与「传播取消」两种上层意图的忠实映射，非疏漏——遵循 CLAUDE.md「显性失败」：reap 的真实 bug 经 debug 日志可诊断，不在控制流路径上抢夺信号。

## Review Findings

（待 bmad-code-review 填）
