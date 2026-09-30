"""Typed, capability-limited operations exposed to trusted GoalScript resources.

GoalScript is an orchestration language, not a second workflow engine.  The facade
only records operation requests; callers decide how each request is admitted and
executed through the existing Runner/governance path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence


ScriptOperation = Literal[
    "step",
    "parallel",
    "checkpoint",
    "input",
    "artifact",
    "decision",
    "validate",
]


class ScriptRequest(BaseModel):
    """One operation requested by a script."""

    model_config = ConfigDict(extra="forbid")

    operation: ScriptOperation
    name: str = ""
    names: list[str] = Field(default_factory=list)
    value: Any = None
    payload: dict[str, Any] = Field(default_factory=dict)
    note: str = ""


class ScriptResponse(BaseModel):
    """Typed result returned by the host for one operation."""

    model_config = ConfigDict(extra="forbid")

    accepted: bool = True
    value: Any = None
    reason: str = ""


class ScriptExecutionResult(BaseModel):
    """The host-visible result of one script invocation."""

    model_config = ConfigDict(extra="forbid")

    requests: list[ScriptRequest] = Field(default_factory=list)
    value: Any = None
    evidence: list[str] = Field(default_factory=list)


class GoalScript:
    """Small facade available to a GoalScript.

    Methods are intentionally asynchronous: every operation crosses the host
    boundary and can be routed through ``WorkflowRunner`` and its governance
    chain.  The facade has no filesystem, process, network, or runner reference.

    **两阶段语义（Story 51-7 的 A 语义）**：``input`` / ``artifact`` 是只读操作，脚本执行期
    同步作答（读已持久化的输入 / 产物）；``step`` / ``parallel`` / ``checkpoint`` /
    ``decision`` / ``validate`` 是**声明**——宿主在脚本返回后按声明顺序**提交**，因此这些
    调用返回 ``None``。阶段一里宿主只校验声明是否可兑现（未知门 / 未声明步骤 / 越出 Runner
    步骤顺序权的请求当场抛错），不落任何状态；脚本无法、也不需要自己写 checkpoint、
    workflow 或 current。
    """

    def __init__(
        self,
        *,
        inputs: Mapping[str, Any] | None = None,
        artifacts: Mapping[str, Any] | None = None,
        request: Any,
        max_requests: int,
    ) -> None:
        self._inputs = dict(inputs or {})
        self._artifacts = dict(artifacts or {})
        self._request = request
        self._max_requests = max_requests
        self._requests: list[ScriptRequest] = []

    @property
    def requests(self) -> tuple[ScriptRequest, ...]:
        return tuple(self._requests)

    async def _call(self, item: ScriptRequest) -> ScriptResponse:
        if len(self._requests) >= self._max_requests:
            raise RuntimeError(f"script request limit exceeded ({self._max_requests})")
        self._requests.append(item)
        response = await self._request(item)
        if not isinstance(response, ScriptResponse):
            raise TypeError("script host must return ScriptResponse")
        if not response.accepted:
            raise RuntimeError(response.reason or f"script operation rejected: {item.operation}")
        return response

    async def step(self, name: str, **payload: Any) -> Any:
        return (await self._call(ScriptRequest(operation="step", name=name, payload=payload))).value

    async def parallel(self, names: Sequence[str], **payload: Any) -> Any:
        return (
            await self._call(ScriptRequest(operation="parallel", names=[str(name) for name in names], payload=payload))
        ).value

    async def checkpoint(self, note: str = "") -> Any:
        return (await self._call(ScriptRequest(operation="checkpoint", note=note))).value

    async def input(self, name: str, default: Any = None) -> Any:
        if name in self._inputs:
            return self._inputs[name]
        response = await self._call(ScriptRequest(operation="input", name=name, value=default))
        return default if response.value is None else response.value

    async def artifact(self, name: str, default: Any = None) -> Any:
        if name in self._artifacts:
            return self._artifacts[name]
        response = await self._call(ScriptRequest(operation="artifact", name=name, value=default))
        return default if response.value is None else response.value

    async def decision(self, name: str, *, note: str = "", value: Any = None) -> Any:
        return (await self._call(ScriptRequest(operation="decision", name=name, note=note, value=value))).value

    async def validate(self, name: str, value: Any = None, **payload: Any) -> Any:
        return (await self._call(ScriptRequest(operation="validate", name=name, value=value, payload=payload))).value
