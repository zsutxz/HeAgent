"""旁路 Provider 调用的统一记账入口（context 层收口）。

主循环经 ``agent/loop._call_provider`` 调用模型，自带调用日志与 token 校准；context 压缩、
窗口重置、goal 命名三类旁路调用此前直调 ``provider.send``，无日志无校准——这类调用常被
路由给 OpenAI/GPT 等廉价模型，在日志与统计里完全隐形，统计长期低估。
收口为单一入口：失败原样上抛，处置（占位符/回退）归调用方。
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from heagent.context.tokens import count_tokens, note_actual_usage

if TYPE_CHECKING:
    from heagent.providers.base import BaseProvider
    from heagent.pub.types import Message, ProviderResponse

logger = logging.getLogger(__name__)


async def send_accounted(
    provider: BaseProvider,
    messages: list[Message],
    *,
    caller: str,
) -> ProviderResponse:
    """带调用日志与 token 校准的旁路 ``provider.send``；失败原样上抛，处置归调用方。"""
    estimated = count_tokens(messages)
    logger.info(
        "[%s] Calling provider: %d messages, ~%d tokens estimated",
        caller,
        len(messages),
        estimated,
    )
    started = time.perf_counter()
    resp = await provider.send(messages)
    duration_ms = max(int((time.perf_counter() - started) * 1_000), 0)
    usage = resp.usage
    if usage and usage.total_tokens > 0:
        logger.info(
            "[%s] Provider response: %d actual tokens (estimated: %d, delta: %+d)",
            caller,
            usage.total_tokens,
            estimated,
            usage.total_tokens - estimated,
        )
        note_actual_usage(resp.model, estimated=estimated, actual=usage.prompt_tokens)
    else:
        logger.warning(
            "[%s] Provider response carries no usage (model=%s finish_reason=%s)",
            caller,
            resp.model,
            resp.finish_reason,
        )
    logger.info(
        "[%s] provider call completed: model=%s finish_reason=%s duration_ms=%d "
        "prompt_tokens=%d completion_tokens=%d total_tokens=%d",
        caller,
        resp.model,
        resp.finish_reason,
        duration_ms,
        usage.prompt_tokens if usage else 0,
        usage.completion_tokens if usage else 0,
        usage.total_tokens if usage else 0,
    )
    return resp
