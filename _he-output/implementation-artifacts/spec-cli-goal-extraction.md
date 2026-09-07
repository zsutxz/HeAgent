---
title: '/goal 命令族拆分为 cli_goal 模块'
type: 'refactor'
created: '2026-09-07'
status: 'done'
review_loop_iteration: 0
baseline_commit: 'c6cf78167096ad26adc07db1250463d5b73f0ec5'
context: ['E:/AI/HeAgent/src/heagent/cli.py', 'E:/AI/HeAgent/tests/test_goal_declarative_workflow.py', 'E:/AI/HeAgent/src/heagent/gui/screens/chat.py']
---

<frozen-after-approval reason="human-owned intent - do not modify unless human renegotiates">

## Intent

**Problem:** `/goal` 命令族（约 1035 行）内联在 cli.py（2401 行）中，占 43%，阻碍 CLI 入口的可读性与后续 goal 演进。

**Approach:** 纯搬移到新顶层模块 `cli_goal.py`（对标 51a4c56 的 cli_display.py 拆分先例）：代码逐字节不变，cli.py 保留最小 re-export，测试 monkeypatch 缝随迁并同步 patch 路径。

## Boundaries & Constraints

**Always:** 搬移内容逐字节不变（`git diff --color-moved` 验证）；monkeypatch 缝（`_goal_session`/`_goal_declarative_advance`/`_goal_auto_lock`）随代码迁至 cli_goal 且测试同步指向新路径；cli.py 保留 `_goal_runner`/`_goal_auto_goal_id`/`_goal_cron_advance` 三个自用符号（GUI 与旧调用路径继续可用）。

**Ask First:** 若搬移中发现未预料的耦合（计划外的反向依赖），停下来重新评估而非就地改写。

**Never:** 不混入任何行为修复或清理（死参数、文案、正则锚定等全部归审核后续提交）；不迁移不重命名既有测试文件；不在 cli.py 做全量 re-export（故意让旧 monkeypatch 路径 `AttributeError` 响亮失败，而非静默不生效）。

</frozen-after-approval>

## Code Map

- `src/heagent/cli.py:80-82,876-1911` -- 搬移来源：goal 常量 + 命令族全部代码。
- `src/heagent/cli_goal.py` -- 新模块（新建）。
- `tests/test_goal_declarative_workflow.py:11-17,70,135-141,372` -- import 块与 monkeypatch 路径改为 `heagent.cli_goal`。
- `src/heagent/gui/screens/chat.py:203` -- 惰性 import 改指 cli_goal。

## Tasks & Acceptance

**Execution:**
- [x] `src/heagent/cli_goal.py` -- 承载 goal 命令族（声明式分发、问卷门控、cron 自动推进）。
- [x] `src/heagent/cli.py` -- 删除 goal 区间与随之未用的 import，新增 3 符号 import；cron tick 与 slash 注册闭包函数体零改动。
- [x] `tests/test_goal_declarative_workflow.py` -- patch 路径随迁 + 新增边界测试（re-export 契约）。
- [x] `docs/frame.md` §4.13 / `CLAUDE.md` -- 模块清单同步。

**Acceptance Criteria:**
- Given 搬移提交，when `git diff --color-moved=plain`，then 仅见代码移动，无 token 级改动。
- Given `heagent.cli` 导入，when 断言 `_goal_runner is cli_goal._goal_runner`，then 成立；`hasattr(cli, "_goal_session")` 为 False。
- Given 全量 goal 测试集，when pytest，then 全绿。

## Design Notes

命名取 `cli_goal.py` 而非 `goal.py`：frame.md 4.13 承诺「不会创建独立的 goal.py 状态模型」，前缀式命名既避免文字冲突，也标注 CLI 层归属（领域逻辑在 `engine/workflow*.py`，本模块只是命令族编排）。最小 re-export 是有意取舍：51a4c56 的全量别名模式适用于无人 patch 的展示 helper；goal 的私有符号是测试 monkeypatch 目标，别名会造成「patch 成功却静默不生效」。

## Verification

**Commands:**
- `pytest tests/test_goal_declarative_workflow.py tests/test_cli.py tests/test_slash.py tests/test_goal_workflow_smoke.py tests/test_goal_epic_story_smoke.py -q` -- expected: all pass。
- `ruff check src tests` / `mypy src` -- expected: no violations。
- `git diff HEAD~1 --color-moved=plain src/heagent/` -- expected: 只见移动。

**Purity evidence（搬移完成时点）:** 与基线 c6cf781 的 80-82 + 876-1911 行逐字节比对，仅 1 个 ruff format 合行 hunk 差异；`/goal status` CLI smoke 与基线输出逐字一致。同会话审核后按用户 triage 在同一工作树追加了行为修复（A1 waiting 结局 / A2 单题校验 / B1 错误包络 / C1-C3 文本清理，各配回归测试），搬移与修复未拆分提交时以本记录为纯度证据。

## Suggested Review Order

**Purity**

- Move-only diff, no token drift.
  [`git diff HEAD~1 --color-moved=plain`](../../src/heagent/cli_goal.py)

**Seam migration**

- Monkeypatch targets follow the code.
  [`test_goal_declarative_workflow.py:70`](../../tests/test_goal_declarative_workflow.py#L70)

**Contract**

- Minimal re-export keeps GUI working, old patch paths fail loudly.
  [`test_goal_declarative_workflow.py`](../../tests/test_goal_declarative_workflow.py) (boundary test)
