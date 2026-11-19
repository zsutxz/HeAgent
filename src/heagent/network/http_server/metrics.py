"""请求级计数与延迟（``GET /api/status`` 的请求观测来源）。

只做三件事：整数自增、一次有界 ``deque`` 追加、一次快照。**不做 I/O、不加锁、不格式化**——
它在每个请求的收尾路径上，任何多余的动作都会变成所有端点的固定开销。

延迟样本是有界的（:data:`LATENCY_WINDOW`）；``p50`` 是窗口内的中位数（样本少时就是真实值，样本
多时是近期值的近似）——状态面要的是量级判断，不是分位数库。

**流式响应不进延迟窗口**：SSE（``text/event-stream``）的耗时是连接寿命而不是请求延迟，一条运行期
订阅（可长达数分钟）会把 ``max`` 独占、把 ``p50`` 拉偏；这类请求只计入总数与错误码。
"""

from __future__ import annotations

import json
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

#: 延迟样本窗口（条）。256 条约几十 KB 的上界，够看「最近这批请求有多慢」。
LATENCY_WINDOW = 256

#: 只对非 2xx 的 JSON 错误信封做一次小体积解析（正常响应的 body 一律不看）。
_ERROR_BODY_LIMIT_BYTES = 1024

_STATUS_CLASSES = ("2xx", "3xx", "4xx", "5xx")


class RequestMetrics:
    """进程内的请求计数与延迟窗口（单实例由 app 持有，关停即消失）。"""

    def __init__(self) -> None:
        self._total = 0
        self._classes: dict[str, int] = dict.fromkeys(_STATUS_CLASSES, 0)
        self._error_codes: dict[str, int] = {}
        self._latencies: deque[float] = deque(maxlen=LATENCY_WINDOW)

    def record(self, *, status: int, elapsed_ms: float, error_code: str | None = None, streamed: bool = False) -> None:
        """记一条请求（热路径：整数自增 + 最多一次 append）。

        ``streamed`` = 流式响应（SSE）：只计总数与错误码，不进延迟窗口（见模块 docstring）。
        """
        self._total += 1
        bucket = f"{status // 100}xx" if status else ""
        if bucket in self._classes:  # 1xx / 0 等不落在四个对外分桶里：只计总数与延迟
            self._classes[bucket] += 1
        if not streamed:
            self._latencies.append(max(elapsed_ms, 0.0))
        if error_code:
            self._error_codes[error_code] = self._error_codes.get(error_code, 0) + 1

    @property
    def total(self) -> int:
        """已记录的请求总数。"""
        return self._total

    def error_codes(self) -> list[tuple[str, int]]:
        """稳定错误码频次（按次数降序、同次数按码名升序，保证输出稳定）。"""
        return sorted(self._error_codes.items(), key=lambda item: (-item[1], item[0]))

    def latency_p50_ms(self) -> float:
        """窗口内延迟中位数（毫秒）；无样本为 0。"""
        if not self._latencies:
            return 0.0
        ordered = sorted(self._latencies)
        return round(ordered[len(ordered) // 2], 3)

    def latency_max_ms(self) -> float:
        """窗口内延迟最大值（毫秒）；无样本为 0。"""
        return round(max(self._latencies), 3) if self._latencies else 0.0

    def status_class(self, name: str) -> int:
        """某个状态码分桶（``2xx`` / ``3xx`` / ``4xx`` / ``5xx``）的计数。"""
        return self._classes.get(name, 0)


def error_code_from_body(body: bytes, raw_headers: Iterable[tuple[bytes, bytes]] | None) -> str | None:
    """从非 2xx 响应体里取 ``error.code``；不是 JSON 信封 / 太大 / 解析失败一律 ``None``。

    只在**非 2xx** 上调用（见 :class:`~heagent.network.http_server.middleware._AccessLogMiddleware`），
    且带体积上限：正常响应（SSE 流、静态资源、大 JSON）从不进这条路径。
    """
    if not body or len(body) > _ERROR_BODY_LIMIT_BYTES:
        return None
    content_type = ""
    for key, value in raw_headers or ():
        if bytes(key).lower() == b"content-type":
            content_type = bytes(value).decode("latin-1").lower()
            break
    if "json" not in content_type:
        return None
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return None
    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) and code else None


def is_event_stream(raw_headers: Iterable[tuple[bytes, bytes]] | None) -> bool:
    """响应头是否声明了 SSE（``text/event-stream``）——流式响应的耗时不是请求延迟。"""
    for key, value in raw_headers or ():
        if bytes(key).lower() == b"content-type":
            return bytes(value).decode("latin-1").lower().startswith("text/event-stream")
    return False


__all__ = ["LATENCY_WINDOW", "RequestMetrics", "error_code_from_body", "is_event_stream"]
