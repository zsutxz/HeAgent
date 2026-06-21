"""Story 1.1 — MCP 依赖引入与 tools/mcp/ 骨架。

验证：
- mcp SDK 已安装且版本落 ``>=1.28,<2``（排除 v2 breaking alpha）；
- ``heagent.tools.mcp`` 包可作为命名空间导入（骨架就位）；
- DAG 守护：``tools/mcp/`` 下源文件禁止从 ``heagent.agent`` 导入。
"""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pytest

import heagent.tools.mcp


def test_mcp_sdk_installed_in_pinned_range() -> None:
    """mcp SDK 已安装且版本在 >=1.28,<2 窗口内。"""
    try:
        v = version("mcp")
    except PackageNotFoundError as exc:  # pragma: no cover - 仅缺依赖时触发
        pytest.fail(f"mcp SDK 未安装：{exc}")
    parts = v.split(".")
    assert (int(parts[0]), int(parts[1])) >= (1, 28), f"mcp 版本 {v} < 1.28"
    assert int(parts[0]) < 2, f"mcp 版本 {v} 不在 <2 窗口（排除 v2 breaking）"


def test_mcp_subpackage_importable() -> None:
    """tools.mcp 包可导入（骨架就位、DAG 合规可加载）。"""
    assert heagent.tools.mcp is not None
    assert hasattr(heagent.tools.mcp, "__path__")


def test_mcp_layer_has_no_agent_import() -> None:
    """DAG 守护：tools/mcp/ 下源文件禁止导入 heagent.agent。"""
    mcp_dir = Path(heagent.tools.mcp.__file__).resolve().parent
    offenders = [py.name for py in mcp_dir.glob("*.py") if "heagent.agent" in py.read_text(encoding="utf-8")]
    assert not offenders, f"违反 DAG（tools/ 层禁从 agent 导入）：{offenders}"
