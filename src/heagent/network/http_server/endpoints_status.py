"""进程状态聚合端点：``GET /api/status``（只读）。

网络层只认**注入的状态来源**（:class:`StatusSource`）：它不认识运行服务、WS 中枢、任务注册表，
也不扫盘、不采样、不读配置——所有数值都由入口层填进 ``StatusResponse`` 后交进来。因此这条端点
与 ``/api/tasks`` 同构：一次内存读取 + 定长模型序列化。

注入方抛任何异常都收敛为 500 + 固定文案（诊断只进服务端日志，带 ``http event=status_failed``）：
状态是辅助信息，它的失败不该变成内部细节（异常类名 / traceback）的出口。

装配口径与 ``/api/tasks`` 一致：来源为 ``None`` 时路由**不注册**（客户端拿 404 ``not_found``），
而不是「注册了但恒 500」。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Protocol

from heagent.network.http_protocol import HttpErrorCode, StatusResponse
from heagent.pub.safe_logging import safe_log

from .pipeline import _json_error

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

logger = logging.getLogger("heagent.network.http_server")

__all__ = ["StatusSource"]


class StatusSource(Protocol):
    """注入的状态来源（**同步**：只读内存计数，端点因此不 ``await``、不做磁盘扫描）。"""

    def status(self) -> StatusResponse:
        """取进程状态的只读快照。

        同步实现是刻意的：计数本来就在内存里，端点因此不必 ``await``；实现方若在这里做 I/O
        会直接卡住 HTTP 事件循环。
        """
        ...


def _build_status_endpoint(responses: Any, source: StatusSource) -> Callable[[Any], Awaitable[Any]]:
    """构造状态端点闭包（异常一律收敛为 500 + 固定文案）。"""

    async def get_status(request: Any) -> Any:  # noqa: ARG001 - 端点的固定签名
        try:
            # 序列化也在隔离内：注入方交出不合契约的对象时同样走这条固定文案，而不是穿透到
            # 全局异常处理（那会丢掉 ``event=status_failed`` 这条诊断）。
            payload = source.status().model_dump(mode="json")
        except Exception:
            safe_log(logger, logging.ERROR, "http event=status_failed", exc_info=True)
            return _json_error(responses, HttpErrorCode.SERVER_ERROR, "request failed", status_code=500)
        return responses.JSONResponse(payload)

    return get_status
