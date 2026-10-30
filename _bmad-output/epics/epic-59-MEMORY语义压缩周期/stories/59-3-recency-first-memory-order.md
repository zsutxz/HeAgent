# Story 59-3 · memory 读序翻转：最新优先注入 + auto_archive 同步 + 压缩指令补写

状态：**in-progress**（2026-10-30 post-retro 追加立项并当日开工；追加缘由见 retro 文档「Post-retro 追记」）
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

## 裁定记录

- 2026-10-30 用户裁定：合并历史、保留最新的、合并只在 dream、读取先读最新；展示序不动（D9）；
  接受头部失去保护、不做钉住折中（D10）；auto_archive 一并翻转（D11）。
  机制后果（黑暗区/merge 增益形态）见 epics.md §Story 59.3。
- 归属裁定：本 story 曾短暂立项为 epic-60，同日用户裁定转回 epic-59 名下（缺陷归属 + 冒烟顺带 +
  工件更少；epic-60 目录已删）。

## 关联

- 59-1/59-2（fact_compact 写侧 + dream 接线）：本 story 在其之上只翻转读取/淘汰序，compact 行为零改动（D13）
- epic-59 retro item-11（真实 LLM dream+compact 冒烟）：可在本 story 验证时顺带闭环
