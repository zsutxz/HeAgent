---
title: 'Story 62.2 拆分 cli/goal.py'
type: refactor
ticket: 2
created: '2026-11-16'
status: done
baseline_revision: '6959a73aa7af45d5abbf673e0f4353a6623901da'
route: full
route_source: auto
risk: medium
review: quick
review_source: pinned
lenses_ran: [quick]
review_loop_iteration: 0
context:
  - 'docs/frame.md'
  - '_bmad-output/Goal-2-v6/tickets/epic-62-代码架构重构/epic-62-代码架构重构.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `cli/goal.py` 1636 行，超单文件 <1000 行红线（NFR3），是 epic-62 第二顺位拆分对象。

**Approach（2026-11-16 用户裁定，A 方案）:** 拆为 `cli/goal/` 子包内聚分模块（messages / verify / execution / commands + `__init__` 全量 `X as X` 再导出）。`heagent.cli.goal` 导入名不变（单文件→同名包），导入面零变化；16 处 monkeypatch 缝按消费模块重定向（9 处改字符串、6 处保留包命名空间不动）。票面两文件布局（`goal/cli_commands.py` + `goal/cli_display.py`）经调查否决：goal/ 是 click-free 域内核（契约 `test_goal_application_use_case_is_click_free` 钉死），搬入命令适配层造成方向污染；「结果展示」经 `_echo` 单点漏斗收敛后仅 ~30 行无可切层。

## Boundaries & Constraints

**Always:**

- 公开导入面零变化：`heagent.cli.goal` 导入名不变，`__init__` 全量 `X as X` 再导出（含 `__all__` 两符号 `goal_record_user_response`/`goal_user_responses`、5 缝属性、测试 import 面 `_goal_declarative_runner`/`_goal_declarative_workflow`/`_goal_runner`）
- monkeypatch 缝按**消费模块**重定向（缝不空打）：`_goal_session` ×7 → `...goal.execution`（消费点 `_goal_execute_step`）；`_goal_verify_report` ×1 → `...goal.verify`（消费点 `_goal_structured_gate`）；`_goal_declarative_advance` ×1 → `...goal.commands`（消费点 dispatch）；`_goal_auto_goal_id` ×4 + `_goal_cron_advance` ×3 **保留 `heagent.cli.goal` 包命名空间不动**（消费点 `cli/wiring.py:138` 惰性 from-import 读包命名空间）
- 层序无环：messages ← verify ← execution ← commands，`__init__` 汇总导出最后导入
- 原单文件删除；子模块无 logger（原模块 logger 是零使用点死变量，不迁）
- `test_entrypoints_do_not_duplicate_runtime_store_paths` 清单条目 `cli/goal.py` 切子包形态（62.1 glob 先例）；`test_architecture_contracts.py:58` 注释与 :456 docstring 的「cli/goal.py」口径顺手净化
- 本机 Windows：pytest 不带 --cov

**Never:**

- 不改任何行为：`_echo` 漏斗/sink ContextVar/锁语义/错误文案逐字保持
- 不动 `heagent.cli.goal` 命名空间的符号集（re-export 全集逐名核对）
- 不顺手做票外重构；不动 wiring/interactive/gui 三处消费者代码

</frozen-after-approval>

## Code Map（搬移账）

- `src/heagent/cli/goal.py` — 被拆对象（1636 行）。分组：常量 L120-131；`_MESSAGE_SINK`+`_echo` L134-151；声明式解析辅助 L163-217（`_goal_active_md` 另在 L1473-1494）；`_goal_declarative_prompt/prepare` L220-290；步骤执行 L293-373；script 两阶段 L377-551；事件发射 L554-603；命令处理器 L606-862（advance/new/doctor/status/pause_resume/decision/decisions + 决策渲染）；verify/门禁 L865-980 与 L1046-1159；解析/分发 L1162-1470；会话/cron/runner L1497-1636
- 分区归属：messages = L134-151；verify = L865-980 + L1046-1159 + 事件发射 L554-603；execution = L163-603（事件发射除外）+ `_goal_active_md` L1473-1494 + `_goal_session` L1497-1528；commands = 命令处理器 L606-862 + `_goal_declarative_verify` L982-1043 + 解析/分发 L1162-1470 + cron/runner L1531-1636
- 共享依赖再导出面：`_GOAL_FAILED/_GOAL_DONE/_GOAL_WAITING/_GOAL_ADVANCED`（状态词汇，prepare 用前三个、advance/cron_advance 用全部）——归 execution 定义，commands 经 `from .execution import` 消费；`_goal_declarative_runner`（application.restore_runner 别名）execution/commands 各自从 goal.application 导入
- patch 缝位点（16 处）：test_goal_cross_process_lock.py:19-20（形态待读）、:52；test_goal_decisions.py:24,27,772；test_goal_declarative_workflow.py:12-13,78,171,940；test_cron_notify.py:69,145,146；test_wiring_loop_helpers.py:90,91,118；test_story_write_audit.py:76,405；test_goal_quality_gates.py:18-19,652；test_goal_status_view.py:205；test_goal_script_step.py:17；test_story_scheduling_integration.py:220
- 缝重定向账：改 9 处（`_goal_session` ×7 → execution；`_goal_verify_report` ×1 → verify；`_goal_declarative_advance` ×1 → commands）；保留 6 处包命名空间缝零改动（`_goal_auto_goal_id` ×4 + `_goal_cron_advance` ×3——消费点 wiring.py:138 惰性 from-import 读包命名空间）
- 架构契约三处：`test_architecture_contracts.py:639` 清单条目 `cli/goal.py`（文件消失必改）、:58 注释、:456 docstring

## Tasks & Acceptance

**Execution:**

- [x] `src/heagent/cli/goal/` — 建子包搬移（messages/verify/execution/commands + __init__ 全量再导出），删原单文件 — 消除 >1000 行（2026-11-16，正文 bytes 逐字节搬移 + 手写 import 头）
- [x] tests patch 缝重定向：字符串 10 处（_goal_session ×8 → execution；_goal_declarative_advance ×1 → commands；_goal_verify_report ×1 → verify）+ 对象形式 ~20 处（doctor/status_view/quality_gates/message_sink/workflow_selection/declarative_workflow）→ 消费模块字符串形式；保留 10 处包命名空间缝（_goal_auto_goal_id ×4 + _goal_cron_advance ×3 + gui _goal_runner ×4——消费点 wiring.py:138 / gui chat.py:210 惰性 from-import 读包命名空间）— 缝不空打
- [x] 契约与配置同步：test_architecture_contracts.py 四处（:639 清单条目切 glob 子包形态、:58/:456 口径、test_cli_package_layout_is_pinned 期望表删 goal 条目）；ruff.toml C901 豁免 cli/goal.py → cli/goal/commands.py；pyproject.toml 覆盖率 omit `*/cli/goal.py` → `*/cli/goal/*`；docs/frame.md 七处口径 — 契约钉新布局
- [x] 行数实测：__init__ 237 / commands 829 / execution 536 / messages 30 / verify 323 — 全部 <1000（2026-11-16）
- [x] 全量验证：goal 批次 297 + 契约 38 + 外围（cli/contract_baselines/cron）74 全绿；ruff check/format、mypy 零错 — 行为零变化

**Acceptance Criteria:**

- Given 拆分完成，when 统计 `src/heagent/cli/goal/` 全部 .py，then 每文件 <1000 行且原单文件已删除
- Given grep 全部 `heagent.cli.goal` patch 字符串，then patch 目标 = 符号消费模块（6 处包命名空间缝除外——消费点 wiring 读包命名空间）
- Given Verification 全部命令执行，then 全绿（行为零变化）

## Verification

**Commands:**

- `pytest tests/test_goal*.py tests/test_story_write_audit.py tests/test_story_scheduling_integration.py tests/test_cron_notify.py tests/test_wiring_loop_helpers.py tests/test_gui_goal.py -q` — 全绿
- `pytest tests/test_architecture_contracts.py -q` — 全绿
- `ruff check src tests scripts && ruff format --check src tests scripts && mypy src` — 骶错
- `python -c "import heagent.cli.goal"` 冒烟 — 命名空间零变化

## Implementation Notes

### 2026-11-16 实现（全链当日闭合）

**实现**：五项 Execution 全部落地；正文按行号区间切割（bytes 逐字节搬移，切割脚本在 .heagent/tmp/goal-split/，临时区不入库），import 头手写。层序一处与 plan 草案不同：`_workflow_event_emitter`/`_emit_goal_gate_event` 归 **verify**（plan 草案归 execution——`_goal_structured_gate` 在 verify 内消费事件发射，归 execution 会成 verify→execution 环）；execution → verify 单向（完成门 + 脚本门验证 + 事件发射）。

**`__init__` 再导出形态**：项目 ruff（force-single-line）把 `X as X` 合并块自动拆为每符号独立语句（catalog/http_server 同款惯例）；`_goal_declarative_runner` 是 restore_runner 的**别名**导入（非同名），`X as X` 不适用 F401 豁免——改模块级赋值 `_goal_declarative_runner = restore_runner`（显式定义，mypy no_implicit_reexport 认可），真源仍 goal.application。

**缝账终局**：字符串缝 10 处重定向 + 对象形式缝 ~20 处转字符串重定向（消费链逐一核对：doctor/status_view/quality_gates/message_sink/workflow_selection/declarative_workflow 六文件）；保留 10 处包命名空间缝（wiring ×6 + gui ×4——消费点函数体内惰性 from-import，每次调用读包命名空间，patch 包命名空间即生效）。`_goal_verify_report` 缝的消费点核实 = `_goal_structured_gate`（verify 内部）。

**测试面适配（两处非机械改动）**：`test_all_goal_output_goes_through_the_echo_funnel`（源码扫描测试，原锚 `cli_goal.__file__` 单文件）切子包全模块扫描——offenders 禁其他模块 `click.echo` 直呼 + funnel 钉 messages.py 漏斗兜底唯一性；`test_cli_package_layout_is_pinned` 期望表删 `goal` 条目（单文件→目录，平铺清单不再含它；子包内部布局由 `test_entrypoints_do_not_duplicate_runtime_store_paths` 的 glob 形态覆盖）。

**动态验证**：goal 批次 297 passed；契约 38 passed；外围（test_cli / contract_baselines / test_cron）74 passed；ruff check + format --check + mypy 全零错。唯一实现期红 `test_build_ws_server_config_*`（9201 端口占用，在案环境噪声，与改动面无交集，未复现于本批）。

## Plan Change Log

- 2026-11-16：布局裁定 A（cli/goal/ 子包四模块），票面两文件布局否决理由见 Intent。
