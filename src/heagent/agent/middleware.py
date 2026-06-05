"""中间件管道 — 可插拔的请求/响应处理链。

设计模式：递归组合（类似洋葱模型）。
每个中间件接收 (Request, NextFn)，可拦截、修改请求或响应。
最终内层 handler 调用 Provider.send()。

示例：日志中间件 → 限流中间件 → 实际 Provider 调用
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol

from heagent.providers.retry import retry_with_backoff

if TYPE_CHECKING:
    from heagent.types import Message

logger = logging.getLogger(__name__)

# 中间件函数类型：(请求, 下一步函数) -> 任意结果
MiddlewareFn = Callable[["Request", "NextFn"], Any]


class Request:
    """中间件管道中传递的请求数据。"""

    __slots__ = ("messages", "tools", "metadata")

    def __init__(
        self,
        messages: list[Message],
        tools: list[object] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.messages = messages       # 对话消息列表
        self.tools = tools or []       # 已启用的工具 Schema 列表
        self.metadata = metadata or {} # 附加元数据（供中间件传递信息）


class NextFn(Protocol):
    """下一步函数的类型签名，调用即委托给下一层中间件。"""

    def __call__(self, request: Request) -> Any: ...


def compose(middlewares: list[MiddlewareFn], handler: Callable[[Request], Any]) -> NextFn:
    """将中间件列表递归组合为链式调用。

    执行顺序：middlewares[0] → middlewares[1] → ... → handler
    每个中间件通过调用 next_fn(req) 将控制权传递给下一层。

    参数：
        middlewares: 中间件函数列表
        handler: 最内层的实际处理函数（通常是 Provider.send 的包装）
    返回：
        组合后的链头函数，调用即触发整条链
    """

    def build(idx: int) -> NextFn:
        # 递归终止：所有中间件已处理完毕，调用内层 handler
        if idx >= len(middlewares):
            return lambda req: handler(req)

        mw = middlewares[idx]

        def next_fn(req: Request) -> Any:
            # 当前中间件处理请求，并接收 build(idx+1) 作为 next 函数
            return mw(req, build(idx + 1))

        return next_fn

    return build(0)  # 从第一个中间件开始


def make_retry_middleware(
    *,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
) -> MiddlewareFn:
    """创建重试中间件，对 TRANSIENT 错误自动指数退避重试。

    参数从 Settings.retry_* 读取，在 cli.py 中构造后注入 AgentLoop.middlewares。
    """
    async def retry_middleware(request: Request, next_fn: NextFn) -> Any:
        return await retry_with_backoff(
            lambda: next_fn(request),
            max_attempts=max_attempts,
            base_delay=base_delay,
            max_delay=max_delay,
        )
    return retry_middleware
