---
title: "HeAgent Sandbox 硬化 — 从管道到真正可用的沙箱执行"
status: draft
cycle: sandbox-hardening
preceded_by:
  - _bmad-output/baseline/（epics 1-10）
  - _bmad-output/mcp-client/（epics 11-13）
  - _bmad-output/mcp-client-v2/（epics 14-17）
created: 2026-07-20
updated: 2026-07-20
---

# PRD: HeAgent Sandbox 硬化

> **本文档的 FR 编号（FR-S1~S7）独立于主线 baseline（FR-1~24）与 MCP V1/V2（FR-1~11 / FR-A*~C*）。**
> 下游 epics/stories 以本 PRD 的 `FR-S*` 为准。

## 0. Document Purpose

本 PRD 面向**架构（`bmad-architecture`）与 epics/stories（`bmad-create-epics-and-stories`）**
两个下游工作流。它建立在以下既有产物之上、不重复其内容：

- **`brief.md`**（本周期）：产品愿景、缺口、方案、边界、关键决策——本 PRD 是其结构化展开。
- **`src/heagent/tools/sandbox.py`**（已交付）：`CommandRunner` Protocol / `PassthroughRunner` /
  `FirejailBackend` / `RuntimeSlot` 注入——本 PRD 的所有 FR 落在其扩展点上，**不重写、不破坏不变量**。
- **`src/heagent/engine/executor.py`**（已交付）：`ToolExecutor.execute_in_sandbox(call, profile, handler)`
  是 profile 注入的消费点。
- **`src/heagent/engine/policy.py`**（已交付）：`PolicyVerdict.sandbox_profile` 是 profile 名的产出点。
- **`src/heagent/engine/roles.py`**（已交付）：`RoleSpec.sandbox_profile` 是 profile 名的声明点。

## 1. Vision

HeAgent 有一条完整但**空壳**的沙箱执行管道：`SANDBOX_REQUIRED` 裁决 → `CommandRunner` 抽象 →
`FirejailBackend`。管道两侧是通的（policy 能裁决、executor 能分发），但**中间段是空的**——
`FirejailBackend` 不消费 `sandbox_profile`、普通用户没有配置入口、firejail 不可用时不提示。

本轮硬化把这条管道填满：**让 `sandbox_profile` 从死字段变成活的 firejail 参数映射，
让普通用户能通过 `.env` / CLI 启用沙箱，让 firejail 不可用时优雅降级而非崩溃。**
不动 architecture、不新增后端类型、不扩 `CommandRunner` Protocol 签名。

安全立场延续：Firejail 仍非完美边界，仅隔离 shell 子进程、Linux-only——须 OS 级沙箱兜底。
本轮不制造「接了 profile 就安全」的假象。

## 2. Target User

### 2.1 Jobs To Be Done

- **功能**：让不同角色（planner/coder/tester）跑 shell 时有**不同的 firejail 隔离强度**——coder 可以
  `--net=none` 阻止出站连接，而 planner 只需 `--private-tmp`。
- **功能**：让我能通过 `.env` 一行配置或 CLI flag 开启 firejail 沙箱，**不需要改 Python 代码**。
- **功能**：机器没装 firejail 时，agent 能**优雅降级**继续工作（warn + passthrough），而不是在
  首次 shell 调用时才炸。
- **情境**：我是这个 agent 的运维者/操作者——我信任自己的本地命令，但**不信任 LLM 自主生成的 shell 命令**
  （可能误删文件、出站泄数据、fork bomb）。firejail 给我一堵 OS 墙——不是完美堡垒，但比裸跑强得多。
- **情感**：我不想为了安全关掉 shell 工具（它太有用）。我要的是「壳还在，但壳里跑的东西被圈住」。

### 2.2 Non-Users (本轮)

- 把 HeAgent 部署在容器/K8s 里、用 Pod Security Policy 替代 firejail 的运维者——不在 scope。
- 在 Windows/macOS 上跑、期望同等级 OS 隔离的用户——Firejail Linux-only，非 Linux 用户仅得降级。
- 需要沙箱隔离非 shell 工具（file/memory 在宿主进程内 I/O，`CommandRunner` 抽象不覆盖）。

### 2.3 User Journeys

- **UJ-S1. tan 给 coder 角色配 `sandbox_profile="network-isolated"`，coder 的 shell 调不了网。**
  tan 在代码里声明角色 `RoleSpec(name="coder", sandbox_profile="network-isolated", ...)`，
  启动 agent 时 `--sandbox firejail`。agent 调 `shell("curl evil.com")` → policy 裁决
  `SANDBOX_REQUIRED(sandbox_profile="network-isolated")` → executor 把 profile 注入 runner →
  `FirejailBackend` 查 profiles dict 拿到 `--net=none` 参数 → firejail 启动的 sh 无法出站。
  Realizes FR-S1, FR-S2, FR-S4。

- **UJ-S2. tan 的机器没装 firejail，但忘了这件事——agent 不炸。**
  tan 在 `.env` 里写了 `SANDBOX_BACKEND=firejail`，但他的 macOS 没装 firejail。agent 启动时检测
  firejail 不存在 → `logger.warning("firejail not found, falling back to passthrough")` →
  后续 shell 走 Passthrough（零隔离，但 agent 照常工作）。tan 看到 warning 后决定装 firejail，
  下次启动沙箱即生效。Realizes FR-S3。

- **UJ-S3. tan 的 agent 跑了一个 `sh -c "background_job &"`，超时后子进程和孙子全被杀干净。**
  agent 超时 kill → `_kill_and_reap` 在 Linux 上用 `killpg` 整组杀 → 主进程和后台子孙都终止。
  Realizes FR-S5。

## 3. Glossary

- **CommandRunner** — `tools/sandbox.py` 中的 Protocol：`async run(command, *, timeout) -> str`。
  沙箱后端抽象。当前有两个实现：`PassthroughRunner`（透传，零隔离）、`FirejailBackend`（firejail 包裹）。
- **sandbox_profile** — 一个字符串标签，从 `RoleSpec.sandbox_profile` 声明，经 `PolicyEngine._sandbox_profile()`
  产出，写入 `PolicyVerdict.sandbox_profile`，传到 `ToolExecutor.execute_in_sandbox(call, profile=...)` ——
  最终被 `FirejailBackend` 用于查 `profiles` dict 得到对应的 firejail 参数。**当前管道最后一环断裂**（profile
  传入 executor 后即丢弃）。
- **profiles dict** — `FirejailBackend` 的新构造参数：`dict[str, Sequence[str]]`，key 是 profile 名，
  value 是该 profile 的 firejail 参数元组（如 `{"default": ("--private-tmp",), "network-isolated": ("--net=none",)}`）。
- **进程组 killing** — Linux `os.killpg(os.getpgid(pid), signal.SIGKILL)`：杀死以该子进程为组长的整个进程组，
  包括 `sh -c "cmd1 & cmd2"` 产生的后台子孙。当前仅 `proc.kill()` 杀直系子进程。
- **优雅降级** — firejail 不可用时 `FirejailBackend` 不抛异常、不阻止 agent 启动。`run()` 内部自动走
  Passthrough 路径（零隔离），同时记一条 WARNING 日志告知用户。

## 4. Requirements

### FR-S1：`FirejailBackend` 按 profile 名映射 firejail 参数

**As a** HeAgent 操作者,
**I want** `FirejailBackend` 接受 `profiles: dict[str, Sequence[str]]` 构造参数并按 profile 名映射 firejail 参数,
**So that** `RoleSpec.sandbox_profile="network-isolated"` 实际产生 `--net=none` 等隔离效果。

**Consequences:**

- `FirejailBackend.__init__` 新增可选参数 `profiles`（默认空 dict），类型 `Mapping[str, Sequence[str]]`
- `FirejailBackend.run(command, *, timeout)` 从当前 contextvar 取 profile 名 → 查 `self._profiles` → 与 `self._extra_args` 合并
- profile 名不在 `profiles` dict 中 → 仅用 `extra_args`（不抛错，回退默认）
- `profiles` 中的 profile 值与 `extra_args` 合并顺序：`[*extra_args, *profile_args, "--", "sh", "-c", command]`

**独立可测：** mock `create_subprocess_exec` 验证不同 profile → 不同 argv。

### FR-S2：`ToolExecutor.execute_in_sandbox` 传递 profile 到 `CommandRunner` 上下文

**As a** HeAgent 开发者,
**I want** `execute_in_sandbox` 把 `profile` 参数注入 `CommandRunner` 可读取的上下文,
**So that** `FirejailBackend.run` 内能取到当前调用的 profile 名。

**Consequences:**

- `tools/sandbox.py` 新增 `bind_sandbox_profile(profile: str | None) -> Iterator[None]` contextmanager，
  以及 `get_sandbox_profile() -> str | None`
- `ToolExecutor.execute_in_sandbox` 在 `bind_command_runner` 外再包一层 `bind_sandbox_profile(profile)`
- `FirejailBackend.run` 内部调 `get_sandbox_profile()` 取 profile 名
- `PassthroughRunner.run` 不读取 profile（保持现有行为，对 profile 透明）
- profile 为 `None` 时 `get_sandbox_profile()` 返回 `None`

**独立可测：** mock executor 调用链，验证 handler 内 `get_sandbox_profile()` 返回预期值。

### FR-S3：firejail 可用性检测 + 优雅降级

**As a** HeAgent 操作者,
**I want** firejail 不可用时 agent 能优雅降级继续工作,
**So that** 我不因为机器没装 firejail 而整个 agent 崩溃。

**Consequences:**

- `FirejailBackend.__init__` 中 `_firejail_available = shutil.which(self._firejail_path) is not None`
- 不可用时：`logger.warning("firejail not found at '%s', sandbox disabled — falling back to passthrough", path)`
- `FirejailBackend.run` 内 `if not self._firejail_available: return await PassthroughRunner().run(command, timeout=timeout)`
- `FirejailBackend.available` 属性暴露检测结果（供 `EngineContainer.default()` 或 CLI 查询）

**独立可测：** mock `shutil.which` 返回 `None`，验证 `run()` 走 Passthrough + warning 日志。

### FR-S4：`.env` / CLI 配置入口

**As a** HeAgent 操作者,
**I want** 通过 `.env` 变量或 CLI flag 启用 firejail 沙箱,
**So that** 我不需要写 Python 代码就能开启沙箱功能。

**Consequences:**

- `Settings` 新增两个字段：
  - `sandbox_backend: Literal["passthrough", "firejail"] = "passthrough"`（来自 `SANDBOX_BACKEND` 环境变量）
  - `sandbox_firejail_path: str = "firejail"`（来自 `SANDBOX_FIREJAIL_PATH` 环境变量）
- CLI `main()` 新增 `--sandbox` option（`type=click.Choice(["passthrough", "firejail"])`，默认 `passthrough`）；
  CLI flag 优先于 `.env`
- `EngineContainer.default()` 读取 Settings 自动构造对应 CommandRunner：
  - `"passthrough"` → `command_runner=None`（executor 内在 `execute_in_sandbox` 的 `if None` 快速路径）
  - `"firejail"` → `command_runner=FirejailBackend(firejail_path=settings.sandbox_firejail_path)`
- 若无配置文件定义 profiles，`EngineContainer.default()` 使用 firejail 默认 profile 集（P2 空集，
  后续 PR 可扩展为含 `"default"` 与 `"network-isolated"` 的集合）

**独立可测：** mock Settings + CLI flag，验证 `EngineContainer.default()` 产出的 executor 的
`sandbox_runner` 是 `None`（passthrough）或 `FirejailBackend` 实例（firejail）。

### FR-S5：Linux 进程组 killing

**As a** HeAgent 操作者,
**I want** shell 子进程被 kill 时其后台子孙一并终止,
**So that** `sh -c "cmd1 & cmd2"` 的孤儿进程不残留在系统里。

**Consequences:**

- `_run_subprocess_shell` / `_run_subprocess_exec` 在 `sys.platform == "linux"` 时传 `start_new_session=True`
- `_kill_and_reap` 中 `proc.kill()` 替换为：
  - Linux → `os.killpg(os.getpgid(proc.pid), signal.SIGKILL)`（包在 `try: except ProcessLookupError` 内，
    与现有 kill 块同构；非 Linux 保持 `proc.kill()`）
- `item 3` 的 kill/wait 解耦不受影响：killpg 失败仍走 wait
- `start_new_session=True` 使子进程成为新会话组长+进程组长——子孙都在该进程组内，`killpg` 全覆盖

**独立可测：** mock `os.killpg` + `os.getpgid`，验证 Linux 路径走 killpg、非 Linux 路径走 `proc.kill()`。

### FR-S6：`FirejailBackend` 自动映射 `workspace_root` 为 `--private`

**As a** HeAgent 操作者,
**I want** `FirejailBackend` 自动把 workspace_root 映射为 firejail 的 `--private` 隔离,
**So that** 子进程只能看到 workspace 目录、看不到宿主文件系统的其他地方。

**Consequences:**

- `FirejailBackend.__init__` 新增可选参数 `workspace_root: str | None = None`
- 若 `workspace_root` 非空：在 argv 中 `--private=<workspace_root>` 参数插入在 `extra_args` 与 `profile_args` 之前。
  即：`[firejail, *extra_args, --private=<ws>, *profile_args, "--", "sh", "-c", command]`
- workspace_root 由 `EngineContainer.default()` 从 `os.getcwd()` 获取并传入
- workspace_root 为 `None` 时不生成 `--private` 参数（不影响纯 profile 映射用例）

**独立可测：** mock `create_subprocess_exec`，验证 argv 中包含 `--private=<path>`。

### FR-S7：沙箱 executor emit 事件新增 backend 类型 + PID

**As a** HeAgent 操作者/开发者,
**I want** executor 的 emit 事件标注当前用的是什么沙箱后端,
**So that** 我能从日志/事件中区分一次 shell 调用是在 firejail 里还是 passthrough 里跑的。

**Consequences:**

- executor 的 `tool_call_started` / `tool_call_completed` / `tool_call_failed` / `tool_call_blocked` 事件
  的 `details` dict 新增字段：
  - `sandbox_backend: str`（`"passthrough"` / `"firejail"`）
  - `sandbox_pid: str`（firejail 子进程 PID 的字符串；passthrough 时为 `""`；无法取到 PID 时为 `"?"`）
- `ToolExecutor.execute_in_sandbox` 中 handler 执行前后读取 `get_command_runner()` 的类型名填入 backend 字段
- PID 从 handler 的返回值中不可直接获取（`shell` handler 返回文本串，不含 PID）→ 复用已存在的
  `_format_result` 惯例：不在 `ToolResult.content` 里注入 PID，而是在 `FirejailBackend.run`
  内把 `proc.pid` 写入一个 contextvar，executor 从该 contextvar 读到 PID 填入事件 details

**独立可测：** mock emit 回调，验证 details 中 `sandbox_backend` 值与 runner 类型一致。

## 5. Non-Functional Requirements

| NFR | 描述 | 验证方式 |
|-----|------|----------|
| **NFR-S1** | **零回归**：DIRECT 路径 + PassthroughRunner 行为不变，全部 727 测试保持绿 | `pytest` 全量通过，`ruff` / `mypy` clean |
| **NFR-S2** | **安全声明诚实**：`CLAUDE.md` / `docs/frame.md` 更新，明确标注 Firejail 仍非完美边界、profile 映射不改变此立场 | diff 审查新文档文本 |
| **NFR-S3** | **平台透明**：Windows/macOS 无 firejail 时优雅降级、不 crash、不阻止 agent 启动或 shell 调用 | mock `shutil.which` + `sys.platform` |
| **NFR-S4** | **确定性单测**：profile→args 映射为纯函数、不入子进程、不触达 LLM | 单元测试不 mock `create_subprocess_exec`，直接断言映射结果 |
| **NFR-S5** | **模块边界**：改动限 `tools/sandbox.py` + `engine/executor.py` + `config.py` + `cli.py`；不反依赖 agent/providers/memory | import 审查 + DAG 验证 |
| **NFR-S6** | **测试覆盖**：每个 FR 至少 1 个独立单测 + 1 个集成/端到端测试 | coverage review |

## 6. User Journeys（详细）

### UJ-S1：profile-aware sandbox 端到端

```
tan 在代码中声明:
  RoleSpec(name="coder", sandbox_profile="network-isolated", ...)

tan 启动 agent:
  $ heagent --sandbox firejail

EngineContainer.default() 检测 SANDBOX_BACKEND=firejail
→ 构造 FirejailBackend(workspace_root="/workspace", profiles={...})
→ firejail_available → True
→ executor.sandbox_runner = FirejailBackend 实例

agent 调 shell("curl evil.com"):
  PolicyEngine._sandbox_profile("shell") → sandbox_tools=["shell"] → profile="network-isolated"
  → PolicyVerdict(mode=SANDBOX_REQUIRED, sandbox_profile="network-isolated")

  ToolExecutor.execute:
    → _execute_in_sandbox
    → bind_sandbox_profile("network-isolated")
    → bind_command_runner(firejail_backend)
    → handler(call)
      → shell handler 调 get_command_runner().run("curl evil.com", timeout=120)
        → FirejailBackend.run:
          → get_sandbox_profile() → "network-isolated"
          → profiles["network-isolated"] → ("--net=none", "--private-tmp")
          → argv = ["firejail", "--private=/workspace", "--net=none", "--private-tmp", "--", "sh", "-c", "curl evil.com"]
          → create_subprocess_exec(*argv)
          → firejail 启动 sh，sh 中的 curl 因 --net=none 无法出站
          → exit_code=... (非零，因为网络不通)
        → 返回 exit_code + stderr
      → executor 收 ToolResult
    → emit 事件携带 sandbox_backend="firejail", sandbox_profile="network-isolated"
```

### UJ-S2：firejail 不可用，优雅降级

```
tan 在 .env 写了 SANDBOX_BACKEND=firejail
macOS 没装 firejail

EngineContainer.default():
→ FirejailBackend(firejail_path="firejail")
  → shutil.which("firejail") → None
  → self._firejail_available = False
  → logger.warning("firejail not found at 'firejail', sandbox disabled — falling back to passthrough")
→ executor.sandbox_runner = FirejailBackend 实例（但内部标记不可用）

agent 调 shell("echo hello"):
  → SANDBOX_REQUIRED → execute_in_sandbox → handler
  → get_command_runner() → FirejailBackend 实例
  → FirejailBackend.run("echo hello", timeout=120)
    → if not self._firejail_available: return await PassthroughRunner().run(...)
  → 成功执行，exit_code=0，stdout="hello"
  → emit 事件携带 sandbox_backend="passthrough"（因为最终走的是 PassthroughRunner）
```

### UJ-S3：进程组 killing

```
Linux 上，agent 调 shell("sleep 100 & sleep 100")

PassthroughRunner.run("sleep 100 & sleep 100", timeout=1):
→ create_subprocess_shell(command, start_new_session=True)
  → 子进程 pid=12345，新会话组长 pgid=12345
  → sh 启动两个 sleep 后台进程，它们在同一进程组 pgid=12345

1 秒后超时:
→ _kill_and_reap(proc)
  → sys.platform == "linux" → os.killpg(12345, signal.SIGKILL)
  → 主 sh + 两个后台 sleep 全部终止
  → await proc.wait() → 回收
→ 返回 "exit_code=-1\nstderr: Command timed out after 1s"
```

## 7. Success Metrics

| SM | 指标 | 目标 |
|----|------|------|
| **SM-1** | 零回归 | 全部 727 已有测试保持绿 |
| **SM-2** | 确定性 | profile→args 映射有纯函数单测，不触达子进程/LLM |
| **SM-3** | 优雅降级 | firejail 不可用时 agent 能完成一次完整 shell 调用（不 crash） |
| **SM-4** | 用户入口 | `.env` 一行 + CLI flag 即可启用 firejail，不改 Python 代码 |
| **SM-5** | 配置错误早期暴露 | `sandbox_backend="firejail"` 但 firejail 不可用 → 启动时即 WARNING 告知，非首次 shell 调用才炸 |
| **SM-6** | 安全声明更新 | `CLAUDE.md` + `docs/frame.md` 同步更新，覆盖本轮新能力与边界 |

### SM-1 counter-metric（防过度自信）

- **SM-C1**：不因 `sandbox_profile` 参数映射的存在而放行本该被审批的 destructive 工具——沙箱 profile
  与审批是独立维度，不互相覆盖。
- **SM-C2**：`SANDBOX_BACKEND=firejail` 且 firejail 可用时，firejail 的 `exit_code` 正常传回（不被
  降级逻辑截胡走 Passthrough）。

## 8. FR→SM 覆盖核对

| FR | 覆盖的 SM |
|----|-----------|
| FR-S1 | SM-2（确定性）、SM-6（文档同步） |
| FR-S2 | SM-2（确定性） |
| FR-S3 | SM-3（优雅降级）、SM-5（早期暴露） |
| FR-S4 | SM-4（用户入口） |
| FR-S5 | SM-1（零回归——不影响非 Linux 路径） |
| FR-S6 | SM-1、SM-6 |
| FR-S7 | SM-6 |

7/7 FR 全覆盖。

## 9. Assumptions & Open Questions

### Assumptions

- **[A1]** `FirejailBackend` 的 `profiles` dict 由调用方（`EngineContainer.default()` 或手动装配）在构造期传入；本周期不提供 `.env` 级 profile 配置。
- **[A2]** Linux 进程组 killing（`os.killpg`）在 `sys.platform == "linux"` 时可用；WSL 属于 Linux；macOS 的 `os.killpg` 存在但行为可能不同 → 保守仅 Linux 启用。
- **[A3]** `workspace_root` 由 `EngineContainer.default()` 从 `os.getcwd()` 取；用户在代码中手动装配 `FirejailBackend` 时需自行传入。
- **[A4]** `PassthroughRunner` 的 profile 行为是 no-op——不接受、不读取、不因此改变行为；这是设计意图，非缺口。

### Open Questions

- **[Q1]** `EngineContainer.default()` 应提供哪几个内置 profile？当前建议空集（仅 `extra_args` 生效），后续 PR 可扩展为 `{"default": ("--private-tmp",), "network-isolated": ("--net=none", "--private-tmp")}`——是否本轮就做？
- **[Q2]** macOS `os.killpg` 经测试在子进程为 session leader 时效果与 Linux 一致——是否把进程组 killing 放宽到 `sys.platform != "win32"`？
- **[Q3]** `SANDBOX_FIREJAIL_PATH` 是否需要支持相对于 workspace 的路径（如 `./bin/firejail`），还是仅绝对路径 / PATH 查找？

## 10. Implementation Notes

### 改动文件清单

| 文件 | 改动类型 | 关联 FR |
|------|----------|---------|
| `src/heagent/tools/sandbox.py` | **核心改动**：`FirejailBackend` profiles + 降级 + `bind_sandbox_profile` + 进程组 kill | FR-S1, S2, S3, S5, S6 |
| `src/heagent/engine/executor.py` | 小改：`execute_in_sandbox` 加 `bind_sandbox_profile` + emit 事件扩展 | FR-S2, S7 |
| `src/heagent/config.py` | 新增 2 个 Settings 字段 | FR-S4 |
| `src/heagent/cli.py` | 新增 `--sandbox` option + `EngineContainer.default()` 调参 | FR-S4 |
| `src/heagent/engine/container.py` | `default()` 读 Settings 自动构造 runner + 传 workspace_root | FR-S4, S6 |
| `tests/test_sandbox.py` | **大幅扩展**：新增 profile 映射、降级、进程组 kill、contextvar 测试 | FR-S1~S7 |
| `tests/test_engine_p0.py` | 扩展：executor emit 事件字段验证 | FR-S7 |
| `tests/test_config.py` | 扩展：新 Settings 字段默认值 + 环境变量测试 | FR-S4 |
| `CLAUDE.md` | 安全声明更新 | NFR-S2 |
| `docs/frame.md` | 4.4 sandbox.py 更新 + 已知缺口更新 | NFR-S2 |
| `docs/iteration.md` | 时间线 + 周期记录 | NFR-S2 |

### 现有测试不变量（必须保持绿）

- `tests/test_sandbox.py` 全部 17 个现有测试
- `tests/test_shell.py` 全部 shell 工具测试
- `tests/test_engine_p0.py` 全部 executor/policy 测试
- `tests/test_config.py` 全部配置测试
- `tests/test_cli.py` 全部 CLI 测试
