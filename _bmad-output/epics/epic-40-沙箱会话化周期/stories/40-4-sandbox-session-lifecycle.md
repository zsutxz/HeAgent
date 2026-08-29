---
title: 'Story 40.4: SandboxSession 会话生命周期（FR-4）'
type: 'feature'
created: '2026-08-26'
status: 'done'
epic: 40
story: '40-4'
context:
  - '{project-root}/_bmad-output/epics/epic-40-沙箱会话化周期/epic-40-context.md'
---

## Intent

**Problem:** `execute_in_sandbox` 是无状态逐命令包装——每条 shell 命令新起子进程，cwd 不跨命令保持（`cd sub && touch a` 后下一条 `pwd` 回到 workspace 根），多步操作（写→编译→运行）无法自然衔接；会话目录在 run 结束后无人清理。

**Approach:** 引入 `SandboxSession` 会话作用域：封装 session workspace（40.1 目录）+ cwd 跨命令状态；`run()` 以「cd 前缀 + 尾捕获 `$PWD`/`%CD%`」包装命令实现 cwd 保持；`close()` 按配置清理会话目录（保留/删除）。shell handler 改用会话执行，`execute_in_sandbox` 绑定会话；run 结束（finally）触发 teardown。

## Boundaries & Constraints

**Always:**
- 工具执行链 `PolicyEngine.evaluate() → ToolExecutor → SafetyGuard.check() → handler` 形态不变。
- 会话**非安全边界**：WinJob 仅目录约定、Firejail `--private` 非完美边界——须 OS 级沙箱兜底（NFR-1）。
- 未启用 `sandbox_session_workspace`（开关关）时行为与现状逐字节一致（不建会话、不包装命令）。
- `SANDBOX_REQUIRED` 但未注入 runner 时既有 fail-safe 透传报错语义不变。
- 会话目录清理复用既有孤儿进程防护（Firejail killpg / WinJob KILL_ON_JOB_CLOSE 已在每次 `run()` 生效）。

**Ask First:**
- 若需改 `AgentLoop.run`/`run_stream` 核心循环（而非仅 `_persist_and_cache` 收尾）——停下询问。

**Never:**
- 不实现 crash 孤儿目录 GC/保留策略（deferred，40.4 teardown 只覆盖正常结束路径）。
- 不给 WinJob 补 env scrub（40.3 scope 外，既有缺口）。
- 不实现持久 shell 进程（每次命令仍是独立子进程，cwd 靠「cd 前缀 + 尾捕获」回填）。

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior |
|----------|--------------|---------------------------|
| 会话初始 cwd | 新建 SandboxSession(workspace) | `cwd == workspace` |
| cwd 保持 | `run("cd sub && touch a")` 后 `run("pwd")` | 第二条 cwd = `<workspace>/sub`，`a` 可见 |
| 开关关 | 无 `sandbox_workspace` metadata | 不建会话、命令不包装、行为与现状一致 |
| 无 runner | `SANDBOX_REQUIRED` 且 runner=None | 既有透传 warning 语义不变 |
| teardown 删除 | run 结束 + keep=False（默认） | session 目录被 rmtree |
| teardown 保留 | run 结束 + keep=True | session 目录保留 |
| 命令失败仍捕获 cwd | `run("cd sub && false")` | cwd 仍更新为 `<workspace>/sub` |

## Code Map

- `src/heagent/tools/sandbox.py` — 新增 `SandboxSession`（`_wrap` / `run` / `close`）+ `bind/get/reset_sandbox_session` contextvar + 模块级 session 缓存。
- `src/heagent/engine/executor.py` — `execute_in_sandbox` 绑定 SandboxSession（按 run_id 复用）。
- `src/heagent/tools/builtins/shell.py` — handler 优先走 session。
- `src/heagent/engine/container.py` — `close_run(run_context)` teardown 入口 + session 缓存。
- `src/heagent/config.py` — `sandbox_session_keep: bool = Field(default=False)`。
- `src/heagent/agent/loop.py` — `_persist_and_cache` 尾部调 `engine.close_run`。
- `docs/frame.md` / `CLAUDE.md` — FR-4 文档同步。

## Tasks & Acceptance

**Execution:**
- [x] `src/heagent/tools/sandbox.py` — `SandboxSession` 类 + contextvar + 缓存
- [x] `src/heagent/engine/executor.py` — 会话绑定
- [x] `src/heagent/tools/builtins/shell.py` — 会话执行
- [x] `src/heagent/engine/container.py` — `close_run` + 缓存
- [x] `src/heagent/config.py` — `sandbox_session_keep`
- [x] `src/heagent/agent/loop.py` — `_persist_and_cache` teardown
- [x] tests — 会话语义 + teardown + 回归
- [x] docs — frame.md + CLAUDE.md

**Acceptance Criteria:**
- Given 同一 run 的先后两条命令，When 第二条执行，Then 复用同一会话（同一 workspace；Firejail 下同一 `--private` 视图）
- Given 第一条 `cd sub && touch a`，When 第二条 `pwd && ls`，Then cwd 保持在 `sub` 且 `a` 可见
- Given run 结束（正常/异常/取消），When teardown，Then 会话目录按配置清理（保留/删除），无孤儿进程
- Given `SANDBOX_REQUIRED` 但未注入 runner，When 执行，Then 既有 fail-safe 报错语义不变
- And 工具执行链形态不变 + 文档同步（NFR-1 非真边界立场）

## Verification

**Commands:**
- `pytest tests/test_sandbox.py tests/test_engine_p0.py tests/test_winjob_backend.py tests/test_credential_guard.py -q` — 结果（2026-08-26，Windows）：**196 passed, 1 skipped**
- `ruff check src` — 结果：**All checks passed**（`test_plan_mode.py:76` E501 为基线既有，非本变更引入）
- `mypy src` — 结果：**Success, no issues found in 92 source files**

## Spec Change Log

- 2026-08-26 迭代1（实现中 review，3 patch）：
  - **cmd 的 `%CD%` 在 `cmd /c` 解析阶段就展开**（拿到的是进程启动 cwd 而非 cd 后目录）——真实 shell 测试暴露。修复：cmd 尾捕获改用无参 `cd` 输出当前目录，marker 改为「单独一行 + 路径行」格式（POSIX `printf "\nMARKER\n%s\n"` / cmd `echo MARKER & cd`），`_extract_cwd`/`_strip_marker` 相应改为「marker 行后一行是路径」。
  - **mypy union-attr**：`run_context.run_id` 在 `workspace` 非 None 分支仍被 mypy 视作可 None——用 `if workspace is None or run_context is None` 收窄类型（同时避免 bandit S101 assert）。
  - **测试跨平台**：`pwd && ls` 为 POSIX-only，Windows cmd 不识别——改为 `mkdir sub && cd sub && echo hi > a` + 断言 `session.cwd == tmp_path/sub` 与文件落点（mkdir/cd/echo 为 cmd 与 sh 通用）。
