"""Tests for smart routing (HeuristicRouter + RoutingProvider)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from heagent.exceptions import ProviderError
from heagent.providers.base import ProviderMetadata
from heagent.providers.router import HeuristicRouter, RouteDecision, RoutingProvider, active_model
from heagent.types import Message, ProviderResponse, Role, TokenUsage, ToolSchema

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


def _make_provider(name: str, content: str = "ok") -> object:
    """构造测试用 FakeProvider，记录 send/stream 调用次数。"""

    class FakeProvider:
        _name = name
        _content = content
        send_calls = 0
        stream_calls = 0

        async def send(self, messages: list[Message], *, tools: list[ToolSchema] | None = None) -> ProviderResponse:
            self.send_calls += 1
            return ProviderResponse(
                content=self._content,
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                model=self._name,
                finish_reason="stop",
            )

        async def stream(
            self, messages: list[Message], *, tools: list[ToolSchema] | None = None
        ) -> AsyncIterator[ProviderResponse]:
            self.stream_calls += 1
            yield ProviderResponse(
                content=self._content,
                usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                model=self._name,
                finish_reason="stop",
            )

        def get_metadata(self) -> ProviderMetadata:
            return ProviderMetadata(name=self._name, model=self._name, supports_streaming=True, supports_tools=True)

    return FakeProvider()


def _msg(content: str, role: Role = Role.USER) -> Message:
    return Message(role=role, content=content)


class TestHeuristicRouter:
    def test_default_fast(self) -> None:
        router = HeuristicRouter(fast="fast", pro="pro")
        decision = router.route([_msg("你好")], None)
        assert decision == RouteDecision(provider="fast", reason="default_fast")

    def test_chinese_keyword_routes_pro(self) -> None:
        router = HeuristicRouter(fast="fast", pro="pro")
        decision = router.route([_msg("帮我分析一下这只股票的走势")], None)
        assert decision.provider == "pro"
        assert decision.reason.startswith("keyword:")

    def test_english_keyword_case_insensitive(self) -> None:
        router = HeuristicRouter(fast="fast", pro="pro")
        decision = router.route([_msg("Please ANALYZE this algorithm")], None)
        assert decision.provider == "pro"
        assert decision.reason == "keyword:analyze"

    def test_reasoning_continuity_routes_pro(self) -> None:
        """ASSISTANT 消息携带 reasoning_content → 推理链续接，停留 pro（即使无关键词）。"""
        router = HeuristicRouter(fast="fast", pro="pro")
        messages = [
            _msg("hello"),
            Message(role=Role.ASSISTANT, content="...", reasoning_content="thinking..."),
            _msg("继续"),
        ]
        decision = router.route(messages, None)
        assert decision == RouteDecision(provider="pro", reason="reasoning_continuity")

    def test_reasoning_continuity_precedes_keyword(self) -> None:
        """推理链续接优先级高于关键词（其实两者都指向 pro，这里验证 reason 取值）。"""
        router = HeuristicRouter(fast="fast", pro="pro")
        messages = [
            Message(role=Role.ASSISTANT, content="...", reasoning_content="thinking..."),
            _msg("分析一下"),
        ]
        decision = router.route(messages, None)
        assert decision.reason == "reasoning_continuity"

    def test_custom_keywords_merge_not_replace(self) -> None:
        """自定义关键词追加到内置表，而非覆盖——内置词仍生效。"""
        router = HeuristicRouter(fast="fast", pro="pro", reasoning_keywords=["审计"])
        assert router.route([_msg("请审计")], None).provider == "pro"  # 自定义词
        assert router.route([_msg("请分析")], None).provider == "pro"  # 内置词仍生效

    def test_keyword_matches_any_user_message(self) -> None:
        """关键词扫描遍历全部 USER 消息，不止最后一条（多轮后最新消息可能是 TOOL）。"""
        router = HeuristicRouter(fast="fast", pro="pro")
        messages = [
            _msg("帮我规划一个复杂方案"),
            Message(role=Role.ASSISTANT, content="好的"),
            Message(role=Role.TOOL, content="tool output", tool_call_id="1"),
        ]
        decision = router.route(messages, None)
        assert decision.provider == "pro"

    def test_mid_tier_routes_mid_keyword(self) -> None:
        """配置了 mid 档时，中档关键词 → mid。"""
        router = HeuristicRouter(fast="terra", mid="luna", pro="sol")
        decision = router.route([_msg("帮我总结一下这篇文章")], None)
        assert decision == RouteDecision(provider="luna", reason="mid_keyword:总结")

    def test_no_mid_tier_ignores_mid_keywords(self) -> None:
        """未配置 mid 档时，中档关键词不回退到 mid，直接兜底 fast。"""
        router = HeuristicRouter(fast="fast", pro="pro")
        decision = router.route([_msg("帮我总结一下")], None)
        assert decision == RouteDecision(provider="fast", reason="default_fast")

    def test_complex_keyword_precedes_mid(self) -> None:
        """复杂关键词优先级高于中档关键词：同时命中时路由到 sol。"""
        router = HeuristicRouter(fast="terra", mid="luna", pro="sol")
        decision = router.route([_msg("帮我分析并总结这段代码")], None)
        assert decision.provider == "sol"

    def test_mid_custom_keywords_merge_not_replace(self) -> None:
        """自定义中档词追加到内置表，内置词仍生效。"""
        router = HeuristicRouter(fast="terra", mid="luna", pro="sol", mid_keywords=["排版"])
        assert router.route([_msg("请排版")], None).provider == "luna"  # 自定义词
        assert router.route([_msg("请总结")], None).provider == "luna"  # 内置词仍生效


class TestRoutingProvider:
    def test_requires_at_least_one(self) -> None:
        with pytest.raises(ValueError):
            RoutingProvider({}, HeuristicRouter(), default="fast")

    def test_default_must_be_in_pool(self) -> None:
        with pytest.raises(ValueError):
            RoutingProvider({"fast": _make_provider("fast")}, HeuristicRouter(), default="missing")

    async def test_send_routes_fast_by_default(self) -> None:
        fast = _make_provider("fast")
        pro = _make_provider("pro")
        provider = RoutingProvider({"fast": fast, "pro": pro}, HeuristicRouter(fast="fast", pro="pro"), default="fast")
        resp = await provider.send([_msg("你好")])
        assert resp.model == "fast"
        assert fast.send_calls == 1
        assert pro.send_calls == 0
        assert provider.last_decision == RouteDecision(provider="fast", reason="default_fast")

    async def test_send_routes_pro_on_keyword(self) -> None:
        fast = _make_provider("fast")
        pro = _make_provider("pro")
        provider = RoutingProvider({"fast": fast, "pro": pro}, HeuristicRouter(fast="fast", pro="pro"), default="fast")
        resp = await provider.send([_msg("请分析这段代码")])
        assert resp.model == "pro"
        assert pro.send_calls == 1
        assert fast.send_calls == 0

    async def test_send_falls_back_to_default_on_unknown_route(self) -> None:
        """Router 返回池外名称时应回退 default，而非 KeyError。"""
        fast = _make_provider("fast")

        class BadRouter:
            def route(self, messages: list[Message], tools: list[ToolSchema] | None) -> RouteDecision:
                return RouteDecision(provider="ghost", reason="oops")

        provider = RoutingProvider({"fast": fast}, BadRouter(), default="fast")
        resp = await provider.send([_msg("hi")])
        assert resp.model == "fast"
        assert provider.last_decision is not None
        assert provider.last_decision.provider == "fast"
        assert provider.last_decision.reason.startswith("fallback_from:ghost")

    async def test_stream_routes_correctly(self) -> None:
        fast = _make_provider("fast")
        pro = _make_provider("pro")
        provider = RoutingProvider({"fast": fast, "pro": pro}, HeuristicRouter(fast="fast", pro="pro"), default="fast")
        chunks = [c async for c in provider.stream([_msg("请证明这个定理")])]
        assert chunks[0].model == "pro"
        assert pro.stream_calls == 1
        assert fast.stream_calls == 0

    def test_get_metadata(self) -> None:
        fast = _make_provider("fast")
        pro = _make_provider("pro")
        provider = RoutingProvider({"fast": fast, "pro": pro}, HeuristicRouter(fast="fast", pro="pro"), default="fast")
        meta = provider.get_metadata()
        assert meta.name == "routing"
        assert meta.model == "fast:fast, pro:pro"
        assert meta.supports_streaming is True
        assert meta.supports_tools is True

    def test_get_metadata_conservative_capability(self) -> None:
        """能力取 all 交集：任一 provider 不支持则整体宣称不支持。"""

        class NoStreamProvider:
            def get_metadata(self) -> ProviderMetadata:
                return ProviderMetadata(name="slow", model="slow", supports_streaming=False, supports_tools=True)

        fast = _make_provider("fast")
        provider = RoutingProvider(
            {"fast": fast, "slow": NoStreamProvider()},
            HeuristicRouter(fast="fast", pro="slow"),
            default="fast",
        )
        assert provider.get_metadata().supports_streaming is False

    def test_names(self) -> None:
        provider = RoutingProvider(
            {"fast": _make_provider("fast"), "pro": _make_provider("pro")},
            HeuristicRouter(),
            default="fast",
        )
        assert provider.names == ["fast", "pro"]
        assert provider.default == "fast"

    async def test_set_force_overrides_router(self) -> None:
        """set_force('pro') 后无视启发式路由，简单消息也走 pro。"""
        fast = _make_provider("fast")
        pro = _make_provider("pro")
        provider = RoutingProvider({"fast": fast, "pro": pro}, HeuristicRouter(fast="fast", pro="pro"), default="fast")
        provider.set_force("pro")
        resp = await provider.send([_msg("你好")])
        assert resp.model == "pro"
        assert pro.send_calls == 1
        assert fast.send_calls == 0
        assert provider.last_decision == RouteDecision(provider="pro", reason="forced")

    async def test_clear_force_restores_auto(self) -> None:
        """set_force(None) 后恢复启发式自动路由。"""
        fast = _make_provider("fast")
        pro = _make_provider("pro")
        provider = RoutingProvider({"fast": fast, "pro": pro}, HeuristicRouter(fast="fast", pro="pro"), default="fast")
        provider.set_force("pro")
        await provider.send([_msg("你好")])
        provider.set_force(None)
        resp = await provider.send([_msg("你好")])
        assert resp.model == "fast"
        assert provider.last_decision == RouteDecision(provider="fast", reason="default_fast")

    def test_set_force_invalid_raises(self) -> None:
        provider = RoutingProvider(
            {"fast": _make_provider("fast"), "pro": _make_provider("pro")},
            HeuristicRouter(fast="fast", pro="pro"),
            default="fast",
        )
        with pytest.raises(ValueError):
            provider.set_force("ghost")

    def test_force_property(self) -> None:
        provider = RoutingProvider(
            {"fast": _make_provider("fast"), "pro": _make_provider("pro")},
            HeuristicRouter(fast="fast", pro="pro"),
            default="fast",
        )
        assert provider.force is None
        provider.set_force("pro")
        assert provider.force == "pro"

    def test_constructor_force(self) -> None:
        provider = RoutingProvider(
            {"fast": _make_provider("fast"), "pro": _make_provider("pro")},
            HeuristicRouter(fast="fast", pro="pro"),
            default="fast",
            force="pro",
        )
        assert provider.force == "pro"
        assert provider.current_model == "pro"

    def test_current_model_reflects_force_immediately(self) -> None:
        provider = RoutingProvider(
            {"fast": _make_provider("fast"), "pro": _make_provider("pro")},
            HeuristicRouter(fast="fast", pro="pro"),
            default="fast",
        )
        provider.set_force("pro")
        assert provider.current_model == "pro"


class TestCurrentModel:
    """RoutingProvider.current_model —— 当前实际命中的模型名（状态栏显示用）。"""

    def test_defaults_to_default_model_before_routing(self) -> None:
        provider = RoutingProvider(
            {"fast": _make_provider("fast"), "pro": _make_provider("pro")},
            HeuristicRouter(fast="fast", pro="pro"),
            default="fast",
        )
        assert provider.current_model == "fast"

    async def test_reflects_last_decision(self) -> None:
        provider = RoutingProvider(
            {"fast": _make_provider("fast"), "pro": _make_provider("pro")},
            HeuristicRouter(fast="fast", pro="pro"),
            default="fast",
        )
        await provider.send([_msg("请分析这段代码")])
        assert provider.current_model == "pro"

    async def test_falls_back_to_default_on_unknown_route(self) -> None:
        fast = _make_provider("fast")

        class BadRouter:
            def route(self, messages: list[Message], tools: list[ToolSchema] | None) -> RouteDecision:
                return RouteDecision(provider="ghost", reason="oops")

        provider = RoutingProvider({"fast": fast}, BadRouter(), default="fast")
        await provider.send([_msg("hi")])
        assert provider.current_model == "fast"


class TestActiveModel:
    """active_model() —— 递归解包嵌套 provider，取当前实际模型名。"""

    def test_routing_provider(self) -> None:
        provider = RoutingProvider(
            {"fast": _make_provider("fast"), "pro": _make_provider("pro")},
            HeuristicRouter(fast="fast", pro="pro"),
            default="fast",
        )
        assert active_model(provider) == "fast"

    async def test_reflects_last_decision(self) -> None:
        provider = RoutingProvider(
            {"fast": _make_provider("fast"), "pro": _make_provider("pro")},
            HeuristicRouter(fast="fast", pro="pro"),
            default="fast",
        )
        await provider.send([_msg("请分析")])
        assert active_model(provider) == "pro"

    def test_unwraps_nested_wrapper(self) -> None:
        inner = RoutingProvider(
            {"fast": _make_provider("fast"), "pro": _make_provider("pro")},
            HeuristicRouter(fast="fast", pro="pro"),
            default="fast",
        )

        class Wrapper:
            def __init__(self, child: object) -> None:
                self._child = child

            @property
            def current(self) -> object:
                return self._child

        assert active_model(Wrapper(inner)) == "fast"

    def test_returns_none_for_plain_provider(self) -> None:
        assert active_model(_make_provider("plain")) is None

    def test_returns_none_for_wrapper_without_routing(self) -> None:
        plain = _make_provider("plain")

        class Wrapper:
            @property
            def current(self) -> object:
                return plain

        assert active_model(Wrapper()) is None


class TestInPoolFallback:
    """池内兄弟回退：限流/瞬时错误先试池内兄弟（同 vendor），非瞬时错误直接上抛。

    语义见 RoutingProvider docstring：flash 过载 → pro 接管，仍失败才上抛给外层
    SwitchableProvider 跨 vendor 回退——避免「flash 单模型过载导致整条目跳 vendor」。
    """

    @staticmethod
    def _failing(error: Exception) -> object:
        class FailingProvider:
            async def send(self, messages: list[Message], *, tools: list[ToolSchema] | None = None) -> ProviderResponse:
                raise error

            async def stream(
                self, messages: list[Message], *, tools: list[ToolSchema] | None = None
            ) -> AsyncIterator[ProviderResponse]:
                raise error
                yield  # pragma: no cover - 使本函数成为 async generator

            def get_metadata(self) -> ProviderMetadata:
                return ProviderMetadata(name="fail", model="fail-m", supports_streaming=True, supports_tools=True)

        return FailingProvider()

    def _routing(self, failing: object, ok: object) -> RoutingProvider:
        router = HeuristicRouter(fast="fast", pro="pro")
        return RoutingProvider({"fast": failing, "pro": ok}, router, default="fast")

    @pytest.mark.asyncio
    async def test_send_rate_limited_falls_back_to_sibling(self) -> None:
        """flash 429（限流）→ 池内 pro 接管，不跨 vendor 上抛。"""
        routing = self._routing(self._failing(ProviderError("rate limited", status_code=429)), _make_provider("pro"))
        response = await routing.send([_msg("你好")])  # 简单消息 → fast → 429 → pro
        assert response.model == "pro"

    @pytest.mark.asyncio
    async def test_send_transient_falls_back_to_sibling(self) -> None:
        """flash 503（瞬时）→ 池内 pro 接管。"""
        routing = self._routing(self._failing(ProviderError("service unavailable: 503")), _make_provider("pro"))
        response = await routing.send([_msg("你好")])
        assert response.model == "pro"

    @pytest.mark.asyncio
    async def test_send_non_transient_raises(self) -> None:
        """401（鉴权失败，换兄弟模型也不会好）→ 不回退，直接上抛。"""
        routing = self._routing(self._failing(ProviderError("unauthorized", status_code=401)), _make_provider("pro"))
        with pytest.raises(ProviderError):
            await routing.send([_msg("你好")])

    @pytest.mark.asyncio
    async def test_stream_falls_back_before_first_chunk(self) -> None:
        """流式在首 chunk 前失败 → 改道兄弟；输出全部来自兄弟。"""
        routing = self._routing(self._failing(ProviderError("rate limited", status_code=429)), _make_provider("pro"))
        chunks = [c async for c in routing.stream([_msg("你好")])]
        assert len(chunks) == 1
        assert chunks[0].model == "pro"

    @pytest.mark.asyncio
    async def test_single_provider_pool_has_no_sibling(self) -> None:
        """单 provider 池无兄弟可回退 → 原样上抛。"""
        router = HeuristicRouter(fast="fast", pro="fast")
        failing = self._failing(ProviderError("rate limited", status_code=429))
        routing = RoutingProvider({"fast": failing}, router, default="fast")
        with pytest.raises(ProviderError):
            await routing.send([_msg("你好")])
