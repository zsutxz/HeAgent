---
cycle: sandbox-hardening
epic: S3
story: S3-2
status: backlog
depends_on: S1-1
---

# Story S3-2: FirejailBackend 自动映射 workspace_root 为 --private

## Story

As a HeAgent 操作者,
I want `FirejailBackend` 自动把 workspace_root 映射为 firejail 的 `--private` 隔离,
So that 子进程只能看到 workspace 目录。

> 依赖 S1-1（`_build_argv` 纯函数已存在，本 story 扩展它）。本 story 独立于 S1-2/S2/S3-1，
> 可并行开发。

## Acceptance Criteria

**AC-1（FR-S6 FirejailBackend 构造参数）**
**Given** `FirejailBackend.__init__` 新增可选参数 `workspace_root: str | None = None`
**When** 构造 `FirejailBackend(workspace_root="/home/user/project")`
**Then** `self._workspace_root = "/home/user/project"`
**And** 不传时 `self._workspace_root = None`

**AC-2（FR-S6 _build_argv 插入 --private）**
**Given** `self._workspace_root = "/home/user/project"`（非空）
**When** `_build_argv("ls", profile=None)`
**Then** 返回的 argv 为 `["firejail", *extra_args, "--private=/home/user/project", "--", "sh", "-c", "ls"]`
**And** `--private` 在 `extra_args` 之后、`profile_args` 之前（如有 profile）

**AC-3（FR-S6 workspace_root=None 不生成 --private）**
**Given** `self._workspace_root = None`
**When** `_build_argv("ls", profile=None)`
**Then** argv 不含 `--private` 参数

**AC-4（FR-S6 EngineContainer.default() 自动传入）**
**Given** `EngineContainer.default(workspace_root=os.getcwd())`
**When** `sandbox_backend="firejail"`
**Then** 构造的 `FirejailBackend` 的 `workspace_root` 为当前工作目录

## Tasks

- [ ] **Task 1: FirejailBackend 新增 workspace_root 参数** (AC-1)
  - [ ] `__init__` 签名新增 `workspace_root: str | None = None`
  - [ ] `self._workspace_root = workspace_root`
  - [ ] 默认 `None`——向后兼容，不改 `FirejailBackend()` 无参构造

- [ ] **Task 2: _build_argv 扩展 --private** (AC-2, AC-3)
  - [ ] 在 `_build_argv` 中，`extra_args` 之后、`profile_args` 之前插入：
    ```python
    if self._workspace_root:
        argv.append(f"--private={self._workspace_root}")
    ```
  - [ ] 纯函数性保持——`self._workspace_root` 是构造期冻结的不可变值

- [ ] **Task 3: EngineContainer.default() 传 workspace_root** (AC-4)
  - [ ] 构造 `FirejailBackend` 时传 `workspace_root=workspace_root`（该参数已存在）
  - [ ] 若 `workspace_root` 为空字符串 → 不传（等同 `None`）

- [ ] **Task 4: 测试** (AC-1~4)
  - [ ] `test_workspace_root_default_none`：`FirejailBackend()` → `_workspace_root is None`
  - [ ] `test_build_argv_with_workspace_root`：workspace_root 非空 → argv 含 `--private=<path>`
  - [ ] `test_build_argv_without_workspace_root`：workspace_root=None → argv 不含 `--private`
  - [ ] `test_build_argv_workspace_and_profile_ordering`：两者非空 → `--private` 在 profile_args 前
  - [ ] `test_container_default_passes_workspace_root`：`EngineContainer.default(workspace_root="...")` → `FirejailBackend._workspace_root == "..."`
