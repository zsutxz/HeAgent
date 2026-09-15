"""摘要输入序列化：唯一实现点（compressor 与 window reset 共用）。

2026-09-15 之前 ``ContextCompressor._summarize`` 与 ``WindowReset._summarize`` 各持一份
逐字相同的 parts 组装副本；两处对 ``tool_result`` 的表示也已分叉，且 window reset 侧把工具
正文**同时**写进标识行与角色行（正文重复计入摘要输入）。现已合并为唯一实现
``render_message_for_summary``，并修掉了重复计入。

本文件锁定：

1. ``render_message_for_summary`` 的逐字输出，以及「工具正文只写一次」的不变量；
2. 两条压缩路径**实际发给 provider 的 prompt**：正文都只出现 1 次，差别仅在挂在哪一行
   （compressor 挂角色行 ``tool: <content>``、window reset 挂标识行
   ``tool_result(<id>): <content>``）。
"""

from __future__ import annotations

import pytest

from heagent.context.compressor import ContextCompressor, render_message_for_summary
from heagent.context.window_reset import WindowReset
from heagent.types import Message, ProviderResponse, Role, TokenUsage, ToolCall


class _RecordingProvider:
    """记录每次 ``send`` 的 prompt 文本，返回固定摘要。"""

    def __init__(self) -> None:
        self.prompts: list[str] = []

    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        self.prompts.append("\n".join(m.content or "" for m in messages))
        return ProviderResponse(
            content="SUMMARY",
            usage=TokenUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            model="stub",
            finish_reason="stop",
        )


def _read_call() -> ToolCall:
    return ToolCall(id="call_1", name="file_read", arguments={"path": "a.py"})


def _conversation(body: str) -> list[Message]:
    return [
        Message(role=Role.USER, content="read it"),
        Message(role=Role.ASSISTANT, content="", tool_calls=[_read_call()]),
        Message(role=Role.TOOL, content=body, tool_call_id="call_1"),
    ]


# --------------------------------------------------------------------- 序列化（纯函数）
def test_user_message_carries_role_prefix() -> None:
    message = Message(role=Role.USER, content="hi")
    assert render_message_for_summary(message, tool_result_content=True) == ["user: hi"]


def test_tool_calls_are_serialized_as_json_arguments() -> None:
    message = Message(role=Role.ASSISTANT, content="", tool_calls=[_read_call()])
    assert render_message_for_summary(message, tool_result_content=True) == ['tool_call: file_read({"path": "a.py"})']


def test_tool_result_body_lands_on_one_line_only() -> None:
    message = Message(role=Role.TOOL, content="file body", tool_call_id="call_1")
    # flag=False：正文挂角色行，标识行只留 id。
    assert render_message_for_summary(message, tool_result_content=False) == [
        "tool_result(call_1):",
        "tool: file body",
    ]
    # flag=True：正文并入标识行，不再另写角色行。
    assert render_message_for_summary(message, tool_result_content=True) == ["tool_result(call_1): file body"]


@pytest.mark.parametrize("tool_result_content", [False, True])
def test_tool_body_is_never_duplicated(tool_result_content: bool) -> None:
    """不变量：无论正文挂哪一行，都只出现一次（2026-09-15 修复重复计入）。"""
    message = Message(role=Role.TOOL, content="file body", tool_call_id="call_1")
    rendered = "\n".join(render_message_for_summary(message, tool_result_content=tool_result_content))
    assert rendered.count("file body") == 1


def test_empty_tool_result_body_keeps_trailing_space_when_requested() -> None:
    """逐字节锁定：空正文 + ``True`` 仍是 ``tool_result(id): ``（尾随空格），与合并前一致。"""
    message = Message(role=Role.TOOL, content="", tool_call_id="call_1")
    assert render_message_for_summary(message, tool_result_content=True) == ["tool_result(call_1): "]


def test_message_without_content_or_tool_calls_is_skipped() -> None:
    message = Message(role=Role.USER, content="")
    assert render_message_for_summary(message, tool_result_content=True) == []


# ----------------------------------------------------------- 两条路径实际发出的 prompt
async def test_compressor_prompt_counts_tool_body_once() -> None:
    """compressor 口径：正文挂角色行，只出现 1 次（标识行不带正文）。"""
    provider = _RecordingProvider()
    compressor = ContextCompressor(provider, max_summary_tokens=4096)
    assert await compressor._summarize(_conversation("SECRET_BODY"), max_tokens=0) == "SUMMARY"
    prompt = provider.prompts[0]
    assert "tool_result(call_1):" in prompt
    assert prompt.count("SECRET_BODY") == 1


async def test_window_reset_prompt_counts_tool_body_once() -> None:
    """window reset 口径：正文并入标识行，同样只出现 1 次（修复前为 2 次）。"""
    provider = _RecordingProvider()
    assert await WindowReset(provider)._summarize(_conversation("SECRET_BODY")) == "SUMMARY"
    prompt = provider.prompts[0]
    assert "tool_result(call_1): SECRET_BODY" in prompt
    assert prompt.count("SECRET_BODY") == 1
