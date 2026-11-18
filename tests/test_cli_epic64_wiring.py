"""Epic 64 的**入口层接线**判据：三处集成点各一条，拨回去就红。

为什么单独成文件：story 自己的测试文件都只测「单元能跑」（`cron_cmd` 直 invoke、
`build_http_app(tasks=…)` 手工注入、`maybe_compress` 之外的压缩钩子）。但真正的用户路径是
「`heagent cron status` 经 `main` 派发」/「内嵌网页入口读到本进程的进度」/「每轮迭代的自动压缩
不只是空转」——这三处正是接线最容易被无声拨掉的地方，故在此钉住。
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import httpx
import pytest
from click.testing import CliRunner

from heagent.agent.context_runtime import maybe_compress
from heagent.agent.run_lifecycle import AgentState
from heagent.cli.console import main
from heagent.config import Settings
from heagent.engine.tasks import TaskRegistry
from heagent.pub.types import Message, Role, TokenUsage

_JOBS = """[
  {
    "id": "job-1",
    "prompt": "say hi",
    "cron": "0 20 * * *",
    "recurring": true,
    "created": "2026-11-17T12:00:00+00:00",
    "last_run": "2026-11-17T12:02:59+00:00",
    "last_status": "success",
    "last_success": "2026-11-17T12:02:59+00:00"
  }
]"""


def test_main_dispatches_cron_status(tmp_path) -> None:
    """`heagent cron status` 必须能从主命令组直达（注册行被删就红）。"""
    jobs_file = tmp_path / "jobs.json"
    jobs_file.write_text(_JOBS, encoding="utf-8")

    result = CliRunner().invoke(main, ["cron", "status", "--jobs-file", str(jobs_file)])

    assert result.exit_code == 0, result.output
    assert "job-1" in result.output


@pytest.mark.embedded_http_service
@pytest.mark.asyncio
async def test_embedded_service_exposes_task_endpoint(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """内嵌网页入口必须注入进度来源：不注入时 `/api/tasks` 恒 404，进度就永远查不到。"""
    from heagent.cli.http import build_http_service

    monkeypatch.chdir(tmp_path)
    settings = Settings(_env_file=None, http_enabled=True, ws_enabled=False)
    service = build_http_service(settings, http_enabled=True, ws_enabled=False)
    http_server = service._http  # 装配产物：None 表示 HTTP listener 未装配
    assert http_server is not None

    transport = httpx.ASGITransport(app=http_server.app)
    async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:9101") as client:
        response = await client.get("/api/tasks")

    assert response.status_code == 200
    assert "tasks" in response.json()


@dataclass
class _FakeRuntime:
    max_context_tokens: int = 100


class _NoopCompressor:
    """未超阈值时压缩器的真实行为：**返回同一个列表对象**。"""

    async def compress(self, messages: list[Message], *, token_count: int = 0, max_tokens: int = 0) -> list[Message]:
        return messages


class _RealCompressor:
    """真压缩时压缩器的真实行为：返回**新的**列表对象。"""

    async def compress(self, messages: list[Message], *, token_count: int = 0, max_tokens: int = 0) -> list[Message]:
        return [Message(role=Role.SYSTEM, content="summary")]


def _loop(compressor: object) -> SimpleNamespace:
    return SimpleNamespace(compressor=compressor, _runtime=_FakeRuntime(), _emit=lambda *a, **k: None)


def _state() -> AgentState:
    return AgentState(messages=[Message(role=Role.USER, content="hi")])


def _usage() -> TokenUsage:
    return TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2)


@pytest.mark.asyncio
async def test_noop_iteration_leaves_no_task_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    """未压缩的迭代不得在注册表里留下 `completed 100%` 噪声（每轮都会调用）。"""
    registry = TaskRegistry()
    monkeypatch.setattr("heagent.agent.context_runtime.default_task_registry", lambda: registry)

    await maybe_compress(_loop(_NoopCompressor()), _state(), SimpleNamespace(run_id="r1"), _usage())

    assert registry.snapshot() == []


@pytest.mark.asyncio
async def test_real_compression_leaves_a_completed_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    """真压缩要留下可查的终态条目（否则 `/api/tasks` 永远看不到压缩发生过）。"""
    registry = TaskRegistry()
    monkeypatch.setattr("heagent.agent.context_runtime.default_task_registry", lambda: registry)

    await maybe_compress(_loop(_RealCompressor()), _state(), SimpleNamespace(run_id="r1"), _usage())

    entries = registry.snapshot()
    assert len(entries) == 1
    assert entries[0].kind == "context_compression"
    assert entries[0].status.value == "completed"
