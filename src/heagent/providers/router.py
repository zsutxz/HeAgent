"""智能路由 Provider — 按请求内容在多个模型间自动选择（如 flash 快速版 / pro 深度版）。

与 ``SwitchableProvider``（手动切换 + 出错回退）和 ``ProviderChain``（纯故障回退）
不同，``RoutingProvider`` 在**每次调用前**由 ``Router`` 根据请求特征（消息历史 +
工具列表）**主动**决定用哪个 provider——这是「按任务复杂度路由」，而非「出错才切换」。

典型用法（DeepSeek 的 flash/pro 类比）：

    fast = OpenAIProvider(api_key="sk-...", model="deepseek-chat", base_url="https://api.deepseek.com/v1")
    pro  = OpenAIProvider(api_key="sk-...", model="deepseek-reasoner", base_url="https://api.deepseek.com/v1")
    router = HeuristicRouter(fast="fast", pro="pro")
    provider = RoutingProvider({"fast": fast, "pro": pro}, router, default="fast")

    await provider.send(messages)   # 普通问题 → fast
    await provider.send(messages)   # 带「分析/推理」关键词 → pro

对 ``AgentLoop`` 完全透明（实现 ``BaseProvider`` 协议），零改动注入。

**非安全边界说明**：路由决策是启发式（关键词 + 推理链续接），仅影响「用哪个模型」，
与安全无关；``Router`` 返回的 provider 名不来自任何不可信输入的可执行路径，仅作为
dict 键查找。与框架内其它治理机制一样，本模块不构成安全边界。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from pydantic import BaseModel

from heagent.providers.base import ProviderMetadata
from heagent.types import Role

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from heagent.providers.base import BaseProvider
    from heagent.types import Message, ProviderResponse, ToolSchema

logger = logging.getLogger(__name__)

# 内置「推理/复杂任务」关键词（大小写不敏感；中文按子串匹配）。
# 命中任意一个即路由到 pro（深度模型）。可在 HeuristicRouter 构造时追加自定义词。
DEFAULT_REASONING_KEYWORDS: list[str] = [
    # 中文
    "分析",
    "推理",
    "证明",
    "推导",
    "数学",
    "复杂",
    "深度思考",
    "权衡",
    "对比",
    "规划",
    "设计",
    "算法",
    "架构",
    "代码审查",
    "调试",
    "原理",
    "为什么",
    "解释",
    # 英文
    "analyze",
    "reason",
    "prove",
    "math",
    "complex",
    "plan",
    "design",
    "algorithm",
    "architecture",
    "debug",
    "explain",
    "why",
    "compare",
    "refactor",
    "step by step",
    "think",
]


class RouteDecision(BaseModel):
    """单次路由决策结果。

    provider: 命中的 provider 名（如 "fast"/"pro"）；RoutingProvider 保证其必在池中，
        未命中时回退到 default 并改写 reason。
    reason: 命中理由（观测/调试用，记录到日志与 last_decision）。
    """

    provider: str
    reason: str


@runtime_checkable
class Router(Protocol):
    """路由策略协议：根据请求内容决定用哪个 provider。

    实现只需 ``route`` 方法，返回 ``RouteDecision``。通过 @runtime_checkable 支持
    isinstance() 检查；与 BaseProvider 一样无需继承——鸭子类型即可。
    """

    def route(self, messages: list[Message], tools: list[ToolSchema] | None) -> RouteDecision:
        """根据消息历史（+ 可选工具列表）返回路由决策。"""
        ...


class HeuristicRouter:
    """启发式路由：推理链续接 + 关键词检测。

    决策顺序（先命中先返回）：
      1. **推理链续接**：任一条 ASSISTANT 消息携带 ``reasoning_content``（思考模型
         的推理痕迹）→ 说明正处在多轮推理链中途，切回非思考模型会打断推理链，
         故强制停留在 pro。
      2. **复杂度关键词**：扫描全部 USER 消息，命中 ``reasoning_keywords`` 中任一
         （大小写不敏感子串）→ 判定为复杂任务，路由到 pro。
      3. **兜底**：否则路由到 fast（快速/廉价模型）。

    这是**纯启发式**（非精确、非安全机制）：关键词可能误判（漏判简单任务 / 误判
    复杂任务），但对「多付一点钱 vs 少一次往返」的取舍足够实用；推理链续接则保证
    pro 模型发起的推理不会被 flash 模型无推理地截断。
    """

    def __init__(
        self,
        *,
        fast: str = "fast",
        pro: str = "pro",
        reasoning_keywords: list[str] | None = None,
    ) -> None:
        """初始化启发式路由。

        Args:
            fast: 快速模型的 provider 名（默认 "fast"）。
            pro: 深度模型的 provider 名（默认 "pro"）。
            reasoning_keywords: 追加到内置关键词表的自定义词（与内置词合并，不覆盖）。
                传入 None 则仅用 DEFAULT_REASONING_KEYWORDS。
        """
        self._fast = fast
        self._pro = pro
        merged = list(DEFAULT_REASONING_KEYWORDS)
        if reasoning_keywords:
            merged.extend(reasoning_keywords)
        # 归一化为小写，匹配时对文本同样 lower()，保证英文大小写不敏感。
        self._keywords: list[str] = [k.lower() for k in merged]

    def route(self, messages: list[Message], tools: list[ToolSchema] | None) -> RouteDecision:
        """按决策顺序返回路由结果（见类 docstring）。"""
        # 1. 推理链续接：ASSISTANT 消息携带 reasoning_content → 停留 pro。
        for msg in messages:
            if msg.role == Role.ASSISTANT and msg.reasoning_content:
                return RouteDecision(provider=self._pro, reason="reasoning_continuity")

        # 2. 复杂度关键词：扫描 USER 消息。
        for msg in messages:
            if msg.role != Role.USER:
                continue
            text = msg.content.lower()
            for kw in self._keywords:
                if kw in text:
                    return RouteDecision(provider=self._pro, reason=f"keyword:{kw}")

        # 3. 兜底 fast。
        return RouteDecision(provider=self._fast, reason="default_fast")


class RoutingProvider:
    """按请求内容智能路由到命名 provider 池（如 fast/pro）。

    每次 ``send``/``stream`` 前调用 ``Router.route`` 决定用哪个 provider，然后原样
    委托；与 SwitchableProvider/ProviderChain 的「出错回退」正交——本类在**无错误**
    的正常路径上做主动选择。

    对 ``AgentLoop`` 完全透明（实现 BaseProvider 协议）。``last_decision`` 记录最近
    一次决策（观测/调试用，best-effort——单次字符串赋值在 CPython 下原子，不引入
    锁；并发下仅可能读到稍旧的决策，无正确性影响）。
    """

    def __init__(self, providers: dict[str, BaseProvider], router: Router, *, default: str) -> None:
        """初始化智能路由 provider。

        Args:
            providers: ``{名称: provider 实例}`` 池；名称即 Router 返回的 key。
            router: 路由策略，返回 ``RouteDecision``。
            default: Router 返回未知名称时的兜底 provider 名，必须在 providers 中。
        """
        if not providers:
            raise ValueError("RoutingProvider requires at least one provider")
        if default not in providers:
            raise ValueError(f"Default provider {default!r} not in provider pool")
        self._providers = dict(providers)
        self._router = router
        self._default = default
        self.last_decision: RouteDecision | None = None

    # -- 公共 API --

    @property
    def names(self) -> list[str]:
        """池中所有 provider 名称。"""
        return list(self._providers.keys())

    @property
    def default(self) -> str:
        """兜底 provider 名。"""
        return self._default

    def _pick(self, messages: list[Message], tools: list[ToolSchema] | None) -> tuple[str, BaseProvider]:
        """执行路由决策并解析为 (名称, 实例)；未知名称回退 default。"""
        decision = self._router.route(messages, tools)
        name = decision.provider
        if name not in self._providers:
            # 路由策略返回了池外名称（配置漂移/自定义 Router 缺陷）→ 兜底 default，
            # 并在 reason 上打标，便于观测层发现异常。
            decision = RouteDecision(provider=self._default, reason=f"fallback_from:{name}({decision.reason})")
            name = self._default
        self.last_decision = decision
        return name, self._providers[name]

    # -- BaseProvider 协议实现 --

    async def send(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
    ) -> ProviderResponse:
        """按路由决策委托给选中的 provider 完成单次调用。"""
        name, provider = self._pick(messages, tools)
        logger.info("Routing → %s (reason=%s)", name, self.last_decision.reason if self.last_decision else "")
        return await provider.send(messages, tools=tools)

    async def stream(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
    ) -> AsyncIterator[ProviderResponse]:
        """流式版：按路由决策委托，逐 chunk 透传（不在流中途改道，避免重放重复前缀）。"""
        name, provider = self._pick(messages, tools)
        logger.info("Routing (stream) → %s (reason=%s)", name, self.last_decision.reason if self.last_decision else "")
        async for chunk in provider.stream(messages, tools=tools):
            yield chunk

    def get_metadata(self) -> ProviderMetadata:
        """返回路由池的能力描述：model 列出各 provider 的模型；能力取「全支持」交集。

        supports_streaming / supports_tools 取 ``all``（保守）：只有全部池内 provider
        都支持时才宣称支持，避免路由到不支持某能力的 provider 时上层误判。
        """
        models = ", ".join(f"{k}:{p.get_metadata().model}" for k, p in self._providers.items())
        return ProviderMetadata(
            name="routing",
            model=models,
            supports_streaming=all(p.get_metadata().supports_streaming for p in self._providers.values()),
            supports_tools=all(p.get_metadata().supports_tools for p in self._providers.values()),
        )
