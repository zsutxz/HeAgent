"""Tests for smart routing (HeuristicRouter + RoutingProvider)."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from heagent.exceptions import ProviderError
from heagent.providers.base import ProviderMetadata
from heagent.providers.router import (
    HeuristicRouter,
    RouteDecision,
    RoutingProvider,
    active_model,
    active_route_reason,
    annotate_route,
    display_reason,
)
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

    def test_flash_reasoning_content_does_not_lock_pro(self) -> None:
        """回归：flash 也返回 reasoning_content，但不能因此锁死 pro。

        DeepSeek v4 的 flash/pro 都是思考模型，历史里出现 reasoning_content 并不代表
        上一轮用了 pro——若按「历史里有无 reasoning_content」判定，简单会话从第二轮起
        就会永久走 pro，fast 再也切不回。
        """
        router = HeuristicRouter(fast="fast", pro="pro")
        messages = [
            _msg("你好"),
            Message(role=Role.ASSISTANT, content="...", reasoning_content="thinking..."),
            _msg("继续"),
        ]
        decision = router.route(messages, None)
        assert decision == RouteDecision(provider="fast", reason="default_fast")

    def test_reasoning_continuity_after_pro_selection(self) -> None:
        """上一轮实际选中 pro + 思考痕迹仍在历史 → 续接 pro（即使关键词已滚出历史）。"""
        router = HeuristicRouter(fast="fast", pro="pro", continuity=True)
        router.note_selection("pro")
        messages = [
            Message(role=Role.ASSISTANT, content="...", reasoning_content="thinking..."),
            _msg("继续"),
        ]
        decision = router.route(messages, None)
        assert decision == RouteDecision(provider="pro", reason="reasoning_continuity")

    def test_reasoning_continuity_after_flash_selection(self) -> None:
        """上一轮实际是 fast → 即使历史里有 reasoning_content 也不续接 pro。"""
        router = HeuristicRouter(fast="fast", pro="pro", continuity=True)
        router.note_selection("fast")
        messages = [
            Message(role=Role.ASSISTANT, content="...", reasoning_content="thinking..."),
            _msg("继续"),
        ]
        assert router.route(messages, None).provider == "fast"

    def test_reasoning_continuity_requires_reasoning_trace(self) -> None:
        """上一轮是 pro，但思考痕迹已被压缩掉 → 不再续接，回落关键词/兜底。"""
        router = HeuristicRouter(fast="fast", pro="pro", continuity=True)
        router.note_selection("pro")
        assert router.route([_msg("继续")], None) == RouteDecision(provider="fast", reason="default_fast")

    def test_reasoning_continuity_precedes_keyword(self) -> None:
        """推理链续接优先级高于关键词（两者都指向 pro，这里验证 reason 取值）。"""
        router = HeuristicRouter(fast="fast", pro="pro", continuity=True)
        router.note_selection("pro")
        messages = [
            Message(role=Role.ASSISTANT, content="...", reasoning_content="thinking..."),
            _msg("分析一下"),
        ]
        assert router.route(messages, None).reason == "reasoning_continuity"

    def test_custom_keywords_merge_not_replace(self) -> None:
        """自定义关键词追加到内置表，而非覆盖——内置词仍生效。"""
        router = HeuristicRouter(fast="fast", pro="pro", reasoning_keywords=["审计"])
        assert router.route([_msg("请审计")], None).provider == "pro"  # 自定义词
        assert router.route([_msg("请分析")], None).provider == "pro"  # 内置词仍生效

    def test_keyword_scan_skips_trailing_assistant_and_tool(self) -> None:
        """反向查找最近一条 USER 消息：同一轮 tool 调用后尾部是 TOOL/ASSISTANT 也不漏判。"""
        router = HeuristicRouter(fast="fast", pro="pro")
        messages = [
            _msg("帮我规划一个方案"),
            Message(role=Role.ASSISTANT, content="好的"),
            Message(role=Role.TOOL, content="tool output", tool_call_id="1"),
        ]
        decision = router.route(messages, None)
        assert decision.provider == "pro"
        assert decision.reason == "keyword:规划"

    def test_keyword_scans_only_latest_user_message(self) -> None:
        """只按**当前请求**判定：历史命中过关键词不再让后续轮次持续走 pro。"""
        router = HeuristicRouter(fast="fast", pro="pro")
        messages = [
            _msg("帮我分析这段代码"),
            Message(role=Role.ASSISTANT, content="好的"),
            _msg("继续"),
        ]
        assert router.route(messages, None) == RouteDecision(provider="fast", reason="default_fast")

    def test_history_keyword_does_not_lock_pro_when_continuity_off(self) -> None:
        """回归：历史命中关键词 + 上一轮是 pro（未开 continuity）→ 简单追问回落 fast。"""
        router = HeuristicRouter(fast="fast", pro="pro")
        router.note_selection("pro")
        messages = [
            _msg("帮我分析这段代码"),
            Message(role=Role.ASSISTANT, content="...", reasoning_content="thinking..."),
            _msg("继续"),
        ]
        assert router.route(messages, None) == RouteDecision(provider="fast", reason="default_fast")

    def test_no_user_message_falls_back_fast(self) -> None:
        """没有任何 USER 消息（如仅 TOOL 结果）→ 兜底 fast，不误判 pro。"""
        router = HeuristicRouter(fast="fast", pro="pro")
        messages = [Message(role=Role.TOOL, content="分析 规划 推理", tool_call_id="1")]
        assert router.route(messages, None) == RouteDecision(provider="fast", reason="default_fast")

    def test_mid_keyword_scans_only_latest_user_message(self) -> None:
        """中档关键词同样只看最近一条 USER 消息（历史命中不再持续走 mid）。"""
        router = HeuristicRouter(fast="terra", mid="luna", pro="sol")
        messages = [
            _msg("帮我总结一下这篇文章"),
            Message(role=Role.ASSISTANT, content="好的"),
            _msg("继续"),
        ]
        assert router.route(messages, None) == RouteDecision(provider="terra", reason="default_fast")

    def test_continuity_disabled_by_default(self) -> None:
        """默认 continuity=False：一次 pro 不会把整个会话钉在 pro。"""
        router = HeuristicRouter(fast="fast", pro="pro")
        assert router.continuity is False
        router.note_selection("pro")
        messages = [
            Message(role=Role.ASSISTANT, content="...", reasoning_content="thinking..."),
            _msg("继续"),
        ]
        assert router.route(messages, None) == RouteDecision(provider="fast", reason="default_fast")

    def test_weak_question_words_do_not_route_pro_by_default(self) -> None:
        """纯疑问词（为什么/解释/why/explain）已移出内置表（pro 主要误判源）。"""
        router = HeuristicRouter(fast="fast", pro="pro")
        for text in ("为什么天空是蓝的", "解释一下这个词", "why is it so", "explain this"):
            assert router.route([_msg(text)], None) == RouteDecision(provider="fast", reason="default_fast")

    def test_weak_question_words_can_be_restored(self) -> None:
        """需要时可用自定义词把纯疑问词加回内置表（合并语义，不覆盖）。"""
        router = HeuristicRouter(fast="fast", pro="pro", reasoning_keywords=["为什么", "explain"])
        assert router.route([_msg("为什么天空是蓝的")], None).provider == "pro"
        assert router.route([_msg("explain this")], None).provider == "pro"

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

    async def test_router_notes_actual_selection(self) -> None:
        """_pick 后把实际选中的 provider 回传给路由器（可选钩子），供判据 1 使用。"""
        router = HeuristicRouter(fast="fast", pro="pro")
        provider = RoutingProvider(
            {"fast": _make_provider("fast"), "pro": _make_provider("pro")}, router, default="fast"
        )
        await provider.send([_msg("你好")])
        assert router.last_provider == "fast"
        await provider.send([_msg("请分析这段代码")])
        assert router.last_provider == "pro"

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
        # 构造期强制与 last_decision 同样自洽，状态行一开局就是 pro←forced。
        assert active_route_reason(provider) == "forced"

    def test_current_model_reflects_force_immediately(self) -> None:
        provider = RoutingProvider(
            {"fast": _make_provider("fast"), "pro": _make_provider("pro")},
            HeuristicRouter(fast="fast", pro="pro"),
            default="fast",
        )
        provider.set_force("pro")
        assert provider.current_model == "pro"

    def test_set_force_syncs_last_decision_immediately(self) -> None:
        """`/route <name>` 后状态行立即自洽（模型与理由来自同一决策）。

        回归（2026-09-10 实测）：force 只改 ``current_model``、``last_decision`` 仍是上一次
        启发式决策时，提示符会把新模型与旧理由拼在一起（如 ``gpt-5.6-luna←keyword:分析``）。
        """
        provider = RoutingProvider(
            {"fast": _make_provider("fast"), "pro": _make_provider("pro")},
            HeuristicRouter(fast="fast", pro="pro"),
            default="fast",
        )
        provider.set_force("pro")
        assert provider.last_decision == RouteDecision(provider="pro", reason="forced")
        assert annotate_route(provider, provider.current_model) == "pro←forced"

    async def test_force_replaces_stale_auto_reason(self) -> None:
        """已有 default_fast 决策时强制 → 旧理由被替换，不再混进状态行。"""
        provider = RoutingProvider(
            {"fast": _make_provider("fast"), "pro": _make_provider("pro")},
            HeuristicRouter(fast="fast", pro="pro"),
            default="fast",
        )
        await provider.send([_msg("你好")])
        assert active_route_reason(provider) == "default_fast"
        provider.set_force("pro")
        assert annotate_route(provider, provider.current_model) == "pro←forced"

    async def test_clear_force_drops_stale_forced_decision(self) -> None:
        """``/route auto`` 清空强制 → 决策置空（不留 ``forced`` 残留），模型回落默认档。"""
        provider = RoutingProvider(
            {"fast": _make_provider("fast"), "pro": _make_provider("pro")},
            HeuristicRouter(fast="fast", pro="pro"),
            default="fast",
        )
        provider.set_force("pro")
        await provider.send([_msg("你好")])
        provider.set_force(None)
        assert provider.last_decision is None
        assert active_route_reason(provider) is None
        assert annotate_route(provider, provider.current_model) == "fast"


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


class TestActiveRouteReason:
    """active_route_reason() / annotate_route() —— 状态栏「为什么是这个模型」的可解释标记。"""

    @staticmethod
    def _provider() -> RoutingProvider:
        return RoutingProvider(
            {"fast": _make_provider("deepseek-flash"), "pro": _make_provider("deepseek-v4-pro")},
            HeuristicRouter(fast="fast", pro="pro"),
            default="fast",
        )

    def test_none_before_first_decision(self) -> None:
        """尚未路由过 → 无理由可标注，展示串逐字节不变。"""
        provider = self._provider()
        assert active_route_reason(provider) is None
        assert annotate_route(provider, "deepseek-flash") == "deepseek-flash"

    async def test_keyword_reason_after_send(self) -> None:
        """命中复杂度关键词 → reason=keyword:<词>，状态栏据此解释「为何走 pro」。"""
        provider = self._provider()
        await provider.send([_msg("帮我分析一下这段日志")])
        assert active_route_reason(provider) == "keyword:分析"
        assert annotate_route(provider, "deepseek-v4-pro") == "deepseek-v4-pro←keyword:分析"

    async def test_default_fast_reason_is_hidden_from_display(self) -> None:
        """无关键词 → reason 仍是 default_fast（观测可查），但不贴到状态行。"""
        provider = self._provider()
        await provider.send([_msg("你好")])
        assert active_route_reason(provider) == "default_fast"
        assert annotate_route(provider, "deepseek-flash") == "deepseek-flash"

    async def test_forced_reason(self) -> None:
        """`/route <name>` 强制后 reason=forced——状态栏可区分「强制」与「启发式选中」。"""
        provider = self._provider()
        provider.set_force("pro")
        await provider.send([_msg("你好")])
        assert active_route_reason(provider) == "forced"
        assert annotate_route(provider, "deepseek-v4-pro") == "deepseek-v4-pro←forced"

    async def test_unwraps_nested_wrapper(self) -> None:
        """SwitchableProvider 等包装层经 `current` 解包后仍能取到 reason。"""
        inner = self._provider()
        await inner.send([_msg("帮我分析一下")])

        class Wrapper:
            def __init__(self, child: object) -> None:
                self._child = child

            @property
            def current(self) -> object:
                return self._child

        assert active_route_reason(Wrapper(inner)) == "keyword:分析"

    def test_display_reason_filters_fallback_only(self) -> None:
        """display_reason 只滤兜底理由：其它理由（含未知值）原样透传。"""
        assert display_reason("default_fast") is None
        assert display_reason("keyword:分析") == "keyword:分析"
        assert display_reason("forced") == "forced"
        assert display_reason(None) is None
        assert display_reason("") is None

    def test_none_for_plain_provider(self) -> None:
        """非路由 provider → 无 reason（状态行保持旧格式）。"""
        assert active_route_reason(_make_provider("plain")) is None

    def test_none_for_wrapper_without_routing(self) -> None:
        """包装层解包到底也不是路由 provider → None。"""
        plain = _make_provider("plain")

        class Wrapper:
            @property
            def current(self) -> object:
                return plain

        assert active_route_reason(Wrapper()) is None
