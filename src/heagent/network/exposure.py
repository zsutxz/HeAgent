"""监听地址的暴露判定与告警文案（Epic 48 Story 48-5 引入，现由 HTTP 网页入口使用）。

网络入口**无认证、无 TLS**，只适合本机实验。本模块是「这个绑定地址是否只对本机可见」的
**唯一判定点**，供 :class:`~heagent.network.http_server.HttpServer` 的启动路径与
``heagent http-server`` 共用——两处各写一套「算不算本地」的逻辑迟早会漂移，而漂移的代价是漏报暴露。

判定语义（刻意保守）：

- **IP 字面量**（含 ``[::1]`` 这种带方括号的 IPv6 写法）：交给标准库 :mod:`ipaddress` 的
  ``is_loopback``——``127.0.0.0/8`` 与 ``::1`` 为真，``0.0.0.0``、``::``、局域网/公网地址为假。
- **``localhost``**：按 RFC 6761 视为本机名，直接判回环。
- **其它主机名**：**不做 DNS 解析**，一律判为「可能对外暴露」。启动期解析会引入阻塞 I/O 与
  不可预测的失败模式，而且「解析到本机」与「实际绑定到本机」并不等价（多网卡、解析结果会变）。
  这里取 fail-safe 方向：误报只是多一条提示，漏报会让运行者以为没有对外暴露。

**这不是安全边界**：回环判定只解释「谁能连上」，不构成信任依据——回环客户端同样不可信，
请求一律按不可信输入处理（story 48-5 的 Never 列表）。
"""

from __future__ import annotations

import ipaddress

_LOCALHOST = "localhost"

# 单条告警文案（stderr 一行 / 日志一条）：明确「无认证、无 TLS、非生产安全边界」三个要点。
_NON_LOOPBACK_WARNING = (
    "bound to non-loopback host '{host}': this entry has no authentication and no TLS and is not a "
    "production security boundary. Keep it on a loopback address or an OS-isolated host, and treat "
    "every request as untrusted input (a loopback client is not trusted either)."
)


def unbracket_host(host: str) -> str:
    """``[::1]`` → ``::1``（URL / CLI 里的 IPv6 字面量写法），并去掉首尾空白。

    只对**合法 IPv6 字面量**脱括号：``[localhost]`` 这类写法不是 IPv6 字面量，保留原样
    （随后既不匹配 ``localhost`` 也过不了 :mod:`ipaddress`，按暴露处理——不做特殊放行）。

    绑定地址的方括号写法在配置面、TLS 材料（SAN 覆盖判定）与 CLI 参数上都会出现，故脱括号
    规则只有这一处实现：三处各写一套时，漏一处的表现是「同一个地址在一处算回环、在另一处
    被当成主机名」——很难从现象反推。
    """
    stripped = host.strip()
    if len(stripped) >= 2 and stripped.startswith("[") and stripped.endswith("]"):  # noqa: PLR2004
        inner = stripped[1:-1]
        try:
            ipaddress.IPv6Address(inner)
        except ValueError:
            return stripped
        return inner
    return stripped


def is_loopback_host(host: str) -> bool:
    """该绑定地址是否只对本机可见（语义见模块 docstring）。

    非 IP 字面量、非 ``localhost`` 的输入一律返回 ``False``（不解析 DNS，fail-safe）。
    """
    candidate = unbracket_host(host)
    if not candidate:
        # 空串在多数 socket API 里等价于「所有接口」——按暴露处理。
        return False
    if candidate.casefold() == _LOCALHOST:
        return True
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


def exposure_warning(host: str) -> str | None:
    """非回环绑定的告警文案；回环绑定返回 ``None``（无告警）。"""
    if is_loopback_host(host):
        return None
    return _NON_LOOPBACK_WARNING.format(host=host)


def is_private_address(host: str) -> bool:
    """该绑定地址是否为**局域网私有地址字面量**（内网免认证模式的准入判据）。

    只认 IP 字面量（``192.168.0.0/16``、``10.0.0.0/8``、``172.16.0.0/12``、``fc00::/7``、
    link-local），其余一律 ``False``：

    - ``0.0.0.0`` / ``::``（通配 = 所有接口，等于把入口对整网开）、组播、未指定地址；
    - 公网地址（``is_global``）：内网免认证模式**不允许**绑到公网地址上；
    - 回环（归本地模式）与主机名（**不解析 DNS**，与 :func:`is_loopback_host` 同口径）；
    - CGNAT 段（``100.64.0.0/10``）：既非 ``is_private`` 也非 ``is_global``，按「不是私有」处理。

    这是准入白名单，不是安全边界——私有地址只说明「同一局域网内可见」，不说明对面可信
    （边界地位见 ``docs/framework.md`` §4.18）。
    """
    candidate = unbracket_host(host)
    if not candidate:
        return False
    try:
        address = ipaddress.ip_address(candidate)
    except ValueError:
        return False
    if address.is_loopback or address.is_unspecified or address.is_multicast or address.is_global:
        return False
    return address.is_private or address.is_link_local


__all__ = ["exposure_warning", "is_loopback_host", "is_private_address", "unbracket_host"]
