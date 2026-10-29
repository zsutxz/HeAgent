---
status: final
stepsCompleted: ["step-01", "step-02", "step-03", "step-04"]
inputDocuments:
  - "docs/frame.md（架构权威：memory 模块节 / 安全口径 §4.19）"
  - "AGENTS.md（硬约束 / 依赖 DAG）"
  - "会话分析（2026-10-29）：MEMORY.md 现状链路与语义压缩缺口"
---

# Epic 59：MEMORY.md 语义压缩周期（dream 侧整理）

- 创建：2026-10-29
- 状态：delivered（59-1/59-2 同日实现落库待评审：fb3475d + 84452a6 + 59-2 提交；全量 4199 passed）
- 基线 commit：bf81b1d
- 来源：
  - 会话分析（2026-10-29）：MEMORY.md 现状链路——`fact_add` 只增不减、注入超预算省略**尾部最新**条目、
    启动 `auto_archive` 仅做确定性字节移出、dream 只会追加新条目；语义压缩缺口由 system prompt 内
    「需由用户整理」提示显性声明；
  - 用户裁定（2026-10-29）：整理/压缩能力加进 heagent，在 dream 里处理（启动侧不加 LLM）；走 BMAD
    流程，全部文档归本目录。

## 目标

MEMORY.md 超注入预算后不再只能手动整理：dream 在离线时段（idle/夜间 cron）自动把语义重复/过时
条目合并改写，注入预算自愈，最新记忆不再被静默省略。

## 非目标

- 不改 `fact_add` 的 70% 词级判重（确定性逻辑维持现状）。
- 不改启动侧 `auto_archive` 的确定性归档行为与触发条件（NFR1：启动路径零新增 LLM）。
- 不给 dreamer 开 file_read / 通用文件写面（白名单最小扩展，只加 `fact_compact`）。
- 不做 profile / soul 两库的压缩（本案只动 MEMORY.md）。
- 不改注入侧 `_fit_facts` 的「文件顺序前 N 条」口径（预算自愈交给压缩，不改选择策略）。

## 需求清单

### 功能需求（FR）

- FR1: 语义级压缩：合并 MEMORY.md 中语义重复/过时/可合并的条目（LLM 判断），保义减字节
- FR2: 压缩在 dream 闭环内执行（dreamer SubAgent 经工具回写），启动路径不引入 LLM 调用
- FR3: 被合并/移除的条目先留底再裁剪（archive 留底，不参与注入）——对齐 auto_archive「归档先于裁剪、宁重复不丢失」
- FR4: 改写走 `atomic_update_text` compare-after-read，并发 `fact_add` 追加不被整份覆盖（冲突即放弃本批，留底已落档）
- FR5: 显式开关（默认 False，不改变现行为）；关闭时 dream 巩固行为与现状完全一致
- FR6: 压缩结果可观测：事件携带统计（压缩前/后条数、释放字节、留底位置）
- FR7: system prompt 预算告警口径同步：「需由用户整理」→ 指向新机制
- FR8: fail-soft：压缩失败只记 WARNING + 事件，不拖垮 dream 其余巩固动作与主循环

### 非功能需求（NFR）

- NFR1: 启动路径零新增 LLM 调用、零阻塞（确定性 auto_archive 维持现状）
- NFR2: 无人监督删改持久记忆的安全立场诚实声明（三层非边界、OS 沙箱兜底；dream「改持久记忆」
  既有声明延伸到「删改」面——dreamer 无人监督下合并/删除记忆条目，影响后续所有会话）
- NFR3: 测试覆盖：工具层单测（合并执行/留底先行/锁冲突/fail-soft/开关关闭即拒）+ dream 接线测试
  （开关/事件/白名单）；`tests/test_architecture_contracts.py` 同步维护
- NFR4: 文档同步：`docs/frame.md` memory 节、`fact_compact` 工具 description、AGENTS.md（如涉及）

### 架构约束

- 新工具住 `tools/builtins/`，经 `configure_memory_tools` RuntimeSlot 注入 FactStore；`memory/` 运行期零 agent/engine 依赖（DAG 红线）
- dreamer 工具白名单在 `pub/roles.py` RoleSpec，最小权限扩展
- 跨模块数据用 Pydantic 模型，禁原始 dict；工具参数 schema 属工具边界不受此限
- 留底与 auto_archive 同目录约定（`.heagent/memory/archive/`），格式沿用小节 + 真实 UTC 时间戳

## 冻结决策

| ID | 决策 | 理由 / 代价 |
|----|------|-------------|
| D1 | 语义压缩**只放 dream 侧**；启动维持确定性 auto_archive | 压缩判断是概率任务，启动路径不被 LLM 阻塞（用户 2026-10-29 裁定 + 「确定性逻辑交给代码」准则）；代价：压缩只在交互模式 dream 触发后发生 |
| D2 | 写侧唯一入口 = 新工具 `fact_compact`（`tools/builtins/`） | 不给 LLM 直写文件面；工具内集中承载留底/锁/校验纪律；dreamer 白名单最小扩展 |
| D3 | **留底先行**：被移除条目先写 archive 再改 MEMORY.md；留底失败整批拒绝 | 对齐 auto_archive「宁可留底重复，不可移出丢失」；LLM 合并出错时原文可回溯 |
| D4 | 并发纪律：`atomic_update_text` compare-after-read；冲突放弃本批、留底保留 | 与 auto_archive `_replace_if_unchanged` 同款；并发 `fact_add` 追加不被整份吞掉 |
| D5 | 开关 `memory_compact_enabled` **默认 False**，工具层 fail-closed | 无人监督删记忆默认不开（对齐 Epic 58 D4 思路）；关闭 = dream 行为与现状逐字节一致 |
| D6 | source 以**条目原文精确匹配**定位（非行号） | 行号在 LLM 读文件与写之间会漂移；原文匹配天然抗并发漂移，缺失/不唯一即显性拒绝 |
| D7 | `system_prompt` 超预算提示同步指向新机制 | FR7；旧文案「该文件不对工具开放，需由用户整理」在能力落地后即失真 |
| D8 | 事件可观测：`dream_end` details 携带 compact 统计 | FR6；不新增事件类型，复用 dream 既有事件通道 |

## Stories

| ID | 标题 | 层 | 依赖 |
|----|------|----|------|
| 59-1 | memory 域 `fact_compact` 工具（留底先行 + 并发安全） | `tools/builtins/` + `config/`（开关） | 无 |
| 59-2 | dream 接线 + 开关 + 口径收口 | `memory/dream.py` + `pub/roles.py` + `agent/system_prompt.py` + docs | 59-1 |
| 收口 | 全量门禁 + sprint-status 回写 + 周期归档 | — | 59-1 / 59-2 |

### FR Coverage Map

- FR1 语义合并 → 59-1（compact 工具的 LLM 判断面）
- FR2 dream 执行 → 59-2（白名单 + dream prompt 指令）
- FR3 留底先行 → 59-1（工具内部保证）
- FR4 并发安全 → 59-1（`atomic_update_text` compare-after-read）
- FR5 默认关开关 → 59-1（工具 fail-closed）+ 59-2（settings 变量与接线）
- FR6 事件统计 → 59-2（dream_end details）
- FR7 prompt 口径 → 59-2（system_prompt 文案同步）
- FR8 fail-soft → 59-1（工具层）+ 59-2（接线层）各兜各的

## Epic 59: MEMORY.md 语义压缩（dream 侧整理）

### Story 59.1: memory 域 `fact_compact` 工具（留底先行 + 并发安全）

As a dreamer SubAgent,
I want 一个受控的 `fact_compact` 工具按「合并计划」改写 MEMORY.md,
So that 语义压缩的写侧有唯一入口：留底先行、锁内比较后写、失败显性不丢数据。

**Acceptance Criteria:**

**AC1 合并执行** Given 条目 A、B 存在，When `fact_compact(merges=[{sources:[A,B], target:C}])`，
Then A/B 行删除、C 追加、文件其余行原序原位保留（对齐 auto_archive 逐行删除口径）。

**AC2 留底先行** Then archive 留底小节含 A/B 原文与真实 UTC 时间戳；留底写失败 ⇒ 整批拒绝、
MEMORY.md 不动。

**AC3 并发冲突** Given 锁内读到的内容与重写时文件已变（模拟并发 fact_add），Then 外部新内容不被
覆盖、返回冲突错误、留底保留（宁重复不丢失）。

**AC4 显性失败** source 在文件中缺失或不唯一 ⇒ 整批拒绝（不部分应用），错误点名问题条目。

**AC5 判重口径** target 仅对「未被本批删除的条目」做 70% 词级判重，命中拒绝该 merge（被删 source
不参与判重）。多条 merge **顺序化应用**：后一条 merge 的判重集合包含前序 merge 已追加的 target
（批内产物互不重复；2026-10-29 retro 补写，实现与测试先于此句落地）。

**AC6 开关 fail-closed** `memory_compact_enabled` 默认 False；关闭时工具直接返回错误（缺失宁可
显性报错），不静默成功。

**AC7 未绑定降级** FactStore 未绑定 ⇒ 返回 `Error: fact tools not configured.`（与 fact_add 同款）。

**AC8 架构契约** 依赖方向不变，`pytest tests/test_architecture_contracts.py` 通过；AC1–AC7 单测
落 `tests/`（工具层，不调真实 LLM）。

### Story 59.2: dream 接线 + 开关 + 口径收口

As a HeAgent 用户,
I want dream 在 idle/夜间巩固时自动执行语义压缩（默认关）,
So that MEMORY.md 注入预算自愈，无需手动整理。

**Acceptance Criteria:**

**AC1 默认关** 开关 False 时 dream prompt 不含压缩指令段，dreamer 行为与现状一致（回归保障）。

**AC2 开启接线** 开启时：dream prompt 增加压缩指令段（工具用法 + 「不确定不改」原则）；
`pub/roles.py` dreamer 白名单仅新增 `fact_compact`（不开文件读写面）。

**AC3 可观测** `dream_end` 事件 details 携带 compact 统计（移除/新增条数、释放字节）。

**AC4 口径同步** `agent/system_prompt.py` 超预算提示由「该文件不对工具开放，需由用户整理」改为
指向 fact_compact/dream 机制。

**AC5 fail-soft** compact 工具错误不终止 dream、不影响其余巩固动作，`dream_end` success 语义
不因此翻 false。

**AC6 文档** `docs/frame.md` memory 节补压缩链路；`fact_compact` description 完整承载写侧准则
（唯一触达模型的闸门，对齐 fact_add 的显式 description 惯例）。

**AC7 门禁** 新增测试全绿 + `ruff check` / `mypy` 通过。

**收口** 全量门禁 + `sprint-status.yaml` 回写 + 周期目录归档（epic-58 同款）。
