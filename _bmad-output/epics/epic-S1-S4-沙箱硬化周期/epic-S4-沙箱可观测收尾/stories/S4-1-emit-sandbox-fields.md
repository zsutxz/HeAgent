---
cycle: sandbox-hardening
epic: S4
story: S4-1
status: backlog
depends_on: S1-2
---

# Story S4-1: executor emit 事件扩展 sandbox_backend + sandbox_pid

## Story

As a HeAgent 操作者/开发者,
I want executor 的 emit 事件标注当前用的是什么沙箱后端,
So that 我能从日志/事件中区分一次 shell 调用是在 firejail 里还是 passthrough 里跑的。

> 依赖 S1-2（`bind_sandbox_profile` contextvar 已存在——PID slot 与其同构）。
> 依赖 S1-1/S2-1（`FirejailBackend` 构造与降级已就位——`type(get_command_runner())` 可推断后端）。

## Acceptance Criteria

**AC-1（FR-S7 PID contextvar）**
**Given** `tools/sandbox.py` 新增 `_sandbox_pid_slot: RuntimeSlot[str]`（类型 `str`，非 `str | None`）
**When** `FirejailBackend.run()` 内子进程启动后
**Then** `_sandbox_pid_slot.set(str(proc.pid))`（或通过 `bind_sandbox_pid(pid)` contextmanager）
**And** PassthroughRunner `run()` 不设置 PID slot

**AC-2（FR-S7 emit 事件字段）**
**Given** executor 四类 emit 事件（`started` / `completed` / `failed` / `blocked`）的 `details` dict
**When** 审查输出
**Then** 含新字段：
- `sandbox_backend: str` — `"passthrough"` / `"firejail"` / `"unknown"`
- `sandbox_pid: str` — PID 字符串（无子进程时为 `""`）

**AC-3（FR-S7 sandbox_backend 推断逻辑）**
**Given** `get_command_runner()` 返回的实例
**When** executor 构造 emit details
**Then** `isinstance(runner, PassthroughRunner)` → `"passthrough"`
**And** `isinstance(runner, FirejailBackend)` → `"firejail"`
**And** 其他 → `"unknown"`

**AC-4（FR-S7 PID 读取与重置）**
**Given** `execute_in_sandbox` handler 返回后
**When** executor 读 `_sandbox_pid_slot.get()`
**Then** 取到 PID（Passthrough 时为空字符串 `""`）
**And** 填入 `tool_call_completed` 事件
**And** 每次调用前 reset PID slot（防上次调用污染下次）

## Tasks

- [ ] **Task 1: PID contextvar** (AC-1)
  - [ ] `tools/sandbox.py` 新增 `_sandbox_pid_slot = RuntimeSlot[str]("heagent_sandbox_pid")`
  - [ ] 暴露 `bind_sandbox_pid(pid: str) -> Iterator[None]` contextmanager
  - [ ] 暴露 `get_sandbox_pid() -> str`（返回 `_sandbox_pid_slot.get() or ""`）
  - [ ] `FirejailBackend.run()` 内 `_run_subprocess_exec` 前设置 `_sandbox_pid_slot.set(str(proc.pid))`（无法在 spawn 前设置——需在 `create_subprocess_exec` 拿到 proc 后立即 set）

- [ ] **Task 2: executor emit 扩展** (AC-2, AC-3, AC-4)
  - [ ] `engine/executor.py` 新增 helper `_sandbox_backend_label() -> str`（从 `get_command_runner()` 推断）
  - [ ] `_execute_in_sandbox` 中：
    - handler 调用前：reset PID slot、取 `sandbox_backend` 标签
    - 用于 `started` 事件的 details
    - handler 返回后：读 `get_sandbox_pid()` 用于 `completed` 事件的 details
  - [ ] `_execute_direct` 中：`sandbox_backend="passthrough"`、`sandbox_pid=""`（DIRECT 路径也走同一 emit 字段，值均默认）
  - [ ] `_policy_error` 中：BLOCKED/APPROVAL_REQUIRED 时 `sandbox_backend` 从 `get_command_runner()` 取（标注「本该用什么后端」）、`sandbox_pid=""`

- [ ] **Task 3: 测试** (AC-1~4)
  - [ ] `test_pid_slot_set_by_firejail_backend`：mock `create_subprocess_exec` → 验证 PID slot 被设置
  - [ ] `test_pid_slot_not_set_by_passthrough`：PassthroughRunner → PID slot 为空
  - [ ] `test_emit_sandbox_backend_passthrough`：mock emit → `sandbox_backend="passthrough"`
  - [ ] `test_emit_sandbox_backend_firejail`：mock emit → `sandbox_backend="firejail"`
  - [ ] `test_emit_sandbox_pid_present`：mock proc.pid=12345 → `sandbox_pid="12345"`
  - [ ] `test_pid_slot_reset_between_calls`：连续两次 execute → 第二次前 PID slot 已重置
