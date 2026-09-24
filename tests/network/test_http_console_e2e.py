"""Story 50-7：网页控制台的端到端收口验收（brief §9 逐条的可执行证据）。

本文件与三个协议层测试的分工：``test_http_console_{projects,sessions,config}.py`` 用**假 console**
钉传输契约；这里一律走**真装配** —— 真 ``HttpProjectConsole`` + 真项目注册表 + 真 ``SessionStore`` +
真写通道 + 真 listener（随机端口），只在 LLM 侧用 stub provider。理由是本 story 要证的是「跨项目的
归属正确」「凭证不外泄」这类**整体性质**，替身会把要证的东西证掉。

覆盖（→ brief §9 的验收标准编号）：
- T1 声明口径一致（§9.9「入口限制在 UI 与文档中可见」）；
- T2 非回环来源在**登记 / 移除**上零副作用（§9.5「非允许来源显式失败」）；
- T3 凭证零回传**五面**扫：配置响应 / 错误信封 / SSE 帧 / 日志 / 审计（§9.7）；
- T4 跨项目不串味：会话归属 + **真实工具路径**（A 的 loop 读不到 B 的文件）（§9.1；R2）；
- T5 闸门关闭时配置面只读、Epic 49 运行链路不受影响、每项目各用自己的状态根（§9.2/§9.9）。
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("starlette")

import httpx

from heagent.cli_http import HttpAgentHandler, HttpProjectConsole
from heagent.config import get_settings, reset_settings
from heagent.network.exposure import exposure_warning
from heagent.network.http_protocol import HttpErrorCode
from heagent.network.http_server import HttpRunService, HttpServer, HttpServerConfig, build_http_app, read_web_asset
from heagent.providers.base import ProviderMetadata
from heagent.types import Message, ProviderResponse, TokenUsage, ToolCall

# 假密钥标记：短密钥与多密钥各一份（§9.7 要求覆盖这两种形态）；MARKER 放在普通键的值里。
# noqa: S105 —— 这两个常量**故意**长得像密钥：它们的用途就是证明「任何一面都回传不出它们」。
SHORT_SECRET = "sk-SHRT1234"  # noqa: S105
POOL_SECRET = "sk-POOLAAAA,sk-POOLBBBB"  # noqa: S105
MARKER = "MARKER-9f3c1a"

NON_LOOPBACK_PEER = ("10.0.0.2", 9000)
NON_LOOPBACK_HOST = "10.0.0.4"


def _answer(text: str) -> ProviderResponse:
    return ProviderResponse(
        content=text,
        usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        model="stub-1",
        finish_reason="stop",
    )


def _tool_request(name: str, arguments: dict[str, Any]) -> ProviderResponse:
    return ProviderResponse(
        content="",
        tool_calls=[ToolCall(id="call-1", name=name, arguments=arguments)],
        usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
        model="stub-1",
        finish_reason="tool_calls",
    )


class _ScriptedProvider:
    """按脚本应答（末项重复）：与 ``tests/test_http_agent_api.py`` 同形。"""

    def __init__(self, script: list[Any]) -> None:
        self._script = script
        self.calls = 0

    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        item = self._script[min(self.calls, len(self._script) - 1)]
        self.calls += 1
        return item

    async def stream(self, messages: list[Message], *, tools: list[object] | None = None) -> Any:
        yield await self.send(messages, tools=tools)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub-1")


@pytest.fixture(autouse=True)
def _isolate(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """在 tmp 里跑：注册表 / 会话 / 引擎产物都落在临时目录（不污染仓库），并重置 Settings 单例。"""
    monkeypatch.chdir(tmp_path)
    reset_settings()
    yield
    reset_settings()


def _project(root: Path) -> Path:
    """建一个「项目根」：目录 + `.env`（凭证标记）+ 自己的会话目录。"""
    root.mkdir(parents=True, exist_ok=True)
    (root / ".env").write_bytes(
        b"# project env\r\n"
        + f"KIMI_API_KEY={SHORT_SECRET}\r\n".encode()
        + f"OPENAI_API_KEYS={POOL_SECRET}\r\n".encode()
        + f"DEFAULT_MODEL={MARKER}-model\r\n".encode()
        + b"MAX_ITERATIONS=25\r\n"
    )
    (root / ".heagent" / "sessions").mkdir(parents=True, exist_ok=True)
    return root


def _workspace(tmp_path: Path) -> Path:
    """服务启动工作区（默认项目；项目注册表落在这里的 `.heagent/console/`）。"""
    workspace = tmp_path / "ws"
    workspace.mkdir()
    return workspace


@contextlib.asynccontextmanager
async def _console_server(
    workspace: Path, handler: HttpAgentHandler, *, write_enabled: bool = False, **config_overrides: Any
) -> AsyncIterator[tuple[HttpProjectConsole, str]]:
    """真 listener（随机端口）+ 真 console。**先建 run service 再建 console**：运行入口是构造期注入的。

    退出时关闭并等待 serve 循环收敛（与 ``tests/test_http_agent_api.py::_served`` 同形）。
    """
    config = HttpServerConfig(**{"port": 0, **config_overrides})
    service = HttpRunService(config, handler)
    console = HttpProjectConsole(
        workspace,
        runs=service,
        handler_factory=handler.for_workspace,
        write_enabled=write_enabled,
        global_env_file=None,
    )
    server = HttpServer(config, version="9.9.9", run_service=service, console=console)
    await server.start()
    task = asyncio.create_task(server.serve_forever())
    try:
        yield console, f"http://127.0.0.1:{server.port}"
    finally:
        await server.close()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(task, timeout=5)


def _app(console: HttpProjectConsole, *, host: str = "127.0.0.1") -> Any:
    return build_http_app(HttpServerConfig(port=0, host=host), version="9.9.9", console=console)


def _asio_client(console: HttpProjectConsole, *, peer: tuple[str, int] | None = None) -> httpx.AsyncClient:
    """ASGI 直连（不起端口）：``peer`` 用来伪造**非回环来源**（判定单点看 ``request.client.host``）。

    ⚠ ``client=None`` 会把 peer 变成空串 ⇒ :func:`is_loopback_host` 判非回环（fail-safe），所以
    回环那一档必须**显式**给一个回环 peer，不能靠 httpx 的默认值。
    """
    transport = httpx.ASGITransport(
        app=_app(console, host=NON_LOOPBACK_HOST if peer else "127.0.0.1"),
        client=peer or ("127.0.0.1", 12345),
    )
    base = f"http://{NON_LOOPBACK_HOST}" if peer else "http://127.0.0.1"
    return httpx.AsyncClient(transport=transport, base_url=base)


def _frames(body: str) -> list[tuple[str, dict[str, Any]]]:
    frames: list[tuple[str, dict[str, Any]]] = []
    for block in body.split("\n\n"):
        if not block.strip():
            continue
        fields = {key: value for line in block.splitlines() if ": " in line for key, value in [line.split(": ", 1)]}
        frames.append((fields["event"], json.loads(fields["data"])))
    return frames


# ── T1：声明口径一致 ───────────────────────────────────────────────


def test_exposure_warning_and_the_ui_notice_state_the_same_three_facts() -> None:
    """T1：非回环告警与 UI 常驻声明必须说同一件事 —— 「无认证 / 无 TLS / 非安全边界」。

    两处口径一致才是收口：只在一处声明，另一处就会被读成「这里更安全」。同时断言两处都**不**把回环
    当信任依据（告警原文含「loopback client is not trusted either」；UI 声明要求 OS 级沙箱兜底）。
    """
    warning = exposure_warning(NON_LOOPBACK_HOST)
    assert warning is not None
    for fact in ("no authentication", "no TLS", "not a production security boundary", "not trusted"):
        assert fact in warning, fact
    assert exposure_warning("127.0.0.1") is None  # 回环绑定不告警

    html = read_web_asset("index.html").decode("utf-8")
    for fact in ("无认证", "无 TLS", "非安全边界", "沙箱"):
        assert fact in html, fact


# ── T2：非回环来源零副作用 ────────────────────────────────────────


async def test_non_loopback_clients_cannot_register_or_remove_projects(tmp_path: Path) -> None:
    """T2：非回环来源在**登记 / 移除**上都收 ``loopback_required``，且注册表**逐字节不变**。

    写通道那条已有专门用例；这里补注册表的两个写操作，并把「无副作用」断言到**文件字节**，
    而不是「接口没返回成功」。

    **范围说明（如实）**：story 的 T2 点名的是「写通道 / 项目登记 / 项目移除」三处，本用例只测这三处。
    同一路径上的 **重命名**（`PATCH /api/projects/{id}`）与四个**会话**写操作、项目内运行入口**当前没有**
    回环门 —— 那是台账里已登记的「非回环运行姿态（intent_gap，**blocked 待人裁决**）」条目，本 story 不
    擅自扩大裁定范围，也不在此把现状钉成断言（真要被绕过，影响面已在台账与 frame.md 五写明）。
    """
    workspace = _workspace(tmp_path)
    target = _project(tmp_path / "target")
    console = HttpProjectConsole(workspace, global_env_file=None)

    async with _asio_client(console) as client:
        created = await client.post("/api/projects", json={"path": str(target), "name": "T"})
    assert created.status_code == 201, created.text
    project_id = created.json()["id"]
    registry = workspace / ".heagent" / "console" / "projects.json"
    before = registry.read_bytes()

    async with _asio_client(console, peer=NON_LOOPBACK_PEER) as client:
        registered = await client.post("/api/projects", json={"path": str(tmp_path / "other"), "name": "X"})
        removed = await client.delete(f"/api/projects/{project_id}?confirm=true")

    responses = [registered, removed]
    assert [response.status_code for response in responses] == [403, 403]
    assert {response.json()["error"]["code"] for response in responses} == {HttpErrorCode.LOOPBACK_REQUIRED}
    assert registry.read_bytes() == before  # 注册表一字未动
    assert not (tmp_path / "other").exists()  # 也不会有「顺手建目录」的副作用


# ── T3：凭证零回传（五面） ────────────────────────────────────────


async def test_no_credential_leaks_across_five_faces(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """T3：配置响应 / 错误信封 / SSE 帧 / 日志 / 审计 —— 五面都不得出现密钥明文。

    覆盖短密钥与多密钥；并断言「值进过写通道的键」在审计里只留哈希（写一个值里带标记的普通键，
    审计文件仍找不到该标记 —— 审计存的是哈希与长度，不是值）。
    """
    caplog.set_level(logging.DEBUG)
    root = _project(tmp_path / "proj")
    provider = _ScriptedProvider([_answer("hello")])
    handler = HttpAgentHandler(provider, get_settings())
    audit = root / ".heagent" / "console" / "audit.jsonl"

    # 工作区就是被测项目根：默认项目的 `.env` 才会是这份（否则面板看到的是空工作区）。
    async with (
        _console_server(root, handler, write_enabled=True) as (_console, base_url),
        httpx.AsyncClient(timeout=15.0) as client,
    ):
        panel = await client.get(f"{base_url}/api/projects/default/config")
        assert panel.status_code == 200
        fingerprint = panel.json()["env_file"]["fingerprint"]

        # ② 错误信封：凭证键 / 非法值 / 指纹冲突（三类真码，都在真流水线上产生）。
        envelopes = [
            await client.put(
                f"{base_url}/api/projects/default/config",
                json={"changes": [{"key": "KIMI_API_KEY", "value": SHORT_SECRET}]},
            ),
            await client.put(
                f"{base_url}/api/projects/default/config",
                json={"changes": [{"key": "MAX_ITERATIONS", "value": "abc"}], "fingerprint": fingerprint},
            ),
            await client.put(
                f"{base_url}/api/projects/default/config",
                json={"changes": [{"key": "MAX_ITERATIONS", "value": "30"}], "fingerprint": "0" * 64},
            ),
        ]
        # ③ SSE：跑一次真实运行，扫描全部事件帧。
        created = await client.post(f"{base_url}/api/projects/default/runs", json={"prompt": "hi"})
        assert created.status_code == 201, created.text
        events = await client.get(f"{base_url}/api/runs/{created.json()['run_id']}/events")

        # ⑤ 审计：写一个**值里带标记**的普通键（指纹仍是面板里那份：前面三次都被拒、没写成）。
        written = await client.put(
            f"{base_url}/api/projects/default/config",
            json={"changes": [{"key": "DEFAULT_MODEL", "value": f"{MARKER}-next"}], "fingerprint": fingerprint},
        )
        assert written.status_code == 200, written.text

    bodies = {
        "面板响应": panel.text,
        **{f"错误信封 {index}": response.text for index, response in enumerate(envelopes)},
        "SSE 帧": events.text,
        "写入响应": written.text,
    }
    # 凭证值：**五面一律不得出现**（这也是「凭证只回 masked」的含义）。
    for name, body in bodies.items():
        for secret in (SHORT_SECRET, POOL_SECRET, *POOL_SECRET.split(",")):
            assert secret not in body, f"{name} 泄漏了 {secret}"
    # 非凭证键的**有效值**：面板与写入响应里**本来就该**出现（那是面板的用途，不是泄漏）；但 SSE 帧、
    # 日志、审计里不得出现（运行事件通道不承载配置值，审计只留哈希）。这一条写清楚，免得把「按设计
    # 回显」误判成泄漏，也免得把「哪几面必须干净」写成含糊的「都不许有值」。
    assert MARKER in bodies["面板响应"] and MARKER in bodies["写入响应"]
    assert MARKER not in bodies["SSE 帧"]

    assert [response.json()["error"]["code"] for response in envelopes] == [
        HttpErrorCode.FIELD_NOT_WRITABLE,
        HttpErrorCode.INVALID_VALUE,
        HttpErrorCode.CONFIG_CONFLICT,
    ]
    items = {entry["key"]: entry for group in panel.json()["groups"] for entry in group["items"]}
    assert items["KIMI_API_KEY"]["value"] is None and items["KIMI_API_KEY"]["masked"] == "*" * 8
    assert items["OPENAI_API_KEYS"]["value"] is None
    assert panel.json()["labels"]["credential"].strip()  # 只回「已配置 + 掩码」，文案由后端给

    # ④ 日志：上述所有动作产生的全部日志记录里都不得出现标记。
    for secret in (SHORT_SECRET, POOL_SECRET, MARKER):
        leaked = [record.getMessage() for record in caplog.records if secret in record.getMessage()]
        assert leaked == [], leaked

    # ⑤ 审计文件：只有哈希与长度，没有值。
    raw = audit.read_text(encoding="utf-8")
    assert MARKER not in raw and SHORT_SECRET not in raw
    entries = [json.loads(line) for line in raw.splitlines()]
    assert [entry["result"] for entry in entries] == ["applied"]
    assert entries[0]["entries"][0]["new_hash"] == hashlib.sha256(f"{MARKER}-next".encode()).hexdigest()


async def test_the_closed_gate_envelope_also_carries_no_credential(tmp_path: Path) -> None:
    """T3② 续：闸门关闭这条拒绝路径（另一台 console）同样不回传任何值。"""
    root = _project(tmp_path / "proj")
    console = HttpProjectConsole(root, global_env_file=None)  # write_enabled 默认 False
    async with _asio_client(console) as client:
        response = await client.put(
            "/api/projects/default/config",
            json={"changes": [{"key": "KIMI_API_KEY", "value": SHORT_SECRET}]},
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == HttpErrorCode.WRITE_DISABLED
    assert SHORT_SECRET not in response.text


async def test_backups_and_the_audit_log_have_no_download_endpoint(tmp_path: Path) -> None:
    """T3 负向面：备份与审计**没有**任何网页端点（把原样配置发出去就是泄漏）。"""
    root = _project(tmp_path / "proj")
    console = HttpProjectConsole(root, write_enabled=True, global_env_file=None)
    async with _asio_client(console) as client:
        panel = await client.get("/api/projects/default/config")
        written = await client.put(
            "/api/projects/default/config",
            json={
                "changes": [{"key": "MAX_ITERATIONS", "value": "30"}],
                "fingerprint": panel.json()["env_file"]["fingerprint"],
            },
        )
        assert written.status_code == 200, written.text
        backup = written.json()["backup"]
        probes = [
            f"/.heagent/backups/{backup}",
            "/.heagent/console/audit.jsonl",
            f"/api/projects/default/backups/{backup}",
            "/api/projects/default/audit.jsonl",
        ]
        responses = [await client.get(path) for path in probes]

    assert backup.endswith(".bak")
    assert [response.status_code for response in responses] == [404, 404, 404, 404]


# ── T4：跨项目不串味（含真实工具路径） ──────────────────────────────


async def test_a_projects_requests_cannot_touch_another_projects_sessions(tmp_path: Path) -> None:
    """T4：会话按项目归属 —— 「A 的 project id + B 的 session id」这条越权路径必须失败且不改文件。"""
    root_a = _project(tmp_path / "A")
    root_b = _project(tmp_path / "B")
    workspace = _workspace(tmp_path)
    provider = _ScriptedProvider([_answer("ok")])
    handler = HttpAgentHandler(provider, get_settings())

    async with (
        _console_server(workspace, handler) as (_console, base_url),
        httpx.AsyncClient(timeout=15.0) as client,
    ):
        entry_a = (await client.post(f"{base_url}/api/projects", json={"path": str(root_a), "name": "A"})).json()
        entry_b = (await client.post(f"{base_url}/api/projects", json={"path": str(root_b), "name": "B"})).json()
        created_b = await client.post(f"{base_url}/api/projects/{entry_b['id']}/sessions", json={"title": "B-only"})
        assert created_b.status_code == 201, created_b.text
        session_b = created_b.json()["session_id"]
        stored = root_b / ".heagent" / "sessions" / f"{session_b}.json"
        before = stored.read_bytes()

        listed_a = await client.get(f"{base_url}/api/projects/{entry_a['id']}/sessions")
        cross_read = await client.get(f"{base_url}/api/projects/{entry_a['id']}/sessions/{session_b}")
        cross_rename = await client.patch(
            f"{base_url}/api/projects/{entry_a['id']}/sessions/{session_b}", json={"title": "HACKED"}
        )
        cross_delete = await client.delete(f"{base_url}/api/projects/{entry_a['id']}/sessions/{session_b}?confirm=true")

    assert [session["session_id"] for session in listed_a.json()["sessions"]] == []
    assert [cross_read.status_code, cross_rename.status_code, cross_delete.status_code] == [404, 404, 404]
    assert {response.json()["error"]["code"] for response in (cross_read, cross_rename, cross_delete)} == {
        HttpErrorCode.UNKNOWN_SESSION
    }
    assert stored.read_bytes() == before  # B 的会话文件一字未动


async def test_a_projects_loop_cannot_read_another_projects_files(tmp_path: Path) -> None:
    """T4（R2）：**经过真实工具调用**的跨项目围栏 —— A 的 loop 用 `file_read` 读 B 的绝对路径必须失败。

    只断言 HTTP 层「取不到 B 的会话」不够：工具层（workspace 围栏）才是真正拦住「让 A 的 agent 去读
    B 的盘」的那道门。这里让 stub provider 发一个 `file_read` 工具请求，再看 SSE 里的工具结果。
    """
    root_a = _project(tmp_path / "A")
    root_b = _project(tmp_path / "B")
    secret_file = root_b / "secret-of-b.txt"
    secret_file.write_text(f"{MARKER} in B\n", encoding="utf-8")
    workspace = _workspace(tmp_path)
    provider = _ScriptedProvider([_tool_request("file_read", {"path": str(secret_file)}), _answer("done")])
    handler = HttpAgentHandler(provider, get_settings())

    async with (
        _console_server(workspace, handler) as (_console, base_url),
        httpx.AsyncClient(timeout=15.0) as client,
    ):
        entry_a = (await client.post(f"{base_url}/api/projects", json={"path": str(root_a), "name": "A"})).json()
        created = await client.post(f"{base_url}/api/projects/{entry_a['id']}/runs", json={"prompt": "read it"})
        assert created.status_code == 201, created.text
        events = await client.get(f"{base_url}/api/runs/{created.json()['run_id']}/events")

    frames = _frames(events.text)
    results = [payload for kind, payload in frames if kind == "tool_result"]
    assert results, frames
    assert results[0]["tool_error"] is True, results
    assert MARKER not in json.dumps(frames, ensure_ascii=False)  # B 的文件内容一个字都没进事件流


# ── T5：闸门关闭只读 + 运行链路不受影响 + 每项目自己的状态根 ────────


async def test_closed_gate_keeps_the_config_surface_read_only_but_runs_still_work(tmp_path: Path) -> None:
    """T5：``HTTP_CONSOLE_WRITE_ENABLED`` 默认关闭时**配置面只读**，而运行链路（Epic 49）照常。"""
    root = _project(tmp_path / "proj")
    provider = _ScriptedProvider([_answer("still alive")])
    handler = HttpAgentHandler(provider, get_settings())
    before = (root / ".env").read_bytes()

    async with (
        _console_server(_workspace(tmp_path), handler) as (_console, base_url),
        httpx.AsyncClient(timeout=15.0) as client,
    ):
        panel = await client.get(f"{base_url}/api/projects/default/config")
        denied = await client.put(
            f"{base_url}/api/projects/default/config",
            json={
                "changes": [{"key": "MAX_ITERATIONS", "value": "30"}],
                "fingerprint": panel.json()["env_file"]["fingerprint"],
            },
        )
        created = await client.post(f"{base_url}/api/projects/default/runs", json={"prompt": "hi"})
        assert created.status_code == 201, created.text
        events = await client.get(f"{base_url}/api/runs/{created.json()['run_id']}/events")
        detail = await client.get(f"{base_url}/api/projects/default/sessions/{created.json()['session_id']}")

    assert panel.status_code == 200 and panel.json()["write_enabled"] is False
    assert denied.status_code == 403 and denied.json()["error"]["code"] == HttpErrorCode.WRITE_DISABLED
    assert (root / ".env").read_bytes() == before
    assert [kind for kind, _payload in _frames(events.text)][-1] == "done"
    assert [message["text"] for message in detail.json()["messages"]] == ["hi", "still alive"]
    assert detail.json()["status"] == "completed"


async def test_each_project_run_uses_its_own_state_root(tmp_path: Path) -> None:
    """T5/§9.2：会话与运行状态落在**该项目自己的**状态根下，而不是服务启动目录。"""
    root_a = _project(tmp_path / "A")
    workspace = _workspace(tmp_path)
    console = HttpProjectConsole(workspace, global_env_file=None)
    entry = console.registry.register(str(root_a), "A")

    runtime_a = console._runtime_for(entry.id)  # noqa: SLF001 - 运行时切片本身就是要断言的事实
    runtime_default = console._runtime_for("default")  # noqa: SLF001

    assert runtime_a.paths.root == root_a.resolve()
    assert runtime_default.paths.root == workspace.resolve()
    assert Path(str(runtime_a.sessions._base)) == root_a.resolve() / ".heagent" / "sessions"  # noqa: SLF001
    assert Path(str(runtime_a.sessions._base)) != Path(str(runtime_default.sessions._base))  # noqa: SLF001


# ── 收口评审补证（镜头三：可达却零覆盖的分支） ─────────────────────


async def test_a_run_cannot_be_started_in_an_unreadable_session(tmp_path: Path) -> None:
    """损坏会话在**运行入口**上必须回 ``session_unreadable``（而不是当成空会话接着写）。

    会话详情那条路径已有用例；但「用损坏会话 id 起 run」（`_resolve_session` 的
    `SessionUnreadableError` 分支）此前**零覆盖**（收口评审·镜头三实测）。该分支可达且必须在
    **起 run 之前**挡住，否则会在损坏文件上继续写。
    """
    root = _project(tmp_path / "proj")
    provider = _ScriptedProvider([_answer("nope")])
    handler = HttpAgentHandler(provider, get_settings())
    broken = root / ".heagent" / "sessions" / "deadbeef.json"
    broken.write_bytes(b"{not json")

    async with _console_server(root, handler) as (_console, base_url), httpx.AsyncClient(timeout=15.0) as client:
        created = await client.post(
            f"{base_url}/api/projects/default/runs", json={"prompt": "hi", "session_id": "deadbeef"}
        )
        sessions = await client.get(f"{base_url}/api/projects/default/sessions")

    assert created.status_code == 409, created.text
    assert created.json()["error"]["code"] == HttpErrorCode.SESSION_UNREADABLE
    assert broken.read_bytes() == b"{not json"  # 损坏文件一字未动
    # 而且没有「顺手」建出一个新会话（起 run 失败不该留下副作用）。
    assert [entry["session_id"] for entry in sessions.json()["sessions"]] == ["deadbeef"]
