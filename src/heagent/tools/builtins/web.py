"""Web fetch 工具 — 抓取 http(s) URL 的文本内容供 Agent 查阅在线文档。

只读操作。``readOnlyHint=True`` 为信息性标注（PolicyEngine 对内置工具不经注解裁决，
按非 ``approval_tools`` 自动放行；注解不改变放行结果）。

安全立场（与 CLAUDE.md 一致）：本工具的 SSRF/围栏防护仅为 defense-in-depth，
**非真正安全边界**——须 OS 级沙箱兜底。已知缺口：
- DNS rebinding：校验时解析的 IP 与 httpx 实际连接时二次解析的 IP 可能不同，
  根治需 IP-pinning 自定义 transport，未实现（依赖 OS 沙箱兜底）。
- 端口不受限（理论上可探测内网端口）；未做端口白名单，避免误伤 :8080/:8443 等合法站点。
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from urllib.parse import urljoin, urlparse

import httpx

from heagent.tools.decorator import tool

logger = logging.getLogger(__name__)

# 响应体硬上限：2 MB（流式读取，超出即截断并警告）
_MAX_CONTENT_BYTES = 2 * 1024 * 1024
# 请求超时（秒）：总读超时 + 单独 connect 超时
_DEFAULT_TIMEOUT = 20.0
_CONNECT_TIMEOUT = 5.0
# 重定向上限（逐跳重新校验主机/协议）
_MAX_REDIRECTS = 5
# 允许的 Content-Type 前缀（只抓文本类内容）
_ALLOWED_CONTENT_TYPES = (
    "text/",
    "application/json",
    "application/xml",
    "application/javascript",
)
_HEADERS = {
    "User-Agent": "HeAgent/1.0 (web_fetch tool)",
    "Accept": "text/html, text/plain, application/json, application/xml, */*;q=0.5",
}


def _is_allowed_content_type(content_type: str) -> bool:
    """检查 Content-Type 是否在允许范围内。"""
    ct = content_type.split(";")[0].strip().lower()
    return any(ct.startswith(prefix) for prefix in _ALLOWED_CONTENT_TYPES)


def _is_address_blocked(ip: str) -> bool:
    """是否为禁止访问的非公网 IP（正向白名单：仅放行 globally-routable 地址）。

    覆盖私网/loopback/link-local/多播/保留/未指定/文档用（TEST-NET）等一切非公网段。
    resolver 返回非 IP token 时 fail-closed（按禁止处理）。
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return True
    return addr.is_multicast or not addr.is_global


async def _resolve_addresses(host: str) -> list[str]:
    """异步解析主机名到 IP 地址列表（测试可 monkeypatch 以避免真实 DNS）。"""
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, None)
    except (socket.gaierror, socket.herror) as exc:
        raise RuntimeError(f"DNS 解析失败: {host} ({exc})") from None
    addrs = sorted({info[4][0] for info in infos})
    if not addrs:
        raise RuntimeError(f"DNS 无解析结果: {host}")
    return addrs


async def _validate_url(raw: str, *, pin_scheme: str | None) -> str:
    """校验并归一化 URL：scheme 白名单 / 禁 userinfo / 禁非公网地址 / 禁 HTTPS 降级。

    scheme 大小写不敏感（``HTTPS://`` 与 ``https://`` 等价）。defense-in-depth——
    经 DNS 解析后再判定 IP，覆盖十进制/十六进制等编码形式（最终依赖 OS resolver；非完美边界，
    见模块文档的 DNS rebinding 缺口）。
    """
    parsed = urlparse(raw)
    scheme = parsed.scheme.lower()
    if scheme not in ("http", "https"):
        raise RuntimeError(f"URL 必须以 http:// 或 https:// 开头，收到: {raw[:100]}")
    if pin_scheme == "https" and scheme != "https":
        raise RuntimeError(f"不允许从 HTTPS 降级到 {scheme}")
    if parsed.username or parsed.password:
        raise RuntimeError("URL 不允许携带 userinfo (user:pass@)")
    host = parsed.hostname
    if not host:
        raise RuntimeError(f"URL 缺少 host: {raw[:100]}")
    for ip in await _resolve_addresses(host):
        if _is_address_blocked(ip):
            raise RuntimeError(f"拒绝访问非公网地址: {host} ({ip})")
    return parsed.geturl()


async def _read_capped(response: httpx.Response) -> tuple[bytes, bool]:
    """流式读取响应体，累计字节数超 ``_MAX_CONTENT_BYTES`` 即中止。

    返回 (已读字节, 是否超限)。流式读取避免对抗性大响应在截断前撑爆内存。
    """
    chunks: list[bytes] = []
    total = 0
    exceeded = False
    async for chunk in response.aiter_bytes():
        total += len(chunk)
        if total > _MAX_CONTENT_BYTES:
            exceeded = True
            break
        chunks.append(chunk)
    return b"".join(chunks), exceeded


@tool(read_only=True)
async def web_fetch(url: str, max_length: int = 50000) -> str:
    """Fetch text content (HTML/JSON/XML/plain) from an http(s) URL. Read-only; binary types rejected.

    非公网/私网/loopback/元数据地址、userinfo URL、HTTPS→HTTP 降级一律拒绝（SSRF 防护，
    defense-in-depth）。响应体硬上限 2 MB（流式截断）。

    Args:
        url: The URL to fetch (must be http:// or https://).
        max_length: 返回字符上限（默认 50000，钳位到 [100, 100000]）。
    """
    url = url.strip()
    pin_scheme = urlparse(url).scheme.lower() or None
    cap = min(max(max_length, 100), 100000)

    # 初始 URL 先校验（fail-fast，避免坏 URL 仍创建连接池）
    current = await _validate_url(url, pin_scheme=pin_scheme)
    timeout = httpx.Timeout(_DEFAULT_TIMEOUT, connect=_CONNECT_TIMEOUT)
    # trust_env=False：忽略进程 HTTP(S)_PROXY，避免流量绕过 IP 出站校验经代理外出
    async with httpx.AsyncClient(
        timeout=timeout, follow_redirects=False, trust_env=False
    ) as client:
        for _ in range(_MAX_REDIRECTS):
            try:
                async with client.stream("GET", current, headers=_HEADERS) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location or not location.strip():
                            raise RuntimeError(f"重定向响应缺少有效 Location: {current}")
                        current = await _validate_url(
                            urljoin(current, location), pin_scheme=pin_scheme
                        )
                        continue
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    # 缺 Content-Type 视为文本放行；仅当存在且非文本类时拒绝
                    if content_type and not _is_allowed_content_type(content_type):
                        raise RuntimeError(
                            f"不支持的内容类型 '{content_type}'。"
                            "仅支持文本类内容（HTML/JSON/XML/纯文本）。"
                        )
                    content_bytes, exceeded = await _read_capped(response)
                    if exceeded:
                        logger.warning(
                            "web_fetch 内容过大，截断到 %d 字节", _MAX_CONTENT_BYTES
                        )
                    encoding = response.encoding or "utf-8"
                break
            except httpx.TimeoutException:
                raise RuntimeError(f"请求超时: {current}") from None
            except httpx.HTTPStatusError as exc:
                raise RuntimeError(f"HTTP {exc.response.status_code}: {current}") from None
            except httpx.RequestError as exc:
                raise RuntimeError(f"请求失败: {exc}") from None
        else:
            raise RuntimeError(f"重定向次数超限 ({_MAX_REDIRECTS}): {url}")

    try:
        text = content_bytes.decode(encoding, errors="replace")
    except LookupError:
        text = content_bytes.decode("utf-8", errors="replace")

    total_chars = len(text)
    if total_chars > cap:
        text = text[:cap]
        text += f"\n\n[已截断: 原文 {total_chars} 字符，显示前 {cap} 字符]"

    return text
