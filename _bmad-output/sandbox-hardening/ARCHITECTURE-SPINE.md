---
name: HeAgent Sandbox 硬化 — 从管道到真正可用的沙箱执行
type: architecture-spine
purpose: build-substrate
altitude: feature
paradigm: brownfield 扩展 — 在既有 `CommandRunner` Protocol + `ToolExecutor.execute_in_sandbox` 管道上，填 profile 映射 / 降级 / 配置入口 / 进程组 kill / workspace 映射，不引入新后端类型、不扩 Protocol 签名
scope: sandbox-hardening 周期（Epic S1 profile-aware sandbox / S2 可用性 & 配置入口 / S3 纵深加固 / S4 可观测）
status: final
created: 2026-07-20
updated: 2026-07-20
binds: [FR-S1, FR-S2, FR-S3, FR-S4, FR-S5, FR-S6, FR-S7, NFR-S1, NFR-S2, NFR-S3, NFR-S4, NFR-S5, NFR-S6, SM-1, SM-2, SM-3, SM-4, SM-5, SM-6, SM-C1, SM-C2]
sources:
  - _bmad-output/sandbox-hardening/brief.md
  - _bmad-output/sandbox-hardening/prd.md
  - src/heagent/tools/sandbox.py
  - src/heagent/engine/executor.py
  - src/heagent/engine/policy.py
  - src/heagent/engine/container.py
  - src/heagent/config.py
  - src/heagent/cli.py
companions: []
---

# Architecture Spine — HeAgent Sandbox 硬化

> 本 spine 只承重「本轮引入的、未来 builder 无法从合规代码读出的不变量」。既有 HeAgent
> 架构（DAG / 执行链 / Provider 容错 / engine 治理层）权威见 `docs/frame.md`；`CommandRunner`
> / `FirejailBackend` / `RuntimeSlot` 既有决策见 `tools/sandbox.py` 源码——本 spine
> **继承而非重述**两者。

## Design Paradigm

**brownfield 扩展（在既有管道上填洞，非新机制）**。本轮不引入新后端类型、不扩 `CommandRunner`
Protocol 签名、不改 PolicyEngine 裁决逻辑。全部增量落在四个既有扩展点上：

1. **`FirejailBackend.__init__`** — 新增 `profiles` dict（profile 名 → firejail 参数），使
   `RoleSpec.sandbox_profile` 从死字段变为活的参数映射。
2. **`ToolExecutor.execute_in_sandbox`** — 新增 profile 的 contextvar 注入（`bind_sandbox_profile`），
   使 `FirejailBackend.run` 内能取到当前调用的 profile 名。
3. **`EngineContainer.default()` + `Settings` + `CLI`** — 新增 `.env`/CLI 配置入口，
   自动构造对应 `CommandRunner`，不给 `CommandRunner` Protocol 加签名负担。
4. **`_run_subprocess_shell/exec` + `_kill_and_reap`** — 新增 Linux 进程组 killing
   （`start_new_session` + `os.killpg`），不改非 Linux 路径。

承重约束：**安全声明诚实**——Firejail 仍非完美边界，本轮硬化不改变「须 OS 级沙箱兜底」的
底线立场。profile 映射 / 降级 / 配置入口均属 defense-in-depth 强化，不制造「配了 profile
就安全」的假象。

## Inherited Invariants

| Inherited | From parent | Binds here |
| --- | --- | --- |
| `CommandRunner` Protocol 签名 = `async run(command, *, timeout) -> str` | `tools/sandbox.py` 已有 | **不扩展签名**——profile 经 contextvar 注入，对 `PassthroughRunner` 透明 |
| `RuntimeSlot` 注入惯例（contextvar） | `tools/runtime.py` + memory/skills 等 | 新增 `_sandbox_profile_slot` 与 `_command_runner_slot` 同构 |
| 工具执行链固定为 `PolicyEngine → ToolExecutor → SafetyGuard → handler` | baseline `docs/frame.md` + CLAUDE.md | 本轮不改执行链顺序；profile 注入发生在 handler 调用前 |
| `SANDBOX_REQUIRED` 仅隔离 shell 子进程，file/memory 等宿主进程 I/O 不受覆盖 | `tools/sandbox.py` 安全声明 | 本轮不改变此边界 |
| `execute_in_sandbox` 默认透传（`sandbox_runner is None` → 直接调 handler） | `engine/executor.py` 既有 | 本轮不改此快速路径——`SANDBOX_BACKEND=passthrough` 时 runner 仍为 `None` |

## Invariants & Rules

```
┌─────────────────────────────────────────────────────────────────┐
│                      本轮改动范围（四个扩展点）                      │
│                                                                   │
│  ┌──────────┐    ┌──────────────┐    ┌──────────────────┐        │
│  │ Settings │───▶│ EngineContainer │──▶│ ToolExecutor     │        │
│  │ +sandbox │    │ .default()     │   │ execute_in_sandbox│       │
│  │ _backend │    │ 读 Setting 自动 │   │ +bind_sandbox     │       │
│  └──────────┘    │ 构造 runner    │   │  _profile(profile)│       │
│                  └──────────────┘    └────────┬─────────┘        │
│                                               │                   │
│                                               ▼                   │
│                  ┌──────────────────────────────────────┐        │
│                  │           CommandRunner               │        │
│                  │  ┌─────────────────────┐             │        │
│                  │  │ FirejailBackend     │             │        │
│                  │  │ +profiles: dict     │ ◀── 新增    │        │
│                  │  │ +workspace_root     │             │        │
│                  │  │ +_firejail_available│             │        │
│                  │  │ .run() → get_profile│             │        │
│                  │  │        → 查 profiles│             │        │
│                  │  │        → 合并 argv  │             │        │
│                  │  └─────────────────────┘             │        │
│                  │  ┌─────────────────────┐             │        │
│                  │  │ PassthroughRunner   │  profile    │        │
│                  │  │ 不变                 │  transparent│        │
│                  │  └─────────────────────┘             │        │
│                  └──────────────────────────────────────┘        │
│                                               │                   │
│                  ┌────────────────────────────┘                   │
│                  ▼                                                │
│  ┌───────────────────────────────┐                               │
│  │ _run_subprocess_shell/exec    │                               │
│  │ +start_new_session (Linux)    │ ◀── 新增                       │
│  │ _kill_and_reap                │                               │
│  │ +os.killpg (Linux)            │ ◀── 新增                       │
│  └───────────────────────────────┘                               │
└─────────────────────────────────────────────────────────────────┘
```

### AD-S1 — profile → args 映射在 `FirejailBackend` 内部、不扩 Protocol 签名（D-1/D-2 定稿）

- **Binds:** FR-S1, FR-S2, NFR-S5；`CommandRunner.run` 签名
- **Prevents:** 扩展 `CommandRunner.run(command, *, timeout)` 签名会强制所有 `CommandRunner`
  实现（含用户自定义 + `PassthroughRunner`）处理新参数 → 破坏 Protocol 稳定性。也防止 profile
  映射泄漏到 `.env`（脆弱、无 schema 校验、易配错）。
- **Rule:** `FirejailBackend.__init__` 接受可选 `profiles: Mapping[str, Sequence[str]]`（默认空）。
  `run()` 内部通过 contextvar `get_sandbox_profile()` 取当前 profile 名 → 查 `self._profiles` →
  合并 `self._extra_args` + profile args → 构造 argv。`profiles` 中的 key 不存在时仅用 `extra_args`
  （不抛错——回退默认参数）。`PassthroughRunner.run` 不调用 `get_sandbox_profile()`，对 profile 完全透明。
  映射为**纯函数**——给定 `(profile_name, extra_args, profiles_dict)` → 固定 argv 列表；单测不 mock
  `create_subprocess_exec`，直接断言 `_build_argv` helper 输出。

### AD-S2 — profile 经 `bind_sandbox_profile` contextvar 注入 executor 管道

- **Binds:** FR-S2, NFR-S5
- **Prevents:** 两种 alternative 接入方式的发散：
  - (a) `CommandRunner.run(command, *, timeout, profile=None)` — 扩签名破坏 Protocol，否决；
  - (b) `FirejailBackend` 在 handler 返回值里解析 profile —— handler 不传递此信息，否决。
- **Rule:** `tools/sandbox.py` 新增 `_sandbox_profile_slot: RuntimeSlot[str | None]`（与既有
  `_command_runner_slot` 同构）。暴露两个函数：
  - `bind_sandbox_profile(profile: str | None) -> Iterator[None]` — contextmanager
  - `get_sandbox_profile() -> str | None` — 读取
  `ToolExecutor.execute_in_sandbox` 在 `bind_command_runner` 外面再包一层
  `bind_sandbox_profile(profile)`。profile 为 `None` 时 `get_sandbox_profile()` 返回 `None`，
  `FirejailBackend.run` 检测到 `None` → 只用 `extra_args`。

### AD-S3 — firejail 不可用时优雅降级，不抛异常

- **Binds:** FR-S3, NFR-S3, SM-3, SM-5
- **Prevents:** firejail 不可用 → 首次 shell 调用才 `FileNotFoundError`（当前行为）；或构造期抛异常
  阻止 agent 启动（过于激进——用户可能愿意降级跑）。
- **Rule:** `FirejailBackend.__init__` 中用 `shutil.which(self._firejail_path)` 检测可用性，结果存
  `self._firejail_available: bool`。不可用时记一条 `logger.warning("firejail not found at %r, "
  "sandbox disabled — falling back to passthrough", path)`。`run()` 开头：
  ```python
  if not self._firejail_available:
      return await PassthroughRunner().run(command, timeout=timeout)
  ```
  属性 `FirejailBackend.available` 暴露检测结果（供 CLI/EngineContainer 查询）。
  **`SANDBOX_BACKEND=firejail` 且 `available=False` 时，executor emit 事件的 `sandbox_backend`
  字段仍为 `"firejail"`**（用户配置的意图），但实际执行路径是 Passthrough（无隔离）。

### AD-S4 — `EngineContainer.default()` 读 Settings 自动构造 runner，CLI flag 优先于 `.env`

- **Binds:** FR-S4, SM-4, SM-5
- **Prevents:** 用户需要写 Python 代码才能启用 firejail（当前）；Settings 字段缺失导致
  `EngineContainer.default()` 无法读取 sandbox 配置。
- **Rule:**
  - `Settings` 新增：
    - `sandbox_backend: Literal["passthrough", "firejail"]`（默认 `"passthrough"`，来自 `SANDBOX_BACKEND` env）
    - `sandbox_firejail_path: str`（默认 `"firejail"`，来自 `SANDBOX_FIREJAIL_PATH` env）
  - CLI `main()` 新增 `--sandbox` option（`click.Choice(["passthrough", "firejail"])`，默认 `"passthrough"`）。
    CLI flag 优先于 `.env`：若传了 `--sandbox firejail`，覆盖 `Settings.sandbox_backend`。
  - `EngineContainer.default()` 读最终生效的 sandbox_backend 值：
    - `"passthrough"` → `command_runner=None`（executor 内 `if None` 快速路径，不经过 bind contextvar）
    - `"firejail"` → `command_runner=FirejailBackend(firejail_path=settings.sandbox_firejail_path, workspace_root=workspace_root)`
  - `EngineContainer.default()` **不传 `profiles`**（本轮默认空集），后续 PR 可经构造参数传入。
  - `EngineContainer.__post_init__` 的既有守卫逻辑不变：仅 `executor.sandbox_runner is None` 时才注入
    container 级 runner。

### AD-S5 — Linux only 进程组 killing，非 Linux 路径零改动

- **Binds:** FR-S5, NFR-S3, SM-1
- **Prevents:** `os.killpg` 在非 Linux 平台行为未经验证 → 引入跨平台回归。也防止 process group
  语义（`start_new_session` 使子进程脱离当前 terminal 的 job control）在 Windows 上误解。
- **Rule:**
  - `_run_subprocess_shell` / `_run_subprocess_exec` 检测 `sys.platform == "linux"` → 传
    `start_new_session=True`（非 Linux 不传此参数，保持现有行为）。
  - `_kill_and_reap` 中 `proc.kill()` 替换为：
    ```python
    if sys.platform == "linux":
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
    ```
  - **与 item 3 的 kill/wait 解耦兼容**：`killpg` 失败后的 `except` 行为与现有 `proc.kill()`
    块同构（吞 `ProcessLookupError`，`PermissionError`/`OSError` 经 `except OSError` 降级）。
  - 非 Linux 平台路径**完全不变**（零回归，SM-1）。

### AD-S6 — workspace_root 映射为 firejail `--private` 参数

- **Binds:** FR-S6
- **Prevents:** 工作区围栏只有 Python 逻辑层（`resolve_under_root` + policy 预检），无 OS 级
  firejail 文件系统隔离——两者不是替代关系，是纵深防御的两个 layer。
- **Rule:**
  - `FirejailBackend.__init__` 新增可选参数 `workspace_root: str | None = None`
  - `workspace_root` 非空时，在 argv 中生成 `--private=<workspace_root>` 参数，插在 `extra_args`
    与 `profile_args` 之间：`[firejail, *extra_args, --private=<ws>, *profile_args, "--", "sh", "-c", command]`
  - `workspace_root` 为 `None` 时不生成 `--private` 参数（不影响纯 profile 映射用例）
  - `EngineContainer.default()` 从 `os.getcwd()` 取 workspace_root 并传入 FirejailBackend
  - firejail `--private` 使子进程只能看到 workspace_root 目录下的文件（宿主文件系统其余部分不可见）——
    这是 OS 级隔离，不依赖 Python 路径校验逻辑

### AD-S7 — executor emit 事件扩展 `sandbox_backend` + `sandbox_pid` 字段

- **Binds:** FR-S7
- **Prevents:** 日志/事件无法区分一次 shell 调用是否走了 firejail——降低可观测性，增加调试难度。
- **Rule:**
  - executor 四类 emit 事件（`started` / `completed` / `failed` / `blocked`）的 `details` dict 新增：
    - `sandbox_backend: str` — `"passthrough"` 或 `"firejail"`（从 `get_command_runner()` 的
      `type` 推断：`PassthroughRunner` → `"passthrough"`，`FirejailBackend` → `"firejail"`）
    - `sandbox_pid: str` — firejail 子进程 PID 的字符串；passthrough 或取不到时为 `""`
  - PID 获取方式：`FirejailBackend.run()` 内把 `proc.pid` 写入一个专用于 PID 的 contextvar
    `_sandbox_pid_slot`（另建，不混入 `_sandbox_profile_slot`）；executor 在 handler 返回后
    从该 slot 读取 PID 填入事件 details。slot 在每次 `execute_in_sandbox` 前/后 reset。
  - `BLOCKED` / `APPROVAL_REQUIRED` 事件的 `sandbox_backend` 字段根据 `get_command_runner()`
    的类型填写（即使调用未实际执行，标注「本该用什么后端」）。

## Profile → Args 映射算法（伪代码）

```python
# FirejailBackend._build_argv(command, profile, workspace_root) -> list[str]
def _build_argv(self, command: str, profile: str | None, workspace_root: str | None) -> list[str]:
    argv = [self._firejail_path]
    argv.extend(self._extra_args)

    if workspace_root:
        argv.append(f"--private={workspace_root}")

    if profile and profile in self._profiles:
        argv.extend(self._profiles[profile])

    argv.extend(["--", "sh", "-c", command])
    return argv
```

此函数为**纯函数**——无 I/O、无 contextvar、无外部状态。可独立单测。

## 降级路径（`FirejailBackend.run` 完整流程）

```python
async def run(self, command: str, *, timeout: int) -> str:
    if not self._firejail_available:
        # 优雅降级：firejail 不可用 → 透传
        return await PassthroughRunner().run(command, timeout=timeout)

    profile = get_sandbox_profile()
    argv = self._build_argv(command, profile, workspace_root=self._workspace_root)
    return await _run_subprocess_exec(argv, timeout=timeout)
```

## 测试策略

| 测试类型 | 测试内容 | 不变量 |
|----------|----------|--------|
| **纯函数单测** | `FirejailBackend._build_argv` 给定不同 profile / workspace_root → 断言 argv 列表 | 无 I/O、无 subprocess、无 contextvar |
| **contextvar 单测** | `bind_sandbox_profile("x")` + `get_sandbox_profile()` → 断言 `"x"`；嵌套 bind 恢复 | 与 `_command_runner_slot` 隔离（两个独立 slot） |
| **降级单测** | mock `shutil.which` → `None`；`FirejailBackend.run("echo hi", timeout=10)` → 断言走 Passthrough + warning 日志 | firejail 不可用时 `run()` 不抛异常 |
| **进程组 mock 单测** | mock `os.killpg` + `os.getpgid`；`sys.platform` monkeypatch；断言 Linux 路径走 killpg、非 Linux 走 `proc.kill()` | 进程组 killing 不对非 Linux 路径产生副作用 |
| **配置集成测试** | mock Settings + CLI flag → `EngineContainer.default()` 产出的 executor 的 `sandbox_runner` 类型断言 | `passthrough` → `None`；`firejail` → `FirejailBackend` 实例 |
| **零回归测试** | 全部 727 个现有测试 | 不新增 failure |
| **emit 事件测试** | mock emit callback → 断言 details 中的 `sandbox_backend` / `sandbox_pid` | 类型正确、PID 可空 |

## FR→AD 覆盖核对

| FR | 实现 AD | 测试锚点 |
|----|---------|----------|
| FR-S1 | AD-S1 | `test_build_argv_*` 纯函数单测 |
| FR-S2 | AD-S2 | `test_bind_sandbox_profile_*` contextvar 单测 |
| FR-S3 | AD-S3 | `test_firejail_unavailable_falls_back` 降级单测 |
| FR-S4 | AD-S4 | `test_container_default_reads_sandbox_setting` 集成测试 |
| FR-S5 | AD-S5 | `test_killpg_linux_only` 进程组单测 |
| FR-S6 | AD-S6 | `test_build_argv_with_workspace_root` 纯函数单测 |
| FR-S7 | AD-S7 | `test_emit_sandbox_fields` emit 事件测试 |

7/7 FR 全覆盖。

## 安全声明（本轮更新）

本轮硬化不改变 HeAgent 的安全边界底线。以下声明需同步进 `CLAUDE.md` / `docs/frame.md`：

> **Sandbox 硬化（2026-07-20）：** `FirejailBackend` 新增 profile → 参数映射、`.env`/CLI 配置入口、
> firejail 不可用时的优雅降级、Linux 进程组 killing、workspace_root OS 级文件系统隔离。
> Firejail 仍非完美边界（仅隔离 shell 子进程、Linux-only、可被绕过），上述强化均为
> defense-in-depth——须 OS 级沙箱兜底。`sandbox_profile` 不改变「Firejail 非完美边界」的底线立场。

## 与既有架构的交互边界

| 边界 | 约束 |
|------|------|
| `PolicyEngine` | **不改**——`_sandbox_profile()` / `PolicyVerdict.sandbox_profile` 保持不变；profile 产生与消费均在本轮范围外 |
| `AgentLoop` | **不改**——本轮改动只在 executor 层和 sandbox 工具层 |
| `SubAgent` | **不改**——子 Agent 经 `dataclasses.replace(engine, policy=...)` 继承父 executor 引用，`sandbox_runner` 随 executor 一同继承；子 Agent 的 `RoleSpec.sandbox_profile` 通过 policy 层传递到 executor |
| `CommandRunner` Protocol | **不改签名**——`run(command, *, timeout)` 不变；profile 经 contextvar 注入 |
| `PassthroughRunner` | **零改动**——不对 profile 做任何响应 |
| 非 shell 工具 | **不受影响**——`CommandRunner` 抽象仅 shell 使用；file/memory 等无子进程、不走沙箱管道 |
