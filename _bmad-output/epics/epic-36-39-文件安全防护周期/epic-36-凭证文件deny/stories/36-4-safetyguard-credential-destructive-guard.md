---
cycle: file-safety-hardening
epic: 36
story: 36-4
status: done
---

# Story 36-4: SafetyGuard 凭证路径破坏性命令拦截

## Story

As a HeAgent 操作者,
I want SafetyGuard 拦截对凭证文件路径的移动/删除/覆盖命令,
So that shell 路径下的 `rm` / `mv` / 重定向不能删改凭证文件（`file_write` 的 deny 覆盖不到 shell）。

> 本 story 是 FR-F1（凭证写 deny）的 shell 层延伸：`path_safety.check_write_denied` 只拦
> `file_write` 工具，移动/删除走 shell（`mv` / `rm`），此前靠 `SafetyGuard` 的 `rm -rf` 模式
> 覆盖不完整（裸 `rm` 指定凭证文件、`mv` 均漏网）。本 story 补齐这一面。

## Acceptance Criteria

**AC-1（凭证破坏性命令拦截）**
**Given** `SafetyGuard` 新增 `_CREDENTIAL_DESTRUCTIVE_PATTERNS`
**When** shell 命令包含 `rm` / `mv` / `rmdir` / `unlink` + 凭证路径（`~/.ssh`、`.env`、`.aws` 等）
**Then** 抛 `SafetyViolation`

**AC-2（重定向覆盖拦截）**
**When** shell 命令用 `>` 覆盖凭证路径（如 `echo evil > ~/.ssh/authorized_keys`）
**Then** 抛 `SafetyViolation`

**AC-3（非凭证不误伤）**
**When** shell 命令删除/移动非凭证文件（`rm report.txt`、`mv report.txt /tmp`、`cp`、普通 `>`）
**Then** 不抛 `SafetyViolation`

## Tasks

- [x] **Task 1: safety.py 新增凭证破坏性模式 + check() 接入** (AC-1, AC-2)
  - [x] `_CREDENTIAL_PATH_ALT` 凭证路径片段（ssh 私钥/authorized_keys/.env/.aws/.gnupg/.kube/.netrc/.npmrc/.pypirc/.git-credentials/sudoers/passwd/shadow）
  - [x] `_CREDENTIAL_DESTRUCTIVE_PATTERNS`：`\b(?:rm|mv|rmdir|unlink)\b[^\n]*?(?:frag)` + `>[^>\n]*?(?:frag)`
  - [x] `check()` 第一层后接入（第一层半）

- [x] **Task 2: 测试** (AC-1~3)
  - [x] `test_blocks_credential_destructive`（9 个用例）
  - [x] `test_blocks_redirect_overwrite_credential`
  - [x] `test_allows_non_credential`（5 个用例，含 cp / 普通重定向不误伤）
