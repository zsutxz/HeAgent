"""`.env` / `setting.md` 行级扫描：只产诊断，永不参与取值。

自 ``heagent.config.catalog`` 单文件拆出（E3 绞杀者），行为零改动。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NamedTuple

from heagent.config.envfile import fingerprint, iter_env_lines
from heagent.pub.frontmatter import FrontmatterSyntaxError, parse_strict_pairs, split_frontmatter

from .models import BOM, EnvScan, LayerMap

_INLINE_COMMENT_RE = re.compile(r"\s#")


# ── 行级扫描（只产诊断，绝不产值）──


def _looks_blank(raw_value: str) -> bool:
    """行内原始值是否**看起来**为空（启发式；权威判据是该键缺席于来源层）。

    引号包裹的值一律算「有值」，避免 ``KEY=" # "`` 被误判成空值。
    """
    value = raw_value.strip()
    if not value or value.startswith("#"):
        return True
    if len(value) > 2 and value[0] in "\"'" and value.endswith(value[0]):
        return False
    head = value.split("#", 1)[0] if _INLINE_COMMENT_RE.search(value) else value
    return head.strip() == ""


class _ScanRead(NamedTuple):
    """诊断源文件的读入结果（``_scan_file_common`` 的产物）。"""

    raw: bytes
    text: str
    encoding_ok: bool


def _scan_file_common(file_path: Path) -> _ScanRead | None:
    """两个扫描器的共享读入前奏：字节 + ``errors="replace"`` 兜底解码 + UTF-8 完好性。

    读失败返回 ``None``（存在性判断与占位模型回报由调用方以其各自的类型做）。
    """
    try:
        raw = file_path.read_bytes()
    except OSError:
        return None
    try:
        raw.decode("utf-8")
        encoding_ok = True
    except UnicodeDecodeError:
        encoding_ok = False
    return _ScanRead(raw, raw.decode("utf-8", errors="replace"), encoding_ok)


def scan_env_file(path: str | Path | None) -> EnvScan:
    """读 ``.env`` 的**行级诊断**（重复键 / 空值行 / 行内注释 / 键的原写法）。

    刻意**不**解析值语义（那是 ``pydantic_settings`` 的职责）：这里的输出只用于给条目挂
    ``notes``。非 UTF-8 文件用 ``errors="replace"`` 兜底（fail-soft，与 Z-D12 同立场）。
    文件头 BOM 在这里同样被剥掉——口径与 :class:`_BomTolerantDotEnvSource` 一致（只剥头部）。
    """
    if path is None:
        return EnvScan()
    file_path = Path(path)
    scanned = _scan_file_common(file_path)
    if scanned is None:
        return EnvScan(path=str(file_path), exists=file_path.exists(), readable=False)
    raw, text, encoding_ok = scanned
    # 非 UTF-8（编码坏了）：值求解会整体降级，行级诊断也只能 best-effort——键名可能被替换字符
    # 污染，因此**不用它**判定「未知键」（否则会报出乱码键名）。
    has_bom = text.startswith(BOM)
    if has_bom:
        text = text[len(BOM) :]

    # ``splitlines()``：0 字节文件算 0 行、末行换行不额外算一行（按 ``split("\n")`` 段数计
    # 会让 0 字节 .env 谎报 1 行）。行解析内核与 envfile 共享（键名/
    # export 口径不漂移），但行切分刻意不同：诊断侧归一化 CRLF，保真侧逐字节。
    lines = text.replace("\r\n", "\n").splitlines()
    counts: dict[str, int] = {}
    names: dict[str, str] = {}
    blanks: set[str] = set()
    commented: set[str] = set()
    for _, name, raw_value in iter_env_lines(lines):
        if not name:
            continue
        lower = name.lower()
        counts[lower] = counts.get(lower, 0) + 1
        names.setdefault(lower, name)
        if _looks_blank(raw_value):
            blanks.add(lower)
        if _INLINE_COMMENT_RE.search(raw_value):
            commented.add(lower)

    return EnvScan(
        path=str(file_path),
        exists=True,
        readable=True,
        encoding_ok=encoding_ok,
        has_bom=has_bom,
        fingerprint=fingerprint(raw),
        line_count=len(lines),
        declared_keys=tuple(names.values()),
        name_by_lower=names,
        duplicate_keys=tuple(names[key] for key in names if counts[key] > 1),
        blank_keys=tuple(names[key] for key in names if key in blanks),
        inline_comment_keys=tuple(names[key] for key in names if key in commented),
    )


class SettingMdScan(EnvScan):
    """用户层 ``setting.md`` 的诊断结果；严格解析下「整文件对或整文件错」，故无逐键结构诊断。"""

    parse_error: str | None = None


def scan_setting_md(path: str | Path | None) -> SettingMdScan:
    """读用户层 ``setting.md`` 的诊断：声明键（原写法）、指纹、行数、语法错摘要。

    刻意与 :func:`read_setting_md`（取值路径）分开走文件：诊断必须独立于取值——取值失败
    （语法错）时这里仍能报告「文件存在、有这些声明键、错在第几行」。
    """
    if path is None:
        return SettingMdScan()
    file_path = Path(path)
    scanned = _scan_file_common(file_path)
    if scanned is None:
        return SettingMdScan(path=str(file_path), exists=file_path.exists(), readable=False)
    raw, text, encoding_ok = scanned
    # 编码坏了：frontmatter 解析只能 best-effort，键名可能被替换字符污染——不做解析诊断。
    lines = text.replace("\r\n", "\n").splitlines()
    names: dict[str, str] = {}
    parse_error: str | None = None
    if encoding_ok:
        split = split_frontmatter(text)
        if split is None:
            if text.strip():
                parse_error = f"{file_path}: 缺少 YAML frontmatter 头（首行须为 ``---``）"
        else:
            try:
                pairs = parse_strict_pairs(split[0])
            except FrontmatterSyntaxError as exc:
                parse_error = f"{file_path}: 第 {exc.line_number} 行无法解析（{exc.kind}）：{exc.line!r}"
            else:
                names = {key.lower(): key for key in pairs}
    return SettingMdScan(
        path=str(file_path),
        exists=True,
        readable=True,
        encoding_ok=encoding_ok,
        has_bom=text.startswith(BOM),
        fingerprint=fingerprint(raw),
        line_count=len(lines),
        declared_keys=tuple(names.values()),
        name_by_lower=names,
        parse_error=parse_error,
    )


def bom_prefixed_keys(layers: LayerMap) -> tuple[str, ...]:
    """所有层里**带 BOM 前缀**的键（T9b②：这些键不生效，必须显式标注而不是静默落 ``default``）。

    留作**绊线**：文件头 BOM 已由 :class:`_BomTolerantDotEnvSource` 剥掉，所以正常输入下这里是空的；
    一旦某个来源（或文件中部）漏出 ``'\\ufeffxxx'`` 形式的键名，面板就会点名它。
    """
    return tuple(sorted({key for keys in layers.values() for key in keys if key.startswith(BOM)}))
