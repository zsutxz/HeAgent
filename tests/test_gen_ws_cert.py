"""``scripts/gen_ws_cert.py`` 的 SAN 处理与真实签发判据。

脚本不是包（``scripts/`` 无 ``__init__.py``），按路径 importlib 加载，不做 sys.path 注入。
真签发那几条用例依赖 ``openssl`` 可执行文件；本机没有时 skip（而不是把断言删掉）。
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "gen_ws_cert.py"
_SPEC = importlib.util.spec_from_file_location("gen_ws_cert_under_test", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
gen = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gen)


def _openssl() -> str:
    try:
        return gen.find_openssl(None)
    except gen.CertError:  # pragma: no cover - 只在没有 openssl 的环境触发
        pytest.skip("本机没有 openssl，跳过真签发用例")


def _run(binary: str, args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run([binary, *args], cwd=str(cwd), capture_output=True, text=True, check=False)  # noqa: S603


def _read(binary: str, cwd: Path, *args: str) -> str:
    completed = _run(binary, list(args), cwd)
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


# ---------------------------------------------------------------- SAN 规范化


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("192.168.1.23", "IP:192.168.1.23"),
        ("::1", "IP:::1"),
        ("IP:127.0.0.1", "IP:127.0.0.1"),
        ("ip:10.0.2.2", "IP:10.0.2.2"),
        ("heagent.lan", "DNS:heagent.lan"),
        ("DNS:heagent.local", "DNS:heagent.local"),
        ("  localhost  ", "DNS:localhost"),
    ],
)
def test_normalize_san_accepts_ip_and_hostname(raw: str, expected: str) -> None:
    assert gen.normalize_san(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "IP:", "192.168.1.999", "heagent/ws", "-oops", "a b"])
def test_normalize_san_rejects_garbage_loudly(raw: str) -> None:
    with pytest.raises(gen.CertError):
        gen.normalize_san(raw)


def test_collect_san_entries_dedupes_and_keeps_order() -> None:
    entries = gen.collect_san_entries(
        ["192.168.1.23", "IP:127.0.0.1", "localhost", "heagent.lan"],
        include_lan=False,
    )
    assert entries[:4] == ["IP:127.0.0.1", f"IP:{gen.IPV6_LOOPBACK}", "DNS:localhost", "DNS:heagent.local"]
    # 重复项（127.0.0.1 / localhost）只保留第一次出现的形态
    assert entries.count("IP:127.0.0.1") == 1
    assert entries.count("DNS:localhost") == 1
    assert entries[-1] == "DNS:heagent.lan"
    assert "IP:192.168.1.23" in entries


def test_default_san_covers_the_common_vm_to_host_gateways() -> None:
    """VM 场景的两条默认通路：VirtualBox/QEMU NAT 与 libvirt NAT。"""
    assert "IP:10.0.2.2" in gen.DEFAULT_SAN
    assert "IP:192.168.122.1" in gen.DEFAULT_SAN
    assert "IP:127.0.0.1" in gen.DEFAULT_SAN


# ---------------------------------------------------------------- 配置渲染


def test_rendered_config_carries_every_san_and_the_server_auth_purpose() -> None:
    entries = ["IP:127.0.0.1", "IP:::1", "DNS:localhost", "IP:192.168.1.23"]
    config = gen.render_leaf_config(entries)
    assert "basicConstraints = critical, CA:FALSE" in config
    assert "extendedKeyUsage = serverAuth" in config
    assert "subjectAltName = @alt_names" in config
    body = config.split("[ alt_names ]", 1)[1]
    for entry in entries:
        value = entry[4:] if entry.startswith("DNS:") else entry[3:]
        assert value in body
    # IP 与 DNS 各自从 1 开始编号（混编会在配置里留编号空洞）
    assert "IP.1 = 127.0.0.1" in body
    assert "IP.2 = ::1" in body
    assert "IP.3 = 192.168.1.23" in body
    assert "DNS.1 = localhost" in body


def test_client_trust_hint_hides_loopback_addresses(tmp_path: Path) -> None:
    """回环地址不是「客户端可连的地址」——列表里出现它只会误导。"""
    hint = gen.client_trust_hint(tmp_path, ["IP:127.0.0.1", "IP:::1", "IP:10.0.2.2", "DNS:localhost"])
    assert "10.0.2.2" in hint
    listed = hint.split("客户端可连的地址：", 1)[1]
    assert "127.0.0.1" not in listed
    assert "::1" not in listed


def test_rendered_config_marks_itself_as_generated() -> None:
    assert gen.render_leaf_config(["IP:127.0.0.1"]).startswith("# 由 scripts/gen_ws_cert.py 生成")


# ---------------------------------------------------------------- 计划模式 / 前提失败


def test_dry_run_writes_nothing(tmp_path: Path) -> None:
    out_dir = tmp_path / "tls"
    rc = gen.main(["--out-dir", str(out_dir), "--no-lan", "--san", "192.168.1.23"])
    assert rc == 0
    assert not out_dir.exists(), "缺省（无 --apply）不得落盘"


def test_missing_openssl_fails_loudly_before_writing(tmp_path: Path) -> None:
    out_dir = tmp_path / "tls"
    rc = gen.main(["--out-dir", str(out_dir), "--openssl", str(tmp_path / "nope.exe"), "--apply"])
    assert rc == 2
    assert not out_dir.exists()


def test_non_positive_days_are_rejected(tmp_path: Path) -> None:
    assert gen.main(["--out-dir", str(tmp_path / "tls"), "--days", "0"]) == 2
    assert gen.main(["--out-dir", str(tmp_path / "tls"), "--ca-days", "0"]) == 2


# ---------------------------------------------------------------- 真签发


def test_apply_issues_a_chain_that_verifies_and_honours_days(tmp_path: Path) -> None:
    binary = _openssl()
    out_dir = tmp_path / "tls"
    rc = gen.main(
        ["--out-dir", str(out_dir), "--openssl", binary, "--no-lan", "--san", "192.168.1.23", "--days", "30", "--apply"]
    )
    assert rc == 0
    for name in ("ca.pem", "ca.key", "ca.srl", "cert.pem", "key.pem", "cert-chain.pem", "openssl-leaf.cnf"):
        assert (out_dir / name).is_file(), name

    assert _run(binary, ["verify", "-CAfile", "ca.pem", "cert.pem"], out_dir).returncode == 0
    san = _read(binary, out_dir, "x509", "-in", "cert.pem", "-noout", "-ext", "subjectAltName")
    assert "IP Address:192.168.1.23" in san
    assert "DNS:localhost" in san

    # 有效期：29 天后仍有效、31 天后已过期（不解析日期字符串，交给 openssl 自己判）
    assert _run(binary, ["x509", "-in", "cert.pem", "-noout", "-checkend", str(29 * 86400)], out_dir).returncode == 0
    assert _run(binary, ["x509", "-in", "cert.pem", "-noout", "-checkend", str(31 * 86400)], out_dir).returncode != 0

    # 链文件 = 叶 + CA
    chain = (out_dir / "cert-chain.pem").read_text(encoding="utf-8")
    assert chain.count("BEGIN CERTIFICATE") == 2
    assert (out_dir / "cert.pem").read_text(encoding="utf-8").strip() in chain
    assert (out_dir / "ca.pem").read_text(encoding="utf-8").strip() in chain


def test_rotation_keeps_the_ca_so_clients_need_no_reimport(tmp_path: Path) -> None:
    binary = _openssl()
    out_dir = tmp_path / "tls"
    args = ["--out-dir", str(out_dir), "--openssl", binary, "--no-lan", "--apply"]
    assert gen.main(args) == 0
    first_ca = _read(binary, out_dir, "x509", "-in", "ca.pem", "-noout", "-fingerprint", "-sha256")
    first_serial = _read(binary, out_dir, "x509", "-in", "cert.pem", "-noout", "-serial")

    assert gen.main(args) == 0
    second_ca = _read(binary, out_dir, "x509", "-in", "ca.pem", "-noout", "-fingerprint", "-sha256")
    second_serial = _read(binary, out_dir, "x509", "-in", "cert.pem", "-noout", "-serial")

    assert first_ca == second_ca, "轮换不得动 CA（否则客户端要重新导入信任）"
    assert first_serial != second_serial, "叶证书必须真的重签"
    assert _run(binary, ["verify", "-CAfile", "ca.pem", "cert.pem"], out_dir).returncode == 0
    # 旧材料整份留底
    backups = list(out_dir.glob("backup-*"))
    assert len(backups) == 1
    assert (backups[0] / "cert.pem").is_file()


def test_new_ca_actually_replaces_the_ca(tmp_path: Path) -> None:
    binary = _openssl()
    out_dir = tmp_path / "tls"
    assert gen.main(["--out-dir", str(out_dir), "--openssl", binary, "--no-lan", "--apply"]) == 0
    first_ca = _read(binary, out_dir, "x509", "-in", "ca.pem", "-noout", "-fingerprint", "-sha256")

    assert gen.main(["--out-dir", str(out_dir), "--openssl", binary, "--no-lan", "--new-ca", "--apply"]) == 0
    second_ca = _read(binary, out_dir, "x509", "-in", "ca.pem", "-noout", "-fingerprint", "-sha256")
    assert first_ca != second_ca
    assert _run(binary, ["verify", "-CAfile", "ca.pem", "cert.pem"], out_dir).returncode == 0


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="Windows 的 stat() 恒返回 0o666 类权限位（NTFS 走 ACL），POSIX 权限位断言在本平台不可检验",
)
def test_ca_key_is_not_world_readable(tmp_path: Path) -> None:
    binary = _openssl()
    out_dir = tmp_path / "tls"
    assert gen.main(["--out-dir", str(out_dir), "--openssl", binary, "--no-lan", "--apply"]) == 0
    for name in ("ca.key", "key.pem"):
        assert (out_dir / name).stat().st_mode & 0o077 == 0, name
