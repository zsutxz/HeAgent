---
title: '批次 9 卡 D：写审计迁 goal/write_audit.py'
type: 'refactor'
created: '2026-11-07'
status: 'done'
route: 'oneshot'
review_loop_iteration: 0
context: []
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** 写审计判负策略家族（12 符号，cli/goal.py:369-582：AD-18 判负 + A40 内容指纹 + 兄弟写集并集防互诬告 + A43 参照系换算）住在入口层命令模块。

**Approach:** 家族迁新 `goal/write_audit.py`（goal 包 engine 同向先例已在 application.py）；事件发射能力注入化——emit 可调用由 cli 侧 `_workflow_event_emitter` 解析后作参数传入，家族零 cli 依赖、同守 click-free；`_goal_live_git_evidence` 复用的 `_audit_git_evidence` 随迁、cli 回导。行为零变化：判负语义/事件字段/参照系逐字；零直接 patch（全部经 `_goal_session` 高层缝）——签名内部变化不触测试。变异脚本 2 件的目标路径与锚点随迁同步。

</frozen-after-approval>

## Implementation Notes

**调查结论（2026-11-07，HEAD 89ff596）：**

- 家族清单：`_audit_git_evidence` :369-382（git_port lazy import :377）、`_covered_by_write_set` :385-400、`_emit_write_audit_event` :403-409、`_WriteAuditBaseline` :412-417、`_audit_story_writes` :420-501、`_write_audit_baseline` :504-511、`_content_fingerprints` :514-523、`_FINGERPRINT_CHUNK_BYTES` :527、`_fingerprint_paths` :530-543、`_host_artifact_relpath` :546-555、`_git_toplevel` :558-568、`_repo_relpath` :571-582。
- 外部消费：`_goal_execute_step` :324 基线（会话前）/ :363 审计（会话+结构门 :357 后）；`_goal_live_git_evidence` :1269-1271 复用 `_audit_git_evidence`（随迁回导）。发射路径：判负 reason :497-501 → :365 `WorkflowStepResult(FAILED, write_violation=True)`；事件经 `_emit_step_event("workflow_write_audit", skipped/untracked/violations)`。
- 缝：家族符号全仓零 patch 核实成立（8 处高层缝 `heagent.cli.goal._goal_session` + 1 处 `_goal_verify_report`）；`_workflow_event_emitter` :763-799 是家族唯一非家族依赖 → 注入化：`_emit_write_audit_event`/`_audit_story_writes`/`_write_audit_baseline` 增加 emit 参数，cli 调用点（:324/:363）传 `_workflow_event_emitter(engine)`。
- 变异脚本 2 件（scripts/mutation/mutate_write_audit_reference.py、mutate_write_audit_content_delta.py）硬编码 `TARGET_REL="src/heagent/cli/goal.py"` + 逐字代码锚点——随迁同步 TARGET_REL → `src/heagent/goal/write_audit.py`（锚点逐字搬运不变），否则「锚点出现 0 次」退出码 2。
- 台账 A41（deferred-work-archive.md:15）引 `cli/goal.py:440-444`（after 采集/git_unavailable skip 段）——搬移后随迁更新为新 file:line。
- imports：家族运行期 asyncio/hashlib/dataclass/SimpleNamespace/Path/Any + `GitEvidence`（goal.evidence）+ `write_set_parts`/`_emit_step_event`（engine.workflow_runner）+ `goal_step_artifact_path`（goal.document）；TYPE_CHECKING Sequence/EngineContainer/StoryExecutionContext；git_port 保持函数内 lazy。cli/goal.py 迁后可删 hashlib/SimpleNamespace/write_set_parts/dataclass（唯一用点均在家族）；GitEvidence/Sequence/_emit_step_event 留守（:1269/:1719/:799 仍用）。
- 契约：goal→engine 先例 application.py:40-44；`test_goal_application_use_case_is_click_free` 只 AST 扫 application.py——write_audit.py 自守 click-free（家族零 click）；goal/ 全包禁工作流包名字面量（contracts:895-910）——家族仅 import 符号无字面量 ✓；cli/goal.py 留守 layout 钉清单（:705-720）不受影响。
- 测试面：test_story_write_audit.py 21 个模块级函数、0 caplog、helpers_goal_audit.py 驱动、全部经高层缝——签名变化零测试改动。

**执行面（动面清单）：**
1. 新建 `goal/write_audit.py`：家族 12 符号逐字迁入 + emit 注入（`_emit_write_audit_event(emit, ...)`、`_audit_story_writes(..., emit)`、`_write_audit_baseline(..., emit)`）+ 模块 docstring（策略真身定位 + click-free 声明）。
2. cli/goal.py：家族删除；:324/:363 调用点改传 emit；`_goal_live_git_evidence` 改从 goal.write_audit 导入 `_audit_git_evidence`；删 4 imports。
3. 变异脚本 2 件 TARGET_REL 同步 + 各跑 M1 一轮自证（锚点命中且变红即验收）。
4. 台账 A41 行更新（新 file:line）。
5. 门禁 → 呈报制提交 → memory。
