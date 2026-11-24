#!/usr/bin/env python3
"""WS/wss 入口的端到端承兑（活动台账 A76 的仓内闭合工具）。

一条命令出结论：四段判据 + 一段可选契约对账，逐段打印 ``[OK]`` / ``[FAIL]``：

1. **绑定面**：``host:port`` 可连（默认 ``192.168.2.226:9201``），且指定的「应拒绝」地址确实拒绝
   （默认在被测地址非回环时加一条 ``127.0.0.1:<port>``——生产姿态下回环腿是刻意消失的）；
2. **TLS 握手**：协议版本、套件、对端叶证书（不校链、不校主机名，信任锚是 pin，与客户端同一口径）；
3. **pin 对账**：对端叶证书的 SPKI-SHA256 与本地材料 ``--cert`` 逐字相等，并打印三格式
   （``spki_sha256`` / 短指纹 / OkHttp ``sha256/<base64>``）供客户端内置；
4. **认证闸门**：无 token 的 WS 升级请求必须被拒（默认期望 ``403``）；给了 ``--token`` 时再验一次 ``101``；
5. **契约面（可选）**：``--status-url`` 指向 ``/api/status`` 时，比对其中 ``listeners[].tls.spki_sha256``
   与第 3 段的值——两处不同源即判 FAIL。

用法::

    python scripts/ws_tls_attest.py                                  # 默认证生产姿态
    python scripts/ws_tls_attest.py --host 192.168.2.226 --port 9201
    python scripts/ws_tls_attest.py --token "<WS_AUTH_TOKEN>"        # 追加验 101
    python scripts/ws_tls_attest.py --self-check                     # 离线自检（本机起 TLS stub）
    python scripts/ws_tls_attest.py --json                           # 机器可读输出

退出码：``0`` 全过 / ``1`` 判据失败 / ``2`` 前提缺失（材料不可读、目标未在监听、环境缺依赖）。

纪律：**只读探针**——不提交 run、不建会话、不改服务端状态；token 只在请求头里出现，任何分支都不打印值
（只报「已提供（长度 N）」）。stdlib only（``ssl`` / ``socket`` / ``urllib``），不依赖 ``websockets``。
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import socket
import ssl
import sys
import threading
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_PRECONDITION = 2

#: 默认入口：与 `.env` 的生产姿态一致（`WS_HOST` + `WS_PORT`）。
DEFAULT_HOST = "192.168.2.226"
DEFAULT_PORT = 9201
DEFAULT_PATH = "/api/runs/ws"
DEFAULT_CERT = Path(".heagent") / "tls" / "cert.pem"
DEFAULT_KEY = Path(".heagent") / "tls" / "key.pem"

#: 叶证书到期预警天数（与 `cli/http_config.py::TLS_EXPIRY_WARNING_DAYS` 同口径，仅作提示不判 FAIL）。
EXPIRY_WARNING_DAYS = 7


class _Segment:
    """一段判据的结果（ok + 人类可读细节）。"""

    def __init__(self, name: str) -> None:
        self.name = name
        self.ok = True
        self.details: list[str] = []

    def note(self, text: str) -> None:
        self.details.append(text)

    def fail(self, text: str) -> None:
        self.ok = False
        self.details.append(f"FAIL: {text}")

    def check(self, condition: bool, ok_text: str, fail_text: str) -> None:
        if condition:
            self.details.append(ok_text)
        else:
            self.fail(fail_text)

    def render(self) -> dict[str, object]:
        return {"segment": self.name, "ok": self.ok, "details": self.details}


def _report(segments: Sequence[_Segment], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps([segment.render() for segment in segments], ensure_ascii=False, indent=2))
        return
    for segment in segments:
        mark = "[OK]  " if segment.ok else "[FAIL]"
        print(f"{mark} {segment.name}")
        for detail in segment.details:
            print(f"       {detail}")


# ── 探针（stdlib） ──


def _split_host_port(text: str) -> tuple[str, int]:
    """``host:port`` → 二元组；IPv6 允许 ``[::1]:9201`` 写法。

    脱方括号走 :func:`heagent.network.exposure.unbracket_host`——本仓该规则**只有一处实现**
    （配置面 / SAN 覆盖判定 / CLI 参数共用）；自己 ``strip("[]")`` 会把 ``[localhost]`` 也剥成
    ``localhost``，与另一处「非 IPv6 字面量保留原样」的口径分叉。
    """
    host, _, port = text.rpartition(":")
    if not host or not port.isdigit():
        raise ValueError(f"地址需形如 host:port（收到 {text!r}）")
    from heagent.network.exposure import unbracket_host

    return unbracket_host(host), int(port)


def _tcp_probe(host: str, port: int, timeout: float) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, "OPEN"
    except OSError as exc:
        return False, f"{type(exc).__name__}: {exc}"


def _client_context() -> ssl.SSLContext:
    """不校链、不校主机名：身份由 pin 承担（与客户端 `X509TrustManager` 同一口径）。"""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


def _tls_handshake(host: str, port: int, timeout: float) -> tuple[str, str, bytes]:
    with (
        socket.create_connection((host, port), timeout=timeout) as raw,
        _client_context().wrap_socket(raw, server_hostname=host) as tls,
    ):
        version = tls.version() or "?"
        cipher_info = tls.cipher()
        cipher = cipher_info[0] if cipher_info else "?"
        leaf = tls.getpeercert(binary_form=True) or b""
        return version, cipher, leaf


def _ws_upgrade(
    host: str,
    port: int,
    path: str,
    *,
    token: str | None,
    origin: str | None,
    timeout: float,
) -> tuple[int | None, str]:
    """发一次真实 WS 升级请求，只读状态行（拿到 101/403 即收工，不进入帧循环）。"""
    key = base64.b64encode(os.urandom(16)).decode("ascii")
    lines = [
        f"GET {path} HTTP/1.1",
        f"Host: {host}:{port}",
        "Upgrade: websocket",
        "Connection: Upgrade",
        f"Sec-WebSocket-Key: {key}",
        "Sec-WebSocket-Version: 13",
    ]
    if token:
        lines.append(f"Authorization: Bearer {token}")
    if origin:
        lines.append(f"Origin: {origin}")
    request = ("\r\n".join(lines) + "\r\n\r\n").encode("ascii")

    with (
        socket.create_connection((host, port), timeout=timeout) as raw,
        _client_context().wrap_socket(raw, server_hostname=host) as tls,
    ):
        tls.sendall(request)
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = tls.recv(4096)
            if not chunk:
                break
            head += chunk
    status_line = head.split(b"\r\n", 1)[0].decode("latin-1").strip()
    fields = status_line.split()
    code = int(fields[1]) if len(fields) >= 2 and fields[1].isdigit() else None
    return code, status_line


# ── 五段判据 ──


def _segment_bind(host: str, port: int, refused: Sequence[tuple[str, int]], timeout: float) -> tuple[_Segment, bool]:
    """第 ① 段：目标可连 **且** 指定地址确实拒绝。

    返回 ``(seg, reachable)``——``reachable=False`` 是**前提缺失**（服务没起，走退出码 2），
    而「期望拒绝却 OPEN」是**判据失败**（暴露面漂移，走退出码 1）。两者都以 ``seg.ok=False`` 收场，
    只看 ``ok`` 会把最该抓的漂移误报成「服务未在监听」。
    """
    seg = _Segment("① 绑定面（端口探活）")
    reachable, detail = _tcp_probe(host, port, timeout)
    if not reachable:
        seg.fail(f"{host}:{port} 连不上（{detail}）——先确认服务在跑，或改 --host / --port")
        return seg, False
    seg.note(f"{host}:{port} OPEN")
    for refused_host, refused_port in refused:
        is_open, _ = _tcp_probe(refused_host, refused_port, timeout)
        seg.check(
            not is_open,
            f"{refused_host}:{refused_port} REFUSED（如预期：无回环腿 / 无全网绑定）",
            f"{refused_host}:{refused_port} 期望拒绝但 OPEN（暴露面漂移）",
        )
    return seg, True


def _segment_handshake(host: str, port: int, timeout: float) -> tuple[_Segment, bytes]:
    seg = _Segment("② TLS 握手")
    try:
        version, cipher, leaf = _tls_handshake(host, port, timeout)
    except (ssl.SSLError, OSError) as exc:
        seg.fail(f"握手失败（{type(exc).__name__}: {exc}）——该端口可能仍是明文 ws")
        return seg, b""
    seg.note(f"{version} / {cipher}")
    if not leaf:
        seg.fail("对端未出示证书（匿名套件或缺证书）")
        return seg, b""
    seg.note(f"对端叶证书 {len(leaf)} 字节 DER")
    return seg, leaf


def _local_spki_sha(cert_path: Path) -> str | None:
    """本地材料的 SPKI-SHA256；读不出 / 解析不出返回 ``None``（调用方按前提缺失处理）。"""
    from heagent.network.tls_identity import TlsIdentityError, spki_der, spki_sha256_of_der

    try:
        return spki_sha256_of_der(spki_der(cert_path))
    except (TlsIdentityError, OSError):
        return None


def _segment_pin(leaf: bytes, local_sha: str, cert_name: str) -> tuple[_Segment, str]:
    """第 ③ 段：对端叶证书的 SPKI 与本地材料逐字比对，并打印客户端要内置的三格式。

    返回 ``(seg, remote_sha)``——第 ⑤ 段要用同一个值对账，**不**从渲染文案里反解析（改文案就静默错值）。
    """
    seg = _Segment("③ pin 对账（对端证书 ↔ 本地材料）")
    from heagent.network.tls_identity import (
        cert_not_after,
        san_entries,
        short_fingerprint_of_der,
        spki_der,
        spki_sha256_base64_of_der,
        spki_sha256_of_der,
    )

    remote_spki = spki_der(leaf)
    remote_sha = spki_sha256_of_der(remote_spki)
    seg.check(
        remote_sha == local_sha,
        f"对端 SPKI == 本地 {cert_name}：{remote_sha}",
        f"对端 SPKI {remote_sha} ≠ 本地材料 {local_sha}（pin 漂移：要么重签过、要么对端不是这套材料）",
    )
    seg.note(f"spki_sha256      = {remote_sha}")
    seg.note(f"short_fingerprint= {short_fingerprint_of_der(remote_spki)}")
    seg.note(f"pin              = sha256/{spki_sha256_base64_of_der(remote_spki)}")

    not_after = cert_not_after(leaf)
    days_left = (not_after - datetime.now(UTC)).days
    seg.check(
        days_left > 0, f"叶到期 {not_after.isoformat()}（余 {days_left} 天）", f"叶已过期：{not_after.isoformat()}"
    )
    if 0 < days_left < EXPIRY_WARNING_DAYS:
        seg.note(f"注意：余量 < {EXPIRY_WARNING_DAYS} 天，跑 `heagent tls issue` 重签（pin 不变）")
    seg.note(f"SAN = {', '.join(san_entries(leaf)) or '<空>'}")
    return seg, remote_sha


def _segment_auth(
    host: str,
    port: int,
    path: str,
    *,
    token: str | None,
    origin: str | None,
    expect_unauth: str,
    timeout: float,
) -> _Segment:
    seg = _Segment("④ 认证闸门（WS 升级请求）")
    if expect_unauth == "skip":
        seg.note("跳过无 token 判定（--expect-unauth skip）")
    else:
        wanted = 403 if expect_unauth == "403" else 101
        try:
            code, status_line = _ws_upgrade(host, port, path, token=None, origin=origin, timeout=timeout)
        except (ssl.SSLError, OSError) as exc:
            seg.fail(f"无 token 探针未完成（{type(exc).__name__}: {exc}）")
            code, status_line = None, ""
        seg.check(
            code == wanted,
            f"无 token → {status_line}（期望 {wanted}）",
            f"无 token → {status_line or '<无响应>'}，期望 {wanted}",
        )
    if token:
        try:
            code, status_line = _ws_upgrade(host, port, path, token=token, origin=origin, timeout=timeout)
        except (ssl.SSLError, OSError) as exc:
            seg.fail(f"带 token 探针未完成（{type(exc).__name__}: {exc}）")
            return seg
        seg.check(code == 101, f"带 token → {status_line}（期望 101）", f"带 token → {status_line}，期望 101")
        seg.note(f"token 已提供（长度 {len(token)}），值不进输出")
    else:
        seg.note("未给 --token：只验拒绝面，跳过硬 101 判定")
    return seg


def _segment_status(status_url: str, expected_sha: str, timeout: float) -> _Segment:
    seg = _Segment("⑤ /api/status 的 tls 契约对账")
    if not expected_sha:
        seg.fail("第 ③ 段没拿到对端指纹，无从对账")
        return seg
    opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=_client_context()))
    try:
        with opener.open(status_url, timeout=timeout) as response:
            payload: dict[str, Any] = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError) as exc:
        seg.fail(f"取 {status_url} 失败（{type(exc).__name__}: {exc}）")
        return seg
    listeners = payload.get("listeners") or []
    seen: list[str] = []
    for entry in listeners:
        tls = (entry or {}).get("tls") or {}
        sha = tls.get("spki_sha256") if isinstance(tls, dict) else None
        if sha:
            seen.append(str(sha))
    seg.check(bool(seen), f"状态面给出 {len(seen)} 条 tls 指纹", "状态面没有 tls 指纹（未启用 TLS 或字段改名）")
    seg.check(
        expected_sha in seen,
        "状态面指纹与对端叶证书一致（两处同源）",
        f"状态面指纹 {seen} 不含对端叶证书的 {expected_sha}",
    )
    return seg


# ── 离线自检（本机起一个 TLS stub） ──


def _start_stub(cert_path: Path, key_path: Path) -> tuple[socket.socket, int]:
    """本机 TLS stub：有 ``Authorization`` 回 ``101``，否则 ``403``——与真 server 的拒绝面同形。"""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(str(cert_path), str(key_path))
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    port = int(listener.getsockname()[1])

    def serve() -> None:
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            try:
                tls = context.wrap_socket(conn, server_side=True)
            except (ssl.SSLError, OSError):
                conn.close()
                continue
            try:
                data = b""
                while b"\r\n\r\n" not in data:
                    chunk = tls.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                if b"authorization:" in data.lower():
                    tls.sendall(
                        b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n"
                        b"Connection: Upgrade\r\nSec-WebSocket-Accept: stub\r\n\r\n"
                    )
                else:
                    tls.sendall(b"HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
            finally:
                tls.close()

    threading.Thread(target=serve, daemon=True).start()
    return listener, port


def _run_self_check(args: argparse.Namespace) -> int:
    cert_path = Path(args.cert)
    key_path = Path(args.key)
    serve_cert = Path(args.serve_cert) if args.serve_cert else cert_path
    if not cert_path.is_file() or not key_path.is_file() or not serve_cert.is_file():
        print(
            f"前提缺失：自检需要一对可用的 TLS 材料（{cert_path} / {key_path}"
            f"{' / ' + str(serve_cert) if args.serve_cert else ''}）。"
            "先跑 `heagent tls init` + `heagent tls issue`，或用 --cert / --key 指向测试夹具。",
            file=sys.stderr,
        )
        return EXIT_PRECONDITION

    local_sha = _local_spki_sha(cert_path)
    if local_sha is None:
        print(
            f"前提缺失：本地材料 {cert_path} 解析不出证书（文件不是 PEM 或块名不符）。"
            "用 `heagent tls init` + `heagent tls issue` 重新生成，或用 --cert 指向测试夹具。",
            file=sys.stderr,
        )
        return EXIT_PRECONDITION

    listener, port = _start_stub(serve_cert, key_path)
    try:
        bind_seg, _ = _segment_bind("127.0.0.1", port, (), args.timeout)
        segments: list[_Segment] = [bind_seg]
        handshake_seg, leaf = _segment_handshake("127.0.0.1", port, args.timeout)
        segments.append(handshake_seg)
        if leaf:
            pin_seg, _remote_sha = _segment_pin(leaf, local_sha, cert_path.name)
            pin_seg.name = "③ pin 对账（自检：stub 证书 vs 同一份材料）"
            segments.append(pin_seg)
        else:
            missing = _Segment("③ pin 对账（自检：stub 证书 vs 同一份材料）")
            missing.fail("没拿到 stub 叶证书")
            segments.append(missing)
        auth_seg = _segment_auth(
            "127.0.0.1",
            port,
            DEFAULT_PATH,
            token=args.token or "self-check-token",
            origin=args.origin,
            expect_unauth="403",
            timeout=args.timeout,
        )
        auth_seg.name = "④ 认证闸门（自检：stub 的 403 / 101）"
        segments.append(auth_seg)
    finally:
        listener.close()
    _report(segments, as_json=args.json)
    return EXIT_OK if all(segment.ok for segment in segments) else EXIT_FAIL


# ── 主流程 ──


def _default_refused(host: str, port: int) -> list[tuple[str, int]]:
    """被测地址非回环时，默认要求回环腿也拒绝（生产姿态下它是刻意消失的）。"""
    from heagent.network.exposure import is_loopback_host

    if is_loopback_host(host):
        return []
    return [("127.0.0.1", port)]


def _run(args: argparse.Namespace) -> int:
    cert_path = Path(args.cert)
    if not cert_path.is_file():
        print(
            f"前提缺失：pin 对账需要本地证书 {cert_path}（`heagent tls init` + `heagent tls issue` 生成）。",
            file=sys.stderr,
        )
        return EXIT_PRECONDITION
    local_sha = _local_spki_sha(cert_path)
    if local_sha is None:
        print(
            f"前提缺失：本地证书 {cert_path} 解析不出（不是 PEM / 块名不符 / 文件被截断）"
            "——用 `heagent tls issue` 重签，或用 --cert 指向测试夹具。",
            file=sys.stderr,
        )
        return EXIT_PRECONDITION

    try:
        refused = [_split_host_port(item) for item in args.refused] or _default_refused(args.host, args.port)
    except ValueError as exc:
        print(f"参数错误：--refused {exc}", file=sys.stderr)
        return EXIT_PRECONDITION

    bind_seg, reachable = _segment_bind(args.host, args.port, refused, args.timeout)
    if not reachable:
        _report([bind_seg], as_json=args.json)
        print(
            f"前提缺失：{args.host}:{args.port} 未在监听——先启动服务（`heagent http-server` 或 "
            "`powershell scripts/start_heagent.ps1`）再跑本脚本。",
            file=sys.stderr,
        )
        return EXIT_PRECONDITION
    segments: list[_Segment] = [bind_seg]

    handshake_seg, leaf = _segment_handshake(args.host, args.port, args.timeout)
    segments.append(handshake_seg)
    if leaf:
        pin_seg, remote_sha = _segment_pin(leaf, local_sha, cert_path.name)
    else:
        pin_seg = _Segment("③ pin 对账（对端证书 ↔ 本地材料）")
        pin_seg.fail("没拿到对端叶证书，无法对账")
        remote_sha = ""
    segments.append(pin_seg)
    segments.append(
        _segment_auth(
            args.host,
            args.port,
            args.path,
            token=args.token,
            origin=args.origin,
            expect_unauth=args.expect_unauth,
            timeout=args.timeout,
        )
    )
    if args.status_url:
        segments.append(_segment_status(args.status_url, remote_sha, args.timeout))
    else:
        skipped = _Segment("⑤ /api/status 的 tls 契约对账")
        skipped.note("未给 --status-url：跳过（HTTP listener 只绑回环，容器内通常拿不到）")
        segments.append(skipped)

    _report(segments, as_json=args.json)
    return EXIT_OK if all(segment.ok for segment in segments) else EXIT_FAIL


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ws_tls_attest",
        description="WS/wss 入口端到端承兑：绑定面 → TLS 握手 → pin 对账 → 认证闸门 → /api/status",
    )
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"被测地址（默认 {DEFAULT_HOST}）")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"被测端口（默认 {DEFAULT_PORT}）")
    parser.add_argument("--path", default=DEFAULT_PATH, help=f"WS 升级路径（默认 {DEFAULT_PATH}）")
    parser.add_argument("--cert", default=str(DEFAULT_CERT), help=f"本地叶证书（默认 {DEFAULT_CERT}）")
    parser.add_argument("--key", default=str(DEFAULT_KEY), help=f"本地私钥，仅 --self-check 用（默认 {DEFAULT_KEY}）")
    parser.add_argument(
        "--serve-cert",
        default=None,
        help="自检 stub 出示的证书（默认同 --cert）；只用于验「对端与本地材料不是同一套」的判红路径",
    )
    parser.add_argument("--token", default=None, help="Bearer token；给了才验 101，值不进输出")
    parser.add_argument("--origin", default=None, help="可选 Origin 头（验 Origin 判定时用）")
    parser.add_argument(
        "--expect-unauth",
        choices=("403", "101", "skip"),
        default="403",
        help="无 token 的期望结果（external 档 403；lan 档 101；skip 跳过）",
    )
    parser.add_argument(
        "--refused",
        action="append",
        default=[],
        metavar="HOST:PORT",
        help="额外要求「必须拒绝」的地址（可重复；默认在被测地址非回环时加 127.0.0.1:<port>）",
    )
    parser.add_argument("--status-url", default=None, help="可选的 /api/status URL，用于第 5 段对账")
    parser.add_argument("--timeout", type=float, default=5.0, help="单次探针超时秒数（默认 5）")
    parser.add_argument("--self-check", action="store_true", help="离线自检：本机起 TLS stub 跑全链")
    parser.add_argument("--json", action="store_true", help="机器可读输出")
    args = parser.parse_args(argv)
    return _run_self_check(args) if args.self_check else _run(args)


if __name__ == "__main__":
    sys.exit(main())
