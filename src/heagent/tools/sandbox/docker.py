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


def _docker_available(docker_path: str) -> bool:
    """探测 = CLI 在 PATH **且** daemon 应答（``docker version`` 短超时探针）。

    结果由 :attr:`DockerRunner.available` 缓存；本函数保持纯探测无缓存。
    """
    if shutil.which(docker_path) is None:
        return False
    try:
        probe = subprocess.run(  # noqa: S603
            [docker_path, "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


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
    return subprocess.Popen(  # noqa: S603
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _docker_kill(docker_path: str, name: str) -> None:
    """按容器名精确 ``docker kill -- <name>``——杀 CLI 进程**不会**停容器，超时/取消必须显式杀。

    kill 后校验容器确已停止（``inspect .State.Running``）；仍活着或校验失败 → WARNING +
    ``docker rm -f`` 兜底（审查修复批）：孤儿容器带着 workspace 写挂载存活是真实暴露面。
    兜底也失败只 warning 留痕（清理是兜底动作，不制造二次异常）；有界等待
    （``_REAP_WAIT_TIMEOUT``）——kill 自身挂死不得拖垮清理路径。
    """
    fallback = False
    try:
        subprocess.run(  # noqa: S603
            [docker_path, "kill", "--", name],
            capture_output=True,
            timeout=_REAP_WAIT_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        logger.debug("docker kill %s failed", name, exc_info=True)
        fallback = True
    if not fallback:
        try:
            probe = subprocess.run(  # noqa: S603
                [docker_path, "inspect", "-f", "{{.State.Running}}", "--", name],
                capture_output=True,
                text=True,
                timeout=_REAP_WAIT_TIMEOUT,
            )
        except (OSError, subprocess.TimeoutExpired):
            logger.warning("docker kill left container %s state uncertain; removing as fallback", name)
            fallback = True
        else:
            fallback = probe.returncode != 0 or probe.stdout.strip() != "false"
    if not fallback:
        return
    logger.warning("docker kill left container %s alive or uncertain; issuing docker rm -f fallback", name)
    try:
        subprocess.run(  # noqa: S603
            [docker_path, "rm", "-f", "--", name],
            capture_output=True,
            timeout=_REAP_WAIT_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired):
        logger.warning("docker rm -f %s also failed; container may be orphaned", name, exc_info=True)


def _docker_inspect_digest(docker_path: str, image: str) -> str | None:
    """``docker image inspect`` 取镜像 repo digest（首个 ``@sha256:…``），不可得返回 None。

    可测缝（判据桩点）：运行期 digest pin 校验的唯一实现点。
    """
    try:
        proc = subprocess.run(  # noqa: S603
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

    @property
    def available(self) -> bool:
        """CLI 在 PATH 且 daemon 应答；单实例缓存（daemon 重启后新实例重新探测）。

        同步探测（与 winjob 装配期探测同型）；``run()`` 内的首触探测走线程池，不在事件循环上阻塞。
        """
        if self._probe_cache is None:
            self._probe_cache = _docker_available(self._docker_path)
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

    async def run(self, command: str, *, timeout: int) -> str:
        # 探测缓存未暖时经线程池探测（审查修复批）：run() 首触不再阻塞事件循环最长 5s；
        # engine 装配链在 resolver 可用性闸处已同步探测过（构造期探测是装配协议的一部分）。
        if self._probe_cache is None:
            self._probe_cache = await asyncio.to_thread(_docker_available, self._docker_path)
        if not self._probe_cache:
            logger.warning(
                "DockerRunner not available (CLI missing or daemon unreachable); falling back to Passthrough"
            )
            return await PassthroughRunner().run(command, timeout=timeout)

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

        async def kill_and_reap(catch: type[BaseException], label: str) -> None:
            try:
                await asyncio.to_thread(_docker_kill, self._docker_path, name)
                try:
                    await asyncio.wait_for(asyncio.to_thread(proc.wait), timeout=_REAP_WAIT_TIMEOUT)
                except catch:
                    logger.debug("%s cleanup: wait failed", label, exc_info=True)
            except catch:
                logger.debug("%s cleanup: kill/wait failed", label, exc_info=True)

        try:
            stdout, stderr = await asyncio.wait_for(
                asyncio.to_thread(proc.communicate),
                timeout=timeout,
            )
            return _format_result(proc.returncode, stdout, stderr)
        except TimeoutError:
            await kill_and_reap(Exception, "timeout")
            return _TIMEOUT_RESULT.format(timeout=timeout)
        except asyncio.CancelledError:
            await kill_and_reap(BaseException, "cancel")
            raise

    def __repr__(self) -> str:
        return f"DockerRunner(image={self._image!r}, network={self._network!r}, available={self.available})"
