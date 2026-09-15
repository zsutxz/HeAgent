# Epic 11–18 MCP 集成周期遗留项台账（deferred-work）

> **归并来源**：`_bmad-output/patches/_meta/deferred-work.md`（原跨周期技术债台账，2026-09-15 整理后退役并删除）。
> **归档规则**：按条目**归属的 epic** 归档；「闭合者」注明实际完成它的 epic / 补丁 spec / commit。
> **只登记已闭合项**——原始长文历史不再保留，结论全部指向代码、测试与 commit。
> **活动（未闭合）遗留项**仍在 [`implementation-artifacts/deferred-work.md`](../../implementation-artifacts/deferred-work.md)。
>
> **安全立场不变**：本文件中所有拦截 / 围栏 / 治理结论均为 **defense-in-depth，非真正安全边界**。
> 外部 MCP server = 不可信代码（stdio server 拉起任意本地子进程、HTTP server 连任意远端端点）；
> `SafetyGuard` / `PolicyEngine` / 返回内容启发式标记都可绕过，**须 OS 级沙箱 + 最小权限兜底**。

## 状态总览

| ID | 条目 | 状态 | 闭合者 |
|----|------|------|--------|
| E11-D1 | FR-3 auto-unregister 评审 6 项 `defer` | 4 项已修 / 2 项**决策关闭（保持现状）** | `spec-mcp-shutdown-timeout`（commit `109df37`）+ 2026-07-11 收尾（commit `7131cd0`）+ 2026-09-15 复核 |
| E11-D2 | DP-4 拆分 defer：MCP 返回内容复核（prompt injection 围栏） | 已交付 2026-07-10 | `spec-dp4-mcp-result-guard` |
| E11-D3 | MCP 注入签名全局（home）级入口 | **决策关闭（won't do）** 2026-09-15 | 用户决策：MCP 非必要开发方向 |

---

## E11-D1 FR-3 MCP auto-unregister 评审 6 项 `defer`

- **来源**：step-04 review of `fr3-mcp-auto-unregister`（2026-07-01，blind hunter + edge case hunter + acceptance auditor；AC/约束全通过，1 项 patch 另记 spec）。6 项均 classified `defer`（pre-existing / spec 显式排除 / 非阻塞）。

| # | 发现 | 结论与证据 |
|---|------|-----------|
| a | `__aexit__` 的 `gather(*tasks)` 无超时（`manager.py`）——stdio 子进程忽略 SIGTERM / HTTP 远端不 FIN 时挂死，进程退出无上界 | **已修复**（`spec-mcp-shutdown-timeout`，commit `109df37`）。新增 `_await_shutdown(tasks)`：`asyncio.wait(tasks, timeout=shutdown_timeout)` **两轮**——首轮超时则 WARNING + `task.cancel()` 每个未完成 task（cancel 经 asyncio 注入 `_server_loop` finally，中断挂死的 `cm.__aexit__`），二轮 bounded 再等让被取消 task 的 finally 收尾；二轮仍超时记 ERROR 放弃。**最坏 ~2×`shutdown_timeout` 必返回，绝不无限阻塞**。`shutdown_timeout` 默认 `_DEFAULT_SHUTDOWN_TIMEOUT=5.0`，`<=0` 构造期 raise。采纳「超时即放弃」并细化：用 `asyncio.wait`（done/pending 分离、不自动 cancel、不传播 task 异常）而非 `wait_for(gather)`；且**超时必 cancel**（非 log-and-leave，否则挂死 task 仍阻塞 event loop）；二轮同样 bounded。回归 `tests/test_mcp_manager.py` +4 例 |
| b | `_watch` 两个 `wait_for` 的 `TimeoutError` 同名异义——第一个 =「该 ping 了」、第二个 =「断连」，仅靠 try 块位置区分（未来合并 try 块的重构会碎） | **已修复**（2026-09-15，采纳原建议的「显式分支消歧」支）。新增 `_stop_requested(stop) -> bool`：内部 `wait_for(stop.wait(), timeout=_health_check_interval)` **吞掉自身 `TimeoutError` 返回 False**、收到关停返回 True；`_watch` 改为 `while not stop.is_set(): if await self._stop_requested(stop): return` → 循环体内 `TimeoutError` 只剩「ping 超时 = 断连」一种含义。行为等价。证据：`src/heagent/tools/mcp/manager.py:460,486`；`tests/test_mcp_manager.py::test_stop_requested_true_when_stop_set`、`::test_stop_requested_false_on_timeout`（含「helper 只观察关停信号、绝不自行 set」断言）、`::test_watch_stop_priority_skips_ping`（stop 已 set 时 `_watch` 须立即返回且不 ping，用「ping 即抛」的 session + `wait_for(..., 1.0)` 对 10s interval 反向锁定） |
| c | `_watch` 的 `except Exception` 过宽——任意 `send_ping` 异常（含 SDK 一次性内部错误）一律永久当断连 + 注销 | **保持现状（决策关闭）**（2026-09-15）。除 spec Always 显式接受该保守 fail-safe 外，本轮实测给出「按原建议收窄会变差」的**证据**：stdio transport 的断连主信号是 anyio 的 `ClosedResourceError` / `BrokenResourceError` / `EndOfStream`，三者 MRO 均只到 `Exception`（实测 `issubclass(cls, ConnectionError)` 与 `issubclass(cls, OSError)` **均 False**；httpx `ConnectError` 亦非 `OSError`）→ 按「收窄到连接类异常」处理会**漏掉这些最常见的断连信号**（工具不注销、状态滞留），比现状更坏。原建议后半句（编程错误另走诊断路径）需先有 MCP 重连特性——后置。届时若做，应改为「按异常类型分级**记录** + 一律注销」而非收窄注销条件 |
| d | handler 未把 in-flight `call_tool` 底层异常封 `ToolError`（运行时断连期间已在 in-flight 的调用可能在被 finally 关闭的 session 上抛非 `ToolError` 底层异常并冒泡） | **研究后关闭**（2026-07-10）——**崩溃前提已被 executor 兜底，不再需要代码修复**。`engine/executor.py` 在 handler 调用边界已加 `except Exception`（`_execute_direct` / `_execute_in_sandbox`）→ 任意 `Exception` 子类（含 `anyio.BrokenResourceError`、`ToolError`）均转 `is_error=True` ToolResult，**不冒泡、不崩循环**；调用链无绕过（`_execute_one` → `execute_tool_call` → `loop.engine.executor.execute(handler=...)`，且 `engine` 恒存在）。唯一逸出的是 `CancelledError`/`KeyboardInterrupt`/`SystemExit`（BaseException）——正是取消信号应传播的正确行为。残值仅诊断/契约层面，属与 executor 重复的冗余 try/except→ **不做**（简约至上） |
| e | `_unregister_all` 迭代 `.values()` 后 `.clear()`（隐患：将来在函数中插 `await` 会破不变量） | **核实关闭**（2026-07-11，原描述已过时）。现为快照遍历 `for name in list(self._registered): self._unregister_server(name)`（`manager.py:299`），遍历的是快照副本，即便遍历中 `_registered` 被修改也无「迭代中变更 dict」风险。建议的防御性快照已隐式满足 |
| f | 测试保真度：`test_disconnect_isolated_to_one_server` 未断言 (a) 断连 server task done / (b) transport 已 `__aexit__` / (c) 内置工具保留 | **已关闭**（commit `7131cd0`）。增强为：经 `tracking_transport` 的 finally 置 `closed[name]=True`，断言断连 server 的 transport `__aexit__` 已执行（`closed["a"]`）且另一 server 仍持有（`not closed["b"]`）+ 手动注册非 server 命名空间的内置工具 `search`，断言断连后仍保留。采纳「或」后半支（断言 fake transport `__aexit__`），**不**叠加 `task.done()`——`closed` 标志置位后 task 几乎立即 done，两者在本测试等价，叠加违反简约 |

---

## E11-D2 DP-4 拆分 defer：MCP 返回内容复核（prompt injection 围栏）

- **来源**：DP-4（SafetyGuard 扩展到 MCP）原含「敏感工具确认 / 返回内容复核」两 half；Multi-goal check 判定两者为独立可发布 deliverable（执行前拦截 vs 执行后复核、不同代码位置、各自可独立 PR），`spec-dp4-mcp-safety-guard` 先做执行前拦截 half，复核 half 拆出 defer（2026-07-08）。
- **问题**：MCP 工具返回内容进 LLM 上下文前无围栏——handler `call_tool` 返回直接 `str()` 化进 `ToolResult.content`，prompt injection 无隔离。
- **结论**：**已交付**（2026-07-10，补丁 spec `_bmad-output/patches/mcp/spec-dp4-mcp-result-guard.md`）。`mapping.bridge_result` 返回前对文本跑内置 prompt-injection 启发式正则（ChatML/tokenizer 标记 `<|im_start|>`/`<|im_end|>`/`<|endoftext|>`/`[INST]`/`[/INST]`、`<system>`/`</system>` 标签、`ignore/disregard/forget (all) previous/prior/above instructions/prompts/messages` 短语），命中加 warning 标记后**透传**（`is_error=False`，不阻断、不截断）。**命中语义经用户确认选「标记透传」**——注入与正常内容语义不可区分、纯启发式必有 FP/FN；拦截会 FP 破坏正常 MCP 工具，且与「不宣称防住 injection」立场矛盾。作用点 = `bridge_result`（MCP 返回内容 `str()` 化的唯一 choke point），manager/config 零改动，仅 MCP（内置工具信任模型不同）。
- **证据**：`src/heagent/tools/mcp/mapping.py:105,223`；`tests/test_mcp_mapping.py` 新增 11 例（干净零回归 / 单·多模式命中 / isError 优先 / 非文本块占位符 / 空文本 / 内置全签名参数化 / 变形 FN）。
- **立场**：此层**非真正边界**，标记仅 observable defense-in-depth（审计痕迹 + 对 LLM 可见警告）；FN 变形攻击仍漏过（`test_guard_deformation_not_matched_fn_accepted` 锁定），**须 OS 级沙箱兜底**。

---

## E11-D3 MCP 注入签名全局（home）级入口（决策关闭）

- **来源**：DP-4 第二半遗留项（2026-09-01 登记）。项目级 `.heagent/injection_signatures.json` 入口已交付（`spec-mcp-user-injection-signatures.md`：workspace 围栏、进程级懒加载、畸形条目 fail-safe 逐条跳过并告警）；**全局 / home 级**配置当时 defer。
- **结论**：**决策关闭（won't do，非技术阻塞）**（2026-09-15）。理由三层：
  1. MCP 后续**不再作为 HeAgent 必要开发方向**（CLAUDE.md 已把该入口列在「后续（deferred / future，V2 未做）」，不再排期）；
  2. home 级签名入口会**跨项目静默生效**——注入签名属安全研究知识、非用户该配项（DP-4 第二半 spec 已据此排除用户配置入口），项目级入口已覆盖「某项目要补自家签名」这一真实需求；
  3. 复核确认项目级实现仍是 workspace 围栏 + 进程级缓存 + 畸形条目 fail-safe 逐条跳过告警，无缺陷需修。
- **证据**：`src/heagent/tools/mcp/mapping.py:135`（路径常量 `_USER_SIGNATURES_PATH`）、`::153`（`_load_user_signatures`）。
- **重启条件**：若未来 MCP 重新成为开发方向，可据本条重启（项目级入口可直接扩展为 home 级）。
