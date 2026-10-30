"""cron → 通知发布点契约（Epic 58 story 58-2）。

58-1 只交付了「中枢 + 端点」，没有任何东西往里发布；本文件钉的是**发布侧**：

- 一次执行 = 一条通知，成功带 ``loop.run`` 的最终答案；
- 失败带异常首行，且异常**继续上抛**（scheduler 仍要 ledger.fail + 更新 last_run）；
- goal 自动推进分支零通知（D5：它不是「给用户的回答」）；
- 通知器自己炸了不影响 cron 结果（降级为「少一条通知」+ 一条 warning）。

回归价值：断点正是「``_run_job`` 把 ``loop.run(prompt)`` 的返回值丢掉」——上面第 1 条断言
（``text == "hello"``）就是那条链有没有接上的判据。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import pytest

from heagent.cli.wiring import _first_line, build_cron_job_runner
from heagent.config import reset_settings, resolve_runtime_config
from heagent.cron.jobs import JobStore
from heagent.engine import EngineContainer
from heagent.network.http_protocol import CronResultStatus

if TYPE_CHECKING:
    from pathlib import Path

    from heagent.engine.context import RunContext

pytestmark = pytest.mark.asyncio

JOB_ID = "1661798f"


@pytest.fixture(autouse=True)
def _reset_settings_singleton():
    """隔离 Settings 单例（与 test_wiring_loop_helpers 同一纪律）。"""
    reset_settings()
    yield
    reset_settings()


class _FakeLoop:
    """AgentLoop 替身：``run`` 直接交回预设答案或抛预设异常（不打 provider、不落盘）。"""

    answer: str = "hello"
    error: BaseException | None = None
    constructed: int = 0

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        type(self).constructed += 1
        self.args = args

    async def run(self, prompt: str) -> str:
        if type(self).error is not None:
            raise type(self).error
        return type(self).answer


@pytest.fixture()
def fake_loop(monkeypatch: pytest.MonkeyPatch) -> type[_FakeLoop]:
    """把 wiring 里的 AgentLoop 换成替身，并清掉 goal 识别（默认按普通 prompt 走）。"""
    _FakeLoop.answer = "hello"
    _FakeLoop.error = None
    _FakeLoop.constructed = 0
    monkeypatch.setattr("heagent.cli.wiring.AgentLoop", _FakeLoop)
    monkeypatch.setattr("heagent.cli.goal._goal_auto_goal_id", lambda prompt: None)
    return _FakeLoop


def _build_runner(engine: EngineContainer, notifier: Any) -> Any:
    return build_cron_job_runner(
        object(),  # provider 不被替身 loop 使用
        engine,
        resolve_runtime_config(),
        JobStore(),
        skills=None,
        facts=None,
        profile=None,
        retry_mw=lambda request, next_handler: next_handler(request),
        cron_notifier=notifier,
    )


def _cron_context(engine: EngineContainer, tmp_path: Path) -> RunContext:
    return engine.create_run_context(metadata={"kind": "cron", "job_id": JOB_ID}, workspace_root=str(tmp_path))


class TestCompletedPath:
    async def test_final_answer_is_delivered_once(self, fake_loop: type[_FakeLoop], tmp_path: Path) -> None:
        """``loop.run`` 的返回值必须流到通知器——断点 B 的正面判据。"""
        engine = EngineContainer.default(workspace_root=str(tmp_path))
        notifications: list[tuple[str, CronResultStatus, str]] = []
        runner = _build_runner(engine, lambda *args: notifications.append(args))

        await runner("说 hello", _cron_context(engine, tmp_path))

        assert notifications == [(JOB_ID, CronResultStatus.COMPLETED, "hello")]

    async def test_job_id_comes_from_run_context_metadata(self, fake_loop: type[_FakeLoop], tmp_path: Path) -> None:
        """job_id 只从 scheduler 写入的 metadata 取；缺失时退化为空串而不是崩。"""
        engine = EngineContainer.default(workspace_root=str(tmp_path))
        notifications: list[tuple[str, CronResultStatus, str]] = []
        runner = _build_runner(engine, lambda *args: notifications.append(args))

        await runner("普通任务", engine.create_run_context(workspace_root=str(tmp_path)))

        assert notifications == [("", CronResultStatus.COMPLETED, "hello")]


class TestFailurePath:
    async def test_first_line_is_delivered_and_the_exception_still_raises(
        self, fake_loop: type[_FakeLoop], tmp_path: Path
    ) -> None:
        """失败也送达，但**不吞异常**：scheduler 的 ledger.fail / last_run 全靠它。"""
        fake_loop.error = RuntimeError("provider exploded\nstack line two")
        engine = EngineContainer.default(workspace_root=str(tmp_path))
        notifications: list[tuple[str, CronResultStatus, str]] = []
        runner = _build_runner(engine, lambda *args: notifications.append(args))

        with pytest.raises(RuntimeError, match="provider exploded"):
            await runner("普通任务", _cron_context(engine, tmp_path))

        assert notifications == [(JOB_ID, CronResultStatus.FAILED, "provider exploded")]
        # 首行提取的两条退路：空消息回退到异常类型名；多行只取第一个非空行。
        assert _first_line(RuntimeError("")) == "RuntimeError"
        assert _first_line(RuntimeError("  \n second line")) == "second line"


class TestGoalBranch:
    async def test_goal_advance_never_notifies(
        self,
        fake_loop: type[_FakeLoop],
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """D5：goal 自动推进不是「给用户的回答」——零通知（也不构造 loop）。"""
        advanced: list[str] = []

        async def fake_advance(provider: Any, engine: Any, store: Any, goal_id: str) -> None:
            advanced.append(goal_id)

        monkeypatch.setattr("heagent.cli.goal._goal_auto_goal_id", lambda prompt: "goal-1")
        monkeypatch.setattr("heagent.cli.goal._goal_cron_advance", fake_advance)

        engine = EngineContainer.default(workspace_root=str(tmp_path))
        notifications: list[tuple[str, CronResultStatus, str]] = []
        runner = _build_runner(engine, lambda *args: notifications.append(args))

        await runner("goal:推进一下", _cron_context(engine, tmp_path))

        assert advanced == ["goal-1"]
        assert notifications == []


class TestNotifierIsolation:
    async def test_notifier_exception_does_not_change_the_cron_outcome(
        self, fake_loop: type[_FakeLoop], tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """通知送不出去只降级为「少一条通知」：cron 仍然算成功。"""
        engine = EngineContainer.default(workspace_root=str(tmp_path))

        def broken_notifier(*args: Any) -> None:
            raise RuntimeError("hub is on fire")

        runner = _build_runner(engine, broken_notifier)
        with caplog.at_level(logging.WARNING, logger="heagent.cli.wiring"):
            await runner("说 hello", _cron_context(engine, tmp_path))

        assert any("cron notifier failed" in record.message for record in caplog.records)

    async def test_no_notifier_is_a_no_op(self, fake_loop: type[_FakeLoop], tmp_path: Path) -> None:
        """两个开关都关（notifier=None）：runner 行为与 58-2 之前逐字一致（照常构造并跑 loop）。"""
        engine = EngineContainer.default(workspace_root=str(tmp_path))
        runner = _build_runner(engine, None)

        await runner("说 hello", _cron_context(engine, tmp_path))

        assert fake_loop.constructed == 1
