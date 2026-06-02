"""Agent 核心循环 — LLM ↔ 工具执行的迭代周期。

核心流程：
  1. 用户输入 → 构建初始消息
  2. 调用 Provider 获取 LLM 响应
  3. 若响应包含 tool_calls → 安全检查 → 并行执行 → 结果追加到消息 → 回到步骤 2
  4. 若响应无 tool_calls → 返回文本作为最终答案
  5. 超过最大迭代次数 → 抛出 BudgetExceeded
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from heagent.agent.middleware import MiddlewareFn, Request, compose
from heagent.config import get_settings
from heagent.exceptions import BudgetExceeded, SafetyViolation, ToolError
from heagent.memory.skills import SkillStore
from heagent.providers.base import BaseProvider
from heagent.tools.registry import ToolRegistry
from heagent.tools.safety import SafetyGuard
from heagent.types import Message, ProviderResponse, Role, ToolCall, ToolResult

logger = logging.getLogger(__name__)


@dataclass
class AgentState:
    """单次 Agent 运行的可变状态。

    messages: 对话历史，随循环不断追加（USER → ASSISTANT → TOOL → ...）
    iteration: 当前迭代计数，用于预算控制
    max_iterations: 最大允许迭代次数
    results: 所有已执行的 ToolResult 累积记录
    """

    messages: list[Message] = field(default_factory=list)
    iteration: int = 0
    max_iterations: int = 50
    results: list[ToolResult] = field(default_factory=list)


class AgentLoop:
    """核心编排器：驱动 LLM ↔ 工具执行的迭代循环。

    典型使用：
        loop = AgentLoop(provider)
        answer = await loop.run("帮我创建一个文件")
    """

    def __init__(
        self,
        provider: BaseProvider,
        *,
        registry: ToolRegistry | None = None,
        guard: SafetyGuard | None = None,
        middlewares: list[MiddlewareFn] | None = None,
        max_iterations: int | None = None,
        skills: SkillStore | None = None,
    ) -> None:
        self.provider = provider                      # LLM 提供者（OpenAI/Anthropic/Chain）
        self.registry = registry or ToolRegistry.get()  # 工具注册中心（默认全局单例）
        self.guard = guard or SafetyGuard()            # 安全防护（默认黑名单模式）
        self.middlewares = middlewares or []            # 中间件链（可选）
        self.skills = skills                           # 技能存储（可选，注入到系统提示词）
        settings = get_settings()
        self.max_iterations = max_iterations or settings.max_iterations

        # 技能工具激活：将 SkillStore 注入工具模块，使 LLM 可通过工具管理技能
        if self.skills:
            from heagent.tools.builtins.skills import configure_skill_tools
            configure_skill_tools(self.skills)

    async def run(self, prompt: str, *, system: str | None = None) -> str:
        """运行 Agent 循环，直到 LLM 产出最终文本答案。

        参数：
            prompt: 用户输入的提示文本
            system: 可选的系统提示词（影响 LLM 行为）
        返回：
            LLM 最终的文本回答（不含 tool_calls 的响应）
        异常：
            BudgetExceeded: 超过最大迭代次数
        """
        state = AgentState(max_iterations=self.max_iterations)

        # 构建初始消息：系统提示（含技能注入，可选）+ 用户输入
        system_content = self._build_system(system, prompt=prompt)
        if system_content:
            state.messages.append(Message(role=Role.SYSTEM, content=system_content))
        state.messages.append(Message(role=Role.USER, content=prompt))

        # ---- 核心循环：Provider → Tool 执行 → Provider → ... ----
        while True:
            state.iteration += 1
            # 迭代预算检查
            if state.iteration > state.max_iterations:
                raise BudgetExceeded(
                    f"Exceeded {state.max_iterations} iterations without final answer"
                )

            # 步骤 1：调用 Provider 获取 LLM 响应
            response = await self._call_provider(state)
            # 将助手回复追加到对话历史
            state.messages.append(
                Message(role=Role.ASSISTANT, content=response.content, tool_calls=response.tool_calls or None)
            )

            # 步骤 2：判断是否包含工具调用
            if not response.tool_calls:
                # 无工具调用 → LLM 已产出最终文本答案
                return response.content

            # 步骤 3：并行执行所有工具调用
            tool_results = await self._execute_tools(response.tool_calls, state)
            # 将工具结果追加到对话历史，供下一轮 LLM 参考
            for tr in tool_results:
                state.messages.append(
                    Message(role=Role.TOOL, content=tr.content, tool_call_id=tr.tool_call_id)
                )

    def _build_system(self, user_system: str | None, prompt: str = "") -> str | None:
        """将用户系统提示词与按需匹配的技能内容组合为最终的系统消息。

        自动调用逻辑：根据用户 prompt 关键词匹配技能 pattern，仅注入相关技能。
        有技能但无匹配时注入简短使用说明；空存储不注入。
        """
        parts: list[str] = []
        if user_system:
            parts.append(user_system)
        if self.skills:
            settings = get_settings()
            matched = self.skills.matching_skills(
                prompt,
                threshold=settings.skill_match_threshold,
            )[: settings.skill_max_auto_invoke]

            if matched:
                # 有匹配：注入相关技能内容
                contents = []
                for name in matched:
                    raw = self.skills.load(name)
                    if raw:
                        contents.append(raw)
                if contents:
                    block = "\n\n---\n\n".join(contents)
                    parts.append(
                        f"<skills>\n"
                        f"The following skills are relevant to the user's request:\n\n"
                        f"{block}\n\n"
                        f"You can use skill_list to see all skills, "
                        f"skill_create to add new ones, or skill_update to modify.\n"
                        f"</skills>"
                    )
                    logger.debug("Auto-invoked %d skill(s): %s", len(matched), matched)
            elif self.skills.list_skills():
                # 有技能但无匹配：注入使用说明
                parts.append(
                    "<skills>\n"
                    "No skills matched the current request. "
                    "You can use skill_create to save reusable patterns, "
                    "skill_list to browse existing skills, or skill_update to refine them.\n"
                    "</skills>"
                )
            # 空存储 → 不注入任何技能内容
        return "\n\n".join(parts) if parts else None

    async def _call_provider(self, state: AgentState) -> ProviderResponse:
        """通过中间件链（或直接）调用 Provider。

        若配置了中间件，则构建 compose 链依次执行；
        否则直接调用 provider.send()。
        """
        tools = self.registry.enabled_schemas()  # 获取所有已启用的工具 Schema

        # 内层 handler：实际调用 Provider
        async def handler(req: Request) -> ProviderResponse:
            return await self.provider.send(
                req.messages,
                tools=req.tools or None,
            )

        # 有中间件 → 构建链式调用
        if self.middlewares:
            chain = compose(self.middlewares, handler)
            return await chain(Request(messages=state.messages, tools=tools))

        # 无中间件 → 直接调用
        return await handler(Request(messages=state.messages, tools=tools))

    async def _execute_tools(
        self, calls: list[ToolCall], state: AgentState
    ) -> list[ToolResult]:
        """并行执行多个工具调用。

        使用 asyncio.gather 实现并发，所有工具同时执行，
        全部完成后统一返回结果列表。
        """
        tasks = [self._execute_one(call) for call in calls]
        results = await asyncio.gather(*tasks)
        state.results.extend(results)  # 累积到 AgentState 的结果记录
        return list(results)

    async def _execute_one(self, call: ToolCall) -> ToolResult:
        """执行单个工具调用的完整流程。

        流程：安全检查 → 查找 handler → 执行 → 返回结果。
        任何环节的失败都包装为 is_error=True 的 ToolResult（不抛异常），
        确保 Agent 循环不会因单个工具失败而中断。
        """
        # 环节 1：安全检查（仅对 shell 工具生效）
        try:
            self.guard.check(call)
        except SafetyViolation as e:
            return ToolResult(tool_call_id=call.id, content=str(e), is_error=True)

        # 环节 2：从 Registry 查找已注册的 handler
        handler = self.registry.get_handler(call.name)
        if handler is None:
            return ToolResult(tool_call_id=call.id, content=f"Unknown tool: {call.name}", is_error=True)

        # 环节 3：执行 handler 并捕获结果
        try:
            result = await self._invoke(handler, call)
            content = str(result) if result is not None else ""
            return ToolResult(tool_call_id=call.id, content=content)
        except Exception as e:
            logger.exception("Tool %s failed", call.name)
            return ToolResult(tool_call_id=call.id, content=f"Tool error: {e}", is_error=True)

    async def _invoke(self, handler: object, call: ToolCall) -> object:
        """调用工具 handler，自动适配同步/异步函数。

        通过 asyncio.iscoroutinefunction 检测 handler 类型：
        - 异步函数 → await handler(**arguments)
        - 同步函数 → handler(**arguments)
        """
        if asyncio.iscoroutinefunction(handler):
            return await handler(**call.arguments)
        return handler(**call.arguments)
