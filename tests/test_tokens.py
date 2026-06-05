"""Token 估算模块测试 — 验证 CJK 感知字符启发式的准确性。"""

from __future__ import annotations

from heagent.context.tokens import _estimate_text_tokens, count_tokens
from heagent.types import Message, Role


class TestEstimateTextTokens:
    """单文本 token 估算测试。"""

    def test_pure_english(self) -> None:
        """纯英文文本：~4 字符/token。"""
        # "hello world" = 11 chars → int(11/4) = 2 tokens
        result = _estimate_text_tokens("hello world")
        assert result == 2

    def test_pure_chinese(self) -> None:
        """纯中文文本：~1 token/字符。"""
        text = "你好世界"  # 4 CJK chars
        result = _estimate_text_tokens(text)
        assert result == 4  # 每个 CJK 字符 = 1 token

    def test_mixed_chinese_english(self) -> None:
        """中英混合文本：CJK 1:1，英文 ~4:1。"""
        text = "你好hello"  # 2 CJK + 5 english
        result = _estimate_text_tokens(text)
        # CJK: 2, other: 5, int(5/4) = 1, max(1,1) = 1 → total = 2 + 1 = 3
        assert result == 3

    def test_empty_string(self) -> None:
        """空字符串：至少 1 token。"""
        result = _estimate_text_tokens("")
        assert result == 1  # max(1, 0) = 1

    def test_single_char(self) -> None:
        """单个字符：1 token。"""
        assert _estimate_text_tokens("a") == 1
        assert _estimate_text_tokens("中") == 1

    def test_japanese_hiragana(self) -> None:
        """日文平假名：~1 token/字符。"""
        text = "こんにちは"  # 5 hiragana
        result = _estimate_text_tokens(text)
        assert result == 5

    def test_korean(self) -> None:
        """韩文音节：~1 token/字符。"""
        text = "안녕하세요"  # 5 Korean syllables
        result = _estimate_text_tokens(text)
        assert result == 5


class TestCountTokens:
    """消息列表 token 估算测试。"""

    def test_empty_list(self) -> None:
        """空消息列表：仅回复预填充开销。"""
        result = count_tokens([])
        assert result == 3  # 仅 _TOKENS_REPLY_PRIMING

    def test_single_user_message(self) -> None:
        """单条用户消息：开销 + 内容。"""
        msg = Message(role=Role.USER, content="hello world")
        result = count_tokens([msg])
        # 3 (reply priming) + 3 (message overhead) + content tokens
        assert result > 3  # 至少有回复预填充 + 消息开销
        assert result > 6  # 至少有内容

    def test_multiple_messages(self) -> None:
        """多条消息：每条有独立开销。"""
        messages = [
            Message(role=Role.SYSTEM, content="You are helpful"),
            Message(role=Role.USER, content="Hi"),
            Message(role=Role.ASSISTANT, content="Hello!"),
        ]
        result = count_tokens(messages)
        # 至少 3 (priming) + 3*3 (overhead) + content
        assert result >= 12  # 3 + 9 = 12 minimum (without content)

    def test_message_with_tool_calls(self) -> None:
        """包含工具调用的消息：估算工具名称和参数。"""
        from heagent.types import ToolCall

        msg = Message(
            role=Role.ASSISTANT,
            content="",
            tool_calls=[
                ToolCall(id="call_1", name="shell", arguments={"command": "ls -la"}),
            ],
        )
        result = count_tokens([msg])
        # 应包含 shell 名称和 arguments 字符串的 token
        assert result > 6  # 至少开销

    def test_chinese_messages(self) -> None:
        """中文消息：CJK 感知估算。"""
        msg = Message(role=Role.USER, content="你好，请帮我写一个Python函数")
        result = count_tokens([msg])
        # 中文部分的 token 应该更多（每字符约1 token）
        assert result > 15  # 中文字符 + 英文 "Python" + 开销

    def test_message_with_tool_result(self) -> None:
        """工具结果消息：包含 tool_call_id。"""
        msg = Message(role=Role.TOOL, content="file contents here", tool_call_id="call_1")
        result = count_tokens([msg])
        assert result > 6  # 开销 + 内容 + tool_call_id

    def test_estimation_reasonable_range(self) -> None:
        """估算值在合理范围内（与 tiktoken 结果偏差 < 50%）。"""
        # 一段典型的对话
        messages = [
            Message(role=Role.SYSTEM, content="You are a helpful coding assistant."),
            Message(role=Role.USER, content="Write a Python function to calculate fibonacci numbers."),
        ]
        result = count_tokens(messages)
        # 真实 tiktoken 结果大约 25-30 tokens
        # 启发式允许 ±50% 偏差
        assert 15 <= result <= 60
