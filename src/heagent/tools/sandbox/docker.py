"""Docker 容器沙箱短命命令后端（``SandboxTier.CONTAINER`` 档首个实现，Epic 53 期一）。

把 ``shell`` 工具的每条命令包进一次性容器（``docker run --rm``）：workspace 读写挂载到
容器内固定路径 ``/workspace`` 并作为命令工作目录——shell 工具的既有契约就是「在 workspace
里改文件」，不给写挂载等于把工具做残；隔离由「workspace 之外不可见」达成（容器内只见
挂载点与镜像在，宿主其余路径零可见）。网络默认 ``--network=none``（brief D2 冻结决策：
工具执行不需要网；bridge 须显式配置开启——配置面在 53-2 落地，本模块只吃构造参数）。

⚠ 边界口径：OS 级强隔离兜底，**非绝对边界**（宿主内核 / Docker daemon 自身的逃逸风险
仍在）。env 隔离发生在**容器边界**：``docker run`` 不传 ``--env`` ⇒ 容器内看不到宿主任何
环境变量（宿主侧 docker CLI 进程继承宿主 env 与既有后端一致，不是暴露面——载荷在容器内）。

降级立场：``available=False``（CLI 缺席 / daemon 不可达）⇒ WARNING + 退 Passthrough
（与 winjob 同口径）；**运行期 docker 错误不降级**——被选中却不工作就该显性失败（容器
以非零码退出，stdout/stderr 经 ``_format_result`` 如实回传），静默退回透传会伪造「已在
沙箱里跑」的假象。

容器硬化与限额（审查修复批，2026-10-21）：``--cap-drop=ALL`` + ``no-new-privileges`` +
非 root ``sandbox`` 用户（Dockerfile 同名创建，防 root-in-container）；资源限额
``memory_limit_mb`` → ``--memory``、``nproc_limit`` → ``--pids-limit``（0=关闭，默认零
旗标）；``cpu_seconds`` 无诚实映射（``--cpus`` 是速率上限不是 CPU 时间上限，硬映射会伪装
成已生效）——由 resolver 在配置了的时候打**诚实提示**而非假装生效。kill 失败升级 WARNING
并 ``docker rm -f`` 兜底（孤儿容器带 workspace 写挂载是真实暴露面）。运行期 digest pin：
构造时传 ``digest=`` 则首 run 前 ``docker image inspect`` 校验本地 tag 的 repo digest，
不符显性拒绝（本地 tag 可被 retag 静默换载荷）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
import subprocess
import time
import uuid
from typing import TYPE_CHECKING

from heagent.tools.sandbox.contracts import SandboxTier, get_sandbox_workspace
from heagent.tools.sandbox.process import (
    _REAP_WAIT_TIMEOUT,
    _TIMEOUT_RESULT,
    PassthroughRunner,
    _format_result,
)

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# 与 Settings.sandbox_docker_image 默认一致（tests/test_sandbox_docker.py 交叉校验钉住双真源）。
DEFAULT_IMAGE = "heagent-sandbox:3.11"
# 容器内固定工作目录：宿主 Windows 盘符路径无法镜像进 Linux 容器，挂载点即工作目录。
CONTAINER_WORKDIR = "/workspace"
# 容器内非 root 用户（docker/sandbox/Dockerfile 同名创建）：命令默认以其运行。
CONTAINER_USER = "sandbox"

# daemon 心跳探测的复用窗口（秒）：健康时最多每 30s 付一次 ``docker version``（Windows 约
# 150–300ms），换来「daemon 挂起后下一次调用 5s 内失败」而不是白等满命令超时（2026-11-02）。
_HEALTH_PROBE_TTL_SECONDS = 30.0
# 探测的逐次 CLI 超时预算（秒）：Docker Desktop 在负载下有数秒级卡顿，且 WSL2 backend 在长时间
# 无 docker 活动后会「冷启动」——2026-11-02 13:58 实测：9 分钟无 docker 活动后三条并行 shell 的
# 探针全部耗尽旧预算（5s×2，每条 duration≈10.5s）、判死并熔断 120s，而 2 分钟后同一 daemon 的
# 单条 shell 只有 610ms。慢 ≠ 死，故逐次递增预算（3s 快判 → 8s 吸收冷启动），总预算 11.5s。
_HEALTH_PROBE_TIMEOUTS: tuple[float, ...] = (3.0, 8.0)
_HEALTH_PROBE_RETRY_DELAY_SECONDS = 0.5
# 判定「daemon 无响应」后的熔断窗口（秒）：期间不 spawn 容器，直接返回显性诊断——历史形态是
# 每条命令都实测 timeout + 40s 清理链才回报（2026-11-02 实测 3 次共 ~305s）。
# 分两档：CLI **明确报错**（连接被拒 / daemon 未启动）重试也不会自愈 ⇒ 整窗；仅**超时**
# （慢、可能冷启动）⇒ 短窗 + 更早半开复探，把「误判代价」从 120s 全停压到 30s。
_DEGRADED_COOLDOWN_SECONDS = 120.0
_SLOW_COOLDOWN_SECONDS = 30.0

# 探针判定：``ok`` / ``timeout``（CLI 不应答，慢） / ``unavailable``（CLI 明确报错或缺失）。
_PROBE_OK = "ok"
_PROBE_TIMEOUT = "timeout"
_PROBE_UNAVAILABLE = "unavailable"
# 清理链全超时（命令已 spawn 且 CLI 整体挂起）——证据强于单次探针超时，按整窗处理。
_PROBE_HUNG = "hung"

# 熔断期内**未执行**命令的返回（保留 ``Command timed out`` 前缀，goal/evidence 的超时归类不漂移）。
_DAEMON_PAUSED_RESULT = (
    "exit_code=-1\n"
    "stderr: Command timed out after 0s (NOT executed): container sandbox paused — docker daemon "
    "unresponsive; retrying in ~{retry_in}s. Restart Docker Desktop, or rerun with "
    "--sandbox passthrough. Do not retry in a loop."
)
# 仅仅「探针超时」的熔断文案：不提「重启 Docker Desktop」——实测该形态 2 分钟内自愈，让模型
# 去劝用户重启 Desktop 是错误归因（2026-11-02 事故：三条并行命令各自打了一遍「重启」建议）。
_DAEMON_SLOW_RESULT = (
    "exit_code=-1\n"
    "stderr: Command timed out after 0s (NOT executed): container sandbox paused — docker CLI did not "
    "answer within {budget}s (slow CLI or Docker Desktop cold start, not necessarily dead); retrying in "
    "~{retry_in}s. Wait for the automatic retry, or rerun with --sandbox passthrough. Do not retry in a loop."
)
# 超时后发现清理链全线不应答时追加的诊断（区分「命令慢」与「daemon 挂」）。
_DAEMON_HINT = (
    "\n[daemon-unresponsive] docker CLI did not answer within the cleanup budget, so this was not a "
    "slow command — the container sandbox is paused for {cooldown}s. Restart Docker Desktop or rerun "
    "with --sandbox passthrough; do not retry in a loop."
)


def _probe_daemon_reason(docker_path: str) -> str:
    """探测一次 daemon 并返回**失败原因**（``ok`` / ``timeout`` / ``unavailable``）。

    逐次用递增预算 ``_HEALTH_PROBE_TIMEOUTS``：单次超时不足以区分「daemon 挂了」与
    「Docker Desktop 冷启动卡了几秒」，而误判的代价是整窗全停。

    两类失败语义不同（2026-11-02 三次修订的依据）：
    - **超时**（``TimeoutExpired``）= CLI 不应答但进程还在 ⇒ 慢，可能自愈；
    - **明确报错**（非零返回 / ``OSError``，典型 ``Cannot connect to the Docker daemon``）
      = 重试也不会自愈 ⇒ 立即返回，省下后面的超时预算（真挂时 1s 内判死）。
    混合场景（先超时、后明确报错）取更强证据 = ``unavailable``。
    """
    if shutil.which(docker_path) is None:
        return _PROBE_UNAVAILABLE
    last_reason = _PROBE_TIMEOUT
    for attempt, timeout in enumerate(_HEALTH_PROBE_TIMEOUTS):
        try:
            probe = subprocess.run(  # nosec B603 - 参数为内部构造的固定列表，不经命令解释器 # noqa: S603
                [docker_path, "version", "--format", "{{.Server.Version}}"],
                capture_output=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            last_reason = _PROBE_TIMEOUT
        except OSError:
            return _PROBE_UNAVAILABLE
        else:
            if probe.returncode == 0:
                return _PROBE_OK
            return _PROBE_UNAVAILABLE
        if attempt + 1 < len(_HEALTH_PROBE_TIMEOUTS):
            time.sleep(_HEALTH_PROBE_RETRY_DELAY_SECONDS)
    return last_reason


def _docker_available(docker_path: str) -> bool:
    """可用性闸：CLI 在 PATH **且** daemon 应答（纯探测、无缓存；原因细节见 _probe_daemon_reason）。"""
    return _probe_daemon_reason(docker_path) == _PROBE_OK


def _mount_spec(workspace: Path | None) -> str | None:
    """宿主 workspace 路径 → ``docker -v`` 挂载值；未 bind 会话目录时 ``None``（纯函数可测缝）。

    用 ``as_posix()``：Windows 盘符路径的 posix 形态（``E:/x:/workspace``）Docker Desktop
    直收，且跨 shell 无反斜杠转义歧义；POSIX 宿主上即普通绝对路径。
    """
    if workspace is None:
        return None
    return f"{workspace.as_posix()}:{CONTAINER_WORKDIR}"


def build_run_argv(
    *,
    docker_path: str,
    image: str,
    network: str,
    name: str,
    workspace: Path | None,
    command: str,
    memory_limit_mb: int = 0,
    nproc_limit: int = 0,
    user: str = CONTAINER_USER,
) -> list[str]:
    """组装 ``docker run`` argv——旗标与顺序**单处**决定（判据钉死在这里）。

    不传 ``--env``：容器 env 隔离的落点（见模块 docstring）。``--pull=never``：镜像缺席
    显性报错而非隐式拉取（隔离工具不制造网络依赖；镜像供给是 53-2 的配置面职责）。
    硬化旗标：``--cap-drop=ALL`` + ``no-new-privileges`` + 非 root ``user``（审查修复批）；
    ``user`` 参数化供测试断言与未来逐 run 覆盖。
    """
    argv = [
        docker_path,
        "run",
        "--rm",
        "--pull=never",
        "--name",
        name,
        "--network",
        network,
        "--cap-drop=ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        user,
    ]
    # 资源限额（0=关闭，默认零旗标 → 既有 argv 逐字节不变）；触发=容器被杀显性失败。
    # ⚠ 必须排在 IMAGE **之前**：`docker run` 的选项只在镜像名之前被解析，排在镜像名之后
    # 会变成容器内命令的参数（限额静默失效，容器照跑）。真实 daemon integration 用例钉住。
    if memory_limit_mb > 0:
        argv += ["--memory", f"{memory_limit_mb}m"]
    if nproc_limit > 0:
        argv += ["--pids-limit", str(nproc_limit)]
    mount = _mount_spec(workspace)
    if mount is not None:
        argv += ["-v", mount, "-w", CONTAINER_WORKDIR]
    argv += [image, "sh", "-c", command]
    return argv


def _docker_spawn(argv: list[str]) -> subprocess.Popen[bytes]:
    """启动 docker CLI 子进程——无 shell、不透传宿主 env 覆盖（可测缝，winjob 同型）。"""
    return subprocess.Popen(  # nosec B603 - 参数为内部构造的固定列表，不经命令解释器 # noqa: S603
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _is_gone(returncode: int, stderr: str | None) -> bool:
    """inspect 的 stderr 是否表示**容器已不存在**（``--rm`` 删除后的常态，非故障）。

    只认 daemon 的「无此对象」语义：容器已消失 = 清理目标已达成。其余 rc≠0（daemon 不可达、
    权限、超时）仍按「状态不确定」处理——**不能**把两者混为一谈，否则每发超时都会白等一次
    ``rm -f`` 并打出假 traceback（真实缺陷，2026-10-21）。
    """
    if returncode == 0 or not stderr:
        return False
    text = stderr.strip().lower()
    return "no such object" in text or "no such container" in text


def _docker_kill(docker_path: str, name: str) -> bool:
    """按容器名精确 ``docker kill -- <name>``——杀 CLI 进程**不会**停容器，超时/取消必须显式杀。

    kill 后（无论成功与否）**始终**做一次 ``inspect`` 确认容器存活状态：``--rm`` 容器被杀后
    自行删除，inspect 返回 ``No such object`` 即清理已达成，直接返回，不走 ``rm -f``（否则
    会撞上 daemon 的删除锁白等满 ``_REAP_WAIT_TIMEOUT`` 并打出假 traceback）。
    kill 失败时也先 inspect：Windows 命名管道并发压力下 kill 常超时但容器早已消失；跳过
    inspect 直接 ``rm -f`` 会额外浪费一个 ``_REAP_WAIT_TIMEOUT`` 周期。
    仍活着或状态真不确定 → WARNING + ``docker rm -f`` 兜底；兜底也失败只 warning 留痕。

    返回值 = 「daemon 无响应」判定（**不是**清理是否成功）：任一 docker CLI 调用撞
    ``TimeoutExpired`` 即为真。调用方据此熔断沙箱——2026-11-02 事故里 daemon 整段挂起时
    每次超时都要白等满 4×10s 清理链，且模型无从知道该重启 Docker Desktop。
    kill **与** inspect 双双超时 ⇒ 省掉必然也超时的 ``rm -f``（再省 10s）。
    """
    unresponsive = False
    kill_timed_out = False
    try:
        subprocess.run(  # nosec B603 - 参数为内部构造的固定列表，不经命令解释器 # noqa: S603
            [docker_path, "kill", "--", name],
            capture_output=True,
            timeout=_REAP_WAIT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.debug("docker kill %s timed out; will inspect to confirm state", name, exc_info=True)
        unresponsive = kill_timed_out = True
    except OSError:
        logger.debug("docker kill %s failed (CLI error); will inspect to confirm state", name, exc_info=True)

    # 无论 kill 成功与否，inspect 给出最终答案——避免对已消失容器重复 rm -f。
    fallback = False
    try:
        probe = subprocess.run(  # nosec B603 - 参数为内部构造的固定列表，不经命令解释器 # noqa: S603
            [docker_path, "inspect", "-f", "{{.State.Running}}", "--", name],
            capture_output=True,
            text=True,
            timeout=_REAP_WAIT_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        logger.warning("docker kill left container %s state uncertain; daemon not answering inspect", name)
        if kill_timed_out:
            # kill 与 inspect 双超时 = CLI 整体挂起；``rm -f`` 必然同样超时，不再白等一个周期。
            return True
        fallback = True
    except OSError:
        logger.warning("docker kill left container %s state uncertain; removing as fallback", name)
        fallback = True
    else:
        # ``--rm`` 容器被杀后自行删除，inspect 必然 ``No such object``（rc=1）——清理已达成。
        if _is_gone(probe.returncode, probe.stderr):
            return unresponsive
        fallback = probe.returncode != 0 or probe.stdout.strip() != "false"

    if not fallback:
        return unresponsive
    logger.warning("docker kill left container %s alive or uncertain; issuing docker rm -f fallback", name)
    try:
        subprocess.run(  # nosec B603 - 参数为内部构造的固定列表，不经命令解释器 # noqa: S603
            [docker_path, "rm", "-f", "--", name],
            capture_output=True,
            timeout=_REAP_WAIT_TIMEOUT,
        )
    except subprocess.TimeoutExpired as exc:
        # 不带 exc_info：清理失败是兜底动作的留痕，打印整段 traceback 会让人误判成程序崩溃。
        logger.warning("docker rm -f %s also failed; container may be orphaned (%s: %s)", name, type(exc).__name__, exc)
        return True
    except OSError as exc:
        logger.warning("docker rm -f %s also failed; container may be orphaned (%s: %s)", name, type(exc).__name__, exc)
    return unresponsive


def _docker_inspect_digest(docker_path: str, image: str) -> str | None:
    """``docker image inspect`` 取镜像 repo digest（首个 ``@sha256:…``），不可得返回 None。

    可测缝（判据桩点）：运行期 digest pin 校验的唯一实现点。
    """
    try:
        proc = subprocess.run(  # nosec B603 - 参数为内部构造的固定列表，不经命令解释器 # noqa: S603
            [docker_path, "image", "inspect", "--format", "{{json .RepoDigests}}", "--", image],
            capture_output=True,
            text=True,
            timeout=_REAP_WAIT_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    try:
        digests = json.loads(proc.stdout.strip() or "[]")
    except json.JSONDecodeError:
        return None
    for entry in digests:
        idx = entry.find("sha256:")
        if idx >= 0:
            return str(entry)[idx:]
    return None


class DockerRunner:
    """Docker 容器沙箱后端：每命令一次性容器，短命命令捕获形状（``sh -c`` 收尾）。

    生命周期与既有后端同型：构造时持有配置，``available`` 缓存探测，``run`` 执行 +
    超时/取消双路清理（超时杀容器后有界回收管道；取消同型，对称语义）。
    """

    tier = SandboxTier.CONTAINER

    def __init__(
        self,
        *,
        docker_path: str = "docker",
        image: str = DEFAULT_IMAGE,
        network: str = "none",
        workspace: Path | None = None,
        digest: str | None = None,
        memory_limit_mb: int = 0,
        nproc_limit: int = 0,
        max_cleanup_concurrency: int = 2,
    ) -> None:
        self._docker_path = docker_path
        self._image = image
        self._network = network
        self._workspace = workspace
        self._digest = digest
        self._memory_limit_mb = memory_limit_mb
        self._nproc_limit = nproc_limit
        self._probe_cache: bool | None = None
        self._digest_checked = False
        # daemon 健康心跳与熔断（2026-11-02）：``_last_health_probe`` 是最近一次探测成功/失败的
        # ``monotonic()`` 时刻；``_degraded_until`` 之前不再 spawn（直接返回显性诊断）。
        # ``_last_probe_reason`` 记录该次探测的判定（ok/timeout/unavailable），供并发折叠复用与
        # 分档熔断；``_degraded_reason`` 决定熔断文案与窗口长度。
        self._last_health_probe = 0.0
        self._last_probe_reason = _PROBE_UNAVAILABLE
        self._degraded_until = 0.0
        self._degraded_reason = _PROBE_UNAVAILABLE
        # 探测 single-flight（2026-11-02 三次修订）：模型常在同一 tool batch 并行发多条 shell，
        # 每条都会走心跳；无折叠时 N 路并行 probe 同时打 Docker CLI（Windows 命名管道 + WSL2
        # 转发），既互相拖慢也让同一判定重复落日志。锁内二次检查 TTL 使一轮并发只付一次探针。
        self._probe_lock = asyncio.Lock()
        # 限制同时进行的 docker kill/rm-f 并发数：Windows 命名管道并发压力下多个清理操作
        # 同时排队会让每条都等满超时；串行清理避免堆积（2 条并发是合理上限，单条显著慢）。
        self._cleanup_sem = asyncio.Semaphore(max_cleanup_concurrency)

    @property
    def available(self) -> bool:
        """CLI 在 PATH 且 daemon 应答；单实例缓存（daemon 重启后新实例重新探测）。

        同步探测（与 winjob 装配期探测同型）；``run()`` 内的首触探测走线程池，不在事件循环上阻塞。
        """
        if self._probe_cache is None:
            reason = _probe_daemon_reason(self._docker_path)
            self._probe_cache = reason == _PROBE_OK
            self._last_probe_reason = reason
            self._last_health_probe = time.monotonic()
        return self._probe_cache

    @property
    def image(self) -> str:
        """当前镜像引用（tag 或 tag@digest 形态）——判据与诊断用。"""
        return self._image

    @property
    def workspace(self) -> Path | None:
        """默认挂载回退目录（resolver 传入的 workspace_root）；FR-1 会话目录优先于它。"""
        return self._workspace

    def isolates_network(self) -> bool:
        """容器网络是否隔离（``--network=none``）——SandboxDecision docker 档的事实源。"""
        return self._network == "none"

    async def _probe_daemon(self) -> str:
        """真探测一次 daemon（线程池执行），并记录时刻与判定。

        single-flight 语义：拿锁后若心跳已被同批的其它协程刷新（TTL 内），直接复用其结论，
        不再 spawn 第二个 ``docker version``。
        """
        async with self._probe_lock:
            if time.monotonic() - self._last_health_probe < _HEALTH_PROBE_TTL_SECONDS:
                return self._last_probe_reason
            reason = await asyncio.to_thread(_probe_daemon_reason, self._docker_path)
            self._last_health_probe = time.monotonic()
            self._last_probe_reason = reason
            return reason

    async def _health_check(self) -> str | None:
        """daemon 健康心跳：``_HEALTH_PROBE_TTL_SECONDS`` 内复用上次结论；``None`` = 健康。

        探测失败**不**改 ``_probe_cache``：那是装配期的可用性闸（False ⇒ 退 Passthrough），
        运行期的 daemon 抖动不该触发静默透传——只用于熔断与显性诊断（2026-11-02）。
        """
        if time.monotonic() - self._last_health_probe < _HEALTH_PROBE_TTL_SECONDS:
            return None
        reason = await self._probe_daemon()
        return None if reason == _PROBE_OK else reason

    def _cooldown_for(self, reason: str) -> float:
        """判定 → 熔断窗口长度（秒）：只有「纯超时」走短窗，其余按整窗。"""
        return _SLOW_COOLDOWN_SECONDS if reason == _PROBE_TIMEOUT else _DEGRADED_COOLDOWN_SECONDS

    def _pause(self, reason: str) -> None:
        """进入熔断窗口：下次 :meth:`run` 起一跳内不再 spawn 容器；窗口长度按判定分档。"""
        self._degraded_reason = reason
        self._degraded_until = time.monotonic() + self._cooldown_for(reason)

    def _paused_result(self) -> str:
        """熔断期内**未执行**命令的返回文案（含剩余窗口，供人/模型决定下一步）。"""
        remaining = max(0.0, self._degraded_until - time.monotonic())
        retry_in = max(1, int(remaining) + 1)
        if self._degraded_reason == _PROBE_TIMEOUT:
            return _DAEMON_SLOW_RESULT.format(
                budget=sum(_HEALTH_PROBE_TIMEOUTS),
                retry_in=retry_in,
            )
        return _DAEMON_PAUSED_RESULT.format(retry_in=retry_in)

    async def _admit_within_cooldown(self) -> str | None:
        """熔断窗口内的一次放行判定：``None`` = 可以执行，否则返回「未执行」结果文案。

        - 不在窗口内 ⇒ ``None``（走正常健康心跳）；
        - 窗口内且心跳新鲜 ⇒ 直接拒绝，不付探针；
        - 窗口内但心跳过期 ⇒ **半开复探**：daemon 恢复则解除熔断并放行（2026-11-02 二次
          修订，修复「daemon 已恢复仍被拒满 120s」），仍不应答则顺延窗口。
        """
        if time.monotonic() >= self._degraded_until:
            return None
        if time.monotonic() - self._last_health_probe < _HEALTH_PROBE_TTL_SECONDS:
            return self._paused_result()
        reason = await self._probe_daemon()
        if reason == _PROBE_OK:
            logger.info("docker daemon answered again; container sandbox resumed")
            self._degraded_until = 0.0
            return None
        self._pause(reason)
        logger.warning(
            "docker daemon still unresponsive (%s); container sandbox paused for another %ss",
            reason,
            self._cooldown_for(reason),
        )
        return self._paused_result()

    async def run(self, command: str, *, timeout: int) -> str:
        # 探测缓存未暖时经线程池探测（审查修复批）：run() 首触不再阻塞事件循环最长一个探针预算；
        # engine 装配链在 resolver 可用性闸处已同步探测过（构造期探测是装配协议的一部分）。
        if self._probe_cache is None:
            reason = await asyncio.to_thread(_probe_daemon_reason, self._docker_path)
            self._probe_cache = reason == _PROBE_OK
            self._last_probe_reason = reason
            self._last_health_probe = time.monotonic()
        if not self._probe_cache:
            logger.warning(
                "DockerRunner not available (CLI missing or daemon unreachable); falling back to Passthrough"
            )
            return await PassthroughRunner().run(command, timeout=timeout)

        # 熔断窗口内直接失败：daemon 挂起时每条命令白等满 timeout + 清理链是纯浪费，
        # 且模型会把「超时」误读成「命令慢」而重试（2026-11-02 实测连续 3 次共 ~305s）。
        # 窗口内的半开复探见 ``_admit_within_cooldown``。
        paused = await self._admit_within_cooldown()
        if paused is not None:
            return paused
        failure = await self._health_check()
        if failure is not None:
            self._pause(failure)
            logger.warning(
                "docker daemon health probe failed (%s); container sandbox paused for %ss",
                failure,
                self._cooldown_for(failure),
            )
            return self._paused_result()

        # 运行期 digest pin（审查修复批）：配置了 digest 则首 run 前校验本地 tag 的 repo
        # digest，不符显性拒绝——本地 tag 可被 retag 静默换载荷（D4 的运行期落实）。
        if self._digest and not self._digest_checked:
            actual = await asyncio.to_thread(_docker_inspect_digest, self._docker_path, self._image)
            if actual is None or not actual.endswith(self._digest):
                raise RuntimeError(
                    f"docker image digest mismatch for {self._image}: "
                    f"configured {self._digest!r}, present {actual!r}; refusing to run"
                )
            self._digest_checked = True

        name = f"heagent-{uuid.uuid4().hex[:12]}"
        # 挂载兜底（审查修复批）：FR-1 会话目录优先，缺省回落 resolver 传入的 workspace_root
        # ——不给「无挂载、写入随 --rm 蒸发还报成功」的静默形态（firejail --private 同型语义）。
        workspace = get_sandbox_workspace() or self._workspace
        argv = build_run_argv(
            docker_path=self._docker_path,
            image=self._image,
            network=self._network,
            name=name,
            workspace=workspace,
            command=command,
            memory_limit_mb=self._memory_limit_mb,
            nproc_limit=self._nproc_limit,
        )
        proc = await asyncio.to_thread(_docker_spawn, argv)

        async def kill_and_reap(catch: type[BaseException], label: str) -> bool:
            """清理容器；返回「daemon 无响应」判定（任一 docker CLI 调用超时）。"""
            # 串行化清理：并发清理操作在 Windows 命名管道上互相拖慢，限流后排队执行。
            async with self._cleanup_sem:
                try:
                    unresponsive = bool(await asyncio.to_thread(_docker_kill, self._docker_path, name))
                except catch:
                    logger.debug("%s cleanup: kill failed", label, exc_info=True)
                    return False
                if unresponsive:
                    # daemon 不应答时 CLI 子进程也不会退出：白等一个周期不如直接放弃
                    # 并让调用方熔断（2026-11-02，每个周期 10s）。poll 只做句柄回收。
                    proc.poll()
                    return True
                try:
                    await asyncio.wait_for(asyncio.to_thread(proc.wait), timeout=_REAP_WAIT_TIMEOUT)
                except catch:
                    logger.debug("%s cleanup: wait failed", label, exc_info=True)
                return False

        try:
            stdout, stderr = await asyncio.wait_for(
                asyncio.to_thread(proc.communicate),
                timeout=timeout,
            )
            return _format_result(proc.returncode, stdout, stderr)
        except TimeoutError:
            unresponsive = await kill_and_reap(Exception, "timeout")
            if not unresponsive:
                return _TIMEOUT_RESULT.format(timeout=timeout)
            # 命令超时 + 清理链全线超时 = daemon 挂了，不是命令慢：熔断并给出可操作的诊断。
            self._pause(_PROBE_HUNG)
            logger.warning(
                "docker daemon unresponsive during cleanup of %s; container sandbox paused for %ss",
                name,
                self._cooldown_for(_PROBE_HUNG),
            )
            return _TIMEOUT_RESULT.format(timeout=timeout) + _DAEMON_HINT.format(
                cooldown=int(self._cooldown_for(_PROBE_HUNG))
            )
        except asyncio.CancelledError:
            await kill_and_reap(BaseException, "cancel")
            raise

    def __repr__(self) -> str:
        return f"DockerRunner(image={self._image!r}, network={self._network!r}, available={self.available})"
