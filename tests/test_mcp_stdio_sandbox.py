"""MCP stdio 进容器（Epic 53 期二 D53-1 / Story 53-5）的判据。

覆盖：``docker run`` argv 形状（旗标顺序/硬化/env 透传/挂载）、容器名指纹、
显性降级（后端不可用 ⇒ 宿主执行 + 每次 WARNING）、探测抛错、TTL 复用、
零回归（无 spec 时参数逐字节不变）、manager 与 CLI 装配接线。
"""

from __future__ import annotations

import logging
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING

from heagent.cli.console import _stdio_sandbox_spec
from heagent.config import Settings
from heagent.tools.mcp import MCPClientManager, MCPConfig, StdioServerConfig, StdioSandboxSpec
from heagent.tools.mcp.stdio_sandbox import build_run_argv, container_name, stdio_params

if TYPE_CHECKING:
    import pytest


def _spec(**overrides: object) -> StdioSandboxSpec:
    init: dict[str, object] = {"image": "heagent-sandbox:3.11", "workspace": None}
    init.update(overrides)
    return StdioSandboxSpec(**init)  # type: ignore[arg-type]


def _cfg(**overrides: object) -> StdioServerConfig:
    init: dict[str, object] = {"command": "python", "args": ["-m", "demo_server"]}
    init.update(overrides)
    return StdioServerConfig(**init)  # type: ignore[arg-type]


class TestArgvShape:
    def test_hardening_flags_and_image_last(self) -> None:
        argv = build_run_argv(_spec(), _cfg())

        assert argv[0] == "docker"
        assert argv[1:3] == ["run", "-i"]
        assert "--rm" in argv
        assert "--pull=never" in argv
        assert argv[argv.index("--network") + 1] == "none"
        assert "--cap-drop=ALL" in argv
        assert argv[argv.index("--security-opt") + 1] == "no-new-privileges"
        assert argv[argv.index("--user") + 1] == "sandbox"
        assert argv[argv.index("--label") + 1] == "heagent.mcp=stdio"
        # 镜像与容器内命令的顺序：image 之后是 server command + args，绝不塞 sh -c
        image_at = argv.index("heagent-sandbox:3.11")
        assert argv[image_at + 1 :] == ["python", "-m", "demo_server"]
        assert "sh" not in argv

    def test_env_flags_only_for_declared_keys(self) -> None:
        cfg = _cfg(env={"ZED_TOKEN": "z", "ALPHA_KEY": "a"})
        argv = build_run_argv(_spec(), cfg)

        env_pairs = [(argv[i], argv[i + 1]) for i, item in enumerate(argv) if item == "-e"]
        assert env_pairs == [("-e", "ALPHA_KEY"), ("-e", "ZED_TOKEN")]  # 排序 + 不带值
        assert all("=" not in value for _, value in env_pairs)  # 值不进 argv（ps 不可见）
        assert "z" not in argv and "a" not in argv

    def test_limits_precede_image(self) -> None:
        argv = build_run_argv(_spec(memory_limit_mb=256, pids_limit=64), _cfg())

        assert argv[argv.index("--memory") + 1] == "256m"
        assert argv[argv.index("--pids-limit") + 1] == "64"
        assert argv.index("--memory") < argv.index("heagent-sandbox:3.11")
        assert argv.index("--pids-limit") < argv.index("heagent-sandbox:3.11")

    def test_zero_limits_emit_no_flag(self) -> None:
        argv = build_run_argv(_spec(), _cfg())

        assert "--memory" not in argv
        assert "--pids-limit" not in argv

    def test_workspace_mount_and_bridge_network(self) -> None:
        argv = build_run_argv(_spec(network="bridge", workspace="/srv/project"), _cfg())

        assert argv[argv.index("-v") + 1] == "/srv/project:/workspace"
        assert argv[argv.index("-w") + 1] == "/workspace"
        assert argv[argv.index("--network") + 1] == "bridge"

    def test_container_name_is_stable_per_command_and_unique_per_launch(self) -> None:
        cfg = _cfg()
        first, second = container_name(cfg), container_name(cfg)

        assert first.startswith("heagent-mcp-")
        assert first != second  # 随机后缀防同名冲突
        assert first.split("-")[2] == second.split("-")[2]  # 命令指纹一致

    def test_container_name_differs_for_different_args(self) -> None:
        left = container_name(_cfg(args=["-m", "a"]))
        right = container_name(_cfg(args=["-m", "b"]))

        assert left.split("-")[2] != right.split("-")[2]


class TestStdioParams:
    def test_container_wrapping_when_available(self) -> None:
        spec = _spec(docker_path="/usr/bin/docker")
        spec._probe_fn = lambda _path: True  # type: ignore[assignment]

        params = stdio_params(_cfg(env={"TOKEN": "t"}), spec)

        assert params.command == "/usr/bin/docker"
        assert params.args[:2] == ["run", "-i"]
        image_at = params.args.index("heagent-sandbox:3.11")
        assert params.args[image_at + 1 :] == ["python", "-m", "demo_server"]
        # env 原样保留 ⇒ `docker run -e TOKEN` 能从 CLI 进程 env 取到值
        assert params.env == {"TOKEN": "t"}

    def test_no_spec_keeps_host_params(self) -> None:
        cfg = _cfg(env={"A": "1"})

        params = stdio_params(cfg, None)

        assert (params.command, params.args, params.env) == ("python", ["-m", "demo_server"], {"A": "1"})

    def test_degradation_runs_on_host_with_warning_every_time(self, caplog: pytest.LogCaptureFixture) -> None:
        spec = _spec()
        calls: list[str] = []

        def _down(path: str) -> bool:
            calls.append(path)
            return False

        spec._probe_fn = _down  # type: ignore[assignment]
        with caplog.at_level(logging.WARNING, logger="heagent.tools.mcp.stdio_sandbox"):
            first = stdio_params(_cfg(), spec)
            second = stdio_params(_cfg(), spec)

        assert first.command == "python" and second.command == "python"
        warnings = [rec for rec in caplog.records if "explicit degradation" in rec.getMessage()]
        assert len(warnings) == 2  # 每次连接都留痕，即使探测结果被 TTL 缓存
        assert len(calls) == 1  # 探测本身按 TTL 复用

    def test_probe_failure_degrades_to_host(self, caplog: pytest.LogCaptureFixture) -> None:
        spec = _spec()

        def _boom(_path: str) -> bool:
            raise RuntimeError("docker state unreadable")

        spec._probe_fn = _boom  # type: ignore[assignment]
        with caplog.at_level(logging.WARNING, logger="heagent.tools.mcp.stdio_sandbox"):
            params = stdio_params(_cfg(), spec)

        assert params.command == "python"
        assert any("probe failed" in rec.getMessage() for rec in caplog.records)


class TestManagerWiring:
    def test_default_opener_binds_spec(self) -> None:
        spec = _spec()
        manager = MCPClientManager(
            MCPConfig(servers={"demo": _cfg()}),
            stdio_sandbox=spec,
        )

        opener = manager._resolve_transport_opener()

        assert isinstance(opener, partial)
        assert opener.keywords == {"stdio_sandbox": spec}

    def test_injected_opener_wins_over_spec(self) -> None:
        spec = _spec()

        def _fake(_cfg: object) -> object:  # pragma: no cover - 只校验选择逻辑
            return None

        manager = MCPClientManager(MCPConfig(servers={"demo": _cfg()}), transport_opener=_fake, stdio_sandbox=spec)

        assert (manager._transport_opener or manager._resolve_transport_opener()) is _fake

    def test_no_spec_keeps_sdk_opener(self) -> None:
        from heagent.tools.mcp.client import default_transport_opener

        manager = MCPClientManager(MCPConfig(servers={"demo": _cfg()}))

        assert manager._resolve_transport_opener() is default_transport_opener


class TestCliSpec:
    def test_docker_backend_builds_spec(self) -> None:
        settings = Settings(_env_file=None, sandbox_backend="docker", sandbox_network=True, sandbox_memory_limit_mb=512)

        spec = _stdio_sandbox_spec(settings)

        assert isinstance(spec, StdioSandboxSpec)
        assert spec.image == settings.sandbox_docker_image
        assert spec.network == "bridge"
        assert spec.memory_limit_mb == 512
        assert spec.workspace == str(Path.cwd())

    def test_other_backends_disable_container_wrapping(self) -> None:
        for backend in ("passthrough", "firejail", "auto", "winjob"):
            assert _stdio_sandbox_spec(Settings(_env_file=None, sandbox_backend=backend)) is None
