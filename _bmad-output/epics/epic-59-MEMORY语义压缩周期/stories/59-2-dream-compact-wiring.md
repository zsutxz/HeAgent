# Story 59-2 · dream 接线 + 开关 + 口径收口

状态：**retro 后 done**（2026-10-29 交付 `eb36ea5`；评审与 59-1 同批，format/台账随 `99dba35`/`361e8e0`）
规格真源：`../epics.md` §Story 59.2（本文件为独立 story 文档 + as-built 记录）

## 轮廓

As a HeAgent 用户,
I want dream 在 idle/夜间巩固时自动执行语义压缩（默认关）,
So that MEMORY.md 注入预算自愈，无需手动整理。

## 范围

把 59-1 的写侧能力接进 dream 闭环：prompt 指令段、dreamer 白名单、统计回传事件、注入侧口径同步、
文档收口。所有行为在 `memory_compact_enabled` 开关下两态可证。

## 交付物（as-built）

- `src/heagent/memory/dream.py`：`DreamResult.compact` 字段；`<memory-compaction>` 指令段仅开关开启时
  拼入 prompt；`dream_end` details 复用既有事件通道携带 compact 统计（D8，不新增事件类型）
- `src/heagent/pub/roles.py`：dreamer 白名单**仅加** `fact_compact`（黑名单不动）；系统提示工具清单
  同步并注明「白名单放行 ≠ 开启」双层独立
- `src/heagent/agent/system_prompt.py`：超预算标注随开关条件化（FR7）：开启→指向 fact_compact/dream
  压缩；关闭→维持「需由用户整理」原文案
- `src/heagent/cli/composition.py`：dream 闭包**窗口归属**——run 前 drain 丢旧账 / run 后 drain 聚合 →
  `DreamResult.compact`（统计只归属本次 dream 窗口）
- `docs/frame.md` §4.6：语义压缩链路段（与自动归档段并列，含判据文件索引）
- 台账 A50（auto_archive 同族无锁读改写缺陷，`deferred-work-archive.md`）

## 验收标准 → as-built 判据

| AC | 判据 | 结果 |
|----|------|------|
| AC1 默认关（prompt 不含指令段，行为与现状一致） | `tests/test_dream.py::test_compact_directive_absent_when_switch_off` | ✔ |
| AC2 开启接线（指令段 + 白名单仅加 fact_compact） | `test_compact_directive_present_when_switch_on` + `test_ac4_dreamer_role_allowlist_blocks_dangerous_tools`（白名单断言扩） | ✔ |
| AC3 可观测（dream_end details 携带 compact 统计） | `test_dream_end_details_carry_compact_stats` + `test_dream_end_has_no_compact_key_when_none` | ✔ |
| AC4 口径同步（超预算标注条件化） | `tests/test_memory.py::test_over_budget_note_points_to_compact_when_switch_on`（关态文案由既有判据钉住） | ✔ |
| AC5 fail-soft（工具错误不终止 dream、不翻 success） | `test_compact_tool_error_is_fail_soft_for_dream`（真实 PolicyEngine/Executor/工具链 + stub provider 全链） | ✔ |
| AC6 文档（frame.md 补链路 + description 完整承载写侧准则） | `docs/frame.md:684`；`tests/test_fact_compact_tool.py::TestDescription` | ✔ |
| AC7 门禁 | 全量 **4200 passed** + ruff / format / mypy / 台账守卫全绿 | ✔ |

## 关键裁定

- 统计通道选型：**FactStore 实例累积 + dream 窗口 drain**（替代事件解析等通道）；run 前 drain 保证
  主循环与 dream 的压缩统计不互相混账；主循环并发 compact 被算进 dream 窗口的归属误差已知且接受
  （retro Findings 已记录）
- `<memory-compaction>` 指令段只住 dream prompt（动态、随开关）；RoleSpec 系统提示只做静态工具感知
  （白名单放行 ≠ 开启，双层独立）

## 验证（实测，2026-10-29）

`pytest tests/test_dream.py`（26 例）+ 全量 4200 passed + ruff/format/mypy/台账守卫全绿。
