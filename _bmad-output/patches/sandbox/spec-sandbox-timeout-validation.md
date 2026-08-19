# Spec：shell/runner timeout 正性校验 + sandbox 测试保真度（D3+D4）

## source
- 路线来源：用户于「bmad 继续开发」方向选择中选定「D3+D4 沙箱硬ening bundle」（一会话一 spec）。
- 根因：`deferred-work.md`「Deferred from: code review of spec-engine-sandbox-backend (2026-07-09)」剩两项：
  - **D3**：`shell(command, timeout=120)` 与 `CommandRunner.run` 全链路不校验 timeout 正性。LLM 传 `timeout=0`/负值 → `asyncio.wait_for(proc.communicate(), timeout=<=0)` 立即 `TimeoutError` → `_kill_and_reap` 一个刚 spawn、尚未真正跑起来的进程，行为不可预期（有效命令被当作超时杀掉，且语义暧昧：`timeout=0` 在某些 API 语境表「无超时」，此处却被当瞬时超时）。
  - **D4**：`test_run_invokes_firejail_with_expected_argv` 的 `_FakeProc.returncode=0` 为类属性 + `communicate` 硬编码返回，`"exit_code=0" in result` 对 fake 恒真，**不验证** `_run_subprocess_exec` 是否正确在 `communicate` 完成后读取 `proc.returncode`——若有人把 `_format_result` 改成 communicate 前读 returncode，此测试仍绿。

## in scope（做）
1. **D3 校验**：`_run_subprocess_shell` / `_run_subprocess_exec` 入口（`tools/sandbox.py`）加 `if timeout <= 0: raise ValueError(...)`（消息含传入的 timeout 值）。两 helper 各一处，同时覆盖 `PassthroughRunner`（经 shell helper）与 `FirejailBackend`（经 exec helper），DRY 单层守卫。
2. **D4 测试保真度**：`tests/test_sandbox.py::test_run_invokes_firejail_with_expected_argv` 的 `_FakeProc` 改 per-instance `returncode`（初始 `None`，`communicate` 内置非零值），断言改 `"exit_code=<非0>" in result`，使 result-shape 断言非同义反复——验证 `_run_subprocess_exec` 读 returncode 的时序正确。
3. **D3 回归测试**：新增 `test_timeout_zero_raises` / `test_timeout_negative_raises`（Passthrough 路径 + 经 mock 的 exec 路径），断言 `<=0` 抛 `ValueError` 且不 spawn 子进程。
4. **文档**：`deferred-work.md` 关闭 D3/D4 两项 Resolution。

## out of scope（不做 / deferred）
- ❌ `@tool` decorator 注入 JSON Schema `minimum`/`exclusiveMinimum` 约束 —— 跨所有工具、改 decorator 公共行为，YAGNI，本次聚焦 shell/runner 入参校验。
- ❌ timeout 钳位（clamp）到默认值 —— 选定 `raise`（见「立场」），不融合两种模式（CLAUDE.md「暴露冲突而非折中」）。
- ❌ D2 进程组 kill（`start_new_session`+`os.killpg`，Linux-only）—— 当前 Windows 开发机无法验证，且 firejail namespace 交互需评估，另记 deferred。
- ❌ `Settings.shell_timeout`（`ge=1`）与工具 `timeout` 默认值 120 的「单一来源」统一 —— 正交，两个值分属 config 与工具签名，本次不动。

## AC（验收）
- **AC1**：`PassthroughRunner().run(cmd, timeout=0)` 与 `timeout=-5` 抛 `ValueError`（消息含传入值），且**不 spawn 子进程**（mock `create_subprocess_shell` 断言未被调用）。
- **AC2**：`FirejailBackend().run` 同样对 `timeout<=0` 抛 `ValueError`（经 `_run_subprocess_exec` 守卫，mock `create_subprocess_exec` 验证不真跑、不被调用）。
- **AC3**：正常 `timeout>0` 行为不变（既有 `test_echo_and_exit_code` / `test_nonzero_exit` / `test_timeout` / firejail argv 测试绿）。
- **AC4**：D4 改造后 `_FakeProc` 为 per-instance returncode、`communicate` 置非零值，断言 `"exit_code=<非0>" in result`——若有人把 `_run_subprocess_exec` 改成 communicate **前**读 returncode（得 `None`/旧值），该测试变红。
- **AC5**：端到端经 executor：shell 工具调 `timeout=0` 时，`ValueError` 被 `ToolExecutor` 的 `except Exception`（`executor.py:133/197`）捕获 → 返回错误 `ToolResult`（content 含 timeout 信息），**不中断 agent 循环**。
- **AC6**：pytest 全绿 / ruff 零新增 / mypy clean。

## 约束（硬）
- DAG：校验放 `tools/sandbox.py`（runner 层），不引入 `engine` 依赖（engine 依赖 tools，反向禁止）。
- 不改 handler 签名：`_invoke`（`tool_execution.py`）用 `fn(**call.arguments)`，加参污染 ToolSchema/LLM 可见性。
- 不改 `@tool` decorator（跨工具公共行为，out of scope）。
- 不新增异常类型：`ValueError` 经既有 `executor` `except Exception` → `ToolResult` 路径，与 MCP config 等 `ToolError`/`ValueError` 既有用法一致。
- 校验在 helper 入口（spawn **之前**）：确保不 spawn 即拒，无竞态 kill。

## 立场（不变）
`timeout <= 0` 是**无效入参**，`raise ValueError`（显性失败）而非静默 clamp 到默认——匹配 `config.py` `shell_timeout: Field(ge=1)` 既有惯例，遵循 CLAUDE.md「显性失败：严禁隐藏错误」。`ValueError` 经既有 `ToolExecutor` `except Exception` → 错误 `ToolResult` 路径回喂 LLM，LLM 据此重试，不引入新语义、不中断循环。

## Review Findings（2026-07-09，bmad-code-review on working-tree D3+D4）

三层对抗式审查（Blind Hunter / Edge Case Hunter / Acceptance Auditor）。**Acceptance Auditor：AC1–AC6 全满足、硬约束无违反、无 out-of-scope 泄漏**（pytest 498 passed / ruff clean / mypy clean 复核）。

dismissed 2 项：guard 层级错位/自定义 runner 绕过（blind，推测性——两具体 runner 均经被守卫的 helper chokepoint，无现存绕过；Protocol 在 Python 无法强制）/ 裸 ValueError 与领域错误分类法（blind，ValueError 对「参数取值非法」语义正确，可争辩非缺陷）。

### patch（4 项，已全部落地）

- [x] [Review][Patch] **D-A timeout 类型/有限性校验**（blind+edge，经用户决定拓宽）：原 `if timeout <= 0` 的 `<=` 对非数值（None/str）抛 TypeError 而非预期 ValueError；`nan <= 0` 恒 False 绕过 → `wait_for(timeout=nan)` 破坏 asyncio timer 堆全序；bool/float/inf 亦绕过 [`src/heagent/tools/sandbox.py`]。修：抽 `_validate_timeout(timeout)`，`isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0` 一律 `raise ValueError`（fail-closed，顺带 dedup 两 helper）。**用户选定「拓宽为正整数校验」**（代价：timeout=None/float 从「能用」变拒绝——None 原是无超时 footgun、float 违反 int 契约，拒绝即执行声明契约；仍在 runner 层，不碰 decorator，不违 spec out-of-scope）。
- [x] [Review][Patch] AC5 端到端 executor 捕获路径零测试（auditor+blind）：新测试都直调 `runner.run()`，无一经 `ToolExecutor`。修：加 `TestExecutorIntegration::test_invalid_timeout_becomes_error_toolresult`，经 executor 驱动 shell(timeout=0) → 断言 `is_error=True` + content 含 timeout。
- [x] [Review][Patch] AC1 测试未锁「消息含传入值」（auditor）：`match="timeout"` 不校验 `got 0`/`got -5`。修：match 收紧为 `r"got 0$"` / `r"got -5$"`。
- [x] [Review][Patch] in-scope #3 exec 负 timeout 路径漏测（auditor）：FirejailBackend 仅 timeout=0。修：加 `TestFirejailBackend::test_timeout_negative_raises_before_spawn`（timeout=-5）。

### defer（1 项，pre-existing adjacent，记 deferred-work.md）

- [x] [Review][Defer] `_kill_and_reap` 在 `except CancelledError` 块内自身抛异常会吞掉原始取消信号（D1 代码，非本 diff） [`src/heagent/tools/sandbox.py:94-96,113-115`] — deferred, pre-existing adjacent。

