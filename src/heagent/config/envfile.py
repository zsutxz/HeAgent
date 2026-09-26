"""``.env`` 的**行级保真**读写：定位键、替换/追加、指纹、备份（Story 50-5 / 脊柱 I7-I8）。

本模块是**顶层**模块——只依赖标准库、Pydantic 与 :mod:`heagent.pub.persist`；不得依赖
``config`` / ``config_catalog`` / ``engine`` / ``agent`` / 入口层（写入流水线
:mod:`heagent.config.write` 才认识白名单与设置）。

为什么必须自己做行级改写，而不是用 ``python-dotenv`` 的 ``set_key`` 或「整文件重写」：

1. **保真**（I7）：只替换目标行；其余行的**字节**、行尾（CRLF/LF）、文件头 BOM、注释、空行一律不变。
   整文件重写必然做行尾归一化与注释丢弃，而这正是 `.env` 里最容易出错的三处（实测真实项目
   ``.env``：77 行全 CRLF、10 处行内注释、1 个重复键）。
2. **确定性**：改写是纯字符串变换，可以逐字节断言；``set_key`` 的行为随版本变化，且会重排/重写
   整个文件。
3. **可审计**：替换前先算出旧值（哈希 + 长度）以便落审计（I9：审计不含值本身）。

四条硬约束（违反即偏离 story 边界）：

- **只认最后一个重复键**：真实 `.env` 里同键出现多次时后者生效（脊柱 §7 坑 5），因此替换必须命中
  **最后一行**，否则写进去的是「当下无效、日后生效」的死值。
- **文件头 BOM 剥离后再取键名**（评审 F6）：不剥离就会把首行键读成 ``'\\ufeffMAX_ITERATIONS'``
  ⇒ 找不到目标行 ⇒ 追加一条永不生效的死行；改写首行时 BOM 必须原样留在文件头。
- **值不可安全表达就拒绝**（``EnvWriteError``，fail-closed）：行尾/控制字符、首尾空白、会被当作
  行内注释截断的 ``" #"`` 一律拒（否则「客户端写的值」与「解析出的值」不一致）。
- **键名不得含分隔符**：``=`` / 空白 / 控制字符一律拒（否则会写出结构性坏行）。

文本以 ``str`` 进出（便于逐字节断言），落盘一律经 :mod:`heagent.pub.persist` 的**字节级**原语——
文本模式的行尾翻译（``\\n`` ↔ ``os.linesep``）会让「未修改行字节不变」在跨平台上不可能成立。
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from heagent.pub.persist import atomic_write_bytes, delete_entries, scan_dir

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

# ── 常量 ──

#: UTF-8 BOM 的字符形式（``BOM_BYTES == b"\xef\xbb\xbf"``）。
BOM = "\ufeff"
BOM_BYTES = BOM.encode("utf-8")

#: **新建 / 空**文件的追加行尾：LF（仓库 `.gitattributes` 为 ``* text=auto eol=lf``，仓库内产物一律 LF）。
#: 既有文件的追加行**跟随该文件自身的行尾风格**（见 :func:`replace_or_append`）。
DEFAULT_EOL = "\n"

#: 备份文件名后缀 / 前缀 + 条目数与保留期上限（写入通道的硬边界，见 :func:`prune_backups`）。
BACKUP_SUFFIX = ".bak"
MAX_CONFIG_BACKUPS = 50
CONFIG_BACKUP_RETENTION_DAYS = 30

#: 键与值的长度上界（``network.http_console_protocol`` 的同名常量镜像这两个值，由测试钉住）。
MAX_KEY_CHARS = 64
MAX_VALUE_CHARS = 8192

#: 行内注释的起点：**空白 + ``#``**（``KEY=v  # c``）。与 ``config_catalog`` 的诊断口径一致。
#: 实测 dotenv 的解析规则（探针 ``env_parse_probe``）：``KEY=#x`` 的 ``#`` **不是**注释（前面没有空白），
#: ``KEY=x#y # z`` 取 ``x#y``，``KEY=x\t# c`` 取 ``x``——所以判据是「空白紧邻 ``#``」，且注释覆盖
#: 到整行结束（值前的空白一并丢掉）。
_INLINE_COMMENT_RE = re.compile(r"\s+#")

#: 合法的 env 键写法（``[A-Za-z_][A-Za-z0-9_]*``）。
_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: 值里绝对不允许出现的字符：行尾会伪造新行、NUL 会截断、BOM 会污染后续解析。
_FORBIDDEN_VALUE_CHARS = ("\r", "\n", "\x00", BOM)

_QUOTES = ("'", '"')


class EnvWriteError(ValueError):
    """值 / 键无法在 ``.env`` 中**安全表达**（fail-closed：宁可拒绝，也不写出会被解析成别的值的内容）。

    ``reason`` 是稳定码（``control_characters`` / ``whitespace`` / ``inline_comment`` /
    ``invalid_key`` / ``too_long``），写入流水线把它映射成 ``invalid_value`` 的字段级原因。
    """

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


class EnvFileIndex(BaseModel):
    """``.env`` 的**行级索引**（只描述「文件里写了什么」，不含任何「有效值」语义）。

    ``line_by_key`` 记同键**最后一行**的行号（0 基，含注释/空行的完整行序），这是替换的落点。
    ``eol`` 是追加行使用的行尾风格；``trailing_newline`` 决定追加时是否需要先补一个行尾。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    has_bom: bool = False
    eol: str = DEFAULT_EOL
    trailing_newline: bool = False
    line_count: int = 0
    keys: tuple[str, ...] = ()
    duplicate_keys: tuple[str, ...] = ()
    line_by_key: dict[str, int] = Field(default_factory=dict)
    inline_comment_keys: tuple[str, ...] = ()


def fingerprint(data: bytes) -> str:
    """内容的 sha256（十六进制）——与 ``config_catalog.EnvFileReport.fingerprint`` 同一算法。"""
    return hashlib.sha256(data).hexdigest()


def parse_index(text: str) -> EnvFileIndex:
    """逐行索引 ``.env``：键、同键最后一行、注释/空行、重复键、行尾风格、BOM（F6）。

    行切分用 ``text.split("\\n")`` 而**不是** ``splitlines()``：后者会按 ``\\v`` / ``\\f`` /
    ``U+2028`` 等 Unicode 行边界切分——那些字符完全可能出现在一行中间，一旦被切开，「未修改行
    的字节不变」就再也无法保证。
    """
    has_bom = text.startswith(BOM)
    body = text[len(BOM) :] if has_bom else text
    segments = body.split("\n")
    trailing_newline = body.endswith("\n") and body != ""
    if body == "":
        line_count = 0
        trailing_newline = False
    else:
        line_count = len(segments) - 1 if trailing_newline else len(segments)

    line_by_key: dict[str, int] = {}
    counts: dict[str, int] = {}
    names: dict[str, str] = {}
    commented: set[str] = set()
    for position, segment in enumerate(segments):
        stripped = segment.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, raw_value = stripped.partition("=")
        name = name.strip()
        if name.lower().startswith("export "):
            name = name[len("export ") :].strip()
        if not name:
            continue
        lower = name.lower()
        line_by_key[lower] = position  # 后者胜：同键只留最后一行
        counts[lower] = counts.get(lower, 0) + 1
        names.setdefault(lower, name)
        if _comment_match(raw_value) is not None:
            commented.add(lower)

    return EnvFileIndex(
        has_bom=has_bom,
        eol="\r\n" if "\r\n" in body else DEFAULT_EOL,
        trailing_newline=trailing_newline,
        line_count=line_count,
        keys=tuple(names.values()),
        duplicate_keys=tuple(names[key] for key in names if counts[key] > 1),
        line_by_key=line_by_key,
        inline_comment_keys=tuple(names[key] for key in names if key in commented),
    )


def _comment_match(text: str) -> re.Match[str] | None:
    """``text`` 里的**行内注释**起点（``None`` = 没有注释）。

    引号感知：**实测** dotenv 尊重引号（``KEY="a # b"`` → ``a # b``），所以引号值只在**闭合引号之后**
    找注释；找不到闭合引号时按「没有注释」处理（不猜）。
    """
    stripped = text.lstrip()
    if stripped[:1] in _QUOTES:
        closing = stripped.find(stripped[0], 1)
        if closing == -1:
            return None
        return _INLINE_COMMENT_RE.search(text, len(text) - len(stripped) + closing + 1)
    return _INLINE_COMMENT_RE.search(text)


def parse_value(raw: str) -> str:
    """按 dotenv 口径解析一行的**原始值文本**（剥首尾空白 → 剥行内注释 → 去配对引号）。

    与 pydantic-settings 的 ``DotEnvSettingsSource`` **逐字对齐**（实测，探针 ``env_parse_probe``：
    ``INFO  # c`` → ``INFO``；``a#b`` → ``a#b``；``a #b`` → ``a``；``"a # b"`` → ``a # b``；
    ``  spaced`` → ``spaced``；``KEY=`` → ``''``）。审计里的「旧值哈希」因此与运行期看到的值同源
    （否则哈希记的是「文件里的一串字面量」，对不上实际生效的值）。
    """
    value = raw.strip()
    match = _comment_match(value)
    if match is not None:
        value = value[: match.start()].rstrip()
    if len(value) >= 2 and value[0] in _QUOTES and value.endswith(value[0]):
        value = value[1:-1]
    return value


def read_value(text: str, key: str) -> str | None:
    """键在文件里的值（同键取最后一行；口径同 :func:`parse_value`；不存在 → ``None``）。

    这是「文件里写的值」而不是「运行期解析出的有效值」——审计只记它的哈希与长度（I9），
    有效值一律以 ``Settings`` 为准（脊柱 §7 坑 1）。
    """
    target = key.strip().lower()
    for segment in reversed(text.split("\n")):
        stripped = segment.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, raw_value = stripped.partition("=")
        name = name.strip()
        if name.lower().startswith("export "):
            name = name[len("export ") :].strip()
        if name.lower() == target:
            return parse_value(raw_value)
    return None


def check_value(value: str, *, key: str = "") -> None:
    """值能否在 ``.env`` 中被**无损**表达；不能则抛 :class:`EnvWriteError`（fail-closed）。

    四类拒绝都是「写进去会变形」而不是「不优雅」（逐条有实测依据，探针 ``env_parse_probe``）：

    - **控制字符**（``\\r`` / ``\\n`` / NUL / BOM）：会凭空多出行或污染后续解析；
    - **首尾空白**：dotenv 会剥掉 ⇒ 写的值与生效的值不一致；
    - **空白 + ``#``**：会被当成注释起点截断（``a #b`` → ``a``）；
    - **配对引号**：dotenv 会**去引号**（``"abc"`` → ``abc``；``"a"b"`` 这种更会让整行解析失败被丢弃）
      ⇒ 拒绝而不是「写进去一个语义变形的值」。
    """
    for char in _FORBIDDEN_VALUE_CHARS:
        if char in value:
            raise EnvWriteError("control_characters", f"value for {key or 'key'} contains a control character")
    if value != value.strip():
        raise EnvWriteError("whitespace", f"value for {key or 'key'} has leading or trailing whitespace")
    if _INLINE_COMMENT_RE.search(value):
        raise EnvWriteError(
            "inline_comment",
            f"value for {key or 'key'} contains whitespace followed by '#' and would be parsed as a comment",
        )
    if len(value) >= 2 and value[0] in _QUOTES and value.endswith(value[0]):
        raise EnvWriteError(
            "quoted", f"value for {key or 'key'} is wrapped in quotes and would be unquoted when parsed"
        )
    if len(value) > MAX_VALUE_CHARS:
        raise EnvWriteError("too_long", f"value for {key or 'key'} exceeds {MAX_VALUE_CHARS} characters")


def check_key(key: str) -> None:
    """键名格式（``[A-Za-z_][A-Za-z0-9_]*``，长度有界）；非法即抛 :class:`EnvWriteError`。"""
    if not _KEY_RE.match(key):
        raise EnvWriteError("invalid_key", f"{key!r} is not a valid environment variable name")
    if len(key) > MAX_KEY_CHARS:
        raise EnvWriteError("invalid_key", f"{key!r} exceeds {MAX_KEY_CHARS} characters")


def replace_or_append(text: str, key: str, value: str) -> str:
    """把 ``key`` 的值替换为 ``value``；键不存在则**追加**（保真，见模块 docstring）。

    - 命中既有行：**只重写值区**（``=`` 之后到注释/行尾），键名写法、``export`` 前缀、``=`` 周围空白、
      行内注释与行尾（``\\r``）**原样保留**；
    - 未命中：以**文件自身**的行尾风格追加；文件原本没有末行换行时也不额外补（保持该文件的行尾状态）。
      **新建 / 空文件**用 LF + 末尾换行（:data:`DEFAULT_EOL`）。
    """
    check_key(key)
    check_value(value, key=key)
    index = parse_index(text)
    prefix = BOM if index.has_bom else ""
    body = text[len(BOM) :] if index.has_bom else text
    segments = body.split("\n")

    target = index.line_by_key.get(key.lower())
    if target is not None:
        segment = segments[target]
        terminator = "\r" if segment.endswith("\r") else ""
        content = segment[: -len(terminator)] if terminator else segment
        # ``parse_index`` 只索引含 ``=`` 的行 ⇒ 这里必定有分隔符（无 ``=`` 的不可能是 ``target``）。
        key_region, _, raw_value = content.partition("=")
        match = _comment_match(raw_value)
        tail = raw_value[match.start() :] if match is not None else ""
        segments[target] = f"{key_region}={value}{tail}{terminator}"
        return prefix + "\n".join(segments)

    line = f"{key}={value}"
    if body == "":
        return f"{prefix}{line}{DEFAULT_EOL}"
    if index.trailing_newline:
        return f"{prefix}{body}{line}{index.eol}"
    return f"{prefix}{body}{index.eol}{line}"


def backup(path: Path, backups_dir: Path, fingerprint_value: str) -> Path | None:
    """把 ``path`` 当前内容复制到 ``backups_dir``（文件名含 UTC 时间戳 + 指纹前缀）。

    文件不存在（首次创建）返回 ``None``——没有「原内容」可备份。备份是**敏感配置**：它落在项目
    状态根内、进内部状态读拒集合（I14），且**不提供任何网页下载端点**（I8）。
    """
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None
    backups_dir.mkdir(parents=True, exist_ok=True)
    name = f"{path.name.lstrip('.')}-{utc_stamp()}-{fingerprint_value[:8]}{BACKUP_SUFFIX}"
    target = backups_dir / name
    atomic_write_bytes(target, data)
    return target


def prune_backups(
    backups_dir: Path,
    *,
    retention_days: int = CONFIG_BACKUP_RETENTION_DAYS,
    max_entries: int = MAX_CONFIG_BACKUPS,
) -> int:
    """回收备份目录：先按 ``retention_days`` 过期、再按 ``max_entries`` 只留**最新的 N 个**。

    与 ``persist.prune_entries_by_mtime`` 共用同一批量 I/O 内核（``scan_dir`` / ``delete_entries``，
    一次 scandir + 一次批量删），但有两点不同：**加了条数上限**（这是备份目录的主边界——写入通道
    可能被反复触发，只靠时间窗挡不住），且**不加跨进程节流**（目录本身被 ``max_entries`` 钉死在
    50 条量级，一次 scandir 的代价远小于节流标记的维护成本——节流是给万级产物目录用的）。

    单个条目删除失败不影响其余（``delete_entries`` 语义）；返回删除数。
    """
    entries = scan_dir(backups_dir)
    backups = [entry for entry in entries if not entry.is_dir and entry.path.name.endswith(BACKUP_SUFFIX)]
    backups.sort(key=lambda entry: entry.mtime, reverse=True)
    cutoff = time.time() - retention_days * 86_400 if retention_days > 0 else None
    doomed = [entry.path for entry in backups if cutoff is not None and entry.mtime < cutoff]
    survivors = [entry for entry in backups if cutoff is None or entry.mtime >= cutoff]
    doomed.extend(entry.path for entry in survivors[max(max_entries, 0) :])
    if not doomed:
        return 0
    deleted, _ = delete_entries(doomed, [])
    return deleted


def utc_stamp(when: datetime | None = None) -> str:
    """UTC 时间戳（微秒精度，文件名安全）：``20260924T164712123456Z``。

    微秒精度让「同一秒内的两次写入」也各有独立备份名（秒精度会互相覆盖）；``Z`` 后缀显式声明
    UTC，避免「本地时间还是 UTC」的歧义。
    """
    moment = when if when is not None else datetime.now(UTC)
    return moment.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")


__all__ = [
    "BACKUP_SUFFIX",
    "BOM",
    "BOM_BYTES",
    "CONFIG_BACKUP_RETENTION_DAYS",
    "DEFAULT_EOL",
    "MAX_CONFIG_BACKUPS",
    "MAX_KEY_CHARS",
    "MAX_VALUE_CHARS",
    "EnvFileIndex",
    "EnvWriteError",
    "backup",
    "check_key",
    "check_value",
    "fingerprint",
    "parse_index",
    "parse_value",
    "prune_backups",
    "read_value",
    "replace_or_append",
    "utc_stamp",
]
