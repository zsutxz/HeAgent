---
title: '消除工具层对子 Agent 编排层的反向依赖'
type: 'refactor'
created: '2026-09-03'
status: 'done'
baseline_commit: 'f49c20a8e19df64111565a28a26e1c16c97bf997'
review_loop_iteration: 0
context:
  - 'AGENTS.md'
  - 'docs/frame.md'
---

<frozen-after-approval reason="human-owned intent - do not modify unless human renegotiates">

## Intent

**Problem:** `tools/builtins/subagent.py` 直接导入并构造 `agent.sub.SubAgent`，使底层工具包反向依赖顶层编排模块，违反“新增 tool 禁止从 agent 导入”的架构约束，也让工具测试必须启动完整 Agent 栈。

**Approach:** 工具层只保留委派请求、结果序列化和运行时槽；具体子 Agent 构造与并行执行由 `agent` 层提供可注入的异步执行回调。`AgentLoop` 在 run 作用域绑定实现，工具层不再知道 `SubAgent` 类型。

## Boundaries & Constraints

**Always:** 保持 `task_delegate`、`task_parallel`、`task_status` 的工具名称、参数和 JSON 返回契约；保留角色解析、父 run 记录和并行结果顺序；跨模块结构化结果继续使用 Pydantic。

**Ask First:** 删除或重命名现有工具；修改外部可观察的 JSON 字段；改变子 Agent 的权限继承、sandbox 或失败语义。

**Never:** 在 tools 中使用延迟导入规避依赖检查；把确定性路由交给模型；顺带拆分 `cli.py` 或重写 `SubAgent`。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 单任务委派 | 已绑定执行回调、合法 task/role | 返回现有 `SubTaskOutcome` JSON | 执行失败返回 `status=failed` |
| 并行委派 | 非空字符串数组 | 保序返回 outcomes，混合结果为 `partial` | 非数组或非字符串元素返回 `status=error` |
| 未绑定运行时 | 调用任一委派工具 | 不构造 Agent | 返回 `status=error` |
| 未知角色 | role 不存在 | 不调用执行回调 | 返回包含可用角色的错误 JSON |

</frozen-after-approval>

## Code Map

- `src/heagent/tools/builtins/subagent.py:12` -- 当前反向导入和 `_make_subagent` 工厂；改为纯回调协议与运行时绑定。
- `src/heagent/agent/sub.py:35` -- `SubAgentResult`、`SubAgent` 与 `run_parallel` 的唯一编排实现，保持行为不变。
- `src/heagent/agent/loop.py:829` -- `_runtime_scope` 是依赖绑定入口，应提供由 agent 层实现的单任务/并行回调。
- `tests/test_subagent_tools.py:1` -- 工具契约测试应使用 fake executor，不再 monkeypatch `SubAgent`。
- `tests/test_sub_agent.py:1`、`tests/test_subagent_role.py:1` -- 保留真实 `SubAgent` 权限继承和角色行为覆盖。
- `src/heagent/cli.py` -- 本次只读；1903 行拆分属于后续独立重构。

## Tasks & Acceptance

**Execution:**
- [x] `src/heagent/tools/builtins/subagent.py` -- 定义可注入异步委派回调并移除所有 `heagent.agent` 导入。
- [x] `src/heagent/agent/loop.py` -- 在运行时作用域组装 `SubAgent` 并绑定单任务/并行执行实现。
- [x] `tests/test_subagent_tools.py` -- 用 fake executor 验证所有工具 JSON 和边界分支。
- [x] `tests/test_sub_agent.py`, `tests/test_subagent_role.py` -- 验证真实编排路径仍保持权限、角色和结果语义。

**Acceptance Criteria:**
- Given 全仓源码, when 搜索 tools 对 agent 的导入, then `src/heagent/tools/**` 中不存在 `from heagent.agent` 或 `import heagent.agent`。
- Given 现有委派工具调用, when 单任务、并行、失败、未知角色或未配置分支执行, then 返回契约与改动前一致。
- Given AgentLoop 启动一次 run, when 模型调用委派工具, then 回调获得当前 run 的 provider、stores、engine 和 parent run id。

## Spec Change Log

- 2026-09-08：新增 `src/heagent/agent/delegation.py`（`build_subagent_delegates` 回调工厂），而非把 `SubAgent` 构造内联进 `AgentLoop._runtime_scope`——loop.py 只做「每 run 绑定 / 退出解绑」，编排细节独立可测。
- 2026-09-08：`configure_subagent_tools` / `bind_subagent_tools` 首参由 `provider` 改为 `delegate_one` / `delegate_many` 回调；`SubagentToolRuntime` 只保留回调与 `run_context` / `roles`（从未被读取的死字段 `default_system` 一并移除）。内部 API 变更，工具名 / 参数 / JSON 契约未动。
- 2026-09-08：`task_parallel` 增加「回调返回条数与 tasks 不等长即 `status=error`」的显性校验，避免错位记账（回调契约要求等长保序）。
- 2026-09-08：新增 `tests/test_agent_delegation.py`（结果映射 / 并行实例隔离 / 组件与 parent_run_id 透传 / AgentLoop 端到端绑定与解绑）；`tests/test_coverage_19_1.py` 4 个用例改用新 API；`tests/test_subagent_tools.py` 改为 fake executor（不再 monkeypatch `SubAgent`）。

## Design Notes

工具层运行时保存 `delegate_one(task, role_spec, system)` 和 `delegate_many(tasks, role_spec, system)` 回调。回调返回工具层定义的 Pydantic 结果，避免工具层引用 agent 数据类型；agent 层负责把 `SubAgentResult` 映射为该结果。

## Verification

**Commands:**
- `ruff check src tests` -- expected: 无 lint 错误。
- `pytest tests/test_subagent_tools.py tests/test_sub_agent.py tests/test_subagent_role.py tests/test_supervisor_role.py -q` -- expected: 全部通过。
- `rg -n "from heagent\.agent|import heagent\.agent" src/heagent/tools` -- expected: 无输出。
- `python -m compileall -q src` -- expected: 成功。
