---
baseline_commit: 4d4cd61f043fdb333f14e7b1e9e5e43d88dd21b0
---

# Story 14.4: 安全声明更新（写操作治理）

Status: done

## Story

As a HeAgent 操作者,
I want CLAUDE.md / docs/frame.md 的安全声明覆盖写操作治理的诚实立场,
So that 不制造「接了 annotations 治理就更安全」的假象——annotation 不可信，须 OS 级沙箱兜底。

> **本 story 是 Epic A（写操作治理）的收尾**——接 Story 14-1/14-2/14-3 的实现，更新安全管理文档（AD-8, SM-6）。本 story 完成后 Epic 14 全部 4 个 story 齐备，可进入 review 并标记 epic-14=done。

## Acceptance Criteria

**AC-1（AD-8, SM-6：CLAUDE.md 安全声明覆盖写操作治理）**
**Given** CLAUDE.md 安全声明章节
**When** 审查写操作治理部分
**Then** 明确陈述：
  - `Tool.annotations` 是 server 自声明、不可信（恶意 server 可把 `delete_repository` 谎报为 `readOnlyHint=true`）
  - 治理闸门（destructive→审批 / readOnly→放行 / 缺省→fail-safe）仅 defense-in-depth 标记，非真正安全边界
  - 须 OS 级沙箱兜底（容器/firejail），不可裸跑
**And** 更新「后续（deferred / future）」段落，反映写操作治理的 V2 交付状态

**AC-2（docs/frame.md 已知缺口同步）**
**Given** `docs/frame.md` 第五章「已知缺口」
**When** 审查
**Then** 新增或更新条目说明：写操作治理的 annotations 是 server 自声明、不可信、非安全边界，与既有 MCP 工具返回同等不可信立场一致

## Tasks / Subtasks

- [x] **Task 1: CLAUDE.md 安全声明更新** (AC: #1)
  - [x] MCP 特定风险小节新增明确的 annotation 不可信陈述
  - [x] 更新「后续（deferred / future）」段落反映 V2 写操作治理已交付
  - [x] 不改变既有安全声明立场

- [x] **Task 2: docs/frame.md 已知缺口同步** (AC: #2)
  - [x] 第五章已知缺口表新增写操作治理 annotations 条目
  - [x] 措辞与 CLAUDE.md 一致

- [x] **Task 3: 交叉验证两项文档一致** (AC: #1, #2)
  - [x] 两文档关于 annotation 不可信的表述一致（不互相矛盾）
  - [x] 不篡改既有安全边界立场（继续声明非真正安全边界）

## Dev Notes

- 本 story 不修改代码——仅更新安全管理文档。
- 安全声明诚实立场在 CLAUDE.md 开篇已有成熟模板，新增 annotation-specific 内容应嵌入既有 MCP 特定风险小节，不新开章节。
- docs/frame.md 的已知缺口表是表格格式，应保持同表格风格。

## File List

- `CLAUDE.md` — 安全声明章节更新
- `docs/frame.md` — 第五章已知缺口更新

## Change Log

- 2026-07-17：Story 14-4 创建，开始实施。
- 2026-07-17：Story 14-4 实现完成——CLAUDE.md 新增 annotation 不可信陈述 + 更新 deferred 段落；docs/frame.md 已知缺口表新增 MCP 写操作治理 annotations 条目。Status → done。
