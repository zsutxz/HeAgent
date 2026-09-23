"""监听地址的暴露判定与告警文案（Epic 48 Story 48-5）。

TCP 入口**无认证、无 TLS**，只适合本机实验。本模块是「这个绑定地址是否只对本机可见」的
**唯一判定点**，供 :meth:`~heagent.network.tcp_server.TcpServer.start` 与 ``heagent tcp-server``
共用——两处各写一套「算不算本地」的逻辑迟早会漂移，而漂移的代价是漏报暴露。

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


def _unbracket(host: str) -> str:
    """``[::1]`` → ``::1``（URL / CLI 里的 IPv6 字面量写法），并去掉首尾空白。

    只对**合法 IPv6 字面量**脱括号：``[localhost]`` 这类写法不是 IPv6 字面量，保留原样
    （随后既不匹配 ``localhost`` 也过不了 :mod:`ipaddress`，按暴露处理——不做特殊放行）。
    """
    stripped = host.strip()
    if len(stripped) >= 2 and stripped.startswith("[") and stripped.endswith("]"):
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
    candidate = _unbracket(host)
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


__all__ = ["exposure_warning", "is_loopback_host"]
