"""Web fetch 工具测试 — 使用 httpx MockTransport 验证 URL 抓取行为。"""

from __future__ import annotations

import logging

import httpx
import pytest

from heagent.tools.builtins.web import _CONNECT_TIMEOUT, _is_allowed_content_type, web_fetch


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


# ── 测试基础设施 ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _stub_dns(monkeypatch: pytest.MonkeyPatch) -> None:
    """避免真实 DNS：默认所有主机解析为公网地址（example.com 真实公网 IP）。

    注意：不能用 TEST-NET（203.0.113.x / 192.0.2.x 等），Python ipaddress 将其判为
    is_private。SSRF 用例可在测试体内再次 monkeypatch ``_resolve_addresses`` 覆盖。
    """

    async def _public(host: str) -> list[str]:
        return ["93.184.216.34"]  # 真实公网地址（example.com），非 TEST-NET

    monkeypatch.setattr("heagent.tools.builtins.web._resolve_addresses", _public)


def _make_mock(
    monkeypatch: pytest.MonkeyPatch,
    *,
    handler=None,
    status: int = 200,
    body: str = "",
    content_type: str = "text/html; charset=utf-8",
    headers: dict | None = None,
) -> tuple[dict, list[str]]:
    """安装 MockTransport，返回 (捕获的 AsyncClient kwargs, 请求过的 URL 列表)。"""

    captured: dict = {}
    requests: list[str] = []

    def _default(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            status_code=status,
            content=body.encode("utf-8"),
            headers={"content-type": content_type, **(headers or {})},
        )

    real_handler = handler or _default

    def _wrapped(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        return real_handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(_wrapped))

    def _factory(**kw):
        captured.update(kw)
        return client

    monkeypatch.setattr("httpx.AsyncClient", _factory)
    return captured, requests


# ── 使用 httpx MockTransport 的集成测试 ──────────────────────────────────────


class TestWebFetch:
    @pytest.mark.asyncio
    async def test_fetch_html_page(self, monkeypatch: pytest.MonkeyPatch) -> None:
        body = "<html><body><h1>Hello</h1><p>World</p></body></html>"
        _make_mock(monkeypatch, body=body)
        result = await web_fetch(url="https://example.com")
        assert "Hello" in result
        assert "World" in result

    @pytest.mark.asyncio
    async def test_fetch_json_api(self, monkeypatch: pytest.MonkeyPatch) -> None:
        body = '{"status": "ok", "data": [1, 2, 3]}'
        _make_mock(monkeypatch, body=body, content_type="application/json")
        result = await web_fetch(url="https://api.example.com/data")
        assert "ok" in result
        assert "data" in result

    @pytest.mark.asyncio
    async def test_fetch_binary_content_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_mock(monkeypatch, body="x", content_type="application/pdf")
        with pytest.raises(RuntimeError, match="不支持的内容类型"):
            await web_fetch(url="https://example.com/doc.pdf")

    @pytest.mark.asyncio
    async def test_fetch_http_404(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_mock(monkeypatch, status=404, body="Not Found")
        with pytest.raises(RuntimeError, match="HTTP 404"):
            await web_fetch(url="https://example.com/missing")

    @pytest.mark.asyncio
    async def test_fetch_http_500(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_mock(monkeypatch, status=500, body="Error")
        with pytest.raises(RuntimeError, match="HTTP 500"):
            await web_fetch(url="https://example.com/error")

    @pytest.mark.asyncio
    async def test_3xx_without_location_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """3xx 但无有效 Location（如 304）应拒绝，不当作成功返空 body。

        注：本 httpx 版本所有 3xx 均 is_redirect=True，故 304 进重定向分支、缺 Location 即报错。
        """
        _make_mock(monkeypatch, status=304)
        with pytest.raises(RuntimeError, match="缺少有效 Location"):
            await web_fetch(url="https://example.com/not-modified")

    @pytest.mark.asyncio
    async def test_invalid_url_no_scheme(self) -> None:
        with pytest.raises(RuntimeError, match="必须以 http"):
            await web_fetch(url="example.com")

    @pytest.mark.asyncio
    async def test_invalid_url_ftp(self) -> None:
        with pytest.raises(RuntimeError, match="必须以 http"):
            await web_fetch(url="ftp://files.example.com")

    @pytest.mark.asyncio
    async def test_uppercase_scheme_accepted(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """大写 scheme（HTTPS://）应与 https:// 等价，不误拒。"""
        _make_mock(monkeypatch, body="ok")
        result = await web_fetch(url="HTTPS://example.com")
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_truncation_to_max_length(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_mock(monkeypatch, body="A" * 500)
        result = await web_fetch(url="https://example.com", max_length=200)
        assert result.startswith("A" * 200)
        assert "已截断" in result
        assert "500" in result

    @pytest.mark.asyncio
    async def test_short_content_no_truncation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_mock(monkeypatch, body="Hello")
        result = await web_fetch(url="https://example.com", max_length=50000)
        assert result == "Hello"

    @pytest.mark.asyncio
    async def test_max_length_clamped_low(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_mock(monkeypatch, body="X" * 300)
        result = await web_fetch(url="https://example.com", max_length=50)
        assert "已截断" in result
        assert result[:100] == "X" * 100

    @pytest.mark.asyncio
    async def test_max_length_clamped_high(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """max_length > 100000 钳位到 100000。"""
        _make_mock(monkeypatch, body="Y" * 150000)
        result = await web_fetch(url="https://example.com", max_length=200000)
        assert "已截断" in result
        assert "100000" in result
        assert len(result) < 150000

    @pytest.mark.asyncio
    async def test_content_type_no_charset_variant(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _make_mock(monkeypatch, body="plain text", content_type="text/plain")
        result = await web_fetch(url="https://example.com")
        assert result == "plain text"

    @pytest.mark.asyncio
    async def test_missing_content_type_allowed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """缺 Content-Type 的 2xx 文本响应应放行（不误拒）。"""

        def _no_ct(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code=200, content=b"no metadata")

        _make_mock(monkeypatch, handler=_no_ct)
        result = await web_fetch(url="https://example.com")
        assert result == "no metadata"

    @pytest.mark.asyncio
    async def test_client_kwargs_observed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """生产代码必须把 timeout(含 connect 拆分)/follow_redirects/trust_env 传给 AsyncClient。"""
        captured, _ = _make_mock(monkeypatch, body="ok")
        await web_fetch(url="https://example.com")
        assert captured.get("follow_redirects") is False
        assert captured.get("trust_env") is False
        timeout = captured.get("timeout")
        assert timeout is not None
        assert timeout.connect == _CONNECT_TIMEOUT

    @pytest.mark.asyncio
    async def test_request_url_observed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """mock 必须能观测到实际请求的 URL。"""
        _, requests = _make_mock(monkeypatch, body="ok")
        await web_fetch(url="https://example.com/path")
        assert any("example.com/path" in u for u in requests)

    @pytest.mark.asyncio
    async def test_byte_cap_truncation(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """响应体超 2MB 硬上限：流式截断 + 警告。"""
        _make_mock(monkeypatch, body="A" * (3 * 1024 * 1024))
        with caplog.at_level(logging.WARNING, logger="heagent.tools.builtins.web"):
            result = await web_fetch(url="https://example.com", max_length=100000)
        assert "内容过大" in caplog.text
        assert len(result) < 3 * 1024 * 1024

    @pytest.mark.asyncio
    async def test_timeout_raises_runtime_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _timeout(request: httpx.Request) -> httpx.Response:
            raise httpx.ReadTimeout("simulated")

        _make_mock(monkeypatch, handler=_timeout)
        with pytest.raises(RuntimeError, match="请求超时"):
            await web_fetch(url="https://example.com")

    @pytest.mark.asyncio
    async def test_request_error_raises_runtime_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _conn_err(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("simulated")

        _make_mock(monkeypatch, handler=_conn_err)
        with pytest.raises(RuntimeError, match="请求失败"):
            await web_fetch(url="https://example.com")

    @pytest.mark.asyncio
    async def test_non_utf8_charset_decoded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _latin1(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=200,
                content=b"\xe9",  # 'é' in iso-8859-1
                headers={"content-type": "text/html; charset=iso-8859-1"},
            )

        _make_mock(monkeypatch, handler=_latin1)
        result = await web_fetch(url="https://example.com")
        assert "é" in result

    @pytest.mark.asyncio
    async def test_bogus_charset_fallback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _bogus(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=200,
                content=b"hello",
                headers={"content-type": "text/html; charset=totally-bogus"},
            )

        _make_mock(monkeypatch, handler=_bogus)
        result = await web_fetch(url="https://example.com")
        assert "hello" in result

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "blocked_ip",
        ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1", "fe80::1"],
    )
    async def test_ssrf_private_ip_blocked(
        self, monkeypatch: pytest.MonkeyPatch, blocked_ip: str
    ) -> None:
        async def _blocked(host: str) -> list[str]:
            return [blocked_ip]

        monkeypatch.setattr("heagent.tools.builtins.web._resolve_addresses", _blocked)
        with pytest.raises(RuntimeError, match="非公网"):
            await web_fetch(url="https://internal.example.com")

    @pytest.mark.asyncio
    async def test_ssrf_userinfo_rejected(self) -> None:
        with pytest.raises(RuntimeError, match="userinfo"):
            await web_fetch(url="https://user:pass@example.com/")

    @pytest.mark.asyncio
    async def test_redirect_followed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _redirector(request: httpx.Request) -> httpx.Response:
            if "start" in str(request.url):
                return httpx.Response(
                    status_code=302, headers={"location": "https://target.example.com/final"}
                )
            return httpx.Response(
                status_code=200, content=b"followed", headers={"content-type": "text/plain"}
            )

        _, requests = _make_mock(monkeypatch, handler=_redirector)
        result = await web_fetch(url="https://example.com/start")
        assert result == "followed"
        assert any("example.com/start" in u for u in requests)
        assert any("target.example.com/final" in u for u in requests)

    @pytest.mark.asyncio
    async def test_redirect_to_private_blocked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """重定向目标解析为私网地址时必须拒绝（验证逐跳校验真实运行）。"""

        async def _mixed(host: str) -> list[str]:
            return ["127.0.0.1"] if "private" in host else ["93.184.216.34"]

        monkeypatch.setattr("heagent.tools.builtins.web._resolve_addresses", _mixed)

        def _redirector(request: httpx.Request) -> httpx.Response:
            if "start" in str(request.url):
                return httpx.Response(
                    status_code=302,
                    headers={"location": "https://private-target.example.com/x"},
                )
            return httpx.Response(
                status_code=200, content=b"x", headers={"content-type": "text/plain"}
            )

        _make_mock(monkeypatch, handler=_redirector)
        with pytest.raises(RuntimeError, match="非公网"):
            await web_fetch(url="https://example.com/start")

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("location", "expected_fragment"),
        [("/other", "example.com/other"), ("//otherhost.example.com/x", "otherhost.example.com/x")],
    )
    async def test_redirect_relative_location(
        self,
        monkeypatch: pytest.MonkeyPatch,
        location: str,
        expected_fragment: str,
    ) -> None:
        """相对/绝对路径/scheme-relative Location 经 urljoin 后仍逐跳校验并抓取。"""

        def _redirector(request: httpx.Request) -> httpx.Response:
            if "start" in str(request.url):
                return httpx.Response(status_code=302, headers={"location": location})
            return httpx.Response(
                status_code=200, content=b"ok", headers={"content-type": "text/plain"}
            )

        _, requests = _make_mock(monkeypatch, handler=_redirector)
        result = await web_fetch(url="https://example.com/start")
        assert result == "ok"
        assert any(expected_fragment in u for u in requests)

    @pytest.mark.asyncio
    async def test_https_to_http_downgrade_blocked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _downgrade(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status_code=302, headers={"location": "http://insecure.example.com/"}
            )

        _make_mock(monkeypatch, handler=_downgrade)
        with pytest.raises(RuntimeError, match="降级"):
            await web_fetch(url="https://example.com/start")

    @pytest.mark.asyncio
    async def test_redirect_loop_limit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _loop(request: httpx.Request) -> httpx.Response:
            return httpx.Response(status_code=302, headers={"location": str(request.url) + "x"})

        _make_mock(monkeypatch, handler=_loop)
        with pytest.raises(RuntimeError, match="重定向次数超限"):
            await web_fetch(url="https://example.com/start")


# ── 工具 schema 注册 ─────────────────────────────────────────────────────────


class TestWebToolRegistration:
    def test_web_fetch_registered(self) -> None:
        """web_fetch 已注册且 schema 形态正确（绑定本工具，非恒真）。"""
        import heagent.tools.builtins.web  # noqa: F401
        from heagent.tools.registry import ToolRegistry

        schema = ToolRegistry.get().get_schema("web_fetch")
        assert schema is not None
        assert schema.name == "web_fetch"
        props = schema.parameters["properties"]
        assert "url" in props
        assert "max_length" in props

    def test_web_fetch_readonly(self) -> None:
        """web_fetch 标记 readOnlyHint=True（注解为信息性，见 web.py 模块文档）。"""
        import heagent.tools.builtins.web  # noqa: F401
        from heagent.tools.registry import ToolRegistry

        schema = ToolRegistry.get().get_schema("web_fetch")
        assert schema is not None
        assert schema.annotations is not None
        assert schema.annotations.readOnlyHint is True
