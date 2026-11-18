---
title: 'Story 66.2 实现技能匹配结果缓存'
type: perf
ticket: 2
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
  - 'src/heagent/skills/skill_store.py'
  - 'tests/test_skill_match_cache.py'
---

## Intent

`agent/system_prompt.py` 每轮构建系统提示都调 `SkillStore.match_skill_details(prompt, threshold)`，
而 `match_skill_details` 对技能库每个技能做一次 `store.parse(name)`（读 `SKILL.md` + `meta.yaml`
并解析 frontmatter）。同一 prompt 在多轮迭代里重复出现（工具循环里 prompt 不变），全部重算。

**Approach：** 在 `skill_catalog.py` 加结果缓存：

- `SkillStore.fingerprint()`（或 `skill_catalog` 内的等价函数）给出「技能库内容指纹」——
  逐技能 `(name, meta.yaml mtime_ns/size, SKILL.md mtime_ns/size)` 排序后 sha256 摘要；
- 缓存 key = `(fingerprint, prompt, threshold)`，LRU 容量默认 32，命中直接返回结果列表副本；
- 技能库任何文件被写 ⇒ 指纹变化 ⇒ 全部失效（不靠 TTL、不靠手动清理）。

## Verify

- 计数型硬断言：同一 prompt 连续匹配两次，第二次 `store.parse()` 调用次数为 0（缓存命中）。
- 失效：写入/改动任一技能的 `meta.yaml` 或 `SKILL.md` 后，指纹变化 ⇒ 下一次匹配重新解析。
- 提速 >30%：同 prompt 重复匹配的耗时对比（缓存命中 vs 冷启动），在 `-m benchmark` 用例里记录
  并断言比值（同时保留计数断言作为主判据）。
- `pytest tests/test_memory.py tests/test_skill_triggers_contract.py -q` 全绿。

## Boundaries

- 不改匹配算法与打分口径（score/priority/排序完全不变）。
- 不做跨进程持久化缓存：技能库改动在别的进程发生时本进程不可见，指纹只覆盖本进程读到的文件状态。
- 不改 `SkillMatch` 模型。

## Implementation（实测）

- 落点：`skills/skill_catalog.py` 的 `SkillMatchCache.results`（LRU 32）+ `skill_library_fingerprint()`
  （逐技能 `meta.yaml` / `SKILL.md` 的 `(mtime_ns, size)` 排序摘要）；缓存随 `SkillStore` 实例存活，
  `SkillStore.__init__` 仍不扫描技能库。
- 实测：`pytest tests/test_skill_match_cache.py -q` → 15 例全绿；同 prompt 第二次匹配 `store.parse` 调用数 = 0；
  改动任一技能文件后指纹变化 ⇒ 重新解析（调用数 > 0）；`-m benchmark` 用例（40 技能、7 次取中位数）
  断言 warm < cold × 0.7 通过（提速 >30%）。
