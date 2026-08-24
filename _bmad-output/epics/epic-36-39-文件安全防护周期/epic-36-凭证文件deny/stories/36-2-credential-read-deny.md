---
cycle: file-safety-hardening
epic: 36
story: 36-2
status: backlog
---

# Story 36-2: path_safety 凭证读 deny + file handler 守卫

## Story

As a HeAgent 开发者,
I want `path_safety.py` 新增读 deny 与 `check_read_denied`，并接入 file handler,
So that `file_read(".env")` 被拦截、API key 不进入上下文。

## Acceptance Criteria

**AC-1（FR-F2 读 deny basename）**
**Given** `build_read_denied_basenames()` 纯函数
**When** 调用
**Then** 返回集合，含 `.env`、`.env.local`、`.env.development`、`.env.production`、
`.env.test`、`.env.staging`、`.envrc`

**AC-2（FR-F2 check_read_denied）**
**Given** `check_read_denied(path)` 纯函数
**When** path 的 basename（小写）命中读 deny 集合
**Then** 返回 deny 原因（提示读 `.env.example`）；未命中返回 None

**AC-3（FR-F2 file_read handler 守卫）**
**Given** `file_read` handler 在 `resolve_workspace_path` 之后调用 `check_read_denied`
**When** 读 `.env`（在 workspace 内）
**Then** 返回错误提示（不抛异常、不读文件内容）

**AC-4（FR-F1 file_write handler 守卫）**
**Given** `file_write` handler 在 `resolve_workspace_path` 之后调用 `check_write_denied`
**When** 写 `~/.ssh/id_rsa`
**Then** 返回错误提示（不写文件）

## Tasks

- [ ] **Task 1: build_read_denied_basenames 纯函数** (AC-1)
- [ ] **Task 2: check_read_denied 纯函数** (AC-2)
  - [ ] basename 小写匹配读 deny 集合
- [ ] **Task 3: file_read handler 接 check_read_denied** (AC-3)
  - [ ] `resolve_workspace_path` 之后调用；命中返回 `f"Error: {reason}"`
- [ ] **Task 4: file_write handler 接 check_write_denied** (AC-4)
- [ ] **Task 5: 测试** (AC-1~4)
  - [ ] `test_build_read_denied_basenames`
  - [ ] `test_check_read_denied_env_basename`
  - [ ] `test_check_read_denied_not_denied`
  - [ ] `test_file_read_denies_env`
  - [ ] `test_file_write_denies_ssh_key`
