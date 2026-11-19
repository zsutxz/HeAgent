"""包内静态资源白名单与读取（Story 62.1 自 ``network/http_server.py`` 拆出）。

``__all__`` 显式列出包内公开名：包级再导出（``__init__.py``）与 exception 快照
（``scripts/contract_snapshot.py``）都以「定义模块的 ``__all__``」为收录依据。
"""

from __future__ import annotations

from importlib import resources

__all__ = ["read_web_asset"]

# 静态资源所在包与**白名单**（路径 → 内容类型）。
#
# 用白名单而不是目录遍历：既挡掉 `../` 路径穿越，也保证「包内后来多出来的文件」不会因为
# 放在这里就被自动发布出去。新增页面资源必须同时改这张表（有测试钉住）。
_WEB_PACKAGE = "heagent.web"
_INDEX_ASSET = "index.html"
_WEB_ASSETS: dict[str, str] = {
    "index.html": "text/html; charset=utf-8",
    "app.js": "text/javascript; charset=utf-8",
    "panels.js": "text/javascript; charset=utf-8",
    "tasks.js": "text/javascript; charset=utf-8",
    "api-console.js": "text/javascript; charset=utf-8",
    "styles.css": "text/css; charset=utf-8",
}


def read_web_asset(name: str) -> bytes:
    """读取包内静态资源；``name`` 必须已在白名单内（否则 ``KeyError``）。

    ``importlib.resources.files("heagent.web")`` 是**唯一**的资源查找方式（AD-11）：它对
    ``wheel`` 安装与源码运行都成立，也不依赖 ``__file__`` 或开发机绝对路径。
    """
    if name not in _WEB_ASSETS:
        raise KeyError(name)
    return resources.files(_WEB_PACKAGE).joinpath(name).read_bytes()
