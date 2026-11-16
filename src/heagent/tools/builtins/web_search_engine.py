"""web_search 引擎层 — 检索引擎抽象、Tavily 实现、按配置名构造的 registry。

引擎可插拔契约：换引擎只改配置声明（``web_search_engine``），src 零 diff；
新增引擎 = 实现 ``SearchEngine`` 协议 + ``register_engine`` 注册工厂。

错误分类复用 ``providers/retry.py`` 的 ``classify_error``（四类容错面的纯函数判据）：
引擎抛 ``SearchEngineError``（携带 status_code 与分类），不自动重试——重试立场归调用方。

安全立场与 ``web_fetch`` 一致（CLAUDE.md）：网络面防护仅为 defense-in-depth，
OS 级沙箱兜底；凭据只经 env/config 注入，引擎不打密钥日志。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol

import httpx
from pydantic import BaseModel

from heagent.providers.retry import ErrorCategory, classify_error
from heagent.pub.exceptions import ProviderError, ToolError

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

# Tavily API 查询长度上限（API 契约：超限 4xx，引擎侧 fail-fast）
_MAX_QUERY_CHARS = 400
# 引擎参数钳位上限；注入上下文前的确定性截断预算在工具面
_MAX_RESULTS_CAP = 20
# 引擎调用超时（总读 + 单独 connect）
_ENGINE_TIMEOUT = httpx.Timeout(20.0, connect=5.0)


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


class TavilyEngine:
    """Tavily 检索引擎（POST JSON + Bearer header）。

    未配密钥时构造成功、调用显性报错——「工具常在」契约的引擎侧实现：
    注册面不因缺密钥收窄，缺密钥的失败在调用时显性暴露。
    """

    _ENDPOINT = "https://api.tavily.com/search"

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key

    async def search(self, query: str, max_results: int = 5) -> list[SearchResult]:
        if not self._api_key:
            raise SearchEngineError(
                "web_search 未配置引擎密钥：经 WEB_SEARCH_API_KEY（env）或 web_search_api_key（config）配置 Tavily key"
            )
        q = query.strip()
        if not q:
            raise SearchEngineError("查询不能为空")
        if len(q) > _MAX_QUERY_CHARS:
            raise SearchEngineError(f"查询过长（>{_MAX_QUERY_CHARS} 字符），当前 {len(q)} 字符")

        n = min(max(max_results, 1), _MAX_RESULTS_CAP)
        headers = {"Authorization": f"Bearer {self._api_key}"}
        body = {"query": q, "max_results": n}
        try:
            # trust_env=False：与 web_fetch 同口径——忽略进程代理环境变量，出站直连
            async with httpx.AsyncClient(timeout=_ENGINE_TIMEOUT, trust_env=False) as client:
                response = await client.post(self._ENDPOINT, json=body, headers=headers)
        except httpx.TimeoutException as exc:
            raise SearchEngineError(f"检索请求超时: {q[:50]}", category=ErrorCategory.TRANSIENT) from exc
        except httpx.RequestError as exc:
            raise SearchEngineError(f"检索请求失败: {exc}", category=ErrorCategory.TRANSIENT) from exc
        if response.status_code >= 400:
            # 分类复用容错面判据：包 ProviderError 走 classify_error 的标准入口
            provider_error = ProviderError(response.text[:200], status_code=response.status_code)
            raise SearchEngineError(
                f"检索引擎 HTTP {response.status_code}: {response.text[:200]}",
                status_code=response.status_code,
                category=classify_error(provider_error),
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise SearchEngineError(
                "检索引擎返回非 JSON 响应",
                status_code=response.status_code,
                category=ErrorCategory.NON_TRANSIENT,
            ) from exc

        results: list[SearchResult] = []
        for item in data.get("results", []):
            url = item.get("url", "")
            if not url:
                continue
            results.append(
                SearchResult(
                    title=item.get("title", ""),
                    url=url,
                    snippet=item.get("content", ""),
                )
            )
        return results


_ENGINE_REGISTRY: dict[str, Callable[[str], SearchEngine]] = {}


def register_engine(name: str, factory: Callable[[str], SearchEngine]) -> None:
    """注册引擎工厂（name → 工厂；工厂收 api_key，返回引擎实例）。"""
    _ENGINE_REGISTRY[name] = factory


def _make_tavily(api_key: str) -> SearchEngine:
    return TavilyEngine(api_key=api_key)


register_engine("tavily", _make_tavily)


def create_engine(name: str, api_key: str = "") -> SearchEngine:
    """按配置声明的引擎名构造引擎；未知名 fail-loud（列出可用引擎）。"""
    factory = _ENGINE_REGISTRY.get(name)
    if factory is None:
        known = ", ".join(sorted(_ENGINE_REGISTRY))
        raise SearchEngineError(f"未知检索引擎 '{name}'（可用: {known}）")
    return factory(api_key)
