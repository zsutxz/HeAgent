"""Web fetch 工具 — 抓取 URL 内容供 Agent 查阅在线文档。

只读操作，标记 ``readOnlyHint=True`` 供 PolicyEngine 自动放行。
"""

from __future__ import annotations

import logging

import httpx

from heagent.tools.decorator import tool

logger = logging.getLogger(__name__)

# 内容大小上限：2 MB（超出截断并警告）
_MAX_CONTENT_BYTES = 2 * 1024 * 1024
# 请求超时（秒）
_DEFAULT_TIMEOUT = 30.0
# 允许的 Content-Type 前缀（只抓文本类内容）
_ALLOWED_CONTENT_TYPES = (
    "text/",
    "application/json",
    "application/xml",
    "application/javascript",
)


def _is_allowed_content_type(content_type: str) -> bool:
    """检查 Content-Type 是否在允许范围内。"""
    ct = content_type.split(";")[0].strip().lower()
    return any(ct.startswith(prefix) for prefix in _ALLOWED_CONTENT_TYPES)


@tool(read_only=True)
async def web_fetch(url: str, max_length: int = 50000) -> str:
    """Fetch content from a URL and return as text. Read-only.

    Only text-based content types are supported (HTML, JSON, XML, plain text).
    Binary content (images, PDFs, etc.) will be rejected with a descriptive error.

    Args:
        url: The URL to fetch (must be http:// or https://).
        max_length: Maximum characters to return (default 50000, capped at 100000).
    """
    # URL 格式校验
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        raise ValueError(f"URL 必须以 http:// 或 https:// 开头，收到: {url[:100]}")

    cap = min(max(max_length, 100), 100000)

    try:
        async with httpx.AsyncClient(timeout=_DEFAULT_TIMEOUT, follow_redirects=True) as client:
            response = await client.get(
                url,
                headers={
                    "User-Agent": "HeAgent/1.0 (web_fetch tool)",
                    "Accept": "text/html, text/plain, application/json, application/xml, */*;q=0.5",
                },
            )
            response.raise_for_status()
    except httpx.TimeoutException:
        raise RuntimeError(f"请求超时 ({_DEFAULT_TIMEOUT}s): {url}") from None
    except httpx.HTTPStatusError as e:
        raise RuntimeError(f"HTTP {e.response.status_code}: {url}") from None
    except httpx.RequestError as e:
        raise RuntimeError(f"请求失败: {e}") from None

    # 检查 Content-Type
    content_type = response.headers.get("content-type", "")
    if not _is_allowed_content_type(content_type):
        raise RuntimeError(
            f"不支持的内容类型 '{content_type}'。"
            f"仅支持文本类内容（HTML/JSON/XML/纯文本），收到 {len(response.content)} 字节。"
        )

    # 读取内容（控制大小）
    content_bytes = response.content
    if len(content_bytes) > _MAX_CONTENT_BYTES:
        logger.warning("web_fetch 内容过大: %d 字节，截断到 %d 字节", len(content_bytes), _MAX_CONTENT_BYTES)
        content_bytes = content_bytes[:_MAX_CONTENT_BYTES]

    # 解码
    encoding = response.encoding or "utf-8"
    try:
        text = content_bytes.decode(encoding, errors="replace")
    except LookupError:
        text = content_bytes.decode("utf-8", errors="replace")

    # 截断到 max_length 字符
    total_chars = len(text)
    if total_chars > cap:
        text = text[:cap]
        text += f"\n\n[已截断: 原文 {total_chars} 字符，显示前 {cap} 字符]"

    return text
