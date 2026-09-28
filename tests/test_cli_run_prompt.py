"""``_run_prompt`` 收尾时对流任务的回收保证。

判据锚在**可观察行为**上：父任务收尾返回/抛出时，``_consume_stream`` 派生出的流任务必须已经
结束——被取消并 await 过，而不是留在后台继续往终端打印、或带着未取回的异常泄漏到会话结束。

背景（实测）：``asyncio.Runner`` 的 SIGINT 处理器把首次 Ctrl+C 转成**主任务 cancel**，父任务
通常停在 ``asyncio.wait`` 上（tty）而非 ``await run_task``；早期实现只取消监听用的等待任务，
于是流任务在父任务退出后仍在跑。
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any

from heagent.cli import interactive

if TYPE_CHECKING:
    import pytest


class _StubMonitor:
    """替掉真实键盘监听：``active`` 由用例决定，三个事件是普通 asyncio.Event。"""

    def __init__(self, active: bool) -> None:
        self._active = active
        self.interrupted = asyncio.Event()
        self.pause_toggle = asyncio.Event()
        self.resume = asyncio.Event()

    @property
    def active(self) -> bool:
        return self._active

    def start(self, loop: object) -> None: ...

    def stop(self) -> None: ...


def _install(monkeypatch: pytest.MonkeyPatch, *, active: bool) -> dict[str, Any]:
    """装桩：流任务记录自身并可被观察，键盘监听按 ``active`` 固定。"""
    observed: dict[str, Any] = {"started": False, "cancelled": False}

    async def fake_consume(*args: object, **kwargs: object) -> None:
        observed["task"] = asyncio.current_task()
        observed["started"] = True
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            observed["cancelled"] = True
            raise

    monkeypatch.setattr(interactive, "KeyInterruptMonitor", lambda: _StubMonitor(active))
    monkeypatch.setattr(interactive, "_echo_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(interactive, "_consume_stream", fake_consume)
    return observed


async def _run_then_cancel(
    monkeypatch: pytest.MonkeyPatch, *, active: bool
) -> tuple[asyncio.Task[None], dict[str, Any], str]:
    """起一次 ``_run_prompt``，等流任务跑起来，取消父任务并等它收尾。"""
    observed = _install(monkeypatch, active=active)
    parent = asyncio.create_task(interactive._run_prompt(None, "hi", None, "s"))
    while not observed["started"]:
        await asyncio.sleep(0)
    parent.cancel()
    outcome = "returned"
    try:
        await parent
    except asyncio.CancelledError:
        outcome = "cancelled"
    return parent, observed, outcome


async def test_parent_cancellation_reaps_the_stream_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """tty 路径（父任务停在 ``asyncio.wait``）：取消必须传播出去（否则 CLI 退不掉），
    且流任务此时已结束——不能留给事件循环收尾。"""
    parent, observed, outcome = await _run_then_cancel(monkeypatch, active=True)
    stream = observed["task"]
    assert outcome == "cancelled"
    assert parent.cancelled() is True
    assert observed["cancelled"] is True, "流任务应收到取消"
    assert stream.done() is True, "父任务收尾前必须已回收流任务"


async def test_reap_also_applies_when_the_cancel_hits_the_task_await(monkeypatch: pytest.MonkeyPatch) -> None:
    """非 tty 路径（``active=False``，父任务直接 ``await run_task``）：取消落点不同，
    回收保证不变。（不断言父任务返回/抛出，那条差异不属于本判据。）"""
    _, observed, _outcome = await _run_then_cancel(monkeypatch, active=False)
    assert observed["cancelled"] is True
    assert observed["task"].done() is True, "父任务收尾前必须已回收流任务"


async def test_run_prompt_without_cancellation_still_returns(monkeypatch: pytest.MonkeyPatch) -> None:
    """反面对照：正常跑完（无取消）不受回收逻辑影响，且不残留监听等待任务。"""
    observed: dict[str, Any] = {"started": False}

    async def quick_consume(*args: object, **kwargs: object) -> None:
        observed["started"] = True

    monkeypatch.setattr(interactive, "KeyInterruptMonitor", lambda: _StubMonitor(True))
    monkeypatch.setattr(interactive, "_echo_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(interactive, "_consume_stream", quick_consume)
    with contextlib.suppress(asyncio.CancelledError):
        await interactive._run_prompt(None, "hi", None, "s")
    assert observed["started"] is True
    pending = [task for task in asyncio.all_tasks() if not task.done() and task is not asyncio.current_task()]
    assert pending == [], f"收尾后不应留下在途任务: {pending}"
