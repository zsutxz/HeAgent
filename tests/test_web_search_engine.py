"""web_search 引擎层测试 — httpx MockTransport 验证引擎契约、Tavily 形态与显性失败。"""

from __future__ import annotations

import json

import httpx
import pytest

from heagent.providers.retry import ErrorCategory
from heagent.tools.builtins import web_search_engine as wse

_TAVILY_PAYLOAD = {
    "query": "q",
    "results": [
        {"title": "T1", "url": "https://a.example/1", "content": "s1"},
        {"title": "T2", "url": "https://a.example/2", "content": "s2", "score": 0.9},
    ],
}


def _json_response(payload: dict, status: int = 200) -> httpx.Response:
    request = httpx.Request("POST", "https://api.tavily.com/search")
    return httpx.Response(status, json=payload, request=request)


def _install_mock(monkeypatch: pytest.MonkeyPatch, handler):
    """替换 httpx.AsyncClient 为 MockTransport；返回捕获容器（requests 列表）。"""
    captured: dict = {"requests": []}
    real_client = httpx.AsyncClient  # patch 前捕获真身，工厂内不得再走被替换的名字

    def _wrapped(request: httpx.Request) -> httpx.Response:
        captured["requests"].append(request)
        return handler(request)

    def _factory(*args, **kwargs):
        kwargs.pop("transport", None)
        return real_client(*args, transport=httpx.MockTransport(_wrapped), **kwargs)

    monkeypatch.setattr("httpx.AsyncClient", _factory)
    return captured


class TestTavilyRequestShape:
    async def test_posts_query_with_bearer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _install_mock(monkeypatch, lambda r: _json_response(_TAVILY_PAYLOAD))
        engine = wse.create_engine("tavily", api_key="k-test")
        results = await engine.search("hello world", max_results=2)

        req = captured["requests"][0]
        assert req.method == "POST"
        assert str(req.url) == "https://api.tavily.com/search"
        assert req.headers["Authorization"] == "Bearer k-test"
        assert json.loads(req.content) == {"query": "hello world", "max_results": 2}
        assert [r.title for r in results] == ["T1", "T2"]
        assert results[0].url == "https://a.example/1"
        assert results[0].snippet == "s1"

    async def test_item_without_url_is_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        payload = {"results": [{"title": "bad"}, {"title": "ok", "url": "https://x/1"}]}
        _install_mock(monkeypatch, lambda r: _json_response(payload))
        engine = wse.TavilyEngine(api_key="k")
        results = await engine.search("q")
        assert [r.title for r in results] == ["ok"]


class TestExplicitFailure:
    async def test_no_key_raises_without_http(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _install_mock(monkeypatch, lambda r: _json_response(_TAVILY_PAYLOAD))
        engine = wse.TavilyEngine(api_key="")
        with pytest.raises(wse.SearchEngineError, match="密钥"):
            await engine.search("q")
        assert captured["requests"] == []

    async def test_blank_query_raises_without_http(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _install_mock(monkeypatch, lambda r: _json_response(_TAVILY_PAYLOAD))
        engine = wse.TavilyEngine(api_key="k")
        with pytest.raises(wse.SearchEngineError, match="查询不能为空"):
            await engine.search("   ")
        assert captured["requests"] == []

    async def test_overlong_query_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _install_mock(monkeypatch, lambda r: _json_response(_TAVILY_PAYLOAD))
        engine = wse.TavilyEngine(api_key="k")
        with pytest.raises(wse.SearchEngineError, match="查询过长"):
            await engine.search("x" * 401)


class TestParamClamp:
    async def test_max_results_clamped_both_ends(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = _install_mock(monkeypatch, lambda r: _json_response(_TAVILY_PAYLOAD))
        engine = wse.TavilyEngine(api_key="k")
        await engine.search("q", max_results=0)
        assert json.loads(captured["requests"][0].content)["max_results"] == 1
        await engine.search("q", max_results=99)
        assert json.loads(captured["requests"][1].content)["max_results"] == 20


class TestErrorClassification:
    @pytest.mark.parametrize(
        ("status", "expected"),
        [
            (429, ErrorCategory.RATE_LIMITED),
            (401, ErrorCategory.AUTH_FAILED),
            (500, ErrorCategory.TRANSIENT),
            (400, ErrorCategory.NON_TRANSIENT),
        ],
    )
    async def test_http_status_classified(
        self, monkeypatch: pytest.MonkeyPatch, status: int, expected: ErrorCategory
    ) -> None:
        _install_mock(monkeypatch, lambda r: _json_response({"detail": "boom"}, status=status))
        engine = wse.TavilyEngine(api_key="k")
        with pytest.raises(wse.SearchEngineError) as excinfo:
            await engine.search("q")
        assert excinfo.value.category == expected
        assert excinfo.value.status_code == status

    async def test_timeout_is_transient(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("conn timeout", request=request)

        _install_mock(monkeypatch, _boom)
        engine = wse.TavilyEngine(api_key="k")
        with pytest.raises(wse.SearchEngineError) as excinfo:
            await engine.search("q")
        assert excinfo.value.category == ErrorCategory.TRANSIENT

    async def test_non_json_response_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        request = httpx.Request("POST", "https://api.tavily.com/search")
        _install_mock(monkeypatch, lambda r: httpx.Response(200, content=b"not-json", request=request))
        engine = wse.TavilyEngine(api_key="k")
        with pytest.raises(wse.SearchEngineError, match="非 JSON"):
            await engine.search("q")


class TestRegistry:
    async def test_config_switch_to_stub_engine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """配置切到替身引擎检索正常，src 零 diff（registry 注入替身工厂）。"""

        class StubEngine:
            async def search(self, query: str, max_results: int = 5) -> list[wse.SearchResult]:
                return [wse.SearchResult(title="stub", url="https://stub/1", snippet="s")]

        monkeypatch.setattr(wse, "_ENGINE_REGISTRY", dict(wse._ENGINE_REGISTRY))
        wse.register_engine("stub", lambda api_key: StubEngine())
        engine = wse.create_engine("stub", api_key="whatever")
        results = await engine.search("q")
        assert results[0].title == "stub"

    def test_unknown_engine_fails_loud(self) -> None:
        with pytest.raises(wse.SearchEngineError, match="未知检索引擎"):
            wse.create_engine("nonexistent-engine")
