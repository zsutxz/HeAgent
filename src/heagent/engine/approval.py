"""工具审批抽象（approval）。

本模块属于 ``engine/`` 运行时治理层（见 ``docs/frame.md`` 4.12）。为
:class:`~heagent.engine.policy.PolicyEngine` 产出的 ``APPROVAL_REQUIRED`` 裁决提供
**可注入的交互审批闭环**——库消费者（CLI / GUI）各自注入 :class:`ApprovalHandler`
实现，主循环（:class:`~heagent.agent.loop.AgentLoop`）与工具执行链零改动。

设计要点：

- ``ApprovalHandler`` 是 ``typing.Protocol``（结构化子类型），不强制继承；
- 默认未注入 handler 时，``APPROVAL_REQUIRED`` 维持既有语义（executor 等同阻断，
  **零回归**）；
- 审批授权写入 ``RunContext.metadata["approved_tools"]``（**per-run 粒度**），
  复用 :meth:`PolicyEngine._approval_granted` 的既有读取逻辑，不新增持久化；
- 授权后由调用方（``tool_execution.execute_tool_call``）**重新裁决**，使后续同类
  工具调用在同 run 内不再重复询问。

⚠ 安全立场（与文首声明一致，诚实不造假象）：审批是**策略层 defense-in-depth 标记**，
**不是安全边界**——``PolicyEngine`` 本就非真正边界（围栏可被绕过），审批仅把「要不要
执行」的决定权交给用户，不提供 OS 级隔离。须 OS 级沙箱兜底（见 CLAUDE.md 安全声明）。
"""

from __future__ import annotations

import asyncio
import sys
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import BaseModel

from heagent.types import ToolCall  # noqa: TC001

if TYPE_CHECKING:
    from collections.abc import Callable


class ApprovalDecision(StrEnum):
    """审批决策：同意执行 / 拒绝（fail-safe）。"""

    APPROVE = "approve"
    DENY = "deny"


class ApprovalRequest(BaseModel):
    """一次审批请求（Pydantic 模型，项目硬约束：跨模块数据用 Pydantic）。"""

    # 工具名（如 ``shell`` / ``<server>__<tool>``）。
    tool_name: str
    # 人类可读的审批原因（来自 PolicyVerdict.reason，含 annotations / 显式策略触发信息）。
    reason: str
    # 触发审批的原始工具调用（handler 可据 arguments 展示更多上下文）。
    call: ToolCall


@runtime_checkable
class ApprovalHandler(Protocol):
    """审批处理器协议：接收一次审批请求，异步返回决策。

    实现方（CLI / GUI）自行决定如何呈现询问（stdin / 弹窗 / 日志）。协议方法
    ``async`` 化以适配 ``asyncio.to_thread(input)`` 等非阻塞交互。
    """

    async def request(self, request: ApprovalRequest) -> ApprovalDecision:  # noqa: A002
        """对 ``request`` 做出审批决策。"""
        ...


class DenyAllApprovalHandler:
    """显式「全部拒绝」处理器（等价于未注入 handler 的现状语义）。

    用于脚本化 / 无人值守场景，保证可预测的 fail-safe 行为。
    """

    async def request(self, request: ApprovalRequest) -> ApprovalDecision:
        """一律拒绝。"""
        return ApprovalDecision.DENY


class ConsoleApprovalHandler:
    """交互式审批处理器：在 stdin 询问用户 ``[y/N]``。

    经 :func:`asyncio.to_thread` 在独立线程跑阻塞的 ``input``，避免卡住事件循环；
    EOF / KeyboardInterrupt 一律 fail-safe 拒绝。``prompt_fn`` 可注入以便测试
    （默认为 ``input``）。
    """

    def __init__(self, *, prompt_fn: Callable[[str], str] | None = None, stream: Callable[[str], None] | None = None) -> None:
        self._prompt_fn = prompt_fn or input
        self._stream = stream or (lambda msg: print(msg, file=sys.stderr, flush=True))

    async def request(self, request: ApprovalRequest) -> ApprovalDecision:
        """展示审批请求并读取用户应答；同意返回 APPROVE，否则 DENY。"""
        self._stream(
            f"[approval] Tool '{request.tool_name}' requires approval: {request.reason}\n"
            f"  Allow? [y/N] "
        )
        try:
            answer = await asyncio.to_thread(self._prompt_fn, "")
        except (EOFError, KeyboardInterrupt):
            return ApprovalDecision.DENY
        return ApprovalDecision.APPROVE if answer.strip().lower() in {"y", "yes"} else ApprovalDecision.DENY
