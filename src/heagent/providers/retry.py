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


def _classify(status: int | None, message: str) -> ErrorCategory:
    """根据状态码和消息文本分类错误的纯函数（供 classify_error/classify_exception 共享）。

    分类优先级：429 > 401 > 5xx > 其他（默认 NON_TRANSIENT）
    """
    msg = message.lower()

    # 限流：429 状态码或消息中包含 rate/429
    if status == 429 or "rate" in msg or "429" in msg:
        return ErrorCategory.RATE_LIMITED
    # 认证失败：401 状态码或消息中包含 auth/401
    if status == 401 or "auth" in msg or "401" in msg:
        return ErrorCategory.AUTH_FAILED
    # 临时错误：5xx 状态码或超时/连接/过载关键词。
    # OpenAI SDK 的 APITimeoutError.message="Request timed out."（含 "timed out" 不含 "timeout"）、
    # APIConnectionError.message="Connection error."——须同时覆盖，否则单 provider 配置下这类典型
    # 瞬时错误会被误判为 NON_TRANSIENT 而不重试、ProviderChain 也不回退（违反 spec I/O 矩阵）。
    if (
        status in (503, 502, 500)
        or "timeout" in msg
        or "timed out" in msg
        or "connection" in msg
        or "503" in msg
        or "overload" in msg
    ):
        return ErrorCategory.TRANSIENT
    # 默认归为非临时错误
    return ErrorCategory.NON_TRANSIENT


def _extract_status_message(error: Exception) -> tuple[int | None, str]:
    """从任意异常中 duck-type 提取状态码与消息。

    兼容 HeAgent ProviderError（.status_code/.message）与 OpenAI/Anthropic SDK 的
    APIStatusError（.status_code/.message），以及任意 Exception（str()）。
    """
    status = getattr(error, "status_code", None)
    if status is None:
        status = getattr(error, "status", None)
    message = getattr(error, "message", None) or str(error)
    return status, message


def wrap_provider_error(error: Exception) -> ProviderError:
    """将任意异常（含原始 SDK 异常）包装为 ProviderError，保留状态码。

    供 provider 源头（OpenAI/Anthropic）统一包装 SDK 抛出的 APIStatusError /
    APIConnectionError / APITimeoutError 等异常，使下游 KeyRotatingProvider /
    retry 中间件 / ProviderChain 始终面对 HeAgentError 体系内的异常——避免裸 SDK
    异常穿透导致密钥轮换/retry 死代码与非框架异常崩溃。

    状态码与消息提取复用 _extract_status_message（duck-type status_code/status/
    message），保证 chain._wrap_error 与 provider 包装行为一致（DRY 单一来源）。
    """
    status, message = _extract_status_message(error)
    return ProviderError(message, status_code=status)


def classify_error(error: ProviderError) -> ErrorCategory:
    """根据状态码和错误信息分类 Provider 错误。

    分类优先级：429 > 401 > 5xx > 其他
    """
    return _classify(getattr(error, "status_code", None), getattr(error, "message", "") or str(error))


def classify_exception(error: Exception) -> ErrorCategory:
    """对任意异常（含原始 SDK 异常，非 ProviderError）进行分类。

    供 ProviderChain 决定是否回退：仅 RATE_LIMITED/AUTH_FAILED/TRANSIENT 可回退，
    NON_TRANSIENT（400/422 等客户端错误）不应回退——切换 Provider 不会令坏请求变好。
    """
    return _classify(*_extract_status_message(error))


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
