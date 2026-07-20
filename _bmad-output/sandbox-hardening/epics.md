---
stepsCompleted: ["step-01-requirements-extraction", "step-02-design-epics", "step-03-create-stories", "step-04-final-validation"]
inputDocuments:
  - _bmad-output/sandbox-hardening/brief.md
  - _bmad-output/sandbox-hardening/prd.md
  - _bmad-output/sandbox-hardening/ARCHITECTURE-SPINE.md
cycle: sandbox-hardening
project: HeAgent
---

# HeAgent Sandbox 硬化 — Epic Breakdown

> 本文档把 Sandbox 硬化周期（profile 映射 / 配置入口 / 进程组 kill / workspace 隔离 / 可观测）
> 的 PRD FR/NFR 与架构承重决策（AD）分解为可实现的 story。FR 编号与 PRD `FR-S*` 对齐；
> AD 编号与 `ARCHITECTURE-SPINE.md` 对齐。

## Overview

本轮把 HeAgent 既有沙箱管道从「空壳」填成「真正可用」——让 `sandbox_profile` 从死字段变为
活的 firejail 参数映射，让普通用户能通过 `.env` / CLI 启用沙箱，让 firejail 不可用时优雅降级。

## Requirements Inventory

### Functional Requirements

> verbatim 自 `prd.md` §4。

- **FR-S1: FirejailBackend 按 profile 名映射 firejail 参数** — 构造时接受 `profiles: Mapping[str, Sequence[str]]`；`run()` 内查 profiles dict 取对应参数；profile 名不存在时仅用 `extra_args`（不抛错）。
- **FR-S2: ToolExecutor.execute_in_sandbox 传递 profile 到 CommandRunner 上下文** — 新增 `bind_sandbox_profile` contextmanager + `get_sandbox_profile`；executor 在 handler 调用前注入 profile。
- **FR-S3: firejail 可用性检测 + 优雅降级** — `FirejailBackend.__init__` 中 `shutil.which` 检测；不可用时 warn + `run()` 降级 Passthrough；`.available` 属性暴露结果。
- **FR-S4: .env / CLI 配置入口** — `Settings` 新增 `sandbox_backend` + `sandbox_firejail_path`；CLI 新增 `--sandbox` flag；`EngineContainer.default()` 自动构造 runner。
- **FR-S5: Linux 进程组 killing** — `_run_subprocess_shell/exec` 传 `start_new_session=True`（Linux only）；`_kill_and_reap` 用 `os.killpg` 替代 `proc.kill()`（Linux only）。
- **FR-S6: FirejailBackend 自动映射 workspace_root 为 --private** — `FirejailBackend.__init__` 接受 `workspace_root`；非空时在 argv 中生成 `--private=<ws>` 参数。
- **FR-S7: executor emit 事件新增 sandbox_backend + sandbox_pid** — 四类 emit 事件的 details dict 新增两个字段；PID 经专用 contextvar 在 handler 执行后回填。

### Non-Functional Requirements

> 自 `prd.md` §5。

- **NFR-S1: 零回归** — DIRECT 路径 + PassthroughRunner 行为不变；全部 727 测试保持绿；ruff/mypy clean。
- **NFR-S2: 安全声明诚实** — `CLAUDE.md` / `docs/frame.md` 更新；Firejail 仍非完美边界。
- **NFR-S3: 平台透明** — Windows/macOS 无 firejail 时优雅降级、不 crash。
- **NFR-S4: 确定性单测** — profile→args 映射为纯函数、不入子进程、不触达 LLM。
- **NFR-S5: 模块边界** — 改动限 `tools/sandbox.py` + `engine/executor.py` + `config.py` + `cli.py` + `container.py`；不反依赖 agent/providers/memory。
- **NFR-S6: 测试覆盖** — 每个 FR 至少 1 个独立单测 + 1 个集成测试。

### Additional Requirements (Architecture Decisions)

> 自 `ARCHITECTURE-SPINE.md` 承重决策 AD-S1~AD-S7，影响实现的硬约束。

- **AR-1 (AD-S1):** profile → args 映射在 `FirejailBackend` 内部，不扩 `CommandRunner` Protocol 签名。`_build_argv` 纯函数可独立单测。
- **AR-2 (AD-S2):** profile 经 `bind_sandbox_profile` contextvar 注入（与既有 `_command_runner_slot` 同构），不混入 `CommandRunner.run` 签名。
- **AR-3 (AD-S3):** firejail 不可用时 `FirejailBackend.run()` 降级 Passthrough，不抛异常。
- **AR-4 (AD-S4):** `EngineContainer.default()` 读 Settings 自动构造 runner；CLI flag 优先于 `.env`；`SANDBOX_BACKEND=passthrough` 时 runner 为 `None`（保留快速路径）。
- **AR-5 (AD-S5):** `sys.platform == "linux"` 守卫进程组 killing；非 Linux 路径零改动。
- **AR-6 (AD-S6):** `FirejailBackend.__init__` 接受 `workspace_root`；非空时 `--private=<ws>` 插在 `extra_args` 与 `profile_args` 之间。
- **AR-7 (AD-S7):** emit 事件新增字段从 contextvar 读取，不扩 `ToolResult` / handler 返回值。
- **AR-8 (Stack):** 不新增运行时依赖；Python 3.11+；Pydantic v2。
- **AR-9 (NFR-S1/S6):** 零回归护栏覆盖 727 现有测试 + 每 FR 新单测 + 集成测试。

### UX Design Requirements

本轮无 UI/UX 表面——HeAgent 是后端库 + CLI。`--sandbox` CLI flag 是标准 click option，无 UX spine 设计契约。

### FR Coverage Map

> 7 个 FR 全覆盖。字母前缀对应 PRD。

- **FR-S1** (FirejailBackend profile 映射) → Epic S1
- **FR-S2** (executor profile 注入) → Epic S1
- **FR-S3** (firejail 可用性检测 + 降级) → Epic S2
- **FR-S4** (.env/CLI 配置入口) → Epic S2
- **FR-S5** (Linux 进程组 killing) → Epic S3
- **FR-S6** (workspace_root --private) → Epic S3
- **FR-S7** (emit 事件扩展) → Epic S4

## Epic List

### Epic S1: Profile-aware sandbox — 让 sandbox_profile 活起来

把 `sandbox_profile` 从死字段变成活的 firejail 参数映射。`FirejailBackend` 接受 `profiles` dict +
经 contextvar 注入 profile 名 + executor 管道传递。完成后 `RoleSpec.sandbox_profile="network-isolated"`
真正产生 `--net=none` 等隔离效果——**本轮核心价值**。

**FRs covered:** FR-S1, FR-S2
**实现落点:** AD-S1 (`FirejailBackend` profiles + `_build_argv`) + AD-S2 (`bind_sandbox_profile` contextvar
+ `ToolExecutor.execute_in_sandbox` 注入)。改 `tools/sandbox.py`（FirejailBackend 新构造参数 +
`get_sandbox_profile` 调用 + `_build_argv` 纯函数）+ `engine/executor.py`（`execute_in_sandbox` 加
`bind_sandbox_profile` 包裹）。
**独立性:** ✅ 无前置依赖。Epic S1 可独立交付核心价值。

### Epic S2: 可用性 & 配置入口 — 让普通用户能用

firejail 不可用时优雅降级（不崩溃）+ `.env` / CLI 入口让用户一行配置即可开启沙箱。
完成后用户只需 `--sandbox firejail` 即可启用，无需写 Python 代码。

**FRs covered:** FR-S3, FR-S4
**实现落点:** AD-S3 (`shutil.which` 检测 + `FirejailBackend.run` 降级) + AD-S4 (`Settings` 新字段
+ CLI `--sandbox` + `EngineContainer.default()` 自动构造)。改 `tools/sandbox.py`（降级逻辑 +
`.available` 属性）+ `config.py`（Settings 新字段）+ `cli.py`（`--sandbox` option）+
`engine/container.py`（`default()` 读 Settings 自动构造 runner）。
**独立性:** ⚠️ 依赖 Epic S1（`FirejailBackend` 新构造参数已存在，`EngineContainer.default()` 需传入
`workspace_root`→依赖 S1 引入的构造参数）。建议在 S1 完成后做。

### Epic S3: 纵深加固 — 进程组 killing + workspace 文件系统隔离

Linux 上子进程 timeout/cancel 时整进程组全杀（不留孤儿） + FirejailBackend 自动把
workspace_root 映射为 `--private` 参数（OS 级文件系统隔离，补充 Python 逻辑围栏）。

**FRs covered:** FR-S5, FR-S6
**实现落点:** AD-S5 (`sys.platform` 守卫 + `os.killpg` in `_kill_and_reap` + `start_new_session`
in `_run_subprocess_*`) + AD-S6 (`FirejailBackend.__init__` workspace_root + `--private` 插入
`_build_argv`)。改 `tools/sandbox.py`（两个 helper + `_kill_and_reap` + `_build_argv` 扩展）。
**独立性:** ✅ 无 Epic S2 依赖；`_build_argv` 依赖 S1 引入，但与 S2 并行可做。

### Epic S4: 可观测 & 文档收尾

executor emit 事件标注沙箱后端类型 + firejail PID；安全声明文档同步。

**FRs covered:** FR-S7, NFR-S2
**实现落点:** AD-S7（`_sandbox_pid_slot` contextvar + executor emit 扩展）+ NFR-S2（CLAUDE.md /
frame.md / iteration.md 更新）。改 `engine/executor.py`（emit 事件 details）+ `tools/sandbox.py`
（`_sandbox_pid_slot`）+ 三文档。
**独立性:** ⚠️ 依赖 S1+S2+S3（emit 事件的 `sandbox_backend` 字段依赖 S2 的 `FirejailBackend` 构造；
PID 依赖 S1/S3 的 `_run_subprocess_*` 执行链路）。建议最后做。

---

## Epic S1: Profile-aware sandbox — 让 sandbox_profile 活起来

tan 在代码里声明 `RoleSpec(sandbox_profile="network-isolated")`，启动 agent 后 agent 调 shell——
firejail 实际收到 `--net=none` 参数。这是本轮核心价值：**profile 死字段激活**。

### Story S1-1: FirejailBackend 支持 profiles dict + _build_argv 纯函数

As a HeAgent 开发者,
I want `FirejailBackend` 接受 `profiles` dict 并按 profile 名映射 firejail 参数,
So that 不同 profile 能产生不同的 firejail 隔离效果。

**Acceptance Criteria:**

**Given** `FirejailBackend` 构造参数新增 `profiles: Mapping[str, Sequence[str]]`（默认空）
**When** 构造 `FirejailBackend(profiles={"default": ("--private-tmp",), "network-isolated": ("--net=none",)})`
**Then** `self._profiles` 存为 dict

**Given** `_build_argv(command, profile, workspace_root=None)` 纯函数
**When** `profile="network-isolated"` 且该 profile 在 profiles dict 中
**Then** 返回的 argv 列表包含 `["firejail", "--", "sh", "-c", command]` + `("--net=none",)` 在 `"--"` 之前
**And** 函数为纯函数——无 I/O、无 contextvar、无外部状态

**Given** `profile` 不在 `profiles` dict 中（或 `profiles` 为空 dict）
**When** 调用 `_build_argv`
**Then** 仅返回 `extra_args`（不含 profile 专用参数），不抛错

**Given** `FirejailBackend.run(command, *, timeout)` 调用
**When** 当前 contextvar `get_sandbox_profile()` 返回 `"network-isolated"`
**Then** `run()` 内部调 `_build_argv` 取到含 `("--net=none",)` 的 argv → 传给 `_run_subprocess_exec`

### Story S1-2: ToolExecutor.execute_in_sandbox 注入 profile contextvar

As a HeAgent 开发者,
I want `ToolExecutor.execute_in_sandbox` 把 `profile` 参数注入 contextvar,
So that `FirejailBackend.run` 内能通过 `get_sandbox_profile()` 取到当前调用的 profile 名。

**Acceptance Criteria:**

**Given** `tools/sandbox.py` 新增 `_sandbox_profile_slot: RuntimeSlot[str | None]`
**When** 调用 `bind_sandbox_profile("network-isolated")` 进入 context
**Then** `get_sandbox_profile()` 返回 `"network-isolated"`；退出 context 后恢复原值

**Given** `ToolExecutor.execute_in_sandbox` 签名不变（`call, profile, handler`）
**When** 执行时 `profile` 不为 None
**Then** handler 调用包在 `bind_command_runner(...)` 和 `bind_sandbox_profile(profile)` 双层 context 内

**Given** `profile=None` 传入
**When** `execute_in_sandbox` 执行
**Then** `get_sandbox_profile()` 返回 `None`（PassthroughRunner 不读取此值，不受影响）

**Given** `PassthroughRunner.run()` 
**When** 上下文中有 `bind_sandbox_profile("x")`
**Then** PassthroughRunner 行为完全不变（不调用 `get_sandbox_profile()`）——**零回归**

---

## Epic S2: 可用性 & 配置入口 — 让普通用户能用

用户一行 `.env` 或一个 CLI flag 即可启用 firejail；没装 firejail 时优雅降级不崩溃。

### Story S2-1: FirejailBackend 可用性检测 + 优雅降级

As a HeAgent 操作者,
I want firejail 不可用时 agent 能优雅降级继续工作,
So that 我不因为机器没装 firejail 而整个 agent 崩溃。

**Acceptance Criteria:**

**Given** `FirejailBackend.__init__` 中 `shutil.which(self._firejail_path)` 返回 `None`（firejail 不可用）
**When** 构造实例
**Then** `self._firejail_available` 为 `False`，且记一条 `logger.warning("firejail not found at %r, sandbox disabled — falling back to passthrough", path)`
**And** `self.available` 属性返回 `False`

**Given** `self._firejail_available` 为 `False`
**When** 调用 `FirejailBackend.run("echo hi", timeout=10)`
**Then** 内部走 `PassthroughRunner().run("echo hi", timeout=10)`——不尝试启动 firejail、不抛异常
**And** `echo hi` 正常执行，返回 `exit_code=0`

**Given** `shutil.which` 返回非空路径（firejail 可用）
**When** 构造实例
**Then** `self._firejail_available` 为 `True`，`run()` 走正常 firejail 路径

**Given** `SANDBOX_BACKEND=firejail` 但 firejail 不可用
**When** 一次完整的 agent run 中调 shell
**Then** shell 正常完成（Passthrough）、不炸 agent 循环——**降级不中断**

### Story S2-2: .env / CLI 配置入口 + EngineContainer.default() 自动构造 runner

As a HeAgent 操作者,
I want 通过 `.env` 变量或 CLI flag 启用 firejail 沙箱,
So that 我不需要写 Python 代码就能开启沙箱功能。

**Acceptance Criteria:**

**Given** `Settings` 新增字段：
- `sandbox_backend: Literal["passthrough", "firejail"] = "passthrough"`（来自 `SANDBOX_BACKEND` env）
- `sandbox_firejail_path: str = "firejail"`（来自 `SANDBOX_FIREJAIL_PATH` env）

**When** `.env` 中 `SANDBOX_BACKEND=firejail`
**Then** `get_settings().sandbox_backend` 为 `"firejail"`

**Given** CLI `main()` 新增 `--sandbox` option（`click.Choice(["passthrough", "firejail"])`，默认 `"passthrough"`）
**When** `heagent --sandbox firejail "echo hi"`
**Then** CLI flag 覆盖 `.env` 的 `SANDBOX_BACKEND` 值（CLI 优先）

**Given** `EngineContainer.default(workspace_root="...")` 
**When** 最终生效的 `sandbox_backend` 值为 `"passthrough"`
**Then** `command_runner=None`（保持 `execute_in_sandbox` 的 `if None` 快速路径）

**Given** `sandbox_backend` 为 `"firejail"`
**When** `EngineContainer.default()` 构造
**Then** `command_runner=FirejailBackend(firejail_path=settings.sandbox_firejail_path, workspace_root=workspace_root)`
**And** `container.__post_init__` 把 runner 注入 `executor.sandbox_runner`

---

## Epic S3: 纵深加固 — 进程组 killing + workspace 文件系统隔离

超时/cancel 杀子进程时整组全杀（Linux）；FirejailBackend 自动把 workspace_root 映射为 OS 级
文件系统隔离（`--private`）。

### Story S3-1: Linux 进程组 killing

As a HeAgent 操作者,
I want shell 子进程被 kill 时其后台子孙一并终止,
So that `sh -c "cmd1 & cmd2"` 的孤儿进程不残留。

**Acceptance Criteria:**

**Given** `sys.platform == "linux"`
**When** `_run_subprocess_shell` / `_run_subprocess_exec` 创建子进程
**Then** 传 `start_new_session=True`（子进程成为新会话组长+进程组长）

**Given** Linux 平台
**When** `_kill_and_reap` 收尾
**Then** 用 `os.killpg(os.getpgid(proc.pid), signal.SIGKILL)` 替代 `proc.kill()`（杀整组）
**And** `ProcessLookupError` 被 suppress、`PermissionError`/`OSError` 经既有 `except OSError` 降级
**And** kill 失败后仍执行 `await proc.wait()`（与 item 3 kill/wait 解耦兼容）

**Given** 非 Linux 平台
**When** 子进程创建 + kill
**Then** 行为完全不变——不传 `start_new_session`、用 `proc.kill()` 而非 `killpg`——**零回归**

### Story S3-2: FirejailBackend 自动映射 workspace_root 为 --private

As a HeAgent 操作者,
I want `FirejailBackend` 自动把 workspace_root 映射为 firejail 的 `--private` 隔离,
So that 子进程只能看到 workspace 目录。

**Acceptance Criteria:**

**Given** `FirejailBackend.__init__` 新增可选参数 `workspace_root: str | None = None`
**When** `workspace_root="/home/user/project"` 非空
**Then** `_build_argv` 在 `extra_args` 与 `profile_args` 之间插入 `"--private=/home/user/project"`
**And** argv 顺序为 `[firejail, *extra_args, --private=<ws>, *profile_args, "--", "sh", "-c", command]`

**Given** `workspace_root=None`
**When** `_build_argv` 调用
**Then** 不生成 `--private` 参数（argv 中无此参数）

**Given** `EngineContainer.default()` 中 workspace_root 来自 `os.getcwd()`
**When** 构造 `FirejailBackend`
**Then** `workspace_root` 自动传入当前工作目录

---

## Epic S4: 可观测 & 文档收尾

executor emit 事件标注沙箱后端类型 + PID；安全声明文档同步。

### Story S4-1: executor emit 事件扩展 sandbox_backend + sandbox_pid

As a HeAgent 操作者/开发者,
I want executor 的 emit 事件标注当前用的是什么沙箱后端,
So that 我能从日志/事件中区分一次 shell 调用是在 firejail 里还是 passthrough 里跑的。

**Acceptance Criteria:**

**Given** executor 四类 emit 事件（`started` / `completed` / `failed` / `blocked`）
**When** 细节 dict 输出
**Then** 新增字段：
- `sandbox_backend: str` — `"passthrough"` 或 `"firejail"`
- `sandbox_pid: str` — 子进程 PID 字符串（passthrough 或取不到时为 `""`）

**Given** `FirejailBackend.run` 内 `proc = await create_subprocess_exec(...)`
**When** 子进程启动后
**Then** 把 `str(proc.pid)` 写入 `_sandbox_pid_slot` contextvar

**Given** executor `execute_in_sandbox` handler 返回后
**When** 读取 `_sandbox_pid_slot` 
**Then** 取到 PID 填入 `tool_call_completed` 事件的 `sandbox_pid` 字段
**And** 每次调用前 reset `_sandbox_pid_slot`（防上次调用的 PID 污染下次）

**Given** Passthrough 路径
**When** emit 事件输出
**Then** `sandbox_backend="passthrough"`、`sandbox_pid=""`

### Story S4-2: 安全声明 + 文档同步

As a HeAgent 维护者,
I want CLAUDE.md / docs/frame.md / docs/iteration.md 同步更新,
So that 本轮硬化不会让人误以为 Firejail 变成了安全边界。

**Acceptance Criteria:**

**Given** `CLAUDE.md` 安全声明章节
**When** 审查 sandbox 部分
**Then** 新增「Sandbox 硬化（2026-07-20）」段：覆盖 profile 映射 / 降级 / 配置入口 / 进程组 kill / workspace 隔离；明确声明 Firejail 仍非完美边界、须 OS 级沙箱兜底

**Given** `docs/frame.md` 4.4 sandbox.py 节 + 第五章已知缺口
**When** 审查
**Then** 更新：新增 profile 映射 + 降级 + 进程组 kill + `--sandbox` CLI flag；已知缺口移除已修复条目

**Given** `docs/iteration.md` 时间线
**When** 审查
**Then** 新增 sandbox-hardening 周期记录

---

## FR → Story 覆盖核对

| FR | Story | 说明 |
| --- | --- | --- |
| FR-S1 | S1-1 | FirejailBackend profiles + _build_argv |
| FR-S2 | S1-2 | executor profile contextvar 注入 |
| FR-S3 | S2-1 | firejail 可用性检测 + 降级 |
| FR-S4 | S2-2 | .env/CLI 配置入口 |
| FR-S5 | S3-1 | Linux 进程组 killing |
| FR-S6 | S3-2 | workspace_root --private |
| FR-S7 | S4-1 | emit 事件扩展 |
| NFR-S2 | S4-2 | 安全声明 + 文档同步 |

8/8 FR/NFR 全覆盖。
