# Adversarial Architecture Review — MCP v1→v2 升级准备 Architecture Spine

> 审查对象：`_bmad-output/mcp-v2-upgrade/architecture.md`（AD-1~AD-6）
> 审查方法：构造两个 Epic 14+ story（**story-X** = `handshake`+`ping` / **story-Y** = `list_tools`+`call_tool`+类型别名+字段兼容），验证它们各自**字面 obey 全部 AD** 却构建出**互不兼容**的产物。
> 代码核查源：`src/heagent/tools/mcp/manager.py` + `mapping.py` + `registry.py` + `agent/loop.py`
> 审查日期：2026-07-12

---

## Verdict

**Spine 在 v2 切换缝处自相矛盾**：AD-2 的「manager.py / mapping.py 零改动（git diff 为空）」与 AD-3 v2-路径步骤 3 的「`_make_handler` 的 handler 闭包捕获 call_tool 异常 → 调 `_unregister_server`」直接冲突——A 路径的注销触发器天然活在 manager.py 里（需要 `self._unregister_server`），无法被 session_api 吸收而不改签名；同时 AD-1 漏定了 `handshake`/`ping` 的返回类型与错误语义，AD-3 的「`_watch` 逻辑不动」与 AD-1 的「send_ping 必须经 session_api」字面冲突，AD-6 的允许导入清单含 `mapping` 制造循环导入风险。两个 story 沿 handshake+ping / list_tools+call_tool+types 缝切开，可各自逐字 obey 全部 AD 却在 v2 切换时和 v1→v2 过渡期产生不兼容构建。

---

## 代码核查（先于断言）

### `_unregister_server` 幂等性（manager.py:261-264）

```python
def _unregister_server(self, name: str) -> None:
    for tool_name in self._registered.pop(name, ()):
        self._registry.unregister(tool_name)
```

- `self._registered.pop(name, ())`：首次调用弹出工具名列表并注销；二次调用得 `()`（空元组），循环 no-op。**`_unregister_server` 对 `_registered` dict 幂等。**
- `registry.unregister`（registry.py:56-60）用 `self._tools.pop(name, None)` / `self._handlers.pop(name, None)` / `self._disabled.discard(name)`——同样幂等。
- **结论：ping 路径与 handler 路径并发触发 `_unregister_server` 同一 server 不会造成双注销损坏（幂等兜底）。** 真正的风险不是 double-unregister，而是**过早注销**（handler 对非断连错误触发注销）——见 Finding 4。

### `_watch` 与 handler 的 task 分离（manager.py:272-294 + loop.py:706-708）

- `_watch` 在 `_server_loop` 的**专属 task**内运行（`_connect_all` 经 `asyncio.create_task(self._server_loop(...))` 启动，manager.py:158）。
- `_make_handler` 返回的 handler 闭包经 `ToolRegistry` 注册，由 `AgentLoop._invoke_handler` → `invoke_handler(self, call)`（loop.py:706-708）在 **AgentLoop 的工具执行 task** 内 await。
- **两条路径运行在不同 asyncio task 中**，可并发触发 `_unregister_server`。单线程 asyncio 下 `dict.pop` 字节码原子，无数据竞争；幂等性进一步保证无重复注销。过渡期并发不是 correctness bug。

### `_watch` 实际调用链（manager.py:283-294）

```python
while not stop.is_set():
    try:
        await asyncio.wait_for(stop.wait(), timeout=self._health_check_interval)
        return  # stop set
    except TimeoutError:
        pass
    try:
        await asyncio.wait_for(session.send_ping(), timeout=self._health_check_interval)
    except Exception as exc:
        logger.warning(...)
        self._unregister_server(name)
        return
```

- ping 失败/超时 → `except Exception` → `_unregister_server(name)` → `return`（`_server_loop` finally 退出 transport context）。
- AD-1 要求 `session.send_ping()` 改经 `session_api.ping(session, timeout)`——即 line 290 的调用点替换。

---

## Findings

### Finding 1（最强）: AD-2 ↔ AD-3 v2-路径步骤 3 直接矛盾——manager.py diff-empty 不可达

**引用的 AD：**
- AD-2 Rule：「`session_api.py` 导出函数签名在 v1→v2 切换前后保持不变；v2 切换**只改 `session_api.py` 内部实现**」
- v2 路径步骤 2：「`manager.py` / `mapping.py` 零改动（NFR-2 验证：**git diff 为空**）」
- v2 路径步骤 3（AD-3）：「`_make_handler` 的 handler 闭包捕获 call_tool 异常 → 调 `_unregister_server(name)`。注销路径（`_unregister_server`）复用，不新增。」

**Unit A = story-X（handshake + ping）：** obey AD-2（「v2 切换只改 session_api.py」）+ AD-3 v1 Rule（A 路径「**不含本周期实现**」）→ 在 v1 **不**预埋任何 call_tool 失败 → 注销的 handler 钩子；`_make_handler` 保持现状 `result = await session_api.call_tool(...); return bridge_result(result)`。story-X 信任 AD-2：v2 切换只动 session_api，manager.py 不碰。

**Unit B = story-Y（list_tools + call_tool + types + 字段兼容）：** obey AD-3 步骤 3（「`_make_handler` 的 handler 闭包捕获 call_tool 异常 → 调 `_unregister_server`」）→ 要在 v2 切换时达成此步且同时 obey AD-2（manager.py diff 为空），story-Y **必须在 v1 就预埋** handler 的失败注销钩子（使 v2 仅 flip session_api 内部标志）。但预埋违反 AD-3 的「不含本周期实现」+ AD-4（纯 v1，不引入 v2 语义）。

**不兼容：** story-X 在 v1 不碰 `_make_handler`（信 AD-2）；story-Y 在 v1 预埋 handler 失败钩子（为让 AD-2 在 v2 成立）。v2 切换时，story-X 的设计**要求 manager.py 改动**（违反 AD-2），story-Y 的设计**在 v1 已含钩子**（违反 AD-3/AD-4）。两者不可同时成立。

**根因：** A 路径的注销触发器天然活在 manager.py 的 `_make_handler` 里——它需要 `self._unregister_server(name)` 的引用。session_api 无法吸收此逻辑：
- 给 `call_tool` 加 `on_failure` 回调参数？→ manager.py 在 `_make_handler` 时传入回调，v1 传 None、v2 传 `lambda: self._unregister_server(name)`——仍是 manager.py 在 v2 的改动，违反 AD-2。
- 把 `_unregister_server` 引用注入 session_api？→ session_api 需持有 MCPClientManager 实例引用，违反 AD-6（session_api 不从 manager 导入）+ Conventions（「隔离层无状态，纯函数 + 传入 session」）。

**AD-2 的「manager.py diff 为空」对 A 路径根本不可达。**

**建议 AD 修复（二选一）：**
- **方案 a（推荐）：前移预埋 + 签名固化。** 新增 **AD-7**：v1 在 `_make_handler` 一次性预埋 `try: result = await session_api.call_tool(session, name, args) except Exception: self._on_call_failure(name); raise`，其中 `self._on_call_failure` 在 v1 是 no-op（候选 C），v2 切换时改为调 `_unregister_server`。v2 切换**只改 `_on_call_failure` 方法体**（manager.py 内部方法，非对外接口）——AD-2 的「对外签名 diff 为空」保留，但「manager.py git diff 为空」放宽为「`_make_handler` handler 闭包结构在 v1 定型，v2 仅改 `_on_call_failure` 实现」。
- **方案 b：承认 AD-2 过约束。** 修订 AD-2：「v2 切换 manager.py 允许 `_make_handler` 局部改动（加异常作用域内的 `_unregister_server` 调用）；其余 manager.py / mapping.py 行不动。session_api 对外签名仍不变。」

---

### Finding 2: AD-1 漏定 `handshake`/`ping` 返回类型与错误语义——story-X 可选破坏 AD-2 的签名

**引用的 AD：**
- AD-1 表格：`async handshake(session)`（无 `-> ...`）、`async ping(session, timeout)`（无 `-> ...`）。仅 `list_tools(session) -> list[Tool]` 和 `call_tool(session, name, args) -> CallToolResult` 有返回类型。
- AD-2 Rule：「`session_api.py` 导出函数签名在 v1→v2 切换前后保持不变」
- AD-3 v2 Rule：「`ping()` 语义改为候选 A」+ v2 路径步骤 1：「`ping(session, timeout)` → 候选 A 语义（call_tool 失败触发注销）」——即 v2 ping 为 no-op。

**Unit A = story-X（handshake + ping）：** obey AD-1（提供 handshake/ping，表格未定返回类型）→ 可实现 `async def ping(session, timeout) -> bool`（True=存活，False=断连），`_watch` 检查返回值 `if not alive: self._unregister_server(name); return`，不靠异常。v2 的 ping no-op 返回 `None`——签名 `bool → None` 变化，**违反 AD-2**。

**Unit B = story-X（另一读法）：** 实现 `async def ping(session, timeout) -> None`（失败/超时即 raise，`_watch` 经 `except Exception` 捕获）→ v2 no-op 返回 None 不 raise，签名兼容 AD-2。

**不兼容：** AD-1 未固定 `ping` 的返回类型与错误语义（raise vs return-bool）。story-X 选 `-> bool` 则 v2 no-op 切换破坏 AD-2 签名；选 `-> None`+raise 则兼容。两读都字面 obey AD-1。更糟：若 ping 返回 bool 且 `_watch` 检查 bool，则 AD-3 的「`_watch` 逻辑不动」在 v2 也被破坏（v2 no-op ping 不返回 bool，`_watch` 的 `if not alive` 分支失效）——与 Finding 3 叠加。

**建议 AD 修复：** 收紧 AD-1 表格，补全签名 + 错误语义：
- `async handshake(session) -> None`（v1 调 `initialize`，v2 no-op；不返回值，失败 raise）
- `async ping(session, timeout) -> None`（**失败/超时即 raise**，沿用 v1 `send_ping`+`wait_for` 语义；不返回成功/失败布尔值。v2 no-op 时返回 None 不 raise）
- 显式注明：「ping 的存活/断连判定经异常传播，不经返回值；`_watch` 经 `except Exception` 捕获后调 `_unregister_server`。禁止返回 bool。」

---

### Finding 3: AD-3「`_watch` 周期探测逻辑不动」↔ AD-1「send_ping 必须经 session_api」字面冲突

**引用的 AD：**
- AD-1 Rule：「`manager.py` / `mapping.py` **禁止**直接 `session.initialize()` / `send_ping()` / `list_tools()` / `call_tool()` …；必须经 `session_api`。」
- AD-3 v1 Rule：「`session_api.ping()` 保留 `send_ping` 占位（候选 C，纯 v1，NFR-4）；**`_watch` 周期探测逻辑不动**。」

**Unit A = story-X（字面读「不动」= 代码不变）：** obey AD-3「`_watch` 逻辑不动」→ **不**重构 `_watch` 的 `session.send_ping()` 调用（manager.py:290）→ `send_ping` 直接调用残留 → **违反 AD-1**（manager.py 直接调 `send_ping`）。

**Unit B = story-X（读「不动」= 逻辑不变、调用点改经 session_api）：** obey AD-1（`_watch` 改调 `session_api.ping(session, timeout)`）→ `_watch` 代码**改动**（line 290 替换）→ 字面违反 AD-3「不动」。

**不兼容：** AD-3 的「不动」在「代码不变」与「逻辑不变、调用点替换」两读间歧义。字面读（代码不变）与 AD-1 的路由强制冲突。两个实现者读同一组 AD 落在相反的 `_watch` 重构决策上。

**建议 AD 修复：** 收紧 AD-3 v1 Rule 措辞：
「`_watch` 的探测**逻辑**（race `stop.wait()` vs ping，ping 失败/超时 → `_unregister_server(name)` + return）不动；**仅 `send_ping` 调用点改经 `session_api.ping(session, timeout)`**。`_watch` 的代码改动限定为调用点替换，逻辑分支结构不变。」

---

### Finding 4: AD-3 A 路径「call_tool 失败即注销」异常作用域歧义——可致过早注销（AD-5 回归）

**引用的 AD：**
- AD-3 v2 路径步骤 3：「`_make_handler` 的 handler 闭包**捕获 call_tool 异常** → 调 `_unregister_server(name)`」
- AD-5：「`tests/test_mcp_*.py` 全绿为本周期所有改动的零回归上限」

**Unit A = story-Y（窄作用域）：** try/except 仅包 `await session_api.call_tool(session, name, args)` → 仅连接级失败（call_tool raise）触发注销；正常工具错误（`isError=True` → `bridge_result` raise `ToolError`）**不**触发注销。（正确，无回归。）

**Unit B = story-Y（宽作用域）：** try/except 包整个 handler 体（`call_tool` + `bridge_result`）→ 任何异常含 `ToolError` 都触发 `_unregister_server` → **一次正常工具错误即注销该 server 全部工具**（行为回归，AD-5 违反：既有用例 `isError=True` 场景会红——工具被误摘，后续调用报 not found）。

**不兼容：** AD-3 的「call_tool 异常」未界定异常作用域是 call_tool-only 还是整个 handler。两读都字面 obey AD-3。宽作用域读法致 AD-5 回归。

**补充核查：** `_unregister_server` 幂等（见代码核查），故 ping 路径与 handler 路径并发双触发**不是** correctness bug。真正风险是**过早注销**——handler 对非断连错误（`ToolError` from `isError`、瞬时超时）触发注销，工具被误摘后 server 仍在线，工具滞留丢失直到重连。v1→v2 过渡期若两路径并存（ping 仍跑 + handler 钩子已激活），此风险叠加。

**建议 AD 修复：** 收紧 AD-3 步骤 3：
「注销触发器的 try/except **仅包 `session_api.call_tool(session, name, args)` 调用**，**不包 `bridge_result(result)`**。`bridge_result` 抛出的 `ToolError`（`isError=True`）**禁止**触发 `_unregister_server`——正常工具错误不是断连。仅 call_tool 级异常（连接失败、超时、协议错）触发注销。」

---

### Finding 5: v2 A 路径注销触发器 ownership 未指派——ping（story-X）vs handler（story-Y）

**引用的 AD：**
- AD-3 v2 Rule：「`ping()` 语义改为候选 A——call_tool 失败即注销」（框架为 ping 语义变更 → story-X 领地）
- AD-3 v2 路径步骤 3：「`_make_handler` 的 handler 闭包捕获 call_tool 异常 → 调 `_unregister_server`」（实际代码在 `_make_handler` → story-Y 领地）
- Conventions：「session 生命周期仍由 `MCPClientManager` 持有」

**Unit A = story-X（ping owner）：** 读 AD-3「`ping()` 语义改为 A」= v2 切换只改 session_api.ping → 假设 `_make_handler` 在 v2 不动（信 AD-2）→ **不**碰 `_make_handler`，v2 切换只动 session_api.ping。

**Unit B = story-Y（call_tool/handler owner）：** 读 AD-3 步骤 3「`_make_handler` handler 捕获 call_tool 失败」= v2 切换需 `_make_handler` 加注销钩子 → 假设 `_make_handler` 在 v2 **必须改**（与 AD-2 冲突，见 Finding 1）→ v1 预埋或 v2 改 manager.py。

**不兼容：** AD-3 把 v2 A 路径同时指派给两个 owner——ping（story-X）和 handler（story-Y）——未澄清谁实现实际注销触发器。v1 的注销 ownership = story-X（ping/_watch 路径）；v2 的注销 ownership = story-Y（handler 路径）。**v2 切换把注销 ownership 从 story-X 转移到 story-Y**，AD-3 未记录此转移。后果：v2 切换时，要么**两者都不实现**（工具滞留，安全立场违反），要么**两者都实现**（冗余，幂等兜底故功能 OK 但浪费）。

**建议 AD 修复：** 收紧 AD-3，显式指派 ownership：
「v2 A 路径注销触发器**唯一实现在 `_make_handler` 的 handler 闭包**（manager.py，story-Y 领地），**不在 session_api.ping**。v2 切换时 `session_api.ping` 变 no-op（`_watch` 的 ping 循环短路或移除）。ownership 转移：v1 注销由 story-X 的 ping/_watch 路径负责；v2 注销由 story-Y 的 handler 失败路径负责。v2 切换需 manager.py 局部改动（见 Finding 1 方案 b 对 AD-2 的修订）。」

---

### Finding 6: AD-6 允许 session_api 从 `mapping` 导入——与 AD-1 制造循环导入

**引用的 AD：**
- AD-6 Rule：「隔离层**仅从 `types` / `exceptions` / `registry` / `config` / `mapping` 导入**，禁从 `agent` 导入」
- AD-1 Rule：「`manager.py` / `mapping.py` … 必须经 `session_api`」+ 表格「类型别名 `Tool`/`CallToolResult`/…」由 session_api 导出，mapping.py 改从 session_api 取（替代 `from mcp.types import ...`，mapping.py:18）

**Unit A = story-Y（`input_schema_of`/`result_is_error` 放 session_api）：** mapping.py 从 session_api 导入类型别名 + 兼容函数；session_api 不从 mapping 导入 → 无循环。

**Unit B = story-Y（`input_schema_of`/`result_is_error` 放 mapping 再经 session_api re-export）：** session_api 从 mapping 导入这些函数（AD-6 允许）+ mapping 从 session_api 导入类型别名（AD-1 强制）→ **循环导入**（`session_api` ↔ `mapping`），运行时 `ImportError`。

**不兼容：** AD-6 把 `mapping` 列入 session_api 允许导入清单，但 AD-1 要求 mapping 反向从 session_api 取类型别名。两者同时成立 → 循环。structural seed 的 DAG 也确认方向是 `MAP --> API`（mapping 依赖 session_api），非反向。

**建议 AD 修复：** 修订 AD-6，从允许清单移除 `mapping`：
「隔离层**仅从 `types` / `exceptions` / `registry` / `config` 导入**（**禁从 `mapping` 导入**——mapping 经 AD-1 反向从 session_api 取类型别名 + 兼容函数，session_api 处于 tools/mcp 内部 DAG 最底层）；禁从 `agent` 导入。」

---

## Deferred 项需前移为 AD

### FR-3 A 路径实现（Deferred）→ 需前移为 AD-7

**Spine Deferred：「FR-3 等价机制实现（A）：本周期只文档化选型 + 路径，不含实现（NFR-4 纯 v1）。」**

**问题：** A 路径虽 deferred 到 v2 切换实现，但其**设计**（注销触发器活在 `_make_handler` 还是 session_api.ping）决定 AD-2（manager.py diff 为空）是否可达。Finding 1 证明当前设计（步骤 3 放 `_make_handler`）与 AD-2 矛盾。此矛盾**现在就影响 v1 代码**：story-Y 是否在 v1 预埋 handler 钩子，取决于此设计。不能 defer——**需现在用 AD 定死**。

**建议：** 新增 **AD-7**（见 Finding 1 方案 a）：v1 在 `_make_handler` 一次性预埋失败钩子骨架（`_on_call_failure` no-op），v2 仅改 `_on_call_failure` 方法体。使 AD-2 的「对外签名 diff 为空」+「`_make_handler` 闭包结构 v1 定型」同时成立。把 A 路径的**实现形态**从 Deferred 前移为 AD，只把**激活**（`_on_call_failure` 从 no-op 改为 `_unregister_server`）留 deferred。

---

## 附：AD-1 成功阻止的分歧（确认未漏）

AD-1 表格**确实固定**了 `list_tools(session) -> list[Tool]` 和 `call_tool(session, name, args) -> CallToolResult` 的签名，成功阻止了 story-X 暴露 `list_tools -> list[Tool]` 而 story-Y 期望 `list_tools -> PaginatedResult` 的分歧——因为表格的「隔离层导出」列是规范性的，两 story 必须遵守。AD-1 在这两点上是强约束。漏洞仅在 `handshake`/`ping` 的返回类型（Finding 2）和字段兼容函数的归属（Finding 6 的循环导入风险）。

Tool / CallToolResult 的 transformation ownership 未跨 story 冲突：story-Y 同时拥有 `session_api.call_tool`（产出 `CallToolResult`）和 `mapping.bridge_result`（消费 `CallToolResult`），单一 owner，无 two-owner 分歧。同理 `list_tools` 产出 `list[Tool]` 与 `mcp_tool_to_schema` 消费 `Tool` 均在 story-Y 内。AD-1 表格在此有效。

---

## 汇总：需新增/收紧的 AD

| # | 动作 | 内容 |
|---|---|---|
| AD-1 收紧 | 补 `handshake`/`ping` 返回类型 + 错误语义 | `-> None`，ping 失败 raise 不返回 bool（Finding 2） |
| AD-2 修订 | 承认 manager.py `_make_handler` 在 v2 局部改动，或前移预埋（Finding 1/5） | 「对外签名 diff 为空」保留；「manager.py git diff 为空」放宽 |
| AD-3 收紧 | 「不动」明确为「逻辑不动、调用点改经 session_api」；A 路径异常作用域仅包 call_tool 不包 bridge_result；ownership 指派 story-Y handler（Finding 3/4/5） | |
| AD-6 修订 | 从允许导入清单移除 `mapping`（Finding 6） | |
| AD-7 新增 | v1 预埋 `_on_call_failure` 钩子骨架，v2 仅改方法体（Finding 1，前移 Deferred） | |
