# Spec：steering / follow-up 消息队列

## source
- 可行性分析：`docs/piagent-feasibility.md`（2026-08-10）
- 参考实现：Pi（`earendil-works/pi`）`packages/agent/src/agent-loop.ts` 的双层循环设计
- 路线来源：用户选定 P0 优化方向（steering/follow-up 消息队列）

## in scope（做）
1. **`AgentLoop` 增加两个可选 async callback**：`steering_callback: Callable[[], Awaitable[list[Message]]] | None` 和 `follow_up_callback: Callable[[], Awaitable[list[Message]]] | None`，构造参数传入。
2. **双层循环重构**：现有单层 `while True` 改为外层（follow-up）+ 内层（steering/tool 执行）双层。外层在无 follow-up 时退出；内层在每轮 LLM 调用前 poll steering，注入消息后继续。
3. **语义**：
   - **steering**：内层每轮 turn 开始前调用 `steering_callback`，注入的消息作为下一轮 LLM 调用的上下文（用于中断/重定向运行中 Agent）。
   - **follow-up**：内层自然退出（无 tool_calls）后调用 `follow_up_callback`，有消息则注入并继续外层循环（用于自动接续已完成的任务）。
4. **`run()` / `run_stream()` 双路径**：两层循环逻辑提取为私有方法 `_run_loop`，供 `run()` 和 `run_stream()` 复用，避免代码重复。
5. **测试**：`tests/test_steering_followup.py` — 验证 steering 注入后 LLM 响应变化、follow-up 自动接续、空回调无影响。

## out of scope（不做 / deferred）
- ❌ follow-up 自动循环的深度限制（当前依赖 `max_iterations` 全局上限即可，不额外加 follow-up 专属计数器）。
- ❌ steering 消息与 tool 执行并发的竞态处理——steering 只在 turn 边界 poll，不存在竞态。
- ❌ 持久化 steering/follow-up 队列——消息注入即消费，不跨 run 恢复。
- ❌ CLI 交互式 steering（REPL 中实时输入中断）——仅定义 API，CLI 接入为后续工作。

## AC（验收）
- **AC1**：steering：Agent 运行中，`steering_callback` 在每轮 LLM 调用前被调用，返回的消息注入到下一轮上下文。LLM 的下一轮回答体现 steering 指令。
- **AC2**：follow-up：Agent 完成当前任务（无 tool_calls）后，`follow_up_callback` 被调用；返回消息则自动接续新一轮 LLM 调用。
- **AC3**：空回调无影响：`steering_callback=None` 和 `follow_up_callback=None` 时，循环行为与现有完全一致（零回归）。
- **AC4**：流式路径同样支持：`run_stream()` 走相同的双层循环逻辑。
- **AC5**：steering 不覆盖 assistant 响应：steering 消息以 `role=USER` 注入，保留上一轮 assistant 回答在上下文中。
- **AC6**：pytest 全绿 / ruff 零新增 / mypy clean。

## 约束（硬）
- steering/follow-up 回调签名固定为 `async () -> list[Message]`，不传 state/run_context（保持回调简单、可测试）。
- 双层循环不改变现有 `_call_provider` / `_execute_tools` / `_maybe_compress` / `_maybe_window_reset` / `_checkpoint` 的调用语义。
- `run()` 和 `run_stream()` 共享同一套 `_run_loop` 实现（模板方法模式，`_emit_text` / `_append_assistant` / `_execute_tools_handler` 作为差异注入）。

## 立场（不变）
此特性增加交互灵活性，不改变 HeAgent 的安全边界声明——steering/follow-up 消息来自调用方（信任边界内），不引入新的攻击面。
