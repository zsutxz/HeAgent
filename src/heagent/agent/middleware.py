"""中间件管道 — 可插拔的请求/响应处理链。

设计模式：递归组合（类似洋葱模型）。
每个中间件接收 (Request, NextFn)，可拦截、修改请求或响应。
最终内层 handler 调用 Provider.send()。

示例：日志中间件 → 限流中间件 → 实际 Provider 调用
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from heagent.providers.retry import retry_with_backoff

if TYPE_CHECKING:
    from heagent.types import Message, ToolSchema

logger = logging.getLogger(__name__)

# 中间件函数类型：(请求, 下一步函数) -> 任意结果
MiddlewareFn = Callable[["Request", "NextFn"], Any]


class Request:
    """中间件管道中贯穿传递的请求数据。

    每个 ``Request`` 是一次「即将交给 LLM 的调用」的不可变快照：从最外层
    中间件流入，逐层向内传递，最终抵达内层 handler（``Provider.send``）。
    中间件可读取/改写其中的字段（例如注入额外 messages、过滤 tools），
    也可经 ``metadata`` 在层与层之间携带私有信息。
    """

    __slots__ = ("messages", "tools", "metadata")

    def __init__(
        self,
        messages: list[Message],
        tools: list[ToolSchema] | None = None,
        metadata: dict[str, object] | None = None,
    ) -> None:
        self.messages = messages  # 对话消息列表（会原样传给 Provider.send）
        self.tools = tools or []  # 已启用的工具 Schema 列表（决定 LLM 可调用哪些工具）
        self.metadata = metadata or {}  # 附加元数据（供中间件在层间传递私有信息）


# 下一步函数的类型签名，调用即委托给下一层中间件
NextFn = Callable[[Request], Any]


def compose(middlewares: list[MiddlewareFn], handler: Callable[[Request], Any]) -> NextFn:
    """将中间件列表递归组合为链式调用（洋葱模型）。

    组合结果是一个「链头函数」，调用它即触发整条链。执行顺序：

        middlewares[0] → middlewares[1] → ... → handler（Provider.send）

    每个中间件拿到 ``(req, next_fn)`` 后，可以选择：
      - 调用 ``next_fn(req)`` —— 把控制权交给下一层（可对返回值做后置处理）；
      - 不调用 ``next_fn`` —— 直接短路，例如被限流中间件拦截。
    ``next_fn`` 由闭包 ``build(idx+1)`` 生成，因此「下一步」天然指向链中的
    下一层中间件，最内层最终落到 ``handler``。

    参数：
        middlewares: 中间件函数列表（按下标顺序逐层包裹）
        handler: 最内层的实际处理函数（通常是 Provider.send 的包装）
    返回：
        组合后的链头函数，调用即触发整条链
    """

    def build(idx: int) -> NextFn:
        # 递归终止：所有中间件已处理完毕，落到内层 handler（Provider.send）
        if idx >= len(middlewares):
            return lambda req: handler(req)

        mw = middlewares[idx]

        def next_fn(req: Request) -> Any:
            # 当前中间件处理请求，并把 build(idx+1) 作为「下一步」交给它
            return mw(req, build(idx + 1))

        return next_fn

    return build(0)  # 从第一个中间件开始，返回整条链的入口


def make_retry_middleware(
    *,
    max_attempts: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
) -> MiddlewareFn:
    """创建一个「指数退避重试」中间件，对瞬时（TRANSIENT）错误自动重试。

    参数从 ``Settings.retry_*`` 读取，在 ``cli.py`` 中构造后注入
    ``AgentLoop.middlewares``。它包裹在 Provider 调用之外：当内层 handler
    抛出瞬时错误时，由 ``retry_with_backoff`` 按指数退避策略重试，最多
    ``max_attempts`` 次；非瞬时错误或耗尽重试次数后照常向上抛出。
    """

    async def retry_middleware(request: Request, next_fn: NextFn) -> Any:
        # next_fn(request) 才是真正触发下游链/Provider 调用的地方；
        # 用 lambda 包一层交给 retry_with_backoff，由它决定何时重试。
        return await retry_with_backoff(
            lambda: next_fn(request),
            max_attempts=max_attempts,
            base_delay=base_delay,
            max_delay=max_delay,
        )

    return retry_middleware
