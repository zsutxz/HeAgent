"""沙箱契约层：后端强度分级、:class:`CommandRunner` Protocol 与注入 slot。

本模块只承载**类型与注入契约**（零后端依赖）：`SandboxTier` 强度分级、
`CommandRunner` 最小 Protocol、profile / workspace 两个 RuntimeSlot 注入面。
进程监督内核见 :mod:`.process`，平台后端见 :mod:`.firejail` / :mod:`.winjob`，
会话目录与 :class:`SandboxSession` 见 :mod:`.session`。
"""

from __future__ import annotations

from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from heagent.tools.runtime import RuntimeSlot

if TYPE_CHECKING:
    from collections.abc import Iterator


_TIER_RANK: dict[str, int] = {
    "passthrough": 0,
    "job": 1,
    "firejail": 2,
    "container": 3,
}


class SandboxTier(StrEnum):
    """沙箱后端强度分级（passthrough < job < firejail < container）。

    强度递增；``container`` 档（OS 级强隔离，如 Docker / bubblewrap / AppContainer）
    为预留枚举，当前无实现后端。仅 ``container`` 档允许审批降级
    （:attr:`can_relax_approval`）——弱后端（passthrough/job/firejail）一律维持原
    审批要求（NFR-2，测试锁定）。
    """

    PASSTHROUGH = "passthrough"
    JOB = "job"
    FIREJAIL = "firejail"
    CONTAINER = "container"

    @property
    def rank(self) -> int:
        """强度序（0=最弱，3=最强），供强度比较。"""
        return _TIER_RANK[self.value]

    @property
    def can_relax_approval(self) -> bool:
        """是否允许审批降级——仅 ``container`` 档（OS 级强隔离）可降审批。

        弱后端（passthrough/job/firejail）一律 False：不得因后端强度跳过审批
        （NFR-2，测试锁定）。
        """
        return self is SandboxTier.CONTAINER


class CommandRunner(Protocol):
    """执行一条 shell 命令的抽象后端。"""

    tier: SandboxTier

    @property
    def available(self) -> bool:
        """后端当前是否可用（不可用时 run 内优雅降级 Passthrough）。"""
        ...

    async def run(self, command: str, *, timeout: int) -> str:
        """执行 ``command``，返回 ``exit_code=...\nstdout:...\nstderr:...`` 格式结果。"""
        ...


# —— Sandbox profile contextvar（S1-2：executor 注入 pipeline）——
_sandbox_profile_slot: RuntimeSlot[str | None] = RuntimeSlot[str | None]("heagent_sandbox_profile")


def get_sandbox_profile() -> str | None:
    return _sandbox_profile_slot.get()


def reset_sandbox_profile() -> None:
    _sandbox_profile_slot.reset()


@contextmanager
def bind_sandbox_profile(profile: str | None) -> Iterator[None]:
    with _sandbox_profile_slot.bind(profile):
        yield


# —— Sandbox session workspace（FR-1：per-run 沙箱会话目录）——
_sandbox_workspace_slot: RuntimeSlot[Path | None] = RuntimeSlot[Path | None]("heagent_sandbox_workspace")


def get_sandbox_workspace() -> Path | None:
    return _sandbox_workspace_slot.get()


def reset_sandbox_workspace() -> None:
    _sandbox_workspace_slot.reset()


@contextmanager
def bind_sandbox_workspace(path: Path | None) -> Iterator[None]:
    with _sandbox_workspace_slot.bind(path):
        yield
