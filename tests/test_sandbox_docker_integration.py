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
    """镜像缺席则构建：默认 digest 基座失败（直连不可达）时回退镜像源基座。"""
    probe = subprocess.run(["docker", "image", "inspect", IMAGE], capture_output=True)  # noqa: S603
    if probe.returncode == 0:
        return
    build = subprocess.run(  # noqa: S603
        ["docker", "build", "-q", "-t", IMAGE, DOCKERFILE_DIR], capture_output=True, text=True
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
    assert "exit_code=0" not in result  # 出站被阻断 = 非零退出（显性失败而非挂死）


@requires_daemon
async def test_real_env_isolation(monkeypatch: pytest.MonkeyPatch):  # 容器边界 env 隔离
    _ensure_image()
    from heagent.tools.sandbox import DockerRunner

    monkeypatch.setenv("HEAGENT_SENTINEL", "host-leak")
    runner = DockerRunner(image=IMAGE)
    result = await runner.run('test -z "$HEAGENT_SENTINEL" && echo clean', timeout=60)
    assert "exit_code=0" in result
    assert "clean" in result
