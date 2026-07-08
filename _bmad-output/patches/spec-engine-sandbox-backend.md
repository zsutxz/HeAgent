# Spec：engine sandbox 接真实后端（通用 CommandRunner）

## source
- plan：`C:\Users\skype\.claude\plans\cosmic-leaping-hopper.md`（用户批准 2026-07-08）
- 路线来源：用户于「bmad 继续开发」方向选择中选定「通用 CommandRunner 重构」（`docs/iteration.md` 第四章候选方向）
- 根因：`ToolExecutor.execute_in_sandbox()` 默认透传（`frame.md` 4.12 已知缺口）。`handler` 是 in-process async 闭包，OS 沙箱只能隔离**子进程**；全项目 grep 确认仅 `shell.py` spawn 子进程（`create_subprocess_shell`），其余工具是宿主进程内 Python I/O，沙箱对它们无意义。

## in scope（做）
1. **新 `src/heagent/tools/sandbox.py`**：`CommandRunner` Protocol（`async run(command, *, timeout) -> str`）+ `PassthroughRunner`（搬 shell 现有逻辑）+ `FirejailBackend`（`create_subprocess_exec`，exec 非 shell）+ RuntimeSlot 注入（`configure_command_runner` / `bind_command_runner` / `get_command_runner`，默认 Passthrough 单例）。
2. **`shell.py`** 走 `get_command_runner().run(...)`（默认 Passthrough → DIRECT 行为不变）。
3. **`executor.py`**：`ToolExecutor.__init__(*, sandbox_runner=None)`；`execute_in_sandbox` 默认实现 `if runner: with bind_command_runner(runner): await handler(call) else: await handler(call)`（无 runner 透传 + 子类化兼容）。
4. **`container.py`**：`EngineContainer.command_runner` 字段 + `__post_init__` 把 runner 注入 `executor.sandbox_runner`。
5. **测试**：新 `tests/test_sandbox.py` + 改 `tests/test_shell.py` + 改 `tests/test_engine_p0.py`。
6. **文档**：`frame.md` 4.12 + 已知缺口、`CLAUDE.md` 安全声明、`iteration.md` 时间线。

## out of scope（不做 / deferred）
- ❌ Settings / CLI 配置入口（`sandbox_backend="firejail"`）—— YAGNI，手动装配即可验证。
- ❌ profile → firejail 参数映射（profile-aware backend）—— 单 backend，YAGNI。
- ❌ MCP server / cron 子进程接入 runner —— 唯一 spawn 子进程者是 shell；未来接入走同一 runner，本次不铺。
- ❌ CI 真跑 firejail integration —— Windows/CI 不保证 firejail 可用；FirejailBackend 仅 mock argv 验证。
- ❌ `roles.py` `sandbox_profile` 死字段接线 —— 正交，不动。

## AC（验收）
- **AC1**：shell DIRECT 路径行为不变（默认 Passthrough，`test_shell.py` 现有断言绿）。
- **AC2**：`PassthroughRunner.run` 等价原 shell（exit_code/stdout/stderr 格式 + 超时分支）。
- **AC3**：`FirejailBackend.run` argv = `[firejail, *extra_args, "--", "sh", "-c", command]`（mock `create_subprocess_exec` 验证，不真跑）。
- **AC4**：`SANDBOX_REQUIRED` + `ToolExecutor(sandbox_runner=RecordingRunner)` → executor bind 后 shell handler 取到 RecordingRunner（端到端注入链路）。
- **AC5**：DIRECT 路径不污染（shell 取默认 Passthrough，即使同批并发有 SANDBOX call）。
- **AC6**：子类化 `execute_in_sandbox` 契约不破（`test_custom_executor_can_override_sandbox_backend` 绿）。
- **AC7**：SubAgent 经 `replace(engine, policy=...)` 继承父 `command_runner`（executor 引用不变）。
- **AC8**：pytest 全绿 / ruff 零新增 / mypy clean。

## 约束（硬）
- handler 签名不可改：`_invoke`（`tool_execution.py:144`）用 `fn(**call.arguments)`，加参污染 ToolSchema/LLM 可见性。
- DAG：engine 依赖 tools，tools 禁止依赖 engine → `CommandRunner` 必须放 `tools/` 层。
- 注入走 RuntimeSlot（`tools/runtime.py`），项目既有 DI 惯例（memory/skills/cron/subagent/workspace_root）。
- 并发隔离：`execute_tools` 的 `asyncio.gather` 每 task 拷贝 contextvar → executor `with bind` 只对该 call 可见。

## 立场（不变）
FirejailBackend 交付后 `SANDBOX_REQUIRED` **对 shell 子进程**产生 OS 级隔离效果，但：(a) 仅 shell，file/memory 等仍无隔离；(b) firejail 非完美边界（可被绕过）；(c) Linux-only，Windows 开发机/CI 无法真跑；(d) 仍须整体在 OS 级沙箱内运行。**不制造「接了 firejail 就安全」假象。**
