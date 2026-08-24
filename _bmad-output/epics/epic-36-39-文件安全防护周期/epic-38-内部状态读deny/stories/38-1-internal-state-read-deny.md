---
cycle: file-safety-hardening
epic: 38
story: 38-1
status: backlog
---

# Story 38-1: 内部状态读 deny + file/search handler 接入

## Story

As a HeAgent 操作者,
I want `file_read` / `file_search` 拦截 `.heagent/` 内部状态读取,
So that 内部状态文件不进入 LLM 上下文。

## Acceptance Criteria

**AC-1（FR-F4 内部状态目录）**
**Given** `build_internal_state_dirs()` 纯函数
**When** 调用
**Then** 返回集合，含 `~/.heagent/sessions`、`~/.heagent/ledger`、`~/.heagent/memory`、
`~/.heagent/skills`

**AC-2（FR-F4 check_read_denied 扩展）**
**Given** `check_read_denied(path)`
**When** path 命中内部状态目录（精确或子路径，如 `.heagent/sessions/xxx.json`）
**Then** 返回 deny 原因；未命中返回 None

**AC-3（FR-F4 handler 接入）**
**Given** `file_read` / `file_search` handler 在围栏后调用 `check_read_denied`
**When** 读 `.heagent/sessions/xxx.json`
**Then** 返回错误提示（不读内容）

## Tasks

- [ ] **Task 1: build_internal_state_dirs 纯函数** (AC-1)
- [ ] **Task 2: check_read_denied 扩展内部状态** (AC-2)
  - [ ] 精确匹配 + `startswith(d + os.sep)` 子路径匹配
- [ ] **Task 3: file_read / file_search handler 接入** (AC-3)
  - [ ] file.py 的 `file_read` 已在 36-2 接 `check_read_denied`，本 story 仅需确认扩展生效
  - [ ] search.py 的 handler 在 `resolve_workspace_path` 后接 `check_read_denied`
- [ ] **Task 4: 测试** (AC-1~3)
  - [ ] `test_build_internal_state_dirs`
  - [ ] `test_check_read_denied_internal_state_exact`
  - [ ] `test_check_read_denied_internal_state_subpath`
  - [ ] `test_file_read_denies_internal_state`
  - [ ] `test_search_denies_internal_state`
