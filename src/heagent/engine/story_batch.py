"""Story 并行批执行：批派生纯函数 + 批收集 + 回调调用契约。

从 workflow_runner 拆出的执行关注点：批派生是推导不是状态（AD-16，同输入同输出、
重启/重放安全）；批收集经 ``gather(return_exceptions=True)`` 双语义（AD-19）；回调
签名探测 fail-closed（宽签名不算实现契约）。观测经注入的 ``emit`` 端口走
``_emit_step_event`` 隔离包装（住 observability），状态写点全在调用方 runner。
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import PurePosixPath
from typing import TYPE_CHECKING, Any

from heagent.engine.observability import _emit_step_event
from heagent.pub.types import StoryExecutionContext

if TYPE_CHECKING:
    from collections.abc import Callable

    from heagent.engine.state_machine import WorkflowRunnerState
    from heagent.engine.workflow_resource import WorkflowStepResource
    from heagent.pub.types import StorySpec

#: 签名探测的位置参数种类。两者**故意不同**、勿统一：执行契约（≥3）不含 ``*args``（宽签名
#: 不算实现契约，fail-closed——tests/test_story_parallel_scheduling.py 有断言锚点）；
#: story 回调（≥2）含 ``*args``（历史宽容）。
_POSITIONAL_KINDS = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
_POSITIONAL_KINDS_WITH_VARARGS = (*_POSITIONAL_KINDS, inspect.Parameter.VAR_POSITIONAL)


def _positional_arity(callback: Callable[..., Any], kinds: tuple[inspect._ParameterKind, ...], minimum: int) -> bool:
    """``kinds`` 过滤后的显式位置参数 ≥ ``minimum`` 即真；签名不可得（TypeError/ValueError）fail-closed 假。"""
    try:
        signature = inspect.signature(callback)
    except (TypeError, ValueError):
        return False
    positional = [parameter for parameter in signature.parameters.values() if parameter.kind in kinds]
    return len(positional) >= minimum


def write_set_parts(entry: str) -> tuple[str, ...]:
    """写集条目 → 规范路径段（交集/覆盖判定的纯词法形态，零文件系统 I/O）。

    分隔符统一、大小写折叠（Windows 不敏感）；空串 / ``.`` 产出空段。含 ``..`` 的条目按
    字面段参与前缀判定——可能误报冲突（fail-closed 方向，安全），真实越界由围栏的
    ``resolve_under_root`` 兜底（死条目永不匹配，见 52-1）。模块级公共函数：宿主审计
    （cli/goal）与引擎批派生必须消费同一份词法，不得各写一份（AD-18 同源诉求）。
    """

    text = entry.strip().replace("\\", "/").casefold()
    return tuple(segment for segment in PurePosixPath(text).parts if segment not in {"", ".", "/"})


def write_set_entries_overlap(a: tuple[str, ...], b: tuple[str, ...]) -> bool:
    """两条目是否路径相交：一方是另一方的前缀（相等亦算）——目录条目覆盖子树。"""
    return a == b[: len(a)] or b == a[: len(b)]


def _accepts_execution(callback: Callable[..., Any]) -> bool:
    """回调是否实现三参执行上下文契约（Epic 52 AD-17 授权条件 3）。

    仿 ``_accepts_story`` 的签名探测：**显式**位置参数 ≥3 = 宿主声明了
    ``(step, story, execution)`` 形状、实现了写集围栏 + Git 审计契约，才有能力接住
    :class:`StoryExecutionContext`。两参老回调 → fail-closed 串行；``*args`` 形状的
    回调**不算**实现契约（fail-closed：宽签名测试桩不得借 varargs 意外获得并发授权）。
    """
    return _positional_arity(callback, _POSITIONAL_KINDS, minimum=3)


def _parallel_batch(state: WorkflowRunnerState, step: WorkflowStepResource, specs: list[StorySpec]) -> list[StorySpec]:
    """批派生纯函数（Epic 52 AD-16）：批次是推导不是状态，每次推进重新计算。

    从 ``story_index`` 起、遇首个不合规未完成 Story 即止；已完成成员跳过（不入批也不
    截断——批内有洞恢复时重推导）。七条件见 Epic 52 ARCHITECTURE-SPINE §2：上限、
    未撤销闩、三参契约三者由调用方前置检查；本函数检查同 non-empty ``parallel_group``、
    ``write_set`` 非空且批内两两不相交（路径段前缀判定：``src`` 覆盖 ``src/x.py``）、
    ``depends_on ⊆ completed_stories``（不允许依赖批内成员——依赖并发中的 Story 不可证
    安全）、批大小 ≤ 上限。同输入同输出，重启/重放安全。
    """
    first = specs[state.story_index]
    if not first.parallel_group or not first.write_set:
        return [first]
    if not all(dependency in state.completed_stories for dependency in first.depends_on):
        return [first]
    batch = [first]
    claimed = [write_set_parts(entry) for entry in first.write_set]
    for candidate in specs[state.story_index + 1 :]:
        if len(batch) >= step.max_parallel_stories:
            break
        if candidate.id in state.completed_stories:
            continue
        if not candidate.parallel_group or candidate.parallel_group != first.parallel_group:
            break
        if not candidate.write_set:
            break
        if not all(dependency in state.completed_stories for dependency in candidate.depends_on):
            break
        candidate_entries = [write_set_parts(entry) for entry in candidate.write_set]
        if any(
            write_set_entries_overlap(claimed_entry, candidate_entry)
            for claimed_entry in claimed
            for candidate_entry in candidate_entries
        ):
            break
        batch.append(candidate)
        claimed.extend(candidate_entries)
    return batch


def _execution_context(active_story: StorySpec, batch: list[StorySpec]) -> StoryExecutionContext:
    """构造单条 Story 的执行上下文（围栏输入 + 审计输入，AD-17/AD-19）。"""
    parallel = len(batch) > 1
    return StoryExecutionContext(
        story_id=active_story.id,
        parallel=parallel,
        write_allowlist=list(active_story.write_set),
        batch_members=[member.id for member in batch],
        sibling_write_sets=(
            {member.id: list(member.write_set) for member in batch if member.id != active_story.id} if parallel else {}
        ),
    )


async def _gather_story_batch(
    step: WorkflowStepResource,
    batch: list[StorySpec],
    callback: Callable[..., Any],
    emit: Callable[..., None] | None,
) -> list[Any]:
    """并发执行一个授权批（AD-19）：``gather(return_exceptions=True)`` 双语义。

    批内单 Story 异常作为结果位收集（不取消同批，与 ``agent/tool_execution`` 的工具
    批先例同构）；步骤级取消传播取消整批（CancelledError 上抛，由 run_step 统一 except
    记 cancelled 落 PENDING）。发 ``workflow_story_batch_scheduled``（成员 + 依据）。
    """
    contexts = {member.id: _execution_context(member, batch) for member in batch}
    _emit_step_event(
        emit,
        "workflow_story_batch_scheduled",
        step=step,
        story=None,
        members=[member.id for member in batch],
        limit=step.max_parallel_stories,
    )
    return list(
        await asyncio.gather(
            *(_invoke_callback(callback, step, member, contexts[member.id]) for member in batch),
            return_exceptions=True,
        )
    )


def _invoke_callback(
    callback: Callable[..., Any],
    step: WorkflowStepResource,
    story: StorySpec | None,
    execution: StoryExecutionContext | None = None,
) -> Any:
    if story is not None:
        if not _accepts_story(callback):
            raise TypeError("story-loop step callback must accept (step, story)")
        if execution is not None:
            return callback(step, story, execution)
        return callback(step, story)
    return callback(step)


def _accepts_story(callback: Callable[..., Any]) -> bool:
    return _positional_arity(callback, _POSITIONAL_KINDS_WITH_VARARGS, minimum=2)
