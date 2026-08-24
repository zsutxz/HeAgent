---
cycle: file-safety-hardening
epic: 39
story: 39-1
status: backlog
---

# Story 39-1: 安全声明 + 文档同步

## Story

As a HeAgent 维护者,
I want CLAUDE.md / AGENTS.md / frame.md / iteration.md 同步更新,
So that 本轮防护不会让人误以为 deny/scrub 变成了安全边界。

## Acceptance Criteria

**AC-1（CLAUDE.md / AGENTS.md）**
**Given** 安全声明章节
**When** 审查
**Then** 新增「文件安全与凭证防护（2026-08-24）」段：覆盖凭证 deny / env scrub / 内部状态读
deny；明确声明均为 defense-in-depth、非真正边界（shell 可 `cat .env` 绕过）

**AC-2（docs/frame.md）**
**Given** path_safety 章节 + 第五章已知缺口
**When** 审查
**Then** 新增凭证 deny 描述；已知缺口更新

**AC-3（docs/iteration.md）**
**Given** 时间线 + 周期记录
**When** 审查
**Then** 新增 file-safety-hardening 周期记录

## Tasks

- [ ] **Task 1: CLAUDE.md / AGENTS.md 安全声明更新** (AC-1)
- [ ] **Task 2: docs/frame.md 更新** (AC-2)
- [ ] **Task 3: docs/iteration.md 更新** (AC-3)
