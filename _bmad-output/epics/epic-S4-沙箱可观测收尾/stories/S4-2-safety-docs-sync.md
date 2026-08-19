---
cycle: sandbox-hardening
epic: S4
story: S4-2
status: backlog
depends_on: S1-1, S1-2, S2-1, S2-2, S3-1, S3-2, S4-1
---

# Story S4-2: 安全声明 + 文档同步

## Story

As a HeAgent 维护者,
I want CLAUDE.md / docs/frame.md / docs/iteration.md 同步更新,
So that 本轮硬化不会让人误以为 Firejail 变成了安全边界。

> 依赖全部 S1~S4 的代码改动——文档以最终代码事实为准。最后做。

## Acceptance Criteria

**AC-1（NFR-S2 CLAUDE.md 更新）**
**Given** `CLAUDE.md` 安全声明章节
**When** 审查 sandbox 部分
**Then** 新增或更新段：

> **Sandbox 硬化（2026-07-20）：** `FirejailBackend` 新增 profile → 参数映射、
> `.env`/CLI 配置入口（`SANDBOX_BACKEND` / `--sandbox`）、firejail 不可用时
> 优雅降级（warn + Passthrough）、Linux 进程组 killing（`os.killpg`）、
> workspace_root → `--private` OS 级文件系统隔离。
> Firejail 仍非完美边界（仅隔离 shell 子进程、Linux-only、可被绕过），
> 上述强化均为 defense-in-depth——须 OS 级沙箱兜底。
> `sandbox_profile` 不改变此底线立场。

**AC-2（NFR-S2 docs/frame.md 更新）**
**Given** `docs/frame.md` 4.4 sandbox.py 节 + 第五章已知缺口
**When** 审查更新
**Then** 4.4 节新增：
- `FirejailBackend` profiles dict + `_build_argv` 纯函数
- profile contextvar 注入（`bind_sandbox_profile`）
- firejail 可用性检测 + 降级
- Linux 进程组 killing（`start_new_session` + `os.killpg`）
- `--sandbox` CLI flag + `SANDBOX_BACKEND` .env

**And** 第五章已知缺口更新：
- 移除「`sandbox_profile` 死字段」——已激活
- 移除「无 CLI/`Settings` 配置入口」——已新增
- 新增「Firejail 仍非完美边界，仅隔离 shell 子进程」

**AC-3（docs/iteration.md 更新）**
**Given** `docs/iteration.md` 时间线
**When** 审查
**Then** 2026-07-20 里程碑新增 sandbox-hardening 周期记录

## Tasks

- [ ] **Task 1: CLAUDE.md 更新** (AC-1)
  - [ ] 在「⚠ 安全声明」章节的 sandbox 段后追加新文本
  - [ ] 不删改既有安全声明、仅追加本轮增量
  - [ ] 措辞与 `ARCHITECTURE-SPINE.md` 安全声明段一致

- [ ] **Task 2: docs/frame.md 更新** (AC-2)
  - [ ] 4.4 sandbox.py 节更新：在现有 `FirejailBackend` 描述后追加新能力
  - [ ] 第五章已知缺口：移除已修复条目 + 新增「仍非完美边界」声明
  - [ ] 确保措辞与代码一致（profile 名→参数映射 / 降级 / 进程组 kill / CLI 入口）

- [ ] **Task 3: docs/iteration.md 更新** (AC-3)
  - [ ] 时间线新增 `2026-07-20 | sandbox-hardening 周期启动（profile 映射 / 降级 / 配置入口 / 进程组 kill / workspace 隔离）`

- [ ] **Task 4: 文档审查**
  - [ ] 三文档的 sandbox 相关文本互不矛盾
  - [ ] 不制造「Firejail 变成安全边界」的假象
  - [ ] git diff 审查：无意外删除 / 无过时表述残留
