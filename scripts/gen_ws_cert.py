"""签发 / 轮换 HeAgent WS 用的 TLS 材料：本地 CA + 短有效期叶证书。

为什么不是「一张 30 天自签证书」：自签叶证书一到期，客户端就得重新导入一次信任。
拆成「长期 CA + 30 天叶证书」之后，客户端只信任 CA 一次，之后每次轮换都只重签叶证书，
客户端侧不用动。

产物（默认落在 ``.heagent/tls/``，仓库 .gitignore 已忽略）：

  ca.pem / ca.key        本地 CA（默认 10 年）。**只把 ca.pem 分发给客户端**，ca.key 永不外发。
  cert.pem / key.pem     叶证书与私钥（默认 30 天）。`.env` 的 WS_TLS_CERT_FILE / WS_TLS_KEY_FILE 指向它。
  cert-chain.pem         叶 + CA 拼接（客户端要求发链时用）。
  openssl-leaf.cnf       由本脚本生成的 SAN / 用途声明——改 SAN 请改命令行参数，不要手改此文件。
  ca.srl                 签发序列号。**轮换时不要删**。
  backup-<stamp>/        每次写入前把旧材料整体备份到这里。

依赖 `openssl` 命令行（本仓不以 `cryptography` 为依赖）。宿主没装时用 ``--openssl`` 指定路径，
脚本也会探测 Git for Windows / OpenSSL-Win64 的常见安装位置。

用法（仓库根目录；缺省只打印计划，不动文件）：

  .venv\\Scripts\\python.exe scripts\\gen_ws_cert.py                        # 打印计划
  .venv\\Scripts\\python.exe scripts\\gen_ws_cert.py --apply                # 轮换叶证书（CA 缺失则先建）
  .venv\\Scripts\\python.exe scripts\\gen_ws_cert.py --apply --san 192.168.1.23
  .venv\\Scripts\\python.exe scripts\\gen_ws_cert.py --apply --days 90 --san heagent.lan
  .venv\\Scripts\\python.exe scripts\\gen_ws_cert.py --apply --new-ca      # 重建 CA（客户端要重新信任）

写完重启 heagent 才生效（证书在 listener 启动时加载一次）。
"""

from __future__ import annotations

import argparse
import contextlib
import ipaddress
import shutil
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_OUT_DIR = ".heagent/tls"
DEFAULT_DAYS = 30
DEFAULT_CA_DAYS = 3650
CA_SUBJECT = "/CN=HeAgent Local CA/O=HeAgent Lab"
LOOPBACK_IP = "127.0.0.1"
IPV6_LOOPBACK = "0:0:0:0:0:0:0:1"
LOOPBACK_ENTRIES = frozenset({f"IP:{LOOPBACK_IP}", f"IP:{IPV6_LOOPBACK}", "IP:::1"})

# 默认 SAN：回环 + 常见「虚拟机 → 宿主」网关地址。
# VirtualBox / QEMU slirp NAT 的宿主是 10.0.2.2；libvirt 默认 NAT 的宿主是 192.168.122.1。
# 桥接 / Hyper-V / VMware NAT 的地址随机器而变，须用 --san 追加，否则信任通过后会变成 hostname mismatch。
DEFAULT_SAN: tuple[str, ...] = (
    f"IP:{LOOPBACK_IP}",
    f"IP:{IPV6_LOOPBACK}",
    "DNS:localhost",
    "DNS:heagent.local",
    "IP:10.0.2.2",
    "IP:192.168.122.1",
)

# 宿主上 openssl 不一定在 PATH 里；这三个位置覆盖 Git for Windows 与 OpenSSL 官方安装包。
OPENSSL_CANDIDATES: tuple[str, ...] = (
    r"C:\Program Files\Git\usr\bin\openssl.exe",
    r"C:\Program Files\Git\mingw64\bin\openssl.exe",
    r"C:\Program Files\OpenSSL-Win64\bin\openssl.exe",
)


class CertError(RuntimeError):
    """前提不成立或 openssl 失败（不猜、不降级、不假装成功）。"""


# ---------------------------------------------------------------- SAN 处理


def detect_lan_ips() -> list[str]:
    """本机非回环 IPv4 列表（探测不到返回空表；绝不猜 0.0.0.0）。"""
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
        if address.version != 4 or address.is_loopback or address.is_unspecified or address.is_link_local:
            continue
        if candidate not in result:
            result.append(candidate)
    return result


def normalize_san(raw: str) -> str:
    """把命令行给的一项 SAN 规范化成 ``IP:`` / ``DNS:`` 形式；认不出就 fail-loud。"""
    text = raw.strip()
    if not text:
        raise CertError("SAN 项不能为空")
    upper = text.upper()
    if upper.startswith(("IP:", "DNS:")):
        kind, _, value = text.partition(":")
        value = value.strip()
        if not value:
            raise CertError(f"{text!r} 缺值")
        if kind.upper() == "IP":
            try:
                return f"IP:{ipaddress.ip_address(value)}"
            except ValueError as exc:
                raise CertError(f"{value!r} 不是 IP 字面量") from exc
        return f"DNS:{value}"
    try:
        return f"IP:{ipaddress.ip_address(text)}"
    except ValueError:
        pass
    # 形似 IP 但解析失败（如 192.168.1.999 / fe80::zz）：一定是打错了。
    # 放行会变成 DNS 项，客户端不报错、只在连接时变成 hostname mismatch —— 宁可当场 fail-loud。
    if text and set(text) <= set("0123456789abcdefABCDEF:."):
        raise CertError(f"{text!r} 形似 IP 但解析失败（检查是否打错）")
    if any(ch in text for ch in " \t/\\:@") or text.startswith("-"):
        raise CertError(f"{text!r} 既不是 IP 也不是主机名（写错会导致客户端 hostname mismatch）")
    return f"DNS:{text}"


def collect_san_entries(extras: list[str], *, include_lan: bool) -> list[str]:
    """默认项 + 自动探测的局域网 IP + 命令行追加项，去重后保序。"""
    entries: list[str] = list(DEFAULT_SAN)
    if include_lan:
        entries.extend(f"IP:{address}" for address in detect_lan_ips())
    entries.extend(normalize_san(item) for item in extras)
    seen: set[str] = set()
    result: list[str] = []
    for entry in entries:
        key = entry.lower()  # DNS 名大小写不敏感；IP 已被 ipaddress 规范化
        if key in seen:
            continue
        seen.add(key)
        result.append(entry)
    return result


def render_leaf_config(san_entries: list[str]) -> str:
    """生成叶证书的 openssl 配置（SAN 与用途的唯一落点）。"""
    # IP 与 DNS 各自从 1 开始独立编号：混编会在配置里留编号空洞（openssl 接受，
    # 但读起来像漏项），也与手改模板的人预期不符。
    ip_lines = [
        f"IP.{index} = {entry[3:]}"
        for index, entry in enumerate((item for item in san_entries if item.startswith("IP:")), 1)
    ]
    dns_lines = [
        f"DNS.{index} = {entry[4:]}"
        for index, entry in enumerate((item for item in san_entries if item.startswith("DNS:")), 1)
    ]
    alt_lines = [*ip_lines, *dns_lines]
    alt_block = "\n".join(alt_lines) if alt_lines else "# （无 SAN 项）"
    return (
        "# 由 scripts/gen_ws_cert.py 生成，请勿手改——改 SAN 请改命令行参数后重跑。\n"
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


# ---------------------------------------------------------------- openssl 调用


def find_openssl(explicit: str | None) -> str:
    """定位 openssl 可执行文件：--openssl > PATH > Windows 常见安装位置。"""
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            raise CertError(f"--openssl 指向的文件不存在：{explicit}")
        return str(path)
    found = shutil.which("openssl")
    if found:
        return found
    for candidate in OPENSSL_CANDIDATES:
        if Path(candidate).is_file():
            return candidate
    raise CertError(
        "找不到 openssl。装一个（Git for Windows 自带），或用 --openssl <路径> 指定；"
        "也可以让 agent 在容器里代签（那边有 openssl 3.x）"
    )


def run_openssl(binary: str, args: list[str], *, cwd: Path) -> str:
    # 参数是脚本内构造的定值（不含外部输入拼接），不经 shell。
    completed = subprocess.run(
        [binary, *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise CertError(f"openssl {args[0]} 失败（exit {completed.returncode}）：{detail}")
    return completed.stdout


def create_ca(binary: str, out_dir: Path, ca_days: int) -> None:
    run_openssl(
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
        cwd=out_dir,
    )


def issue_leaf(binary: str, out_dir: Path, days: int, config_name: str) -> None:
    """重签叶证书。``-CAcreateserial`` 复用已有的 ca.srl，序列号只增不复用。"""
    run_openssl(binary, ["genrsa", "-out", "key.pem", "2048"], cwd=out_dir)
    run_openssl(binary, ["req", "-new", "-key", "key.pem", "-config", config_name, "-out", "leaf.csr"], cwd=out_dir)
    run_openssl(
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
            config_name,
            "-extensions",
            "v3_req",
            "-out",
            "cert.pem",
        ],
        cwd=out_dir,
    )
    chain = (out_dir / "cert.pem").read_bytes() + (out_dir / "ca.pem").read_bytes()
    (out_dir / "cert-chain.pem").write_bytes(chain)
    (out_dir / "leaf.csr").unlink(missing_ok=True)


# ---------------------------------------------------------------- 落盘


def write_text_lf(path: Path, text: str) -> None:
    """按字节写：Windows 上 text mode 会把 ``\\n`` 翻成 ``\\r\\n``（配置文件要 LF）。"""
    path.write_bytes(text.encode("utf-8"))


def backup_materials(out_dir: Path) -> Path | None:
    """把已有材料整体拷到 ``backup-<stamp>/``；没有可备份的返回 None。"""
    names = ("ca.pem", "ca.key", "cert.pem", "key.pem", "cert-chain.pem", "openssl-leaf.cnf", "ca.srl")
    existing = [name for name in names if (out_dir / name).is_file()]
    if not existing:
        return None
    target = out_dir / f"backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    target.mkdir(parents=True, exist_ok=True)
    for name in existing:
        shutil.copy2(out_dir / name, target / name)
    return target


def describe_materials(binary: str, out_dir: Path) -> str:
    """读完再报告：subject / issuer / 有效期 / SAN 一律来自刚签出来的文件本身。"""
    head = run_openssl(
        binary,
        ["x509", "-in", "cert.pem", "-noout", "-subject", "-issuer", "-dates", "-ext", "subjectAltName"],
        cwd=out_dir,
    )
    return head.strip()


def verify_chain(binary: str, out_dir: Path) -> str:
    """链校验：失败即 CertError（绝不把「签了但链不通」报成成功）。"""
    return run_openssl(binary, ["verify", "-CAfile", "ca.pem", "cert.pem"], cwd=out_dir).strip()


def client_trust_hint(out_dir: Path, san_entries: list[str]) -> str:
    ca_path = (out_dir / "ca.pem").resolve()
    addresses = [entry[3:] for entry in san_entries if entry.startswith("IP:") and entry not in LOOPBACK_ENTRIES]
    lines = [
        "",
        "客户端侧（只拷 ca.pem，不要拷 ca.key / key.pem）：",
        "  Windows : certutil -addstore -f Root ca.pem",
        "  Linux   : cp ca.pem /usr/local/share/ca-certificates/heagent-ca.crt && update-ca-certificates",
        "  Node    : 设置 NODE_EXTRA_CA_CERTS=<ca.pem 路径>（Electron / Node 不读系统信任库）",
        "  Python  : 设置 SSL_CERT_FILE / REQUESTS_CA_BUNDLE",
        "  Java    : keytool -importcert -cacerts -alias heagent -file ca.pem",
        "  Firefox : 自带信任库，走设置页单独导入",
        f"  本机 CA 路径：{ca_path}",
    ]
    if addresses:
        lines.append(f"  客户端可连的地址：{', '.join(addresses)}（不在 SAN 里的地址会报 hostname mismatch）")
    return "\n".join(lines)


# ---------------------------------------------------------------- 入口


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="签发 / 轮换 WS 用的 TLS 材料（本地 CA + 短有效期叶证书）")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help=f"材料落点（默认 {DEFAULT_OUT_DIR}）")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS, help=f"叶证书有效期天数（默认 {DEFAULT_DAYS}）")
    parser.add_argument("--ca-days", type=int, default=DEFAULT_CA_DAYS, help=f"CA 有效期天数（默认 {DEFAULT_CA_DAYS}）")
    parser.add_argument("--san", action="append", default=[], help="追加 SAN 项（可重复；IP 或主机名）")
    parser.add_argument("--no-lan", action="store_true", help="不自动探测本机局域网 IP")
    parser.add_argument("--new-ca", action="store_true", help="重建 CA（客户端必须重新信任新 CA）")
    parser.add_argument("--openssl", default=None, help="openssl 可执行文件路径（缺省查 PATH 与常见安装位置）")
    parser.add_argument("--apply", action="store_true", help="真正写入（缺省只打印计划，不动文件）")
    args = parser.parse_args(argv)

    if args.days < 1 or args.ca_days < 1:
        print("错误：--days / --ca-days 必须是正整数", file=sys.stderr)
        return 2

    try:
        binary = find_openssl(args.openssl)
        san_entries = collect_san_entries(args.san, include_lan=not args.no_lan)
    except CertError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    out_dir = Path(args.out_dir)
    ca_exists = (out_dir / "ca.pem").is_file() and (out_dir / "ca.key").is_file()
    make_ca = args.new_ca or not ca_exists

    print(f"openssl  : {binary}")
    print(f"落点     : {out_dir.resolve()}")
    print(f"CA       : {'重建（客户端需重新信任）' if make_ca else '沿用现有'}，{args.ca_days} 天")
    print(f"叶证书   : {args.days} 天")
    print("SAN      :")
    for entry in san_entries:
        print(f"  {entry}")
    if (out_dir / "ca.srl").is_file():
        print("ca.srl   : 保留（序列号只增不复用）")

    if not args.apply:
        print("\n未写入任何文件（确认 SAN 无误后加 --apply 落盘）")
        return 0

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        saved = backup_materials(out_dir)
        if saved is not None:
            print(f"\n备份旧材料 -> {saved}")
        if make_ca:
            create_ca(binary, out_dir, args.ca_days)
        config_name = "openssl-leaf.cnf"
        write_text_lf(out_dir / config_name, render_leaf_config(san_entries))
        issue_leaf(binary, out_dir, args.days, config_name)
        (out_dir / "key.pem").chmod(0o600)
        (out_dir / "ca.key").chmod(0o600)
        verified = verify_chain(binary, out_dir)
        described = describe_materials(binary, out_dir)
    except CertError as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1

    print("\n签发完成：")
    print(f"  {verified}")
    for line in described.splitlines():
        print(f"  {line.strip()}")
    print(client_trust_hint(out_dir, san_entries))
    print("\n下一步：重启 heagent（证书在 listener 启动时加载一次），再确认日志 ws event=started ... tls=wss")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
