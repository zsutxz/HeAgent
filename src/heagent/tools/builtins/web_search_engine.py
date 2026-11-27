"""web_search 引擎层 — 检索引擎抽象、Tavily/Zhipu/DuckDuckGo 实现、按配置名构造的 registry。

引擎可插拔契约：换引擎只改配置声明（``web_search_engine``），src 零 diff；
新增引擎 = 实现 ``SearchEngine`` 协议 + ``register_engine`` 注册工厂。

错误分类复用 ``providers/retry.py`` 的 ``classify_error``（四类容错面的纯函数判据）：
引擎抛 ``SearchEngineError``（携带 status_code 与分类），不自动重试——重试立场归调用方。

安全立场与 ``web_fetch`` 一致（CLAUDE.md）：网络面防护仅为 defense-in-depth，
OS 级沙箱兜底；凭据只经 env/config 注入，引擎不打密钥日志。
"""

from __future__ import annotations

import html
import logging
import re
import urllib.parse
from typing import TYPE_CHECKING, Protocol

import httpx
from pydantic import BaseModel

from heagent.providers.retry import ErrorCategory, classify_error
from heagent.pub.exceptions import ProviderError, ToolError

# 检索引擎响应状态分档（3xx = 网关劫持疑点，4xx+ = 请求侧失败）。
_HTTP_REDIRECT_MIN = 300
_HTTP_REDIRECT_MAX = 400
_HTTP_CLIENT_ERROR_MIN = 400

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# 检索引擎查询长度上限（API 契约：超限 4xx，引擎侧 fail-fast；三引擎共用）
_MAX_QUERY_CHARS = 400
# 引擎参数钳位上限；注入上下文前的确定性截断预算在工具面
_MAX_RESULTS_CAP = 20
# 引擎调用超时（总读 + 单独 connect）
_ENGINE_TIMEOUT = httpx.Timeout(20.0, connect=5.0)
# 错误分类自携人类可读指引（模型可见面，指引是确定性文本——重试立场仍归调用方）
_CATEGORY_HINTS: dict[ErrorCategory, str] = {
    ErrorCategory.RATE_LIMITED: "检索引擎限流，稍后重试；",
    ErrorCategory.AUTH_FAILED: "检索引擎认证失败，检查 WEB_SEARCH_API_KEY；",
    ErrorCategory.TRANSIENT: "检索引擎临时错误，可稍后重试；",
    ErrorCategory.NON_TRANSIENT: "检索引擎拒绝了请求（查询或参数问题），重试无效；",
}


class SearchResult(BaseModel):
    """单条检索结果（跨模块数据走 Pydantic）。"""

    title: str
    url: str
    snippet: str = ""


class SearchEngineError(ToolError):
    """检索引擎调用失败（携带 status_code 与分类）。

    分类面与 providers 容错面同名同义（classify_error 判据），但立场不同：
    检索错误是否重试由调用方依分类自行决定，引擎不自动重试。
    """

    def __init__(
        self,
        message: str = "",
        *,
        status_code: int | None = None,
        category: ErrorCategory | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.category = category


class SearchEngine(Protocol):
    """检索引擎协议（结构化类型，实现类无需显式继承）。"""

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """检索并返回结果列表；失败显性报错，不返回空列表冒充成功。"""
        ...


class _BearerPostSearchEngine:
    """POST JSON + Bearer header 检索引擎的共用骨架（Tavily/Zhipu 同纪律）。

    密钥/查询前置校验、HTTP 失败分类、响应形状守卫全部共面，引擎差异只落在三个声明点：
    端点 ``_ENDPOINT``、请求体 ``_build_body``、响应键位 ``_LIST_KEY``/``_URL_KEY``。
    未配密钥时构造成功、调用显性报错——「工具常在」契约的引擎侧实现：
    注册面不因缺密钥收窄，缺密钥的失败在调用时显性暴露。
    """

    _ENDPOINT: str
    _ENGINE_LABEL: str  # 缺密钥报错文案里的引擎名
    _LIST_KEY: str  # 响应中结果列表的键名（Tavily=results，智谱=search_result）
    _URL_KEY: str  # 单条结果中链接的键名（Tavily=url，智谱=link）

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    def _build_body(self, q: str, n: int) -> dict[str, object]:
        """构造引擎私有请求体（入参已过校验：q 非空且不超长，n 已钳位）。"""
        raise NotImplementedError

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """执行一次搜索请求并返回结构化结果列表（HTTP 失败按统一分类上抛，不吞错）。"""
        if not self._api_key:
            raise SearchEngineError(
                f"web_search 未配置引擎密钥：经 WEB_SEARCH_API_KEY（env）或 web_search_api_key（config）配置 {self._ENGINE_LABEL} key"
            )
        q = query.strip()
        if not q:
            raise SearchEngineError("查询不能为空")
        if len(q) > _MAX_QUERY_CHARS:
            raise SearchEngineError(f"查询过长（>{_MAX_QUERY_CHARS} 字符），当前 {len(q)} 字符")

        n = min(max(max_results, 1), _MAX_RESULTS_CAP)
        headers = {"Authorization": f"Bearer {self._api_key}"}
        body = self._build_body(q, n)
        try:
            # trust_env=False：与 web_fetch 同口径——忽略进程代理环境变量，出站直连
            async with httpx.AsyncClient(timeout=_ENGINE_TIMEOUT, trust_env=False) as client:
                response = await client.post(self._ENDPOINT, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise SearchEngineError(f"检索请求超时: {q[:50]}", category=ErrorCategory.TRANSIENT) from exc
        except httpx.RequestError as exc:
            raise SearchEngineError(f"检索请求失败: {exc}", category=ErrorCategory.TRANSIENT) from exc
        if _HTTP_REDIRECT_MIN <= response.status_code < _HTTP_REDIRECT_MAX:
            raise SearchEngineError(
                f"检索引擎重定向 {response.status_code}（API 直连不应重定向，疑网关劫持）",
                status_code=response.status_code,
                category=ErrorCategory.TRANSIENT,
            )
        if response.status_code >= _HTTP_CLIENT_ERROR_MIN:
            # 分类复用容错面判据：包 ProviderError 走 classify_error 的标准入口；
            # 分类自携人类可读指引（模型可见面，指引是确定性文本——重试立场仍归调用方）
            provider_error = ProviderError(response.text[:200], status_code=response.status_code)
            category = classify_error(provider_error)
            raise SearchEngineError(
                f"{_CATEGORY_HINTS[category]}检索引擎 HTTP {response.status_code}: {response.text[:200]}",
                status_code=response.status_code,
                category=category,
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise SearchEngineError(
                "检索引擎返回非 JSON 响应",
                status_code=response.status_code,
                category=ErrorCategory.NON_TRANSIENT,
            ) from exc

        if not isinstance(data, dict) or not isinstance(data.get(self._LIST_KEY), list):
            raise SearchEngineError(
                f"检索引擎响应形状非法（非对象或缺 {self._LIST_KEY} 列表，契约漂移）: {response.text[:200]}",
                status_code=response.status_code,
                category=ErrorCategory.NON_TRANSIENT,
            )

        results: list[SearchResult] = []
        dropped = 0
        for item in data[self._LIST_KEY]:
            if not isinstance(item, dict) or not item.get(self._URL_KEY):
                dropped += 1
                continue
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=item.get(self._URL_KEY, ""),
                    snippet=item.get("content", ""),
                )
            )
        if not results and dropped:
            raise SearchEngineError(
                f"检索引擎返回 {dropped} 条但全部缺 {self._URL_KEY}（契约漂移），不冒充零命中",
                status_code=response.status_code,
                category=ErrorCategory.NON_TRANSIENT,
            )
        if dropped:
            logger.warning(
                "web_search 引擎返回 %d 条中 %d 条缺 %s 或形状非法，已丢弃",
                len(data[self._LIST_KEY]),
                dropped,
                self._URL_KEY,
            )
        return results


class TavilyEngine(_BearerPostSearchEngine):
    """Tavily 检索引擎（POST JSON + Bearer header）。

    调用纪律见 ``_BearerPostSearchEngine``；本类只声明 Tavily 的端点与请求/响应键位。
    """

    _ENDPOINT = "https://api.tavily.com/search"
    _ENGINE_LABEL = "Tavily"
    _LIST_KEY = "results"
    _URL_KEY = "url"

    def _build_body(self, q: str, n: int) -> dict[str, object]:
        return {"query": q, "max_results": n}


class ZhipuEngine(_BearerPostSearchEngine):
    """智谱检索引擎（GLM 生态，POST JSON + Bearer header）。

    走智谱官方 Web Search API（``search_std`` 标准引擎），title/link/content 映射到
    SearchResult.title/url/snippet；调用纪律与 Tavily 共面（见 ``_BearerPostSearchEngine``）：
    缺 link 的契约漂移显性失败，不冒充零命中。
    """

    _ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/web_search"
    _ENGINE_LABEL = "智谱"
    _LIST_KEY = "search_result"
    _URL_KEY = "link"

    def _build_body(self, q: str, n: int) -> dict[str, object]:
        return {"search_engine": "search_std", "search_query": q, "search_result_count": n}


# ── DuckDuckGo 免 key 引擎（HTML 端点解析，刮削面）─────────────────────────
# DDG 对默认客户端 UA 返回 403，必须带浏览器 UA（UA 是模块级常量字符串，非配置——常量≠配置）
_DDG_ENDPOINT = "https://html.duckduckgo.com/html/"
_DDG_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
# 刮削面反爬拦截码：免 key 引擎的 403 是反爬不是认证失败，不能走 classify_error 的 AUTH 桶
_DDG_FORBIDDEN_STATUS = 403
# 解析锚点（DDG HTML 端点的 class 约定）
_DDGS_BLOCK_MARKER = "result__body"  # 结果块锚点，块内再找标题锚与摘要锚
_DDGS_TITLE_MARKER = "result__a"
_DDGS_SNIPPET_MARKER = "result__snippet"
_DDGS_NO_RESULTS_MARKER = "no-results"  # DDG 官方零命中标记


def _anchor_text_and_href(block: str, class_marker: str) -> tuple[str, str] | None:
    """取块内 class 含 ``class_marker`` 的第一个 <a>，返回 ``(href, 内文)``；无则 ``None``。

    内文清洗固定「先剥标签后 unescape」——先 unescape 会把实体还原成 <>，被下一步误剥。
    """
    match = re.search(r'<a\b[^>]*class="[^"]*' + class_marker + r'[^"]*"[^>]*>(.*?)</a>', block, re.DOTALL)
    if match is None:
        return None
    href_match = re.search(r'href="([^"]*)"', match.group(0))
    href = href_match.group(1) if href_match else ""
    text = html.unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip()
    return href, text


def _resolve_ddg_href(href: str) -> str:
    """解出 DDG 跳转链（``/l/?uddg=<urlencoded 真实 URL>&rut=...``）的真实 URL；直链原样。"""
    if "uddg=" not in href:
        return href
    values = urllib.parse.parse_qs(urllib.parse.urlparse(href).query).get("uddg")
    return values[0] if values and values[0] else href


class DuckDuckGoEngine:
    """DuckDuckGo 免 key 检索引擎（POST HTML 端点 + stdlib 解析，刮削面）。

    无 key、响应是 HTML，不适配 ``_BearerPostSearchEngine``（Bearer-JSON 骨架），自含实现
    ``SearchEngine`` 协议；查询校验、钳位、超时与错误分类与 API 引擎共面（复用模块常量与
    ``classify_error``）。刮削面特有显性失败纪律：页面带 no-results 标记 → 真零命中返回
    ``[]``；无标记且解析出 0 条 → 显性报错（反爬拦截或结构漂移），不冒充零命中。
    """

    def __init__(self, api_key: str = "") -> None:
        # 免 key：按 registry 工厂签名收下 api_key 但忽略，缺 key 不报错、正常工作
        self._api_key = api_key

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        """执行一次 DDG HTML 搜索并解析结构化结果（HTTP/解析失败显性报错，不吞错）。"""
        q = query.strip()
        if not q:
            raise SearchEngineError("查询不能为空")
        if len(q) > _MAX_QUERY_CHARS:
            raise SearchEngineError(f"查询过长（>{_MAX_QUERY_CHARS} 字符），当前 {len(q)} 字符")

        # HTML 端点无数量参数，钳位口径与 API 引擎一致，只作用于客户端截取
        n = min(max(max_results, 1), _MAX_RESULTS_CAP)
        try:
            async with httpx.AsyncClient(timeout=_ENGINE_TIMEOUT, trust_env=False) as client:
                response = await client.post(_DDG_ENDPOINT, data={"q": q}, headers={"User-Agent": _DDG_USER_AGENT})
        except httpx.TimeoutException as exc:
            raise SearchEngineError(f"检索请求超时: {q[:50]}", category=ErrorCategory.TRANSIENT) from exc
        except httpx.RequestError as exc:
            raise SearchEngineError(f"检索请求失败: {exc}", category=ErrorCategory.TRANSIENT) from exc
        if _HTTP_REDIRECT_MIN <= response.status_code < _HTTP_REDIRECT_MAX:
            raise SearchEngineError(
                f"检索引擎重定向 {response.status_code}（直连不应重定向，疑网关劫持）",
                status_code=response.status_code,
                category=ErrorCategory.TRANSIENT,
            )
        if response.status_code == _DDG_FORBIDDEN_STATUS:
            raise SearchEngineError(
                "DuckDuckGo 反爬拦截（HTTP 403，浏览器 UA 未被接受）；长期依赖请配置 tavily/zhipu 引擎",
                status_code=response.status_code,
                category=ErrorCategory.NON_TRANSIENT,
            )
        if response.status_code >= _HTTP_CLIENT_ERROR_MIN:
            # 其余 >=400 走既有判据（429 -> RATE_LIMITED 等），指引文本随分类自带上浮
            provider_error = ProviderError(response.text[:200], status_code=response.status_code)
            category = classify_error(provider_error)
            raise SearchEngineError(
                f"{_CATEGORY_HINTS[category]}检索引擎 HTTP {response.status_code}: {response.text[:200]}",
                status_code=response.status_code,
                category=category,
            )

        page = response.text
        if re.search(r'class="[^"]*' + _DDGS_NO_RESULTS_MARKER + r'[^"]*"', page):
            return []  # DDG 官方零命中标记：真零命中，不进入解析
        results: list[SearchResult] = []
        for block in re.split(r'class="[^"]*' + _DDGS_BLOCK_MARKER + r'[^"]*"', page)[1:]:
            anchor = _anchor_text_and_href(block, _DDGS_TITLE_MARKER)
            if anchor is None or not anchor[0]:
                continue
            snippet = _anchor_text_and_href(block, _DDGS_SNIPPET_MARKER)
            results.append(
                SearchResult(
                    title=anchor[1],
                    url=_resolve_ddg_href(html.unescape(anchor[0])),
                    snippet=snippet[1] if snippet else "",
                )
            )
        if not results:
            # 无标记又解析不出结果 = 反爬软拦截页或结构漂移：显性失败，不冒充零命中
            raise SearchEngineError(
                "DuckDuckGo 页面解析出 0 条结果且无 no-results 标记（疑反爬拦截或页面结构漂移），不冒充零命中",
                status_code=response.status_code,
                category=ErrorCategory.NON_TRANSIENT,
            )
        return results[:n]


_ENGINE_REGISTRY: dict[str, Callable[[str], SearchEngine]] = {}


def register_engine(name: str, factory: Callable[[str], SearchEngine]) -> None:
    """注册引擎工厂（name → 工厂；工厂收 api_key）。

    重复注册同名显性报错——不允许静默 last-wins 换掉已注册引擎（扩展点卫生）。
    """
    if name in _ENGINE_REGISTRY:
        raise SearchEngineError(f"检索引擎 '{name}' 已注册，禁止覆盖")
    _ENGINE_REGISTRY[name] = factory


def _make_tavily(api_key: str) -> SearchEngine:
    return TavilyEngine(api_key=api_key)


register_engine("tavily", _make_tavily)


def _make_zhipu(api_key: str) -> SearchEngine:
    return ZhipuEngine(api_key=api_key)


register_engine("zhipu", _make_zhipu)


def _make_duckduckgo(api_key: str) -> SearchEngine:
    # 免 key：api_key 按 registry 工厂签名收下即忽略，三引擎工厂签名统一
    return DuckDuckGoEngine(api_key=api_key)


register_engine("duckduckgo", _make_duckduckgo)


def create_engine(name: str, api_key: str = "") -> SearchEngine:
    """按配置声明的引擎名构造引擎；未知名 fail-loud（列出可用引擎）。"""
    factory = _ENGINE_REGISTRY.get(name)
    if factory is None:
        known = ", ".join(sorted(_ENGINE_REGISTRY))
        raise SearchEngineError(f"未知检索引擎 '{name}'（可用: {known}）")
    return factory(api_key)
