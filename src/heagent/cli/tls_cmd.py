"""``heagent tls``：WS TLS 身份材料的唯一入口（签发 / 轮换 / 指纹导出 / 一致性校验）。

五个动词，一个不变量：**身份密钥 ``identity.key`` 长期固定**，叶证书重签只换有效期与 SAN，
因此客户端 pin 的 SPKI-SHA256 不变（ADR-004「安装期信任」）。唯一会改变 pin 的动作是
``rotate-key``，它必须显式执行并打印新旧两个指纹。

材料布局（默认 ``<cwd>/.heagent/tls/``，``--dir`` 可改；仓库 .gitignore 已忽略）：

  ``ca.pem`` / ``ca.key``      本地 CA（默认 10 年）。只把 ``ca.pem`` 分发给客户端，``ca.key`` 永不外发。
  ``identity.key``             长期身份密钥 —— 客户端 pin 的对象。``rotate-key`` 才会换。
  ``cert.pem`` / ``key.pem``   叶证书（默认 30 天）与身份密钥副本（``.env`` 的 ``WS_TLS_*`` 指向它们）。
  ``cert-chain.pem``           叶 + CA（要求发链的客户端用）。
  ``openssl-leaf.cnf``         SAN / 用途声明，由本命令生成 —— 改 SAN 走 ``--san``，不要手改。

私钥纪律：``ca.key`` / ``identity.key`` 尽力 ``chmod 0600``，失败只提示不中断（9p / drvfs 上
``chmod`` 必 EPERM，真正的保护是材料目录的访问控制）。任何输出都不含私钥正文，只报路径与指纹。

退出码（与 ``heagent cron`` / ``heagent audit`` 同一约定）：``0`` 成功；``1`` 校验或前提失败；
``2`` 参数 / 环境 / 材料不可用（找不到或无法执行 ``openssl``、材料缺失或读不出）。异常自带
退出码（:class:`TlsCommandError` 的 ``exit_code``），命令体只负责把码交出去。

分层：入口层（``heagent/cli/``），依赖 click + 标准库 + ``heagent.network.tls_identity``（纯 stdlib
解析）；签发路径用 ``openssl`` 子进程（不在请求路径上）。
"""

from __future__ import annotations

import base64
import contextlib
import ipaddress
import json
import os
import shutil
import socket
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

import click

from heagent.network.exposure import unbracket_host
from heagent.network.tls_identity import (
    TlsCertificateInfo,
    TlsIdentityError,
    cert_key_matches,
    certificate_info,
    key_spki_der,
    san_entries,
    short_fingerprint_of_der,
    spki_sha256_base64,
    spki_sha256_base64_of_der,
    spki_sha256_of_der,
)

EXIT_OK = 0
EXIT_PROBLEM = 1
EXIT_UNUSABLE = 2

CA_SUBJECT = "/CN=HeAgent Local CA/O=HeAgent Lab"
LEAF_CONFIG = "openssl-leaf.cnf"
DEFAULT_CA_DAYS = 3650
DEFAULT_LEAF_DAYS = 30
#: 缺省 SAN —— 回环 + 本机常见主机名；``WS_HOST``、已签 SAN 与 ``--san`` 在其上追加。
DEFAULT_SAN: tuple[str, ...] = ("IP:127.0.0.1", "IP:::1", "DNS:localhost", "DNS:heagent.local")

FINGERPRINT_FORMATS = ("text", "json", "pin")


class TlsCommandError(RuntimeError):
    """前提不成立或 ``openssl`` 失败（不猜、不降级、不假装成功）。

    ``exit_code`` 随异常携带：**参数 / 环境 / 材料不可用**是 ``2``（脚本据此区分「环境没装好」
    与「校验结论不合格」），其余前提失败是 ``1``；模块 docstring 的退出码表就是这张映射。
    """

    def __init__(self, message: str, *, exit_code: int = EXIT_PROBLEM) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True)
class _Session:
    """一次命令调用的公共上下文（材料目录 + openssl 路径）。"""

    directory: Path
    openssl: str | None

    @property
    def ca_cert(self) -> Path:
        return self.directory / "ca.pem"

    @property
    def ca_key(self) -> Path:
        return self.directory / "ca.key"

    @property
    def identity_key(self) -> Path:
        return self.directory / "identity.key"

    @property
    def leaf_cert(self) -> Path:
        return self.directory / "cert.pem"

    @property
    def leaf_key(self) -> Path:
        return self.directory / "key.pem"

    @property
    def chain(self) -> Path:
        return self.directory / "cert-chain.pem"

    @property
    def leaf_config(self) -> Path:
        return self.directory / LEAF_CONFIG


def _fail(message: str, *, code: int = EXIT_UNUSABLE) -> NoReturn:
    click.echo(f"Error: {message}", err=True)
    raise SystemExit(code)


def _fail_exit(exc: TlsCommandError | TlsIdentityError) -> NoReturn:
    """按异常自带的退出码退出（:class:`TlsIdentityError` 无码，落 ``1`` = 前提失败）。"""
    _fail(str(exc), code=getattr(exc, "exit_code", EXIT_PROBLEM))


def _default_directory() -> Path:
    """缺省材料目录：当前工作区根的 ``.heagent/tls``（与其它运行产物同根）。"""
    return Path.cwd() / ".heagent" / "tls"


def _find_openssl(explicit: str | None) -> str:
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise TlsCommandError(f"--openssl 指向的文件不存在：{explicit}", exit_code=EXIT_UNUSABLE)
        # Windows 没有 POSIX 执行位（扩展名决定可执行性），只在其它平台查一次。
        if os.name != "nt" and not os.access(path, os.X_OK):
            raise TlsCommandError(f"--openssl 指向的文件不可执行：{explicit}", exit_code=EXIT_UNUSABLE)
        return str(path)
    found = shutil.which("openssl")
    if found:
        return found
    raise TlsCommandError(
        "找不到 openssl（签发与链校验需要它）。装一个，或用 --openssl <路径> 指定；"
        "宿主 Windows 没有 openssl 时**在容器里执行**（既有先例）："
        'docker run --rm -v "$PWD:/work" -w /work <含 openssl 的镜像> heagent tls issue',
        exit_code=EXIT_UNUSABLE,
    )


def _run(binary: str, args: list[str], *, cwd: Path) -> str:
    # 参数全部由本模块构造（不含外部拼接），不经 shell。
    completed = subprocess.run(  # nosec B603 - 参数由本模块构造不经命令行壳 # noqa: S603 - 定值参数
        [binary, *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise TlsCommandError(f"openssl {args[0]} 失败（exit {completed.returncode}）：{detail}")
    return completed.stdout


# ---------------------------------------------------------------- SAN 与配置


def _normalize_san(raw: str) -> str:
    """把一项 SAN 规范化成 ``IP:`` / ``DNS:`` 形式；认不出就 fail-loud（写错只在握手期才炸）。"""
    text = raw.strip()
    if not text:
        raise TlsCommandError("--san 项不能为空")
    if text.upper().startswith(("IP:", "DNS:")):
        kind, _, value = text.partition(":")
        value = value.strip()
        if not value:
            raise TlsCommandError(f"{text!r} 缺值")
        if kind.upper() == "IP":
            try:
                return f"IP:{ipaddress.ip_address(unbracket_host(value))}"
            except ValueError as exc:
                raise TlsCommandError(f"{value!r} 不是 IP 字面量") from exc
        return f"DNS:{value}"
    # `[::1]` 与绑定地址同一口径脱括号（见 exposure.unbracket_host）。
    candidate = unbracket_host(text)
    try:
        return f"IP:{ipaddress.ip_address(candidate)}"
    except ValueError:
        pass
    if _looks_like_ip_literal(candidate):
        raise TlsCommandError(f"{text!r} 形似 IP 但解析失败（检查是否打错）")
    if any(ch in candidate for ch in " \t/\\:@[]") or candidate.startswith("-"):
        raise TlsCommandError(f"{text!r} 既不是 IP 也不是主机名")
    return f"DNS:{candidate}"


def _looks_like_ip_literal(text: str) -> bool:
    """是否「形似 IP」：带冒号（IPv6 形状）或点分四段全数字（IPv4 形状）。

    只按形状判：``cafe`` / ``dead.beef`` 这类主机名虽然只由十六进制字符与点组成，却是合法
    DNS 名，报「形似 IP 但解析失败」会把人引向错误的排查方向。
    """
    if ":" in text:
        return True
    parts = text.split(".")
    return len(parts) == 4 and all(part.isdigit() for part in parts)  # noqa: PLR2004 - IPv4 固定四段


def _detect_lan_ips() -> list[str]:
    """本机非回环 IPv4（探测不到返回空表；绝不猜 0.0.0.0）。"""
    found: list[str] = []
    with contextlib.suppress(OSError), socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        # 只让内核选源地址，不实际发包（UDP connect 不发数据）。
        sock.connect(("8.8.8.8", 80))
        found.append(sock.getsockname()[0])
    with contextlib.suppress(OSError):
        found.extend(socket.gethostbyname_ex(socket.gethostname())[2])
    result: list[str] = []
    for candidate in found:
        try:
            address = ipaddress.ip_address(candidate)
        except ValueError:
            continue
        if address.version != 4 or address.is_loopback or address.is_unspecified or address.is_link_local:  # noqa: PLR2004
            continue
        if candidate not in result:
            result.append(candidate)
    return result


def _ws_host() -> str | None:
    """当前 ``WS_HOST``；配置读不出来时返回 ``None``（材料签发不该被无关配置错卡住）。"""
    try:
        from heagent.config import get_settings  # noqa: PLC0415 - 只有 issue/init 需要配置面

        host = get_settings().ws_host.strip()
    except Exception:  # noqa: BLE001 - 配置坏掉不阻断签发，SAN 仍有默认项与既有项
        return None
    if not host or host in {"0.0.0.0", "::"}:  # nosec B104 - 只比对字面量不在此绑定 # noqa: S104 - 比对通配绑定字面量
        # 通配绑定不是客户端会连的地址 ⇒ 不进 SAN。
        return None
    return host


def _collect_san(session: _Session, extras: tuple[str, ...], *, include_lan: bool) -> list[str]:
    """默认项 ∪ 既有证书 SAN ∪ ``WS_HOST`` ∪ 探测到的局域网 IP ∪ ``--san``，去重保序。

    保留既有证书的 SAN 是刻意的：换网段后重签不会把旧地址悄悄删掉（删了就是静默失联）。
    """
    entries: list[str] = list(DEFAULT_SAN)
    if session.leaf_cert.is_file():
        with contextlib.suppress(TlsIdentityError):
            entries.extend(san_entries(session.leaf_cert))
    host = _ws_host()
    if host is not None:
        with contextlib.suppress(TlsCommandError):
            entries.append(_normalize_san(host))
    if include_lan:
        entries.extend(f"IP:{address}" for address in _detect_lan_ips())
    entries.extend(_normalize_san(item) for item in extras)
    seen: set[str] = set()
    result: list[str] = []
    for entry in entries:
        key = entry.lower()  # DNS 大小写不敏感；IP 已被 ipaddress 规范化
        if key in seen:
            continue
        seen.add(key)
        result.append(entry)
    return result


def _render_leaf_config(san_list: list[str]) -> str:
    """叶证书的 SAN / 用途声明（IP 与 DNS 各自从 1 编号：混编会留编号空洞）。"""
    ip_lines = [
        f"IP.{index} = {entry[3:]}" for index, entry in enumerate(filter(lambda e: e.startswith("IP:"), san_list), 1)
    ]
    dns_lines = [
        f"DNS.{index} = {entry[4:]}" for index, entry in enumerate(filter(lambda e: e.startswith("DNS:"), san_list), 1)
    ]
    alt_lines = [*ip_lines, *dns_lines]
    alt_block = "\n".join(alt_lines) if alt_lines else "# （无 SAN 项）"
    return (
        "# 由 heagent tls 生成，请勿手改 —— 改 SAN 请用 `heagent tls issue --san`。\n"
        "[ req ]\n"
        "default_md = sha256\n"
        "distinguished_name = dn\n"
        "prompt = no\n"
        "req_extensions = v3_req\n\n"
        "[ dn ]\n"
        "CN = heagent-ws\n\n"
        "[ v3_req ]\n"
        "basicConstraints = critical, CA:FALSE\n"
        "keyUsage = critical, digitalSignature, keyEncipherment\n"
        "extendedKeyUsage = serverAuth\n"
        "subjectAltName = @alt_names\n\n"
        "# 客户端实际连的那个地址必须在这份名单里。\n"
        "[ alt_names ]\n"
        f"{alt_block}\n"
    )


def _write_leaf_config(session: _Session, san_list: list[str]) -> None:
    """按字节写 LF：Windows text mode 会把 ``\\n`` 翻成 ``\\r\\n``（openssl 配置要 LF）。"""
    session.directory.mkdir(parents=True, exist_ok=True)
    session.leaf_config.write_bytes(_render_leaf_config(san_list).encode("utf-8"))


# ---------------------------------------------------------------- openssl 动作


def _tighten(path: Path) -> None:
    """尽力把私钥权限收成 0600；文件系统不提供 POSIX 权限时只提示，不中断。"""
    try:
        path.chmod(0o600)
    except OSError as exc:
        click.echo(f"提示：无法把 {path.name} 收成 0600（{exc.strerror or exc}）—— 私钥保护依赖材料目录访问控制。")


def _create_ca(binary: str, session: _Session, ca_days: int) -> None:
    _run(
        binary,
        [
            "req",
            "-x509",
            "-newkey",
            "rsa:4096",
            "-nodes",
            "-keyout",
            "ca.key",
            "-out",
            "ca.pem",
            "-days",
            str(ca_days),
            "-sha256",
            "-subj",
            CA_SUBJECT,
            "-addext",
            "basicConstraints=critical,CA:TRUE,pathlen:0",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
        ],
        cwd=session.directory,
    )


def _ensure_identity(binary: str, session: _Session, *, rotate: bool) -> None:
    """生成 / 轮换身份密钥，并同步成 ``key.pem``（``.env`` 指向的路径不变）。"""
    if rotate or not session.identity_key.is_file():
        _run(binary, ["genrsa", "-out", "identity.key", "2048"], cwd=session.directory)
        _tighten(session.identity_key)
    # 只复制正文：9p / drvfs 上 copystat(chmod/utime) 必 EPERM，copy2 会让签发在成功后被异常打断。
    shutil.copyfile(session.identity_key, session.leaf_key)
    _tighten(session.leaf_key)


def _issue_leaf(binary: str, session: _Session, days: int) -> None:
    """重签叶证书并写链文件；``identity.key`` 不动 ⇒ pin 不变。"""
    _run(
        binary,
        ["req", "-new", "-key", "identity.key", "-config", LEAF_CONFIG, "-out", "leaf.csr"],
        cwd=session.directory,
    )
    _run(
        binary,
        [
            "x509",
            "-req",
            "-in",
            "leaf.csr",
            "-CA",
            "ca.pem",
            "-CAkey",
            "ca.key",
            "-CAcreateserial",
            "-days",
            str(days),
            "-sha256",
            "-extfile",
            LEAF_CONFIG,
            "-extensions",
            "v3_req",
            "-out",
            "cert.pem",
        ],
        cwd=session.directory,
    )
    session.chain.write_bytes(session.leaf_cert.read_bytes() + session.ca_cert.read_bytes())
    (session.directory / "leaf.csr").unlink(missing_ok=True)


def _backup(session: _Session) -> Path | None:
    """把已有材料整体拷进 ``backup-<stamp>/``（换密钥 / 重建 CA 前留底）。"""
    names = ("ca.pem", "ca.key", "identity.key", "cert.pem", "key.pem", "cert-chain.pem", LEAF_CONFIG, "ca.srl")
    existing = [name for name in names if (session.directory / name).is_file()]
    if not existing:
        return None
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    target = session.directory / f"backup-{stamp}"
    index = 1
    while target.exists():
        # 同秒内跑两次破坏性命令：``copyfile`` 会静默覆盖同名文件，留底就不再是留底。
        target = session.directory / f"backup-{stamp}-{index}"
        index += 1
    target.mkdir(parents=True)
    for name in existing:
        # 同 _ensure_identity：不带元数据，否则 9p / drvfs 上备份会半途失败。
        shutil.copyfile(session.directory / name, target / name)
    return target


# ---------------------------------------------------------------- 前置检查与呈现


def _require(session: _Session, *paths: Path) -> None:
    missing = [path.name for path in paths if not path.is_file()]
    if missing:
        hint = "先执行 `heagent tls init`"
        if "identity.key" in missing:
            # 旧材料（scripts/gen_ws_cert.py 签出）没有身份密钥；迁移会换 CA，客户端改按 pin 信任。
            hint = "先执行 `heagent tls init --force` 迁移到身份密钥布局（旧材料会留底；CA 会换，客户端改按 pin 信任）"
        raise TlsCommandError(
            f"材料目录 {session.directory} 缺少 {', '.join(missing)}；{hint}", exit_code=EXIT_UNUSABLE
        )


def _require_leaf(session: _Session) -> None:
    if not session.leaf_cert.is_file():
        raise TlsCommandError(f"缺少叶证书 {session.leaf_cert}；先执行 `heagent tls issue`", exit_code=EXIT_UNUSABLE)


def _identity_spki(session: _Session) -> bytes:
    return key_spki_der(session.identity_key)


def _identity_pin(session: _Session) -> str:
    """身份密钥的 pin（还没有叶证书时也能打印——pin 的对象是密钥，不是证书）。"""
    return spki_sha256_of_der(_identity_spki(session))


def _identity_short(session: _Session) -> str:
    return short_fingerprint_of_der(_identity_spki(session))


def _render_report(info: TlsCertificateInfo, *, pin: str) -> str:
    """``fingerprint --format text`` 的四段人读视图（与 json 形态同源同值）。"""
    not_after = info.not_after.isoformat().replace("+00:00", "Z")
    san = ", ".join(info.san) if info.san else "（无 SAN 项）"
    return "\n".join(
        (
            f"spki_sha256       : {info.spki_sha256}",
            f"short_fingerprint : {info.short_fingerprint}",
            f"pin               : sha256/{pin}",
            f"not_after         : {not_after}",
            f"san               : {san}",
        )
    )


# ---------------------------------------------------------------- 命令


@click.group("tls")
@click.option(
    "--dir",
    "material_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="材料目录（默认 <当前目录>/.heagent/tls）",
)
@click.option("--openssl", "openssl_path", default=None, help="openssl 可执行文件路径（缺省查 PATH）")
@click.pass_context
def tls_cmd(ctx: click.Context, material_dir: Path | None, openssl_path: str | None) -> None:
    """WS TLS 身份材料：签发 / 轮换 / 指纹导出 / 一致性校验（客户端 pin 的是身份密钥）。"""
    directory = material_dir or _default_directory()
    # 一律转绝对路径：``verify`` 把路径交给 ``openssl`` 的同时把 cwd 设成该目录，相对路径会被
    # 解析两次（材料完好却报「叶证书不由此 CA 签发」）；其余子命令只受益于更明确的报错路径。
    ctx.obj = _Session(directory=Path(os.path.abspath(directory)), openssl=openssl_path)


@tls_cmd.command("init")
@click.option("--force", is_flag=True, help="已有材料时先备份再重建（会换 CA 与身份密钥 ⇒ 客户端要重新信任）")
@click.option("--ca-days", default=DEFAULT_CA_DAYS, type=int, show_default=True, help="CA 有效期（天）")
@click.option("--no-lan", is_flag=True, help="不自动探测本机局域网 IP")
@click.pass_obj
def init_materials(session: _Session, force: bool, ca_days: int, no_lan: bool) -> None:
    """建 CA 与长期身份密钥（幂等：已有材料不覆盖，除非 --force）。"""
    try:
        if ca_days < 1:
            raise TlsCommandError("--ca-days 必须是正整数")
        existing = [path.name for path in (session.ca_cert, session.ca_key, session.identity_key) if path.is_file()]
        if existing and not force:
            raise TlsCommandError(
                f"{session.directory} 已有材料（{', '.join(existing)}），未做任何改动；"
                "重建请加 --force（会更换 CA 与身份密钥，客户端需重新安装信任）"
            )
        binary = _find_openssl(session.openssl)
        session.directory.mkdir(parents=True, exist_ok=True)
        saved = _backup(session) if existing else None
        if saved is not None:
            click.echo(f"旧材料已备份到 {saved}")
        _write_leaf_config(session, _collect_san(session, (), include_lan=not no_lan))
        _create_ca(binary, session, ca_days)
        # 新 CA 是新密钥签发的：旧序列号文件留着会让新 CA 从旧序列段继续签发，而两者 subject
        # 相同（CA_SUBJECT 是常量）——等于两张 CA 证书共用一个 serial 前缀，没必要留这个坑。
        (session.directory / "ca.srl").unlink(missing_ok=True)
        _tighten(session.ca_key)
        _ensure_identity(binary, session, rotate=True)
        pin = spki_sha256_base64_of_der(_identity_spki(session))
        short = _identity_short(session)
    except (TlsCommandError, TlsIdentityError) as exc:
        _fail_exit(exc)

    click.echo(f"材料目录 : {session.directory}")
    click.echo(f"CA       : {session.ca_cert.name}（{ca_days} 天）")
    click.echo(f"身份密钥 : {session.identity_key.name}（长期固定，客户端 pin 的对象）")
    click.echo(f"pin      : sha256/{pin}")
    click.echo(f"短指纹   : {short}（完整值见 `heagent tls fingerprint --format text`）")
    click.echo("")
    click.echo("下一步：`heagent tls issue` 签发叶证书；再把 .env 的 WS_TLS_CERT_FILE / WS_TLS_KEY_FILE 指到本目录。")


@tls_cmd.command("issue")
@click.option("--days", default=DEFAULT_LEAF_DAYS, type=int, show_default=True, help="叶证书有效期（天）")
@click.option("--san", "san_items", multiple=True, help="追加 SAN 项（可重复；IP 或主机名）")
@click.option("--no-lan", is_flag=True, help="不自动探测本机局域网 IP")
@click.pass_obj
def issue_leaf_cmd(session: _Session, days: int, san_items: tuple[str, ...], no_lan: bool) -> None:
    """重签叶证书（**复用身份密钥** ⇒ pin 不变；只换有效期与 SAN）。"""
    try:
        if days < 1:
            raise TlsCommandError("--days 必须是正整数")
        binary = _find_openssl(session.openssl)
        _require(session, session.ca_cert, session.ca_key, session.identity_key)
        pin_before = _identity_pin(session)
        _write_leaf_config(session, _collect_san(session, san_items, include_lan=not no_lan))
        _issue_leaf(binary, session, days)
        info = certificate_info(session.leaf_cert)
        if info.spki_sha256 != pin_before:
            raise TlsCommandError("重签后公钥变了（身份密钥未被复用）——pin 会失效，请检查材料目录")
        pin = spki_sha256_base64(session.leaf_cert)
    except (TlsCommandError, TlsIdentityError) as exc:
        _fail_exit(exc)

    click.echo(f"叶证书   : {session.leaf_cert}（{days} 天）")
    click.echo(_render_report(info, pin=pin))
    click.echo("")
    click.echo("pin 未变（身份密钥复用）。重启 heagent 让 listener 重新加载证书。")


@tls_cmd.command("rotate-key")
@click.option("--yes", is_flag=True, help="确认轮换（会改变客户端 pin，需要重发安装包）")
@click.option("--days", default=DEFAULT_LEAF_DAYS, type=int, show_default=True, help="新叶证书有效期（天）")
@click.option("--no-lan", is_flag=True, help="不自动探测本机局域网 IP")
@click.pass_obj
def rotate_key(session: _Session, yes: bool, days: int, no_lan: bool) -> None:
    """轮换身份密钥（**唯一会改变客户端 pin 的动作**）：打印新旧指纹与双 pin 过渡提示。"""
    try:
        # 参数先于任何破坏性动作校验：``days`` 不合法时绝不能已经换了密钥（那会让客户端
        # pin 失效、又拿不到可用证书，两个坏结果同时成立）。
        if days < 1:
            raise TlsCommandError("--days 必须是正整数")
        binary = _find_openssl(session.openssl)
        _require(session, session.ca_cert, session.ca_key, session.identity_key)
        old_pin = _identity_pin(session)
        old_short = _identity_short(session)
        if not yes:
            if not sys.stdin.isatty():
                raise TlsCommandError("轮换身份密钥会改变客户端 pin，需要显式确认：加 --yes 后重试")
            click.confirm("轮换身份密钥会改变客户端 pin（需要重发安装包），继续？", abort=True)
        saved = _backup(session)
        if saved is not None:
            click.echo(f"旧材料已备份到 {saved}")
        _write_leaf_config(session, _collect_san(session, (), include_lan=not no_lan))
        _ensure_identity(binary, session, rotate=True)
        _issue_leaf(binary, session, days)
        new_pin = _identity_pin(session)
        new_short = _identity_short(session)
        info = certificate_info(session.leaf_cert)
    except (TlsCommandError, TlsIdentityError) as exc:
        _fail_exit(exc)

    if new_pin == old_pin:
        _fail("轮换后 pin 未变化（身份密钥没有真的换掉）", code=EXIT_PROBLEM)
    click.echo(f"旧 pin   : sha256/{_b64(old_pin)}   ({old_short})")
    click.echo(f"新 pin   : sha256/{_b64(new_pin)}   ({new_short})")
    click.echo(f"新证书   : 到期 {info.not_after.isoformat().replace('+00:00', 'Z')}")
    click.echo("")
    click.echo("双 pin 过渡：客户端下一版内置**旧 + 新**两个 pin，全部设备升级后再发一版移除旧 pin。")
    click.echo("过渡完成前，仍用旧 pin 的客户端握手会被拒（pin_mismatch）；轮换后需要重发安装包。")


def _b64(hex_digest: str) -> str:
    return base64.b64encode(bytes.fromhex(hex_digest)).decode("ascii")


@tls_cmd.command("fingerprint")
@click.option("--format", "output_format", type=click.Choice(FINGERPRINT_FORMATS), default="text", show_default=True)
@click.pass_obj
def fingerprint(session: _Session, output_format: str) -> None:
    """打印客户端该 pin 的指纹（text / json / pin 三形态，哈希逐字一致）。"""
    try:
        _require_leaf(session)
        info = certificate_info(session.leaf_cert)
        pin = spki_sha256_base64(session.leaf_cert)
    except (TlsCommandError, TlsIdentityError) as exc:
        _fail_exit(exc)

    if output_format == "pin":
        click.echo(f"sha256/{pin}")
        return
    if output_format == "json":
        click.echo(
            json.dumps(
                {
                    "spki_sha256": info.spki_sha256,
                    "short_fingerprint": info.short_fingerprint,
                    "pin": f"sha256/{pin}",
                    "not_after": info.not_after.isoformat().replace("+00:00", "Z"),
                    "san": list(info.san),
                },
                ensure_ascii=False,
            )
        )
        return
    click.echo(_render_report(info, pin=pin))


@tls_cmd.command("verify")
@click.pass_obj
def verify(session: _Session) -> None:
    """一致性校验：叶由本 CA 签发 / 叶公钥 == 身份密钥 / 到期余量 > 0（逐条列出）。"""
    try:
        binary = _find_openssl(session.openssl)
        _require(session, session.ca_cert, session.ca_key, session.identity_key)
        _require_leaf(session)
    except (TlsCommandError, TlsIdentityError) as exc:
        _fail_exit(exc)

    checks: list[tuple[str, bool, str]] = []
    verified = subprocess.run(  # nosec B603 - 定值参数 # noqa: S603 - 定值参数
        [binary, "verify", "-CAfile", str(session.ca_cert), str(session.leaf_cert)],
        cwd=str(session.directory),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    lines = (verified.stdout or verified.stderr or "").strip().splitlines()
    checks.append(("叶证书由 ca.pem 签发", verified.returncode == 0, lines[-1] if lines else ""))

    try:
        keys_ok = cert_key_matches(session.leaf_cert, session.identity_key)
        keys_note = "公钥一致" if keys_ok else "公钥不一致（身份密钥与证书不是一对）"
    except TlsIdentityError as exc:
        keys_ok = False
        keys_note = str(exc)
    checks.append(("叶证书公钥 == identity.key", keys_ok, keys_note))

    info = certificate_info(session.leaf_cert)
    remaining = info.not_after - datetime.now(UTC)
    checks.append(
        (
            "叶证书尚未到期",
            remaining.total_seconds() > 0,
            f"到期 {info.not_after.isoformat().replace('+00:00', 'Z')}（余 {remaining.days} 天）",
        )
    )

    click.echo(f"材料目录 : {session.directory}")
    click.echo(f"短指纹   : {info.short_fingerprint}")
    for label, ok, note in checks:
        click.echo(f"[{'OK' if ok else 'FAIL'}] {label}{f'：{note}' if note else ''}")
    if not all(ok for _, ok, _ in checks):
        raise SystemExit(EXIT_PROBLEM)


__all__ = ["tls_cmd"]
