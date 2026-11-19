"""``network/tls_identity`` 的判据：SPKI 指纹与 openssl 逐字节一致、SAN / 有效期 / 密钥配对。

夹具 ``tests/fixtures/tls/`` 是一次性生成的固定材料（自签 CA + 10 年期叶证书），**没有任何
生产用途**：它们钉住「同一个公钥算出的 pin 恒定」这条安装期信任的地基。

为什么用固定夹具而不是测试期现签：pin 的判据本质是「与 openssl 输出逐字相同」，固定材料让
这条判据有一个跨机器、跨时间的常量对照；现签只在需要「重签换叶子不换公钥」时才用
（``test_cli_tls.py`` 里那批用例走真实 openssl）。
"""

from __future__ import annotations

import base64
import hashlib
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from heagent.network.tls_identity import (
    TlsIdentityError,
    cert_key_matches,
    cert_not_after,
    cert_not_before,
    certificate_info,
    key_spki_der,
    load_cert_der,
    san_covers,
    san_entries,
    short_fingerprint,
    spki_der,
    spki_sha256,
    spki_sha256_base64,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "tls"
CERT = FIXTURES / "cert.pem"
CA = FIXTURES / "ca.pem"
KEY_PKCS8 = FIXTURES / "key.pem"
KEY_PKCS1 = FIXTURES / "key-pkcs1.pem"
OTHER_KEY = FIXTURES / "other-key.pem"
NO_SAN_CERT = FIXTURES / "no-san-cert.pem"
CSR = FIXTURES / "not-a-cert.pem"

#: 固定夹具的 SPKI-SHA256（= openssl 对同一 SPKI 的 dgst 输出）。
EXPECTED_SHA256 = "d5af625c13e6bc95eac24f6c41f9e29c4ad06d97e48185bdeb80d635b95eacfb"
EXPECTED_SHORT = "2WXW-EXAT-426J"
EXPECTED_NOT_AFTER = datetime(2036, 11, 16, 13, 40, 49, tzinfo=UTC)


class TestSpkiFingerprint:
    def test_spki_is_the_raw_tlv_of_the_whole_element(self) -> None:
        """取的是**整个** SPKI 元素（含 tag 与长格式长度头），不是内容片段。"""
        der = spki_der(CERT)
        assert len(der) == 294, "RSA 2048 的 SPKI 共 294 字节"
        assert der[:4] == b"\x30\x82\x01\x22", "外层 SEQUENCE + 长格式长度头（0x82 两字节）必须原样保留"

    def test_sha256_matches_the_pinned_constant(self) -> None:
        assert spki_sha256(CERT) == EXPECTED_SHA256

    def test_sha256_matches_openssl_output(self) -> None:
        """与 ``openssl x509 -pubkey | openssl pkey -pubin -outform der | sha256`` 逐字节一致。"""
        openssl = shutil.which("openssl")
        if openssl is None:
            pytest.skip("本机没有 openssl，跳过交叉校验（固定常量用例仍覆盖同一判据）")
        public_pem = subprocess.run(  # noqa: S603 - 定值参数
            [openssl, "x509", "-in", str(CERT), "-pubkey", "-noout"],
            capture_output=True,
            check=True,
        ).stdout
        der = subprocess.run(  # noqa: S603 - 定值参数
            [openssl, "pkey", "-pubin", "-outform", "der"],
            input=public_pem,
            capture_output=True,
            check=True,
        ).stdout
        assert hashlib.sha256(der).hexdigest() == spki_sha256(CERT)

    def test_base64_form_is_the_okhttp_pin_payload(self) -> None:
        encoded = spki_sha256_base64(CERT)
        assert base64.b64decode(encoded).hex() == EXPECTED_SHA256

    def test_short_fingerprint_shape_and_stability(self) -> None:
        short = short_fingerprint(CERT)
        assert short == EXPECTED_SHORT
        assert re.fullmatch(r"[A-Z2-7]{4}-[A-Z2-7]{4}-[A-Z2-7]{4}", short)

    def test_der_bytes_are_accepted_like_a_path(self) -> None:
        assert spki_sha256(load_cert_der(CERT)) == EXPECTED_SHA256


class TestCertificateInfo:
    def test_single_read_agrees_with_the_specialised_helpers(self) -> None:
        info = certificate_info(CERT)
        assert info.spki_sha256 == spki_sha256(CERT)
        assert info.short_fingerprint == short_fingerprint(CERT)
        assert info.not_after == cert_not_after(CERT)
        assert info.san == tuple(san_entries(CERT))

    def test_validity_bounds_are_utc_datetimes(self) -> None:
        assert cert_not_after(CERT) == EXPECTED_NOT_AFTER
        assert cert_not_before(CERT) < cert_not_after(CERT)
        assert cert_not_before(CERT).tzinfo is UTC


class TestSan:
    def test_entries_follow_der_order_with_kind_prefix(self) -> None:
        assert san_entries(CERT) == [
            "IP:127.0.0.1",
            "IP:::1",
            "IP:192.168.2.226",
            "DNS:localhost",
            "DNS:heagent.local",
            "DNS:*.lab.local",
        ]

    @pytest.mark.parametrize(("host", "covered"), [("192.168.2.226", True), ("::1", True), ("127.0.0.1", True)])
    def test_ip_literals_hit_ip_entries(self, host: str, covered: bool) -> None:
        assert san_covers(CERT, host) is covered

    def test_address_drift_is_reported_as_not_covered(self) -> None:
        assert san_covers(CERT, "192.168.2.99") is False

    def test_hostnames_only_match_dns_entries(self) -> None:
        assert san_covers(CERT, "localhost") is True
        assert san_covers(CERT, "heagent.local") is True
        # IP 项不会匹配主机名形态的字符串，反之亦然。
        assert san_covers(CERT, "192.168.2.226.example") is False

    def test_wildcard_covers_one_label_only(self) -> None:
        assert san_covers(CERT, "app.lab.local") is True
        assert san_covers(CERT, "a.b.lab.local") is False

    def test_certificate_without_san_returns_empty_list(self) -> None:
        assert san_entries(NO_SAN_CERT) == []
        assert san_covers(NO_SAN_CERT, "localhost") is False


class TestKeyPairing:
    def test_pkcs8_and_pkcs1_forms_both_match_the_certificate(self) -> None:
        assert cert_key_matches(CERT, KEY_PKCS8) is True
        assert cert_key_matches(CERT, KEY_PKCS1) is True

    def test_both_forms_derive_the_same_spki(self) -> None:
        assert key_spki_der(KEY_PKCS8) == key_spki_der(KEY_PKCS1) == spki_der(CERT)

    def test_a_different_key_returns_false_not_an_exception(self) -> None:
        """配错文件是运维常犯的错：返回 False（启动自检据此拒绝启动），不是崩在解析上。"""
        assert cert_key_matches(CERT, OTHER_KEY) is False


class TestFailLoud:
    def test_non_pem_garbage_is_rejected_as_der(self) -> None:
        """不含 PEM 头的字节按 DER 解释（材料也可能直接是 DER），结构不成立即报错。"""
        assert load_cert_der(b"not a certificate at all") == b"not a certificate at all"
        with pytest.raises(TlsIdentityError, match="DER"):
            spki_sha256(b"not a certificate at all")

    def test_missing_file_message_carries_the_path(self, tmp_path: Path) -> None:
        missing = tmp_path / "absent.pem"
        with pytest.raises(TlsIdentityError, match="无法读取 TLS 材料") as excinfo:
            load_cert_der(missing)
        assert str(missing) in str(excinfo.value)

    def test_csr_is_not_a_certificate(self) -> None:
        with pytest.raises(TlsIdentityError):
            spki_sha256(CSR)

    def test_truncated_der_is_rejected(self) -> None:
        der = load_cert_der(CERT)
        with pytest.raises(TlsIdentityError):
            spki_sha256(der[: len(der) // 2])

    def test_private_key_error_never_leaks_key_material(self) -> None:
        """报错只说结构问题，不回显私钥正文（PEM 内容一律不进消息）。"""
        payload = "TUlJRXZRSUJBREFOQmdrcWhraUc5dzBCQVFFRkFBU0NCSzh3Z2dTckFnRUFBb0lCQVFE"
        with pytest.raises(TlsIdentityError) as excinfo:
            key_spki_der(f"-----BEGIN PRIVATE KEY-----\n{payload}\n-----END PRIVATE KEY-----\n".encode())
        assert payload[:20] not in str(excinfo.value)


class TestCaFixtureIsUsableAsTrustAnchor:
    """夹具 CA 必须真的能验证夹具叶证书——73.2/73.6 的「叶由本 CA 签发」判据复用同一对材料。"""

    def test_openssl_verify_accepts_the_leaf(self) -> None:
        openssl = shutil.which("openssl")
        if openssl is None:
            pytest.skip("本机没有 openssl")
        completed = subprocess.run(  # noqa: S603 - 定值参数
            [openssl, "verify", "-CAfile", str(CA), str(CERT)],
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr
