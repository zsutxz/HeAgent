"""MCP stdio server 进容器（Epic 53 期二 D53-1 / Story 53-5）。

**形状**：不新增 runner，也**不复用** ``CommandRunner``（那是 ``sh -c`` 短命命令捕获，
承载不了长命双向 JSON-RPC 管道）。做法是把 SDK 的 stdio 子进程**换成 docker CLI**：
``stdio_client`` 拉起 ``docker run -i --rm … <image> <server-cmd> <args…>``，
容器内进程的 stdin/stdout 就是 JSON-RPC 管道（``-i`` 保持 stdin 打开，SDK 关闭子进程 ⇒
docker CLI 转发信号停容器 + ``--rm`` 清理）。

**冻结决策**：

- **网络档沿用 D2**：默认 ``--network=none``，``SANDBOX_NETWORK=true`` 时 ``bridge``。
- **不传宿主 env**：只对本 server 在 ``.mcp.json`` 里**显式声明**的 env 名发 ``-e KEY``
  （不带值 ⇒ docker 从 CLI 进程 env 取值）。宿主其它变量一律不进容器，与 DockerRunner
  「不传 ``--env``」同口径。
- **显性降级（用户 2026-11-03 裁定）**：容器后端不可用（CLI 缺席 / daemon 不应答 / 探测抛错）
  ⇒ 仍按原样在**宿主**拉起 server，但**每次**连接都打 WARNING 留痕，绝不静默假装已隔离。
- **硬化旗标与 DockerRunner 同源**：``--cap-drop=ALL`` / ``no-new-privileges`` / 非 root
  ``user`` / ``--pull=never``；镜像缺席显性失败而非隐式拉取。

⚠ 边界口径：容器档是 OS 级强隔离兜底，**非绝对边界**（宿主内核 / Docker daemon 自身逃逸仍在）。
MCP server 自身仍是不可信代码——镜像里没有的二进制（典型 ``npx``）会显性失败，属预期。
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from mcp.client.stdio import StdioServerParameters
from pydantic import BaseModel, ConfigDict, PrivateAttr

from heagent.tools.sandbox.docker import CONTAINER_USER, CONTAINER_WORKDIR, docker_available

if TYPE_CHECKING:
    from collections.abc import Callable

    from heagent.tools.mcp.config import StdioServerConfig

logger = logging.getLogger(__name__)

# 可用性探测的复用窗口（秒）：与 DockerRunner 心跳同量级。健康时每个 spec 最多每 30s 付一次
# ``docker version``；降级 WARNING 仍按**每次连接**打（显性降级 + 每次留痕）。
_PROBE_TTL_SECONDS = 30.0


class StdioSandboxSpec(BaseModel):
    """MCP stdio 进容器的后端规格（由入口层按 ``Settings`` 构造；非安全边界）。"""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    image: str
    docker_path: str = "docker"
    # none | bridge（工具执行默认不需要网）。
    network: str = "none"
    # 宿主 workspace（posix 形态挂到 CONTAINER_WORKDIR）；None = 不挂载。
    workspace: str | None = None
    memory_limit_mb: int = 0
    pids_limit: int = 0
    user: str = CONTAINER_USER

    _probe_fn: Callable[[str], bool] | None = PrivateAttr(default=None)
    _probe_cache: tuple[float, bool] | None = PrivateAttr(default=None)

    def available(self) -> bool:
        """容器后端当前是否可用（带 TTL 缓存；探测抛错按不可用处理 = 显性降级）。"""
        now = time.monotonic()
        if self._probe_cache is not None and now - self._probe_cache[0] < _PROBE_TTL_SECONDS:
            return self._probe_cache[1]
        probe = self._probe_fn or docker_available
        try:
            ok = bool(probe(self.docker_path))
        except Exception:  # noqa: BLE001 - 探测失败即按不可用处理（显性降级 + 每次 WARNING）
            logger.warning("MCP stdio sandbox: docker probe failed; MCP server will run on host", exc_info=True)
            ok = False
        self._probe_cache = (now, ok)
        return ok


def container_name(cfg: StdioServerConfig) -> str:
    """容器名：``heagent-mcp-<命令指纹>-<随机后缀>``（随机后缀防同名冲突，指纹便于对账）。"""
    digest = hashlib.sha256(f"{cfg.command}\0{' '.join(cfg.args)}".encode()).hexdigest()[:8]
    return f"heagent-mcp-{digest}-{uuid4().hex[:6]}"


def _mount_arg(workspace: str | None) -> list[str]:
    if not workspace:
        return []
    return ["-v", f"{Path(workspace).as_posix()}:{CONTAINER_WORKDIR}", "-w", CONTAINER_WORKDIR]


def build_run_argv(spec: StdioSandboxSpec, cfg: StdioServerConfig) -> list[str]:
    """组装 ``docker run`` argv（旗标与顺序单处决定；判据钉在这里）。

    env 旗标**先于** IMAGE：``docker run`` 的选项只在镜像名之前解析，排在后面会被当成
    容器内命令的参数而静默失效（与 DockerRunner 的限额旗标同一坑）。
    """
    argv = [
        spec.docker_path,
        "run",
        "-i",
        "--rm",
        "--pull=never",
        "--name",
        container_name(cfg),
        "--network",
        spec.network,
        "--cap-drop=ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        spec.user,
        # 便于孤儿容器核查（scripts/cleanup_orphan_containers.ps1 口径一致）
        "--label",
        "heagent.mcp=stdio",
    ]
    if spec.memory_limit_mb > 0:
        argv += ["--memory", f"{spec.memory_limit_mb}m"]
    if spec.pids_limit > 0:
        argv += ["--pids-limit", str(spec.pids_limit)]
    # 只透传 server 自己声明的 env 名（不带值 ⇒ 从 docker CLI 进程 env 取）。
    for key in sorted(cfg.env):
        argv += ["-e", key]
    argv += _mount_arg(spec.workspace)
    argv += [spec.image, cfg.command, *cfg.args]
    return argv


def stdio_params(cfg: StdioServerConfig, spec: StdioSandboxSpec | None) -> StdioServerParameters:
    """按 spec 产出 SDK 的 stdio 参数：容器档可用 ⇒ 用 docker 包裹；否则显性降级回宿主。"""
    host = StdioServerParameters(command=cfg.command, args=cfg.args, env=cfg.env or None)
    if spec is None:
        return host
    if not spec.available():
        logger.warning(
            "MCP stdio server '%s' is NOT sandboxed (docker backend unavailable); "
            "running on host — explicit degradation",
            cfg.command,
        )
        return host
    argv = build_run_argv(spec, cfg)
    return StdioServerParameters(command=argv[0], args=argv[1:], env=cfg.env or None)
