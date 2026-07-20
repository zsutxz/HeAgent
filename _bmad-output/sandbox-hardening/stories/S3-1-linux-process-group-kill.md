---
cycle: sandbox-hardening
epic: S3
story: S3-1
status: backlog
---

# Story S3-1: Linux 进程组 killing

## Story

As a HeAgent 操作者,
I want shell 子进程被 kill 时其后台子孙一并终止,
So that `sh -c "cmd1 & cmd2"` 的孤儿进程不残留。

> 独立 story——仅改 `_run_subprocess_shell/exec` + `_kill_and_reap` 内部，
> 不依赖 S1 或 S2。Linux-only，非 Linux 路径零改动。

## Acceptance Criteria

**AC-1（FR-S5 Linux start_new_session）**
**Given** `sys.platform == "linux"`
**When** `_run_subprocess_shell(command, timeout=...)` 创建子进程
**Then** 传 `start_new_session=True`（子进程成为新会话组长 + 进程组长）
**And** `_run_subprocess_exec` 同

**AC-2（FR-S5 Linux killpg）**
**Given** Linux 平台
**When** `_kill_and_reap(proc)` 收尾
**Then** `proc.kill()` 替换为 `os.killpg(os.getpgid(proc.pid), signal.SIGKILL)`
**And** `ProcessLookupError` 被 suppress（竞态：子进程在 killpg 前恰退出）
**And** `PermissionError` / `OSError` 经既有 `except OSError` 降级（与 item 3 kill/wait 解耦兼容）
**And** kill 失败后仍执行 `await proc.wait()`（item 3 解耦不受影响）

**AC-3（NFR-S1 非 Linux 零回归）**
**Given** 非 Linux 平台
**When** 子进程创建 + kill
**Then** 行为完全不变——不传 `start_new_session`、用 `proc.kill()` 而非 `killpg`

**AC-4（NFR-S3 跨平台测试覆盖）**
**Given** mock `sys.platform` 分别为 `"linux"` 和 `"win32"`
**When** 执行 kill 路径
**Then** Linux 走 `os.killpg`，Windows 走 `proc.kill()`

## Tasks

- [ ] **Task 1: _run_subprocess_shell/exec 加 start_new_session** (AC-1, AC-3)
  - [ ] 在 `create_subprocess_shell` / `create_subprocess_exec` 调用的 kwargs 中：
    `**({"start_new_session": True} if sys.platform == "linux" else {})`
  - [ ] 不改变现有 kwargs（`stdout=PIPE, stderr=PIPE`）

- [ ] **Task 2: _kill_and_reap 加 killpg 分支** (AC-2, AC-3)
  - [ ] `import os, signal`（文件顶部已有 `import asyncio, logging`）
  - [ ] kill 块重构为：
    ```python
    if sys.platform == "linux":
        with suppress(ProcessLookupError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
    else:
        with suppress(ProcessLookupError):
            proc.kill()
    ```
  - [ ] 后续 `except OSError` 块不变（killpg 的 PermissionError 也在此处理）
  - [ ] `await proc.wait()` 不变

- [ ] **Task 3: 测试** (AC-1~4)
  - [ ] `test_linux_uses_start_new_session`：mock `sys.platform="linux"` → 验证 create 调用含 `start_new_session=True`
  - [ ] `test_non_linux_no_start_new_session`：mock `sys.platform="win32"` → 验证 create 调用不含 `start_new_session`
  - [ ] `test_linux_uses_killpg`：mock `os.killpg` + `os.getpgid` → 验证 Linux 走 killpg
  - [ ] `test_non_linux_uses_proc_kill`：mock `sys.platform="win32"` → 验证走 `proc.kill()`
  - [ ] `test_killpg_process_lookup_error_suppressed`：`os.killpg` 抛 `ProcessLookupError` → 被吞
  - [ ] `test_killpg_permission_error_still_waits`：`os.killpg` 抛 `PermissionError` → `except OSError` → 仍 wait
  - [ ] 与既有 `test_kill_failure_still_waits` 不冲突（该测试 mock `sys.platform` 使走非 Linux 路径）
