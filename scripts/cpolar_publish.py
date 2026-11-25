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

CONTAINER = "aihome-android-verify"
ADB_SERIAL = "host.docker.internal:7555"
PACKAGE = "com.aihome.client"
PREFS_RELATIVE = "shared_prefs/connection_settings.xml"

PREFS_ENDPOINT = re.compile(r'<string name="websocket_endpoint">([^<]*)</string>')
PREFS_REVISION = re.compile(r'<long name="revision" value="(\d+)"')


def log(message: str) -> None:
    print(message, flush=True)


# ── 目标与地址回读 ──
def tunnel_target() -> str:
    """隧道目标 = WS listener 的真实绑定地址（`.env` 的 WS_HOST:WS_PORT）。"""
    host, port = "", ""
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.split("#", 1)[0].strip()
            if line.startswith("WS_HOST="):
                host = line.split("=", 1)[1].strip().strip('"').strip("'")
            elif line.startswith("WS_PORT="):
                port = line.split("=", 1)[1].strip().strip('"').strip("'")
    return f"{host or '192.168.2.226'}:{port or '9201'}"


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


def address_from_log() -> str | None:
    # 日志名带时间戳（每次起隧道一份），按 mtime 从新到旧找第一份含地址的
    if not CPOLAR_LOG_DIR.exists():
        return None
    candidates = sorted(
        CPOLAR_LOG_DIR.glob("tunnel*.log"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for path in candidates:
        text = path.read_text(encoding="utf-8", errors="replace")
        hit = FORWARDING.search(text) or ANY_TUNNEL.search(text)
        if hit:
            return hit.group(1)
    return None


def public_address() -> tuple[str, str] | None:
    """按「管理面 → 地址文件 → 预留地址 → 隧道日志」回读，返回 (host:port, 来源)。"""
    sources = (
        ("本地管理面 /api/tunnels", address_from_admin_api),
        ("cpolar-address.txt", lambda: address_from_file(ADDRESS_FILE)),
        ("预留地址", lambda: address_from_file(RESERVED_FILE)),
        ("隧道日志", address_from_log),
    )
    for label, source in sources:
        value = source()
        if value:
            return value, label
    return None


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
def publish(address: str, source: str, apply: bool, check_san: bool) -> int:
    url = f"wss://{address}"
    log(f"[ok] 公网地址 {url}（来源：{source}）")
    if check_san:
        report_san(address)
    if not apply:
        return 0
    try:
        apply_to_app(url)
    except (RuntimeError, subprocess.SubprocessError) as error:
        log(f"[fail] 回填 App 失败：{error}")
        return 1
    return 0


def watch(apply: bool, check_san: bool, interval: int) -> None:
    log("[watch] 常驻：隧道掉了重起，地址变了就回填（Ctrl+C 结束）")
    last: str | None = None
    while True:
        found = ensure_tunnel()
        if found is None:
            log("[watch] 隧道没起来，30 秒后重试")
        else:
            address, source = found
            if address != last:
                log(f"[watch] 公网地址 {address}（来源：{source}）")
                if apply:
                    try:
                        apply_to_app(f"wss://{address}")
                    except (RuntimeError, subprocess.SubprocessError) as error:  # 设备不在线不该打死守护循环
                        log(f"[watch] 回填失败：{error}")
                if check_san:
                    report_san(address)
                last = address
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
        return publish(address, "--address 显式指定", args.apply, args.check_san)

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
