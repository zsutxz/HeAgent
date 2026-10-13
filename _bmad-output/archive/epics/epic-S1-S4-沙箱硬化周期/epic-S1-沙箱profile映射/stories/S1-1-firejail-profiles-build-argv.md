---
cycle: sandbox-hardening
epic: S1
story: S1-1
status: backlog
---

# Story S1-1: FirejailBackend 支持 profiles dict + _build_argv 纯函数

## Story

As a HeAgent 开发者,
I want `FirejailBackend` 接受 `profiles` dict 并按 profile 名映射 firejail 参数,
So that 不同 profile 能产生不同的 firejail 隔离效果。

> 本 story 是 Epic S1 的数据层——只建 `profiles` 构造参数 + `_build_argv` 纯函数，
> **不触碰 executor 注入**（那是 S1-2 的范围）。本 story 完成后，`FirejailBackend`
> 已能按 profile 映射参数但 `get_sandbox_profile()` 返回 `None`（无 executor 注入）——
> 这是预期的，S1-2 才接上管道。

## Acceptance Criteria

**AC-1（FR-S1 profiles dict 构造）**
**Given** `FirejailBackend.__init__` 新增可选参数 `profiles: Mapping[str, Sequence[str]]`（默认空）
**When** 构造 `FirejailBackend(profiles={"default": ("--private-tmp",), "network-isolated": ("--net=none",)})`
**Then** `self._profiles` 为 `{"default": ("--private-tmp",), "network-isolated": ("--net=none",)}`
**And** 不传 `profiles` 时 `self._profiles` 为 `{}`

**AC-2（FR-S1 _build_argv 纯函数）**
**Given** `FirejailBackend._build_argv(command, profile, workspace_root=None)` 为纯函数
**When** `profile="network-isolated"` 且该 profile 在 profiles dict 中
**Then** 返回 argv 列表 `["firejail", *extra_args, "--net=none", "--", "sh", "-c", command]`
**And** 函数为纯函数——无 I/O、无 contextvar、无 `self` 以外的外部状态

**AC-3（FR-S1 profile 不存在不抛错）**
**Given** profile 名不在 `profiles` dict 中（或 `profiles` 为空）
**When** 调用 `_build_argv`
**Then** 仅用 `extra_args`（不含 profile 专用参数），不抛错

**AC-4（FR-S1 run() 调用 _build_argv 并传入 _run_subprocess_exec）**
**Given** `FirejailBackend.run(command, *, timeout)` 调用
**When** `get_sandbox_profile()` 返回 `"network-isolated"`（由 S1-2 注入，本 story mock 此调用）
**Then** `run()` 内部调 `_build_argv` → 传给 `_run_subprocess_exec`

## Tasks

- [ ] **Task 1: FirejailBackend 新增 profiles 构造参数** (AC-1)
  - [ ] `__init__` 签名新增 `profiles: Mapping[str, Sequence[str]] = {}`
  - [ ] `self._profiles = dict(profiles)`（浅拷贝，存入 tuple）
  - [ ] 默认值 `{}`——向后兼容，不改 `FirejailBackend()` 无参构造

- [ ] **Task 2: 实现 _build_argv 纯函数** (AC-2, AC-3)
  - [ ] 提取 `_build_argv(self, command: str, profile: str | None, workspace_root: str | None = None) -> list[str]`
  - [ ] argv 拼接顺序：`[firejail_path, *extra_args, *profile_args, "--", "sh", "-c", command]`
  - [ ] profile 为 None 或不在 `_profiles` 中 → 不插入 profile_args
  - [ ] 纯函数——仅依赖参数与 `self._firejail_path` / `self._extra_args` / `self._profiles`

- [ ] **Task 3: FirejailBackend.run 接入 _build_argv** (AC-4)
  - [ ] `run()` 中：`profile = get_sandbox_profile()` → `argv = self._build_argv(command, profile)` → `_run_subprocess_exec(argv, timeout)`
  - [ ] 现有 `_run_subprocess_exec` 调用替换为新路径
  - [ ] `get_sandbox_profile()` 在 S1-2 前返回 `None`（无 executor 注入），此时行为与现有 `extra_args` 一致（零回归）

- [ ] **Task 4: 测试** (AC-1~4)
  - [ ] `test_profiles_empty_by_default`：`FirejailBackend()` → `_profiles == {}`
  - [ ] `test_build_argv_no_profile`：profile=None → argv 不含 profile_args
  - [ ] `test_build_argv_with_profile`：profile 在 dict 中 → argv 含对应参数
  - [ ] `test_build_argv_unknown_profile`：profile 不在 dict 中 → 仅 extra_args，不抛错
  - [ ] `test_build_argv_pure_function`：相同输入 → 相同输出（无副作用）
  - [ ] `test_run_uses_build_argv`：mock `get_sandbox_profile` + `_run_subprocess_exec` → 验证传给 exec 的 argv
