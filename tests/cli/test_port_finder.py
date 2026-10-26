"""Tests for port finder utility.

环境敏感性说明（Epic 57-2）：历史版本硬编码 55xxx 固定端口段，隐含假设「该段处于预期占用/空闲状态」。
本机多开实例端口顺延（a545613 起默认开启）或 Windows 排除端口区间（Hyper-V/WSL/Docker 保留段）覆盖该段时
前提即被破坏——epic-52 期 test_respects_max_attempts 因此稳定失败（环境复现）。现行版本统一经
`_reserve_block` 动态取口，不再依赖任何固定段。
"""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from heagent.cli.port_finder import find_available_port


def _bind_block(base: int, count: int) -> list[socket.socket] | None:
    """尝试连续绑定 [base, base+count)；任一失败则清理已打开的 socket 并返回 None。"""
    sockets: list[socket.socket] = []
    for offset in range(count):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            s.bind(("127.0.0.1", base + offset))
        except OSError:
            s.close()
            for opened in sockets:
                opened.close()
            return None
        sockets.append(s)
    return sockets


def _reserve_block(count: int, tries: int = 20) -> tuple[int, list[socket.socket]]:
    """占住 count 个连续可用端口，返回 (base, sockets)。

    以 OS 临时口（bind 0）为起点探测，碰撞（被并发抢占或落入排除区间）即换起点重试，
    有界 tries 次后显性失败——测试前提由测试自身建立，不依赖环境端口状态。
    """
    for _ in range(tries):
        probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        probe.bind(("127.0.0.1", 0))
        base = probe.getsockname()[1]
        probe.close()
        if base + count - 1 > 65535:
            continue
        sockets = _bind_block(base, count)
        if sockets is not None:
            return base, sockets
    raise RuntimeError(f"could not reserve {count} consecutive free ports after {tries} tries")


class TestFindAvailablePort:
    def test_returns_preferred_port_when_available(self) -> None:
        """首选端口可用时直接返回。"""
        base, (holder,) = _reserve_block(1)
        holder.close()
        assert find_available_port(base) == base

    def test_finds_next_available_port_when_preferred_is_in_use(self) -> None:
        """首选端口被占用时，尝试后续端口。"""
        base, (holder, nxt) = _reserve_block(2)
        nxt.close()
        try:
            port = find_available_port(base, max_attempts=10)
            assert port == base + 1
        finally:
            holder.close()

    def test_respects_max_attempts(self) -> None:
        """尊重 max_attempts 参数。"""
        base, sockets = _reserve_block(6)
        sockets[-1].close()  # 释放第 6 个端口：前 5 个占用、第 6 个可用
        try:
            # 前 3 个都被占用：max_attempts=3 应失败
            with pytest.raises(RuntimeError, match="No available port found"):
                find_available_port(base, max_attempts=3)

            # 第 6 个端口可用：max_attempts=10 应成功
            assert find_available_port(base, max_attempts=10) == base + 5
        finally:
            for s in sockets:
                s.close()

    def test_raises_runtime_error_when_no_port_available(self) -> None:
        """所有尝试的端口都被占用时抛出 RuntimeError。"""
        base, sockets = _reserve_block(15)
        try:
            with pytest.raises(RuntimeError) as exc_info:
                find_available_port(base, max_attempts=10)

            assert f"No available port found in range {base}-{base + 9}" in str(exc_info.value)
            assert "Please specify a different port" in str(exc_info.value)
        finally:
            for s in sockets:
                s.close()

    def test_works_with_different_hosts(self) -> None:
        """支持不同的绑定地址。"""
        base, (holder,) = _reserve_block(1)
        holder.close()
        assert find_available_port(base, host="127.0.0.1") == base

        # 0.0.0.0（需要权限，可能失败）
        base2, (holder2,) = _reserve_block(1)
        holder2.close()
        try:
            assert find_available_port(base2, host="0.0.0.0") == base2
        except (OSError, PermissionError):
            # 某些环境可能不允许绑定 0.0.0.0
            pytest.skip("Cannot bind to 0.0.0.0 in this environment")

    def test_handles_os_errors_gracefully(self) -> None:
        """处理 OSError（如权限错误）时继续尝试下一个端口。"""
        with patch("socket.socket") as mock_socket:
            # 前 2 次尝试抛出 OSError，第 3 次成功
            mock_socket.return_value.__enter__.return_value.bind.side_effect = [
                OSError("Permission denied"),
                OSError("Address already in use"),
                None,  # 成功
            ]

            port = find_available_port(55050, max_attempts=5)
            assert port == 55052  # 前两次失败，第三次成功

    def test_logs_when_port_changes(self, caplog) -> None:
        """端口发生变化时记录日志。"""
        import logging

        caplog.set_level(logging.INFO, logger="heagent.cli.port_finder")

        # 占用首选端口
        base, (holder, nxt) = _reserve_block(2)
        nxt.close()
        try:
            port = find_available_port(base, max_attempts=10)
            assert port == base + 1

            # 验证日志
            assert any(f"Port {base} was in use" in record.message for record in caplog.records)
            assert any(f"using port {base + 1} instead" in record.message for record in caplog.records)
        finally:
            holder.close()
