---
title: 'FR-3 收紧 — MCP server 运行时断连自动 unregister'
type: 'enhancement'
created: '2026-07-01'
status: 'done'
baseline_commit: '2ae99edf7909e229566f70486f6bccc952e378f4'
context: ['{project-root}/_bmad-output/mcp-client/architecture.md', '{project-root}/_bmad-output/mcp-client/epics-mcp-client.md', '{project-root}/docs/frame.md']
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** `MCPClientManager._server_loop`（`tools/mcp/manager.py:108`）连接 + 发现成功后 `await stop.wait()` 持有 session。运行时 server 崩溃 / 网络断开时，该 `await` 不触碰 session、**感知不到断连**——server 的工具滞留 `ToolRegistry`，LLM 仍把它们当可用工具（污染工具选择、重复调用死工具）。现状仅在工具被调用时 `session.call_tool()` 抛错降级为 `ToolError`（FR-3 运行时断连基线路径，已做）。架构（`architecture.md:517`）与 epic-13 回顾均把「断连自动 unregister」列为 future enhancement——本 spec 兑现它。

**Approach:** 每个 server 持有期 race `stop` 事件 vs 周期 `session.send_ping()` 健康探测（MCP SDK `ClientSession.send_ping` → `EmptyResult`，pin 版本可用）。ping 失败 → 注销该 server 已注册的全部工具 + WARNING 日志，随后该 server task 退出（同 task 内 transport context 在 `finally` 干净退出）。`_registered` 由扁平 `list[str]` 改为 `dict[str, list[str]]`（server 原始名 → 其已注册的 namespaced 工具名），以便按 server 精确摘除。

## Boundaries & Constraints

**Always:** 单 server 断连只影响该 server 自己的工具，其他 server + 内置工具零影响（NFR-6 错误隔离延续）；健康探测与 session 生命周期同 task（沿用现有「同 task enter/exit transport」架构，避免 anyio cancel scope 跨 task 回归）；ping 超时也视为断连（防 ping 挂死阻塞探测）；`__aexit__` 的 `_unregister_all` 与断连注销都经 `registry.unregister`（`pop(name, None)` 幂等，重复调用安全）；探测间隔可注入（测试用极小值，默认 5s）。

**Ask First:** 默认探测间隔 5s 是否合适（V1 取舍：越短发现越快但 ping 流量越多；本 spec 取 5s，可调）。—— 已在 spec 阶段定：5s。

**Never:** 不改 FR-3 建立失败路径（连接阶段失败工具不注入，已做）；不引入 server 重连（断连即注销，重连属另一 spec）；不把探测做成跨 task 后台守护（同 task 内 race，随 `__aexit__` 自然收回）；不动 `AgentLoop` / `ToolRegistry` 公共 API（仅用既有 `unregister`）；不融合「反应式 on-call 注销」作为第二模式（暴露冲突而非折中——见 Design Notes，选定主动 ping 单一机制）。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|---------------|----------------------------|----------------|
| 运行时断连主动注销 | 持有期 ping 失败 | 该 server 全部工具从 registry 摘除 + WARNING；其他 server 不受影响 | ping 异常被吞，仅记日志 + 注销 |
| ping 超时视作断连 | `send_ping` 超过探测间隔 | 同上（注销 + WARNING） | `asyncio.wait_for` TimeoutError 触发 |
| 正常运行不误删 | 持有期 ping 成功 | 工具保留，无日志 | ping 返回 EmptyResult 即可，不看内容 |
| `__aexit__` 优先于探测 | stop 被 set | 立即退出持有循环，不再 ping | `_watch` 检测 `stop.is_set()` 即返回 |
| 已断连 server 的 `__aexit__` | 断连已注销过 | `_unregister_all` 幂等 no-op | `registry.unregister` 用 `pop(_, None)` |

</frozen-after-approval>

## Code Map

- `src/heagent/tools/mcp/manager.py` -- `_registered` 改 dict；新增 `_watch()` 健康探测持有循环 + `_unregister_server()`；`_server_loop` 把 `await stop.wait()` 换成 `await self._watch(...)`；`_unregister_all` / `_discover_and_register` 适配 dict；构造器加 `health_check_interval`。
- `tests/test_mcp_manager.py` -- `StubSession` 加 `send_ping`（默认成功，可置 `disconnected` 标志后抛错）；新增断连主动注销测试 + 其他 server 不受影响测试。

## Tasks & Acceptance

**Execution:**
- [x] `src/heagent/tools/mcp/manager.py` -- `_registered: dict[str, list[str]]`；`_discover_and_register` 用 `setdefault(name, []).append`；`_unregister_all` 遍历 dict；新增 `_unregister_server(name)`；新增 `_watch(name, session, stop)`（race stop vs ping，ping 超时/失败 → `_unregister_server` + WARNING + return）；`_server_loop` 用 `_watch` 替换 `await stop.wait()`；构造器加 `health_check_interval: float = _DEFAULT_HEALTH_CHECK_INTERVAL`（5.0）。
- [x] `tests/test_mcp_manager.py` -- `StubSession.send_ping`（返回 None；`self._disconnected` 时 raise）；新增 `test_disconnect_auto_unregisters`（小间隔 + 置 disconnected → 等待 → 该 server 工具消失）；新增 `test_disconnect_isolated_to_one_server`（另一 server 工具保留）。

**Acceptance Criteria:**
- Given 两 server 各注册工具且进入持有期，when 其中一个的 session `send_ping` 持续失败，then 最多一个探测间隔后该 server 全部工具从 `registry.list_names()` 消失，另一 server 工具与内置工具完整保留，WARNING 已记。
- Given 持有期 ping 全程成功，when 正常 `__aexit__`，then 行为与现状一致（`_unregister_all` 摘除全部 MCP 工具，既有测试不破坏）。
- Given 探测间隔内 `__aexit__` 触发 stop，when `_watch` 在 `asyncio.wait_for(stop.wait())`，then 立即返回、不发起多余 ping、task 同 task 干净退出。

## Design Notes

**为何主动 ping-watch，而非反应式 on-call 注销（暴露冲突，选定其一不融合）：**
- 反应式（handler 在 `call_tool` 抛错时注销该 server 工具）零探测基建、最简，但**必须等一次调用**才触发——若死 server 的工具不再被调用，它们永久滞留 LLM 工具列表，持续污染工具选择。这与 FR-3「运行时断连」的语义不符（断连应被探测到，而非等调用撞上）。
- 主动 ping-watch 用 SDK 原生 `send_ping`，断连后最多一个间隔即注销，即使无调用也保持工具列表干净。代价是后台探测 + 间隔取值——本 spec 接受（间隔可调，测试用极小值）。
- 选定**单一**主动机制；既有「调用时降级 ToolError」作为基线保留（不是新加的第二模式，属既有 FR-3 路径，不动）。两者不融合为一个混合策略。

**探测同 task：** `_watch` 在 `_server_loop` task 内执行，与 session/transport 同 task——延续 `manager.py` 既有架构注释（避免 `streamable_http_client` 的 anyio cancel scope 跨 task 回归）。

**幂等：** `registry.unregister` 用 `pop(name, None)`，断连注销 + `__aexit__` 卸载可安全重复。

## Verification

**Commands:**
- `pytest tests/test_mcp_manager.py -v` -- expected: 既有 + 新增全绿
- `pytest tests/ -k mcp -v` -- expected: MCP 全套（含 http / mapping / config / cli）零回归
- `pytest` -- expected: 全量通过，无回归
- `ruff check src tests` -- expected: 无错误
- `mypy src` -- expected: 无新错误

## Suggested Review Order

**断连探测核心（设计意图入口）**

- 持有循环 race stop vs ping：`_watch`
  [`manager.py`](../../src/heagent/tools/mcp/manager.py)
- `_server_loop` 把 `await stop.wait()` 换成 `await self._watch(...)`
  [`manager.py:108`](../../src/heagent/tools/mcp/manager.py#L108)

**按 server 精确摘除**

- `_registered` 由 list 改 dict（server → 工具名）
- `_unregister_server(name)` 注销单 server 工具
- `_unregister_all` / `_discover_and_register` 适配 dict

**测试（外围）**

- 断连主动注销 + 单 server 隔离
  [`test_mcp_manager.py`](../../tests/test_mcp_manager.py)

## Review Findings

> BMad code-review（blind hunter + edge case hunter + acceptance auditor），2026-07-01。
> 结果：D=0 decision-needed / P=1 patch / W=6 defer / R=4 dismiss（误报 2 + 确认正确/不 flaky 2）。
> Acceptance Auditor：AC1/AC2/AC3 + Never 5 + Always 4 全通过。

### patch（已处理）

- [x] [Review][Patch] `health_check_interval <= 0` 致启动即误注销全部健康 server [`src/heagent/tools/mcp/manager.py:64-76`] — 构造函数无校验；`_watch` 直接把 interval 当 `wait_for` timeout，0/负值会让首个 ping 立即 `TimeoutError` → `_unregister_server` 摘除全部工具（即便 server 健康）。**已修复（2026-07-01）**：构造函数加 `health_check_interval > 0` 校验，违例抛 `ValueError`；回归测试 `test_health_check_interval_must_be_positive`。

### defer（pre-existing / spec 显式排除 / 非阻塞，详见 `deferred-work.md`）

- [x] [Review][Defer] `__aexit__` 的 `gather(*tasks)` 无超时，transport 清理卡住可致关停挂死 [`manager.py:85-93,144-149`] — deferred, pre-existing（`cm.__aexit__` 既有就无超时，非本次引入）
- [x] [Review][Defer] `_watch` 两个 `wait_for` 的 `TimeoutError` 同名异义 [`manager.py:235-245`] — deferred，内联注释已缓解，重构易碎
- [x] [Review][Defer] `_watch` `except Exception` 过宽 [`manager.py:242`] — deferred，spec Always 显式接受「ping 失败/超时即断连」保守 fail-safe
- [x] [Review][Defer] handler 未把 in-flight `call_tool` 底层异常封 `ToolError` [`manager.py:205-207`] — deferred, pre-existing，spec Never 排除反应式封装
- [x] [Review][Defer] `_unregister_all` 迭代 `.values()` 后 `.clear()` [`manager.py:216-221`] — deferred，当前安全（无 await 交错），防御性快照
- [x] [Review][Defer] 测试未断言 task done / transport 关闭 / 内置工具保留 [`tests/test_mcp_manager.py:252-273`] — deferred，测试保真度缺口

### dismiss（4）

- ~~ping 失败早退无 session 关闭~~（blind 误报：`_server_loop` finally `:144-149` 经 `cm.__aexit__` 关闭 transport，盲猎无项目权限未见）
- ~~ping 延迟 2×interval~~（前提错：死 server 主动拒绝时 ping 即时失败，≈1×interval，符合 AC1）
- ~~namespace 跳过工具不在 `_registered`~~（确认正确）
- ~~`disconnected` 标志与首次 ping 时序~~（1s 预算覆盖 100 周期，不 flaky）
