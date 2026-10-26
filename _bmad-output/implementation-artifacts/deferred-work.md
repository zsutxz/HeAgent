# Deferred Work Review Notes

> 历史 code review 摘要与**待办入口**。活动条目正文的唯一真源是
> [`deferred-work-archive.md`](deferred-work-archive.md)（四态：active / scheduled / frozen / retired）；
> 本文件只保留入口指针与已闭合事项索引，**同一 ID 不得同时出现在两个文件**（2026-10-26 S-6 单向收敛）。

## 活动条目入口

| ID | 主题 | 状态 | 正文位置 |
| --- | --- | --- | --- |
| A34 | 会话文件并发写残余（隔离 vs 丢弃语义待裁） | `frozen` | [archive](deferred-work-archive.md#活动未闭合条目) |
| A35 | HTTP 在途 run 与 SSE 缓冲重启即丢 | `active` | 同上 |
| A36 | 全局级 MCP 注入签名入口（YAGNI，触发条件未到） | `active` | 同上 |
| A40 | 审计基线已脏文件检测盲区（`cli/goal.py:434`） | `frozen`（AD-20，OQ-4 未裁） | 同上 |
| A41 | 兄弟 Story 越集写互相误归因（`cli/goal.py:440-444`） | `frozen`（AD-20，OQ-4 未裁） | 同上 |
| A42 | 违规写无补救语义（`workflow_runner.py:633`） | `frozen`（AD-20 族，OQ-4 未裁） | 同上 |
| A43 | `_host_artifact_relpath` 参照系（`cli/goal.py:454-457`） | `active` | 同上 |
| A44 | 交互 REPL 不挂事件 rollout sink | `active` | 同上 |
| A49 | `EmbeddedHttpService.failure` 传播路径缺直接测试 | `active` | 同上 |

> 已闭合的 4 条（A45 中断语义 / A46 cause 链 / A47 reason 无上限 / A48 失败事件缺驱动字段）正文与证据
> 在 archive 的「本轮闭合」段；Epic 52 审计语义 4 项的处置同样在 archive 的活动表（A40–A43），不再在本文件重复。

## 已闭合事项索引

| 来源 | 结论 | 证据 |
| --- | --- | --- |
| Story 51-4 | workflow/revision 冻结绑定已接入 `/goal verify`；执行期证据复用完成门，受治理重跑经过审计链 | `tests/test_goal_workflow_selection.py::test_frozen_revision_flows_into_verify_step`；Story 51-6/51-8 |
| Story 51-6 | workflow 与 revision 半键绑定规则已明确并有正反向测试 | `src/heagent/goal/application.py::read_workflow_binding`；`tests/test_goal_workflow_selection.py` |
| Story 51-7 | GoalScript 后续步骤声明、持久化恢复、受控 facade 和限额已完成；同步 CPU 密集脚本的超时限制仍依赖 OS 隔离 worker | `docs/frame.md` §4.13.1；`tests/test_goal_script_*.py`；`src/heagent/goal/script_runtime.py` |
| Story 51-2（异常路径落盘） | **已闭合**：`run_step()` 的异常分支经 `_absorb_step_exception()` 转换后由 `_persist_interrupted()` 落盘（`asyncio.shield` + 双层 except，落盘失败只告警不替换原异常） | `src/heagent/engine/workflow_runner.py::_persist_interrupted`；`tests/test_story_loop.py::test_story_failure_persists_failed_checkpoint` |
| Story 51-2（多 phase pause） | **生产路径不可达**：`_pause_resume_unlocked()` 首行 `if runner.done` 即返回 `UNCHANGED`（"declarative workflow is already complete"），`runner.pause()` 到不了 `COMPLETED` 态 | `src/heagent/goal/application.py::_pause_resume_unlocked` |
| 52-3 AC1（端到端围栏贯通冒烟） | **已闭合**（2026-10-26，Epic 57-3）：真实注册表 `file_write` handler 经 `policy.evaluate_tool_call → executor.execute` 全链贯通 | `tests/test_write_allowlist.py::test_e2e_chain_*`（2 例）；附带发现见 archive 已归档表 |

当前实现状态以源码、测试、`docs/frame.md` 和 `sprint-status.yaml` 为准；本文件不重复复制完整验收报告。
