---
title: "HeAgent Sandbox 硬化 — 从管道到真正可用的沙箱执行"
status: draft
cycle: sandbox-hardening
preceded_by:
  - _bmad-output/baseline/（epics 1-10，MVP + 自学习闭环）
  - _bmad-output/mcp-client/（epics 11-13，MCP Tools-only）
  - _bmad-output/mcp-client-v2/（epics 14-17，写操作治理 + Resources/Prompts + Git 工具）
created: 2026-07-20
updated: 2026-07-20
---

# Product Brief: HeAgent Sandbox 硬化

> **本轮聚焦一个明确的问题：** HeAgent 有沙箱执行的开关和管道（`SANDBOX_REQUIRED` 裁决 →
> `CommandRunner` 抽象 → `FirejailBackend`），但管道是空的——profile 不映射参数、
> 普通用户没入口、firejail 不可用时不提示。**把这条管道填满，让它从「只有懂代码的人
> 手动装配才生效」变成「配一下就能用」。**

## 当前状态（一句话）

HeAgent 有一个完整但**空壳**的沙箱执行路径：

```
PolicyEngine          →  裁决 shell 工具需要沙箱
    ↓
ToolExecutor          →  走 execute_in_sandbox()，注入 CommandRunner
    ↓
CommandRunner         →  PassthroughRunner（默认，零隔离）
                      →  FirejailBackend（需手动编程装配，profile 参数不消费）
```

**开了沙箱 ≠ 有隔离。** 除非用户自己写代码组装 `EngineContainer(command_runner=FirejailBackend())`，
否则 `SANDBOX_REQUIRED` 和 `DIRECT` 没有任何区别。

## 问题

### 问题 1：`sandbox_profile` 是死字段——角色系统形同虚设

角色系统（planner / coder / tester / supervisor）允许声明 `sandbox_profile`：

```python
RoleSpec(
    name="coder",
    system="...",
    sandbox_profile="network-isolated",  # ← 这是期望，但 firejail 不会收到
)
```

这个 profile 名被 `PolicyEngine._sandbox_profile()` 算出、写进 `PolicyVerdict`、
传入 `ToolExecutor.execute_in_sandbox(call, profile=..., handler=...)`……然后就丢了。
`FirejailBackend` 构造时只接受一个扁平的 `extra_args` tuple，根本不认识 profile 语义。

**结果：** planner 和 coder 都跑 `shell`，policy 说一个要 `"network-isolated"`、一个要 `"default"`，
但在 firejail 那边它们跑的是完全相同的参数——profile 只是文档里的一个字符串，不产生任何
实际隔离差异。

### 问题 2：普通用户没有配置入口

启用 Firejail 的唯一方式是写 Python 代码：

```python
EngineContainer(command_runner=FirejailBackend(extra_args=("--private-tmp",)))
```

`.env` 里没有 `SANDBOX_BACKEND` 字段，CLI 没有 `--sandbox` 标志。用 `.mcp.json` 配 MCP
server 很方便，但配沙箱后端需要改源码——对非开发者用户是门槛。

### 问题 3：机器没装 firejail 时不提示，首次执行才炸

`FirejailBackend` 构造时不检查 `firejail` 命令是否存在。用户配了 firejail 后端，启动
正常，第一次 `shell` 调用时才 `FileNotFoundError: firejail`——而且是作为 ToolResult 错误
回传给 LLM，体验很差。

### 问题 4：timeout/cancel kill 子进程时，后台子孙进程泄漏

`sh -c "cmd1 & cmd2"` —— 主进程被 SIGKILL 后，后台子孙变成孤儿被 init 收养，
继续占用资源。`proc.kill()` 只杀直系子进程。

### 问题 5：workspace_root 未映射到 OS 级文件系统隔离

当前工作区围栏是纯 Python 逻辑（`resolve_under_root` + policy 预检）。
Firejail 有能力做 OS 级隔离：`--private=/workspace` 只暴露 workspace，其他目录不可见。
但 `FirejailBackend` 没有接线。

---

## 方案

**不引入新架构、不改 agent 循环、不改 PolicyEngine 核心逻辑。全部改动落在既有管道内部：**

### P0（核心价值：激活死字段）

**1. profile → firejail 参数映射**

`FirejailBackend` 构造时接受 `profiles: dict[str, Sequence[str]]`，key 是 profile 名，
value 是该 profile 的 firejail 参数列表。例：

```python
FirejailBackend(profiles={
    "default":          ("--private-tmp",),
    "network-isolated": ("--net=none", "--private-tmp"),
})
```

**2. profile 参数传达到 `CommandRunner`**

`ToolExecutor.execute_in_sandbox` 把 `profile` 通过 `bind_command_runner` + 上下文或
`CommandRunner.run` 签名扩展传递给后端。`FirejailBackend.run` 查 profiles dict 拿到对应
参数，与 `extra_args` 合并 → 不同 profile 跑不同的 firejail 参数。

### P1（用户面）

**3. firejail 可用性检测 + 优雅降级**

`FirejailBackend.__init__` 中 `shutil.which(firejail_path)`，不存在则：
- 记 `logger.warning("firejail not found, sandbox disabled — falling back to passthrough")`
- 后续 `run()` 降级为 Passthrough（不抛异常）

**4. `.env` + CLI 配置入口**

- `.env` 新增 `SANDBOX_BACKEND=firejail|passthrough`（默认 `passthrough`）
- CLI 新增 `--sandbox firejail` flag
- `EngineContainer.default()` 自动读取 Settings → 构造对应的 CommandRunner

### P2（纵深加固）

**5. 进程组 killing（Linux-only）**

`_run_subprocess_shell` / `_run_subprocess_exec` 在 Linux 上加 `start_new_session=True`，
`_kill_and_reap` 中用 `os.killpg(os.getpgid(proc.pid), signal.SIGKILL)` 替代 `proc.kill()`。
仅 `sys.platform == "linux"` 时启用，Windows/macOS 保持当前 `proc.kill()` 行为。

**6. workspace_root 映射为 firejail `--private`**

`FirejailBackend` 自动把 `workspace_root` 映射为 `--private=<workspace_root>` 参数，
让 firejail 子进程只能看到 workspace 目录。

### P3（收尾）

**7. 沙箱可观测**

executor 的 `emit` 事件现有 `sandbox_profile` 字段；新增 `sandbox_backend`（`"passthrough"` /
`"firejail"`）+ `sandbox_pid`（firejail 子进程 PID）。

---

## 边界

### In Scope（本周期做）

| ID | 内容 | 优先级 |
|----|------|--------|
| S1 | `FirejailBackend` 按 profile 名映射 firejail 参数 | P0 |
| S2 | `ToolExecutor.execute_in_sandbox` 传递 profile 到 CommandRunner | P0 |
| S3 | firejail 可用性检测 + 降级 Passthrough | P1 |
| S4 | `.env` `SANDBOX_BACKEND` + CLI `--sandbox` flag | P1 |
| S5 | Linux 进程组 killing（`start_new_session` + `killpg`） | P2 |
| S6 | FirejailBackend 自动 `--private=<workspace_root>` | P2 |
| S7 | 沙箱 executor emit 事件新增 backend 类型 + PID | P3 |

### Out of Scope（本周期不做）

- ❌ **非 firejail 的新沙箱后端**（Docker / gVisor / Windows Sandbox）—— YAGNI，Firejail 是唯一已验证的 OS 级后端
- ❌ **Settings 复杂化**——不引入 `SandboxProfile` 类、不逐 profile 配 firejail 参数（profiles mapping 在代码里，不在 `.env`）
- ❌ **非 shell 工具的沙箱**——file / memory 等宿主进程 I/O 不 spawn 子进程，`CommandRunner` 抽象对它们无意义
- ❌ **Windows `killpg` 等价物**（`taskkill /T`）——进程组 killing 仅 Linux，Windows 保持现状
- ❌ **自动安装 firejail**——检测到不可用就 warn + 降级，不尝试 `apt install` 等外部操作
- ❌ **CI 真跑 firejail**——测试用 mock，不要求 CI 环境有 firejail

### Deferred（未来考虑）

- ⬜ `FirejailBackend` 的 `--seccomp` / `--caps` 等高级参数
- ⬜ per-tool 粒度的 firejail 参数（目前 per-profile 粒度）
- ⬜ 沙箱执行的资源限额（`--rlimit-as` / `--rlimit-cpu`）
- ⬜ MCP server / cron 子进程接入沙箱

---

## 关键决策

### D-1：profile → args 映射存在代码里，不在 `.env`

**选择：** `FirejailBackend(profiles={"default": ..., "network-isolated": ...})` 构造参数。

**理由：** profile 映射是安全配置——firejail 参数的选择直接影响隔离强度。放在 `.env` 里容易
被用户随意修改、且无 schema 校验。放在代码里意味着 profile 集由开发者/管理员定义、用户只需
按名引用（`sandbox_profile="network-isolated"`）。

**替代方案（否决）：** `.env` 里逐 profile 配参数（如 `SANDBOX_PROFILE_NETWORK_ISOLATED=--net=none,--private-tmp`）——太脆弱、无校验、容易写错。

### D-2：profile 经 `bind_command_runner` 上下文注入，不扩展现有 Protocol 签名

**选择：** `bind_command_runner(runner, profile=...)` 把 profile 注入 contextvar；
`FirejailBackend.run` 从 contextvar 取 profile 名。

**理由：** `CommandRunner.run(command, *, timeout)` 签名已被 `shell` handler 约定死——handler
里是 `get_command_runner().run(command, timeout=timeout)`。如果扩展签名，所有 `CommandRunner`
实现（含用户自定义）都要改。走 contextvar 注入对 `PassthroughRunner` 透明（它不管 profile，
也不受影响）。

**替代方案（否决）：** `run(command, *, timeout, profile=None)`——破坏 Protocol、强制所有
实现者处理新参数。

### D-3：`SANDBOX_BACKEND=passthrough` 时 EngineContainer 不构造 PassthroughRunner 实例

**选择：** `SANDBOX_BACKEND=passthrough`（默认）等同于 executor 的 `sandbox_runner=None`，
即 `execute_in_sandbox` 内部 if None → 透传。不为 passthrough 显式构造 runner 实例。

**理由：** 当前 `ToolExecutor.execute_in_sandbox` 的逻辑是 `if self.sandbox_runner is None: return await handler(call)`——这是有意设计的快速路径（不经过 bind/unbind contextvar 开销）。
显式注入 PassthroughRunner 反会走 bind 路径，无意义且引入微小性能退化。

---

## FR / NFR 摘要

### 功能需求

| FR | 描述 |
|----|------|
| FR-S1 | `FirejailBackend` 接受 `profiles: dict[str, Sequence[str]]`，按 profile 名映射 firejail 参数 |
| FR-S2 | `ToolExecutor.execute_in_sandbox` 把 `profile` 经 contextvar 注入 CommandRunner 上下文 |
| FR-S3 | `FirejailBackend.__init__` 检测 firejail 可用性，不可用时 warn + 后续 `run()` 降级 Passthrough |
| FR-S4 | `.env` 支持 `SANDBOX_BACKEND` + `SANDBOX_FIREJAIL_PATH`；CLI 支持 `--sandbox` flag |
| FR-S5 | Linux 平台 `_run_subprocess_shell/exec` 加 `start_new_session=True` + `os.killpg` |
| FR-S6 | `FirejailBackend` 自动映射 `workspace_root` 为 `--private` 参数 |
| FR-S7 | executor emit 事件新增 `sandbox_backend` 字段 + `sandbox_pid` |

### 非功能需求

| NFR | 描述 |
|-----|------|
| NFR-S1 | 零回归：DIRECT 路径 + PassthroughRunner 行为不变，全部 727 测试保持绿 |
| NFR-S2 | 安全声明诚实：Firejail 仍非完美边界，profile 映射不改变此立场 |
| NFR-S3 | 平台透明：Windows/macOS 无 firejail 时优雅降级、不 crash |
| NFR-S4 | 确定性单测：profile→args 映射为纯函数、不入子进程、不触达 LLM |
| NFR-S5 | 模块边界：sandbox 改动在 `tools/sandbox.py` + `engine/executor.py`，不反依赖 |
| NFR-S6 | 测试覆盖：新增功能有独立单测 + 端到端集成测试 |
