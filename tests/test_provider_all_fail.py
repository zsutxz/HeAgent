"""Provider 全部失败场景的容错测试 —— 重试×回退两层容错全耗尽时的端到端契约。

容错两层：重试中间件（``retry_with_backoff``，瞬时错误指数退避）包在
``ProviderChain``（逐 provider 回退）之外。全部 provider 失败时系统契约：

  - 异常显性上抛（显性失败）——不被吞、入口层拿原始 ``ProviderError`` 展示；
  - 最后一条错误原样保留（消息与 status_code 不被中间层覆盖）；
  - ``run_failed`` 事件携带结构化分类（``error_kind``）与原始错误消息——
    可程序化处理，这就是库层面的「友好错误」面；
  - ``run`` / ``run_stream`` 两条路径同契约。
"""

from __future__ import annotations

from typing import Any

import pytest

from heagent.agent.loop import AgentLoop
from heagent.agent.middleware import make_retry_middleware
from heagent.events.protocol import ERROR_KIND_EXCEPTION
from heagent.providers.base import ProviderMetadata
from heagent.providers.chain import ProviderChain
from heagent.pub.exceptions import ProviderError
from heagent.pub.types import Message, ProviderResponse, Role, TokenUsage

_RETRY_KWARGS = dict(max_attempts=2, base_delay=0.01, max_delay=0.02)


class FailingProvider:
    """每次 send/stream 都抛指定状态码 ProviderError 的桩 provider（调用计数留痕）。"""

    def __init__(self, name: str, message: str, status_code: int) -> None:
        self.name = name
        self.message = message
        self.status_code = status_code
        self.send_calls = 0
        self.stream_calls = 0

    async def send(self, messages: list[Message], **_kw: object) -> ProviderResponse:
        self.send_calls += 1
        raise ProviderError(self.message, status_code=self.status_code)

    async def stream(self, messages: list[Message], **_kw: object) -> object:
        self.stream_calls += 1
        raise ProviderError(self.message, status_code=self.status_code)
        yield  # pragma: no cover — 使其成为异步生成器

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name=self.name, model=self.name)


class TestRetryFallbackExhaustion:
    """重试×回退组合层：全耗尽时每层都完整走过、最后错误原样浮出。"""

    async def test_retry_reenters_chain_then_exhausts(self) -> None:
        """末端错误为瞬时（503）：重试中间件重入整条链，每个 provider 被打满重试次数。"""
        p1 = FailingProvider("p1", "primary exploded", 503)
        p2 = FailingProvider("p2", "secondary exploded", 503)
        chain = ProviderChain([p1, p2])
        loop_provider = chain  # 重试中间件包在 chain 外——由测试直接组合验证
        mw = make_retry_middleware(**_RETRY_KWARGS)

        from heagent.agent.middleware import Request, compose

        async def handler(req: Request) -> ProviderResponse:
            return await loop_provider.send(req.messages)

        call = compose([mw], handler)

        with pytest.raises(ProviderError) as excinfo:
            await call(Request(messages=[Message(role=Role.USER, content="hi")]))
        # 最后一条错误原样浮出：消息与状态码都是链尾 provider 的
        assert excinfo.value.message == "secondary exploded"
        assert excinfo.value.status_code == 503
        # 重试重入整条链：每个 provider 都被打了 max_attempts 次
        assert p1.send_calls == 2
        assert p2.send_calls == 2

    async def test_non_transient_last_error_skips_retry(self) -> None:
        """末端错误为客户端错（400）：链回退耗尽后即抛，重试层不重入。"""
        p1 = FailingProvider("p1", "primary unavailable", 503)
        p2 = FailingProvider("p2", "bad request shape", 400)
        chain = ProviderChain([p1, p2])
        mw = make_retry_middleware(**_RETRY_KWARGS)

        from heagent.agent.middleware import Request, compose

        async def handler(req: Request) -> ProviderResponse:
            return await chain.send(req.messages)

        call = compose([mw], handler)

        with pytest.raises(ProviderError) as excinfo:
            await call(Request(messages=[Message(role=Role.USER, content="hi")]))
        assert excinfo.value.status_code == 400
        assert excinfo.value.message == "bad request shape"
        # 400 非瞬时：只走了一轮链，无重入
        assert p1.send_calls == 1
        assert p2.send_calls == 1


class TestLoopRunAllFail:
    """AgentLoop 非流式路径：全部 provider 失败 → 显性上抛 + run_failed 结构化事件。"""

    async def test_run_raises_and_emits_structured_run_failed(self) -> None:
        providers = [FailingProvider(f"p{i}", f"provider {i} down", 503) for i in range(3)]
        loop = AgentLoop(
            ProviderChain(providers),
            max_iterations=3,
            middlewares=[make_retry_middleware(**_RETRY_KWARGS)],
        )

        with pytest.raises(ProviderError):
            await loop.run("hi")

        # 每个 provider 都被打满重试次数（整链重入）
        assert all(p.send_calls == 2 for p in providers)
        failed = [e for e in loop.engine.events.recent_events if e.event_type == "run_failed"]
        assert len(failed) == 1
        details = failed[0].details
        # 结构化错误面：原始消息保留 + 封闭分类 + 真实耗时
        assert "provider 2 down" in details["error"]
        assert details["error_kind"] == ERROR_KIND_EXCEPTION
        assert details["duration_ms"] >= 0

    async def test_run_failure_does_not_poison_next_success(self) -> None:
        """全失败后同一 loop 换可用 provider 再跑：不残留失败态，正常完成。"""
        bad = FailingProvider("bad", "down", 503)

        class GoodProvider:
            async def send(self, messages: list[Message], **_kw: object) -> ProviderResponse:
                return ProviderResponse(
                    content="recovered",
                    usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                    model="good",
                    finish_reason="stop",
                )

            async def stream(self, messages: list[Message], **_kw: object) -> object:
                yield await self.send(messages)

            def get_metadata(self) -> ProviderMetadata:
                return ProviderMetadata(name="good", model="good")

        loop = AgentLoop(ProviderChain([bad]), max_iterations=3)
        with pytest.raises(ProviderError):
            await loop.run("first try")
        assert bad.send_calls == 1

        # 换纯可用 provider（新链）后同一 loop 恢复正常
        good = GoodProvider()
        loop.provider = ProviderChain([good])
        result = await loop.run("second try")
        assert result == "recovered"
        ok_events = [e for e in loop.engine.events.recent_events if e.event_type == "run_completed"]
        assert len(ok_events) == 1, "恢复后的 run 未恰好发出一次 run_completed"


class TestLoopStreamAllFail:
    """AgentLoop 流式路径：全部 provider 失败同契约。"""

    async def test_run_stream_raises_and_emits_run_failed(self) -> None:
        providers = [FailingProvider(f"s{i}", f"stream provider {i} down", 503) for i in range(2)]
        loop = AgentLoop(
            ProviderChain(providers),
            max_iterations=3,
            middlewares=[make_retry_middleware(**_RETRY_KWARGS)],
        )

        with pytest.raises(ProviderError):
            async for _ev in loop.run_stream("hi"):
                pass

        # 现状契约：流式路径 provider.stream 直调（stream_runtime 不经重试中间件），
        # 容错只剩 chain 内部回退——每个 provider 恰被打一次
        assert all(p.stream_calls == 1 for p in providers)
        failed = [e for e in loop.engine.events.recent_events if e.event_type == "run_failed"]
        assert len(failed) == 1
        assert "stream provider 1 down" in failed[0].details["error"]
        assert failed[0].details["error_kind"] == ERROR_KIND_EXCEPTION
