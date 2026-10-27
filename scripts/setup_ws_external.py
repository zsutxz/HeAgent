"""为 WS 对外 listener 准备配置：ws_auth_token（用户级 setting.md）+ WS_EXTERNAL_HOST（项目 .env）。

为什么要脚本而不是手改：两处改动有**顺序依赖**——对外 listener 缺 token 会 fail-closed 拒绝启动，
所以 token 必须先就位、host 才能写进 `.env`。本脚本把两件事绑成一次原子操作，并为两个文件各留备份。

纪律（与本仓既有口径一致）：
  * token 只写用户级 `<home>/.heagent/setting.md`：项目 `.env` 里写 WS_AUTH_TOKEN 既不生效，
    也会被诊断面判成未知键；
  * 两个文件都先备份再原子写；重复执行幂等（已有 token 则复用，已有 host 行则就地替换）；
  * 保持原文件的 EOL / BOM / 末行换行状态；
  * 前提不成立就 fail-loud（setting.md 有内容却无 YAML frontmatter 时拒绝猜）。

用法（宿主 Windows，仓库根目录）：

  .venv\\Scripts\\python.exe scripts\\setup_ws_external.py                 # 只打印计划（默认，不动文件）
  .venv\\Scripts\\python.exe scripts\\setup_ws_external.py --apply         # 真正写入（自动探测局域网 IP）
  .venv\\Scripts\\python.exe scripts\\setup_ws_external.py --host 192.168.1.23 --apply
"""

from __future__ import annotations

import argparse
import ipaddress
import re
import secrets
import shutil
import socket
import sys
from datetime import datetime
from pathlib import Path

TOKEN_KEY = "ws_auth_token"  # noqa: S105 - 这是键名不是凭证
ENV_KEY = "WS_EXTERNAL_HOST"
LOOPBACK_PREFIXES = ("127.",)
APIPA_PREFIXES = ("169.254.",)


class SetupError(RuntimeError):
    """配置前提不成立（不猜、不降级）。"""


# ---------------------------------------------------------------- 探测


def detect_lan_ip() -> str | None:
    """返回本机第一个非回环 IPv4；探测不到返回 None（绝不猜 0.0.0.0）。"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            # 只让内核选源地址，不实际发包（UDP connect 不发数据）。
            sock.connect(("8.8.8.8", 80))
            candidate = sock.getsockname()[0]
        if not candidate.startswith(LOOPBACK_PREFIXES + APIPA_PREFIXES):
            return candidate
    except OSError:
        pass
    try:
        for candidate in socket.gethostbyname_ex(socket.gethostname())[2]:
            if not candidate.startswith(LOOPBACK_PREFIXES + APIPA_PREFIXES):
                return candidate
    except OSError:
        pass
    return None


def validate_host(host: str) -> str:
    """对外 listener 的绑定地址必须是具体的非回环 IP。"""
    text = host.strip()
    try:
        address = ipaddress.ip_address(text)
    except ValueError as exc:
        raise SetupError(f"{text!r} 不是 IP 字面量；请写本机局域网 IP（如 192.168.1.23）") from exc
    if address.is_loopback:
        raise SetupError(f"{text} 是回环地址：本机客户端已由主 listener 服务，对外 listener 不接受回环")
    if address.is_unspecified:
        raise SetupError(f"{text} 会绑所有网卡（含可能的公网）；请写具体局域网 IP")
    return text


# ---------------------------------------------------------------- 文本改写（纯函数）


def detect_eol(raw: str) -> str:
    crlf = raw.count("\r\n")
    lf = raw.count("\n") - crlf
    return "\r\n" if crlf > lf else "\n"


def upsert_env_value(raw: str, key: str, value: str) -> str:
    """在 dotenv 文本里就地替换 `KEY=...` 行；没有则追加到末尾（保持 EOL 与末行状态）。"""
    eol = detect_eol(raw)
    ends_with_eol = raw.endswith(eol)
    lines = raw.split(eol)
    if ends_with_eol:
        lines = lines[:-1]
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=", re.IGNORECASE)
    replacement = f"{key}={value}"
    for index, line in enumerate(lines):
        if pattern.match(line):
            lines[index] = replacement
            break
    else:
        lines.append(replacement)
    return eol.join(lines) + (eol if ends_with_eol else "")


def read_frontmatter_value(raw: str, key: str) -> str | None:
    eol = detect_eol(raw)
    lines = raw.split(eol)
    if not lines or lines[0].strip() != "---":
        return None
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration:
        return None
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*:\s*(?P<value>.*)$", re.IGNORECASE)
    for line in lines[1:end]:
        match = pattern.match(line)
        if match:
            return match.group("value").strip().strip("'\"") or None
    return None


def upsert_frontmatter_value(raw: str, key: str, value: str) -> str:
    """在 YAML frontmatter 内 upsert 一个键；没有 frontmatter 即 fail-loud。"""
    eol = detect_eol(raw)
    lines = raw.split(eol)
    if not lines or lines[0].strip() != "---":
        raise SetupError("setting.md 有内容但没有 YAML frontmatter（首行须为 ---）；请手工加 frontmatter 后重跑")
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration as exc:
        raise SetupError("setting.md 的 frontmatter 没有闭合的 ---；拒绝修改") from exc
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*:", re.IGNORECASE)
    for index in range(1, end):
        if pattern.match(lines[index]):
            lines[index] = f"{key}: {value}"
            return eol.join(lines)
    lines.insert(end, f"{key}: {value}")
    return eol.join(lines)


# ---------------------------------------------------------------- 文件操作


def backup(path: Path, backup_dir: Path) -> Path | None:
    if not path.is_file():
        return None
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = backup_dir / f"{path.name}.{stamp}.bak"
    shutil.copy2(path, target)
    return target


def render_summary(path: Path, old: str | None, new: str) -> str:
    if old is None:
        return f"  {path}: 新建，{len(new.splitlines())} 行"
    old_lines = old.splitlines()
    new_lines = new.splitlines()
    added = len(new_lines) - len(old_lines)
    changed = sum(1 for a, b in zip(old_lines, new_lines, strict=False) if a != b)
    return f"  {path}: {len(old_lines)} -> {len(new_lines)} 行（新增 {added:+d} 行，内容变化 {changed} 行）"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="配置 WS 对外 listener（token + 绑定地址）")
    parser.add_argument("--host", default=None, help="对外绑定地址；缺省自动探测本机局域网 IPv4")
    parser.add_argument("--setting-md", default=None, help="用户级 setting.md（默认 <home>/.heagent/setting.md）")
    parser.add_argument("--env-file", default=".env", help="项目 .env 路径（默认 .env）")
    parser.add_argument("--backup-dir", default=".heagent/backups", help="备份目录")
    parser.add_argument("--token", default=None, help="指定 token（缺省复用已有或随机生成）")
    parser.add_argument("--apply", action="store_true", help="真正写入（缺省只打印计划，不动文件）")
    args = parser.parse_args(argv)

    env_path = Path(args.env_file)
    if not env_path.is_file():
        print(f"错误：找不到 {env_path}（请在仓库根目录运行）", file=sys.stderr)
        return 2
    setting_path = Path(args.setting_md) if args.setting_md else Path.home() / ".heagent" / "setting.md"

    # 1) 绑定地址
    host = validate_host(args.host) if args.host else detect_lan_ip()
    if host is None:
        print("错误：探测不到局域网 IPv4，请用 --host <IP> 指定", file=sys.stderr)
        return 2
    if not args.host:
        host = validate_host(host)
        print(f"自动探测到本机地址 {host}（若这不是要暴露的那块网卡，请用 --host 指定）\n")

    # 2) token：复用已有，否则生成
    setting_raw = setting_path.read_text(encoding="utf-8") if setting_path.is_file() else ""
    token = args.token or read_frontmatter_value(setting_raw, TOKEN_KEY) or secrets.token_urlsafe(32)

    # 3) 计算两份新内容
    env_raw = env_path.read_text(encoding="utf-8")
    new_env = upsert_env_value(env_raw, ENV_KEY, host)
    if setting_path.is_file():
        new_setting = upsert_frontmatter_value(setting_raw, TOKEN_KEY, token)
    else:
        new_setting = f"---\n{TOKEN_KEY}: {token}\n---\n"

    print("将要应用：")
    print(f"  WS_EXTERNAL_HOST = {host}")
    print(f"  {TOKEN_KEY} = <{len(token)} 字符，值不打印>")
    print(render_summary(env_path, env_raw, new_env))
    print(render_summary(setting_path, setting_raw if setting_path.is_file() else None, new_setting))

    if not args.apply:
        print("\n未写入任何文件（确认无误后加 --apply 落盘）")
        return 0

    # 4) 先写 token 侧（host 生效前 token 必须就位），再写 .env
    backup_dir = Path(args.backup_dir)
    for path in (setting_path, env_path):
        saved = backup(path, backup_dir)
        if saved is not None:
            print(f"备份 {path} -> {saved}")
    setting_path.parent.mkdir(parents=True, exist_ok=True)
    setting_path.write_text(new_setting, encoding="utf-8")
    env_path.write_text(new_env, encoding="utf-8")
    print("\n写入完成。下一步：")
    print("  1) 重启 heagent（配置在启动时读一次）")
    print("  2) 日志确认：ws event=started ... listener=external tls=wss")
    print(f"  3) 放行 Windows 防火墙入站端口（默认 9002），再从另一台设备连 wss://{host}:9002/api/runs/ws")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
