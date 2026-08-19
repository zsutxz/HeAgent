---
cycle: sandbox-hardening
epic: S1
story: S1-2
status: backlog
depends_on: S1-1
---

# Story S1-2: ToolExecutor.execute_in_sandbox 注入 profile contextvar

## Story

As a HeAgent 开发者,
I want `ToolExecutor.execute_in_sandbox` 把 `profile` 参数注入 contextvar,
So that `FirejailBackend.run` 内能通过 `get_sandbox_profile()` 取到当前调用的 profile 名。

> 本 story 接上 S1-1 的管道——S1-1 让 FirejailBackend 能查 profiles dict，
> 本 story 让 executor 把 profile 名送进去。依赖 S1-1（`_build_argv` + `get_sandbox_profile()` 调用已存在）。

## Acceptance Criteria

**AC-1（FR-S2 contextvar 基础设施）**
**Given** `tools/sandbox.py` 新增 `_sandbox_profile_slot: RuntimeSlot[str | None]`
**When** `bind_sandbox_profile("network-isolated")` 进入 context
**Then** `get_sandbox_profile()` 返回 `"network-isolated"`
**And** 退出 context 后 `get_sandbox_profile()` 恢复原值

**AC-2（FR-S2 profile=None 行为）**
**Given** `profile=None` 传入 `bind_sandbox_profile`
**When** context 内调 `get_sandbox_profile()`
**Then** 返回 `None`

**AC-3（FR-S2 executor 注入点）**
**Given** `ToolExecutor.execute_in_sandbox(call, profile="network-isolated", handler)`
**When** 执行 handler
**Then** handler 调用被 `bind_command_runner(...)` 和 `bind_sandbox_profile("network-isolated")` 双层 context 包裹
**And** handler 内 `get_sandbox_profile()` 返回 `"network-isolated"`

**AC-4（FR-S2 PassthroughRunner 零回归）**
**Given** `PassthroughRunner.run()` 在任何 profile 上下文中
**When** 执行
**Then** 行为完全不变——不调用 `get_sandbox_profile()`、不因 profile 改变执行路径

## Tasks

- [ ] **Task 1: 新增 contextvar 基础设施** (AC-1, AC-2)
  - [ ] `tools/sandbox.py` 新增 `_sandbox_profile_slot = RuntimeSlot[str | None]("heagent_sandbox_profile")`
  - [ ] 暴露 `bind_sandbox_profile(profile: str | None) -> Iterator[None]` contextmanager
  - [ ] 暴露 `get_sandbox_profile() -> str | None`（`_sandbox_profile_slot.get()` 或 None）
  - [ ] `reset_sandbox_profile()` 测试隔离用

- [ ] **Task 2: executor 注入点** (AC-3)
  - [ ] `engine/executor.py` 的 `execute_in_sandbox` 中，`handler` 调用包在：
    ```python
    with bind_command_runner(self.sandbox_runner):
        with bind_sandbox_profile(profile):
            result = await handler(call)
    ```
  - [ ] `sandbox_runner is None` 的透传路径**不包 bind_sandbox_profile**（profile 无意义）
  - [ ] profile 为 None 时 bind 仍执行（透明 no-op）

- [ ] **Task 3: 测试** (AC-1~4)
  - [ ] `test_bind_sandbox_profile_sets_and_restores`：嵌套 bind 恢复
  - [ ] `test_get_sandbox_profile_default_none`：无 bind 时返回 None
  - [ ] `test_executor_binds_profile`：mock handler → 内部 `get_sandbox_profile()` 断言为预期值
  - [ ] `test_passthrough_runner_ignores_profile`：`PassthroughRunner.run()` 在有 profile 上下文中行为不变
  - [ ] `test_executor_null_runner_no_bind_profile`：`sandbox_runner=None` 时 handler 不经过 profile bind
