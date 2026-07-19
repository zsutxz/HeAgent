"""Tests for HeAgent shared types."""

from heagent.types import (
    Message,
    ProviderResponse,
    Role,
    TokenUsage,
    ToolAnnotations,
    ToolCall,
    ToolResult,
    ToolSchema,
)


def test_role_enum() -> None:
    assert Role.USER == "user"
    assert Role.ASSISTANT == "assistant"
    assert Role.SYSTEM == "system"
    assert Role.TOOL == "tool"


def test_message_user() -> None:
    msg = Message(role=Role.USER, content="Hello")
    assert msg.role is Role.USER
    assert msg.content == "Hello"
    assert msg.tool_calls is None


def test_message_assistant_with_tool_calls() -> None:
    tc = ToolCall(id="call_1", name="shell", arguments={"command": "ls"})
    msg = Message(role=Role.ASSISTANT, content="", tool_calls=[tc])
    assert msg.tool_calls is not None
    assert len(msg.tool_calls) == 1
    assert msg.tool_calls[0].name == "shell"


def test_message_tool_result() -> None:
    msg = Message(role=Role.TOOL, content="output", tool_call_id="call_1")
    assert msg.tool_call_id == "call_1"


def test_token_usage() -> None:
    usage = TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30)
    assert usage.total_tokens == 30


def test_tool_result() -> None:
    result = ToolResult(tool_call_id="call_1", content="ok")
    assert not result.is_error

    err = ToolResult(tool_call_id="call_2", content="failed", is_error=True)
    assert err.is_error


def test_provider_response() -> None:
    resp = ProviderResponse(
        content="Hi",
        usage=TokenUsage(prompt_tokens=5, completion_tokens=1, total_tokens=6),
        model="gpt-4o",
        finish_reason="stop",
    )
    assert resp.model == "gpt-4o"
    assert resp.tool_calls == []
    assert resp.finish_reason == "stop"


# --- ToolAnnotations（FR-A1：四 hint 风险模型，纯 bool 默认 False）---


def test_tool_annotations_defaults_all_false() -> None:
    """四 hint 字段均默认 False（AC-1）—— HeAgent 自有模型，非 tri-state。"""
    ann = ToolAnnotations()
    assert ann.readOnlyHint is False
    assert ann.destructiveHint is False
    assert ann.idempotentHint is False
    assert ann.openWorldHint is False


def test_tool_annotations_destructive_hint_carried() -> None:
    """destructiveHint=True 可正确携带（供下游 PolicyEngine 读，AC-2/AC-3 基础）。"""
    ann = ToolAnnotations(destructiveHint=True)
    assert ann.destructiveHint is True
    assert ann.readOnlyHint is False  # 其余字段仍默认 False


def test_tool_annotations_has_no_title_field() -> None:
    """HeAgent ToolAnnotations 不透传 mcp.types 第 5 字段 title（非裁决信号，丢弃）。

    模型仅四 hint 字段；title 不在其中（映射层透传时丢弃，见 test_mcp_mapping）。
    """
    ann = ToolAnnotations()
    assert not hasattr(ann, "title")
    # Pydantic v2 默认 extra="ignore"：即便误传 title 也不残留进模型
    ann2 = ToolAnnotations(title="should be dropped")  # type: ignore[call-args]
    assert not hasattr(ann2, "title")


# --- ToolSchema.annotations（FR-A1：可选字段，缺省 None，V1 零回归）---


def test_tool_schema_annotations_defaults_none() -> None:
    """不传 annotations 时缺省 None（AC-1）—— V1 既有 3 字段构造零改动通过。"""
    schema = ToolSchema(name="shell", description="run shell", parameters={"type": "object"})
    assert schema.annotations is None


def test_tool_schema_with_annotations() -> None:
    """显式传 annotations 时正确携带（AC-1）。"""
    ann = ToolAnnotations(readOnlyHint=True)
    schema = ToolSchema(name="search", description="search", parameters={"type": "object"}, annotations=ann)
    assert schema.annotations is not None
    assert schema.annotations.readOnlyHint is True
