"""Firejail 沙箱后端（OS 级隔离，Linux-only，非完美边界）。

经 ``create_subprocess_exec`` 启动 firejail 包裹子进程；argv 组装为纯函数
:meth:`FirejailBackend._build_argv`（profile 参数 / ``--net=none`` / ``--private``
工作区映射 / rlimit 资源限额）。firejail 不可用时经 :meth:`FirejailBackend.run`
优雅降级到 Passthrough。
"""

from __future__ import annotations

import logging
import shutil
from typing import TYPE_CHECKING

from heagent.tools.sandbox.contracts import SandboxTier, get_sandbox_profile, get_sandbox_workspace
from heagent.tools.sandbox.process import PassthroughRunner, _run_subprocess_exec

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


logger = logging.getLogger(__name__)


class FirejailBackend:
    """经 firejail 包裹子进程的后端（OS 级隔离，Linux-only，非完美边界）。

    用 ``create_subprocess_exec`` 启动 firejail。``extra_args`` 透传给 firejail；
    ``profiles`` 提供 per-profile 参数映射（如 ``{"network-isolated": ("--net=none",)}``），
    由 ``PolicyEngine`` 裁决出的 profile 名（``SANDBOX_PROFILES`` / ``SANDBOX_TOOL_PROFILES``
    配置注入）选用。``workspace_root`` 自动映射为 ``--private`` 参数（OS 级文件系统隔离）。
    firejail 不可用时通过 :meth:`run` 优雅降级到 PassthroughRunner。
    """

    tier = SandboxTier.FIREJAIL

    def __init__(
        self,
        firejail_path: str = "firejail",
        extra_args: Sequence[str] = (),
        profiles: Mapping[str, Sequence[str]] | None = None,
        workspace_root: str | None = None,
        network: bool = True,
        memory_limit_mb: int = 0,
        cpu_seconds: int = 0,
        nproc_limit: int = 0,
    ) -> None:
        self._firejail_path = firejail_path
        self._extra_args = tuple(extra_args)
        self._workspace_root = workspace_root
        # P0-2：False 时在 argv 中插入 ``--net=none``（禁止子进程出站）。
        self._network = network
        self._profiles: dict[str, tuple[str, ...]] = {}
        if profiles:
            self._profiles = {k: tuple(v) for k, v in profiles.items()}
        # 资源限额（2026-09-17 硬化批，2026-09-18 补进程数，0=关闭）：映射
        # --rlimit-as / --rlimit-cpu / --rlimit-nproc。限额触发 → 子进程被终止 → 非零
        # 退出码经正常结果回传（显性失败，不静默截断）。
        self._memory_limit_mb = memory_limit_mb
        self._cpu_seconds = cpu_seconds
        # ⚠ --rlimit-nproc 底层是 setrlimit(RLIMIT_NPROC)：Linux 按**真实 UID** 计数，
        # 不是 per-sandbox 作用域——设小了会波及同一用户的其他进程（WinJob 侧是 job 作用域）。
        self._nproc_limit = nproc_limit

        # FR-S3：构造期检测 firejail 可用性
        resolved = shutil.which(self._firejail_path)
        if resolved is None:
            self._firejail_available = False
            self._resolved_path: str | None = None
            logger.warning(
                "firejail not found at %r, sandbox disabled — falling back to passthrough",
                self._firejail_path,
            )
        else:
            self._firejail_available = True
            self._resolved_path = resolved

    @property
    def available(self) -> bool:
        """firejail 是否可用（构造期 ``shutil.which`` 检测结果）。"""
        return self._firejail_available

    def _build_argv(
        self,
        command: str,
        profile: str | None,
        workspace_root: str | None = None,
    ) -> list[str]:
        """纯函数：给定 command 与 profile 名，返回完整 firejail argv。

        拼接顺序：``[firejail, *extra_args, --private=<ws>, *profile_args, "--", "sh", "-c", command]``。
        ``workspace_root`` 未显式传入时默认取 ``self._workspace_root``。
        """
        if workspace_root is None:
            workspace_root = self._workspace_root
        argv: list[str] = [self._resolved_path or self._firejail_path]
        argv.extend(self._extra_args)

        if not self._network:
            # --net=none 必须排在 profile -- 之前；与 profile 参数同为 defense-in-depth，
            # 非完美边界（firejail 本身非安全边界，见模块 docstring）。
            argv.append("--net=none")

        if workspace_root:
            argv.append(f"--private={workspace_root}")

        if profile is not None and profile in self._profiles:
            argv.extend(self._profiles[profile])

        # 资源限额（0=关闭，默认零参数 → 既有 argv 逐字节不变）：排在 profile 参数之后、
        # "--" 之前。触发为显性失败（子进程被终止 → 非零退出码），非静默截断。
        if self._memory_limit_mb > 0:
            argv.append(f"--rlimit-as={self._memory_limit_mb * 1024 * 1024}")
        if self._cpu_seconds > 0:
            argv.append(f"--rlimit-cpu={self._cpu_seconds}")
        if self._nproc_limit > 0:
            argv.append(f"--rlimit-nproc={self._nproc_limit}")

        argv.extend(["--", "sh", "-c", command])
        return argv

    async def run(self, command: str, *, timeout: int) -> str:
        # FR-S3：优雅降级——firejail 不可用时走 Passthrough
        if not self._firejail_available:
            return await PassthroughRunner().run(command, timeout=timeout)

        profile = get_sandbox_profile()
        # FR-1：per-run 沙箱会话目录（经 executor bind）优先作为 --private 根；
        # 未 bind（None）时 _build_argv 回退构造期 self._workspace_root，行为与现状一致。
        workspace = get_sandbox_workspace()
        argv = self._build_argv(
            command,
            profile,
            workspace_root=str(workspace) if workspace is not None else None,
        )
        return await _run_subprocess_exec(argv, timeout=timeout)
