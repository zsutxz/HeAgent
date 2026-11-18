"""Story 67.8：按**攻击向量**组织的沙箱逃逸测试。

与既有沙箱测试的分工：``tests/test_sandbox.py`` / ``tests/test_sandbox_mode.py`` 覆盖后端的
功能与生命周期（spawn / 超时 / 清理 / 档位选型），``test_sandbox_docker.py`` 覆盖 argv 形状。
本文件只回答一个问题：**攻击者从工具面往外伸手时，是谁挡住、挡住后的判据是什么**。

每个向量都是三段式：攻击动作 → 期望拒绝 → 断言；且尽量带**正面控制**，否则「什么都没发生」
会被误读成「挡住了」（例如环境变量那条：必须证明普通变量确实继承下来了）。

============  ==================================  ================================  ========
向量           攻击动作                            拒绝层                            需容器
============  ==================================  ================================  ========
dotdot        ``../../secret.txt`` 读 / 写         ``tools/path_safety`` 围栏         否
absolute      绝对路径落到工作区外（含系统文件）  同一围栏 + ``check_write_denied``   否
symlink       工作区内符号链接指向宿主目录/文件   围栏 + 逐组件 ``O_NOFOLLOW``        否
sensitive     读 ``.env`` / 凭证 / 内部运行状态     ``path_safety`` 的 deny 表          否
env_leak      子进程 / 容器读宿主密钥              ``scrub_sensitive_env`` + 容器边界  否
mount_escape  容器内 ``/workspace/..`` 与宿主绝对路径  容器挂载面（OS 级）          是
pid_probe     容器内探宿主 PID / 挂载表           容器 PID 命名空间（OS 级）        是
============  ==================================  ================================  ========

⚠ 口径：这些**都不是**绝对安全边界（``docs/frame.md`` §4.19 的三层非边界）。本文件钉的是
「合作模式下尊重工具拒绝」那条防线仍然生效，以及容器档的 OS 级兜底**确实存在**——不是
「沙箱不可逃逸」的证明。
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from heagent.tools.builtins.file import file_read, file_write
from heagent.tools.path_safety import (
    WorkspacePathError,
    bind_workspace_root,
    check_read_denied,
    check_write_denied,
    read_bytes_under_root,
    resolve_under_root,
)
from heagent.tools.sandbox import DockerRunner, _run_subprocess_exec, scrub_sensitive_env
from heagent.tools.sandbox.docker import build_run_argv

_SECRET_MARKER = "HOST-SECRET-MARKER-4f1a"
_ENV_SECRET_MARKER = "sk-escape-marker-77c1"
_IMAGE = "heagent-sandbox:3.11"


@pytest.fixture()
def workspace(tmp_path: Path) -> Any:
    """独立工作区：围栏之外还放一份「宿主秘密」，供各向量证明内容没有漏出来。"""
    root = tmp_path / "workspace"
    root.mkdir()
    (tmp_path / "host-secret.txt").write_text(_SECRET_MARKER, encoding="utf-8")
    with bind_workspace_root(root):
        yield root


def _symlink_or_skip(link: Path, target: Path) -> None:
    """建符号链接；平台不允许（Windows 无权限 / 文件系统不支持）时 skip 并说明原因。"""
    try:
        link.symlink_to(target, target_is_directory=target.is_dir())
    except (OSError, NotImplementedError) as exc:  # pragma: no cover - 平台相关
        pytest.skip(f"symlinks unavailable on this host: {exc}")


# ── 向量 1：``../`` 路径穿越 ────────────────────────────────────────────


@pytest.mark.parametrize(
    "attempt",
    ["../host-secret.txt", "./../host-secret.txt", "nested/../../host-secret.txt"],
)
async def test_dotdot_traversal_cannot_read_outside_the_workspace(workspace: Path, attempt: str) -> None:
    """``../`` 变体一律被围栏拒绝，且拒绝回执里**不含**宿主文件内容。"""
    result = await file_read(path=attempt)

    assert result.startswith("Error:"), result
    assert "escapes current workspace" in result, result
    assert _SECRET_MARKER not in result


async def test_dotdot_traversal_cannot_write_outside_the_workspace(workspace: Path) -> None:
    """写侧同样围栏；且真正落盘发生在前置校验之前就必须被挡住（断言文件不存在）。"""
    target = workspace.parent / "escaped.txt"
    result = await file_write(path="../escaped.txt", content="pwned")

    assert result.startswith("Error:"), result
    assert not target.exists(), "越界写入真的落盘了"


# ── 向量 2：绝对路径逃逸 ────────────────────────────────────────────────


async def test_absolute_path_outside_the_workspace_is_refused(workspace: Path, tmp_path: Path) -> None:
    """绝对路径不是「绕过围栏的通道」：落在工作区外一样拒（读写两侧）。"""
    outside = tmp_path / "outside.txt"
    outside.write_text("HOST-ONLY", encoding="utf-8")

    read = await file_read(path=str(outside))
    write = await file_write(path=str(tmp_path / "planted.txt"), content="pwned")

    assert read.startswith("Error:") and "escapes current workspace" in read, read
    assert "HOST-ONLY" not in read
    assert write.startswith("Error:"), write
    assert not (tmp_path / "planted.txt").exists()


def test_absolute_path_to_a_system_credential_file_is_refused_by_the_deny_table(workspace: Path) -> None:
    """系统凭证文件的写 deny 与围栏**各自独立**生效：围栏之外还有一层具名拒绝。

    ``/etc/passwd`` 在本机解析出的绝对路径必须命中 deny 表——这条与「路径在工作区外」是两条
    不同的判据（前者防误伤系统文件，后者防越界）。
    """
    reason = check_write_denied("/etc/passwd")

    assert reason is not None, "写 /etc/passwd 未被拒绝"
    assert "protected" in reason


# ── 向量 3：符号链接指向宿主 ────────────────────────────────────────────


async def test_symlink_pointing_outside_the_workspace_is_fenced(workspace: Path) -> None:
    """工作区内的符号链接不得成为「合法相对路径」的通行证（读、写、内核读三个入口都判）。"""
    link_dir = workspace / "link-to-host"
    _symlink_or_skip(link_dir, workspace.parent)
    link_file = workspace / "host-secret-link.txt"
    _symlink_or_skip(link_file, workspace.parent / "host-secret.txt")

    read_via_dir = await file_read(path="link-to-host/host-secret.txt")
    read_via_file = await file_read(path="host-secret-link.txt")
    write_via_dir = await file_write(path="link-to-host/planted.txt", content="pwned")

    assert read_via_dir.startswith("Error:") and _SECRET_MARKER not in read_via_dir, read_via_dir
    assert read_via_file.startswith("Error:") and _SECRET_MARKER not in read_via_file, read_via_file
    assert write_via_dir.startswith("Error:"), write_via_dir
    assert not (workspace.parent / "planted.txt").exists()
    # 底层「解析后安全打开」内核是另一条独立通道（技能包 / 资源读取走它），同样拒。
    with pytest.raises(WorkspacePathError):
        read_bytes_under_root(workspace, str(link_file))


def test_symlink_named_like_a_credential_does_not_bypass_the_read_deny(workspace: Path) -> None:
    """deny 判据作用在**解析后**的路径上：把 ``.env`` 换成链接不改变「不许读」。"""
    fake_env = workspace / ".env"
    fake_env.write_text("OPENAI_API_KEY=" + _ENV_SECRET_MARKER, encoding="utf-8")
    link = workspace / "harmless.txt"
    _symlink_or_skip(link, fake_env)

    assert check_read_denied(".env") is not None
    assert check_read_denied(str(link)) is not None


# ── 向量 4：读宿主敏感文件 ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "target",
    [
        ".env",
        ".env.production",
        ".envrc",
        ".heagent/runs/run-1.json",
    ],
)
async def test_sensitive_host_files_cannot_be_read_into_context(workspace: Path, target: str) -> None:
    """凭证类文件与内部运行状态不得进模型上下文（``file_read`` 是主要入口）。"""
    if not target.startswith(".heagent/"):
        # 内容写进工作区也无所谓：值在判据命中时根本不读盘。
        (workspace / target).write_text("TOKEN=" + _ENV_SECRET_MARKER, encoding="utf-8")

    result = await file_read(path=target)

    assert result.startswith("Error: Read denied"), result
    assert _ENV_SECRET_MARKER not in result


@pytest.mark.xfail(
    strict=True,
    reason=(
        "已知缺口（Story 67.8 登记，未修）：读侧 deny 只覆盖 .env 一族，"
        ".netrc / .git-credentials 这类同性质凭证载体在工作区内可被 file_read 读进上下文；"
        "写侧（~/.netrc 等精确路径）有对应 deny。修好后本条会 XPASS，届时删掉此标记"
    ),
)
async def test_workspace_credential_files_outside_the_env_family_are_denied(workspace: Path) -> None:
    """同一性质的文件名应当同口径被拒——写侧有 deny 而读侧没有，是对称破缺。"""
    (workspace / ".git-credentials").write_text("https://user:token@example.com", encoding="utf-8")

    result = await file_read(path=".git-credentials")

    assert result.startswith("Error: Read denied"), result


def test_internal_runtime_state_is_denied_even_though_it_is_inside_the_workspace(workspace: Path) -> None:
    """``.heagent/`` 在**工作区之内**，所以只靠围栏挡不住——它靠内部状态 deny 单独挡。"""
    state_dir = workspace / ".heagent" / "runs"
    state_dir.mkdir(parents=True)
    (state_dir / "leak.json").write_text(_SECRET_MARKER, encoding="utf-8")

    reason = check_read_denied(str(state_dir / "leak.json"))

    assert reason is not None
    assert "internal HeAgent state" in reason


# ── 向量 5：环境变量泄漏 ────────────────────────────────────────────────


def test_scrub_strips_secret_suffixes_and_keeps_everything_else() -> None:
    """纯函数口径：按键名后缀剥离，**保留**其余变量（否则子进程连 PATH 都没有）。"""
    host_env = {
        "OPENAI_API_KEY": "sk-1",
        "HEAGENT_TEST_API_KEYS": "k1,k2",
        "GITHUB_TOKEN": "ghp_1",
        "DB_PASSWORD": "hunter2",
        "SSH_PRIVATE_KEY": "-----BEGIN",
        "SOME_CREDENTIALS": "creds",
        "PATH": "/usr/bin",
        "LANG": "C.UTF-8",
    }

    scrubbed = scrub_sensitive_env(host_env)

    assert set(scrubbed) == {"PATH", "LANG"}
    assert not any(value in {"sk-1", "hunter2"} for value in scrubbed.values())


def test_scrub_allowlist_keeps_only_the_explicitly_named_variable() -> None:
    """allowlist 是**豁免**而不是关闭：只放行点名的那一个，其余敏感后缀照旧剥离。"""
    host_env = {"OPENAI_API_KEY": "sk-1", "GITHUB_TOKEN": "ghp_1"}

    assert scrub_sensitive_env(host_env, allowlist=["openai_api_key"]) == {"OPENAI_API_KEY": "sk-1"}


async def test_child_process_does_not_inherit_a_sensitive_variable(monkeypatch: pytest.MonkeyPatch) -> None:
    """真实 spawn 的子进程读不到敏感变量——纯函数断言不足以证明 spawn 路径用上了它。

    正面控制：同一命令里放一个普通变量，它必须继承下来；否则「读不到」也可能只是 env 没传。
    """
    monkeypatch.setenv("HEAGENT_ESCAPE_API_KEY", _ENV_SECRET_MARKER)
    monkeypatch.setenv("HEAGENT_ESCAPE_PLAIN", "plain-marker")
    probe = (
        "import os;"
        "print('secret=' + os.environ.get('HEAGENT_ESCAPE_API_KEY', '<absent>'));"
        "print('plain=' + os.environ.get('HEAGENT_ESCAPE_PLAIN', '<absent>'))"
    )

    result = await _run_subprocess_exec([sys.executable, "-c", probe], timeout=60)

    assert "exit_code=0" in result, result
    assert "secret=<absent>" in result, result
    assert _ENV_SECRET_MARKER not in result
    assert "plain=plain-marker" in result, "正面控制失败：子进程根本没继承环境"


def test_container_argv_forwards_no_host_environment(tmp_path: Path) -> None:
    """容器档的 env 隔离落在 argv 形状上：``docker run`` 不带 ``--env``/``-e``。

    这是**唯一**能证明「容器内看不到宿主环境变量」的静态判据（运行期判据见
    ``tests/test_sandbox_docker_integration.py``）；顺带钉住硬化旗标与「只挂工作区」。
    """
    argv = build_run_argv(
        docker_path="docker",
        image=_IMAGE,
        network="none",
        name="probe",
        workspace=tmp_path,
        command="true",
    )

    assert "--env" not in argv and "-e" not in argv
    assert not any(part.startswith("HEAGENT_") for part in argv)
    assert argv.count("-v") == 1
    assert argv[argv.index("-v") + 1] == f"{tmp_path.as_posix()}:/workspace"
    # 硬化旗标与命令沙箱、MCP stdio 容器同源（弱化任何一处都会让容器档退回普通进程）。
    assert "--cap-drop=ALL" in argv
    assert "no-new-privileges" in argv
    assert argv[argv.index("--user") + 1] == "sandbox"


def test_container_tier_reports_network_isolation_only_when_it_is_real() -> None:
    """``isolates_network()`` 按**实际能力**回答：配了 bridge 就不能宣称已隔离。"""
    assert DockerRunner(network="none").isolates_network() is True
    assert DockerRunner(network="bridge").isolates_network() is False


# ── 向量 6 / 7：容器内的挂载与 PID 探测（需要 docker daemon） ──────────────


def _docker_unavailable_reason() -> str | None:
    """容器档可用性：``None`` = 可用，否则返回 skip 原因（惰性求值，默认门不付代价）。"""
    if shutil.which("docker") is None:
        return "docker CLI unavailable"
    try:
        probe = subprocess.run(  # noqa: S603 - 固定参数列表，不经命令解释器
            ["docker", "version", "--format", "{{.Server.Version}}"],
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover - 环境相关
        return f"docker daemon unreachable ({type(exc).__name__})"
    if probe.returncode != 0:
        return "docker daemon unreachable"
    try:
        image = subprocess.run(  # noqa: S603 - 固定参数列表，不经命令解释器
            ["docker", "image", "inspect", _IMAGE],
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:  # pragma: no cover - 环境相关
        return f"docker image probe failed ({type(exc).__name__})"
    if image.returncode != 0:
        return f"image {_IMAGE} missing (build it via tests/test_sandbox_docker_integration.py)"
    return None


@pytest.fixture()
def container_runner() -> Any:
    """容器档 runner；daemon 或镜像缺席时 skip 并说明原因（默认门不跑这些用例）。"""
    reason = _docker_unavailable_reason()
    if reason is not None:
        pytest.skip(f"container sandbox unavailable: {reason}")
    return DockerRunner(image=_IMAGE)


@pytest.mark.integration
async def test_container_cannot_reach_host_files_outside_the_mount(container_runner: Any, tmp_path: Path) -> None:
    """挂载面逃逸探测：``/workspace/..`` 与宿主绝对路径都读不到宿主同级文件。"""
    from heagent.tools.sandbox import bind_sandbox_workspace

    host_dir = tmp_path / "workspace"
    host_dir.mkdir()
    sibling = tmp_path / "host-only-secret.txt"
    sibling.write_text(_SECRET_MARKER, encoding="utf-8")

    with bind_sandbox_workspace(host_dir):
        result = await container_runner.run(
            f"cat /workspace/../host-only-secret.txt 2>&1; cat {sibling.as_posix()} 2>&1; echo PROBE-DONE",
            timeout=120,
        )

    assert "exit_code=" in result, result
    assert "PROBE-DONE" in result, f"probe did not run to completion: {result[:300]}"
    assert _SECRET_MARKER not in result, f"宿主同级文件在容器内可读: {result[:300]}"
    assert "No such file" in result or "cannot open" in result, result


@pytest.mark.integration
async def test_container_mount_table_exposes_no_second_host_path(container_runner: Any, tmp_path: Path) -> None:
    """挂载表里宿主路径只应作为 ``/workspace`` 的源出现，不该有第二个把宿主搬进容器的挂载。"""
    from heagent.tools.sandbox import bind_sandbox_workspace

    host_dir = tmp_path / "workspace"
    host_dir.mkdir()

    with bind_sandbox_workspace(host_dir):
        result = await container_runner.run(
            f"cat /proc/mounts | grep -F '{tmp_path.as_posix()}' | grep -v ' /workspace ' | wc -l",
            timeout=120,
        )

    assert "exit_code=0" in result, result
    assert "0" in result.split("stdout:")[-1], f"宿主路径出现在 /workspace 之外的挂载点: {result[:300]}"


@pytest.mark.integration
async def test_container_pid_namespace_hides_the_host(container_runner: Any) -> None:
    """PID 探测：容器内看不到宿主进程（用宿主自己的 pid 做判据），且 pid 1 不是宿主 init。"""
    host_pid = os.getpid()
    if host_pid <= 200:  # pragma: no cover - 只在 pid 很小的环境生效
        pytest.skip("host pid is too small to be a meaningful probe")

    result = await container_runner.run(
        f"cat /proc/1/comm; test -e /proc/{host_pid} && echo HOST-PID-VISIBLE || echo HOST-PID-HIDDEN",
        timeout=120,
    )

    stdout = result.split("stdout:")[-1]
    assert "HOST-PID-HIDDEN" in stdout, f"容器内能看到宿主 pid {host_pid}: {result[:300]}"
    assert "HOST-PID-VISIBLE" not in stdout
    first_line = stdout.strip().splitlines()[0].strip()
    assert first_line not in {"systemd", "init"}, f"容器 pid 1 是宿主 init（{first_line}）"
