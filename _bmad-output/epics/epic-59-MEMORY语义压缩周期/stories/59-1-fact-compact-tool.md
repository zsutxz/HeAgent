# Story 59-1 · memory 域 `fact_compact` 工具（留底先行 + 并发安全）

状态：**done**（2026-10-29 交付 `84452a6`；评审 HIGH 修复 `a8b0fc6`；format `99dba35`）
规格真源：`../epics.md` §Story 59.1（本文件为独立 story 文档 + as-built 记录，内容以其为准）

## 范围

MEMORY.md 语义压缩的**写侧唯一入口**：dreamer SubAgent 经受控工具按「合并计划」改写 MEMORY.md——
留底先行、锁内比较后写、失败显性不丢数据。本 story 只交付工具层与 memory 域执行逻辑；dream 接线
（白名单 / prompt 指令段 / 事件统计）在 59-2。

## 交付物（as-built）

- `src/heagent/memory/compact.py`（新，自包含维护模块，与 auto_archive 同款惯例）：
  `CompactMerge` / `CompactRejection` / `CompactStats`（Pydantic frozen）、`FactCompactConflictError`、
  `compact_facts()`（批级校验 → 顺序化判重应用 → 留底先行 → `atomic_update_text` compare-after-read）、
  `aggregate_compactions()`（窗口聚合，供 59-2 dream_end 统计）
- `src/heagent/memory/facts.py`：`FactStore.compact()` 薄委托 + 实例级压缩累积（带锁、只记真实压缩）+
  `drain_compactions()`（59-2 窗口归属的存储侧）
- `src/heagent/tools/builtins/memory.py`：`fact_compact` 工具（门序：未绑定降级 → 开关 fail-closed →
  参数整形 → `asyncio.to_thread(store.compact)`）；description 完整承载写侧准则（唯一触达模型的闸门）
- `src/heagent/config/__init__.py`：`memory_compact_enabled` 默认 False；登记 `config/catalog.py`
  memory_skills 组 + `.env.example`（白名单计数守卫 48→49）

## 验收标准 → as-built 判据

| AC | 判据 | 结果 |
|----|------|------|
| AC1 合并执行（sources 删 / target 追加 / 其余原序原位） | `tests/memory/test_compact.py::TestMergeExecution` | ✔ |
| AC2 留底先行（归档小节含原文 + 真实 UTC 时间戳；留底失败整批拒绝） | `TestArchiveFirst` | ✔ |
| AC2+（审查 HIGH：归档追加经锁串行化，并发不丢小节） | `TestArchiveSerialization`（`a8b0fc6`） | ✔ |
| AC3 并发冲突（比较后写、外部追加不被吞、留底保留） | `TestConcurrency` | ✔ |
| AC4 显性失败（缺失/不唯一/重复引用/target 畸形，一次性点名） | `TestExplicitFailure` | ✔ |
| AC5 判重口径（被删 source 不参与；命中只拒该条；顺序化语义） | `TestDedupScope` | ✔ |
| AC6 开关 fail-closed（默认 False，关闭即显性报错、文件不动） | `tests/test_fact_compact_tool.py::TestGates` | ✔ |
| AC7 未绑定降级（与 fact_add 同款错误） | `TestGates::test_unbound_store_reports_not_configured` | ✔ |
| AC8 架构契约 + 单测不调真实 LLM | `tests/test_architecture_contracts.py` 37 passed | ✔ |

## 关键裁定（详见 retro 文档 Findings F5）

- `bytes_freed` 可为负（如实报告净变化，钳 0 会掩盖「越压越大」）
- AC5 顺序化：后序 merge 的判重集合含前序 merge 已追加的 target（spec 已于 retro 补写）
- 批内 source 重复引用 / target∈批内 sources / target 含换行 → 整批拒绝（AC4 精神的保守延伸）
- 全被拒的 no-op 压缩不进实例累积（dream_end 不出「removed=0 却带 compact 键」假信号）

## 验证（实测，2026-10-29）

`pytest tests/memory/test_compact.py tests/test_fact_compact_tool.py`（42 例）+ 全量 **4200 passed** +
`ruff check` / `ruff format --check` / `mypy src` / 架构契约 37 全绿。
