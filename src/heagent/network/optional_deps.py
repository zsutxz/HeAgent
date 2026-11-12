"""可选依赖的延迟导入辅助（HTTP / WS 两个宿主共用）。

``network/`` 是传输层，不能假定 HTTP 栈一定装好（基础安装只含 MCP 等必需依赖）。
本模块是 ``http_server`` 与 ``ws_host`` 共享这一辅助的唯一落点：此前 ``ws_host`` 直接取
``http_server`` 的私有名 ``_require_module``，同层传输模块的私有跨模块依赖无契约钉住。

monkeypatch 缝：``http_server`` 以 ``_require_module`` 别名导入 :func:`require_module`，
测试 patch ``heagent.network.http_server._require_module`` 的既有缝保持有效。
"""

from __future__ import annotations

import importlib
from typing import Any


class HttpDependencyError(RuntimeError):
    """缺少可选 HTTP 依赖（``heagent[http]``）。"""


def require_module(name: str) -> Any:
    """延迟导入可选依赖模块；缺失时给出可诊断的安装提示。

    只有「真的要提供 HTTP/WS 服务」的路径才走到这里，因此把导入失败收敛成一条安装指引
    而不是 ImportError 栈。
    """
    try:
        return importlib.import_module(name)
    except ImportError as exc:  # pragma: no cover - 依赖齐全时不会触发（CI 装 http extra）
        raise HttpDependencyError(
            f"the HTTP entry point requires optional dependencies (missing {name!r}); "
            "install them with: pip install 'heagent[http]'"
        ) from exc


__all__ = ["HttpDependencyError", "require_module"]
