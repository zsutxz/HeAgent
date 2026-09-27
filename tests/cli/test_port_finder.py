"""Tests for port finder utility."""

from __future__ import annotations

import socket
from unittest.mock import patch

import pytest

from heagent.cli.port_finder import find_available_port


class TestFindAvailablePort:
    def test_returns_preferred_port_when_available(self) -> None:
        """首选端口可用时直接返回。"""
        # 使用一个极不可能被占用的高位端口
        port = find_available_port(55000)
        assert port == 55000

    def test_finds_next_available_port_when_preferred_is_in_use(self) -> None:
        """首选端口被占用时，尝试后续端口。"""
        # 先占用一个端口
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 55001))
            # 尝试获取从 55001 开始的可用端口
            port = find_available_port(55001, max_attempts=10)
            # 应该返回 55002（55001 被占用）
            assert port == 55002

    def test_respects_max_attempts(self) -> None:
        """尊重 max_attempts 参数。"""
        # 占用连续的多个端口
        sockets = []
        try:
            for offset in range(5):
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.bind(("127.0.0.1", 55010 + offset))
                sockets.append(s)

            # 尝试最多 3 次，应该失败（前 3 个都被占用）
            with pytest.raises(RuntimeError, match="No available port found"):
                find_available_port(55010, max_attempts=3)

            # 尝试最多 10 次，应该成功（第 6 个端口可用）
            port = find_available_port(55010, max_attempts=10)
            assert port == 55015
        finally:
            for s in sockets:
                s.close()

    def test_raises_runtime_error_when_no_port_available(self) -> None:
        """所有尝试的端口都被占用时抛出 RuntimeError。"""
        # 占用连续的 15 个端口
        sockets = []
        try:
            for offset in range(15):
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.bind(("127.0.0.1", 55020 + offset))
                sockets.append(s)

            # 尝试最多 10 次，应该失败
            with pytest.raises(RuntimeError) as exc_info:
                find_available_port(55020, max_attempts=10)

            assert "No available port found in range 55020-55029" in str(exc_info.value)
            assert "Please specify a different port" in str(exc_info.value)
        finally:
            for s in sockets:
                s.close()

    def test_works_with_different_hosts(self) -> None:
        """支持不同的绑定地址。"""
        # 测试 127.0.0.1
        port1 = find_available_port(55030, host="127.0.0.1")
        assert port1 >= 55030

        # 测试 0.0.0.0（需要权限，可能失败）
        try:
            port2 = find_available_port(55040, host="0.0.0.0")
            assert port2 >= 55040
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
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 55060))

            port = find_available_port(55060, max_attempts=10)
            assert port == 55061

            # 验证日志
            assert any("Port 55060 was in use" in record.message for record in caplog.records)
            assert any("using port 55061 instead" in record.message for record in caplog.records)
