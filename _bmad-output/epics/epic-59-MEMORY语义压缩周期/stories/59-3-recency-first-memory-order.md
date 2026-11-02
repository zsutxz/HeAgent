# Story 59-3 · memory 读序翻转：最新优先注入 + auto_archive 同步 + 压缩指令补写

状态：**done**（2026-10-30 post-retro 追加立项并当日开工，2026-11-02 全门实测后回写收口；追加缘由见 retro 文档「Post-retro 追记」）
规格真源：`../epics.md` §Story 59.3（D9–D13 冻结决策）

## 范围

MEMORY.md 读序价值序翻转（**合并历史、保留最新的、合并只在 dream、读取先读最新**，用户 2026-10-30 裁定）。
立项缘起：epic-59 收尾复核发现 `compact.py:198` 注释矛盾（「尾部最可能保留」与 `_fit_facts` 保头截尾相反），
端到端实证确认后用户裁定翻转读序——翻转后该注释论证自动成立，缺陷由本 story 消解。
四个交付面：

1. **注入选取翻转**（`agent/system_prompt.py`）
   - `_fit_facts`：改为从尾部倒装——预算内保留**最新后缀**、省略**最旧前缀**；返回值保持文件序（旧→新）
     （D9：选取方向翻转、展示序不动）
   - `_memory_block` docstring（「按文件顺序保留前部条目…省略较新尾部」）与新序口径同步翻转
   - 省略标注：「另有 {omitted} 条**较新**记忆未注入」→「**较旧**记忆未注入」；remediation 口径不变
   - 模块 docstring（~L49）与 `config/__init__.py:205` 注释同步
2. **auto_archive 新序**（`memory/auto_archive.py`，D11）
   - `_build_plan`：删除 `CORE_FACTS_TO_KEEP` 头部钉住；保留 = 全体 fact 中装进 `memory_archive_trigger_bytes`
     的**最新后缀**，归档 = **最旧前缀**；留底先行 + 比较后写 + fail-soft 契约不变
   - 模块 docstring「省略的是最新的尾部条目…移走中间老条目」 rationale 翻转；`_ARCHIVE_HEADER` 中
     「文件顺序是唯一先后凭据」的口径复核（文件序 = 时间序不变，无需改）
   - `CORE_FACTS_TO_KEEP` 常量删除（tests 同步更新）
3. **压缩指令补写**（D12）
   - `memory/dream.py` `_COMPACTION_DIRECTIVE` 补：「优先合并较旧的历史条目，保留最新表述」
   - `tools/builtins/memory.py` `fact_compact` description 补英文对应准则（写侧唯一闸门，需完整触达）
4. **注释一致化 + 文档同步**（D13）
   - `compact.py:198`：尾部追加 rationale 在新序下成立，注释改写为明确陈述（尾部=最新=新序下最先注入）
   - `docs/frame.md:814`（memory_inject_max_bytes 行）+ `docs/frame.md:450/682`（匹配行复核）+
     `docs/iteration.md:292`（§3.2 历史叙事——按历史记录保留或加新序注记，实现时裁定）
   - 运行时 MEMORY.md 文件头注记属运行产物，不在本 story 仓库改动内（登记为运行时跟进项）

## 验收标准

| AC | 内容 | 判据 |
|----|------|------|
| AC1 | `_fit_facts` 保留最新后缀、省略最旧前缀；返回保持文件序；`budget<=0` 不限制；单条要么整条注入要么整条省略 | `tests/test_memory.py` 注入预算用例（翻转断言方向） |
| AC2 | 省略标注「较旧记忆未注入」+ remediation 两态口径不变；保留为空不留空的事实行 | `tests/test_memory.py` |
| AC3 | auto_archive：无头部钉住，保留最新后缀、归档最旧前缀；留底先行（归档小节 + 真实 UTC 时间戳）；并发比较后写；fail-soft；`memory_archive_trigger_bytes<=0` 禁用 | `tests/memory/test_auto_archive.py`（判据全量重写） |
| AC4 | 压缩指令补写触达模型：dream prompt 含「优先合并较旧…保留最新表述」；fact_compact description 同步 | `tests/test_dream.py` / `tests/test_fact_compact_tool.py` 相关断言 |
| AC5 | compact.py:198 注释与 `_fit_facts` 新行为一致（矛盾消解，行为零改动）；compact 全部既有 AC 不回归 | `tests/memory/test_compact.py` 全绿 |
| AC6 | 文档同步：frame.md / iteration.md / 各模块注释无旧口径残留（grep 复核） | grep 无「保留前部」「省略较新」类残留 |
| AC7 | 全门绿：pytest 全量 + `ruff check` / `ruff format --check` / `mypy src` / `bandit -r src/ -ll` + `tests/test_architecture_contracts.py` | `python scripts/quality_gate.py` |

## 实测结果（2026-11-02 收口实测，容器沙箱 + `.heagent/tmp/py311-venv-linux`）

**代码落点核对（逐 AC 取证）**

| AC | 实测落点 | 结论 |
|----|----------|------|
| AC1 | `agent/system_prompt.py:257 _fit_facts` —— `for fact in reversed(facts)` 装预算、末尾 `kept_reversed.reverse()` 还文件序；`budget <= 0` 短路返回全量 | 通过 |
| AC2 | `system_prompt.py:248` 文案「（另有 {omitted} 条**较旧**记忆未注入：…）」；remediation 两态未变 | 通过 |
| AC3 | `memory/auto_archive.py` 模块 docstring + `_build_plan`（`:106` 从最新往前装）；全仓 `grep CORE_FACTS_TO_KEEP` 仅剩注释/文档的历史说明，无活常量 | 通过 |
| AC4 | `memory/dream.py:70`「优先合并较旧的历史条目，保留最新表述」；`tools/builtins/memory.py` `fact_compact` description 英文对应句「Prefer merging older historical entries and keep the newest wording」 | 通过 |
| AC5 | `memory/compact.py:198-200` 注释改写为「尾部 = 最新 = 59-3 保尾注入序下最先注入」，并注明 59-1 时该句与行为相反的历史 | 通过 |
| AC6 | `grep -rn "省略较新\|保留前部\|较新的尾部" src docs AGENTS.md` → **0 命中**；本轮另发现并修掉 2 处旧口径残留（见下） | 通过（含修补） |
| AC7 | 六门全绿（见下） | 通过 |

**AC6 发现并修掉的 2 处残留**（属本 story 交付面，非范围外顺手改）

- `docs/frame.md` 设置表 `memory_archive_trigger_bytes` 行：仍写「自动归档『前 20 条核心约定』与『最新尾部』之间的**中间老条目**」——那是已删的 `CORE_FACTS_TO_KEEP` 口径，与现行「归档最旧前缀」相反 ⇒ 改为「自动归档**最旧前缀**（保留能装进此预算的最新后缀；59-3 读序翻转后无头部钉住）」。
- `config/__init__.py:207` 字段注释：「中间老条目移入 archive/…」⇒ 改为「最旧前缀移入 archive/…」。

**命令实测**

| 命令 | 实测 |
|------|------|
| `python scripts/quality_gate.py`（`PATH` 前置 venv bin，六门一次跑完） | **all gates passed** |
| ├ goal workflow smoke | 通过 |
| ├ 回归 + 覆盖率（`--cov-fail-under=87`） | **4214 passed, 50 skipped, 25 deselected**（235.93s） |
| ├ 覆盖率（`coverage report --format=total`） | **93%**（门限 87%） |
| ├ `ruff check src tests scripts` | All checks passed |
| ├ `ruff format --check src tests scripts` | 374 files already formatted |
| ├ `mypy src` | Success: no issues found in 177 source files |
| └ `bandit -r src/ -ll` | No issues identified（High 0 / Medium 0；Low 8） |
| 定向子集 `pytest tests/test_memory.py tests/memory/test_auto_archive.py tests/memory/test_compact.py tests/test_dream.py tests/test_fact_compact_tool.py -q` | **142 passed**（3.41s） |

（容器内 bare `ruff`/`mypy` 不在 PATH，`quality_gate.py` 直接 `subprocess` 调它们会 `[Errno 2]`；
把 venv `bin` 前置到 `PATH` 后六门一次跑通，改的是取证环境而非仓库。）

## 裁定记录

- 2026-10-30 用户裁定：合并历史、保留最新的、合并只在 dream、读取先读最新；展示序不动（D9）；
  接受头部失去保护、不做钉住折中（D10）；auto_archive 一并翻转（D11）。
  机制后果（黑暗区/merge 增益形态）见 epics.md §Story 59.3。
- 归属裁定：本 story 曾短暂立项为 epic-60，同日用户裁定转回 epic-59 名下（缺陷归属 + 冒烟顺带 +
  工件更少；epic-60 目录已删）。

## 关联

- 59-1/59-2（fact_compact 写侧 + dream 接线）：本 story 在其之上只翻转读取/淘汰序，compact 行为零改动（D13）
- epic-59 retro item-11（真实 LLM dream+compact 冒烟）：可在本 story 验证时顺带闭环
