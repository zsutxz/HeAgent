# 工具系统与 MCP（`tools/`）

> 状态：实现细节参考，自 [`framework.md`](../framework.md) **4.4 / 4.11 / 4.14** 迁出（2026-11-24 整理；编号不变，
> 其它文档里「4.4」的引用即指本页）。架构视角（项目定位 / 数据流 / 模块 DAG / 各模块职责与边界）见
> [`framework.md`](../framework.md)，安全立场（canonical）见 [§4.18](../framework.md#418-安全口径canonical)，
> 扩展页总索引见 [`frame/README.md`](README.md)。

## 4.4 Tool 系统 (`tools/`)

### decorator.py — @tool 装饰器

```python
@tool
def shell(command: str) -> str:
    """Execute a shell command."""
    ...


# 自动提取：
#   name = "shell"
#   description = "Execute a shell command."
#   parameters = {"type": "object", "properties": {"command": {"type": "string"}}}
```

- 从函数签名 + 类型提示 + docstring 自动生成 `ToolSchema`
- 注册到 `ToolRegistry`

### registry.py — 工具注册中心（单例）

| 方法 | 说明 |
|------|------|
| `get()` | 获取单例实例 |
| `register(schema, handler)` | 注册工具 |
| `get_handler(name)` | 查找执行函数 |
| `enable(name)` / `disable(name)` | 启用/禁用工具 |
| `unregister(name)` | 注销工具（MCP 退出时清理注册） |
| `get_schema(name)` | 查询工具 Schema（存在性检查） |
| `enabled_schemas()` | 返回所有已启用的 ToolSchema |

### safety.py — 安全防护

```
SafetyGuard
  ├── 工具名黑名单（blocked_tools）：对所有工具生效（含 MCP/内置/shell），正则匹配 call.name → 命中拦截
  └── shell 命令检查（仅 "shell"）：BLACKLIST（12 种危险模式 + 自定义）/ WHITELIST
```

工具名黑名单对所有工具生效；shell 命令检查仅对 `shell` 工具生效。违反时抛出 `SafetyViolation`。

### tools/sandbox/ 包 — 子进程沙箱后端（CommandRunner）

> **Phase 4 C1（2026-09-21）拆分**：原单文件 `sandbox.py` 拆为 `contracts.py`（SandboxTier / CommandRunner Protocol / profile+workspace 注入 slot）、`process.py`（进程监督内核：supervise / kill-reap / `cap_channel` 512KB 保头尾截断 + `decode_channel` **解码策略**（UTF-8 优先，失败再按平台控制台代码页——Windows 的 `oem`／`GetOEMCP`，zh-CN 即 GBK；截断路径**整段判一次编码**，否则会把切分点上的半个多字节序列误判成「不是 UTF-8」）/ `scrub_sensitive_env` / `reap_subprocess` 有界回收 / `PassthroughRunner` / command_runner slot）、`firejail.py`、`winjob.py`、`session.py`（会话目录 + SandboxSession）；`__init__` re-export 全历史公共名，导入面不变。`CommandRunner` Protocol 补 `available` property（三 backend 形状统一）。`git.py` / `engine/hooks.py` 复用 `reap_subprocess`（有界回收）+ `cap_channel` / `decode_channel`（截断与解码）内核——超时/取消/回收/截断/解码语义全仓统一；WinJob 补 env 剥离（V1）与有界 wait（V2）。

`shell` 等子进程工具的可注入执行抽象。默认 `PassthroughRunner`（等价 `create_subprocess_shell` 直接执行）；`SANDBOX_REQUIRED` 路径下 `ToolExecutor.execute_in_sandbox` 经 `bind_command_runner` + `bind_sandbox_profile` 注入配置的后端与 profile 名。注入走 `RuntimeSlot`（contextvar），与 skills 包等工具族一致；`DIRECT` 路径不 bind，取默认 Passthrough。

**FirejailBackend：** `profiles` dict（profile 名 → firejail 参数映射）供 `PolicyEngine` 裁决出的 profile 名选用（配置注入见下段）；`shutil.which` 构造期检测 firejail 可用性，不可用时 `run()` 优雅降级到 Passthrough（warn + 不崩溃）；Linux 进程组 killing（`start_new_session` + `os.killpg`）解决 `sh -c "cmd &"` 子孙泄漏；自动 `--private=<workspace_root>` OS 级文件系统隔离。⚠ `FirejailBackend` 仅隔离 shell 子进程、Linux-only；边界地位见 §4.18。

**DockerRunner（container 档首个实现，Epic 53 期一，2026-10-21）：** `tools/sandbox/docker.py`——每命令一次性容器、短命命令捕获形状（argv 组装恒以 `sh -c` 收尾，不容长命双向管道）；镜像经 `Settings.sandbox_docker_image`（默认 `heagent-sandbox:3.11`，与 `DockerRunner.DEFAULT_IMAGE` 同源，交叉校验测试钉住；构建文件 `docker/sandbox/Dockerfile` 以 digest pin 基座，`ARG BASE` 保留换源重建通道）；网络档按 brief D2（决策记录 `_bmad-output/epics/epic-53-容器沙箱档周期/brief.md`）——`--network=none` 默认，`SANDBOX_NETWORK=True` 才 bridge；workspace 挂载 FR-1 会话目录优先、缺省回落 workspace_root（firejail `--private` 同型语义，不给静默无挂载；回退链末端是启动进程 cwd ⇒ **启动目录即挂载面**：从盘根启动会把整盘以 9p 无缓存挂进容器，是 daemon/IO 卡顿的放大器，`scripts/start_heagent.ps1` 把 cwd 钉在仓库根）；容器硬化 `--cap-drop=ALL` + `no-new-privileges` + 非 root `sandbox` 用户；资源限额 `--memory`/`--pids-limit` 映射（`cpu_seconds` 无诚实映射，配置了打提示）；探测 = CLI 在 PATH 且 daemon 应答，resolver 期可用性闸（不可用告警回透传，事件/决策不再报 container 档），`run()` 内首触探测走线程池；daemon 健康心跳（`_HEALTH_PROBE_TTL_SECONDS` 30s 复用窗口 + **single-flight**：同批并发只付一次探针，锁内二次检查 TTL 复用结论）；失败**不**改可用性闸、不退透传；判定**分原因**——CLI **明确报错**（连不上 / 未启动）立即判死并短路，**纯超时**才重试（逐次递增预算 `_HEALTH_PROBE_TIMEOUTS`=3s→8s、间隔 `_HEALTH_PROBE_RETRY_DELAY_SECONDS`=0.5s））与「daemon 不可用」熔断（**慢不否决**：只有硬失败——CLI 明确报错、或命令超时后清理链 CLI 整体挂起——才进 `_DEGRADED_COOLDOWN_SECONDS`=120s 整窗；探针只是**超时**则放行本次命令并落 WARNING，把「卡」交给该命令自身的 timeout 与清理链兜底——同一份 CLI 卡顿也会拖慢 `docker run`，跳过命令等于替它放弃，2026-11-02 实测探针耗尽 11.5s 预算后把 cron 作业的 `date /t` 判成未执行，而 30s 后同一 daemon 只需 519ms；命令超时且清理链任一 CLI 调用撞 10s 上限 ⇒ 同样直接返回带 `[daemon-unresponsive]` 诊断的超时结果、不再 spawn；窗口内**半开复探**——心跳过期即再探一次，恢复**或仅超时**都立刻清零窗口并放行，只有仍明确报错才顺延窗口，修复「daemon 已恢复仍被拒满整窗」）——2026-11-02 三次事故形态分别是「每条超时都要白等满 timeout+40s 清理链且模型无从知道该重启 daemon」「9 分钟无 docker 活动后首批量并行命令的探针各耗尽预算、误判整窗 120s 全停、模型据此劝用户重启 Desktop（实测 2 分钟后同一 daemon 单条命令仅 610ms）」与「探针超时仍把命令判成未执行（cron 步骤被 0ms 跳过）」；超时/取消经 `docker kill -- <name>` 精确清理（kill 后校验：容器已因 `--rm` 删除即视为清理达成；仍存活或状态真不确定才升级 WARNING + `rm -f` 兜底；杀 CLI 进程不停容器；kill 与 inspect 双超时视为 CLI 整体挂起，跳过必然也超时的 `rm -f`）。仅覆盖 `execute_in_sandbox` 注入的 shell 路径；宿主内核 / Docker daemon 自身逃逸风险仍在——该档的边界地位见 §4.18（要素 2）。

**沙箱硬化配置接入：** 后端能力经四组配置项接入配置面（**默认全关闭，默认行为逐字节不变**）：① `SANDBOX_PROFILES`（JSON：profile 名 → firejail 参数表，如 `{"default": ["--seccomp", "--caps.drop=all"]}`）经 `container.default()` 传入 `FirejailBackend.profiles`——高级隔离参数（--seccomp/--caps 类）由此声明；② `SANDBOX_TOOL_PROFILES`（JSON：工具名 → profile 名）叠加进 `PolicyEngine.sandbox_profiles`，per-tool 差异化选用 profile（与代码内映射同形状，不引入新抽象）；③ 资源限额 `SANDBOX_MEMORY_LIMIT_MB` / `SANDBOX_CPU_SECONDS`（0=关闭）——firejail 映射 `--rlimit-as` / `--rlimit-cpu`（排在 profile 参数后、`--` 前），WinJob 映射 `JOB_OBJECT_LIMIT_JOB_MEMORY` / `JOB_OBJECT_LIMIT_PROCESS_TIME`（与恒开的 KILL_ON_JOB_CLOSE 按位或）；④ 进程数限额 `SANDBOX_NPROC_LIMIT`（0=关闭）——firejail 映射 `--rlimit-nproc`，WinJob 映射 `JOB_OBJECT_LIMIT_ACTIVE_PROCESS` + `ActiveProcessLimit`。**限额触发为显性失败**：子进程被终止 → 非零退出码经正常结果回传（对齐超时 `exit_code=-1` 先例），不静默截断输出；JSON 配置坏行/坏条目告警丢弃（对齐 `routing_pool_map` 容错）。⚠ 进程数限额两后端语义不对称：firejail 侧底层 `setrlimit(RLIMIT_NPROC)` 按**真实 UID** 计数（非 per-sandbox 作用域），WinJob 侧才是 job 作用域，故默认关闭。以上均属 defense-in-depth 层，边界地位见 §4.18。

**沙箱会话目录（FR-1，2026-08-26）：** `Settings.sandbox_session_workspace`（env `SANDBOX_SESSION_WORKSPACE`，默认 False）开启后，`EngineContainer.create_run_context` 经 `sandbox_session_dir(run_id)`（幂等目录解析；run_id 非法——空串/含分隔符/`..`/绝对路径——抛 `ValueError`）为每个 run 幂等创建 `<workspace_root 回退链>/.heagent/sandboxes/<run_id>/` 并写入 `RunContext.metadata["sandbox_workspace"]`——**根锚定 workspace_root 回退链**（参数→container→policy→cwd）而非进程 cwd，目录落在 file 工具围栏内；目录创建失败**显性抛异常**（消息含 try 外预推导的目标路径）、严禁静默降级。开关关闭时清除 caller 预含键、不建目录、不 bind，argv/cwd 与现状逐字节一致。`ToolExecutor.execute_in_sandbox` 检测到该键并校验（非 str/空串不 bind；目录缺失 bind 前抛 `RuntimeError` 显性失败）后经 `bind_sandbox_workspace` 送达后端——Firejail 复用既有 `_build_argv(workspace_root=)` 通道**优先**作为 `--private` 根（优先于构造期 workspace_root），WinJob 将其作为子进程 cwd（**目录约定 only，零文件系统/网络隔离**；边界地位见 §4.18）；`sandbox_runner=None` 时记 "sandbox_workspace ignored" warning 照旧透传；对子类 override 经 `inspect.signature` 探测做旧签名兼容。firejail 不可用时目录照常解析创建、后端照旧 warn + Passthrough 降级。

**沙箱后端强度分级（FR-2，2026-08-26）：** 引入 `SandboxTier(StrEnum)` 四档强度枚举 `passthrough(0) < job(1) < firejail(2) < container(3)`——`PassthroughRunner`→`passthrough`、`WinJobBackend`→`job`、`FirejailBackend`→`firejail`、`DockerRunner`→`container`（OS 级强隔离，Epic 53 期一落地，2026-10-21）。`CommandRunner` Protocol 新增 `tier` 属性，执行路径经 `ToolExecutor._runner_tier()` 查询当前后端档位（无后端→`PASSTHROUGH`；自定义 runner 缺 `tier`→`PASSTHROUGH` fail-safe），并随 `SANDBOX_REQUIRED` emit 事件 `details["sandbox_tier"]` 可观测。审批降级（`SandboxTier.can_relax_approval`）仅 `container` 档返回 True——弱后端（passthrough/job/firejail）一律维持原审批要求（NFR-2 测试锁定）；该判定点已于 Epic 53 期二（Story 53-4，2026-11-03）**接入** `PolicyEngine` 裁决：`PolicyEngine._container_relaxes_approval` 在「工具真进沙箱（`sandbox_tools` 且非 MCP）+ 后端 `tier.can_relax_approval` 为真 + 后端 `available` 为真 + provider 未抛错」四条全成立时放松审批，落 `PolicyVerdict.approval_relaxed=True` 并打 WARNING 留痕；放松**不**绕过沙箱授权，弱后端 / 降级 Passthrough / 宿主执行面（file/git）/ MCP 工具一律照旧要求审批（`tests/test_sandbox_approval_relax.py`）。

**沙箱 env 豁免（FR-3，2026-08-26）：** `scrub_sensitive_env(env, *, allowlist=...)` 新增 `allowlist` 参数（精确变量名、大小写不敏感）——命中 allowlist 的变量即使匹配敏感后缀也保留，其余仍剥离；未配置时行为与现状逐字节一致（默认全剥离）。配置入口 `Settings.sandbox_env_allowlist`（env `SANDBOX_ENV_ALLOWLIST`，逗号分隔）经 `sandbox_env_allowlist_set` property 解析，`_run_subprocess_shell`/`_run_subprocess_exec` 经 `_spawn_kwargs()` → `_env_allowlist()` 读 Settings 传入（2026-09-15 起两条路径共用同一 kwargs 构造，env 剥离不会分叉）。豁免仅作用于 env 剥离，不影响 `path_safety` 凭证 deny 与 `SafetyGuard` 凭证路径拦截。

**SandboxSession 会话生命周期（FR-4，2026-08-26）：** 引入 `SandboxSession` 会话作用域——同一 run 的连续 shell 命令共享同一 session workspace（40.1 目录）并**跨命令保持 cwd**：`run()` 以「cd 前缀 + 末尾上报（POSIX `printf $PWD` / cmd `cd`）回填 `session.cwd`」包装命令，多步操作（写→编译→运行）自然衔接；包装同时**保持用户命令退出码**（POSIX `exit "$__rc"` 复原 / Windows `call echo %^ERRORLEVEL%` 经 marker 行带回并由 `run()` 回填 `exit_code=`，修复包装后失败命令恒 `exit_code=0` 的缺陷；`exit N` 直退类命令 marker 缺失属固有限制，rc 仍正确）。会话经 `get_or_create_session(run_id, *, runner)`（runner 构造期注入，B1 seam）按 run 缓存、`bind_sandbox_session` 送达 shell handler（handler 优先走 session，无会话回落全局 runner）；`EngineContainer.close_run`（`AgentLoop._persist_and_cache` 尾部调用）teardown 按 `sandbox_session_keep`（默认 False=删除）清理会话目录。⚠ 会话只提供 cwd 保持约定（「cd 前缀 + 尾捕获」），WinJob 无文件系统隔离、Firejail 亦无完整隔离；边界地位见 §4.18。

**E40 补齐（2026-09-15，四项）：** ① **孤儿目录 GC（E40-D1）**——crash / SIGKILL 的 run 不走 teardown，其 `<workspace>/.heagent/sandboxes/<run_id>/` 由 CLI/GUI 启动时的 `housekeeping.prune_sandbox_dirs` 按 `sandbox_dir_retention_days`（默认 7 天）回收：判活取「目录 + **直接子项**」最新 mtime（正在写的 run 不被删；只扫一层，成本有界），非目录条目与符号链接一律不动（符号链接记 warning，绝不穿透），单趟删除数有上限、删除失败记 warning 留待下次启动。约定根由 `tools.sandbox.sandbox_sessions_root(workspace)` 单一表达（创建方与回收方共用，防空漂移）。② **目录对模型可见（E40-D2）**——`_build_system()` 在本 run 会话目录**真正生效**（存在真实沙箱后端）时注入 `<shell-workspace>` 块，告知绝对路径与「file 工具相对路径按 workspace root 解析」的差异；开关开但后端缺席（passthrough）时**不报路径**（与真实 cwd 不一致比不提示更坏）。③ **WinJob cwd 可测缝（E40-D3）**——子进程启动收敛到 `_winjob_spawn(command, workspace)` 单点（未 bind 时不传 `cwd`，与改动前逐字段一致），使该决定可在非 Windows 平台被断言（原实现写在 `run()` 两条 `Popen` 分支里，Linux CI 整段跳过）。④ **CLI/GUI 平权（E40-D4）**——`--sandbox-session-workspace` / `--sandbox-session-keep`（含 `--no-...`）三态覆盖 `Settings`（未传标志时行为与改动前逐字节一致）。

### call_summary.py — 工具调用「作用对象」摘要（纯展示辅助）

`summarize_tool_call(name, arguments)` 把一次调用归纳为**单行**说明：读写哪个文件、
执行哪条命令、抓哪个 URL、委派给哪个角色的子 Agent（如 `docs/framework.md`、
`src — *.py`、`0 9 * * * — 生成 AI 新闻摘要`、`coder — 实现登录模块`）。
该摘要出现在四个展示面：CLI 提示行 `[calling <tool> → <target>]`
（`cli.display._print_stream_event`，在执行**前**发出；整行由
`cli.display.format_activity_line` 按**显示列**裁成单行——CJK 宽字符计 2 列，超宽折行会与
进度行的 `\r` 重绘叠加成「同一条命令重复显示」的残影）、TUI 聊天日志、工具事件的
`target` 字段（`EngineEvent.target`——独立成段而非埋进 `details`，见 4.12）、以及状态栏的
`🔧 <tool> → <target>` 段（`loop.active_tool`，暂停/恢复时据此判断卡在哪个工具）、
GUI 状态栏与 TUI 聊天日志（`gui/bridge.py` 流式路径与 `gui/observers.py` 引擎事件路径同口径）。
单次模式（`python -m heagent "..."`，走 `run()` 无流式事件）跑完另由
`cli.display.show_tool_activity` 回显 run 级台账 `loop.tool_activity`（**调用尝试**：
执行前登记，被阻止 / 命中缓存的调用同样留痕；同目标去重、超 20 条折叠为一行计数），
保证「执行中没有提示行」的场景事后仍有记录。

纯函数、零 heagent 依赖，是该信息的**唯一来源**（`AgentLoop.run_stream` 的流式事件、
`ToolExecutor` 工具事件的 `target` 字段、`loop.active_tool` 与 `tool_activity` 共用，
避免多处映射漂移）。契约：
**永不抛异常**（参数形状异常退化为空摘要，展示逻辑不得中断 agent 循环）、只回显参数
不推断语义、单行折叠（换行 / 连续空白折叠为单空格，防终端串行）。长度：路径类
72 字符、自由文本（子 Agent 任务 / 记忆事实）40 字符，超长加省略号；**shell 命令不截断**
（全文保留，只折叠空白）——截断后的命令无法判断「它到底跑了什么」，是审查与审计场景里
信息损失最大的一类参数（`_NO_TRUNCATE_TOOLS`）。

`<tool> → <target>` 的**拼接**同样同源：`activity_label(name, target)`——CLI 提示行 / 状态行、
GUI 聊天日志 / 状态栏、工具活动台账统一经它拼接。各展示层自行拼箭头曾是漂移源头
（2026-09-14 复核：GUI 两条事件路径一个带 target、一个不带，同一状态字段被互相覆盖）。

### path_safety.py — 工作区路径校验（文件工具）

文件类工具（`file_read` / `file_write` / `file_search` / `content_search`）写入前调用
`resolve_workspace_path(path)`，解析后若逃逸出当前工作区根（含 `../` 越界、绝对路径指向外部），
抛出 `WorkspacePathError`。`workspace_root()` 默认取 `Path.cwd()`，`set_workspace_root()`
提供测试可注入的覆盖入口（无需 monkeypatch cwd）。

围栏算法集中在 `resolve_under_root(path, root)`：`engine.policy._validate_paths()` 的执行前
预检与各 file 工具的 handler 守卫（`resolve_workspace_path`）共用同一实现——两层是有意的纵深
防御（policy 预检 + handler 守卫），不再是两份可各自漂移的副本。root 来源策略是两层唯一有意
差异：policy 用 `context/self.workspace_root`（皆空则放行），handler 用 `workspace_root()`
（RuntimeSlot → override → cwd）。

另含**凭证 deny**与**内部状态读 deny**（借鉴 hermes `file_safety.py`，2026-08-24）：`build_write_denied_paths` / `build_write_denied_prefixes` 拦截对凭证文件（`~/.ssh/*` / `~/.aws/*` / `.env` / `.netrc` 等）的写入；`check_read_denied` 拦截对 secret-bearing 文件名（`.env` 等）与 `.heagent/` 内部状态目录（sessions/ledger/runs/memory/skills）的读取。**项目级可配置入口（2026-09-17）**：`.heagent/path_deny.json`（workspace 围栏锚定 + 进程级懒缓存）允许收紧（追加 deny 项）或放行显式列举项（精确路径 / basename 豁免；内部状态目录 deny 不接受豁免），无整体关闭入口、fail-safe 默认仍拒。deny 与围栏是**并列的独立层**（先围栏后 deny），git 工具只走围栏不接 deny。⚠ 均为 defense-in-depth 启发式层，边界地位见 §4.18。

### edits.py — 编辑原语支撑（行尾保真 / diff 回执 / 落盘前快照）

`file_write` / `file_edit` 共用的编辑护栏（2026-09-14 新增）：

- **行尾与 BOM 保真**：`read_text_file` / `write_text_file` 走 `read_bytes` / `write_bytes`
  ——`Path.read_text/write_text` 默认做 universal-newline 翻译（Windows 上把 LF 文件写成 CRLF），
  编辑类工具若破坏行尾即是真实事故面（本仓 2026-09-08 行尾治理）。读写两侧都保真，才能保证
  「只改一处、其余字节不动」。`file_read` 与 `file_edit` **共用同一文本形态**（去 BOM + 行尾
  归一为 `\n`），使模型从 `file_read` 复制的片段可直接用于匹配（否则 BOM 会造成隐形失配）。
- **diff 回执**：`render_diff` 回 `+N -M` 与有界 hunk 预览（行数 40 / 字符 4000 双限 + 截断标注）；
  `file_write` 回执含 diff，不再是裸的 `wrote N chars`——模型与用户都能在回执里自证「实际改了什么」。
- **落盘前快照**：`snapshot_before_write` 复制旧字节到
  `<workspace>/.heagent/tmp/edit-snapshots/<run_id>/` 并追加 `manifest.jsonl` 台账
  （`at` / `op` / `path` / `snapshot` / `bytes`）。run 绑定由 `AgentLoop._runtime_scope` 经
  `bind_edit_snapshot_run(run_context.run_id)` 完成；未绑定（直接调工具 / 子进程 / 测试）退化为
  工作区级共享目录。快照是 **best-effort**：文件超 2 MB 或 I/O 失败均跳过快照、不阻断编辑
  （回执不出现 snapshot 行，仅记日志）。快照 GC 见「五、已知缺口」。
- ⚠ 行尾保真与快照均属**可用性**护栏（快照目录位于 workspace 内、可被 shell 删除），边界地位见 §4.18。

### builtins/ — 29 个内置工具（运行时 ToolRegistry 注册数，2026-11-16 实计）

**基础工具（6 个）：**

| 工具 | 文件 | 功能 |
|------|------|------|
| `shell` | `shell.py` | 执行 shell 命令 |
| `file_read` | `file.py` | 读取文件内容 |
| `file_write` | `file.py` | 全量覆写文件（回 `+N -M` diff 摘要，写前留快照） |
| `file_edit` | `file.py` | 精确替换文件中的唯一片段（失配/歧义即报错，磁盘零改动） |
| `file_search` | `search.py` | 按文件名搜索 |
| `content_search` | `search.py` | 按内容搜索文件 |

**技能管理工具（7 个，`skills.py`）：**

| 工具 | 功能 |
|------|------|
| `skill_create` | 创建新技能（SKILL.md + 目录结构；支持 triggers / negative_triggers / priority 匹配元数据） |
| `skill_update` | 更新已有技能内容（仅改非空字段） |
| `skill_list` | 列出所有已注册技能 |
| `skill_load` | 按规范化技能名只读完整 SKILL.md（不执行 steps/scripts、不读取任意资源；受手动读取 token 预算限制） |
| `skill_delete` | 删除指定技能 |
| `skill_curate` | 列出超 N 天未使用的过期技能（含使用次数/最后使用时间） |
| `skill_archive` | 归档技能到 `.archive/`（不参与匹配/列出，可恢复） |

**记忆管理工具（2 个，`memory.py`）：**

| 工具 | 功能 |
|------|------|
| `fact_add` | 保存一条事实到长期记忆（**工具描述即写侧闸门**：只写改变未来行为的结论，不收过程叙述/状态记账——`@tool` 只取 docstring 首行，故该准则走显式 `description=`；2026-09-24 追加，见 4.6） |
| `profile_update` | 更新用户画像的指定部分 |

**Cron 管理工具（3 个，`cron.py`）：**

| 工具 | 功能 |
|------|------|
| `cron_add` | 创建定时任务（cron 表达式） |
| `cron_list` | 列出所有已调度任务 |
| `cron_remove` | 删除指定任务 |

**子 Agent 委派工具（3 个，`subagent.py`）：**

| 工具 | 功能 |
|------|------|
| `task_delegate` | 将单个任务委派给隔离的子 Agent（可传 `role`=planner/coder/tester/supervisor 角色化，或 `system` 自定义提示词；独立上下文+迭代预算）执行；**返回结构化 JSON** `SubTaskOutcome`（status ok/failed/error + role/task/iterations/run_id/output，P5-3） |
| `task_parallel` | 并行执行多个子任务（`tasks_json` 传 JSON 数组，`run_parallel()` 汇总；同 `role`/`system`）；返回 `{"status": ok/partial/error, "outcomes": [SubTaskOutcome...]}`（P5-3） |
| `task_status` | 读回本 run 已完成的委派步骤（`run_context.metadata['completed_steps']`，含 iterations/run_id，跨窗口重置存活，P2/P5-3） |

**Web 工具（2 个，`web.py`）：**

| 工具 | 功能 |
|------|------|
| `web_fetch` | 抓取 HTTP URL 内容（`@tool(read_only=True)`，`max_length` 截断；SSRF 围栏 + 流式截断 + 重定向再校验） |
| `web_search` | 按主题检索（`@tool(read_only=True)`，引擎经 `WEB_SEARCH_ENGINE` 声明可插拔、默认 Tavily；条数硬切片 + 摘要/title/url 钳位 + 汇总 ≤20000 字符确定性预算 + `guard_content` 围栏；无密钥时工具常在、调用显性报错） |

**Git 工具（4 个，`git.py`，均 `@tool(read_only=True)`）：**

| 工具 | 功能 |
|------|------|
| `git_status` | 仓库工作区状态 |
| `git_diff` | 提交/工作区差异 |
| `git_log` | 提交历史 |
| `git_blame` | 行级作者追溯 |

技能工具在 `AgentLoop` 接收 `SkillStore` 时激活；记忆工具在接收 `FactStore`/`ProfileStore` 时激活；
Cron 工具在接收 `JobStore` 时激活；子 Agent 工具由 `AgentLoop._runtime_scope` 在每次 run 注入委派回调（`agent/delegation.build_subagent_delegates`）激活，run 退出即解绑（单次与交互模式均如此）。委派结果经 `_record_step()` 写入 supervisor 的 `metadata['completed_steps']`（含 iterations/run_id，跨窗口重置存活）。未注入时工具返回 `status=error` 结构化错误，不抛异常。`task_delegate`/`task_parallel` 另受**递归深度闸门**约束：当前 loop 的 `depth` `>= Settings.subagent_max_depth`（默认 3）时直接返回 `status=error`、不再构造子 Agent，防止 LLM 自我委派无限递归；根 loop `depth=0`，SubAgent 创建的子 loop 为父深度 +1。子 Agent 的迭代预算按「显式参数 > 角色显式声明 > `Settings.subagent_max_iterations`（默认 20）」解析；角色未声明即跟随配置（内置 `tester` 已改为不声明，使验证器预算可调）。

---

## 4.11 MCP 集成 (`tools/mcp/`)

MCP server 桥接层（非必要功能，已交付）。连接时发现+注册到 `ToolRegistry`，退出时 unregister。

| 模块 | 说明 |
|------|------|
| `config.py` | `MCPConfig` + `load_mcp_config()`（`.mcp.json` + `${ENV}` 插值） |
| `mapping.py` | `mcp_tool_to_schema()`（namespace `<server>__<tool>`）、`bridge_result()` |
| `client.py` | `TransportOpener` Protocol + `default_transport_opener`（stdio/http 分派 + 握手），构造期可注入（Phase 4 C2） |
| `registry_bridge.py` | `RegistryBridge` — server 工具 + 桥接工具注册/注销单一入口，命名冲突策略（Phase 4 C2） |
| `manager.py` | `MCPClientManager`（生命周期 façade）— 并发连接+发现+注册，单 server 失败隔离；`discovery_failures` 结构化记录失败，cli 渲染 stderr（不隐藏发现错误） |
| `sdk.py` | `import_mcp()` / `mcp_types()` / `require_sdk()` — mcp SDK 的**唯一导入通道**：本包任何模块都不得在 import 期 `from mcp… import …`（那会让缺可选依赖时 `import heagent` 直接炸）；缺包抛 `McpSdkMissingError`（`E_TOOL_MCP_SDK_MISSING`，带 `pip install "heagent[mcp]"` 提示） |

⚠ MCP 工具与内置工具同等不可信（执行前拦截 + 返回启发式围栏均已落地）；这两层的边界地位见 §4.18。

**安装面（Story 67.9）**：`mcp` 自核心依赖移到可选 extra ⇒ 基础安装（6 项）不含 MCP SDK，需要 MCP 时 `pip install "heagent[mcp]"`（`dev` extra 已含它，测试与 CI 不降级）；缺包只影响 MCP 能力，`import heagent` 与普通 CLI 照常。

---

## 4.14 技能资源读取 TOCTOU 评估与安全打开加固（Epic 46.1/46.2）

`SkillPackage` 的入口、step、reference、template、asset 和 script 均采用“`resolve_under_root` 解析 ->
加固打开（POSIX 逐组件 `openat` / 整路径 `open` 回退）”。Phase 4 C4（2026-09-21）起该实现收敛为
`tools/path_safety.open_text_under_root` 单一入口，`SkillPackage`、`SkillStore` 与 importer 的 manifest.lock
读取全部接入（契约测试钉 `os.open` 白名单）；-> `fstat()` 常规文件校验 -> 已打开 descriptor 读取”。这能拒绝
绝对路径、路径穿越、解析后越界符号链接，以及支持 `O_NOFOLLOW` 的平台上最终组件在打开前被替换为符号链接的情形。
不支持该标志的平台保留兼容打开；特征证据与回退覆盖见 `tests/test_skill_packages_toctou.py`，
评估、复核与实现规格见 `_bmad-output/epics/epic-43-46-目标级工作流周期/epic-46-技能资源并发替换安全评估/`。

**内容完整性校验（2026-09-23 交付）**：读路径不再只做围栏与常规文件校验——若包根有合法的
`manifest.json`（**复用**渲染器 `_bmad/scripts/render_skill.py` 的既有产物，其 `outputs` 为
「相对 POSIX 路径 → sha256」，不为本特性新增文件或 lock 字段），则读到的**原始字节**摘要必须与清单一致，
否则 `SkillPackageResourceError("content hash differs from manifest.json")` 显性失败。
摘要取原始字节（`path_safety.read_text_with_digest_under_root`）而非归一化文本——固有 CRLF 的文件同样可校验；
无 `manifest.json` 的包（手写技能占多数）行为**逐字节不变**——凭据读取**先 stat 再读**（`is_file()` 门控），
未托管包零额外 `os.open`（读取次数刻画测试与 `O_NOFOLLOW` 的 EINVAL 兼容回退测试依赖此点，
2026-09-23 由 Linux 等价验证抓出：无门控时会多开一次文件），凭据不可用（损坏 / `outputs` 形状不符）时
跳过并记 warning（`manifest.json` 是通用文件名，可能属于别的工具，不据此拒读）。
代价与边界：渲染/导入后被**手工编辑**的包将拒读（有意，fail-loud；渲染器对漂移本就 `RenderError`）；
清单只钉它列出的文件，包内新增文件不在校验范围；能写该目录者本就能直接改写 `SKILL.md`，故本项只是 defense-in-depth 层（边界地位见 §4.18）。

**导入器凭据（2026-09-28 交付，活动台账 A1④）**：导入形态（`skills/skill_importer.py` 物化到
`.heagent/skills/<id>/`）的凭据不在包内，而在 **skills 根目录的兄弟文件** `manifest.lock`——它是整批
导入的索引，故读侧取 `root.parent/manifest.lock` 中本包条目的 `resources`（与渲染器 `outputs` **同形**：
「相对 POSIX 路径 → sha256」）。判定语义与渲染器凭据一致地保守：无 lock ⇒ `{}`（只多一次 stat、不 open）；
损坏 / 无本包条目 / `resources` 形状不符 ⇒ warning 后跳过；**老 lock**（2026-09-28 之前只钉入口
`source_hash`）⇒ **静默**跳过（升级路径，下一次导入自动补齐钉）；命中则逐资源比对，漂移报
`content hash differs from manifest.lock`。条目定位先按规范化 `destination_path`、再按 `canonical_id`
兜底（凭据是内容寻址的，包被移动后仍能比对）；两种凭据同时存在时**渲染器优先**（它是包内容的直接
生产者）。导入侧同轮把 `resources` 写进 lock（覆盖 `SKILL.md` 与 `references` / `templates` / `assets` /
`scripts` 下的全部常规文件），并在**落地之前**复核物化目录的逐文件摘要
（`materialized package differs from source`，失败不留半成品）。

**两个加固打开通道（2026-09-27 起）**：① **POSIX 逐组件 `openat`**（`_WALK_SUPPORTED` 为真时）——
从 root 起用 `dir_fd` 逐组件打开，每个**中间目录**组件用 `O_DIRECTORY|O_NOFOLLOW`、叶组件用
`O_NOFOLLOW`（root 自身不做 `NOFOLLOW`：工作区经链接指向真实目录是合法布局）；围栏之后、打开之前把
**中间目录**换成符号链接的竞态因此在那个组件上失败（`ELOOP` 并点名组件——注意 `O_DIRECTORY|O_NOFOLLOW`
撞上符号链接时 Linux 回 `ENOTDIR`，实现里对两种 errno 都做一次「是不是链接」的归因）。能力判定
**在导入期算一次**：`os.open in os.supports_dir_fd` 是函数对象身份比较，任何把 `os.open` 包一层的
观测/测试代码都会让它变假、把整条硬化**静默**降级回宽窗口通道（2026-09-27 实测踩到，用
`test_walk_gate_matches_platform_capability` 正面钉住）。② **整路径 `open` 回退**（Windows 无
`dir_fd`）：语义与硬化前逐字一致、窗口与那时一样宽（`test_without_dir_fd_the_resolved_path_is_opened_once`
钉住该形状）。

**仍未消除的残余（如实）**：① Windows 无 `dir_fd` ⇒ 只保护最终组件；② 组件级竞态不为零——每个组件
各自一次原子 open，组件之间仍有时间差；③ 恶意挂载、更高权限宿主进程与「可信导入 snapshot」这类
非竞态面不受影响——`manifest.lock` 的 `resources` 哈希已于 2026-09-28 交付（见上），但**可信导入
snapshot**（物化来源自身的可信性）与「凭据文件与包由同一写者掌控时可被同时改写」仍属未闭合面。
不声称已完成 TOCTOU 防护；所有方案仍是 defense-in-depth 层（真边界见 §4.18）。实现与判据见 `tests/test_skill_packages_toctou.py`（形状用例 +
「替换中间目录」竞态用例，仅 POSIX 跑；变异体 5/5 精确变红）、`tests/test_skill_package_integrity.py`
（两类凭据的读侧语义 + 未托管包零行为变化，变异体 6/6 精确变红）与 `tests/test_skill_importer.py`
（钉整包 / 漂移拒导 / 老 lock 补齐 / 落地前复核）；Ask First 授权与证据见活动台账 A1 条目。
