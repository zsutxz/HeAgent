"""WS 对外模式的静态 token 认证（Epic 56 D3/D5）。

本模块是**纯逻辑面**：解析 ``Authorization`` 头、常量时间比较、按来源地址的失败限速。
不执行 I/O，不导入配置与运行栈——宿主（``ws_host``）在 accept **之前**调用，失败时自行
``close(1008)``（D3：未 accept 前关闭，不透出错误信封，也不告诉探测者 token 对不对）。

三条刻意的取舍：

- **常量时间比较**（:func:`hmac.compare_digest`）：认证是唯一一道对外防线，把它写成
  ``==`` 等于把 token 交给时序侧信道。
- **失败限速按来源地址滑窗**：对外 listener 上无限次尝试等于允许离线暴力枚举；限速只在
  「同一来源短时间内错太多次」时生效，超额后**不再做 token 比较**，仍回同一个 1008
  （不给探测者「被限速」与「token 错」的区分信号）。
- **条目有界**：来源地址可被伪造刷爆内存，因此保留上限 + 最旧淘汰；计数本身不是安全边界
  （伪造来源仍可绕过限速），它只挡住「同一 IP 的傻瓜式暴力尝试」。
"""

from __future__ import annotations

import hmac
import time
from collections import OrderedDict, deque
from collections.abc import Callable, Iterable, Mapping
from typing import Any

from heagent.network.ws_protocol import WS_CLOSE_POLICY

#: 认证失败的 close code：policy violation（D3 冻结值，与协议面单一来源同值）。
AUTH_CLOSE_CODE = WS_CLOSE_POLICY

#: 同一来源在窗口内允许的失败次数上限；达到即不再比较 token。
DEFAULT_MAX_FAILURES = 10
#: 限速窗口（秒）。
DEFAULT_WINDOW_SECONDS = 60.0
#: 同时跟踪的来源地址上限（超出淘汰最久未更新的条目）。
DEFAULT_MAX_SOURCES = 1024

#: :func:`make_authorizer` 的返回签名：``None`` = 通过，否则是拒绝原因（供日志）。
Authorizer = Callable[[Mapping[str, Any]], "str | None"]


def client_source(scope: Mapping[str, Any]) -> str:
    """连接的来源地址（限速键）。

    取 ASGI ``scope["client"]`` 的 host 部分；缺失或形态不符时回落 ``"unknown"``——
    限速键退化不会让认证失效（比较与拒绝仍照常执行）。
    """
    client = scope.get("client")
    if isinstance(client, (tuple, list)) and client:
        return str(client[0])
    return "unknown"


def parse_bearer(headers: Iterable[tuple[bytes, bytes]]) -> str | None:
    """从原始头序列取出 ``Bearer`` token；缺失 / 方案不符 / 空值 → ``None``。

    严格按 RFC 6750 的 ``Bearer <token>`` 形态解析：**恰好一个** ``Authorization`` 头
    （重复头视为不可信输入）、方案大小写不敏感、值前后空白剥掉但**内部空白不剥**
    （token 里出现空白必然是错值，交给比较失败处理）。
    """
    values = [value for name, value in headers if name.lower() == b"authorization"]
    if len(values) != 1:
        return None
    try:
        text = values[0].decode("latin-1").strip()
    except (AttributeError, UnicodeDecodeError):
        return None
    scheme, _, rest = text.partition(" ")
    if scheme.lower() != "bearer":
        return None
    token = rest.strip()
    return token or None


def token_matches(expected: str, provided: str | None) -> bool:
    """常量时间比较；任一侧为空一律不通过（空 token 永远不是合法凭证）。"""
    if not expected or not provided:
        return False
    return hmac.compare_digest(expected.encode("utf-8"), provided.encode("utf-8"))


class AuthThrottle:
    """按来源地址的认证失败滑窗（条目有界；``clock`` 可注入便于测试）。"""

    def __init__(
        self,
        *,
        max_failures: int = DEFAULT_MAX_FAILURES,
        window_seconds: float = DEFAULT_WINDOW_SECONDS,
        max_sources: int = DEFAULT_MAX_SOURCES,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_failures < 1:
            raise ValueError("max_failures must be >= 1")
        if window_seconds <= 0 or max_sources < 1:
            raise ValueError("window_seconds and max_sources must be positive")
        self.max_failures = max_failures
        self.window_seconds = window_seconds
        self.max_sources = max_sources
        self._clock = clock
        self._failures: OrderedDict[str, deque[float]] = OrderedDict()

    def __len__(self) -> int:
        """当前跟踪的来源数（诊断与上界判据用）。"""
        return len(self._failures)

    def failures(self, source: str) -> int:
        """该来源在窗口内的有效失败次数（读取时顺手修剪过期记录）。"""
        events = self._failures.get(source)
        if events is None:
            return 0
        self._prune(source, events)
        return len(events)

    def blocked(self, source: str) -> bool:
        """该来源是否已达失败阈值（达到后不再比较 token）。"""
        return self.failures(source) >= self.max_failures

    def record_failure(self, source: str) -> None:
        """记一次失败；条目数超上界时淘汰最久未更新的来源。"""
        events = self._failures.get(source)
        if events is None:
            if len(self._failures) >= self.max_sources:
                self._failures.popitem(last=False)
            events = deque()
            self._failures[source] = events
        else:
            self._failures.move_to_end(source)
        events.append(self._clock())
        self._prune(source, events)

    def record_success(self, source: str) -> None:
        """认证成功即清空该来源的失败计数（正常客户端不会被历史误伤）。"""
        self._failures.pop(source, None)

    def _prune(self, source: str, events: deque[float]) -> None:
        cutoff = self._clock() - self.window_seconds
        while events and events[0] <= cutoff:
            events.popleft()
        if not events:
            self._failures.pop(source, None)


def make_authorizer(token: str, throttle: AuthThrottle) -> Authorizer:
    """构造握手前认证回调：``None`` = 通过，否则是拒绝原因（``missing`` / ``invalid`` / ``throttled``）。

    顺序是**先限速后比较**：被限速的来源不再触碰 token 比较路径（也不刷新其计数），
    「被限速」与「token 错」对客户端完全不可区分（都回 1008）。
    """
    if not token:
        raise ValueError("authorizer requires a non-empty token")

    def authorize(scope: Mapping[str, Any]) -> str | None:
        source = client_source(scope)
        if throttle.blocked(source):
            return "throttled"
        provided = parse_bearer(scope.get("headers") or ())
        if provided is None:
            throttle.record_failure(source)
            return "missing"
        if not token_matches(token, provided):
            throttle.record_failure(source)
            return "invalid"
        throttle.record_success(source)
        return None

    return authorize


__all__ = [
    "AUTH_CLOSE_CODE",
    "DEFAULT_MAX_FAILURES",
    "DEFAULT_MAX_SOURCES",
    "DEFAULT_WINDOW_SECONDS",
    "AuthThrottle",
    "Authorizer",
    "client_source",
    "make_authorizer",
    "parse_bearer",
    "token_matches",
]
