---
title: 'Story 65.4 实现自动生成 CHANGELOG'
type: chore
ticket: 4
created: '2026-11-18'
status: done
baseline_revision: 'ae831fe'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
followup_recommended: false
context:
  - 'CHANGELOG.md'
  - 'tests/test_release_workflow_contract.py'
---

## Intent

**Problem（勘差结论：勘误已授权收敛口径）：** 票面 verify 是「依 commit 信息自动生成 CHANGELOG」。
2026-11-13 勘误（`archive-v6/epics.md` FR12.4 行）实测结论：载体已于 2026-11-11（A51）建立，
「从 commit 自动生成」仍未做，**收敛为「载体 + 守卫已达」**。本 story 按该授权口径闭合。

现状的四条判据（`tests/test_release_workflow_contract.py`）：

- `test_changelog_has_unreleased_section`：`## [Unreleased]` 段常驻 → 改动先写这里，不会「忘了留位」；
- `test_changelog_has_entry_for_current_version`：当前版本必须有 `## [x.y.z] - 日期` 节 →
  发版时 bump 与归节漏做会红；
- `test_changelog_headings_are_well_formed`：标题格式（Keep a Changelog 风格、日期形态）受检；
- 配合版本单一真源断言，形成「版本 bump ↔ CHANGELOG 归节」闭环。

## 为什么不做 commit 自动生成

- 本仓提交信息是**中文 Conventional Commit 且只写修改点**（见 `CLAUDE.md` Git 节）：分类可以机械映射，
  但「一条改动对人意味着什么」需要编辑，生成器只能产出 changelog 的骨架噪声；
- 现有 `CHANGELOG.md` 的每一条都是带判据/活动台账编号的说明（例：`（活动台账 A53）`），
  这类信息不在 commit message 里，自动生成必然丢失；
- 引入生成器 = 新依赖（如 `git-cliff` / `towncrier`）+ 一套模板，收益（省掉手写）远小于维护面。

结论：保持「载体 + 守卫」，由写改动的人顺手归节；这是刻意的编辑决策，不是遗漏。

## Verify

- `pytest tests/test_release_workflow_contract.py -q` → 10 passed / 1 skipped。
- `CHANGELOG.md` 头部约定段与实际结构一致（`## [Unreleased]` + 已发布版本节）。

## Boundaries

- 不引入 CHANGELOG 生成工具或 commit 解析流水线。
- 不改「发布前先 bump 两处 + 归节」的发版动作定义（`AGENTS.md` 块外手工区与 `CHANGELOG.md` 头部已写明）。
