"""ASGI HTTP 传输层：静态资源、安全响应头与有界生命周期（Epic 49）。

2026-11-15（Story 62.1）自单文件拆为子包（config / assets / records / service / pipeline /
middleware / endpoints_run / endpoints_console / app / listener），公开 API 与导入面经本
``__init__`` 全量 ``X as X`` 再导出保持零变化；层序无环：config → assets/records → service →
pipeline → endpoints_* → middleware → app → listener。

**职责边界（AD-1）**：本包只做 HTTP 协议与生命周期——路由、安全响应头、包内静态资源、
listener 的 start/close。它**不**构造 Agent：任何 Agent 能力都由入口层（``cli/http.py``）以
注入对象的方式交进来。因此本包的导入面被刻意限制在：标准库、Pydantic、可选 ASGI 栈
（Starlette / Uvicorn，延迟导入）、``heagent.network.exposure``、``heagent.pub.safe_logging`` 与
同层协议模型。``tests/test_architecture_contracts.py`` 对此有可执行断言。

**可选依赖（AD-11）**：Starlette / Uvicorn 由 ``pyproject.toml`` 的 ``http`` extra 直接声明，
且**只在需要时才导入**——普通 CLI 用法、库用法与 ``gui`` / ``init`` / ``replay``
子命令都不应因为「存在这个模块」而拉起 ASGI 栈，更不该因为缺依赖而失败。缺依赖时抛
:class:`HttpDependencyError`（带 ``pip install 'heagent[http]'`` 诊断），由入口层转成可读的
命令错误。

**生命周期契约（AD-5）**：``start()`` 只在「listener 已绑定**且** ``/api/health`` 真的可服务」
后返回；绑定失败或就绪探测失败都抛 :class:`HttpStartupError`，且绝不打印「正在监听」。
``serve_forever()`` 是阻塞式服务循环（由入口层放进自己的任务里，异常向该任务的持有者传播）。
``close()`` 按「停止接收 → 关闭 listener → 有界等待」收尾，幂等且**不会无界等待**：
Uvicorn 的连接排空受 ``timeout_graceful_shutdown`` 约束，本包再加一层 ``wait_for`` 兜底。

**日志口径**：各子模块显式 ``logging.getLogger("heagent.network.http_server")``（catalog 先例，
对 ``__name__`` 惯例的有意偏离）——caplog 断言按父包名捕获，子模块拆分对日志名不可见。
"""

from heagent.network.http_protocol import HttpRunConflictError as HttpRunConflictError
from heagent.network.optional_deps import HttpDependencyError as HttpDependencyError

from .app import build_http_app as build_http_app
from .assets import _WEB_ASSETS as _WEB_ASSETS
from .assets import read_web_asset as read_web_asset
from .config import HttpServerConfig as HttpServerConfig
from .config import HttpStartupError as HttpStartupError
from .listener import HttpServer as HttpServer
from .pipeline import HttpRequestTooLargeError as HttpRequestTooLargeError
from .pipeline import _parse_last_event_id as _parse_last_event_id
from .records import RunEventPublisher as RunEventPublisher
from .records import _RunRecord as _RunRecord
from .service import HttpRunService as HttpRunService

__all__ = [
    "HttpDependencyError",
    "HttpRequestTooLargeError",
    "HttpRunConflictError",
    "HttpRunService",
    "HttpServer",
    "HttpServerConfig",
    "HttpStartupError",
    "RunEventPublisher",
    "build_http_app",
    "read_web_asset",
]
