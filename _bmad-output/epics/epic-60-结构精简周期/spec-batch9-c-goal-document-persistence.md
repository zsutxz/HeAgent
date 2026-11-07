---
title: '批次 9 卡 C：goal 文档持久化迁 goal/document.py'
type: 'refactor'
created: '2026-11-07'
status: 'done'
route: 'oneshot'
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** goal 需求文档的持久化规则（goal id 冲突后缀分配 a–z + 三步写：文档 → checkpoint 工作区 → `current` 指针）内联在入口层命令函数 `_goal_declarative_new`（cli/goal.py:875-901）——业务规则住入口层。

**Approach:** 规则迁 `goal/document.py` 扩展（该模块已存在、已持 GOALS_DIR/goal_document 系）：新增 `reserve_goal_id`（后缀循环，取尽返回 None）与 `write_goal_bundle`（三步写；crash 半挂现状成文 docstring）；cli/goal.py 留编排、LLM 命名 await、`_echo` 呈现、cron 换绑——搬规则不搬呈现。行为零变化（含半挂语义），既有 tmp_path 真盘断言自然验收。

</frozen-after-approval>

## Implementation Notes

**调查结论（2026-11-07，HEAD 89ff596）：**

- 现场：`_goal_declarative_new` :860-902；持久化块 :875-901 逐段——875 previous 快照（换绑用，留 cli）、876 `llm_project_id` await（naming，留 cli）、877 workspace 解析、878-884 后缀循环（GOALS_DIR 目录 + `external_checkpoint_dir` 双占位；`""`+`-a..-z`）、885-887 else 分支 `_echo`（呈现留 cli）、888-891 `goal_document` 生成 + `goal_document_title` 校验（生成规则已在 document.py，本卡不重复）、893 文档落盘、894-895 `initialize_checkpoint_workspace`、896 `current` 指针内联写、897-899 except(OSError, ValueError) `_echo`（留 cli）、900-901 `_goal_auto_remove` 换绑（cron 接线留 cli）、902 advance（不属本卡）。
- document.py 现状：197 行，已持 GOALS_DIR/goal_document/path/title；`atomic_write_text`=pub/persist:427；current 指针无专用助手（:896 内联；`_goal_reset` :1749-1755 内联 unlink 不属本卡）。
- 调用链唯一：分发 :1591 → `_goal_start_new` :1478 → :1522；cron/GUI 零调用。
- 缝：块内符号零 patch；高层缝 test_goal_declarative_workflow.py:171 patch `_goal_declarative_advance`（noop，不动）；test_wiring_loop_helpers.py:91-92 patch `_goal_auto_goal_id`/`_goal_cron_advance` 不属本卡、不随迁。
- 测试面：tmp_path 真盘（:91-121 brief.md+frontmatter+title；:227-239 后缀 stock-picker→-a + current 指针；:212-219 命名失败回落 "project"+current）；0 logger、断言走 capsys err。
- 契约：document.py→pub.persist/pub.frontmatter 先例已在（:25-26）；goal 包入口层登记（contracts:56-62）；新助手同守 click-free。

**执行面（动面清单）：**
1. document.py 追加 `reserve_goal_id(base_id, external_checkpoint_dir) -> str | None`（后缀循环逐字）与 `write_goal_bundle(goal_dir, doc_text, paths_root)`（三步写逐字：文档 → checkpoint → current；docstring 成文「文档写成功 + current 写失败 = 半挂——行为等价保留，不新增机制」）。
2. cli/goal.py :878-884 改调 reserve_goal_id、:893-896 改调 write_goal_bundle；_echo/llm await/换绑留 cli；imports 增两名。
3. 门禁（pytest 不带 --cov + ruff + format + mypy）→ 呈报制提交 → 台账行 → memory。
