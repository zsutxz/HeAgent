"""``heagent tls`` 命令族的判据：五个动词各有正/负用例（真实 openssl，缺则 skip）。

判据的重点不是「命令跑通」，而是**安装期信任的契约**：

- ``issue`` 复用身份密钥 ⇒ pin 不变（客户端不因 30 天轮换重装）；
- ``rotate-key`` 是唯一改变 pin 的动作，且必须显式 ``--yes``；
- ``fingerprint`` 三种格式的哈希逐字一致；
- ``verify`` 逐条列出失败项，不抛 traceback。
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from heagent.cli.tls_cmd import tls_cmd
from heagent.network.tls_identity import (
    cert_key_matches,
    key_spki_der,
    san_entries,
    spki_sha256,
    spki_sha256_base64,
    spki_sha256_of_der,
)


def _openssl() -> str:
    found = shutil.which("openssl")
    if found is None:  # pragma: no cover - 只在没有 openssl 的环境触发
        pytest.skip("本机没有 openssl，跳过签发类用例")
    return found


@pytest.fixture()
def materials(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """隔离的材料目录；``WS_HOST`` 推导打桩成 None（不让仓库 .env 影响断言）。"""
    monkeypatch.setattr("heagent.cli.tls_cmd._ws_host", lambda: None)
    return tmp_path / "tls"


def _run(materials: Path, *args: str) -> Result:
    openssl = _openssl()
    return CliRunner().invoke(tls_cmd, ["--dir", str(materials), "--openssl", openssl, *args])


def _init(materials: Path, *extra: str) -> Result:
    return _run(materials, "init", "--no-lan", *extra)


class TestHelp:
    @pytest.mark.parametrize("subcommand", ["init", "issue", "rotate-key", "fingerprint", "verify"])
    def test_every_subcommand_has_help(self, subcommand: str) -> None:
        result = CliRunner().invoke(tls_cmd, [subcommand, "--help"])
        assert result.exit_code == 0, result.output
        assert "--help" in result.output

    def test_group_is_registered_on_the_cli(self) -> None:
        """``heagent --help`` 的子命令列表必须含 ``tls``（注册漏了就没法签材料）。"""
        from heagent.cli.console import main  # noqa: PLC0415 - 只想看注册表，不跑其它命令

        assert "tls" in main.commands


class TestInit:
    def test_fresh_directory_gets_ca_and_identity_key(self, materials: Path) -> None:
        result = _init(materials)
        assert result.exit_code == 0, result.output
        for name in ("ca.pem", "ca.key", "identity.key", "key.pem", "openssl-leaf.cnf"):
            assert (materials / name).is_file(), name
        assert not (materials / "cert.pem").exists(), "init 只建身份材料，叶证书交给 issue"
        assert "sha256/" in result.output
        assert "pin" in result.output

    def test_existing_materials_are_not_touched_without_force(self, materials: Path) -> None:
        assert _init(materials).exit_code == 0
        before = {name: (materials / name).read_bytes() for name in ("ca.pem", "ca.key", "identity.key")}
        result = _init(materials)
        assert result.exit_code != 0
        assert "--force" in result.output
        for name, payload in before.items():
            assert (materials / name).read_bytes() == payload, f"{name} 被改动了"

    def test_force_backs_up_then_rebuilds(self, materials: Path) -> None:
        assert _init(materials).exit_code == 0
        old_ca = (materials / "ca.pem").read_bytes()
        result = _init(materials, "--force")
        assert result.exit_code == 0, result.output
        assert (materials / "ca.pem").read_bytes() != old_ca
        backups = list(materials.glob("backup-*"))
        assert len(backups) == 1
        assert (backups[0] / "ca.pem").read_bytes() == old_ca


class TestIssue:
    def test_leaf_reuses_the_identity_key_so_the_pin_is_stable(self, materials: Path) -> None:
        assert _init(materials).exit_code == 0
        assert _run(materials, "issue", "--no-lan").exit_code == 0
        first = spki_sha256(materials / "cert.pem")
        assert first == spki_sha256_of_der(key_spki_der(materials / "identity.key"))

        result = _run(materials, "issue", "--no-lan", "--days", "45")
        assert result.exit_code == 0, result.output
        assert spki_sha256(materials / "cert.pem") == first, "重签不得改 pin"
        assert cert_key_matches(materials / "cert.pem", materials / "key.pem") is True

    def test_extra_san_is_added_and_previous_entries_survive(self, materials: Path) -> None:
        assert _init(materials).exit_code == 0
        assert _run(materials, "issue", "--no-lan").exit_code == 0
        before = san_entries(materials / "cert.pem")
        assert _run(materials, "issue", "--no-lan", "--san", "10.1.2.3").exit_code == 0
        after = san_entries(materials / "cert.pem")
        assert "IP:10.1.2.3" in after
        assert set(before) <= set(after), "换网段重签不得把旧 SAN 悄悄删掉"

    def test_issue_before_init_fails_loudly(self, materials: Path) -> None:
        result = _run(materials, "issue", "--no-lan")
        assert result.exit_code != 0
        assert "heagent tls init" in result.output

    def test_ws_host_is_derived_into_the_san(self, materials: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("heagent.cli.tls_cmd._ws_host", lambda: "192.168.7.7")
        assert _init(materials).exit_code == 0
        assert _run(materials, "issue", "--no-lan").exit_code == 0
        assert "IP:192.168.7.7" in san_entries(materials / "cert.pem")

    def test_non_positive_days_are_rejected(self, materials: Path) -> None:
        assert _init(materials).exit_code == 0
        result = _run(materials, "issue", "--no-lan", "--days", "0")
        assert result.exit_code == 1
        assert "正整数" in result.output


class TestRotateKey:
    def test_rotates_the_pin_and_prints_both_fingerprints(self, materials: Path) -> None:
        assert _init(materials).exit_code == 0
        assert _run(materials, "issue", "--no-lan").exit_code == 0
        old_pin = spki_sha256(materials / "cert.pem")

        result = _run(materials, "rotate-key", "--no-lan", "--yes")
        assert result.exit_code == 0, result.output
        new_pin = spki_sha256(materials / "cert.pem")
        assert new_pin != old_pin
        assert "旧 pin" in result.output and "新 pin" in result.output
        assert "双 pin 过渡" in result.output
        assert "重发安装包" in result.output
        assert cert_key_matches(materials / "cert.pem", materials / "identity.key") is True

    def test_without_yes_it_refuses_and_changes_nothing(self, materials: Path) -> None:
        assert _init(materials).exit_code == 0
        assert _run(materials, "issue", "--no-lan").exit_code == 0
        identity_before = (materials / "identity.key").read_bytes()
        pin_before = spki_sha256(materials / "cert.pem")

        result = _run(materials, "rotate-key", "--no-lan")
        assert result.exit_code != 0
        assert "--yes" in result.output
        assert (materials / "identity.key").read_bytes() == identity_before
        assert spki_sha256(materials / "cert.pem") == pin_before


class TestFingerprint:
    def test_three_formats_carry_the_same_hash(self, materials: Path) -> None:
        assert _init(materials).exit_code == 0
        assert _run(materials, "issue", "--no-lan").exit_code == 0

        text = _run(materials, "fingerprint")
        as_json = _run(materials, "fingerprint", "--format", "json")
        as_pin = _run(materials, "fingerprint", "--format", "pin")
        assert text.exit_code == as_json.exit_code == as_pin.exit_code == 0

        payload = json.loads(as_json.output)
        assert payload["spki_sha256"] in text.output
        assert payload["pin"] == as_pin.output.strip()
        assert payload["pin"] == f"sha256/{spki_sha256_base64(materials / 'cert.pem')}"
        assert len(payload["short_fingerprint"]) == 14  # XXXX-XXXX-XXXX
        assert payload["san"]

    def test_unknown_format_exits_with_usage_error(self, materials: Path) -> None:
        assert _init(materials).exit_code == 0
        result = _run(materials, "fingerprint", "--format", "yaml")
        assert result.exit_code == 2

    def test_fingerprint_before_issue_names_the_next_command(self, materials: Path) -> None:
        assert _init(materials).exit_code == 0
        result = _run(materials, "fingerprint")
        assert result.exit_code != 0
        assert "heagent tls issue" in result.output


class TestVerify:
    def test_healthy_materials_pass_every_check(self, materials: Path) -> None:
        assert _init(materials).exit_code == 0
        assert _run(materials, "issue", "--no-lan").exit_code == 0
        result = _run(materials, "verify")
        assert result.exit_code == 0, result.output
        assert result.output.count("[OK]") == 3
        assert "FAIL" not in result.output

    def test_mismatched_identity_key_is_reported_per_check(self, materials: Path) -> None:
        assert _init(materials).exit_code == 0
        assert _run(materials, "issue", "--no-lan").exit_code == 0
        # 用另一把密钥顶替身份密钥：证书不再是它的公钥（模拟「配错文件」）
        stranger = Path(__file__).resolve().parent / "fixtures" / "tls" / "other-key.pem"
        (materials / "identity.key").write_bytes(stranger.read_bytes())

        result = _run(materials, "verify")
        assert result.exit_code == 1
        assert result.output.count("[FAIL]") == 1
        assert "公钥不一致" in result.output
        assert "Traceback" not in result.output


class TestNoOpenSSL:
    def test_missing_openssl_points_at_the_container_workaround(
        self, materials: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(shutil, "which", lambda *_args, **_kwargs: None)
        result = CliRunner().invoke(tls_cmd, ["--dir", str(materials), "init", "--no-lan"])
        assert result.exit_code != 0
        assert "openssl" in result.output
        assert "容器" in result.output
