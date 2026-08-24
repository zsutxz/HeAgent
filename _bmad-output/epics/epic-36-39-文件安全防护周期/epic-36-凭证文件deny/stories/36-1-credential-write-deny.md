---
cycle: file-safety-hardening
epic: 36
story: 36-1
status: backlog
---

# Story 36-1: path_safety 凭证写 deny 规则表 + check 函数

## Story

As a HeAgent 开发者,
I want `path_safety.py` 新增凭证写 deny 规则表与 `check_write_denied`,
So that file_write 能拦截对凭证文件的写入。

> 本 story 是 Epic 36 的数据层——只建写 deny 规则表 + `check_write_denied` 纯函数，
> **不触碰 handler / policy 接入**（那是 36-2 / 36-3 的范围）。

## Acceptance Criteria

**AC-1（FR-F1 写 deny 精确匹配）**
**Given** `build_write_denied_paths()` 纯函数
**When** 调用
**Then** 返回 `realpath` 集合，含 `~/.ssh/authorized_keys`、`~/.ssh/id_rsa`、`~/.ssh/id_ed25519`、
`~/.env`、`~/.netrc`、`~/.npmrc`、`~/.pypirc`、`~/.git-credentials`、`/etc/sudoers`、
`/etc/passwd`、`/etc/shadow`
**And** 纯函数——无 I/O、无 contextvar、无外部可变状态

**AC-2（FR-F1 写 deny 目录前缀）**
**Given** `build_write_denied_prefixes()` 纯函数
**When** 调用
**Then** 返回前缀列表，含 `~/.ssh/`、`~/.aws/`、`~/.gnupg/`、`~/.kube/`、`/etc/sudoers.d/`、
`~/.docker/`、`~/.azure/`、`~/.config/gh/`、`~/.config/gcloud/`

**AC-3（FR-F1 check_write_denied）**
**Given** `check_write_denied(path)` 纯函数
**When** path 命中精确匹配（如 `~/.ssh/id_rsa`）或目录前缀（如 `~/.aws/credentials`）
**Then** 返回非 None 的 deny 原因
**And** 未命中（如 `~/project/notes.txt`）返回 None

## Tasks

- [ ] **Task 1: build_write_denied_paths 纯函数** (AC-1)
  - [ ] 用 `Path.home()` 解析 `~` 前缀，`realpath` 精确匹配
  - [ ] 覆盖凭证文件：ssh 私钥/authorized_keys、.env、.netrc、.npmrc、.pypirc、
        .git-credentials、/etc/sudoers、/etc/passwd、/etc/shadow

- [ ] **Task 2: build_write_denied_prefixes 纯函数** (AC-2)
  - [ ] 目录前缀列表：.ssh/.aws/.gnupg/.kube/.docker/.azure/.config/gh/.config/gcloud、
        /etc/sudoers.d

- [ ] **Task 3: check_write_denied 纯函数** (AC-3)
  - [ ] `Path(path).expanduser().resolve()` → 精确匹配 + 前缀匹配
  - [ ] 命中返回 deny 原因（含用户可读提示），未命中返回 None

- [ ] **Task 4: 测试** (AC-1~3)
  - [ ] `test_build_write_denied_paths_contains_ssh_keys`
  - [ ] `test_build_write_denied_prefixes_contains_dirs`
  - [ ] `test_check_write_denied_exact_match`
  - [ ] `test_check_write_denied_prefix_match`
  - [ ] `test_check_write_denied_not_denied`
