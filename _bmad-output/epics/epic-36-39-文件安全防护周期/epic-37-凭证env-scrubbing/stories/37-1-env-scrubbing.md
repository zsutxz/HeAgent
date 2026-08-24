---
cycle: file-safety-hardening
epic: 37
story: 37-1
status: backlog
---

# Story 37-1: scrub_sensitive_env 纯函数 + shell spawn 接入

## Story

As a HeAgent 操作者,
I want shell 子进程 spawn 前剥离敏感环境变量,
So that `shell("env")` 输出不含 API key。

## Acceptance Criteria

**AC-1（FR-F3 scrub 纯函数）**
**Given** `scrub_sensitive_env(env=None)` 纯函数
**When** 传入含 `DEEPSEEK_API_KEY` / `OPENAI_API_KEY` / `GH_TOKEN` / `DB_PASSWORD` 的 dict
**Then** 返回 dict 中这些敏感键被剥离
**And** `PATH` / `HOME` / `LANG` 等非敏感键保留

**AC-2（FR-F3 大小写不敏感）**
**Given** 键名 `deepseek_api_key`（小写）或 `DEEPSEEK_API_KEY`（大写）
**When** scrub
**Then** 都被剥离

**AC-3（FR-F3 spawn 接入）**
**Given** `_run_subprocess_shell` / `_run_subprocess_exec`
**When** 创建子进程
**Then** 传 `env=scrub_sensitive_env()`

**AC-4（FR-F3 默认 os.environ）**
**Given** `scrub_sensitive_env()` 无参数
**When** 调用
**Then** 从 `os.environ` 取源并剥离敏感键

## Tasks

- [ ] **Task 1: scrub_sensitive_env 纯函数** (AC-1, AC-2, AC-4)
  - [ ] `_SENSITIVE_ENV_SUFFIXES = ("_API_KEY", "_API_KEYS", "_TOKEN", "_SECRET", "_PASSWORD", "_CREDENTIALS", "_PRIVATE_KEY")`
  - [ ] 键 `.upper().endswith(suffix)` 匹配，大小写不敏感
  - [ ] 默认 `os.environ`
- [ ] **Task 2: _run_subprocess_shell / _run_subprocess_exec 传 env** (AC-3)
  - [ ] kwargs 增加 `"env": scrub_sensitive_env()`
- [ ] **Task 3: 测试** (AC-1~4)
  - [ ] `test_scrub_strips_sensitive_keys`
  - [ ] `test_scrub_keeps_nonsensitive_keys`
  - [ ] `test_scrub_case_insensitive`
  - [ ] `test_run_subprocess_shell_passes_scrubbed_env`（mock create_subprocess_shell）
  - [ ] `test_run_subprocess_exec_passes_scrubbed_env`
