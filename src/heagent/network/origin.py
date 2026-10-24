"""入口 listener 的同源防线（AD-6）与探测地址推导——HTTP 与 WS 两个 server 共用的单源。

Epic 56 D1（HTTP/WS 完全分离）时自 ``http_server.py`` 纯搬移：两条 listener 的同源规则
**必须同源演进**，两处各写一套迟早漂移（``exposure.py`` 的既有立场）。这里的判定被两个
server 逐字共用；哪一 side 要收紧规则，改这一处即可。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from collections.abc import MutableMapping

from heagent.network.exposure import is_loopback_host

# 我们不信任任何代理头：反向代理部署不在 MVP 支持范围（AD-6），出现这些头即拒绝请求——
# 否则 `X-Forwarded-Host` 就能把「跨站请求」伪装成本机同源请求（DNS rebinding 的常见变体）。
_UNTRUSTED_FORWARD_HEADERS = frozenset(
    {b"forwarded", b"x-forwarded-for", b"x-forwarded-host", b"x-forwarded-proto", b"x-real-ip"}
)

# 回环绑定时接受的等价本机写法：三者指向同一个 listener（浏览器地址栏习惯不同），拒绝其中
# 任何一个都会让「本机自用」这个主用例失效。**非回环绑定只用配置的那个名字**（不额外放宽）。
_LOOPBACK_HOST_ALIASES = ("127.0.0.1", "localhost", "[::1]")

# 通配绑定地址：就绪探测改走回环（见 :func:`probe_host`）。这里**只识别**，不在此绑定。
_WILDCARD_HOSTS = frozenset({"", "0.0.0.0", "*"})  # nosec B104 - 仅识别通配地址，本模块不在此绑定 # noqa: S104
_IPV6_WILDCARDS = frozenset({"::", "[::]"})


class ListenerConfig(Protocol):
    """两条 listener 配置的最小结构面（``HttpServerConfig`` / ``WsServerConfig`` 均满足）。"""

    host: str
    port: int


def canonical_authority(value: str) -> str | None:
    """规范化 ``Host`` 的 authority：小写、省略 http 默认端口 80。

    返回 ``None`` 表示格式不可信（含路径/查询、非数字端口、越界端口、空值）——调用方按拒绝处理。
    IPv6 字面量写成 ``[::1]:8766``（方括号是 authority 的一部分）。
    """
    text = value.strip().lower()
    if not text or "/" in text or "?" in text:
        return None
    if text.startswith("["):
        end = text.find("]")
        if end < 0:
            return None
        host = text[: end + 1]
        rest = text[end + 1 :]
        port = rest[1:] if rest.startswith(":") else ""
    elif ":" in text:
        host, _, port = text.rpartition(":")
    else:
        host, port = text, ""
    if port and (not port.isdigit() or int(port) > 65535):
        return None
    effective = int(port) if port else 80
    return host if effective == 80 else f"{host}:{effective}"


def split_authority(authority: str) -> tuple[str, int]:
    """把规范化后的 authority 拆成 ``(host, port)``；无端口视为 http 默认端口 80。"""
    if authority.startswith("["):
        end = authority.find("]")
        host = authority[: end + 1]
        rest = authority[end + 1 :]
        return host, int(rest[1:]) if rest.startswith(":") else 80
    host, sep, port = authority.rpartition(":")
    if not sep:
        return authority, 80
    return host, int(port)


def allowed_hosts(config: ListenerConfig) -> frozenset[str]:
    """允许的 host 名集合：配置 host + （**仅当它是回环时**）等价本机写法。

    这是「请求必须打在本 listener 上」的判据，用于挡住 Host 伪装（例如把 ``evil.example`` 解析到
    127.0.0.1 的 DNS rebinding）。**不是认证**：能连上端口的本机进程可以随便伪造 Host。
    """
    host = config.host.strip().lower()
    names = {host}
    # 通配绑定（``0.0.0.0`` / ``::`` / ``*``）没有单一主机名：就绪探测与浏览器都是从回环地址
    # 打进这个 listener 的（见 :func:`probe_host`），因此把等价本机写法一并接受——否则探测会
    # 撞上自己的 Host 校验（403），``HTTP_HOST=0.0.0.0`` 永远起不来。
    # 这不削弱反 DNS-rebinding：伪造的域名（``evil.example``）仍在拒绝之列；通配绑定的其它网卡
    # 地址也仍按「不匹配 listener 名」拒绝（非回环联网不受支持，见 CLI help 与 exposure 告警）。
    if is_loopback_host(host) or host in _WILDCARD_HOSTS or host in _IPV6_WILDCARDS:
        names.update(_LOOPBACK_HOST_ALIASES)
    return frozenset(names)


def allowed_ports(config: ListenerConfig) -> frozenset[int] | None:
    """允许的端口集合；``None`` 表示「任意端口」。

    ``port=0``（操作系统分配随机端口，只用于程序化/测试）时构建 app 还不知道实际端口，故不限制
    端口；CLI 与 ``WS_PORT``/``HTTP_PORT`` 都限定 1..65535，生产路径永远有确定的端口。
    """
    return None if config.port == 0 else frozenset({config.port})


def request_origin_violation(
    scope: MutableMapping[str, Any],
    *,
    hosts: frozenset[str],
    ports: frozenset[int] | None,
) -> str | None:
    """请求是否违反同源防线；返回违规原因（供日志），``None`` 表示通过。

    规则（AD-6）：

    1. 出现任何 forwarded-* 头 ⇒ 检出即拒（见 :data:`_UNTRUSTED_FORWARD_HEADERS`）；
    2. ``Host`` 必须恰好一个、且规范化后的 host/port 都在允许集合内；
    3. 若带 ``Origin``：不得为 ``null``/空，且必须等于 ``http://`` 加该 authority（同源）。
       **缺少 Origin** 只表示「非浏览器客户端」（curl / 脚本），Host 已校验故放行。
    """
    headers = scope.get("headers") or []
    if any(name.lower() in _UNTRUSTED_FORWARD_HEADERS for name, _value in headers):
        return "untrusted forwarded header"
    host_headers = [value.decode("latin-1") for name, value in headers if name.lower() == b"host"]
    if len(host_headers) != 1:
        return "missing or duplicated Host header"
    authority = canonical_authority(host_headers[0])
    if authority is None:
        return "malformed Host header"
    host, port = split_authority(authority)
    if host not in hosts:
        return "host not allowed"
    if ports is not None and port not in ports:
        return "port not allowed"
    for name, value in headers:
        if name.lower() != b"origin":
            continue
        origin = value.decode("latin-1").strip().lower()
        if not origin or origin == "null":
            return "null Origin"
        if origin != f"http://{authority}":
            return "origin mismatch"
    return None


def probe_host(host: str) -> str:
    """就绪探测用的连接地址：通配绑定（``0.0.0.0`` / ``::`` / 空串）改用回环地址。

    连 ``0.0.0.0`` 在多数平台上是未定义/失败行为，而「通配绑定是否真的能服务」完全可以经
    回环地址验证（通配包含回环）。
    """
    candidate = host.strip()
    if candidate in _IPV6_WILDCARDS:
        return "::1"
    if candidate in _WILDCARD_HOSTS:
        return "127.0.0.1"
    return candidate


__all__ = [
    "ListenerConfig",
    "allowed_hosts",
    "allowed_ports",
    "probe_host",
    "request_origin_violation",
]
