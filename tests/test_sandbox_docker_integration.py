"""Epic 53 期一 Story 53-2：DockerRunner 真实 daemon 链路（``integration`` 标记）。

CI 无 docker（frame.md 五：控制台 UI 同款限制），常规 ``pytest`` 跳过；本机跑：
``pytest -m integration tests/test_sandbox_docker_integration.py``。镜像缺失时用例自行
构建（默认基座 digest，直连不可达时回退 daocloud 镜像源——见 docker/sandbox/Dockerfile）。
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

IMAGE = "heagent-sandbox:3.11"
DOCKERFILE_DIR = str(Path(__file__).resolve().parents[1] / "docker" / "sandbox")
MIRROR_BASE = "docker.m.daocloud.io/library/python:3.11-slim"


def _daemon_ok() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        probe = subprocess.run(
            ["docker", "version", "--format", "{{.Server.Version}}"], capture_output=True, timeout=10
        )
        return probe.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _ensure_image() -> None:
    """镜像缺席则构建：默认 digest 基座失败（直连不可达）时回退镜像源基座。两路都有界。"""
    probe = subprocess.run(  # noqa: S603
        ["docker", "image", "inspect", IMAGE],
        capture_output=True,
        timeout=30,
    )
    if probe.returncode == 0:
        return
    build = subprocess.run(  # noqa: S603
        ["docker", "build", "-q", "-t", IMAGE, DOCKERFILE_DIR],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if build.returncode != 0:
        build = subprocess.run(  # noqa: S603
            ["docker", "build", "-q", "--build-arg", f"BASE={MIRROR_BASE}", "-t", IMAGE, DOCKERFILE_DIR],
            capture_output=True,
            text=True,
            timeout=600,
        )
    assert build.returncode == 0, f"sandbox image build failed: {(build.stderr or build.stdout)[-500:]}"


requires_daemon = pytest.mark.skipif(not _daemon_ok(), reason="docker daemon unavailable")


@requires_daemon
async def test_real_exec_and_workspace_mount(tmp_path: Path):  # 真实执行 + 挂载链路
    _ensure_image()
    from heagent.tools.sandbox import DockerRunner, bind_sandbox_workspace

    (tmp_path / "hello.txt").write_text("mount-ok", encoding="utf-8")
    runner = DockerRunner(image=IMAGE)
    assert runner.available
    with bind_sandbox_workspace(tmp_path):
        result = await runner.run("cat /workspace/hello.txt && git --version", timeout=60)
    assert "exit_code=0" in result
    assert "mount-ok" in result
    assert "git version" in result


@requires_daemon
async def test_real_network_isolation_by_default():  # D2：默认 --network=none 真实阻断出站
    _ensure_image()
    from heagent.tools.sandbox import DockerRunner

    runner = DockerRunner(image=IMAGE)
    result = await runner.run(
        "python -c \"import socket; socket.create_connection(('1.1.1.1', 53), timeout=3)\"",
        timeout=60,
    )
    # 审查修复批 G：区分「网络被阻断」与「docker 层坏/挂死」——容器命令必须真实到达并
    # 以非零码退出（连接失败签名），且不得是超时形态（挂死 ≠ 阻断实证）。
    assert not result.startswith("exit_code=-1"), f"probe hung until timeout, not blocked: {result[:200]}"
    assert "exit_code=0" not in result
    assert "docker:" not in result.lower(), f"docker-layer error, not isolation proof: {result[:200]}"


@requires_daemon
async def test_real_timeout_cleans_up_container():  # 审查修复批 C：真实链路的超时清理
    """超时路径真杀容器：短超时跑长命命令后，``heagent-*`` 无 running 残留（判据 7/8 的桩测不到真实 argv）。"""
    _ensure_image()
    from heagent.tools.sandbox import DockerRunner

    runner = DockerRunner(image=IMAGE)
    result = await runner.run("sleep 30", timeout=2)
    assert result.startswith("exit_code=-1"), f"expected timeout shape: {result[:120]}"
    probe = subprocess.run(  # noqa: S603
        ["docker", "ps", "--filter", "name=heagent-", "--filter", "status=running", "-q"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert probe.returncode == 0 and probe.stdout.strip() == "", (
        f"orphan running container after timeout: {probe.stdout!r}"
    )


@requires_daemon
async def test_real_env_isolation(monkeypatch: pytest.MonkeyPatch):  # 容器边界 env 隔离
    _ensure_image()
    from heagent.tools.sandbox import DockerRunner

    monkeypatch.setenv("HEAGENT_SENTINEL", "host-leak")
    runner = DockerRunner(image=IMAGE)
    result = await runner.run('test -z "$HEAGENT_SENTINEL" && echo clean', timeout=60)
    assert "exit_code=0" in result
    assert "clean" in result


@requires_daemon
async def test_real_pids_limit_is_enforced():  # 审查修复批 E：--pids-limit 真实生效
    """限额不是「argv 里有旗标」就算数：受限容器内粗粒度 fork 必须被打断（非零退出）。

    判据 14 只钉 argv 形状（替身），本条证「旗标确实约束了容器」。
    """
    _ensure_image()
    from heagent.tools.sandbox import DockerRunner

    runner = DockerRunner(image=IMAGE, nproc_limit=8)
    # 反复 fork 直到失败：限额生效时 shell 拿不到新进程，最终以非零码退出。
    result = await runner.run(
        "i=0; while [ $i -lt 50 ]; do sleep 2 & i=$((i+1)); done; wait; echo survived",
        timeout=60,
    )
    assert "survived" not in result, f"pids limit not enforced: {result[:300]}"
    assert not result.startswith("exit_code=0")


@requires_daemon
async def test_real_memory_limit_is_enforced():  # 审查修复批 E：--memory 真实生效
    """受限内存下分配超额内存必须被杀（OOM），而非静默成功。"""
    _ensure_image()
    from heagent.tools.sandbox import DockerRunner

    runner = DockerRunner(image=IMAGE, memory_limit_mb=64)
    result = await runner.run(
        'python -c "x = bytearray(512 * 1024 * 1024); print(len(x))"',
        timeout=60,
    )
    assert "exit_code=0" not in result, f"memory limit not enforced: {result[:300]}"
    assert "536870912" not in result, "allocation of 512MiB succeeded under a 64MiB cap"


@requires_daemon
async def test_real_hardening_flags_apply():  # 审查修复批：cap-drop / 非 root 用户真实生效
    """硬化旗标须在容器内可观测：非 root 用户 + 零有效 capability + 无法写系统路径。

    三条各自独立断言（不靠「整条命令非零退出」间接推断——末尾 `echo` 会把退出码抹成 0）。
    """
    _ensure_image()
    from heagent.tools.sandbox import DockerRunner

    runner = DockerRunner(image=IMAGE)
    result = await runner.run(
        'id -u; id -un; grep "^CapEff" /proc/self/status; touch /etc/probe && echo WROTE || echo DENIED',
        timeout=60,
    )
    assert "exit_code=0" in result, f"probe command itself failed: {result[:300]}"
    lines = [line.strip() for line in result.splitlines()]
    # ① 非 root：uid 非 0 且用户名为沙箱用户
    assert lines[lines.index("stdout:") + 1] != "0", f"running as root in container: {lines[:6]}"
    assert "sandbox" in lines, f"expected non-root sandbox user: {lines[:6]}"
    # ② --cap-drop=ALL：有效 capability 位图全零
    assert any(line == "CapEff:\t0000000000000000" or line.startswith("CapEff:\t0000") for line in lines), (
        f"capabilities not dropped: {lines[:8]}"
    )
    # ③ 非 root ⇒ 系统路径不可写
    assert "DENIED" in result and "WROTE" not in result, f"write to /etc succeeded: {result[:300]}"
