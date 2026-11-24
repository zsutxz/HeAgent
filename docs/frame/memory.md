# 记忆系统（`memory/` + `skills/`）

> 状态：实现细节参考，自 [`framework.md`](../framework.md) **4.6** 迁出（2026-11-24 整理；编号不变，
> 其它文档里「4.6」的引用即指本页）。架构视角（项目定位 / 数据流 / 模块 DAG / 各模块职责与边界）见
> [`framework.md`](../framework.md)，安全立场（canonical）见 [§4.18](../framework.md#418-安全口径canonical)，
> 扩展页总索引见 [`frame/README.md`](README.md)。

## 4.6 记忆系统 (`memory/`)

### facts.py — 事实存储

`.heagent/memory/MEMORY.md`，70% 关键词重叠去重。通过 `fact_add` 工具由 LLM 自主保存（**append-only**）。

注入侧有字节预算 `memory_inject_max_bytes`（默认 98304 = 96 KiB，0=不限制）：`_memory_block` 按文件顺序累计`- <fact>` 的字节数，超预算保留**前部**条目并在块尾追加省略标注（含省略条数/总条数/预算值）同时打 warning——绝不静默；文件本体不被修改，超预算条目仍在盘上，整理该文件即释放预算（无预算时单轮 SYSTEM 前缀实测可达数万 token，预算是必要刹车）。

**写侧闸门**：预算只在读侧刹车，故 `fact_add` 的工具描述（**唯一能触达模型的写侧入口**——本文件头部注记不进 system prompt）明确「只写改变未来行为的结论，不收过程叙述 / 状态记账 / 探针细节」，`<memory-nudge>` 同口径复述；`tests/test_memory.py::TestFactAddWriteGuardrail` 钉住该契约。实测中过程叙述与状态记账一度占到文件四成以上、把最新事实挤出预算 ⇒ 写侧契约须配合定期整理（压缩原则与工具见该文件头部「整理历史」与 `.heagent/tmp/mem_curate.py`）。

**自动归档（2026-10-10 重写）**：`memory/auto_archive.py` 在 CLI 启动时（`console.py::_prune_runtime_artifacts`，独立 try-except）检查 MEMORY.md——fact 总字节超过 `memory_archive_trigger_bytes`（默认 49152 = 注入预算的一半；0=禁用）时，保留**最新尾部**能装进预算的后缀、把其余的**最旧前缀**移入单一 append-only `.heagent/memory/archive/MEMORY-archive.md`（每批一个小节，标题带**真实** UTC 时间戳；2026-10-30 59-3 读序翻转：`CORE_FACTS_TO_KEEP` 头部钉住已删，与 `_fit_facts` 保尾序配对——归档移走的正是注入将省略的同一段最旧前缀）。重写**逐行删除**被移走的 fact 行、其余行原位保留；MEMORY.md 的写入走 `atomic_update_text` + 比较后写（并发 `fact_add` 的追加不会被整卷覆盖）；**归档文件自身的追加**也在它自己的 `.lock` 内读改写（归档小节构造、UTC 时间戳与字节账 `_fact_line_bytes` 单源住 `auto_archive._append_archive`——2026-11-14 清理批从 `compact.py` 收敛而来，`memory/compact.py::_append_archive_section` 退化为带 `label="；fact_compact"` 的**薄委托**（保留 `tests/test_compact.py` 的 monkeypatch 缝）；跨进程节流标记同批改用 `pub.persist` 的 `stamp_is_recent`/`touch_prune_stamp`——与 store/ledger/housekeeping 共用的唯一节流序列，原手写 `_should_skip_prune`/`_touch_stamp` 双轨读取协议已删）——两个写者并发归档若各读旧内容再整份写回，会互相吞掉对方的小节，且丢失**无声且不可检测**（条目既不在 MEMORY.md、也不在留底里；A50，2026-11-02 闭合）。任何异常 fail-soft（只 WARNING，不阻断启动）。为什么是「字节」而不是「天数」：事实条目格式只有 `- <text>`，**没有真实时间戳**——原实现用 `DAYS_PER_FACT = 7` 从 mtime 线性外推「年龄」，2026-10-09 那批 170 条因此被写进 `archive/2023-04.md … 2026-07.md` 40 个**虚构月份**文件（且重写时静默丢弃 fact 之后的非 `- ` 行），该口径已于 2026-10-10 删除。判据：`tests/memory/test_auto_archive.py`（16 例；其中 `TestArchiveAppendSerialization` 两例分别钉机制「归档追加必经 `atomic_update_text`」与行为「两写者并发追加后两段小节都在」）。

**语义压缩（epic-59，2026-10-29）**：归档只做确定性字节移出，语义重复/过时条目的**合并改写**由 `memory/compact.py` 承载、经 `fact_compact` 工具（`tools/builtins/memory.py`，写侧唯一入口）在 **dream 侧**执行——启动路径零新增 LLM（确定性逻辑交给代码）。写侧纪律：source 以**条目原文精确匹配**定位（非行号），缺失/不唯一/批内重复引用即整批拒绝并点名；**留底先行**（被移除条目先写同一 `archive/MEMORY-archive.md`，小节标题带 `；fact_compact` 标记区分写者，留底失败整批拒绝）；MEMORY.md 重写走 `atomic_update_text` compare-after-read（并发 `fact_add` 追加不被吞，冲突放弃本批、留底保留——宁重复不丢失）；target 对「未被本批移除的条目」做 70% 词级判重（公式单源 `compact.word_overlap_duplicate`，`FactStore.add` 反向复用同一公式——2026-11-14 清理批把三份拷贝收成单点），命中只拒该条 merge（多条 merge 顺序化应用，后序判重集合含前序 target）。开关 `memory_compact_enabled` **默认 False**、工具层 fail-closed（无人监督删改持久记忆须显式 opt-in，对齐 `dream_enabled` 立场；关闭时 dream prompt 与现状一致——dreamer 系统提示/白名单虽无条件含 `fact_compact`，调用会被工具层显性拒绝，故巩固行为不变）。接线：dream prompt 仅在开启时拼 `<memory-compaction>` 指令段；dreamer 白名单仅加 `fact_compact`；dream 闭包对 `FactStore.drain_compactions()` 做**窗口归属**（run 前 drain 丢旧账、run 后 drain 聚合为本次窗口统计）→ `DreamResult.compact` → `dream_end` details 携带 compact 统计（不新增事件类型）。注入侧超预算标注随开关条件化：开启指向 `fact_compact`/dream 压缩，关闭维持「需由用户整理」。判据：`tests/memory/test_compact.py`、`tests/test_fact_compact_tool.py`、`tests/test_dream.py`。

**崩溃窗口口径（2026-11-06 定向审查裁定，无缺口）**：`compact_facts` 在「留底已写 → MEMORY.md 比较后写」之间崩溃，残留为留底与现行**并存的可检测重复态**（archive 小节带 `fact_compact` 标记即崩溃遗留的合成痕迹），无静默丢失路径——归档并发覆盖已由 A50 闭合、比较后写防并发吞写（冲突放弃本批、留底保留）；同批 merge 可原样重放恢复（source 精确匹配仍唯一在场），失败方向与「宁重复不丢失」一致，不引入锁文件语义。

### 技能库（顶层 `skills/` 包，2026-10-10 自 memory/ 迁出）

> **Phase 4 C4（2026-09-21）拆分 + 2026-10-10 迁出**：原单文件 `skills.py` 先拆为 `skill_models.py`（模型 + `parse_skill_md` + 名称校验）、`skill_rewrite.py`（渲染 / `body_survives_rerender` / frontmatter 就地改写）、`skill_catalog.py`（匹配 + 过期盘点，以 store 为数据源的纯函数）、`skill_store.py`（`SkillStore` 门面）；`skills.py` re-export 兼容。`SkillStore` 文件读取走 `path_safety.open_text_under_root` 单一安全入口（契约测试钉 `os.open` 白名单 = path_safety + persist 锁文件）。

**双根技能库（2026-10-10）**：构造接受多根、序即优先级——全局 `~/.heagent/skills`（`config.GLOBAL_CONFIG_DIR` 锚点）先、项目 `<root>/.heagent/skills` 兜底（与 roles/commands 的「本地覆盖全局」方向相反，属技能库的刻意语义：自研技能跨项目共享、usage 跨项目累计）。读取沿根序 first-hit-wins，同名冲突全局生效 + 每名一次警告（`SkillStore.conflicts()` / `SkillCatalog.conflicts` 供复核与合并）；create 落 authoring 根（本地），update/record_usage 落拥有根，delete/archive 仅限 authoring 根（跨根显性拒绝）。catalog 跨根同 canonical_id 取最早源目录生效，不同 id 撞别名仍 ambiguous。

`.heagent/skills/<name>/SKILL.md + meta.yaml`，HermesAgent 标准目录结构（可选 `templates/`、`references/`）。SKILL.md frontmatter 只承载触发面四键（name/description/triggers/negative_triggers），其余（canonical_id/aliases/version/available/model_invocable/user_invocable/tags/created/priority/usage_count/last_used）在 `<name>/meta.yaml`（`skills/skill_meta.py` 契约，2026-10-10 拆分；解析到旧键显性抛 `SkillMetaError`）。双开关（B4，2026-11-06，meta.yaml）：`model_invocable: false` 不进自动注入检索（`match_skill_details` 过滤）；`user_invocable: false` 被 `skill_load` 显式拒绝（`Error:` 文案）；缺省两开向后兼容。frontmatter `triggers`、`negative_triggers`：负向触发优先排除，显式触发优先于常规相关度，随后按相关度、priority、名称稳定排序。常规匹配使用无依赖的混合 tokenizer：ASCII 标识符完整分词，CJK 使用二/三字片段（避免空格边界和单字高频误匹配）；旧 Skill 缺新字段时退化为原有 `pattern + tags` 相关度。自动注入同时受数量上限与可选总 token 预算限制，只注入完整正文、跳过超预算项且仅对最终注入项记录 usage；`skill_load` 可显式按名读取完整技能（同样不截断）。

**运行时计数与正文保真（2026-10-10 拆分后）：** `record_usage` 只原子回写 `meta.yaml`（`meta.yaml.lock` 文件锁），SKILL.md 运行时零写入——历史缺陷「自动匹配一次即把 130 行契约削成 411 字符空壳」从机制上消亡。`skill_update` 仍经 `_body_survives_rerender` 判定：只改 description/triggers/negative_triggers 时就地改写 frontmatter、正文逐字节保留（tags/priority 走 meta.yaml 事务）；要求改 `pattern` / `steps` 则抛 `SkillRewriteError(ValueError)` 显式拒绝（工具层转成可读 `Error:` 文案），无 frontmatter 块同样拒绝——无「静默重排正文」的路径（`save()` 仍是显式全量覆写 API，只在创建时被调用）。

### profile.py — 用户画像

`.heagent/user/USER.md`，按 section 更新。通过 `profile_update` 工具由 LLM 自主维护。

### soul.py — 人格系统

两级 SOUL.md 加载：全局 `~/.heagent/SOUL.md` + 项目 `.heagent/SOUL.md`。项目级存在时覆盖全局级，不做合并。

### dream.py — 离线记忆巩固调度器（Dreaming 模式，epic 外增量）

后台 asyncio 调度器，到点起角色化 `SubAgent(role="dreamer")` 对近期 session 历史 + 记忆库做巩固（去重 / 提炼 / 查证 / 归档），经 memory 工具回写四库，下个会话 `_build_system()` 自然注入。tick 逻辑**模仿而非塞进 `CronScheduler`**（dream 不进 `JobStore`、不是用户 prompt、有专属巩固流程；两者可并存于交互模式后台）。

| 组件 | 说明 |
|------|------|
| `DreamScheduler` | 双触发共用 tick（每 `cron_tick_seconds` 秒）：cron 时刻命中 + idle 超时（距上次 run ≥ `dream_idle_minutes`）；`_dreaming` 互斥（同时最多一个 dream）；`stop()` 带硬上界（对齐 `CronScheduler._await_stop`）；`__init__` fail-fast 校验 `dream_cron` |
| `DreamRunner` | agent 层注入的执行协议（`prompt → DreamResult`）；dreamer SubAgent 由 `cli.py` 组合根构造注入（`memory/` **不导入 `agent/`**，DAG 合规——与 `CronScheduler`+`JobRunner` 同构） |
| idle 计时 | 经 `EventBus` 订阅 `run_completed` 更新 `last_active_ts`（不改 REPL 同步 `input()`）；`_run_dream` finally 兜底重置（防失败/取消 dream 不发 `run_completed` 致每 tick 重燃） |
| session 预注入 | `SessionStore.recent_session_ids()` 按 timestamp 降序取最近 N，截断拼进 prompt（dreamer **不持 `file_read`**，最小权限） |
| `dreamer` 角色 | `RoleSpec` allowed/blocked 双层（见顶层 `pub/roles.py`）；`dream_enabled` 默认 `False`（opt-in） |

事件：`dream_start` / `dream_end`（trigger / success / iterations / run_id）经 `EventBus` 发布，`LoggingObserver` 落日志。

**触发投递语义（misfire 口径，2026-11-06 成文）**：双触发 tick 是**判定式而非队列式**——每 tick（`cron_tick_seconds`，默认 60s）以 `cron_matches(now)` 判定「此刻是否命中」，无排队、无补跑：进程宕机跨过整个命中窗口、或命中时已有 dream 在跑（`_dreaming` 互斥只防并发，不提供窗口幂等——快速 dream 收口后同窗口 tick 再命中会再跑一次），该次触发丢弃；idle 是机会主义触发（非预约），不适用 misfire。`CronScheduler`（§4.7）由**分钟级 ledger key** 提供每逻辑分钟至多一次的幂等（`ledger.complete` 先于 `last_run` 写回，P1-10；失败也盖 `last_run`，防每分钟热重试 P1-11），但同样**宕机窗口不补跑**——对跳过敏感的无人值守批次须在调用方（外部任务计划器或包装脚本）层自做 catch-up，框架内不补跑。

⚠ **安全立场**：dreaming = 无人监督 + 联网（`web_fetch` / `web_search`）+ 改持久记忆，被污染网页可经 prompt injection 跨会话污染记忆库——这是本模块的真实风险面，边界地位见 §4.18；OS 沙箱就绪后 dreamer 须迁移进沙箱。`web_fetch` / `web_search` 返回经 `guard_content` 启发式围栏（机制出自 Epic 35，2026-08-19：命中内置注入签名加 warning 标记后透传，不阻断；与 MCP `bridge_result` 同语义）。
