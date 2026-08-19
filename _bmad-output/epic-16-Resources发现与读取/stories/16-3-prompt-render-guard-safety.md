---
baseline_commit: 4d4cd61f043fdb333f14e7b1e9e5e43d88dd21b0
---

# Story 16.3: 渲染输出同等不可信围栏 + 安全声明更新

Status: ready-for-dev

## Story

As a HeAgent 操作者,
I want /mcp-prompt 渲染输出经注入围栏标记后再注入,
So that server 渲染的模板文本与工具返回同等不可信，且安全声明披露 Prompts 这条腿。

> **本 story 是 Epic C 的收尾**——复用 15-3 提取的公共 `guard_content` 对 Prompts 渲染输出加围栏，更新安全声明文档覆盖 Prompts 返回同等不可信立场。

## Acceptance Criteria

**AC-1（FR-C4：guard_content 围栏）**
**Given** get_prompt 渲染出的文本
**When** slash 分发器注入前
**Then** 先经公共 `guard_content` 标记，命中注入启发式加 warning 后再作 user message 注入（FR-C4, AD-6/7）

**AC-2（SM-6：安全声明更新）**
**Given** CLAUDE.md MCP 特定风险章节
**When** 审查 Prompts 部分
**Then** 覆盖：Prompts 渲染输出同等不可信 + 语义重叠披露（Prompts 与 context-files/自学习记忆在「注入预设上下文」重叠，本周期不统一三者）

**AC-3（SM-6：docs 同步）**
**Given** `docs/frame.md` 已知缺口/安全声明
**When** 审查
**Then** 同步 Prompts 同等不可信立场

**AC-4（零回归：既有测试全绿）**
**Given** 既有 19 内置工具 + V1 MCP + Epic 14/15 测试套件
**When** 运行全量测试
**Then** 全绿

## Tasks / Subtasks

- [ ] **Task 1: slash 分发器注入前 guard_content**
  - [ ] 在 `/mcp-prompt` 渲染文本作为 user message 注入前调 `guard_content(rendered_text)`
  - [ ] 与 FR-B4 同构——标记透传不阻断

- [ ] **Task 2: CLAUDE.md 安全声明更新**
  - [ ] MCP 特定风险章节加 Prompts 覆盖
  - [ ] 语义重叠披露

- [ ] **Task 3: docs/frame.md 同步**
  - [ ] 已知缺口/安全声明章节同步

- [ ] **Task 4: 回归测试**
  - [ ] 全量测试通过

## Dev Notes

- `guard_content` 已在 15-3 提取为公共函数（`mapping.py`），本 story 仅调用不重实现。
- 语义重叠披露是本 story 的特色：Prompts（注入预设指令）与已有 context-files/自学习记忆功能重叠，文档说明不统一三者。

## File List

- `src/heagent/cli.py` — slash 分发器内 `guard_content` 调用（与 16-2 同一处修改）
- `CLAUDE.md` — 安全声明更新
- `docs/frame.md` — 安全声明同步

## Change Log

- 2026-07-23：Story 16-3 创建。
