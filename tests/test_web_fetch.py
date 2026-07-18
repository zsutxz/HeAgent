"""Web fetch 工具测试 — 使用 httpx MockTransport 验证 URL 抓取行为。"""

from __future__ import annotations

import httpx
import pytest

from heagent.tools.builtins.web import _is_allowed_content_type


def test_is_allowed_html() -> None:
    assert _is_allowed_content_type("text/html") is True


def test_is_allowed_json() -> None:
    assert _is_allowed_content_type("application/json") is True


def test_is_allowed_json_with_charset() -> None:
    assert _is_allowed_content_type("application/json; charset=utf-8") is True


def test_is_allowed_xml() -> None:
    assert _is_allowed_content_type("application/xml") is True


def test_is_allowed_plain() -> None:
    assert _is_allowed_content_type("text/plain") is True


def test_is_not_allowed_pdf() -> None:
    assert _is_allowed_content_type("application/pdf") is False


def test_is_not_allowed_image() -> None:
    assert _is_allowed_content_type("image/png") is False


def test_is_not_allowed_empty() -> None:
    assert _is_allowed_content_type("") is False


# ── 使用 httpx MockTransport 的集成测试 ──────────────────────────────────────


def _mock_transport(
    status: int = 200,
    body: str = "",
    content_type: str = "text/html; charset=utf-8",
    headers: dict | None = None,
) -> httpx.MockTransport:
    """创建返回指定响应的 MockTransport。"""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=status,
            content=body.encode("utf-8"),
            headers={"content-type": content_type, **(headers or {})},
        )

    return httpx.MockTransport(handler)


class TestWebFetch:
    @pytest.mark.asyncio
    async def test_fetch_html_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """抓取 HTML 页面返回内容。"""
        from heagent.tools.builtins.web import web_fetch

        body = "<html><body><h1>Hello</h1><p>World</p></body></html>"
        client = httpx.AsyncClient(transport=_mock_transport(body=body))
        monkeypatch.setattr("httpx.AsyncClient", lambda **kw: client)
        result = await web_fetch(url="https://example.com")
        assert "Hello" in result
        assert "World" in result

    @pytest.mark.asyncio
    async def test_fetch_json_api(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """抓取 JSON API 返回内容。"""
        from heagent.tools.builtins.web import web_fetch

        body = '{"status": "ok", "data": [1, 2, 3]}'
        client = httpx.AsyncClient(transport=_mock_transport(body=body, content_type="application/json"))
        monkeypatch.setattr("httpx.AsyncClient", lambda **kw: client)
        result = await web_fetch(url="https://api.example.com/data")
        assert "ok" in result
        assert "data" in result

    @pytest.mark.asyncio
    async def test_fetch_binary_content_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """二进制内容类型被拒绝。"""
        from heagent.tools.builtins.web import web_fetch

        client = httpx.AsyncClient(transport=_mock_transport(body="x", content_type="application/pdf"))
        monkeypatch.setattr("httpx.AsyncClient", lambda **kw: client)
        with pytest.raises(RuntimeError, match="不支持的内容类型"):
            await web_fetch(url="https://example.com/doc.pdf")

    @pytest.mark.asyncio
    async def test_fetch_http_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """HTTP 404 抛 RuntimeError。"""
        from heagent.tools.builtins.web import web_fetch

        client = httpx.AsyncClient(transport=_mock_transport(status=404, body="Not Found"))
        monkeypatch.setattr("httpx.AsyncClient", lambda **kw: client)
        with pytest.raises(RuntimeError, match="HTTP 404"):
            await web_fetch(url="https://example.com/missing")

    @pytest.mark.asyncio
    async def test_fetch_http_500(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """HTTP 500 抛 RuntimeError。"""
        from heagent.tools.builtins.web import web_fetch

        client = httpx.AsyncClient(transport=_mock_transport(status=500, body="Error"))
        monkeypatch.setattr("httpx.AsyncClient", lambda **kw: client)
        with pytest.raises(RuntimeError, match="HTTP 500"):
            await web_fetch(url="https://example.com/error")

    @pytest.mark.asyncio
    async def test_invalid_url_no_scheme(self) -> None:
        """无 http:// 前缀的 URL 抛 ValueError。"""
        from heagent.tools.builtins.web import web_fetch

        with pytest.raises(ValueError, match="必须以 http:// 或 https:// 开头"):
            await web_fetch(url="example.com")

    @pytest.mark.asyncio
    async def test_invalid_url_ftp(self) -> None:
        """非 http 协议抛 ValueError。"""
        from heagent.tools.builtins.web import web_fetch

        with pytest.raises(ValueError, match="必须以 http:// 或 https:// 开头"):
            await web_fetch(url="ftp://files.example.com")

    @pytest.mark.asyncio
    async def test_truncation_to_max_length(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """内容超过 max_length 时截断并加提示。"""
        from heagent.tools.builtins.web import web_fetch

        body = "A" * 500
        client = httpx.AsyncClient(transport=_mock_transport(body=body))
        monkeypatch.setattr("httpx.AsyncClient", lambda **kw: client)
        result = await web_fetch(url="https://example.com", max_length=200)
        assert result.startswith("A" * 200)
        assert "已截断" in result
        assert "500" in result

    @pytest.mark.asyncio
    async def test_short_content_no_truncation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """短内容不加截断标记。"""
        from heagent.tools.builtins.web import web_fetch

        body = "Hello"
        client = httpx.AsyncClient(transport=_mock_transport(body=body))
        monkeypatch.setattr("httpx.AsyncClient", lambda **kw: client)
        result = await web_fetch(url="https://example.com", max_length=50000)
        assert result == "Hello"

    @pytest.mark.asyncio
    async def test_max_length_clamped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """max_length 钳位：<100 → 100, >100000 → 100000。"""
        from heagent.tools.builtins.web import web_fetch

        body = "X" * 300
        client = httpx.AsyncClient(transport=_mock_transport(body=body))
        monkeypatch.setattr("httpx.AsyncClient", lambda **kw: client)
        result = await web_fetch(url="https://example.com", max_length=50)
        assert "已截断" in result
        assert result[:100] == "X" * 100

    @pytest.mark.asyncio
    async def test_content_type_no_charset_variant(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Content-Type 无 charset 变体也能正常抓取。"""
        from heagent.tools.builtins.web import web_fetch

        client = httpx.AsyncClient(transport=_mock_transport(body="plain text", content_type="text/plain"))
        monkeypatch.setattr("httpx.AsyncClient", lambda **kw: client)
        result = await web_fetch(url="https://example.com")
        assert result == "plain text"


# ── 工具 schema 注册 ─────────────────────────────────────────────────────────


class TestWebToolRegistration:
    def test_web_fetch_registered(self) -> None:
        """web_fetch 已在全局 registry 中注册。"""
        import heagent.tools.builtins.web  # noqa: F401
        from heagent.tools.registry import ToolRegistry

        reg = ToolRegistry.get()
        assert "web_fetch" in reg.list_names()

    def test_web_fetch_readonly(self) -> None:
        """web_fetch 标记 readOnlyHint=True。"""
        import heagent.tools.builtins.web  # noqa: F401
        from heagent.tools.registry import ToolRegistry

        reg = ToolRegistry.get()
        schema = reg.get_schema("web_fetch")
        assert schema is not None
        assert schema.annotations is not None
        assert schema.annotations.readOnlyHint is True
