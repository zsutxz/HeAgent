"""智能路由 Provider — 按请求内容在多个模型间自动选择（如 flash 快速版 / pro 深度版）。

与 ``SwitchableProvider``（手动切换 + 出错回退）和 ``ProviderChain``（纯故障回退）
不同，``RoutingProvider`` 在**每次调用前**由 ``Router`` 根据请求特征（消息历史 +
工具列表）**主动**决定用哪个 provider——这是「按任务复杂度路由」，而非「出错才切换」。

典型用法（DeepSeek 的 flash/pro 类比）：

    fast = OpenAIProvider(api_key="sk-...", model="deepseek-v4-flash", base_url="https://api.deepseek.com/v1")
    pro  = OpenAIProvider(api_key="sk-...", model="deepseek-v4-pro", base_url="https://api.deepseek.com/v1")
    router = HeuristicRouter(fast="fast", pro="pro")
    provider = RoutingProvider({"fast": fast, "pro": pro}, router, default="fast")

    await provider.send(messages)   # 普通问题 → fast
    await provider.send(messages)   # 带「分析/推理」关键词 → pro

判定**只作用于当前请求**（最近一条 USER 消息），且默认关闭「推理链续接」——历史里
命中过关键词不会让后续轮次持续走 pro（**默认立场：能用 fast 就用 fast**）。

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
from heagent.providers.retry import ErrorCategory, classify_exception
from heagent.types import Role

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from heagent.providers.base import BaseProvider
    from heagent.types import Message, ProviderResponse, ToolSchema

logger = logging.getLogger(__name__)

# 内置「推理/复杂任务」关键词（大小写不敏感；中文按子串匹配）。
# 命中任意一个即路由到 pro（深度模型）。可在 HeuristicRouter 构造时追加自定义词。
# 表内不含「为什么」「解释」「why」「explain」等**纯疑问词**：它们高频出现在普通问答里，
# 是 pro 的主要误判源（默认立场是尽量用 fast）；确需按其上 pro 时，用
# ROUTING_REASONING_KEYWORDS / reasoning_keywords= 追加回来即可。
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
    "compare",
    "refactor",
    "step by step",
    "think",
]

# 内置「中档任务」关键词（大小写不敏感；中文按子串匹配）。命中任意一个即路由到
# mid（中档模型）。仅当 HeuristicRouter 配置了 mid 档时生效；可在构造时追加自定义词。
DEFAULT_MID_KEYWORDS: list[str] = [
    # 中文
    "总结",
    "概括",
    "整理",
    "改写",
    "翻译",
    "润色",
    "缩写",
    "扩写",
    "列举",
    "查找",
    "提取",
    "转换",
    "格式化",
    "分类",
    "校对",
    # 英文
    "summarize",
    "summarise",
    "organize",
    "rewrite",
    "translate",
    "polish",
    "extract",
    "convert",
    "classify",
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

    **可选钩子**：额外实现 ``note_selection(name)`` 的 Router，会在每次实际选中 provider
    后被 ``RoutingProvider`` 回调（duck-typing，未实现则跳过）。自定义 Router 不实现该
    钩子也能正常工作。
    """

    def route(self, messages: list[Message], tools: list[ToolSchema] | None) -> RouteDecision:
        """根据消息历史（+ 可选工具列表）返回路由决策。"""
        ...


def _latest_user_text(messages: list[Message]) -> str | None:
    """返回**最近一条** USER 消息的小写文本；无 USER 消息时返回 None。

    **反向扫描**而非取列表末条：同一轮内的 tool 调用会把尾部消息变成 TOOL/ASSISTANT
    结果，取末条会漏判本轮请求；反向找最近一条 USER 消息既跳过尾部噪声，又保证只按
    **当前请求**判定复杂度——历史里命中过关键词不再让后续轮次持续走 pro。
    """
    for message in reversed(messages):
        if message.role == Role.USER:
            return message.content.lower()
    return None


class HeuristicRouter:
    """启发式路由：关键词检测（默认）+ 可选推理链续接。

    决策顺序（先命中先返回）：
      1. **推理链续接**（**默认关闭**，构造参数 ``continuity=True`` 时启用）：**上一轮
         实际选中的就是 pro** 且历史里仍有 ASSISTANT 消息携带 ``reasoning_content``
         （思考痕迹）→ 继续停留在 pro。**默认关闭**的理由：它会让「一次 pro」把整个
         会话钉在 pro（思考痕迹要等上下文压缩才消失），与「默认尽量用 fast」冲突。
         启用时判据以「上一轮是否真的用了 pro」为准，而非「历史里有没有
         ``reasoning_content``」：DeepSeek v4 的 flash 与 pro 都是思考模型、都返回
         ``reasoning_content``，按后者判定会让走过一次 flash 后永久锁死 pro。
      2. **复杂度关键词**：扫描**最近一条 USER 消息**（反向查找，跳过尾部的
         ASSISTANT/TOOL），命中 ``reasoning_keywords`` 中任一（大小写不敏感子串）→
         判定为复杂任务，路由到 pro。
      3. **中档关键词**（仅当配置了 ``mid`` 档时）：同样只扫描最近一条 USER 消息，命中
         ``mid_keywords`` 中任一 → 判定为中档任务，路由到 mid。
      4. **兜底**：否则路由到 fast（快速/廉价模型）。

    **成本语义（按当前请求判定，默认尽量用 fast）**：判据 2/3 只看最近一条 USER
    消息——历史里命中过关键词**不会**让后续轮次（含简单追问）持续走 pro；只有当前这条
    请求自身命中才走 pro。用「反向查找最近一条 USER 消息」而非「取列表末条」：同一轮内
    的 tool 调用会让尾部消息变成 TOOL 结果，此时最近一条 USER 消息仍是本轮请求，不会
    漏判——这正是旧版「扫描全部历史」想解决的问题，现以更精准的方式覆盖，且不再有
    「长会话全量按 pro 计费」的副作用。确需「一次 pro 就一直 pro」时开 ``continuity=True``；
    也确实想全程 fast 时用 ``/route fast`` 强制。

    这是**纯启发式**（非精确、非安全机制）：关键词可能误判（漏判简单任务 / 误判
    复杂任务），但对「多付一点钱 vs 少一次往返」的取舍足够实用。
    """

    def __init__(
        self,
        *,
        fast: str = "fast",
        pro: str = "pro",
        mid: str | None = None,
        reasoning_keywords: list[str] | None = None,
        mid_keywords: list[str] | None = None,
        continuity: bool = False,
    ) -> None:
        """初始化启发式路由。

        Args:
            fast: 快速模型的 provider 名（默认 "fast"）。
            pro: 深度模型的 provider 名（默认 "pro"）。
            mid: 可选；中档模型的 provider 名（如 "luna"）。传入 None 则退化为
                二档路由（fast/pro），不启用中档关键词匹配。
            reasoning_keywords: 追加到内置「复杂任务」关键词表的自定义词（合并，不覆盖）。
                传入 None 则仅用 DEFAULT_REASONING_KEYWORDS。
            mid_keywords: 追加到内置「中档任务」关键词表的自定义词（合并，不覆盖）。
                传入 None 则仅用 DEFAULT_MID_KEYWORDS（仅在配置 mid 时生效）。
            continuity: 是否启用「推理链续接」（判据 1）。默认 False = 尽量用 fast——
                启用后，上一轮走了 pro 且思考痕迹仍在历史中时，后续轮次即使没命中关键词
                也继续走 pro，代价是在思考痕迹被压缩掉之前一直按 pro 计费。
        """
        self._fast = fast
        self._pro = pro
        self._mid = mid
        self._continuity = continuity
        merged = list(DEFAULT_REASONING_KEYWORDS)
        if reasoning_keywords:
            merged.extend(reasoning_keywords)
        # 归一化为小写，匹配时对文本同样 lower()，保证英文大小写不敏感。
        self._keywords: list[str] = [k.lower() for k in merged]
        merged_mid = list(DEFAULT_MID_KEYWORDS)
        if mid_keywords:
            merged_mid.extend(mid_keywords)
        self._mid_keywords: list[str] = [k.lower() for k in merged_mid]
        # 上一次「实际选中」的 provider 名（由 RoutingProvider 经 note_selection 回调
        # 写入，含 forced / 兜底后的真实结果）；None = 尚未路由过。判据 1 用它判断
        # 「上一轮是不是 pro」——不能改用「历史里有没有 reasoning_content」（见类 docstring）。
        self._last_provider: str | None = None

    @property
    def last_provider(self) -> str | None:
        """上一次实际选中的 provider 名；None = 尚未路由过（观测 / 测试用）。"""
        return self._last_provider

    @property
    def continuity(self) -> bool:
        """是否启用「推理链续接」（判据 1）；默认 False（尽量用 fast）。"""
        return self._continuity

    def note_selection(self, name: str) -> None:
        """记录本次实际选中的 provider 名（由 ``RoutingProvider`` 在 ``_pick`` 后回调）。

        判据 1「推理链续接」据此判断上一轮是否真的用了 pro——而非扫描历史里是否存在
        ``reasoning_content``（flash 也返回该字段，扫描会让 pro 永久锁死）。
        """
        self._last_provider = name

    def route(self, messages: list[Message], tools: list[ToolSchema] | None) -> RouteDecision:
        """按决策顺序返回路由结果（见类 docstring）。"""
        # 1. 推理链续接（默认关闭，continuity=True 时启用）：上一轮实际选中 pro，且思考
        #    痕迹仍在历史中 → 继续 pro。只看「上一轮是不是 pro」而非「历史里有没有
        #    reasoning_content」：flash 也返回该字段，按后者会让走过一次 flash 后永久
        #    锁死 pro（fast 再也切不回）。
        if (
            self._continuity
            and self._last_provider == self._pro
            and any(msg.role == Role.ASSISTANT and msg.reasoning_content for msg in messages)
        ):
            return RouteDecision(provider=self._pro, reason="reasoning_continuity")

        # 2/3. 复杂度 + 中档关键词：**只扫描最近一条 USER 消息**（按当前请求判定，默认
        #      尽量用 fast）。反向查找以跳过尾部 ASSISTANT/TOOL——同一轮 tool 调用后尾部
        #      已不是 USER 消息，但本轮请求仍是最新的那一条，不会漏判。
        text = _latest_user_text(messages)
        if text is not None:
            for kw in self._keywords:
                if kw in text:
                    return RouteDecision(provider=self._pro, reason=f"keyword:{kw}")
            if self._mid is not None:
                for kw in self._mid_keywords:
                    if kw in text:
                        return RouteDecision(provider=self._mid, reason=f"mid_keyword:{kw}")

        # 4. 兜底 fast。
        return RouteDecision(provider=self._fast, reason="default_fast")


class RoutingProvider:
    """按请求内容智能路由到命名 provider 池（如 fast/pro）。

    每次 ``send``/``stream`` 前调用 ``Router.route`` 决定用哪个 provider，然后原样
    委托；与 SwitchableProvider/ProviderChain 的「跨 vendor 出错回退」不同层——本类
    在**无错误**的正常路径上做主动选择。

    **池内兄弟回退**：路由目标失败且错误为 RATE_LIMITED / TRANSIENT（与
    ``SwitchableProvider`` 同一套 ``classify_exception`` 分类）时，先尝试池内其余
    provider（如 flash 过载 → pro）再上抛——同 vendor 的 flash/pro 容量独立，比
    跨 vendor 粘性跳转（对话中途换模型、质量漂移）代价小。AUTH_FAILED /
    NON_TRANSIENT 不回退（换兄弟模型也不会好转），直接上抛给外层
    ``SwitchableProvider`` 按条目回退。流式仅在**首个 chunk 前**失败才改道（已
    开始输出后无法重放前缀）。

    ``_pick`` 解析出实际选中的 provider 后，若路由策略实现了可选钩子
    ``note_selection(name)`` 则回传（供 ``HeuristicRouter`` 判定「上一轮是否 pro」）。

    对 ``AgentLoop`` 完全透明（实现 BaseProvider 协议）。``last_decision`` 记录最近
    一次决策（观测/调试用，best-effort——单次字符串赋值在 CPython 下原子，不引入
    锁；并发下仅可能读到稍旧的决策，无正确性影响）。
    """

    def __init__(
        self,
        providers: dict[str, BaseProvider],
        router: Router,
        *,
        default: str,
        force: str | None = None,
    ) -> None:
        """初始化智能路由 provider。

        Args:
            providers: ``{名称: provider 实例}`` 池；名称即 Router 返回的 key。
            router: 路由策略，返回 ``RouteDecision``。
            default: Router 返回未知名称时的兜底 provider 名，必须在 providers 中。
            force: 可选；强制固定使用某个 provider 名（如 "pro"），None = 自动路由。
                可在运行时用 ``set_force()`` 动态切换（对应 ``/route pro|fast|auto``）。
        """
        if not providers:
            raise ValueError("RoutingProvider requires at least one provider")
        if default not in providers:
            raise ValueError(f"Default provider {default!r} not in provider pool")
        self._providers = dict(providers)
        self._router = router
        self._default = default
        self._force: str | None = None
        if force is not None:
            self.set_force(force)
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

    @property
    def force(self) -> str | None:
        """当前强制指定的 provider 名；None = 自动路由（启发式）。"""
        return self._force

    def set_force(self, name: str | None) -> None:
        """强制后续调用固定使用某个 provider；传入 None 恢复自动路由。

        传池外名称抛 ``ValueError``。设置后 ``_pick()`` 跳过 ``Router.route()``，
        直接使用强制项（reason="forced"）；``current_model`` 立即反映新模型。
        """
        if name is not None and name not in self._providers:
            raise ValueError(f"Forced provider {name!r} not in pool {sorted(self._providers)}")
        self._force = name

    @property
    def current_model(self) -> str:
        """最近一次路由实际选中的模型名；尚未路由时返回 default 模型。

        状态栏 / 观测层用它显示「当前模型」，而非 get_metadata().model 的
        池内全部模型列表（如 "fast:deepseek-v4-flash, pro:deepseek-v4-pro"）。
        若已 ``set_force`` 强制指定，则立即返回强制项的模型（不等下一次路由）。
        """
        if self._force is not None:
            return self._providers[self._force].get_metadata().model
        name = self._default
        if self.last_decision is not None and self.last_decision.provider in self._providers:
            name = self.last_decision.provider
        return self._providers[name].get_metadata().model

    def _pick(self, messages: list[Message], tools: list[ToolSchema] | None) -> tuple[str, BaseProvider]:
        """执行路由决策并解析为 (名称, 实例)；未知名称回退 default。

        若 ``set_force`` 已强制指定，则跳过 ``Router.route()`` 直接使用强制项。
        """
        if self._force is not None:
            decision = RouteDecision(provider=self._force, reason="forced")
        else:
            decision = self._router.route(messages, tools)
        name = decision.provider
        if name not in self._providers:
            # 路由策略返回了池外名称（配置漂移/自定义 Router 缺陷）→ 兜底 default，
            # 并在 reason 上打标，便于观测层发现异常。
            decision = RouteDecision(provider=self._default, reason=f"fallback_from:{name}({decision.reason})")
            name = self._default
        self.last_decision = decision
        self._note_selection(name)
        return name, self._providers[name]

    def _note_selection(self, name: str) -> None:
        """把本次实际选中的 provider 名回传给路由策略（若其实现了可选钩子）。

        ``HeuristicRouter`` 借此把「推理链续接」收窄为「上一轮实际是 pro」。钩子为
        duck-typing 可选——只实现 ``route`` 的自定义 Router 不受影响。
        """
        hook = getattr(self._router, "note_selection", None)
        if callable(hook):
            hook(name)

    @staticmethod
    def _is_fallback_error(error: Exception) -> bool:
        """是否触发池内兄弟回退——与 ``SwitchableProvider`` 同一套分类，避免两套语义漂移。"""
        return classify_exception(error) in (ErrorCategory.RATE_LIMITED, ErrorCategory.TRANSIENT)

    def _sibling(self, name: str) -> BaseProvider | None:
        """返回池内除 ``name`` 外的第一个 provider（按插入序，确定性）；无兄弟则 None。"""
        for other_name, provider in self._providers.items():
            if other_name != name:
                return provider
        return None

    # -- BaseProvider 协议实现 --

    async def send(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
    ) -> ProviderResponse:
        """按路由决策委托给选中的 provider 完成单次调用。

        路由目标失败且为限流/瞬时错误时，回退到池内兄弟（见类 docstring）。
        """
        name, provider = self._pick(messages, tools)
        logger.info("Routing → %s (reason=%s)", name, self.last_decision.reason if self.last_decision else "")
        try:
            return await provider.send(messages, tools=tools)
        except Exception as exc:
            if not self._is_fallback_error(exc):
                raise
            sibling = self._sibling(name)
            if sibling is None:
                raise
            logger.warning("Routing target %s failed (%s); retrying with in-pool sibling", name, exc)
            return await sibling.send(messages, tools=tools)

    async def stream(
        self,
        messages: list[Message],
        *,
        tools: list[ToolSchema] | None = None,
    ) -> AsyncIterator[ProviderResponse]:
        """流式版：按路由决策委托，逐 chunk 透传。

        仅在**首个 chunk 产生前**失败才改道兄弟（已开始输出后无法重放前缀，不改道）。
        """
        name, provider = self._pick(messages, tools)
        logger.info("Routing (stream) → %s (reason=%s)", name, self.last_decision.reason if self.last_decision else "")
        iterator = provider.stream(messages, tools=tools)
        try:
            first = await iterator.__anext__()
        except StopAsyncIteration:
            return
        except Exception as exc:
            if not self._is_fallback_error(exc):
                raise
            sibling = self._sibling(name)
            if sibling is None:
                raise
            logger.warning("Routing target %s failed in stream (%s); retrying with in-pool sibling", name, exc)
            iterator = sibling.stream(messages, tools=tools)
            first = await iterator.__anext__()
        yield first
        async for chunk in iterator:
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


def active_model(provider: object) -> str | None:
    """递归解包嵌套 provider，返回「当前实际使用的模型名」（观测 / 状态栏用）。

    RoutingProvider 通过 ``current_model`` 暴露当前实际命中的模型；包装器
    （SwitchableProvider / ProviderChain / KeyRotatingProvider）通过 ``current``
    指向活跃子 provider。递归解包找到 RoutingProvider 的 ``current_model``；
    找不到则返回 None（调用方回退 ``get_metadata().model``）。

    供 CLI 提示符前缀 / GUI 状态栏复用，避免各处重复鸭子类型判断。
    """
    seen = 0
    while provider is not None and seen < 10:
        model = getattr(provider, "current_model", None)
        if isinstance(model, str) and model:
            return model
        child = getattr(provider, "current", None)
        if child is None or child is provider:
            return None
        provider = child
        seen += 1
    return None
