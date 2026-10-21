"""Epic 53 期一 Story 53-1：DockerRunner 判据（替身测试——不调用真实 docker daemon）。"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import time
from pathlib import Path

import pytest

from heagent.tools.sandbox import DockerRunner, PassthroughRunner
from heagent.tools.sandbox.contracts import SandboxTier, bind_sandbox_workspace
from heagent.tools.sandbox.process import bind_command_runner
from heagent.tools.sandbox.docker import (
    DEFAULT_IMAGE,
    _docker_available,
    _docker_inspect_digest,
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
        "--cap-drop=ALL",
        "--security-opt",
        "no-new-privileges",
        "--user",
        "sandbox",
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
    monkeypatch.setattr(f"{MODULE}._docker_available", lambda p: True)  # 替身链不真实探测 daemon
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
    monkeypatch.setattr(f"{MODULE}._docker_available", lambda p: True)  # 替身链不真实探测 daemon
    runner = DockerRunner()
    result = await runner.run("sleep 30", timeout=1)
    assert result == _TIMEOUT_RESULT.format(timeout=1)
    kills = [c for c in spawn_calls if c[0] == "KILL"]
    assert len(kills) == 1 and kills[0][1].startswith("heagent-")


async def test_cancel_kills_container_and_propagates(monkeypatch: pytest.MonkeyPatch):  # 判据8：取消清理
    spawn_calls: list = []
    fake = _FakeProc(returncode=None, delay=5.0)
    _install(spawn_calls, fake, monkeypatch)
    monkeypatch.setattr(f"{MODULE}._docker_available", lambda p: True)  # 替身链不真实探测 daemon
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
    monkeypatch.setattr(f"{MODULE}._docker_available", lambda p: True)  # 替身链不真实探测 daemon
    runner = DockerRunner()
    result = await runner.run("echo hi", timeout=5)
    assert result == _format_result(125, b"", b"docker: image not found")
    assert "called" not in fallbacks  # 不降级：静默回透传会伪造「已在沙箱里跑」


def test_resolver_builds_docker_runner(monkeypatch: pytest.MonkeyPatch):  # 判据10：resolver 分支吃 Settings
    from types import SimpleNamespace

    from heagent.engine.container import _resolve_command_runner
    from heagent.tools.sandbox.docker import DockerRunner as _DR

    # 可用性闸（审查修复批）：resolver 现在同步探测，替身链一律桩掉真实 daemon 探测。
    monkeypatch.setattr("heagent.tools.sandbox.docker._docker_available", lambda p: True)
    settings = SimpleNamespace(
        sandbox_docker_image="heagent-sandbox:3.11",
        sandbox_network=False,
        sandbox_memory_limit_mb=0,
        sandbox_nproc_limit=0,
        sandbox_cpu_seconds=0,
        sandbox_docker_digest="",
    )
    runner = _resolve_command_runner(settings, "docker", None)
    assert isinstance(runner, _DR)
    assert runner.tier is SandboxTier.CONTAINER
    assert runner.isolates_network() is True

    bridged = _resolve_command_runner(
        SimpleNamespace(
            sandbox_docker_image="img:x",
            sandbox_network=True,
            sandbox_memory_limit_mb=0,
            sandbox_nproc_limit=0,
            sandbox_cpu_seconds=0,
            sandbox_docker_digest="",
        ),
        "docker",
        "E:/demo/ws",
    )
    assert bridged.isolates_network() is False
    assert bridged.workspace == Path("E:/demo/ws")
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


def test_resolver_gate_unavailable_docker(monkeypatch: pytest.MonkeyPatch):  # 判据12：resolver 可用性闸
    """daemon 不可达 ⇒ resolver 回 None（对齐 winjob）：装配期诚实，事件/决策不再报 container 档。"""
    from types import SimpleNamespace

    from heagent.engine.container import _resolve_command_runner

    monkeypatch.setattr("heagent.tools.sandbox.docker._docker_available", lambda p: False)
    settings = SimpleNamespace(
        sandbox_docker_image="img:x",
        sandbox_network=False,
        sandbox_memory_limit_mb=0,
        sandbox_nproc_limit=0,
        sandbox_cpu_seconds=0,
        sandbox_docker_digest="",
    )
    assert _resolve_command_runner(settings, "docker", None) is None


async def test_workspace_fallback_mount(  # 判据13：workspace_root 兜底挂载（审查修复批 A）
    monkeypatch: pytest.MonkeyPatch,
):
    """FR-1 未 bind 时回落 runner 持有的 workspace（firejail --private 同型语义）——不给静默无挂载。"""
    spawn_calls: list = []
    fake = _FakeProc(returncode=0, stdout=b"ok", stderr=b"")
    _install(spawn_calls, fake, monkeypatch)
    monkeypatch.setattr(f"{MODULE}._docker_available", lambda p: True)
    runner = DockerRunner(workspace=Path("E:/demo/ws"))
    result = await runner.run("echo ok", timeout=5)
    assert result == _format_result(0, b"ok", b"")
    assert spawn_calls[0][spawn_calls[0].index("-v") + 1] == "E:/demo/ws:/workspace"


async def test_workspace_bind_wins_over_fallback(monkeypatch: pytest.MonkeyPatch):  # 判据13b：FR-1 优先
    spawn_calls: list = []
    fake = _FakeProc(returncode=0, stdout=b"ok", stderr=b"")
    _install(spawn_calls, fake, monkeypatch)
    monkeypatch.setattr(f"{MODULE}._docker_available", lambda p: True)
    runner = DockerRunner(workspace=Path("E:/demo/ws"))
    with bind_sandbox_workspace(Path("E:/demo/session")):
        await runner.run("echo ok", timeout=5)
    assert spawn_calls[0][spawn_calls[0].index("-v") + 1] == "E:/demo/session:/workspace"


def test_resource_limits_argv_mapping(monkeypatch: pytest.MonkeyPatch):  # 判据14：限额 argv 映射
    from types import SimpleNamespace

    from heagent.engine.container import _resolve_command_runner

    monkeypatch.setattr("heagent.tools.sandbox.docker._docker_available", lambda p: True)
    settings = SimpleNamespace(
        sandbox_docker_image="img:x",
        sandbox_network=False,
        sandbox_memory_limit_mb=512,
        sandbox_nproc_limit=100,
        sandbox_cpu_seconds=30,
        sandbox_docker_digest="",
    )
    runner = _resolve_command_runner(settings, "docker", None)
    argv = build_run_argv(
        docker_path="docker",
        image="img:x",
        network="none",
        name="n",
        workspace=Path("E:/demo/ws"),
        command="true",
        memory_limit_mb=runner._memory_limit_mb,
        nproc_limit=runner._nproc_limit,
    )
    assert argv[argv.index("--memory") + 1] == "512m"
    assert argv[argv.index("--pids-limit") + 1] == "100"
    # 位置判据（回归：旗标排在 IMAGE 之后 ⇒ docker 将其视作容器内命令参数，限额静默失效）。
    # 只断言「旗标存在」会漏掉这一点——真实 daemon integration 用例是第二道闸。
    image_at = argv.index("img:x")
    assert argv.index("--memory") < image_at, "--memory must precede the image, else docker ignores it"
    assert argv.index("--pids-limit") < image_at, "--pids-limit must precede the image, else docker ignores it"


def test_cpu_seconds_honesty_warning_resolver(  # 判据14b：cpu_seconds 无诚实映射 → 显性提示
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    from types import SimpleNamespace

    from heagent.engine.container import _resolve_command_runner

    monkeypatch.setattr("heagent.tools.sandbox.docker._docker_available", lambda p: True)
    settings = SimpleNamespace(
        sandbox_docker_image="img:x",
        sandbox_network=False,
        sandbox_memory_limit_mb=0,
        sandbox_nproc_limit=0,
        sandbox_cpu_seconds=30,
        sandbox_docker_digest="",
    )
    with caplog.at_level(logging.WARNING, logger="heagent.engine.container"):
        _resolve_command_runner(settings, "docker", None)
    assert any("NOT enforced" in r.message for r in caplog.records)


def test_kill_fallback_when_kill_fails(monkeypatch: pytest.MonkeyPatch):  # 判据15：kill 失败 → rm -f 兜底
    calls: list[list[str]] = []

    class _KillFails(_FakeSubprocess):
        def __init__(self) -> None:  # 不设实例 run——方法即实现；仅继承异常类型等类属性
            pass

        def run(self, argv, capture_output=False, timeout=None):
            calls.append(list(argv))
            if argv[1] == "kill":
                raise subprocess.TimeoutExpired(cmd=argv, timeout=5)
            return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(f"{MODULE}.subprocess", _KillFails())
    _docker_kill("docker", "heagent-orphan")
    assert calls[-1][:3] == ["docker", "rm", "-f"]


def test_kill_rm_fallback_failure_only_warns(  # 判据15c：兜底也失败 → 只留痕，不上抛
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
):
    """清理是兜底动作：``rm -f`` 也失败时不得抛异常拖垮超时/取消路径，须 warning 留痕。"""

    class _AllFail(_FakeSubprocess):
        def __init__(self) -> None:
            pass

        def run(self, argv, capture_output=False, text=False, timeout=None):
            raise OSError("docker daemon gone")

    monkeypatch.setattr(f"{MODULE}.subprocess", _AllFail())
    with caplog.at_level(logging.WARNING, logger=MODULE):
        _docker_kill("docker", "heagent-stuck")  # 不抛
    assert any("may be orphaned" in r.message for r in caplog.records)


def test_kill_inspect_failure_triggers_fallback(  # 判据15d：状态不确定 ⇒ 当活着处理
    monkeypatch: pytest.MonkeyPatch,
):
    """kill 成功但 inspect 失败（无法确认已停）→ 按「不确定」走 rm -f 兜底，而不是假定已停。"""
    calls: list[list[str]] = []

    class _InspectFails(_FakeSubprocess):
        def __init__(self) -> None:
            pass

        def run(self, argv, capture_output=False, text=False, timeout=None):
            calls.append(list(argv))
            if argv[1] == "inspect":
                raise subprocess.TimeoutExpired(cmd=argv, timeout=5)
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

    monkeypatch.setattr(f"{MODULE}.subprocess", _InspectFails())
    _docker_kill("docker", "heagent-uncertain")
    assert calls[-1][:3] == ["docker", "rm", "-f"]


def test_digest_parse_reads_repo_digest(monkeypatch: pytest.MonkeyPatch):  # 判据16c：digest 解析
    """``docker image inspect`` 输出形如 ``["repo@sha256:…"]`` → 取首个 ``sha256:…`` 片段。"""
    payload = json.dumps(["heagent-sandbox@sha256:" + "c" * 64])

    monkeypatch.setattr(
        f"{MODULE}.subprocess",
        _FakeSubprocess(lambda argv, **kw: subprocess.CompletedProcess(argv, 0, stdout=payload, stderr="")),
    )
    assert _docker_inspect_digest("docker", "img:x") == "sha256:" + "c" * 64


def test_digest_parse_returns_none_when_unavailable(monkeypatch: pytest.MonkeyPatch):  # 判据16d
    """镜像缺席 / 输出非法 / 无 digest 条目 → None（由调用方判为不符并拒绝，不得伪造匹配）。"""
    cases = [
        subprocess.CompletedProcess([], 1, stdout="", stderr="no such image"),
        subprocess.CompletedProcess([], 0, stdout="not json", stderr=""),
        subprocess.CompletedProcess([], 0, stdout=json.dumps(["local/img:tag"]), stderr=""),
        subprocess.CompletedProcess([], 0, stdout="[]", stderr=""),
    ]
    for case in cases:
        monkeypatch.setattr(f"{MODULE}.subprocess", _FakeSubprocess(lambda argv, _c=case, **kw: _c))
        assert _docker_inspect_digest("docker", "img:x") is None

    def _boom(argv, **kw):
        raise OSError("docker gone")

    monkeypatch.setattr(f"{MODULE}.subprocess", _FakeSubprocess(_boom))
    assert _docker_inspect_digest("docker", "img:x") is None


def test_kill_no_fallback_when_container_stopped(monkeypatch: pytest.MonkeyPatch):  # 判据15b：正常停无兜底
    calls: list[list[str]] = []

    class _KillOK(_FakeSubprocess):
        def __init__(self) -> None:  # 同上：实例不遮蔽方法
            pass

        def run(self, argv, capture_output=False, text=False, timeout=None):
            calls.append(list(argv))
            return subprocess.CompletedProcess(argv, 0, stdout="false\n" if argv[1] == "inspect" else "", stderr="")

    monkeypatch.setattr(f"{MODULE}.subprocess", _KillOK())
    _docker_kill("docker", "heagent-ok")
    assert not any(c[1] == "rm" for c in calls)


async def test_digest_pin_mismatch_rejects(monkeypatch: pytest.MonkeyPatch):  # 判据16：digest 不符显性拒绝
    spawn_calls: list = []
    fake = _FakeProc(returncode=0, stdout=b"out", stderr=b"")
    _install(spawn_calls, fake, monkeypatch)
    monkeypatch.setattr(f"{MODULE}._docker_available", lambda p: True)
    monkeypatch.setattr(f"{MODULE}._docker_inspect_digest", lambda p, i: "sha256:" + "a" * 64)
    runner = DockerRunner(digest="sha256:" + "b" * 64)
    with pytest.raises(RuntimeError, match="digest mismatch"):
        await runner.run("echo hi", timeout=5)


async def test_digest_pin_match_runs(  # 判据16b：相符则放行
    monkeypatch: pytest.MonkeyPatch,
):
    spawn_calls: list = []
    fake = _FakeProc(returncode=0, stdout=b"out", stderr=b"")
    _install(spawn_calls, fake, monkeypatch)
    monkeypatch.setattr(f"{MODULE}._docker_available", lambda p: True)
    monkeypatch.setattr(f"{MODULE}._docker_inspect_digest", lambda p, i: "sha256:" + "a" * 64)
    runner = DockerRunner(digest="sha256:" + "a" * 64)
    result = await runner.run("echo hi", timeout=5)
    assert result.startswith("exit_code=0")


def test_default_image_matches_settings():  # 判据17：双真源交叉校验
    from heagent.config import Settings

    assert DockerRunner().image is not None
    assert Settings(_env_file=None).sandbox_docker_image == DEFAULT_IMAGE


def test_isolates_network_protocol_surface():  # 判据18：四后端 isolates_network 全实现
    from heagent.tools.sandbox import FirejailBackend, PassthroughRunner, WinJobBackend

    assert PassthroughRunner().isolates_network() is False
    assert WinJobBackend().isolates_network() is False
    assert FirejailBackend(network=False).isolates_network() is True
    assert FirejailBackend(network=True).isolates_network() is False
    assert DockerRunner(network="none").isolates_network() is True
    assert DockerRunner(network="bridge").isolates_network() is False


async def test_session_docker_wrap_keeps_container_cwd(  # 判据19：session×docker 容器侧 cwd（审查修复批 D）
    monkeypatch: pytest.MonkeyPatch,
):
    """FR-1 开 + docker 后端：wrap 用容器侧 cwd（/workspace 起）+ POSIX marker + 退出码复原。"""
    from heagent.tools.sandbox.session import SandboxSession, _MARKER, bind_sandbox_session

    spawn_calls: list = []
    stdout = f"exit_code=0\nhello\n{_MARKER}\n/workspace/sub\n".encode()
    fake = _FakeProc(returncode=0, stdout=stdout, stderr=b"")
    _install(spawn_calls, fake, monkeypatch)
    monkeypatch.setattr(f"{MODULE}._docker_available", lambda p: True)
    runner = DockerRunner(workspace=Path("E:/demo/ws"))
    session = SandboxSession("E:/demo/ws")
    with bind_command_runner(runner), bind_sandbox_session(session):
        result = await session.run("echo hello", timeout=5)
    wrapped = spawn_calls[0][-1]  # sh -c 的命令串
    assert wrapped.startswith('cd "/workspace" && { echo hello; }')
    assert _MARKER in wrapped and "exit" in wrapped
    assert session._docker_cwd == "/workspace/sub"  # 容器侧 cwd 已前移
    assert "hello" in result and _MARKER not in result  # marker 行已清理
