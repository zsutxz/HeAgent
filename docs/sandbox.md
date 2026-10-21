# 沙箱机制导读

> **定位**：导读，不是权威。运行行为以 `src/` 为准；架构权威与配置表在
> [`frame.md`](frame.md)（DockerRunner 段、配置表 `sandbox_*`、已知缺口）。
> 本文补三件 `frame.md` 未成篇的内容：**端到端调用链**、**四档后端的行为差异**、
> **`container` 档（2026-10-21）相对旧形态的变化**。
>
> **维护触发**：改沙箱后端、档位分级、容器旗标、会话目录约定时同步本文。

## 0. 一句话结论

- HeAgent 的「沙箱」= **`shell` 工具的一个可替换执行后端**（`CommandRunner`）。
- 默认后端 = `PassthroughRunner`：直接 `create_subprocess`，**零隔离**。
- 要真隔离必须换后端：`firejail`（本机 namespace，Linux/macOS）或 `docker`（每命令一次性容器）。
- **所有后端都只覆盖 `shell` 路径**——文件工具、HTTP 工具、MCP 子进程都不在其中。
- 沙箱是 OS 级兜底，**不是安全边界**：`SafetyGuard`、`PolicyEngine`、`path_safety`、
  `firejail`、`DockerRunner` 全部可被绕过或存在逃逸面（宿主内核 / Docker daemon）。

## 1. 端到端调用链

```
LLM tool_call(shell)
   │
   ▼
AgentLoop
   │
   ▼
ToolExecutor.execute(call, verdict, guard, handler, run_context)
   │  ├─ PolicyEngine.evaluate() → PolicyVerdict.mode
   │  │     DIRECT / SANDBOX_REQUIRED / APPROVAL_REQUIRED / BLOCKED
   │  ▼
   ├─ _dispatch()  四路分发
   │     SANDBOX_REQUIRED ↓
   │
  ▼
_execute_in_sandbox()
   ① 二次授权复核  _sandbox_granted(call, run_context, verdict)
   ② SafetyGuard.check()
   ③ execute_in_sandbox(profile, handler, run_context)   ← 默认可被覆写
        bind_command_runner(runner)        # contextvar 注入
        bind_sandbox_profile(profile)
        bind_sandbox_workspace(dir)        # 仅 FR-1 开关开启时
        │
        ▼
    handler = tools/builtins/shell.py::shell()
        session = get_sandbox_session()
        有会话 → SandboxSession.run(cmd)   # 包 cd + marker + rc 回填
        无会话 → CommandRunner.run(cmd, timeout)
        │
        ▼
    PassthroughRunner / FirejailBackend / WinJobBackend / DockerRunner
        │
        ▼
    ToolResult(content="exit_code=…\nstdout:…\nstderr:…")
```

关键缝（monkeypatch 与测试的落点）：

| 缝 | 位置 |
| --- | --- |
| 策略裁决 | `engine/policy.py::PolicyEngine.evaluate` |
| 四路分发 | `engine/executor.py::ToolExecutor._dispatch` |
| 沙箱执行（可被库消费者覆写） | `engine/executor.py::ToolExecutor.execute_in_sandbox` |
| 后端注入 | `tools/sandbox/contracts.py::bind_command_runner` 等 `RuntimeSlot` |
| handler 取后端 | `tools/builtins/shell.py::shell` → `get_command_runner()` |
| 后端实现 | `tools/sandbox/{process,firejail,winjob,docker}.py` |

## 2. 四个决定点（谁决定「走不走沙箱」）

1. **策略**（`PolicyEngine`）
   - `sandbox_tools`：哪些工具名走沙箱；`sandbox_profiles`：工具 → profile 名映射；
   - `sandbox_mcp_tools`：MCP 工具是否走 `__mcp__` profile；
   - `sandbox_mode`：`read-only`（非只读工具一律 BLOCKED，fail-closed）/ `workspace-write`（默认）/ `danger-full-access`（跳过围栏与凭证 deny）。
2. **授权**（`EngineContainer.create_run_context`）
   - **仅在 `sandbox_runner is not None` 时**才把 `sandboxed_tools` 写进 run metadata；
   - 后端缺席（passthrough）不写 ⇒ 策略要求沙箱时按「未授权即拒绝」处理，**不伪造已在沙箱里跑**。
3. **强制**（`Settings.sandbox_enforce`，默认 True）
   - 探测到真实后端时自动把 `shell` 加进 `policy.sandbox_tools` 并授权本 run；
   - 无真实后端时零行为变更。
4. **装配事实**（`SandboxDecision`）
   - 装配期（`EngineContainer.default`）算好 `requested_backend` / `effective_backend` /
     `filesystem_isolation` / `network_isolation` / `reason`，写入 run metadata；
   - `effective_backend` 是**能力探测结果**，不是用户要求的字符串：请求 `docker` 但 daemon 不可达 ⇒
     降级 `passthrough` 且 `reason` 如实标注。

## 3. 四档后端

`SandboxTier` 强度序：`passthrough`(0) < `job`(1) < `firejail`(2) < `container`(3)。

| 档 | 实现 | 文件系统隔离 | 网络隔离 | 资源限额 | 平台 |
| --- | --- | --- | --- | --- | --- |
| `passthrough` | `PassthroughRunner` | 无 | 无 | 无 | 全平台 |
| `job` | `WinJobBackend` | 无（仅目录约定作 cwd） | 无 | Job Object（内存 / CPU 时间 / 进程数） | Windows |
| `firejail` | `FirejailBackend` | `--private=<ws>` | `--net=none`（`SANDBOX_NETWORK=False`） | `--rlimit-as` / `--rlimit-cpu` / `--rlimit-nproc` | Linux/macOS |
| `container` | `DockerRunner` | 仅挂 workspace → `/workspace` | `--network=none`（`SANDBOX_NETWORK=True` 才 bridge） | `--memory` / `--pids-limit`（`cpu_seconds` 无诚实映射） | 需 Docker daemon |

`container` 档的硬化与语义（`tools/sandbox/docker.py`）：

- 每命令 `docker run --rm --pull=never --name heagent-<hex>`；
- `--cap-drop=ALL` + `--security-opt no-new-privileges` + `--user sandbox`（非 root）；
- **不传 `--env`** ⇒ 容器内看不到宿主环境变量；
- 资源限额旗标**必须排在 IMAGE 之前**（排在镜像名之后会被 `docker run` 当成容器内命令参数，静默失效）；
- `sandbox_docker_digest` 非空 ⇒ 首 run 前 `docker image inspect` 校验 repo digest，不符显性拒绝；
- 超时 / 取消 ⇒ `docker kill -- <name>` → 校验 `.State.Running` → 仍活着则 `rm -f` 兜底；
- 镜像缺席**不隐式拉取**（`--pull=never`）；镜像内只装 `git` + `ca-certificates`，需要联网的
  `pip install` 会显性失败（D2 的设计立场）。

协议契约（`contracts.py`，四后端全实现）：`tier` / `available` / `run` / `isolates_network`。
`SandboxTier.can_relax_approval` 仅 `container` 为 True（弱后端不得因档位跳过审批）。

## 4. 会话层（与安全无关，但影响可用性）

- `SandboxSession`（`tools/sandbox/session.py`）：同一 run 内跨命令保持 cwd。
  - 包装形态：`cd <cwd> && { cmd; }` → 末尾 marker 行上报 `$PWD` 与真实退出码 → 回填。
  - 支持 `exit N`、含 `cd` 的复合命令；marker 行在返回前被剥离。
- docker 后端走 `_wrap_docker()`：cwd 用**容器侧**路径 `/workspace`（宿主路径在容器内不存在），
  且 `AgentLoop` 会把容器侧路径锚写进系统提示词，否则模型拿宿主路径写命令必然落空。
- 会话目录（FR-1，`SANDBOX_SESSION_WORKSPACE`）：`<workspace>/.heagent/sandboxes/<run_id>/`，
  幂等创建；`run_id` 非法或目标为符号链接 ⇒ `ValueError`（防路径逃逸锚定）。
  - firejail 作 `--private` 根；winjob 仅作子进程 cwd；docker 作挂载源。
  - 清理：正常结束按 `SANDBOX_SESSION_KEEP` 决定；崩溃遗留由 `cli/housekeeping.prune_sandbox_dirs`
    按 `SANDBOX_DIR_RETENTION_DAYS`（默认 7 天）回收。
- 目录约定**不是**安全边界（`session.py` docstring 明示）。

## 5. `container` 档相对旧形态的变化（2026-10-21）

三个提交：`ea301e7`（新增 DockerRunner）→ `2e6e043`（镜像 + 配置面）→ `03376e0`（硬化、限额、路径锚）。

| 项 | 之前 | 现在 |
| --- | --- | --- |
| 最高档 | `firejail`(2) | `container`(3) = `DockerRunner` |
| 启用方式 | `passthrough` / `firejail` / `winjob` | 多一个 `--sandbox docker` / `SANDBOX_BACKEND=docker` |
| 隔离单位 | 同一宿主上的子进程 | 一次性容器（宿主其余路径不可见） |
| 宿主环境变量 | 子进程继承 | 容器内看不到 |
| 默认网络 | 宿主网络 | `--network=none` |
| 容器硬化 | — | cap-drop / no-new-privileges / 非 root |
| 镜像防换 | — | 运行期 digest pin |
| 清理 | kill 子进程 | `docker kill` → 校验 → `rm -f` 兜底 |
| 会话 cwd | 宿主路径 | 容器侧 `/workspace`（`_wrap_docker`） |

**没有变的部分**（别按「已经默认上容器」理解）：

- `sandbox_backend` 默认仍是 `auto`，而 `auto` **只探 firejail**；`docker` 必须显式指定。
- MCP stdio 子进程仍不经沙箱（Epic 53 期二）。
- 四档都只覆盖 `shell` 路径。

## 6. 本机实况（2026-10-21 实测：`container` 档**已在用**）

- HeAgent 进程跑在**宿主 Windows** 上；`shell` 工具的后端是 `DockerRunner`
  （`SANDBOX_BACKEND=docker` 或 CLI `--sandbox docker`）⇒ **每条命令都是一台新的一次性容器**。
- 本机已在 `.env` 显式钉 `SANDBOX_BACKEND=docker`（2026-10-21）：`auto` 只探 firejail，
  靠启动参数的话一旦忘带 `--sandbox docker` 就会**静默裸跑**；`.env` 固化后所有入口同档，
  需要裸跑时用 `--sandbox passthrough` 显式覆盖。
- 三条判据（同一会话内连续实测）：
  1. 三次 `hostname` 各不相同（`8987d93ceaab` / `a550a1ff5e23` / `35217c3af666`）；
  2. 容器内 `/proc/1/cmdline` = `sh -c <整条命令>` —— 正是 `docker run … IMAGE sh -c` 的形态；
  3. `python3 -V` = `3.11.17`，与 `docker/sandbox/Dockerfile` 的 `python:3.11-slim` 基座一致。
- 容器内可观察到的隔离事实（**属于沙箱容器，不是 HeAgent 的运行环境**）：
  - `CapEff=0`、`CapBnd=0`、`NoNewPrivs=1`、`Seccomp=2`（2 个过滤器）；
  - 网络只有 `lo`、无默认路由，外部 TCP 全部 `[Errno 101] Network is unreachable`（`--network=none`）；
  - `/workspace` 是宿主**整盘**（本例 `E:\`）的 9p 挂载；`/sys`、`/sys/fs/cgroup` 只读；无 `docker.sock`；
  - 用户 `sandbox`(uid 1000)，有 `git`，**无** `docker` CLI、**无** `heagent` 包。
- 由此产生的操作后果（写文档/跑工具时容易踩）：
  - 每条命令独立容器 ⇒ 容器内**不保留跨命令状态**（临时文件、`cd`、导出的变量都不跨命令）；
  - 容器内**跑不了** `pytest`（无 `pydantic`、无网络装依赖）；
  - 文件工具的工作区根是宿主 Windows 路径，`/workspace/...` 这类绝对路径会被判 `outside workspace`，
    在工具里应使用相对路径；
  - `git` 需 `-c safe.directory=/workspace`（挂载后 uid 不匹配），且容器内无 git identity。

## 7. 从沙箱容器内**无法**验证的项

- `docker` CLI / daemon：容器内不可见 ⇒ 镜像构建与 digest 校验、`tests/test_sandbox_docker_integration.py`
  只能在宿主侧执行。
- `firejail` 路径：本机（Windows 宿主）不可用。
- `sandbox_backend=auto` 的选档：`auto` **只探 firejail**，在 Windows（或镜像内）永远落到 `passthrough`，
  **不会**自动选 `docker` / `winjob`；要用容器档必须显式配置。

## 8. 判据位置

| 测试 | 钉住什么 |
| --- | --- |
| `tests/test_sandbox.py` | 档位分级、`can_relax_approval`、firejail argv、降级与清理 |
| `tests/test_sandbox_mode.py` | `sandbox_mode` 三档语义、强制开关装配、限额 argv |
| `tests/test_sandbox_docker.py` | 可用性探测、argv 形状（含限额**位置**断言）、digest、kill 兜底、双真源交叉校验 |
| `tests/test_sandbox_docker_integration.py` | 真实 daemon 端到端（不进默认回归） |
| `tests/test_coverage_sandbox.py` | 覆盖率补齐用例 |

## 9. 配置键

不在此重复。见 [`frame.md`](frame.md) 配置表：`sandbox_backend` / `sandbox_mode` /
`sandbox_network` / `sandbox_enforce` / `sandbox_firejail_path` / `sandbox_docker_image` /
`sandbox_docker_digest` / `sandbox_session_workspace` / `sandbox_session_keep` /
`sandbox_dir_retention_days` / `sandbox_memory_limit_mb` / `sandbox_cpu_seconds` /
`sandbox_nproc_limit` / `sandbox_tool_profiles`。
