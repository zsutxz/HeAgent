---
title: 'Story 62.5 提取会话管理共享逻辑'
type: refactor
ticket: 5
created: '2026-11-17'
status: dropped
baseline_revision: '19668cf5693c79f8cc9cbdf44f38b58bd62ae9ef'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
context:
  - 'docs/frame.md'
  - '_bmad-output/Goal-2-v6/tickets/epic-62-代码架构重构/epic-62-代码架构重构.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 票面要求把 `cli/http_console.py` 与 `cli/interactive.py` 的会话管理逻辑抽取为 `cli/session_manager.py` 供双方复用。勘测（baseline 19668cf）判定票面前提不成立。

**Ruling（2026-11-17 用户裁定：改判「不做」，票闭合）：** 勘测证据——

1. 真实共享面仅剩 1 行：`SessionStore(str(paths.sessions))` 构造 ×2（`http_console.py:790`、`interactive.py:362`）；共享层已经存在，即 `SessionStore` 本体（context/memory 侧），两文件只是消费者；composition.py 已单点传递 `session` 参数。
2. 「缺省取最近会话」精神同源、实现**有意分叉**：interactive 走 Epic 30 `--continue`（`interactive.py:314` `recent_session_ids(1)`）；http_console 走 AC9（`http_console.py:812` `list_metadata()` + unreadable 过滤）——其 docstring（`:801`）明文解释为何**不能**用 `recent_session_ids`：损坏文件被沉底却不会被剔除，直接采用会把它当空会话覆盖掉。统一推导即推翻 AC9 损坏文件防护，属行为回归。
3. 其余会话面各自独占：`_guarded_session_id`/会话 CRUD 仅 http_console（HTTP 外部输入守卫，interactive 无此输入面）；`_compact_session` 仅 interactive。
4. 与 2026-11-06 跨模块去重普查结论一致（最大孪生对判有意分离），epic-60 档案无本对未决裁定。

抽取的两个方向均与票面相悖：空壳模块（两条分叉推导同居一文件、互不复用）= 纯结构税；统一推导 = AC9 防护回归。故改判「不做」，本票零代码变更。

</frozen-after-approval>

## Ruling Record

- 处置选项已呈用户（不做 / 字面空壳提取 / 改判对象为 cli/http.py），裁定取「不做」。
- 票面 verify（"共享模块建立，两个文件均复用该逻辑"）以「前提不成立」关闭，不以实现关闭。
- 票外线索登记（不属本票，不入码）：`cli/http.py` 1014 行超 NFR3 单文件 <1000 红线，为本 epic 域内现存唯一已知超标文件；已报用户，未立项。
