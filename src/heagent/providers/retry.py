"""错误分类与差异化重试策略。

将 Provider 调用错误分为四类：
  - RATE_LIMITED (429): 限流，不重试（需等待限流窗口重置）
  - AUTH_FAILED (401/403): 认证失败，不重试（需修正密钥）
  - TRANSIENT (5xx/超时): 临时错误，使用指数退避 + 随机抖动重试
  - NON_TRANSIENT (其他): 非临时错误，不重试

当前为独立函数，未来可作为 Middleware 接入 AgentLoop。
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from enum import Enum

from heagent.exceptions import ProviderError


class ErrorCategory(str, Enum):
    """错误分类枚举。"""

    RATE_LIMITED = "rate_limited"    # 限流错误（429）
    AUTH_FAILED = "auth_failed"      # 认证失败（401/403）
    TRANSIENT = "transient"          # 临时错误（5xx/超时）→ 可重试
    NON_TRANSIENT = "non_transient"  # 非临时错误 → 不重试


def classify_error(error: ProviderError) -> ErrorCategory:
    """根据状态码和错误信息分类 Provider 错误。

    分类优先级：429 > 401 > 5xx > 其他
    """
    msg = error.message.lower()
    status = getattr(error, "status_code", None)

    # 限流：429 状态码或消息中包含 rate/429
    if status == 429 or "rate" in msg or "429" in msg:
        return ErrorCategory.RATE_LIMITED
    # 认证失败：401 状态码或消息中包含 auth/401
    if status == 401 or "auth" in msg or "401" in msg:
        return ErrorCategory.AUTH_FAILED
    # 临时错误：5xx 状态码或超时/过载关键词
    if status in (503, 502, 500) or "timeout" in msg or "503" in msg or "overload" in msg:
        return ErrorCategory.TRANSIENT
    # 默认归为非临时错误
    return ErrorCategory.NON_TRANSIENT


async def retry_with_backoff(
    fn: Callable[[], Awaitable[object]],
    *,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
) -> object:
    """对异步函数执行指数退避重试（仅针对 TRANSIENT 错误）。

    退避策略：delay = min(base_delay * 2^attempt + random_jitter, max_delay)
    随机抖动（0~1秒）防止多个客户端同时重试造成惊群效应。

    参数：
        fn: 要重试的异步函数
        max_attempts: 最大尝试次数
        base_delay: 基础延迟（秒）
        max_delay: 最大延迟上限（秒）
    返回：
        fn() 的成功返回值
    异常：
        非临时错误立即抛出；重试耗尽后抛出最后一次错误
    """
    last_error: Exception | None = None

    for attempt in range(max_attempts):
        try:
            return await fn()
        except ProviderError as e:
            category = classify_error(e)
            # 只有临时错误才重试，其他类型立即抛出
            if category != ErrorCategory.TRANSIENT:
                raise
            last_error = e
            # 最后一次不等待，直接进入下一次循环抛出
            if attempt < max_attempts - 1:
                delay = min(base_delay * (2 ** attempt) + random.uniform(0, 1), max_delay)
                await asyncio.sleep(delay)

    raise last_error or ProviderError("Retry exhausted")
