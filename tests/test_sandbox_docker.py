"""Epic 53 期一 Story 53-1：DockerRunner 判据（替身测试——不调用真实 docker daemon）。"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from pathlib import Path

import pytest

from heagent.tools.sandbox import DockerRunner, PassthroughRunner
from heagent.tools.sandbox.contracts import SandboxTier, bind_sandbox_workspace
from heagent.tools.sandbox.docker import (
    _docker_available,
    _docker_kill,
    _docker_spawn,
    build_run_argv,
)
from heagent.tools.sandbox.process import _TIMEOUT_RESULT, _format_result

MODULE = "heagent.tools.sandbox.docker"


class _FakeProc:
    """同步 Popen 替身：``communicate``/``wait`` 与真实 ``subprocess.Popen`` 同形。"""

    def __init__(self, *, returncode: int = 0, stdout: bytes = b"", stderr: bytes = b"", delay: float = 0.0):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self._delay = delay

    def communicate(self) -> tuple[bytes, bytes]:
        if self._delay:
            time.sleep(self._delay)
        return self._stdout, self._stderr

    def wait(self) -> int | None:
        return self.returncode


class _FakeSubprocess:
    """``subprocess`` 模块替身：只覆盖探测路径用到的 ``run`` 与异常类型。"""

    TimeoutExpired = subprocess.TimeoutExpired
    PIPE = subprocess.PIPE
    Popen = subprocess.Popen

    def __init__(self, run_impl):
        self.run = run_impl


def _install(spawn_calls: list, fake: _FakeProc, monkeypatch: pytest.MonkeyPatch) -> None:
    """替身缝安装：``_docker_spawn`` 捕获 argv，``_docker_kill`` 记名（判据共用）。"""
    monkeypatch.setattr(f"{MODULE}._docker_spawn", lambda argv: (spawn_calls.append(argv), fake)[1])
    monkeypatch.setattr(f"{MODULE}._docker_kill", lambda path, name: spawn_calls.append(["KILL", name]))


def test_tier_and_relaxation():  # 判据1：档位与审批降级资格
    runner = DockerRunner()
    assert runner.tier is SandboxTier.CONTAINER
    assert SandboxTier.CONTAINER.can_relax_approval is True
    assert SandboxTier.JOB.can_relax_approval is False


def test_available_false_when_cli_missing(monkeypatch: pytest.MonkeyPatch):  # 判据2：CLI 缺席
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert _docker_available("docker") is False
    assert DockerRunner(docker_path="no-such-bin").available is False


def test_available_false_when_daemon_unreachable(monkeypatch: pytest.MonkeyPatch):  # 判据3：daemon 不可达
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/docker")

    def raise_timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(cmd=argv, timeout=5)

    monkeypatch.setattr(f"{MODULE}.subprocess", _FakeSubprocess(raise_timeout))
    assert _docker_available("docker") is False


def test_available_true_when_daemon_ok(monkeypatch: pytest.MonkeyPatch):  # 判据3b：探测成功
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/docker")

    class _OK:
        returncode = 0

    monkeypatch.setattr(f"{MODULE}.subprocess", _FakeSubprocess(lambda argv, **kw: _OK()))
    assert _docker_available("docker") is True


async def test_unavailable_falls_back_with_warning(  # 判据4：不可用降级 + 显性留痕
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    captured: dict = {}

    async def fake_passthrough(self, command: str, *, timeout: int) -> str:
        captured["command"] = command
        return "passthrough-result"

    monkeypatch.setattr(PassthroughRunner, "run", fake_passthrough)
    runner = DockerRunner(docker_path="no-such-bin")
    with caplog.at_level(logging.WARNING, logger="heagent.tools.sandbox.docker"):
        result = await runner.run("echo hi", timeout=5)
    assert result == "passthrough-result"
    assert captured["command"] == "echo hi"
    assert any("falling back" in rec.message for rec in caplog.records)


def test_run_argv_shape_with_and_without_workspace():  # 判据5：argv 形状（判据钉死在组装处）
    argv = build_run_argv(
        docker_path="docker",
        image="python:3.11-slim",
        network="none",
        name="heagent-abc123",
        workspace=Path("E:/demo/ws"),
        command="echo hi",
    )
    assert argv == [
        "docker",
        "run",
        "--rm",
        "--pull=never",
        "--name",
        "heagent-abc123",
        "--network",
        "none",
        "-v",
        "E:/demo/ws:/workspace",
        "-w",
        "/workspace",
        "python:3.11-slim",
        "sh",
        "-c",
        "echo hi",
    ]
    no_ws = build_run_argv(
        docker_path="docker",
        image="img",
        network="none",
        name="n",
        workspace=None,
        command="true",
    )
    assert "-v" not in no_ws and "-w" not in no_ws
    assert "--env" not in no_ws  # env 隔离落点：不透传任何宿主环境变量


async def test_run_uses_bound_workspace_and_formats_result(  # 判据6：会话目录挂载 + 结果如实回传
    monkeypatch: pytest.MonkeyPatch,
):
    spawn_calls: list = []
    fake = _FakeProc(returncode=0, stdout=b"hello", stderr=b"")
    _install(spawn_calls, fake, monkeypatch)
    runner = DockerRunner()
    with bind_sandbox_workspace(Path("E:/demo/session")):
        result = await runner.run("echo hello", timeout=5)
    assert result == _format_result(0, b"hello", b"")
    assert spawn_calls[0][spawn_calls[0].index("-v") + 1] == "E:/demo/session:/workspace"
    assert "-w" in spawn_calls[0]


async def test_timeout_kills_container_and_reports(monkeypatch: pytest.MonkeyPatch):  # 判据7：超时清理
    spawn_calls: list = []
    fake = _FakeProc(returncode=None, delay=2.0)
    _install(spawn_calls, fake, monkeypatch)
    runner = DockerRunner()
    result = await runner.run("sleep 30", timeout=1)
    assert result == _TIMEOUT_RESULT.format(timeout=1)
    kills = [c for c in spawn_calls if c[0] == "KILL"]
    assert len(kills) == 1 and kills[0][1].startswith("heagent-")


async def test_cancel_kills_container_and_propagates(monkeypatch: pytest.MonkeyPatch):  # 判据8：取消清理
    spawn_calls: list = []
    fake = _FakeProc(returncode=None, delay=5.0)
    _install(spawn_calls, fake, monkeypatch)
    runner = DockerRunner()
    task = asyncio.create_task(runner.run("sleep 30", timeout=10))
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert any(c[0] == "KILL" for c in spawn_calls)


async def test_docker_failure_is_explicit_not_fallback(  # 判据9：运行期 docker 错误显性失败
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    spawn_calls: list = []
    fake = _FakeProc(returncode=125, stdout=b"", stderr=b"docker: image not found")
    _install(spawn_calls, fake, monkeypatch)
    fallbacks: dict = {}

    async def no_fallback(self, command: str, *, timeout: int) -> str:
        fallbacks["called"] = True
        return ""

    monkeypatch.setattr(PassthroughRunner, "run", no_fallback)
    runner = DockerRunner()
    result = await runner.run("echo hi", timeout=5)
    assert result == _format_result(125, b"", b"docker: image not found")
    assert "called" not in fallbacks  # 不降级：静默回透传会伪造「已在沙箱里跑」


def test_resolver_builds_docker_runner():  # 判据10：engine 选择分支吃 Settings（镜像 + 网络档 D2）
    from types import SimpleNamespace

    from heagent.engine.container import _resolve_command_runner
    from heagent.tools.sandbox.docker import DockerRunner as _DR

    settings = SimpleNamespace(sandbox_docker_image="heagent-sandbox:3.11", sandbox_network=False)
    runner = _resolve_command_runner(settings, "docker", None)
    assert isinstance(runner, _DR)
    assert runner.tier is SandboxTier.CONTAINER
    assert runner.isolates_network() is True

    bridged = _resolve_command_runner(
        SimpleNamespace(sandbox_docker_image="img:x", sandbox_network=True), "docker", None
    )
    assert bridged.isolates_network() is False
    assert "img:x" in repr(bridged)


def test_sandbox_decision_full_chain_docker(
    monkeypatch: pytest.MonkeyPatch,
):  # 判据11：Settings→resolver→runner→decision→executor→元数据全链
    from heagent.config import Settings
    from heagent.engine.container import EngineContainer

    # 可用链：docker 档 runner 注入 executor，decision 三事实 + run 上下文元数据同源
    monkeypatch.setattr("heagent.tools.sandbox.DockerRunner.available", True)
    engine = EngineContainer.default(settings=Settings(_env_file=None, sandbox_backend="docker"))
    runner = engine.executor.sandbox_runner
    assert isinstance(runner, DockerRunner) and runner.tier is SandboxTier.CONTAINER
    decision = engine.sandbox_decision
    assert decision.requested_backend == "docker"
    assert decision.effective_backend == "docker"
    assert decision.filesystem_isolation is True
    assert decision.network_isolation is True  # --network=none 默认（brief D2）
    ctx = engine.create_run_context()
    assert ctx.metadata["sandbox_decision"]["effective_backend"] == "docker"

    # bridge 档：SANDBOX_NETWORK=True 显式开启后网络隔离事实翻转
    bridged = EngineContainer.default(settings=Settings(_env_file=None, sandbox_backend="docker", sandbox_network=True))
    assert bridged.sandbox_decision.network_isolation is False

    # 不可用链：decision 诚实降级——effective passthrough、隔离双 False
    monkeypatch.setattr("heagent.tools.sandbox.DockerRunner.available", False)
    degraded = EngineContainer.default(settings=Settings(_env_file=None, sandbox_backend="docker"))
    assert degraded.sandbox_decision.effective_backend == "passthrough"
    assert degraded.sandbox_decision.filesystem_isolation is False
    assert degraded.sandbox_decision.network_isolation is False
