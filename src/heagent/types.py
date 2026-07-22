"""HeAgent 共享类型定义。

本模块定义了框架内所有模块间传递的数据模型。
所有跨模块数据必须通过这些 Pydantic 模型传递，禁止使用原始 dict。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class Role(StrEnum):
    """对话消息角色枚举。"""

    USER = "user"  # 用户输入
    ASSISTANT = "assistant"  # LLM 助手回复
    SYSTEM = "system"  # 系统提示词
    TOOL = "tool"  # 工具执行结果


class TokenUsage(BaseModel):
    """Token 使用量统计，从 Provider 响应中提取。"""

    prompt_tokens: int  # 输入 Token 数
    completion_tokens: int  # 输出 Token 数
    total_tokens: int  # 总 Token 数


class ToolCall(BaseModel):
    """LLM 发起的工具调用请求。

    当 LLM 判断需要调用工具时，返回此结构。
    id: 调用唯一标识，用于匹配后续 ToolResult
    name: 工具名称，对应 ToolRegistry 中注册的名称
    arguments: 工具参数，由 LLM 根据工具 JSON Schema 生成
    """

    id: str
    name: str
    arguments: dict[str, object]


class ToolResult(BaseModel):
    """工具执行结果，反馈给 LLM。

    tool_call_id: 对应的 ToolCall.id，建立调用-结果的映射关系
    content: 工具输出的文本内容
    is_error: 标记执行是否失败（安全拦截/运行异常）
    """

    tool_call_id: str
    content: str
    is_error: bool = False


class Message(BaseModel):
    """对话消息，Agent 循环中的基本通信单元。

    role: 消息角色（USER/ASSISTANT/SYSTEM/TOOL）
    content: 消息文本内容
    name: 工具名称（仅 TOOL 角色使用）
    tool_call_id: 关联的工具调用 ID（仅 TOOL 角色使用）
    tool_calls: LLM 请求的工具调用列表（仅 ASSISTANT 角色使用）
    reasoning_content: 思考模型要求在工具调用续轮中原样回传的推理内容
    """

    role: Role
    content: str
    name: str | None = None
    tool_call_id: str | None = None
    tool_calls: list[ToolCall] | None = None
    reasoning_content: str | None = None


class ProviderResponse(BaseModel):
    """Provider 统一响应格式。

    所有 LLM Provider（OpenAI/Anthropic/Chain）都返回此结构。
    content: LLM 生成的文本
    tool_calls: LLM 请求的工具调用（为空则表示最终答案）
    usage: Token 使用统计
    model: 实际使用的模型名称
    finish_reason: 结束原因（stop/tool_calls/length 等）
    reasoning_content: OpenAI 兼容思考模型返回、续轮时必须回传的推理内容
    """

    content: str
    tool_calls: list[ToolCall] = []
    usage: TokenUsage
    model: str
    finish_reason: str
    reasoning_content: str | None = None


class ToolAnnotations(BaseModel):
    """MCP 工具的风险 hint（HeAgent 自有模型）。

    由 ``mapping.mcp_tool_to_schema`` 从 MCP ``Tool.annotations`` 透传，供下游 PolicyEngine
    做确定性危险分级（``destructiveHint`` 审批 / ``readOnlyHint`` 放行）。**server 自声明、不可信**
    ——恶意/错误 server 可谎报；治理闸门仅 defense-in-depth 标记，**非真正安全边界**，须 OS 级
    沙箱兜底（见 CLAUDE.md 安全声明）。

    与 ``mcp.types.ToolAnnotations`` 的差异：四 hint 折叠为纯 ``bool``（mcp 原为 ``bool|None``
    tri-state，``None``→``False``）；**不透传** mcp 第 5 字段 ``title``（非裁决信号，丢弃）。
    """

    readOnlyHint: bool = False  # 工具不改环境（PolicyEngine 据此放行）
    destructiveHint: bool = False  # 工具可能 destructive（PolicyEngine 据此审批）
    idempotentHint: bool = False  # 幂等 hint（透传存储，V2 不进裁决）
    openWorldHint: bool = False  # 与外部开放世界交互 hint（透传存储，V2 不进裁决）


class ToolSchema(BaseModel):
    """工具的 JSON Schema 描述，用于 LLM function calling。

    由 @tool 装饰器从函数签名自动生成，发送给 LLM 使其了解可用工具。
    name: 工具名称
    description: 工具功能描述（取自 docstring 首行）
    parameters: 参数的 JSON Schema（从类型提示自动映射）
    annotations: 工具风险 hint（来自 MCP ``Tool.annotations``）；``None``=未声明，内置工具缺省
    """

    name: str
    description: str
    parameters: dict[str, object]
    annotations: ToolAnnotations | None = None


class StreamEvent(BaseModel):
    """流式输出事件 — run_stream() 逐步 yield 的事件类型。

    type: 事件类型
      - "text": LLM 生成的文本片段
      - "tool_call": 工具开始执行
      - "tool_result": 工具执行完成
      - "done": 最终完成，携带完整回答
    """

    type: Literal["text", "tool_call", "tool_result", "done"]
    text: str = ""
    tool_name: str = ""
    tool_result_content: str = ""
    final_answer: str = ""
