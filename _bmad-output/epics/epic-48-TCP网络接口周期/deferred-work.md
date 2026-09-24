# Epic 48 TCP 网络接口周期遗留项台账（deferred-work）

> **归并来源**：`implementation-artifacts/deferred-work-archive.md` 的 **Z-D10 / Z-D11**（两条均出自本周期 **Story 48-5** 收口评审 C-1 / C-2）；2026-09-24 按「**条目闭合后按归属 epic 归档**」规则从活动台账的闭合归档区回填至本文件。
> **归档规则**：按条目**归属的 epic** 归档；「闭合者」注明实际完成它的批次 / commit。
> **只登记已闭合项**——原始长文历史不再保留，结论全部指向代码与测试。
> **活动（未闭合）遗留项**仍在 [`implementation-artifacts/deferred-work-archive.md`](../../implementation-artifacts/deferred-work-archive.md)（工作流 append-only 入口）——本周期相关未闭合条目 = 台账编号 **A7「TCP 入口不写 rollout」**（`EVENTS_ROLLOUT_ENABLED` 对 `tcp-server` 是死开关），正文以台账为准。

## 状态总览

| ID | 归属 | 条目 | 状态 | 闭合者 |
|----|------|------|------|--------|
| Z-D10 | Epic 48 · Story 48-5 评审 C-1 | 运行栈日志的观测故障免疫 | 已闭合（2026-09-23） | 可观测性与日志卫生批次（`safe_log` 逐调用点 + 进程级 `install_logging_fault_guard`） |
| Z-D11 | Epic 48 · Story 48-5 评审 C-2 | 日志行的凭证脱敏 | 已闭合（2026-09-23） | 同批次（`LoggingObserver` 掩码 `target` / `details`） |

---

## Z-D10 运行栈日志的观测故障免疫

- **来源**：Epic 48 Story 48-5 评审 C-1（2026-09-22）；`docs/frame.md` 五原「运行栈日志非『观测故障免疫』」。
- **问题**：`logging` 的 `Handler.handle` **不**捕获 `emit` 抛出的异常（与 `logging.raiseExceptions` 取值无关，实测：自定义 handler 两种情况都传播；stdlib handler 走 `handleError` 故不传播）。于是第三方/自定义 handler 一旦在 `emit` 中抛错，运行栈**任意** `logger.*` 调用都会上抛——一次 run 里的进度日志（如 `Calling provider: …`）就能把成功的运行变成失败。
- **原始登记（2026-09-22，来源 = Epic 48 Story 48-5 评审 C-1）**：触发条件 = 第三方 / 自定义 logging handler 在 `emit` 中抛异常；严重度 低-中；冻结边界 = 给运行栈加安全日志**不得改变既有日志文案与级别**，也**不得吞掉业务异常**（异常仍须抵达调用方）；实证探针 `.heagent/tmp/probe_raise_exceptions.py`（实测证明 `logging.raiseExceptions=False` 拦不住）；同记于 `docs/frame.md` 五「运行栈日志非『观测故障免疫』」行。
- **结论**：**已闭合**（2026-09-23，可观测性与日志卫生批次）。两层防线：
  1. **逐调用点** `safe_logging.safe_log`：插桩与 best-effort 路径（`EventBus.emit` 观察者兜底、`LoggingObserver`、`ToolExecutor._emit_tool_event`、`WorkflowRunner._emit_step_event`、ledger 三处旁路告警、run 快照落盘告警、`AgentLoop._emit`）全部改走它；`network/tcp_server.py` 与 `cli_tcp.py` 各自的 `_safe_log` 收敛为它的薄封装（调用点零改动）。
  2. **进程级** `safe_logging.install_logging_fault_guard()`：把 `logging.Handler.handle` 包一层，失败仍调 stdlib `handleError`（照旧按 `raiseExceptions` 打印 `--- Logging error ---` 与 traceback，故「不抛」不等于「无声」）但不传播；由 CLI `_setup_logging()`（TCP 入口复用同一函数）与 `gui/cli.py` 在配置 logging 时安装。逐调用点收口只能覆盖「记得改」的地方，运行栈进度日志数量多且会新增，故必须有这一层。
- **证据**：`tests/test_safe_logging.py` 34 例——含两个**对照** e2e（装守卫时坏 handler 不影响 run；显式拆守卫时同一 run 抛 `RuntimeError`，证明守卫承重）、守卫幂等、诊断不被吞。负向验证：把 `LoggingObserver.handle`/`EventBus.emit`/`AgentLoop._emit` 三处守卫同时还原 → e2e 复现失败；还原后按 sha256 逐字节复位。
- **残留（如实标注）**：守卫安装前打的日志、或宿主自行把 `Handler.handle` 还原成 `safe_logging.ORIGINAL_HANDLER_HANDLE`（公开常量，供想自行掌控 logging 语义的 embedder 使用）时不在保证内。

## Z-D11 日志行的凭证脱敏

- **来源**：Epic 48 Story 48-5 评审 C-2（2026-09-22）；`docs/frame.md` 五原「TCP 日志含工具摘要」。
- **问题**：入口复用 `EngineContainer.default` ⇒ 默认 `LoggingObserver` 在 INFO 打印 `tool=… target=…`，而 `shell` 的 target **不截断**（`call_summary._NO_TRUNCATE_TOOLS`，审查需要原文）：路径与命令原文（可能含 `API_KEY=…` 等凭证串）会进 `logs/heagent-*.log`。
- **原始登记（2026-09-22，来源 = Epic 48 Story 48-5 评审 C-2；属既有引擎行为，非 Epic 48 引入）**：触发条件 = 任意入口执行含凭证的 shell 命令；严重度 低-中；冻结边界 = 脱敏**不得改变工具摘要对用户的既有语义与可观测字段集**，且脱敏仍非安全边界（`README` 已提示「不要把凭证写进命令或路径」）；同记于 `docs/frame.md` 五「TCP 日志含工具摘要」行。
- **结论**：**已闭合**（2026-09-23，同一批次）。`LoggingObserver` 打印前对 `target` 与 `details` 掩码：`redact_secrets`（键值形态 / CLI 旗标 / 厂商前缀 `sk-`·`ghp_`·`AKIA`·`AIza`·JWT / `Bearer` / URL userinfo）+ `redact_details`（按键名掩码，覆盖 `{"secret": "x"}` 这类无形状可认的短值；浅层遍历、深度上限 3）。选择**掩码而非截断**：`shell` 命令结构对审查有价值，不该丢；也不依赖调用方自觉。
- **证据**：`tests/test_safe_logging.py` 的参数化用例（12 种凭证形态逐个掩码、7 类普通文本零误伤、幂等）+ `LoggingObserver` 经 caplog 断言日志行不含原文。
- **边界（如实标注）**：模式匹配**非完备**，必有漏网形态；`shell` target 仍不截断；`logs/`、`.heagent/runs/`（run 快照与 rollout JSONL）按设计保存完整 prompt 与消息，**不在**本次覆盖内——仍须 OS 级沙箱兜底并避免把凭证写进命令或路径。
