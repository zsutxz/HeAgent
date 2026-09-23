"""HTTP 传输层测试（Epic 49 Story 49-1）。

覆盖两层：

- **ASGI 层**（``httpx.ASGITransport``，不起真实 socket）：健康检查、包内静态页、安全响应头、
  稳定错误信封、路径穿越拒绝——快且跨平台稳定；
- **listener 层**（真实 ``127.0.0.1`` 绑定，``port=0`` 随机端口）：绑定、就绪探测、幂等、
  绑定失败显式报错、关闭后服务循环退出。

Starlette 是可选依赖（``heagent[http]``）：测试用 :func:`pytest.importorskip` 守卫，缺依赖时
整个模块跳过（CI 的 test / coverage job 已装该 extra，见 ``.github/workflows/ci.yml``）。
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import pytest

pytest.importorskip("starlette")

import httpx
from pydantic import ValidationError

from heagent.network import http_server
from heagent.network.http_protocol import HttpErrorCode, RunOutcome
from heagent.network.http_server import (
    HttpRunService,
    HttpServer,
    HttpServerConfig,
    HttpStartupError,
    build_http_app,
    read_web_asset,
)

_VERSION = "9.9.9"
# 页面里所有 src/href 引用（用于断言「不加载第三方资源」）。
_PAGE_REF_RE = re.compile(r'(?:src|href)\s*=\s*"([^"]+)"')


def _config(**overrides: Any) -> HttpServerConfig:
    """测试配置：默认 ``port=0``（随机端口），可覆盖任意字段（含 ``port``）。"""
    return HttpServerConfig(**{"port": 0, **overrides})


@pytest.fixture
async def client() -> Any:
    """直接打 ASGI 应用的客户端（不占端口、不起服务循环）。"""
    transport = httpx.ASGITransport(app=build_http_app(_config(), version=_VERSION))
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8766") as value:
        yield value


def _error_code(response: httpx.Response) -> str:
    return str(response.json()["error"]["code"])


class TestHealth:
    """``GET /api/health`` 的稳定契约。"""

    async def test_health_reports_stable_fields(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/api/health")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("application/json")
        payload = response.json()
        assert set(payload) == {"status", "service", "version", "schema_version"}
        assert payload["status"] == "ok"
        assert payload["service"] == "heagent-http"
        assert payload["version"] == _VERSION
        assert payload["schema_version"] == "1"

    async def test_health_does_not_leak_internals(self, client: httpx.AsyncClient) -> None:
        """健康响应不得带绝对路径、密钥样式串或 traceback（验收项）。"""
        body = (await client.get("/api/health")).text

        assert "heagent/" not in body
        assert ":\\" not in body and "\\\\" not in body
        assert "Traceback" not in body
        assert "sk-" not in body


class TestStaticPage:
    """根路径与包内静态资源。"""

    async def test_root_serves_packaged_page(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/")

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        assert "<!DOCTYPE html>" in response.text
        assert "<title>HeAgent</title>" in response.text

    async def test_page_loads_no_third_party_resources(self, client: httpx.AsyncClient) -> None:
        """页面所有 src/href 都是同源绝对路径，且 HTML 里没有任何外链域名。"""
        body = (await client.get("/")).text

        refs = _PAGE_REF_RE.findall(body)
        assert refs, "页面应当引用本地的样式与脚本"
        assert all(ref.startswith("/") for ref in refs), refs
        assert "http://" not in body
        assert "https://" not in body

    async def test_assets_have_explicit_content_types(self, client: httpx.AsyncClient) -> None:
        js = await client.get("/app.js")
        css = await client.get("/styles.css")

        assert js.status_code == 200
        assert js.headers["content-type"].startswith("text/javascript")
        assert css.status_code == 200
        assert css.headers["content-type"].startswith("text/css")

    async def test_page_renders_text_without_html_injection(self, client: httpx.AsyncClient) -> None:
        """页面脚本必须用 textContent/createTextNode 渲染不可信内容，绝不写 innerHTML。"""
        script = (await client.get("/app.js")).text

        assert "textContent" in script
        assert "createTextNode" in script
        # 只查「属性访问」形态：注释里出现该词是说明文字，不构成 HTML 注入面。
        assert ".innerHTML" not in script

    async def test_unknown_asset_is_stable_404(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/nope.js")

        assert response.status_code == 404
        assert _error_code(response) == HttpErrorCode.NOT_FOUND

    @pytest.mark.parametrize(
        "path",
        ["/..%2fpyproject.toml", "/%2e%2e%2f%2e%2e%2fetc%2fpasswd", "/nested/app.js", "/.env"],
    )
    async def test_traversal_style_paths_are_rejected(self, client: httpx.AsyncClient, path: str) -> None:
        """白名单之外的一律 404：编码穿越、多段路径、隐藏文件都不例外。"""
        response = await client.get(path)

        assert response.status_code == 404
        assert _error_code(response) == HttpErrorCode.NOT_FOUND


class TestSecurityHeaders:
    """安全响应头（AD-6）对每一个响应都生效。"""

    @pytest.mark.parametrize("path", ["/api/health", "/", "/app.js", "/nope.js"])
    async def test_every_response_carries_security_headers(self, client: httpx.AsyncClient, path: str) -> None:
        response = await client.get(path)

        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["x-frame-options"] == "DENY"
        assert response.headers["referrer-policy"] == "no-referrer"
        csp = response.headers["content-security-policy"]
        assert "default-src 'none'" in csp
        assert "script-src 'self'" in csp
        assert "unsafe-inline" not in csp
        assert "frame-ancestors 'none'" in csp

    async def test_mutating_methods_are_allowed_nowhere_yet(self, client: httpx.AsyncClient) -> None:
        """Story 49-1 只有读取端点：写方法收稳定 405，不 500。"""
        response = await client.post("/api/health", json={"prompt": "hi"})

        assert response.status_code == 405
        assert _error_code(response) == HttpErrorCode.METHOD_NOT_ALLOWED


class TestErrorEnvelope:
    """错误信封的结构与脱敏。"""

    async def test_unknown_endpoint_uses_error_envelope(self, client: httpx.AsyncClient) -> None:
        response = await client.get("/api/nope")

        assert response.status_code == 404
        payload = response.json()
        assert set(payload) == {"error"}
        assert set(payload["error"]) == {"code", "message"}
        assert payload["error"]["code"] == HttpErrorCode.NOT_FOUND
        assert payload["error"]["message"]
        assert "Traceback" not in response.text


class TestConfig:
    """配置默认值与校验（AD-11 的固定预算）。"""

    def test_defaults_match_documented_budget(self) -> None:
        config = HttpServerConfig()

        assert config.host == "127.0.0.1"
        assert config.port == 8766
        assert config.max_connections == 16
        assert config.max_inflight_runs == 1
        assert config.max_request_bytes == 65_536
        assert config.event_buffer_size == 512
        assert config.run_history_size == 64
        assert config.request_timeout == 300.0
        assert config.shutdown_timeout == 5.0

    @pytest.mark.parametrize(
        "overrides",
        [
            {"host": ""},
            {"port": -1},
            {"port": 70_000},
            {"max_connections": 0},
            {"max_inflight_runs": 0},
            {"max_request_bytes": 0},
            {"event_buffer_size": 0},
            {"run_history_size": 0},
            {"request_timeout": 0},
            {"request_timeout": float("inf")},
            {"request_timeout": float("nan")},
            {"shutdown_timeout": -1.0},
            {"shutdown_timeout": float("inf")},
        ],
    )
    def test_invalid_values_are_rejected(self, overrides: dict[str, Any]) -> None:
        """非法值必须显性失败，不能静默变成「无限制」。"""
        with pytest.raises(ValidationError):
            HttpServerConfig(**overrides)


class TestLifecycle:
    """真实 listener 的绑定、就绪、幂等与失败路径。"""

    async def test_start_binds_and_serves_health(self) -> None:
        server = HttpServer(_config(), version=_VERSION)
        await server.start()
        try:
            assert server.port > 0
            assert server.address == f"127.0.0.1:{server.port}"
            async with httpx.AsyncClient() as client:
                response = await client.get(f"http://127.0.0.1:{server.port}/api/health")
            assert response.status_code == 200
            assert response.json()["version"] == _VERSION
            assert response.headers["x-content-type-options"] == "nosniff"
        finally:
            await server.close()

    async def test_start_and_close_are_idempotent(self) -> None:
        server = HttpServer(_config(), version=_VERSION)
        await server.start()
        port = server.port
        await server.start()  # 重复 start 不重新绑定、不改端口
        assert server.port == port
        await server.close()
        await server.close()  # 幂等：第二次是 no-op

    async def test_bind_failure_raises_startup_error(self) -> None:
        """端口被占用必须显式失败（uvicorn 在此路径上是 sys.exit，需被转成可诊断错误）。"""
        first = HttpServer(_config(), version=_VERSION)
        await first.start()
        try:
            second = HttpServer(_config(port=first.port), version=_VERSION)
            with pytest.raises(HttpStartupError) as excinfo:
                await second.start()
            assert "could not bind" in str(excinfo.value)
        finally:
            await first.close()

    async def test_start_rolls_back_when_health_is_not_servable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """就绪门禁：``/api/health`` 不可服务时 start 必须失败且回滚 listener。"""
        server = HttpServer(_config(), version=_VERSION)

        async def _unhealthy() -> bool:
            return False

        monkeypatch.setattr(server, "_probe_health", _unhealthy)
        with pytest.raises(HttpStartupError) as excinfo:
            await server.start()
        assert "not servable" in str(excinfo.value)

        # 回滚后同一实例可以重新启动（说明失败路径没有留下悬挂 listener）。
        monkeypatch.undo()
        await server.start()
        await server.close()

    async def test_serve_forever_returns_after_close(self) -> None:
        server = HttpServer(_config(), version=_VERSION)
        await server.start()
        task = asyncio.create_task(server.serve_forever())
        try:
            await asyncio.sleep(0.05)
            async with httpx.AsyncClient() as client:
                response = await client.get(f"http://127.0.0.1:{server.port}/api/health")
            assert response.status_code == 200
        finally:
            await server.close()
        await asyncio.wait_for(task, timeout=5)
        assert not task.cancelled()
        assert task.exception() is None

    async def test_close_stops_accepting_connections(self) -> None:
        server = HttpServer(_config(), version=_VERSION)
        await server.start()
        port = server.port
        await server.close()

        with pytest.raises((httpx.ConnectError, httpx.ConnectTimeout)):
            async with httpx.AsyncClient(timeout=2.0) as client:
                await client.get(f"http://127.0.0.1:{port}/api/health")

    async def test_non_loopback_binding_logs_exposure_warning(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        """非回环绑定的告警来自 ``network.exposure``（此处打桩文案，避免真绑非回环地址）。"""
        monkeypatch.setattr(http_server, "exposure_warning", lambda host: "exposure-under-test")
        server = HttpServer(_config(), version=_VERSION)
        with caplog.at_level(logging.INFO, logger="heagent.network.http_server"):
            await server.start()
        try:
            assert "http event=exposed" in caplog.text
            assert "exposure-under-test" in caplog.text
        finally:
            await server.close()

    async def test_loopback_binding_has_no_exposure_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        server = HttpServer(_config(), version=_VERSION)
        with caplog.at_level(logging.INFO, logger="heagent.network.http_server"):
            await server.start()
        try:
            assert "http event=started" in caplog.text
            assert "http event=exposed" not in caplog.text
        finally:
            await server.close()


class TestPackagedAssets:
    """包内静态资源（源码运行与 wheel 安装都走同一个查找方式）。"""

    def test_all_whitelisted_assets_exist_and_are_non_empty(self) -> None:
        for name in sorted(http_server._WEB_ASSETS):
            assert read_web_asset(name), name

    def test_unknown_asset_name_raises(self) -> None:
        with pytest.raises(KeyError):
            read_web_asset("secrets.txt")

    def test_asset_whitelist_covers_every_shipped_file(self) -> None:
        """包目录里不能有「没登记进白名单」的散落文件：那样它们既不会被发布，也不会被测试。"""
        from importlib import resources

        shipped = {
            entry.name
            for entry in resources.files("heagent.web").iterdir()
            if entry.is_file() and entry.name != "__init__.py"
        }

        assert shipped == set(http_server._WEB_ASSETS)


def _ok_executor():
    """立即返回的假 executor（listener 层只需要「能跑完的入口」）。"""

    async def run(prompt: str, publisher: object) -> RunOutcome:
        return RunOutcome(answer="ok")

    return run


def _stubborn_executor(delay: float):
    """吞掉取消的假 executor：模拟忽略取消的长工具，让关闭真的需要等待。"""

    async def run(prompt: str, publisher: object) -> RunOutcome:
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            await asyncio.sleep(delay)
        return RunOutcome(answer="late")

    return run


def _app_client(app: Any) -> httpx.AsyncClient:
    """直接打 ASGI 应用的客户端；``raise_app_exceptions=False`` 让我们断言应用给出的 500 响应。"""
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    return httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:8766")


class TestFallbackErrorEnvelope:
    """**唯一**挡住 traceback 外泄的通道：未预期异常与资源读失败也必须走统一信封（AD-8）。"""

    async def test_unexpected_route_exception_returns_a_sanitized_500(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """未预期异常 ⇒ 固定文案 + 稳定错误码；异常细节只进服务端日志。"""

        def _boom(_name: str) -> bytes:
            raise RuntimeError("disk exploded at C:\\secret\\page.html")

        monkeypatch.setattr(http_server, "read_web_asset", _boom)
        async with _app_client(build_http_app(_config(), version=_VERSION)) as client:
            response = await client.get("/")

        assert response.status_code == 500
        assert response.json() == {"error": {"code": "server_error", "message": "internal server error"}}
        assert "disk exploded" not in response.text
        assert "secret" not in response.text
        # 失败响应同样带安全头（安全头中间件在最外层）。
        assert response.headers["x-content-type-options"] == "nosniff"

    async def test_unavailable_asset_returns_a_stable_500(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """包内资源缺失（例如 wheel 漏打）⇒ 稳定 500，不吐 traceback、不暴露路径。"""

        def _missing(_name: str) -> bytes:
            raise OSError("missing packaged asset")

        monkeypatch.setattr(http_server, "read_web_asset", _missing)
        async with _app_client(build_http_app(_config(), version=_VERSION)) as client:
            response = await client.get("/app.js")

        assert response.status_code == 500
        assert response.json()["error"]["code"] == "server_error"
        assert "Traceback" not in response.text


class TestBindingAndConcurrencyBudget:
    """绑定地址与连接额度的边界（评审修复回归）。"""

    async def test_wildcard_host_binds_and_serves_over_loopback(self) -> None:
        """``HTTP_HOST=0.0.0.0`` 必须真能起来。

        就绪探测走回环地址（连 ``0.0.0.0`` 在多数平台是未定义行为），因此同源防线必须接受等价
        本机写法——否则探测被自己的 Host 校验拒掉（403），入口永远起不来。
        """
        server = HttpServer(_config(host="0.0.0.0"), version=_VERSION)
        await server.start()
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"http://127.0.0.1:{server.port}/api/health")
            assert response.status_code == 200
        finally:
            await server.close()

    async def test_max_connections_one_still_starts(self) -> None:
        """``HTTP_MAX_CONNECTIONS=1`` 是合法配置：就绪探测不得把自己挡在额度之外。"""
        server = HttpServer(_config(max_connections=1), version=_VERSION)
        await server.start()
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"http://127.0.0.1:{server.port}/api/health")
            assert response.status_code == 200
        finally:
            await server.close()

    def test_wildcard_binding_only_adds_loopback_aliases(self) -> None:
        """通配绑定额外接受等价本机写法；普通非回环 host 不额外放宽（反 DNS-rebinding）。"""
        assert http_server._allowed_hosts(_config(host="0.0.0.0")) >= {
            "0.0.0.0",
            "127.0.0.1",
            "localhost",
            "[::1]",
        }
        assert http_server._allowed_hosts(_config(host="::")) >= {"::", "[::1]"}
        assert http_server._allowed_hosts(_config(host="192.168.1.5")) == frozenset({"192.168.1.5"})

    @pytest.mark.parametrize(("host", "expected"), [("0.0.0.0", "127.0.0.1"), ("::", "::1")])
    def test_wildcards_are_probed_over_loopback(self, host: str, expected: str) -> None:
        assert http_server._probe_host(host) == expected


class TestCloseAndRestartSemantics:
    """``close()`` 的幂等语义与 ``close()`` → ``start()`` 的重启语义。"""

    async def test_concurrent_close_waits_for_the_same_shutdown(self) -> None:
        """并发 ``close()`` 必须等到**同一次**收尾完成，不能提前返回假的「已关闭」。"""
        config = _config(shutdown_timeout=2.0)
        server = HttpServer(
            config,
            version=_VERSION,
            run_service=HttpRunService(config, _stubborn_executor(0.6)),
        )
        await server.start()
        port = server.port
        try:
            async with httpx.AsyncClient() as client:
                created = await client.post(f"http://127.0.0.1:{port}/api/runs", json={"prompt": "stuck"})
                assert created.status_code == 201

            first = asyncio.create_task(server.close())
            await asyncio.sleep(0.2)  # 让第一次 close 进入「等在途运行进入终态」
            second = asyncio.create_task(server.close())
            await asyncio.sleep(0.2)

            assert not first.done()
            assert not second.done(), "后到的 close 不得在收尾完成前返回"
            await asyncio.wait_for(asyncio.gather(first, second), timeout=15)
        finally:
            await server.close()

        with pytest.raises((httpx.ConnectError, httpx.ConnectTimeout)):
            async with httpx.AsyncClient(timeout=2.0) as client:
                await client.get(f"http://127.0.0.1:{port}/api/health")

    async def test_restart_after_close_accepts_runs_again(self) -> None:
        """``close()`` → ``start()`` 之后运行入口必须被重新武装（否则健康检查 200 而提交恒 409）。"""
        config = _config()
        server = HttpServer(config, version=_VERSION, run_service=HttpRunService(config, _ok_executor()))
        await server.start()
        await server.close()
        await server.start()
        try:
            async with httpx.AsyncClient() as client:
                health = await client.get(f"http://127.0.0.1:{server.port}/api/health")
                created = await client.post(f"http://127.0.0.1:{server.port}/api/runs", json={"prompt": "hi"})
            assert health.status_code == 200
            assert created.status_code == 201, created.text
        finally:
            await server.close()
