"""TLS 身份解析（纯 stdlib）：从 PEM/DER 证书取出 SubjectPublicKeyInfo、有效期与 SAN。

**为什么手写 ASN.1 而不引 ``cryptography``**：本仓核心依赖刻意保持 6 项，而这里只需要「读」——
证书是 DER 编码的 ``Certificate ::= SEQUENCE { tbsCertificate, ... }``，SPKI 在 tbs 里按固定顺序
出现。手写遍历足以取出**原始 TLV**（tag + 长度头 + 内容），因此算出的 SPKI-SHA256 与
``openssl pkey -pubin -outform der | openssl dgst -sha256`` 逐字节一致（判据见
``tests/test_tls_identity.py``）。

客户端 pin 的对象是**整张 SPKI 元素**，不是证书：叶证书重签（换有效期 / 换 SAN）时公钥不变 ⇒
pin 不变（ADR-004「安装期信任」）。因此本模块的公共面以 SPKI 为中心。

依赖纪律：本模块只依赖标准库与 pydantic（``network/`` 不得 import ``config/`` 与运行栈），材料
路径由调用方传入；解析失败一律抛 :class:`TlsIdentityError`（显性，不猜、不降级）。
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from heagent.network.exposure import unbracket_host

__all__ = [
    "TlsCertificateInfo",
    "TlsIdentityError",
    "cert_key_matches",
    "cert_not_after",
    "cert_not_before",
    "certificate_info",
    "key_spki_der",
    "load_cert_der",
    "san_covers",
    "san_entries",
    "short_fingerprint",
    "spki_der",
    "spki_sha256",
    "spki_sha256_base64",
    "spki_sha256_base64_of_der",
    "spki_sha256_of_der",
    "short_fingerprint_of_der",
]

# DER tag 常量（证书结构里出现的全部单字节 tag）。
_TAG_INTEGER = 0x02
_TAG_BIT_STRING = 0x03
_TAG_OCTET_STRING = 0x04
_TAG_OID = 0x06
_TAG_UTC_TIME = 0x17
_TAG_GENERALIZED_TIME = 0x18
_TAG_SEQUENCE = 0x30
_TAG_VERSION = 0xA0  # [0] EXPLICIT（v3 证书的 version 字段）
_TAG_EXTENSIONS = 0xA3  # [3] EXPLICIT（证书扩展）
_TAG_DNS_NAME = 0x82  # GeneralName ::= dNSName [2] IA5String
_TAG_IP_ADDRESS = 0x87  # GeneralName ::= iPAddress [7] OCTET STRING

# OID 2.5.29.17 = subjectAltName（只取内容字节，省一次 OID 编码）。
_OID_SUBJECT_ALT_NAME = bytes.fromhex("551d11")

# 短指纹的人读长度：base32 60 bit（10 字节摘要的前 12 个 base32 字符），按 4-4-4 分组。
# 它只用于「两台设备上念一遍核对」，安全判定仍用完整 SHA-256。
_SHORT_FINGERPRINT_CHARS = 12


class TlsIdentityError(ValueError):
    """TLS 材料不可读或结构不符（PEM 解不出 / DER 越界 / 非证书 / 非 RSA 私钥）。

    刻意留在本模块而不进 :mod:`heagent.pub.exceptions`：``network/`` 只依赖标准库与 pydantic，
    而这个错误只可能由「读材料」产生，CLI 侧按类型捕获转成人读消息即可，不需要错误码体系。
    消息里只出现**路径**与结构描述，绝不带私钥内容。
    """


class TlsCertificateInfo(BaseModel):
    """一张叶证书的身份事实（:func:`certificate_info` 的单次读取结果）。

    ``spki_sha256`` 是安全判定值（客户端 pin），``short_fingerprint`` 只供人眼核对，
    ``san`` / ``not_after`` 回答「这个地址连得上吗、还能用多久」。
    """

    model_config = ConfigDict(frozen=True)

    spki_sha256: str = Field(min_length=64, max_length=64)
    short_fingerprint: str = Field(min_length=14, max_length=14)
    not_before: datetime
    not_after: datetime
    san: tuple[str, ...] = ()


# ---------------------------------------------------------------- PEM / DER 读取


def _read_bytes(source: str | Path | bytes) -> bytes:
    """把「路径 / DER 字节」统一成字节。

    ``str`` 一律按**路径**解释（PEM 文本请传 ``bytes``）——避免把一段长文本误当文件名，也避免
    Windows 上传入超长字符串触发路径错误。
    """
    if isinstance(source, bytes):
        return source
    path = Path(source)
    try:
        return path.read_bytes()
    except OSError as exc:
        raise TlsIdentityError(f"无法读取 TLS 材料 {path}（{exc.strerror or exc}）") from exc


def _pem_body(data: bytes, label: str) -> bytes:
    """从 PEM 文本里取出指定 label 的 DER；找不到 / base64 坏掉都显性报错。"""
    begin = f"-----BEGIN {label}-----".encode()
    end = f"-----END {label}-----".encode()
    start = data.find(begin)
    if start < 0:
        raise TlsIdentityError(f"未找到 PEM 块 {label}（文件不是 PEM 或块名不符）")
    body_start = start + len(begin)
    body_end = data.find(end, body_start)
    if body_end < 0:
        raise TlsIdentityError(f"PEM 块 {label} 缺少结束标记（文件被截断）")
    try:
        return base64.b64decode(b"".join(data[body_start:body_end].split()), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise TlsIdentityError(f"PEM 块 {label} 的 base64 内容无法解码（{exc}）") from exc


def _to_der(source: str | Path | bytes, label: str) -> bytes:
    data = _read_bytes(source)
    if b"-----BEGIN" in data[:4096]:
        return _pem_body(data, label)
    return data


def load_cert_der(source: str | Path | bytes) -> bytes:
    """读取证书的 DER 字节（PEM 自动剥壳；已经是 DER 就原样返回）。"""
    der = _to_der(source, "CERTIFICATE")
    if not der:
        raise TlsIdentityError("证书内容为空")
    return der


# ---------------------------------------------------------------- 最小 ASN.1 遍历


class _Element:
    """一个 DER 元素在父缓冲区里的位置（``content_end`` 同时是元素结尾）。"""

    __slots__ = ("content_end", "content_start", "elem_start", "tag")

    def __init__(self, tag: int, elem_start: int, content_start: int, content_end: int) -> None:
        self.tag = tag
        self.elem_start = elem_start
        self.content_start = content_start
        self.content_end = content_end


def _decode_length(data: bytes, offset: int, end: int) -> tuple[int, int]:
    """解出长度字段，返回 ``(内容长度, 内容起点)``；长格式宽度按实际字节算（不写死 2 字节）。"""
    if offset >= end:
        raise TlsIdentityError("DER 长度字段缺失（数据被截断）")
    first = data[offset]
    if first < 0x80:  # noqa: PLR2004 - DER 短格式长度阈值
        return first, offset + 1
    count = first & 0x7F
    if count == 0:
        raise TlsIdentityError("DER 不定长编码不受支持（证书必须是定长 DER）")
    if count > 4:  # noqa: PLR2004 - 长度字段最多 4 字节（证书不会更大）
        raise TlsIdentityError(f"DER 长度字段过宽（{count} 字节），不是合法证书")
    if offset + 1 + count > end:
        raise TlsIdentityError("DER 长度字段越界（数据被截断）")
    return int.from_bytes(data[offset + 1 : offset + 1 + count], "big"), offset + 1 + count


def _children(data: bytes, start: int, end: int) -> list[_Element]:
    """把 ``[start, end)`` 切成同一层的 DER 元素；越界 / 多字节 tag 一律显性报错。"""
    elements: list[_Element] = []
    offset = start
    while offset < end:
        tag = data[offset]
        if tag & 0x1F == 0x1F:  # noqa: PLR2004 - 低位 5 位全 1 即多字节 tag
            raise TlsIdentityError("DER 多字节 tag 不受支持（TLS 材料里不应出现）")
        length, content_start = _decode_length(data, offset + 1, end)
        content_end = content_start + length
        if content_end > end:
            raise TlsIdentityError("DER 元素长度越界（不是完整的证书）")
        elements.append(_Element(tag, offset, content_start, content_end))
        offset = content_end
    return elements


def _single(data: bytes, element_range: tuple[int, int], expected_tag: int, what: str) -> _Element:
    """要求区间内**恰好一个**元素且 tag 匹配。"""
    elements = _children(data, *element_range)
    if len(elements) != 1 or elements[0].tag != expected_tag:
        raise TlsIdentityError(f"{what} 结构不符（期望 tag 0x{expected_tag:02x} 的单个元素）")
    return elements[0]


def _tbs_fields(der: bytes) -> list[_Element]:
    """返回 ``tbsCertificate`` 的直接子元素（已跳过可选的 ``[0] version``）。"""
    outer = _single(der, (0, len(der)), _TAG_SEQUENCE, "证书")
    top = _children(der, outer.content_start, outer.content_end)
    if not top or top[0].tag != _TAG_SEQUENCE:
        raise TlsIdentityError("证书结构不符（首个元素不是 tbsCertificate）")
    fields = _children(der, top[0].content_start, top[0].content_end)
    if fields and fields[0].tag == _TAG_VERSION:
        fields = fields[1:]
    if len(fields) < 7:  # noqa: PLR2004 - serial/sigAlg/issuer/validity/subject/spki + 至少一个扩展
        raise TlsIdentityError("证书结构不完整（tbsCertificate 字段不足）")
    return fields


# ---------------------------------------------------------------- SPKI 与指纹


def spki_der(cert: str | Path | bytes) -> bytes:
    """证书里 ``SubjectPublicKeyInfo`` 的**原始 TLV**（含 tag 与长度头），与 openssl 输出逐字节一致。"""
    der = load_cert_der(cert)
    return _spki_from(der, _tbs_fields(der))


def _spki_from(der: bytes, fields: list[_Element]) -> bytes:
    """从已解析的 ``tbsCertificate`` 字段表取 SPKI（:func:`certificate_info` 复用同一次解析）。"""
    field = fields[5]
    if field.tag != _TAG_SEQUENCE:
        raise TlsIdentityError("证书结构不符（SubjectPublicKeyInfo 不是 SEQUENCE）")
    return der[field.elem_start : field.content_end]


def spki_sha256_of_der(spki: bytes) -> str:
    """SPKI DER 的 SHA-256（小写 hex）——客户端 pin 的判定值。"""
    if not spki:
        raise TlsIdentityError("SPKI 内容为空")
    return hashlib.sha256(spki).hexdigest()


def spki_sha256(cert: str | Path | bytes) -> str:
    """证书对应 SPKI 的 SHA-256（小写 hex）。"""
    return spki_sha256_of_der(spki_der(cert))


def spki_sha256_base64_of_der(spki: bytes) -> str:
    """SPKI 摘要的 base64 形态（OkHttp ``CertificatePinner`` 的 ``sha256/<base64>`` 载荷）。"""
    return base64.b64encode(hashlib.sha256(spki).digest()).decode("ascii")


def spki_sha256_base64(cert: str | Path | bytes) -> str:
    """证书对应 SPKI 摘要的 base64 形态（OkHttp ``sha256/...`` 的载荷部分）。"""
    return spki_sha256_base64_of_der(spki_der(cert))


def short_fingerprint_of_der(spki: bytes) -> str:
    """人读短指纹：SHA-256 摘要前 10 字节的 base32 取前 12 字符，按 ``XXXX-XXXX-XXXX`` 分组。

    60 bit 足够「在两台设备上念一遍核对」，但**不是**安全边界——真正校验仍用完整
    :func:`spki_sha256`（客户端常量时间比较整段摘要）。
    """
    digest = hashlib.sha256(spki).digest()
    prefix = base64.b32encode(digest[:10]).decode("ascii")[:_SHORT_FINGERPRINT_CHARS]
    return "-".join(prefix[index : index + 4] for index in range(0, _SHORT_FINGERPRINT_CHARS, 4))


def short_fingerprint(cert: str | Path | bytes) -> str:
    """证书对应 SPKI 的短指纹（:func:`short_fingerprint_of_der` 的证书入口）。"""
    return short_fingerprint_of_der(spki_der(cert))


# ---------------------------------------------------------------- 有效期


def _parse_time(tag: int, raw: bytes, what: str) -> datetime:
    """``UTCTime`` / ``GeneralizedTime`` → 带时区的 ``datetime``（一律 UTC）。"""
    text = raw.decode("ascii", "replace")
    if not text.endswith("Z"):
        raise TlsIdentityError(f"{what} 不是以 Z 结尾的 UTC 时间（{text!r}）")
    digits = text[:-1]
    try:
        if tag == _TAG_UTC_TIME and len(digits) == 12:  # noqa: PLR2004 - YYMMDDHHMMSS
            year = int(digits[0:2])
            # RFC 5280：UTCTime 的两位年份以 1950 为界。
            year += 2000 if year < 50 else 1900  # noqa: PLR2004 - RFC 5280 的两位年份分界
            rest = digits[2:]
        elif tag == _TAG_GENERALIZED_TIME and len(digits) == 14:  # noqa: PLR2004 - YYYYMMDDHHMMSS
            year = int(digits[0:4])
            rest = digits[4:]
        else:
            raise TlsIdentityError(f"{what} 时间格式不受支持（{text!r}）")
        month, day, hour, minute, second = (int(rest[index : index + 2]) for index in range(0, 10, 2))
        return datetime(year, month, day, hour, minute, second, tzinfo=UTC)
    except (ValueError, IndexError) as exc:
        raise TlsIdentityError(f"{what} 时间无法解析（{text!r}）") from exc


def _validity_from(der: bytes, fields: list[_Element]) -> tuple[datetime, datetime]:
    """从已解析的字段表取 ``(notBefore, notAfter)``。"""
    field = fields[3]
    if field.tag != _TAG_SEQUENCE:
        raise TlsIdentityError("证书结构不符（validity 不是 SEQUENCE）")
    bounds = _children(der, field.content_start, field.content_end)
    if len(bounds) != 2:  # noqa: PLR2004 - validity = notBefore + notAfter
        raise TlsIdentityError("证书有效期字段不含两个时间值")
    return (
        _parse_time(bounds[0].tag, der[bounds[0].content_start : bounds[0].content_end], "notBefore"),
        _parse_time(bounds[1].tag, der[bounds[1].content_start : bounds[1].content_end], "notAfter"),
    )


def cert_not_after(cert: str | Path | bytes) -> datetime:
    """叶证书到期时刻（UTC）。"""
    der = load_cert_der(cert)
    return _validity_from(der, _tbs_fields(der))[1]


def cert_not_before(cert: str | Path | bytes) -> datetime:
    """叶证书生效时刻（UTC）。"""
    der = load_cert_der(cert)
    return _validity_from(der, _tbs_fields(der))[0]


# ---------------------------------------------------------------- SAN


def san_entries(cert: str | Path | bytes) -> list[str]:
    """证书的 SAN 项（``IP:`` / ``DNS:`` 前缀，保持 DER 顺序；无扩展返回空表）。"""
    der = load_cert_der(cert)
    return _san_from(der, _tbs_fields(der))


def _san_from(der: bytes, fields: list[_Element]) -> list[str]:
    """从已解析的字段表取 SAN 项（:func:`certificate_info` 复用同一次解析）。"""
    extension = next((field for field in fields if field.tag == _TAG_EXTENSIONS), None)
    if extension is None:
        return []
    # [3] EXPLICIT 里面先是一层 SEQUENCE OF Extension，逐个 Extension 才是 { OID, [critical], OCTET STRING }。
    extensions = _single(der, (extension.content_start, extension.content_end), _TAG_SEQUENCE, "Extensions")
    entries: list[str] = []
    for item in _children(der, extensions.content_start, extensions.content_end):
        if item.tag != _TAG_SEQUENCE:
            raise TlsIdentityError("证书扩展结构不符（Extensions 里出现非 SEQUENCE 元素）")
        parts = _children(der, item.content_start, item.content_end)
        if not parts or parts[0].tag != _TAG_OID:
            raise TlsIdentityError("证书扩展结构不符（缺少 OID）")
        if der[parts[0].content_start : parts[0].content_end] != _OID_SUBJECT_ALT_NAME:
            continue
        value = next((part for part in parts[1:] if part.tag == _TAG_OCTET_STRING), None)
        if value is None:
            raise TlsIdentityError("subjectAltName 扩展缺少 extnValue")
        names = _single(der, (value.content_start, value.content_end), _TAG_SEQUENCE, "subjectAltName")
        for name in _children(der, names.content_start, names.content_end):
            raw = der[name.content_start : name.content_end]
            if name.tag == _TAG_DNS_NAME:
                entries.append(f"DNS:{raw.decode('ascii', 'replace')}")
            elif name.tag == _TAG_IP_ADDRESS:
                if len(raw) not in (4, 16):
                    raise TlsIdentityError(f"iPAddress 长度不合法（{len(raw)} 字节）")
                entries.append(f"IP:{ipaddress.ip_address(raw)}")
    return entries


def san_covers(cert: str | Path | bytes, host: str) -> bool:
    """``host`` 是否被 SAN 覆盖：IP 字面量只比 IP 项，主机名只比 DNS 项（含单层 ``*.`` 通配）。

    ``host`` 允许 ``[::1]`` 这种带方括号的 IPv6 写法（与绑定地址同一口径，见
    :func:`heagent.network.exposure.unbracket_host`）——否则同一个地址在暴露判定里算 IP、
    在这里被当成主机名，结果是「证书明明覆盖了却报未覆盖」。
    """
    target = unbracket_host(host)
    entries = san_entries(cert)
    try:
        address = ipaddress.ip_address(target)
    except ValueError:
        address = None
    if address is not None:
        return f"IP:{address}" in entries
    normalized = target.lower().rstrip(".")
    for entry in entries:
        if not entry.startswith("DNS:"):
            continue
        pattern = entry[4:].lower().rstrip(".")
        if pattern == normalized:
            return True
        # 通配只覆盖**同一层**：``*.example.com`` 不匹配 ``a.b.example.com``（RFC 6125）。
        wildcard_hit = normalized.endswith(pattern[1:]) and normalized.count(".") == pattern.count(".")
        if pattern.startswith("*.") and wildcard_hit:
            return True
    return False


# ---------------------------------------------------------------- 身份密钥 ↔ 证书


def _der_length(length: int) -> bytes:
    if length < 0x80:  # noqa: PLR2004 - 同 DER 短格式阈值
        return bytes([length])
    raw = length.to_bytes((length.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(raw)]) + raw


def _tlv(tag: int, content: bytes) -> bytes:
    return bytes([tag]) + _der_length(len(content)) + content


def _integer_content(data: bytes, element: _Element) -> bytes:
    """取 INTEGER 的正值内容并规范化为最小 DER 编码（去冗余前导零、必要时补一位）。"""
    raw = data[element.content_start : element.content_end]
    if not raw:
        raise TlsIdentityError("私钥结构不符（INTEGER 为空）")
    value = int.from_bytes(raw, "big")
    if value == 0:
        return b"\x00"
    content = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return b"\x00" + content if content[0] & 0x80 else content


#: rsaEncryption 的 AlgorithmIdentifier（OID 1.2.840.113549.1.1.1 + NULL 参数）。
_RSA_ALGORITHM = bytes.fromhex("300d06092a864886f70d0101010500")


def _rsa_spki(der: bytes, pkcs1: _Element) -> bytes:
    parts = _children(der, pkcs1.content_start, pkcs1.content_end)
    if len(parts) < 3 or parts[1].tag != _TAG_INTEGER or parts[2].tag != _TAG_INTEGER:  # noqa: PLR2004
        raise TlsIdentityError("私钥结构不符（不是 PKCS#1 RSA 私钥）")
    modulus = _integer_content(der, parts[1])
    exponent = _integer_content(der, parts[2])
    public_key = _tlv(_TAG_SEQUENCE, _tlv(_TAG_INTEGER, modulus) + _tlv(_TAG_INTEGER, exponent))
    return _tlv(_TAG_SEQUENCE, _RSA_ALGORITHM + _tlv(_TAG_BIT_STRING, b"\x00" + public_key))


def key_spki_der(key: str | Path | bytes) -> bytes:
    """私钥（PKCS#1 ``RSA PRIVATE KEY`` 或 PKCS#8 ``PRIVATE KEY``）对应的 SPKI DER。

    只支持 RSA：本仓的身份密钥由 ``openssl genrsa`` 生成。EC 需要曲线运算，属另行引入依赖的
    范围，这里显性报错而不是猜。
    """
    data = _read_bytes(key)
    if b"-----BEGIN" in data[:4096]:
        # 先认 PKCS#1 的块名：``RSA PRIVATE KEY`` 里不含 ``PRIVATE KEY`` 子串匹配歧义（块名精确匹配）。
        label = "RSA PRIVATE KEY" if b"BEGIN RSA PRIVATE KEY" in data[:4096] else "PRIVATE KEY"
        der = _pem_body(data, label)
    else:
        der = data
    outer = _single(der, (0, len(der)), _TAG_SEQUENCE, "私钥")
    parts = _children(der, outer.content_start, outer.content_end)
    if len(parts) < 2:  # noqa: PLR2004 - version + algorithm/密钥本体
        raise TlsIdentityError("私钥结构不完整")
    if parts[1].tag == _TAG_SEQUENCE:
        # PKCS#8：AlgorithmIdentifier 之后是包着 PKCS#1 的 OCTET STRING。
        inner = next((part for part in parts[2:] if part.tag == _TAG_OCTET_STRING), None)
        if inner is None:
            raise TlsIdentityError("PKCS#8 私钥缺少 privateKey 字段")
        inner_range = (inner.content_start, inner.content_end)
        return _rsa_spki(der, _single(der, inner_range, _TAG_SEQUENCE, "PKCS#8 privateKey"))
    return _rsa_spki(der, outer)


def cert_key_matches(cert: str | Path | bytes, key: str | Path | bytes) -> bool:
    """证书里的公钥是否就是这把私钥对应的公钥。

    材料**读不出来**（PEM 坏、非 RSA）抛 :class:`TlsIdentityError`；读得出来但两者不是一对
    返回 ``False``——两种情形在启动自检里走不同分支（前者材料坏，后者配错文件）。
    """
    return spki_der(cert) == key_spki_der(key)


# ---------------------------------------------------------------- 汇总


def certificate_info(cert: str | Path | bytes) -> TlsCertificateInfo:
    """一次读取给出证书身份事实（SPKI 摘要、短指纹、有效期、SAN）——状态面与 CLI 共用这一个源。

    **只解析一次 DER**：状态端点会反复取这份事实，SPKI / 有效期 / SAN 三项各走一次公开函数
    等于同一棵树遍历三遍。
    """
    der = load_cert_der(cert)
    fields = _tbs_fields(der)
    spki = _spki_from(der, fields)
    not_before, not_after = _validity_from(der, fields)
    return TlsCertificateInfo(
        spki_sha256=spki_sha256_of_der(spki),
        short_fingerprint=short_fingerprint_of_der(spki),
        not_before=not_before,
        not_after=not_after,
        san=tuple(_san_from(der, fields)),
    )
