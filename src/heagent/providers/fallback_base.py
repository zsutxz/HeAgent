"""Provider 回退的共享基础设施。

提取 chain/key_rotation/switchable 三个回退层的共享逻辑，减少重复代码。
本模块提供：
  - 统一的错误包装（确保始终抛出 ProviderError）
  - 回退决策接口（哪些错误值得回退）
  - 共享的回退循环模板（可选，供简化使用）
"""

from __future__ import annotations

from typing import NoReturn

from heagent.providers.retry import ErrorCategory, classify_exception, is_pool_fallback_error, wrap_provider_error
from heagent.pub.exceptions import ProviderError


def raise_as_provider_error(error: Exception) -> NoReturn:
    """统一的错误包装：确保抛出的始终是 ProviderError。

    这是 chain._raise_provider_error / key_rotation._raise_wrapped /
    retry.raise_provider_error 的合并版本。

    - 已经是 ProviderError：原样抛出，保留 cause 链
    - 其他异常：包装为 ProviderError，原异常作为 cause（状态码提取委托
      :func:`heagent.providers.retry.wrap_provider_error`，DRY 单一来源）
    """
    if isinstance(error, ProviderError):
        raise error
    raise wrap_provider_error(error) from error


class FallbackPolicy:
    """回退策略的统一接口。

    不同的容错层有不同的回退判据：
    - ProviderChain: 除了 NON_TRANSIENT 都回退（跨 provider 类型）
    - KeyRotatingProvider: 仅 RATE_LIMITED + AUTH_FAILED（同 provider 换 key）
    - SwitchableProvider: 仅 RATE_LIMITED + TRANSIENT（池内换档）
    """

    @staticmethod
    def should_fallback_chain(error: Exception) -> bool:
        """ProviderChain 的回退判据：除了 NON_TRANSIENT 都回退。

        跨 provider 类型回退，AUTH_FAILED 换一家可能成功。
        """
        return classify_exception(error) != ErrorCategory.NON_TRANSIENT

    @staticmethod
    def should_fallback_key_rotation(error: Exception) -> bool:
        """KeyRotatingProvider 的回退判据：RATE_LIMITED + AUTH_FAILED。

        同 provider 换 key，换密钥正是认证失败的解。
        """
        if not isinstance(error, ProviderError):
            return False
        category = classify_exception(error)
        return category in (ErrorCategory.RATE_LIMITED, ErrorCategory.AUTH_FAILED)

    @staticmethod
    def should_fallback_pool(error: Exception) -> bool:
        """SwitchableProvider 的回退判据：RATE_LIMITED + TRANSIENT。

        池内换档会静默改掉用户选定的模型，AUTH_FAILED 属配置问题不该偷偷换。
        委托给 retry.is_pool_fallback_error 保持向后兼容。
        """
        return is_pool_fallback_error(error)


# 重新导出，供消费方统一导入
__all__ = ["raise_as_provider_error", "FallbackPolicy"]
