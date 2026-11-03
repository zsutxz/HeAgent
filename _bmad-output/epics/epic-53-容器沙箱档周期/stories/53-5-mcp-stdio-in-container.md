# Story 53-5 · MCP stdio server 进容器（期二 D53-1）

状态：**done**（2026-11-03 判据 11 条全绿 + 变异体 6/6 精确变红 + 六门 all passed；待用户 walkthrough 验收）

## 范围

把 `.mcp.json` 声明的 stdio server 从「SDK 自行 `anyio.open_process` 宿主直跑」改为「经容器档
后端拉起」，闭合 AGENTS.md / `docs/frame.md` 五 登记的中-高缺口；Streamable HTTP server 不在范围。

## 冻结决策（D-53-5-1 … D-53-5-5）

- **D-53-5-1 不复用 `CommandRunner`**：SDK 的 stdio 子进程是长命双向 JSON-RPC 管道，而
  `CommandRunner` 是 `sh -c` 短命捕获形状（epic-53 实施约束 3 明列）。做法 = 把 SDK 要 spawn 的
  子进程**换成 docker CLI**：`docker run -i … <image> <cmd>`，容器内进程的 stdin/stdout 即管道。
- **D-53-5-2 开关复用 `SANDBOX_BACKEND`**：仅当解析为 `docker` 时启用容器包裹（其它后端没有容器
  档能力，套 docker 包裹等于违背用户选择）；不新增 MCP 专用开关，避免两个隔离旋钮漂移。
- **D-53-5-3 env 只透传声明项**：对 `.mcp.json` 该 server 显式声明的 env 键发 `-e KEY`（不带值 ⇒
  docker 从 CLI 进程 env 取值，**值不进 argv**）；宿主其它变量一律不进容器（与 DockerRunner
  「不传 `--env`」同口径）。
- **D-53-5-4 显性降级（用户裁定）**：CLI 缺席 / daemon 不应答 / 探测抛错 ⇒ 仍按原样在**宿主**
  拉起 server，但**每次连接**打 WARNING；探测结果按 30s TTL 复用（避免每个 server 每次连接都付
  `docker version`）。不选 fail-closed：MCP 不可用会连带交互模式整体不可用，取舍由用户裁定。
- **D-53-5-5 硬化旗标与 DockerRunner 同源**：`--cap-drop=ALL` / `no-new-privileges` / 非 root
  `--user sandbox` / `--pull=never` / `--label heagent.mcp=stdio`（孤儿容器可核查）/ 资源限额旗标
  **必须排在 IMAGE 之前**。

## 交付物

- `src/heagent/tools/mcp/stdio_sandbox.py`（新）：`StdioSandboxSpec`（Pydantic + 私有探测缓存）、
  `build_run_argv`、`container_name`、`stdio_params`（含显性降级）。
- `src/heagent/tools/mcp/client.py`：`default_transport_opener(cfg, *, stdio_sandbox=None)`。
- `src/heagent/tools/mcp/manager.py`：`MCPClientManager(stdio_sandbox=…)` + `_resolve_transport_opener()`。
- `src/heagent/tools/mcp/__init__.py`：导出 `StdioSandboxSpec`。
- `src/heagent/tools/sandbox/docker.py`：新增公共 `docker_available()` 包装（原 `_docker_available` 语义不变）。
- `src/heagent/cli/console.py`：`_stdio_sandbox_spec(settings)` + `_mcp_lifecycle` 接线。
- `src/heagent/tools/mcp/mapping.py`：两处安全注释更新（不再声明「不经任何沙箱」）。
- `tests/test_mcp_stdio_sandbox.py`（新）：argv 形状 / env 透传 / 限额顺序 / 容器名 / 三条降级路径 /
  TTL 复用 / 零回归 / manager 与 CLI 接线。
- 文档：`docs/frame.md` §4.19 要素 2 + 五 缺口行、`docs/sandbox.md` §3.1、`AGENTS.md` 两处。
- 台账：`../deferred-work.md` D53-1 → done；`../epics.md` 53-5 行；`sprint-status.yaml` 53-5 行。

## 验收判据

| # | 判据 | 期望 |
|---|------|------|
| 1 | `build_run_argv` 形状 | `docker run -i --rm --pull=never` 起头；硬化旗标齐；IMAGE 之后是 server command + args（无 `sh -c`） |
| 2 | env 透传 | 只对声明键发 `-e KEY`（排序、无值），**值不出现在 argv** |
| 3 | 限额顺序 | `--memory` / `--pids-limit` 均排在 IMAGE 之前；0 值不发旗标 |
| 4 | 挂载与网络档 | `-v <ws>:/workspace -w /workspace`；`network=bridge` 时 `--network bridge` |
| 5 | 容器名 | 同一命令指纹稳定、每次启动随机后缀唯一；不同 args 指纹不同 |
| 6 | 可用 ⇒ 容器包裹 | `params.command == docker_path`，`params.env` 保留声明 env |
| 7 | 不可用 ⇒ 显性降级 | 回宿主参数 + **每次**连接 WARNING（探测只付一次） |
| 8 | 探测抛错 ⇒ 降级 | 回宿主 + WARNING（fail-safe 方向 = 显性降级） |
| 9 | 无 spec ⇒ 零回归 | 参数与既有逐字段一致 |
| 10 | manager 接线 | 有 spec ⇒ `partial(default_transport_opener, stdio_sandbox=spec)`；注入 opener 优先；无 spec 用 SDK 原实现 |
| 11 | CLI 接线 | `SANDBOX_BACKEND=docker` ⇒ spec 带 image/network/workspace/限额；其它后端 ⇒ `None` |

## 不做 / 边界

- 不做 Streamable HTTP server 的容器化（远程端点，无本地进程可包）。
- 不为容器内 server 提供额外依赖安装通道：镜像里没有的二进制**显性失败**（镜像供给属配置面）。
- 边界地位不变：容器档是 OS 级强隔离兜底，**不是绝对边界**。

## 实测结果（2026-11-03 亲跑，容器沙箱 + `.heagent/tmp/py311-venv-linux`）

| 命令 | 实测 |
|------|------|
| `python scripts/quality_gate.py`（`PATH` 前置 venv bin，六门一次跑完） | **all gates passed**：回归/覆盖率 **4249 passed, 50 skipped, 25 deselected**（217.51s）、覆盖率 **92.57%**（≥87%）、ruff lint / format（379 files）、`mypy src`（178 files）、`bandit -r src/ -ll`（High 0 / Medium 0）全绿 |
| `pytest tests/test_mcp_stdio_sandbox.py -q` | **16 passed** |
| `pytest tests/test_mcp_stdio_sandbox.py tests/test_mcp_manager.py tests/test_mcp_config.py tests/test_mcp_cli.py -q` | **111 passed**（3.97s，MCP 面零回归） |
| `pytest tests/test_security_posture_contract.py -q` | **58 passed**（契约判据随 D53-1 闭合更新，见下） |
| `python scripts/mutation/mutate_mcp_stdio_sandbox.py` | 基线 16 passed；**存活变异体 0/6**（M1 不降级 2 failed / M2 不传 env 1 / M3 删 `--cap-drop=ALL` 1 / M4 删 `-i` 2 / M5 限额排到 IMAGE 之后 1 / M6 降级不告警 1） |
| `python scripts/mcp_stdio_container_probe.py --mode fake` | **VERDICT: PASS**——整链：真 `stdio_client` → 替身 docker CLI（应答 `version` 过可用性闸）→ 真 MCP stdio server → 真 JSON-RPC 握手 → `tools/list` → `tools/call`；替身收到的 argv 实测 `image=PROBE_IMAGE`、`command=['python', '<server>.py']`、`env_names=['HEAGENT_MCP_PROBE_TOKEN']`、`workdir='/workspace'`；降级支路 PASS（docker 路径不存在 ⇒ 宿主直跑、docker 从未被调用、env 照常透传） |
| `python scripts/mcp_stdio_container_probe.py --mode docker` | **未跑**：容器沙箱内无 docker CLI 也无 `/var/run/docker.sock`（实测 `command -v docker` 空、socket 不存在）⇒ 真 daemon 模式必须在**宿主**执行，属待用户拍的实物验收项 |

**连带修正的契约判据**（`tests/test_security_posture_contract.py`，属本 story 交付面）：

- `test_mcp_annotations_passthrough_marks_known_gap_unclosed` → `…_marks_residual_exposure`：
  关键词由「D53-1 未闭合」改为「53-5 + 暴露面」（降级宿主时仍是暴露面）。
- `test_mcp_canonical_section_points_back_to_the_stdio_gap`：关键词由「D53-1」改为「53-5 + 显性降级」。
- 两条均保留「annotations 自声明 / 不可信」这一不变断言——本 story 不扩大任何安全宣称。

