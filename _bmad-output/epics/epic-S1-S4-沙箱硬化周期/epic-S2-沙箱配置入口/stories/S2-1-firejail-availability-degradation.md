---
cycle: sandbox-hardening
epic: S2
story: S2-1
status: backlog
---

# Story S2-1: FirejailBackend 可用性检测 + 优雅降级

## Story

As a HeAgent 操作者,
I want firejail 不可用时 agent 能优雅降级继续工作,
So that 我不因为机器没装 firejail 而整个 agent 崩溃。

> 本 story 独立——不依赖 S1（`FirejailBackend` 降级路径走 `PassthroughRunner`，
> 与 profile 无关）。可与 S1 并行开发。

## Acceptance Criteria

**AC-1（FR-S3 构造期检测）**
**Given** `FirejailBackend.__init__` 中 `shutil.which(self._firejail_path)` 返回 `None`
**When** 构造实例
**Then** `self._firejail_available = False`
**And** 记 `logger.warning("firejail not found at %r, sandbox disabled — falling back to passthrough", path)`

**AC-2（FR-S3 可用性属性）**
**Given** `FirejailBackend` 实例
**When** 访问 `.available` 属性
**Then** firejail 可用时返回 `True`，不可用时返回 `False`

**AC-3（FR-S3 run() 降级）**
**Given** `self._firejail_available == False`
**When** 调用 `FirejailBackend.run("echo hi", timeout=10)`
**Then** 内部调用 `PassthroughRunner().run("echo hi", timeout=10)`——不尝试启动 firejail、不抛异常
**And** `echo hi` 正常执行、返回 `exit_code=0`

**AC-4（NFR-S3 可用时正常路径）**
**Given** `shutil.which` 返回非空（firejail 可用）
**When** 构造实例 + 调用 `run()`
**Then** `self._firejail_available == True`，`run()` 走正常 firejail 路径

**AC-5（NFR-S3 端到端降级不中断）**
**Given** `SANDBOX_BACKEND=firejail` 但 firejail 不可用
**When** 一次完整 agent run 中调 shell
**Then** shell 正常完成（Passthrough），不炸 agent 循环

## Tasks

- [ ] **Task 1: 构造期检测 + 属性** (AC-1, AC-2)
  - [ ] `__init__` 开头 `import shutil` → `firejail_path = shutil.which(self._firejail_path)`
  - [ ] 不可用时：`logger.warning(...)` + `self._firejail_available = False` + `self._resolved_path = None`
  - [ ] 可用时：`self._firejail_available = True` + `self._resolved_path = firejail_path`
  - [ ] `@property available -> bool` 返回 `self._firejail_available`

- [ ] **Task 2: run() 降级路径** (AC-3, AC-4)
  - [ ] `run()` 开头：
    ```python
    if not self._firejail_available:
        return await PassthroughRunner().run(command, timeout=timeout)
    ```
  - [ ] 可用时：`argv[0] = self._resolved_path`（用 `shutil.which` 解析过的全路径）

- [ ] **Task 3: 测试** (AC-1~5)
  - [ ] `test_available_true_when_found`：mock `shutil.which` → 非 None → `.available is True`
  - [ ] `test_available_false_when_not_found`：mock → None → `.available is False` + warning 日志
  - [ ] `test_run_falls_back_when_unavailable`：`.available=False` → `run()` 走 Passthrough、`echo hi` 成功
  - [ ] `test_run_uses_resolved_path_when_available`：mock `shutil.which` → 全路径 → argv[0] 为该路径
  - [ ] `test_unavailable_no_warning_on_run`：降级路径不在此重复 warn（构造期已 warn）
