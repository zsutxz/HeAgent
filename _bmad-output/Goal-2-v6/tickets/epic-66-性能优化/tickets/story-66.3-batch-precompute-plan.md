---
title: 'Story 66.3 优化技能匹配为批量预计算'
type: perf
ticket: 3
created: '2026-11-18'
status: done
baseline_revision: '0a70447'
route: full
route_source: auto
risk: low
review: quick
review_source: pinned
lenses_ran: [quick]
followup_recommended: false
context:
  - 'src/heagent/skills/skill_catalog.py'
  - 'tests/test_skill_index_batch.py'
---

## Intent

`match_skill_details` 的每轮成本是 O(技能数)：每个技能一次 `store.parse()`（IO + YAML/frontmatter
解析）+ 两次 `skill_tokens()`（CJK n-gram 切词）。这些量与 prompt 无关，却按 prompt 重复付出。

**Approach：** 把「与 prompt 无关的部分」抽成一次性构建的索引：

- `skill_catalog.py` 新增 `SkillMatchIndex`（`entries: tuple[SkillIndexEntry, ...]`，每条含
  `name` / `priority` / `pattern_tokens` / `triggers(casefold)` / `negative_triggers(casefold)` /
  `model_invocable`）；
- `build_skill_index(store)` 一次遍历技能库构建索引；索引按技能库指纹缓存（与 66.2 的指纹同一函数）；
- `match_skill_details` 改成「取索引 → 逐条做集合运算与阈值判定」，打分/排序口径逐字不变。

## Verify

- 等价性：对现有 `.heagent/skills` 与一组固定 prompt，新实现的 `SkillMatch` 列表与旧实现在
  名称、分数、优先级、`matched_triggers` 上逐条相等（等价性用例作为回归锁）。
- 批量效果：M 个技能 + N 个不同 prompt，`store.parse()` 总调用次数从 M×N 降到 M（计数断言）。
- 不影响启动：索引是**首次匹配时**构建，不在 `SkillStore` 构造/`scan()` 时构建（计数断言：
  构造 store 后 parse 次数为 0）。
- `pytest tests/test_memory.py tests/test_skill_triggers_contract.py -q` 全绿。

## Boundaries

- 不引入新的匹配算法/新特征（只把既有计算搬进索引）。
- 不改 `SkillMatch` / `SkillMeta` 模型。
- 索引不落盘。

## Implementation（实测）

- 落点：`SkillMatchIndex` / `SkillIndexEntry` + `build_skill_index(store)`，按指纹缓存（4 槽）；
  `match_skill_details` 变为「取索引 → 集合运算」，负向触发器、CJK n-gram 分母、trigger 原文回填与
  打分/排序口径逐字不变。
- 实测：`pytest tests/test_skill_index_batch.py -q` → 9 例全绿；等价性用例对多个 prompt 与参照实现逐条相等；
  M 技能 × N prompt 时 `parse` 次数 = M；构造 store 后 `parse` = 0、索引槽为空（不在启动期构建）。
