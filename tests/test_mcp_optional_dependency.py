"""A63：缺少 ``mcp`` 可选依赖时的安装诊断判据（Story 67.9 把 SDK 移出核心依赖后的缺口）。

判据三件事：
- SDK 不可用时，取用通道（``import_mcp`` / ``require_sdk``）抛 :class:`McpSdkMissingError`，
  消息同时带**功能名**与一条可执行安装命令；
- ``import heagent`` 与 ``import heagent.tools.mcp`` 在 SDK 缺席时照常（可选依赖不得炸入口）；
- ``McpManager`` 的连接路径 fail loud（早于连接尝试给出安装提示，而非连接失败）。

模拟方式：``importlib.import_module`` 与内建 ``__import__`` 在调用期被替换，只拦 ``mcp`` 前缀，
其余导入转发原实现。``import heagent`` 一条走**子进程**——进程内早已把 ``mcp`` 装进 ``sys.modules``，
只有干净解释器才能证明「缺依赖也能导入」。
"""

from __future__ import annotations

import importlib
import subprocess
import sys
from pathlib import Path

import pytest

from heagent.pub.exceptions import McpSdkMissingError
from heagent.tools.mcp.sdk import INSTALL_HINT, import_mcp, mcp_types, require_sdk


def _src_root() -> Path:
    """``src/`` 目录（子进程靠 PYTHONPATH 找到未安装的源码树）。"""
    return Path(__file__).resolve().parents[1] / "src"


def _block_mcp(monkeypatch: pytest.MonkeyPatch) -> None:
    """让 ``mcp`` 及其子模块的所有导入抛 ImportError（其余转发原实现）。"""
    real_import_module = importlib.import_module
    real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __builtins__.__import__

    def fake_import_module(name: str, package: str | None = None) -> object:
        if name == "mcp" or name.startswith("mcp."):
            raise ImportError(f"simulated missing dependency: {name}")
        return real_import_module(name, package) if package is not None else real_import_module(name)

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "mcp" or name.startswith("mcp."):
            raise ImportError(f"simulated missing dependency: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake_import_module)
    monkeypatch.setattr("builtins.__import__", fake_import)


def test_import_mcp_raises_with_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    """缺 SDK 时取用通道抛专用异常，消息含功能名与安装命令。"""
    _block_mcp(monkeypatch)

    with pytest.raises(McpSdkMissingError) as excinfo:
        import_mcp("mcp")

    message = str(excinfo.value)
    assert "MCP 支持" in message
    assert INSTALL_HINT in message
    assert INSTALL_HINT == 'pip install "heagent[mcp]"'


def test_mcp_types_raises_with_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    """``mcp_types`` 走同一通道：缺 SDK 同样抛专用异常，而不是裸 ImportError。"""
    _block_mcp(monkeypatch)

    with pytest.raises(McpSdkMissingError) as excinfo:
        mcp_types("Tool")

    assert INSTALL_HINT in str(excinfo.value)


def test_require_sdk_fails_loud_at_construction(monkeypatch: pytest.MonkeyPatch) -> None:
    """构造期自检 ``require_sdk`` 立即抛（早于任何连接尝试），消息带调用方给的功能名。"""
    _block_mcp(monkeypatch)

    with pytest.raises(McpSdkMissingError) as excinfo:
        require_sdk("MCP 连接")

    message = str(excinfo.value)
    assert "MCP 连接" in message
    assert INSTALL_HINT in message


def test_manager_construction_fails_loud_without_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    """工具面（MCP manager）构造期即报缺依赖——用户拿到安装命令，而不是若干秒后的连接失败。"""
    from heagent.tools.mcp.config import MCPConfig
    from heagent.tools.mcp.manager import MCPClientManager

    _block_mcp(monkeypatch)

    with pytest.raises(McpSdkMissingError) as excinfo:
        MCPClientManager(MCPConfig())

    assert INSTALL_HINT in str(excinfo.value)


def test_import_heagent_without_mcp_sdk() -> None:
    """缺 SDK 时 ``import heagent`` 与 ``import heagent.tools.mcp`` 照常（可选依赖不炸入口）。"""
    code = """
import builtins

_real_import = builtins.__import__


def _blocked(name, *args, **kwargs):
    if name == "mcp" or name.startswith("mcp."):
        raise ImportError("simulated missing dependency: " + name)
    return _real_import(name, *args, **kwargs)


builtins.__import__ = _blocked
import heagent
import heagent.tools.mcp

assert heagent.__version__
print("IMPORT_OK")
"""
    completed = subprocess.run(  # noqa: S603 -- argv 是固定字面量 + 本进程解释器，无外部输入
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={"PYTHONUTF8": "1", "PYTHONPATH": str(_src_root())},
        timeout=120,
    )
    assert completed.returncode == 0, completed.stderr
    assert "IMPORT_OK" in completed.stdout
