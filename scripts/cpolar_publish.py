"""cpolar 发布口：读公网地址 → 回填 AIHome-Client → 常驻守护。

分工（三份脚本各管一段，地址口径只有一套）：
- ``scripts/cpolar_tunnel.ps1``：**唯一**「起隧道」实现 —— authtoken / 预留地址 ``-remote-addr`` /
  三源回读，并把结果落到 ``.heagent/tmp/cpolar-address.txt``；
- ``scripts/cpolar_selftest.ps1``：一条命令跑六项外部判据，读同一个地址文件；
- 本脚本：只做「读地址 + 回填 App + 守护」，**不自己拼 cpolar 参数、不把日志当唯一来源**。

地址回读（与另两份脚本同序；这个顺序是 2026-11-25 实测定的）：
① 本地管理面 ``http://127.0.0.1:9200/api/tunnels``（cpolar web UI 默认 9200，兼容 ngrok 血统的 4040；
   隧道活着必列 ``public_url``）→ ② ``.heagent/tmp/cpolar-address.txt`` → ③ 付费档预留地址
   ``.heagent/tmp/cpolar-remote-addr.txt`` → ④ ``%LOCALAPPDATA%\\cpolar\\tunnel*.log`` 的 ``Forwarding`` 行。
   3.3.12 的日志只吐控制通道 debug 行（``Pong from Switch Server`` 只能证明 authtoken 有效、控制通道在线），
   **隧道地址常常不在日志里** ⇒ 只认日志会把已建好的隧道判成「没起来」（当日三次假阴性）。
   非管理面来源（②③④）在**回填前**还要过一道活性闸门：探一次 TCP，连不上就当死地址拒绝写入
   （退出码 1；`--address` 显式给可跳过）。隧道改协议 / 地址轮换后旧文件仍留着死地址，
   没有这道闸门就会把 App 指向一个连不上的端点（A78，2026-11-27）。

用法（在仓库根、Windows 宿主）：
  .venv\\Scripts\\python.exe scripts\\cpolar_publish.py                    # 打印当前公网地址
  .venv\\Scripts\\python.exe scripts\\cpolar_publish.py --restart          # 先重起隧道再打印
  .venv\\Scripts\\python.exe scripts\\cpolar_publish.py --apply            # 地址有变才写进 App 的 prefs
  .venv\\Scripts\\python.exe scripts\\cpolar_publish.py --watch --apply    # 常驻：隧道掉了重起、地址变了回填
  .venv\\Scripts\\python.exe scripts\\cpolar_publish.py --address 1.tcp.vip.cpolar.cn:20046
                                                                          # 跳过回读，显式指定（应急）

退出码：0 成功 / 1 拿不到地址或写 App 失败 / 2 参数不合法。
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"
TMP_DIR = ROOT / ".heagent" / "tmp"
ADDRESS_FILE = TMP_DIR / "cpolar-address.txt"
RESERVED_FILE = TMP_DIR / "cpolar-remote-addr.txt"
TUNNEL_SCRIPT = ROOT / "scripts" / "cpolar_tunnel.ps1"

LOCALAPPDATA = pathlib.Path(os.environ.get("LOCALAPPDATA", ""))
CPOLAR_LOG_DIR = LOCALAPPDATA / "cpolar"

#: cpolar 本地管理面的端口（web UI 默认 9200；4040 是 ngrok 血统的兼容口）
ADMIN_API_PORTS = (9200, 4040)
ADDRESS_SHAPE = re.compile(r"^\S+:\d{1,5}$")
FORWARDING = re.compile(r"Forwarding\s+\S+://(\S+:\d{1,5})")
ANY_TUNNEL = re.compile(r"tcp://([^\s\"]+:\d{1,5})")

#: 权威地址来源的标签：与 `cpolar_tunnel.ps1` / `cpolar_selftest.ps1` 的回读次序一致（管理面优先）。
_SOURCE_ADMIN = "本地管理面 /api/tunnels"

CONTAINER = "aihome-android-verify"
ADB_SERIAL = "host.docker.internal:7555"
PACKAGE = "com.aihome.client"
PREFS_RELATIVE = "shared_prefs/connection_settings.xml"

PREFS_ENDPOINT = re.compile(r'<string name="websocket_endpoint">([^<]*)</string>')
PREFS_REVISION = re.compile(r'<long name="revision" value="(\d+)"')


def log(message: str) -> None:
    print(message, flush=True)


# ── 目标与地址回读 ──
#: 通配绑定的两个字面量：这里只做**比对**（不是 bind），但 ruff/bandit 的「硬编码全接口绑定」
#: 规则按字面量命中 ⇒ 显式豁免一次（同 `cli/http_config.py` 的 nosec 立场：抑制是正确姿态）。
_WILDCARD_HOSTS = frozenset({"0.0.0.0", "::"})  # noqa: S104  # nosec B104


def tunnel_target() -> str:
    """隧道目标 = WS listener 的真实绑定地址（`.env` 的 `WS_HOST:WS_PORT`）。

    回退值与 `cpolar_tunnel.ps1` / `cpolar_selftest.ps1` **同源**：缺键、`0.0.0.0`、`::` 一律落
    `127.0.0.1`（通配绑定没有可路由地址）。**不要**写死某台机器的私有 IP——那会让换机后的
    `[info] 隧道目标` 谎报一个隧道并未使用的主机。
    """
    host, port = "", ""
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.split("#", 1)[0].strip()
            if line.startswith("WS_HOST="):
                host = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("WS_PORT="):
                port = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not host or host in _WILDCARD_HOSTS:
        host = "127.0.0.1"
    return f"{host}:{port or '9201'}"


def normalize_address(value: str) -> str | None:
    """把 `wss://host:port` / `tcp://host:port` / `host:port` 统一成 `host:port`。"""
    text = re.sub(r"^[A-Za-z][A-Za-z0-9+.-]*://", "", value.strip()).rstrip("/")
    return text if ADDRESS_SHAPE.match(text) else None


def first_line(path: pathlib.Path) -> str | None:
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            value = line.strip()
            if value:
                return value
    except OSError:
        return None
    return None


def address_from_file(path: pathlib.Path) -> str | None:
    value = first_line(path)
    return value if value and ADDRESS_SHAPE.match(value) else None


def address_from_admin_api() -> str | None:
    """本地管理面是权威来源：隧道只要活着就会列出 `public_url`，与日志文本无关。"""
    for port in ADMIN_API_PORTS:
        # 只连本机管理面：scheme 与主机都是固定字面量，没有「由外部输入决定协议」的风险面
        endpoint = f"http://127.0.0.1:{port}/api/tunnels"
        try:
            with urllib.request.urlopen(endpoint, timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8", "replace"))
        except (OSError, ValueError, urllib.error.URLError):
            continue
        for tunnel in payload.get("tunnels") or []:
            url = str((tunnel or {}).get("public_url") or "")
            match = re.match(r"^tcp://(\S+:\d{1,5})$", url)
            if match:
                return match.group(1)
    return None


def _decode_log(raw: bytes) -> str:
    """cpolar 日志的编码不统一：按 BOM 判 UTF-16，否则先严格 UTF-8、失败再当无 BOM 的 UTF-16LE。

    本仓实测 cpolar / PowerShell 侧落盘的文本出现过 UTF-16LE（`FF FE` 开头、字符间夹空格），
    按 UTF-8 硬读会整篇变成替换符、正则静默零命中 ⇒ 第四级回读会假装「日志里没有地址」。
    """
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16", "replace")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-16-le", "replace")


def address_from_log() -> str | None:
    # 日志名带时间戳（每次起隧道一份），按 mtime 从新到旧找第一份含地址的
    if not CPOLAR_LOG_DIR.exists():
        return None

    def _mtime(path: pathlib.Path) -> float:
        try:
            return path.stat().st_mtime
        except OSError:  # 并发轮转删掉了：排序时按最旧计，不炸整个回读
            return 0.0

    for path in sorted(CPOLAR_LOG_DIR.glob("tunnel*.log"), key=_mtime, reverse=True):
        try:
            text = _decode_log(path.read_bytes())
        except OSError:  # 同上：读的瞬间被删
            continue
        hit = FORWARDING.search(text) or ANY_TUNNEL.search(text)
        if hit:
            return hit.group(1)
    return None


def public_address() -> tuple[str, str] | None:
    """按「管理面 → 地址文件 → 预留地址 → 隧道日志」回读，返回 (host:port, 来源)。"""
    sources = (
        (_SOURCE_ADMIN, address_from_admin_api),
        ("cpolar-address.txt", lambda: address_from_file(ADDRESS_FILE)),
        ("预留地址", lambda: address_from_file(RESERVED_FILE)),
        ("隧道日志", address_from_log),
    )
    for label, source in sources:
        value = source()
        if value:
            return value, label
    return None


def probe_reachable(address: str, timeout: float = 3.0) -> bool:
    """对 ``host:port`` 做一次 TCP 连接探测；连不上（含超时 / 解析失败）一律 ``False``。"""
    host, _, port = address.partition(":")
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except (OSError, ValueError):
        return False


def verified_address(address: str, source: str, *, explicit: bool = False) -> bool:
    """回填前的活性闸门（A78）：只有被证明「活着」或由用户显式指定的地址才许写进 App。

    管理面 ``/api/tunnels`` 是权威来源（隧道活着才列出 public_url）⇒ 免探。其余三个回退来源
    都可能拿到上一次运行留下的死地址（隧道改协议、地址轮换、管理面没起来），而付费档的预留
    地址又常常长期不变 ⇒ 探一次 TCP 再把关，比事后排查「App 连不上」便宜得多。
    """
    if explicit or source == _SOURCE_ADMIN:
        return True
    if probe_reachable(address):
        log(f"[ok] {source} 的地址 TCP 可达")
        return True
    log(f"[warn] {source} 的地址 TCP 不可达：可能是上一次运行留下的死地址，拒绝回填（确认无误时用 --address 显式给）")
    return False


# ── 隧道生命周期（起隧道统一委托给 cpolar_tunnel.ps1）──
def tunnel_running() -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq cpolar.exe", "/NH"],
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )
    except OSError:  # 非 Windows 宿主没有 tasklist：按「没在跑」处理，由调用方决定怎么办
        return False
    return "cpolar.exe" in (result.stdout or "").lower()


def start_tunnel(restart: bool) -> None:
    """调 `cpolar_tunnel.ps1 -Detach` 起隧道：authtoken、预留地址、三源回读只有那一份实现。"""
    if not TUNNEL_SCRIPT.exists():
        log(f"[tunnel] 缺 {TUNNEL_SCRIPT}，无法起隧道")
        return
    command = ["powershell", "-ExecutionPolicy", "Bypass", "-File", str(TUNNEL_SCRIPT), "-Detach"]
    if restart:
        command.append("-KillExisting")  # 已有进程时由 ps1 负责停旧的，本脚本不再自己 taskkill
    log("[tunnel] 起隧道（交给 cpolar_tunnel.ps1 -Detach）")
    try:
        result = subprocess.run(command, capture_output=True, text=True, errors="replace", check=False)
    except OSError as error:  # 非 Windows 宿主没有 powershell
        log(f"[tunnel] 起不了隧道（{error}）：请在宿主跑 scripts\\cpolar_tunnel.ps1 -Detach")
        return
    for line in (result.stdout or "").splitlines():
        log(f"  {line}")
    if result.returncode != 0:
        detail = (result.stderr or "").strip() or (result.stdout or "").strip().splitlines()[-1:]
        log(f"[tunnel] cpolar_tunnel.ps1 退出码 {result.returncode}：{detail}")


def ensure_tunnel(restart: bool = False, timeout_seconds: int = 60) -> tuple[str, str] | None:
    if restart or not tunnel_running():
        start_tunnel(restart)
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        found = public_address()
        if found:
            return found
        time.sleep(1)
    return None


# ── 回填手机 App（adb）──
def adb(*args: str, stdin: str | None = None) -> str:
    command = ["docker", "exec"]
    if stdin is not None:
        command.append("-i")
    command += [CONTAINER, "adb", "-s", ADB_SERIAL, *args]
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        errors="replace",
        input=stdin,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"adb 调用失败: {' '.join(args)}\n{result.stderr.strip()}")
    return result.stdout


def read_prefs() -> str:
    return adb("shell", f"run-as {PACKAGE} cat {PREFS_RELATIVE}")


def write_prefs(content: str) -> None:
    subprocess.run(
        ["docker", "exec", "-i", CONTAINER, "sh", "-c", "cat > /tmp/connection_settings.xml"],
        input=content,
        text=True,
        check=True,
    )
    adb("push", "/tmp/connection_settings.xml", "/data/local/tmp/connection_settings.xml")  # noqa: S108
    adb("shell", "am force-stop", PACKAGE)
    adb("shell", f"run-as {PACKAGE} cp /data/local/tmp/connection_settings.xml {PREFS_RELATIVE}")


def apply_to_app(url: str) -> bool:
    """把地址写进 App 的 prefs（`revision` 递增 ⇒ 任何端点变更都会触发推送通道复位）。"""
    current = read_prefs()
    stored = PREFS_ENDPOINT.search(current)
    if stored is None:
        raise RuntimeError("当前 prefs 里没有 websocket_endpoint 键：先在 App 里手填一次并保存，再跑本脚本")
    if stored.group(1) == url:
        log(f"[app] 已是 {url}，无需改动")
        return False
    revision = PREFS_REVISION.search(current)
    next_revision = (int(revision.group(1)) + 1) if revision else 1
    updated = current.replace(stored.group(0), f'<string name="websocket_endpoint">{url}</string>')
    if revision is not None:
        updated = updated.replace(revision.group(0), f'<long name="revision" value="{next_revision}"')
    write_prefs(updated)
    if f">{url}</string>" not in read_prefs():
        raise RuntimeError("写入后回读不一致：App 可能仍持有 prefs（彻底关掉 App 再试）")
    log(f"[app] 已写入 {url}（revision {next_revision}），App 已停，下次打开生效")
    return True


# ── 可选的 SAN 提示（默认不做，且从不阻断）──
def cert_covers(host: str, port: str, exe: str) -> bool | None:
    """对面证书是否覆盖这个主机名；`None` = 判不了。仅供 `--check-san` 排查用。"""
    try:
        result = subprocess.run(
            [exe, "s_client", "-connect", f"{host}:{port}", "-servername", host, "-verify_hostname", host],
            input="",
            capture_output=True,
            text=True,
            errors="replace",
            timeout=25,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):  # 连不上 / 超时都只是「判不了」
        return None
    text = (result.stdout or "") + (result.stderr or "")
    if "connect:errno" in text or "getaddrinfo" in text or "Connection refused" in text:
        return None  # 连不上（隧道没起 / 无外网）⇒ 判不了，不要当「覆盖了」
    if "no peer certificate" in text:
        return False
    return "hostname mismatch" not in text


def report_san(address: str) -> None:
    """只提示：客户端只认 SPKI pin、不校主机名（`docs/errors.md` 第四节）⇒ SAN 不覆盖也能连。"""
    host, _, port = address.partition(":")
    exe = shutil.which("openssl")
    if not exe:
        log("[san] 宿主没有 openssl，跳过（对只认 pin 的客户端无影响）")
        return
    covers = cert_covers(host, port or "443", exe)
    if covers is None:
        log(f"[san] 连不上 {host}:{port or '443'}，判不了 SAN（隧道没起或本机无外网）")
    elif covers is False:
        log(f"[san] 证书 SAN 不含 {host}：对只认 pin 的客户端**无影响**，不必为此重签；")
        log(f"      真要给会校主机名的客户端用：heagent tls issue --san {host}（重签叶证书后重启 heagent）")
    elif covers:
        log(f"[san] 证书 SAN 含 {host}")


# ── 入口 ──
def publish(address: str, source: str, apply: bool, check_san: bool, *, explicit: bool = False) -> int:
    """打印 / 回填一个公网地址；``apply`` 时先过活性闸门，死地址一律不写（退出码 1）。

    只打印（不带 ``--apply``）时死地址只给 WARNING、仍回 0——此时没有任何副作用，拦下来反而
    妨碍「先把地址看一眼」的用法。
    """
    url = f"wss://{address}"
    log(f"[ok] 公网地址 {url}（来源：{source}）")
    if check_san:
        report_san(address)
    if not apply:
        # 只打印时死地址只给 WARNING（没有任何副作用），不改变退出码。
        verified_address(address, source, explicit=explicit)
        return 0
    if not verified_address(address, source, explicit=explicit):
        return 1
    try:
        apply_to_app(url)
    except (RuntimeError, subprocess.SubprocessError) as error:
        log(f"[fail] 回填 App 失败：{error}")
        return 1
    return 0


def watch(apply: bool, check_san: bool, interval: int) -> None:
    log("[watch] 常驻：隧道掉了重起、地址变了就回填（Ctrl+C 结束）")
    last_seen: str | None = None
    last_applied: str | None = None
    last_checked: str | None = None
    while True:
        found = ensure_tunnel()
        if found is None:
            log("[watch] 隧道没起来，30 秒后重试")
        else:
            address, source = found
            if address != last_seen:
                log(f"[watch] 公网地址 {address}（来源：{source}）")
                last_seen = address
            if apply and address != last_applied and verified_address(address, source):
                try:
                    apply_to_app(f"wss://{address}")  # 返回 False = 本来就是它，同样算同步完成
                    last_applied = address
                except (RuntimeError, subprocess.SubprocessError) as error:  # 设备不在线不该打死守护循环
                    # **不**更新 last_applied：设备掉线是一时的，地址却可能长期不变（付费预留地址）
                    # ⇒ 下一轮必须重试，否则这次的失败会被永久记住、App 永远停在旧地址。
                    log(f"[watch] 回填失败（下一轮重试）：{error}")
            if check_san and address != last_checked:
                report_san(address)
                last_checked = address
        time.sleep(interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="cpolar 发布口：读公网地址并回填 AIHome-Client")
    parser.add_argument("--apply", action="store_true", help="地址有变化时写进 App 的 prefs")
    parser.add_argument("--restart", action="store_true", help="先重起隧道（交给 cpolar_tunnel.ps1 -KillExisting）")
    parser.add_argument("--watch", action="store_true", help="常驻：隧道掉线重起、地址变化回填")
    parser.add_argument("--interval", type=int, default=30, help="--watch 的检查间隔（秒）")
    parser.add_argument("--address", default="", help="跳过回读，显式指定 host:port（应急）")
    parser.add_argument("--check-san", action="store_true", help="额外提示对面证书是否覆盖该主机名（默认不做）")
    parser.add_argument("--timeout", type=int, default=60, help="等地址的超时（秒，默认 60）")
    args = parser.parse_args(argv)

    if args.watch:
        watch(args.apply, args.check_san, args.interval)
        return 0

    if args.address:
        address = normalize_address(args.address)
        if address is None:
            log(f"[fail] --address 形状不对（要 host:port）：{args.address}")
            return 2
        return publish(address, "--address 显式指定", args.apply, args.check_san, explicit=True)

    log(f"[info] 隧道目标 {tunnel_target()}")
    found = ensure_tunnel(restart=args.restart, timeout_seconds=args.timeout)
    if found is None:
        log("[fail] 没回读到公网地址：管理面 /api/tunnels、cpolar-address.txt、预留地址、日志四路全空")
        log("       先跑 scripts\\cpolar_tunnel.ps1 -Detach 看它的诊断块，或 --address 显式指定")
        return 1
    address, source = found
    return publish(address, source, args.apply, args.check_san)


if __name__ == "__main__":
    sys.exit(main())
