"""Token 估算 — 基于 CJK 感知字符启发式的消息 token 数计算。

提供本地 token 估算能力，无需外部依赖（tiktoken 等），
用于发送前上下文预算管理和日志记录。

估算策略：
  - CJK 字符（中日韩）：~1 token/字符
  - 其他字符（英文/代码等）：~4 字符/token
  - 每条消息结构开销：+3 tokens（角色标签、分隔符）
  - 回复预填充开销：+3 tokens

与 LangChain 的 count_tokens_approximately 策略一致，
适用于所有 LLM provider（OpenAI、Anthropic 等）。
"""

from __future__ import annotations

import importlib
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from heagent.types import Message, TokenUsage, ToolCall

logger = logging.getLogger(__name__)

# 消息结构开销常量（与 OpenAI/LangChain 对齐）
_TOKENS_PER_MESSAGE = 3  # 每条消息的角色标签、分隔符开销
_TOKENS_REPLY_PRIMING = 3  # 回复预填充 "<|assistant|/>" 开销
_CHARS_PER_TOKEN = 4.0  # 非CJK文本的字符/token比

# 真实 tokenizer encoding 缓存（model → encoding | None）；None 也缓存，避免反复尝试导入。
_ENCODING_CACHE: dict[str, Any] = {}
# 启发式校准系数（model → factor）：provider 真实 usage 的指数滑动平均。
_CALIBRATION: dict[str, float] = {}
# 校准样本的合理区间：超出即视为异常样本（缓存折扣 / 服务端改写历史），丢弃不采纳。
_MIN_FACTOR = 0.2
_MAX_FACTOR = 5.0
# 新样本在滑动平均中的权重（越小越保守，越不易被单次异常带偏）。
_CALIBRATION_WEIGHT = 0.5


def count_tokens(messages: list[Message], *, model: str | None = None) -> int:
    """计算消息列表的总 token 数：真实 tokenizer 优先，其次**校准后**的启发式。

    ``model`` 决定两件事：用哪个 tokenizer encoding，以及查哪个模型的历史校准系数。
    未安装 ``tiktoken``（或 ``TOKENIZER=estimate``）时退回 CJK 感知启发式 —— 但会叠加
    :func:`note_actual_usage` 从 provider 真实 usage 学到的系数。两条路径都直接喂给压缩
    阈值与窗口重置判定，偏差会以「该压缩时没压缩（撞 400）」或「提前压缩、白丢上下文」
    的形式放大，故不满足于「永远纯估算」。
    """
    encoding = _load_encoding(model)
    if encoding is not None:
        return _count_with_encoding(encoding, messages)
    return _apply_calibration(_count_heuristic(messages), model)


def _count_heuristic(messages: list[Message]) -> int:
    """CJK 感知启发式计量（原 ``count_tokens`` 实现，无外部依赖）。"""
    total = 0
    for msg in messages:
        total += _TOKENS_PER_MESSAGE
        # 内容 token
        if msg.content:
            total += _estimate_text_tokens(msg.content)
        # 工具调用 token（序列化参数）
        if msg.tool_calls:
            for tc in msg.tool_calls:
                total += _estimate_text_tokens(tc.name)
                total += _estimate_text_tokens(str(tc.arguments))
        # 工具调用 ID
        if msg.tool_call_id:
            total += _estimate_text_tokens(msg.tool_call_id)
    total += _TOKENS_REPLY_PRIMING
    return total


def estimate_completion_tokens(content: str, tool_calls: list[ToolCall] | None = None) -> int:
    """估算一次 LLM 输出的 token 数（文本 + 工具调用参数）。

    与 :func:`count_tokens` 相同的 CJK 感知启发式，但只算「输出侧」：
    纯文本内容 + 每个工具调用的名称与序列化参数。用于流式 Provider
    不返回 usage 时的 completion token 兜底（避免 out=0 的失真显示）。
    """
    total = _estimate_text_tokens(content) if content else 0
    for call in tool_calls or []:
        total += _estimate_text_tokens(call.name)
        total += _estimate_text_tokens(str(call.arguments))
    return total


def _count_with_encoding(encoding: Any, messages: list[Message]) -> int:
    """用真实 tokenizer encoding 计量（结构开销常量与启发式路径保持一致）。"""
    total = _TOKENS_REPLY_PRIMING
    for msg in messages:
        total += _TOKENS_PER_MESSAGE
        if msg.content:
            total += len(encoding.encode(msg.content))
        for tc in msg.tool_calls or []:
            total += len(encoding.encode(tc.name))
            total += len(encoding.encode(str(tc.arguments)))
        if msg.tool_call_id:
            total += len(encoding.encode(msg.tool_call_id))
    return total


def _tokenizer_mode() -> str:
    """读 ``Settings.tokenizer``（auto / estimate / tiktoken）；读配置失败按 auto。"""
    try:
        from heagent.config import get_settings

        return (get_settings().tokenizer or "auto").strip().lower()
    except Exception:  # 配置异常不得让计量崩掉（计量是观测/预算路径，不是业务路径）
        return "auto"


def _load_encoding(model: str | None) -> Any | None:
    """惰性加载 tiktoken encoding；不可用返回 ``None``（结果按模型缓存，含 None）。

    ``TOKENIZER=estimate`` 时直接返回 None（显式禁用真实 tokenizer，便于对齐旧行为或
    在离线环境复现）；``TOKENIZER=tiktoken`` 而依赖缺失时告警一次后仍回退估算。
    模型名不被 tiktoken 认识（自研/中转模型名）时退到 ``cl100k_base`` 兜底。
    """
    key = model or ""
    if key in _ENCODING_CACHE:
        return _ENCODING_CACHE[key]

    mode = _tokenizer_mode()
    encoding: Any | None = None
    if mode != "estimate":
        try:
            # 经 importlib 加载可选依赖：mypy strict 下直接 import 会报 import-not-found
            # （tiktoken 无 stub、且不在必需依赖里），而它确实是「有则用、无则退」。
            tiktoken = importlib.import_module("tiktoken")

            try:
                encoding = tiktoken.encoding_for_model(model) if model else None
            except Exception:
                encoding = None
            if encoding is None:
                encoding = tiktoken.get_encoding("cl100k_base")
        except Exception:
            encoding = None
        if encoding is None and mode == "tiktoken":
            logger.warning("TOKENIZER=tiktoken but the tiktoken package is unavailable; using estimation")

    _ENCODING_CACHE[key] = encoding
    return encoding


def _apply_calibration(raw: int, model: str | None) -> int:
    """把启发式原始值按模型的校准系数缩放；无样本（系数 1.0）时原样返回。"""
    factor = calibration_factor(model)
    if factor == 1.0:
        return raw
    return max(1, round(raw * factor))


def note_actual_usage(model: str | None, *, estimated: int, actual: int) -> None:
    """用 provider 返回的真实 usage 校正启发式系数（按模型记录，指数滑动平均）。

    只在样本可用时更新：``estimated``/``actual`` 非正（provider 未返回 usage，如
    DeepSeek 流式）或比值落在 :data:`_MIN_FACTOR` ~ :data:`_MAX_FACTOR` 之外（缓存命中折扣、
    服务端重写历史等异常样本）一律忽略 —— 坏样本比没有样本更糟，会把压缩阈值带偏。
    """
    if estimated <= 0 or actual <= 0:
        return
    ratio = actual / estimated
    if not (_MIN_FACTOR <= ratio <= _MAX_FACTOR):
        logger.debug("ignoring token calibration sample for %r: ratio %.3f out of range", model, ratio)
        return
    key = model or ""
    previous = _CALIBRATION.get(key, 1.0)
    updated = previous * (1.0 - _CALIBRATION_WEIGHT) + ratio * _CALIBRATION_WEIGHT
    _CALIBRATION[key] = updated
    logger.debug("token calibration for %r: %.3f -> %.3f (sample ratio %.3f)", key, previous, updated, ratio)


def calibration_factor(model: str | None = None) -> float:
    """当前校准系数（无样本时 1.0）；供诊断与测试读取。"""
    return _CALIBRATION.get(model or "", 1.0)


def tokenizer_backend(model: str | None = None) -> str:
    """当前生效的计量后端名（``tiktoken`` / ``estimate``）——状态展示与诊断用。"""
    return "tiktoken" if _load_encoding(model) is not None else "estimate"


def reset_calibration() -> None:
    """清空校准系数与 encoding 缓存（测试隔离；亦可在切换模型集后手动重置）。"""
    _CALIBRATION.clear()
    _ENCODING_CACHE.clear()


def estimate_cost(usage: TokenUsage, model: str, pricing: dict[str, dict[str, float]]) -> float | None:
    """按模型价格估算一次使用的美元成本；无该模型价格则返回 None。

    参数：
        usage: 一次 provider 调用的 token 用量（prompt/completion）。
        model: 实际使用的模型名（``ProviderMetadata.model``）。
        pricing: 价格表 ``{"<model>": {"input": $/M tok, "output": $/M tok}}``。

    返回：美元成本（input + output）；模型不在价格表返回 None。
    """
    prices = pricing.get(model)
    if prices is None:
        return None
    in_cost = usage.prompt_tokens / 1_000_000.0 * prices.get("input", 0.0)
    out_cost = usage.completion_tokens / 1_000_000.0 * prices.get("output", 0.0)
    return in_cost + out_cost


def estimate_text_tokens(text: str) -> int:
    """Public wrapper for the shared heuristic token estimator."""
    return _estimate_text_tokens(text)


def _estimate_text_tokens(text: str) -> int:
    """估算文本的 token 数，CJK 感知。

    CJK 字符（中日韩统一表意文字）：~1 token/字符
    其他字符（英文、数字、标点、代码）：~4 字符/token
    """
    if not text:
        return 1  # 非空文本至少 1 token
    cjk_count = 0
    other_count = 0
    for ch in text:
        cp = ord(ch)
        # CJK 统一表意文字 + 扩展区 + CJK 兼容 + 假名 + 韩文
        if (
            0x4E00 <= cp <= 0x9FFF  # CJK 统一表意文字
            or 0x3400 <= cp <= 0x4DBF  # CJK 扩展 A
            or 0x20000 <= cp <= 0x2A6DF  # CJK 扩展 B
            or 0x2A700 <= cp <= 0x2B73F  # CJK 扩展 C
            or 0xF900 <= cp <= 0xFAFF  # CJK 兼容表意文字
            or 0x3040 <= cp <= 0x309F  # 平假名
            or 0x30A0 <= cp <= 0x30FF  # 片假名
            or 0xAC00 <= cp <= 0xD7AF  # 韩文音节
        ):
            cjk_count += 1
        else:
            other_count += 1
    # CJK：1 token/字符；其他：4 字符/token；非空文本至少 1 token
    other_tokens = int(other_count / _CHARS_PER_TOKEN) if other_count > 0 else 0
    return max(1, cjk_count + other_tokens)
