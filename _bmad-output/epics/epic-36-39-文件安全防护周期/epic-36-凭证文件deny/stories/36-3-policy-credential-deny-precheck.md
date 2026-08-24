---
cycle: file-safety-hardening
epic: 36
story: 36-3
status: backlog
---

# Story 36-3: PolicyEngine._validate_paths 挂接凭证 deny 预检

## Story

As a HeAgent 开发者,
I want `_validate_paths` 在围栏预检后挂接凭证 deny 预检,
So that deny 在 policy 层也被预检拦截（与 handler 守卫形成两层纵深防御）。

## Acceptance Criteria

**AC-1（FR-F1/F2 policy 预检）**
**Given** `_validate_paths` 对 file_read / file_write 增加 deny 预检
**When** 目标路径命中凭证 deny（file_read 读 `.env` / file_write 写 `~/.ssh/id_rsa`）
**Then** 返回非空 deny reason → 调用方判 BLOCKED

**AC-2（围栏与 deny 独立）**
**Given** 围栏预检与 deny 预检是独立两步
**When** 路径在 workspace 内但命中 deny
**Then** 仍 BLOCKED（deny 不依赖围栏越界）

## Tasks

- [ ] **Task 1: _validate_paths 增加 deny 预检** (AC-1)
  - [ ] file_read → 围栏后调 `check_read_denied`
  - [ ] file_write → 围栏后调 `check_write_denied`
  - [ ] 命中返回 deny reason（越界与 deny 的 reason 可区分）
- [ ] **Task 2: 测试** (AC-1, AC-2)
  - [ ] `test_policy_blocks_env_read`（workspace 内 .env → BLOCKED）
  - [ ] `test_policy_blocks_ssh_write`
  - [ ] `test_policy_deny_independent_of_fence`
