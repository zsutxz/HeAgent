"""wiring loop 装配共享缝契约（Phase 2 C3）。

``build_cron_job_runner``：goal 分支短路走 ``_goal_cron_advance``、其余 prompt 构造
一次性 loop 并透传装配参数；``ensure_runtime_config``：构造完成后的 engine 必有快照，
None 显性失败。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from heagent.config import reset_settings, resolve_runtime_config
from heagent.engine import EngineContainer
from heagent.wiring import build_cron_job_runner, ensure_runtime_config

if TYPE_CHECKING:
    from pathlib import Path

    from heagent.engine.context import RunContext

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset_settings_singleton():
    """隔离 Settings 单例（Phase 1 构造期解析契约）。"""
    reset_settings()
    yield
    reset_settings()


class _RecordingProvider:
    """只记录 send 调用的最小 provider。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def send(self, messages, *, tools=None):  # noqa: ANN001, ANN202
        self.calls.append(messages[-1].content)
        from heagent.types import ProviderResponse, TokenUsage

        return ProviderResponse(
            content="done",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            model="stub",
            finish_reason="stop",
        )

    async def stream(self, messages, *, tools=None):  # noqa: ANN001, ANN202
        yield await self.send(messages, tools=tools)

    def get_metadata(self):
        from heagent.providers.base import ProviderMetadata

        return ProviderMetadata(name="stub", model="stub")


@pytest.fixture()
def engine_container():
    return EngineContainer.default(workspace_root=None)


class TestEnsureRuntimeConfig:
    def test_returns_snapshot_after_construction(self, engine_container) -> None:
        config = ensure_runtime_config(engine_container)
        assert config is engine_container.runtime_config

    def test_none_fails_loud(self, engine_container) -> None:
        bare = engine_container
        bare.runtime_config = None  # 模拟「构造完成前的中间态」（__post_init__ 后实际不可达）
        with pytest.raises(RuntimeError, match="未解析"):
            ensure_runtime_config(bare)


class TestBuildCronJobRunner:
    async def test_goal_branch_short_circuits_to_advance(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, engine_container
    ) -> None:
        """goal 自动推进 prompt 不构造 loop，直接走 _goal_cron_advance。"""
        from heagent.cron.jobs import JobStore

        advanced: list[str] = []

        def fake_auto_goal_id(prompt: str) -> str | None:
            return "goal-123" if prompt.startswith("goal:") else None

        async def fake_advance(provider, engine, store, goal_id) -> None:  # noqa: ANN001
            advanced.append(goal_id)

        monkeypatch.setattr("heagent.cli_goal._goal_auto_goal_id", fake_auto_goal_id)
        monkeypatch.setattr("heagent.cli_goal._goal_cron_advance", fake_advance)

        config = resolve_runtime_config()
        provider = _RecordingProvider()
        runner = build_cron_job_runner(
            provider,
            engine_container,
            config,
            JobStore(),
            skills=None,
            facts=None,
            profile=None,
            retry_mw=lambda req, next_handler: next_handler(req),
        )
        run_context: RunContext = engine_container.create_run_context(workspace_root=str(tmp_path))
        await runner("goal:推进一下", run_context)

        assert advanced == ["goal-123"]
        assert provider.calls == []  # 未构造 loop、未调用 provider

    async def test_plain_prompt_builds_one_shot_loop(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, engine_container
    ) -> None:
        """普通 prompt 构造一次性 loop：装配参数透传，run 正常完成。"""
        from heagent.context.compressor import ContextCompressor
        from heagent.cron.jobs import JobStore

        monkeypatch.setattr("heagent.cli_goal._goal_auto_goal_id", lambda prompt: None)

        config = resolve_runtime_config()
        provider = _RecordingProvider()
        compressor = ContextCompressor(provider, threshold=10**9)
        runner = build_cron_job_runner(
            provider,
            engine_container,
            config,
            JobStore(),
            skills=None,
            facts=None,
            profile=None,
            max_iterations=7,
            retry_mw=lambda req, next_handler: next_handler(req),
            compressor=compressor,
            context_dir=str(tmp_path),
        )
        run_context: RunContext = engine_container.create_run_context(workspace_root=str(tmp_path))
        await runner("普通任务", run_context)

        assert provider.calls == ["普通任务"]
        # 一次性 loop 结束后 run_context 已被消费（事后产物可读）
        assert engine_container.events.recent_events  # 事件经同一 EventBus 汇聚
