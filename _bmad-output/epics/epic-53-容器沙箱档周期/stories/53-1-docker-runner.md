# Story 53-1 · DockerRunner 与注入接线

状态：**done**（2026-10-21 判据全绿 + 变异体 6/6 精确变红；真实 daemon 链路已由 53-2 integration 3/3 实证。2026-10-24 用户 walkthrough 验收通过）。

## 范围

按 `epics.md` Story 列表行交付；冻结决策见 `../brief.md` D1–D4。

## 交付物

- `src/heagent/tools/sandbox/docker.py`：`DockerRunner`（`tier=CONTAINER`）实现 `CommandRunner`
  Protocol。每命令一次性容器（`--rm --pull=never`），`--network=none` 默认（D2），workspace
  经 `as_posix()` 形态挂载到 `/workspace` 并作工作目录；**不传 `--env`** ⇒ 容器内零宿主 env
  （env 驻隔离落点在容器边界，docstring 钉口径）。超时/取消双路 `docker kill -- <name>` + 有界
  回收；不可用降级 WARNING + Passthrough；**运行期 docker 错误显性失败**（不降级——静默回透传
  会伪造「已在沙箱里跑」的假象）。
- `tools/sandbox/__init__.py`：注册出口 `DockerRunner`。
- `engine/container.py`：`_resolve_command_runner` 增 `docker` 分支（53-1 期模块默认值构造；
  Settings 配置面在 53-2）；`SandboxDecision` 非 firejail 分支由硬编码 "winjob" 通用化为按
  后端名 + `available`；FS 隔离判定 `in {"firejail", "docker"}`；网络隔离判定接
  `DockerRunner.isolates_network()`；enforce 告警面放行 container 档。

## 验收证据（2026-10-21 亲跑）

- 判据 11 条（`tests/test_sandbox_docker.py`）：档位/降级资格、CLI 缺席、daemon 不可达、探测
  成功、降级 WARNING、argv 形状钉死（无 `--env`）、会话目录挂载 + 结果如实回传、超时 kill、
  取消 kill、运行期错误不降级、resolver 分支。
- 变异体 **6/6 精确变红**（`.heagent/tmp/mutate_docker.py`：网络旗标删 / 挂载删 / env 泄漏
  注入 / 静默降级 / 超时免杀 / 结果静默回透传）；字节还原后基线复绿（11 passed）。
- 回归：既有沙箱 175 passed + 1 skipped；`test_engine_p0` 67 passed；ruff check/format、
  mypy（两文件）全绿。
