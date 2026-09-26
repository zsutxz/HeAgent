"""``POST /api/dialogs/pick-directory`` 的端到端用例（Story 50-8 R2）。

两层：

- **端点层**（假 console）：状态码映射、回环门、方法限制、路由缺席、异常兜底；
- **真实装配**（真 ``HttpProjectConsole`` + 真 ASGI 应用 + 假子进程）：入口层到传输层的接线、
  单在途冲突、「拿到的路径什么也没改」——真对话框不开窗口（``_spawn`` 被替换）。

非回环来源一律用**显式 peer**：``httpx.ASGITransport`` 默认 peer 是空串，而
``is_loopback_host("")`` 判非回环（fail-safe）——所以「回环那一档」必须显式给回环 peer。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, ClassVar

import pytest

pytest.importorskip("starlette")

import httpx

from heagent.cli import dialogs as cli_dialogs
from heagent.cli.dialogs import MARKER
from heagent.network.http_console_protocol import ConsoleOperationError, DirectoryPickResponse
from heagent.network.http_protocol import HttpErrorCode
from heagent.network.http_server import HttpServerConfig, build_http_app

_VERSION = "test"


class FakeConsole:
    """只实现本 story 用到的协议方法（其余方法缺失 ⇒ 真调用了会立刻炸出来）。"""

    def __init__(self, result: DirectoryPickResponse | None = None, error: BaseException | None = None) -> None:
        self.result = result or DirectoryPickResponse(path=None, cancelled=True, backend="auto")
        self.error = error
        self.calls = 0

    async def pick_directory(self) -> DirectoryPickResponse:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


def _app(console: Any = None, *, host: str = "127.0.0.1") -> Any:
    return build_http_app(HttpServerConfig(port=0, host=host), version=_VERSION, console=console)


def _error(response: httpx.Response) -> str:
    return response.json()["error"]["code"]


def _client(
    app: Any, *, client: tuple[str, int] | None = None, base_url: str = "http://127.0.0.1"
) -> httpx.AsyncClient:
    """``base_url`` 必须与 ``config.host`` 同源，否则先撞同源防线（``origin_forbidden``）而不是回环门。"""
    transport = httpx.ASGITransport(app=app) if client is None else httpx.ASGITransport(app=app, client=client)
    return httpx.AsyncClient(transport=transport, base_url=base_url)


class TestEndpoint:
    async def test_selected_path_is_returned(self, tmp_path: Path) -> None:
        console = FakeConsole(DirectoryPickResponse(path=str(tmp_path), cancelled=False, backend="auto"))
        async with _client(_app(console)) as client:
            response = await client.post("/api/dialogs/pick-directory")
        assert response.status_code == 200
        assert response.json() == {"path": str(tmp_path), "cancelled": False, "backend": "auto"}
        assert console.calls == 1

    async def test_cancel_is_a_success_response_without_a_path(self) -> None:
        async with _client(_app(FakeConsole())) as client:
            response = await client.post("/api/dialogs/pick-directory")
        assert response.status_code == 200
        assert response.json() == {"path": None, "cancelled": True, "backend": "auto"}

    async def test_unavailable_backend_maps_to_503(self) -> None:
        console = FakeConsole(error=ConsoleOperationError(HttpErrorCode.DIALOG_UNAVAILABLE, "no backend"))
        async with _client(_app(console)) as client:
            response = await client.post("/api/dialogs/pick-directory")
        assert response.status_code == 503
        assert _error(response) == HttpErrorCode.DIALOG_UNAVAILABLE

    async def test_busy_maps_to_409(self) -> None:
        console = FakeConsole(error=ConsoleOperationError(HttpErrorCode.DIALOG_BUSY, "already open"))
        async with _client(_app(console)) as client:
            response = await client.post("/api/dialogs/pick-directory")
        assert response.status_code == 409
        assert _error(response) == HttpErrorCode.DIALOG_BUSY

    async def test_unexpected_failure_becomes_server_error(self) -> None:
        console = FakeConsole(error=RuntimeError("boom"))
        async with _client(_app(console)) as client:
            response = await client.post("/api/dialogs/pick-directory")
        assert response.status_code == 500
        assert _error(response) == HttpErrorCode.SERVER_ERROR

    async def test_non_loopback_client_is_rejected_without_touching_the_console(self) -> None:
        console = FakeConsole()
        app = _app(console, host="10.0.0.4")
        async with _client(app, client=("10.0.0.2", 9000), base_url="http://10.0.0.4") as client:
            response = await client.post("/api/dialogs/pick-directory")
        assert response.status_code == 403
        assert _error(response) == HttpErrorCode.LOOPBACK_REQUIRED
        assert console.calls == 0, "被拒的请求不得让服务端弹窗（无副作用）"

    async def test_get_is_not_allowed_so_a_link_cannot_open_a_dialog(self) -> None:
        console = FakeConsole()
        async with _client(_app(console)) as client:
            response = await client.get("/api/dialogs/pick-directory")
        assert response.status_code == 405
        assert console.calls == 0

    async def test_route_is_absent_without_an_injected_console(self) -> None:
        async with _client(_app()) as client:
            response = await client.post("/api/dialogs/pick-directory")
        assert response.status_code == 404


class TestRealAssembly:
    """真 console（入口层实现）+ 真路由 + 假子进程：验证接线与「什么都没改」。"""

    def _console(self, tmp_path: Path, *, backend: str = "auto") -> Any:
        from heagent.cli.http import HttpProjectConsole

        workspace = tmp_path / "ws"
        workspace.mkdir(parents=True, exist_ok=True)
        self.workspace = workspace
        return HttpProjectConsole(workspace, dialog_backend=backend)

    async def test_none_backend_is_reported_as_unavailable(self, tmp_path: Path) -> None:
        console = self._console(tmp_path, backend="none")
        async with _client(_app(console)) as client:
            response = await client.post("/api/dialogs/pick-directory")
        assert response.status_code == 503
        assert _error(response) == HttpErrorCode.DIALOG_UNAVAILABLE

    async def test_real_console_returns_the_picked_path_without_side_effects(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        picked = tmp_path / "picked-project"
        picked.mkdir()

        class _Proc:
            returncode = 0

            async def communicate(self) -> tuple[bytes, bytes]:
                return f"{MARKER}{picked}\n".encode(), b""

            def kill(self) -> None:  # pragma: no cover - 本用例不会超时
                raise AssertionError("不应终止")

        class _Spawn:
            calls: ClassVar[list[tuple[list[str], str]]] = []

            async def __call__(self, argv: list[str], script: str) -> Any:
                _Spawn.calls.append((argv, script))
                return _Proc()

        monkeypatch.setattr(cli_dialogs, "_spawn", _Spawn())
        console = self._console(tmp_path)
        async with _client(_app(console)) as client:
            response = await client.post("/api/dialogs/pick-directory")
        assert response.status_code == 200
        assert response.json() == {"path": str(picked), "cancelled": False, "backend": "auto"}
        # 「选择器不是权限」：注册表一字未改（登记仍要另发 POST /api/projects）。
        assert console.registry.list()[0].id == "default"
        assert len(console.registry.list()) == 1
        assert len(_Spawn.calls) == 1

    async def test_second_request_while_a_dialog_is_open_is_busy(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        released = asyncio.Event()

        class _Proc:
            returncode = 0

            async def communicate(self) -> tuple[bytes, bytes]:
                await released.wait()
                return b"", b""

            def kill(self) -> None:  # pragma: no cover - 收尾由取消触发
                released.set()

        class _Spawn:
            async def __call__(self, argv: list[str], script: str) -> Any:
                return _Proc()

        monkeypatch.setattr(cli_dialogs, "_spawn", _Spawn())
        console = self._console(tmp_path)
        app = _app(console)
        async with _client(app) as client:
            first = asyncio.create_task(client.post("/api/dialogs/pick-directory"))
            for _ in range(100):  # 等到真的在途（可观测条件，不用固定墙钟）
                await asyncio.sleep(0.01)
                if console._picker.in_flight:  # noqa: SLF001 - 测试直接观测在途标志
                    break
            assert console._picker.in_flight is True  # noqa: SLF001
            second = await client.post("/api/dialogs/pick-directory")
            assert second.status_code == 409
            assert _error(second) == HttpErrorCode.DIALOG_BUSY
            first.cancel()
            with pytest.raises(asyncio.CancelledError):
                await first

    async def test_real_console_loopback_gate_blocks_before_spawning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        spawn_calls: list[Any] = []

        class _Spawn:
            async def __call__(self, argv: list[str], script: str) -> Any:  # pragma: no cover
                spawn_calls.append(argv)
                raise AssertionError("非回环来源不得拉起任何进程")

        monkeypatch.setattr(cli_dialogs, "_spawn", _Spawn())
        console = self._console(tmp_path)
        app = _app(console, host="10.0.0.4")
        async with _client(app, client=("10.0.0.2", 9000), base_url="http://10.0.0.4") as client:
            response = await client.post("/api/dialogs/pick-directory")
        assert _error(response) == HttpErrorCode.LOOPBACK_REQUIRED
        assert spawn_calls == []
