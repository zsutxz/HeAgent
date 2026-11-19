"""追加式审计面：工具执行与敏感操作各落一行 JSONL，敏感操作另带前序哈希链。

定位：公共层（``pub/``，运行期零 heagent 运行栈依赖），被 ``engine/``（工具执行完成处）、
``context/``（会话删除）、``skills/``（技能删除）与入口层（配置写入调用方、``heagent audit``）共用
——只有一份存储格式、一条链、一个读取面（:func:`read_entries` / :func:`verify_chain`）。

两类记录写进**同一个**追加文件（``<状态根>/audit/tool-audit.jsonl``，文件名沿用 Story 67.2 既定默认值；
内容是审计事件流而非「只有工具行」）：

- 工具执行（:func:`record_tool_execution`）：``ts`` / ``operator`` / ``tool`` / ``args``（脱敏）/
  ``status`` / ``duration_ms`` / ``error_kind``；
- 敏感操作（:func:`record_operation`）：``operation`` / ``operator`` / ``target`` /
  ``before`` / ``after``——三者只存**摘要**（哈希 / 指纹 / 计数），绝不存明文值。

链口径：每行带 ``prev``（上一行的 ``digest``，首行为空串）与自身 ``digest``（除 ``digest`` 键的规范化
JSON 的 sha256）。:func:`verify_chain` 返回**首个**断链行号（1 起，按非空行计）：
`digest` 不符 = 该行内容被改过；`prev` 不符 = 该行之前有删行/换序。写入是
``O_APPEND`` 单次写，进程内用线程锁把「读尾 → 算链 → 追加」串成一件事。

保留与轮转（A61）：单文件达 :func:`segment_bytes`（``HEAGENT_AUDIT_SEGMENT_BYTES``，默认 8 MiB，
``0`` = 关闭）时，写路径把当前文件改名为 ``tool-audit.seg-NNN.jsonl``，新主文件首行写一条
**段头**（``kind="segment"``，``prev`` == ``continues_from`` == 上一段末行 ``digest``）⇒
:func:`verify_chain` 不看前段文本也能自证，:func:`verify_chain_segments` 再核段边界；
查询面用 ``read_entries(include_segments=True)`` / ``heagent audit list|export|verify`` 跨段。
:func:`rotate_audit` 供运维主动切段（按天归档一类）。**已知留存缺口**：整个归档段被删时
没有外部锚点可判定（链只能证明「留下的部分连续」），故轮转不替代异地备份。

fail-soft：任何读写异常只 WARNING，绝不改变业务结果（与 :mod:`heagent.pub.safe_logging` 同一立场）；
:func:`record_tool_execution` / :func:`record_operation` 返回 ``False`` 表示本次没落盘。

⚠ 非安全边界（与 ``SafetyGuard`` / ``redact_secrets`` 同一立场）：哈希链是「篡改**可检出**」而非
密码学不可篡改——不带外部密钥、不依赖 append-only 介质，能改本文件的人通常也能重算整条链；
脱敏是模式匹配启发式（复用 :func:`heagent.pub.safe_logging.redact_details`），必然有漏网形态。
跨进程并发追加未被串行化（只有进程内锁）：多进程同时写时链可能分叉，``verify`` 会如实报断链。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from heagent.pub.safe_logging import redact_details, safe_log
from heagent.pub.workspace import WorkspacePaths

logger = logging.getLogger(__name__)

#: 状态根下的审计目录名与默认文件名（文件名沿用 67.2 的既定默认值，见模块 docstring）。
AUDIT_DIRNAME = "audit"
AUDIT_FILENAME = "tool-audit.jsonl"

#: 操作者标识的环境变量覆盖：服务化 / 容器部署可显式指定（缺省 ``<user>@pid<pid>``）。
OPERATOR_ENV = "HEAGENT_AUDIT_OPERATOR"

#: 单段字节上限的进程环境变量覆盖（``0`` = 关闭轮转）；与 :data:`OPERATOR_ENV` 同族——
#: 都是部署期开关而非配置面设置，故不进 ``Settings``（``pub/`` 不得依赖 ``config/``）。
SEGMENT_BYTES_ENV = "HEAGENT_AUDIT_SEGMENT_BYTES"

#: 单段默认上限：8 MiB（约 3 万条记录，达此量再轮转；``audit verify`` 仍是线性一次读）。
DEFAULT_SEGMENT_BYTES = 8 * 1024 * 1024

#: 单个字符串参数 / 整份 ``args`` 的字符上限（超限即截断并标 ``_truncated``）。
MAX_FIELD_CHARS = 200
MAX_ARGS_CHARS = 2_000

#: 读尾回看的字节数：一条审计行远小于此值（超大 ``args`` 已被上限截断）。
_TAIL_WINDOW_BYTES = 64 * 1024

#: 进程内串行化「读尾 → 算链 → 追加」；跨进程见模块 docstring 的已知局限。
#: 可重入：轮转在持锁状态下再调一次 :func:`_append` 写段头。
_APPEND_LOCK = threading.RLock()


# ── 路径与操作者 ────────────────────────────────────────────────


def state_dir_for(root: str | Path | None = None) -> Path:
    """工作区根 → 状态目录（``<root>/.heagent``；``root=None`` 取进程 cwd，与 workspace_root 口径一致）。"""
    return WorkspacePaths.from_root(Path.cwd() if root is None else root).state_dir


def resolve_audit_path(
    *,
    state_dir: str | Path | None = None,
    root: str | Path | None = None,
) -> Path:
    """审计文件绝对落点：``state_dir`` 优先，否则由工作区根 ``root`` 派生，再否则进程 cwd。"""
    base = Path(state_dir) if state_dir is not None else state_dir_for(root)
    return base / AUDIT_DIRNAME / AUDIT_FILENAME


def current_operator(*, run_id: str | None = None, session_id: str | None = None) -> str:
    """操作者标识：``HEAGENT_AUDIT_OPERATOR`` 覆盖优先，否则 ``<user>@pid<pid>``，再缀 run/session。"""
    override = os.environ.get(OPERATOR_ENV, "").strip()
    parts = [override or f"{_user_name()}@pid{os.getpid()}"]
    if session_id:
        parts.append(f"session:{session_id}")
    if run_id:
        parts.append(f"run:{run_id}")
    return " ".join(parts)


def _user_name() -> str:
    """尽力取登录名（容器内可能无 passwd 条目 ⇒ 退化为 ``unknown``，绝不抛）。"""
    try:
        import getpass

        return getpass.getuser() or "unknown"
    except Exception:  # noqa: BLE001 - 标识取不到不该让审计/业务失败
        return "unknown"


# ── 摘要原语（只存哈希，不存明文）──────────────────────────────


def fingerprint_text(text: str) -> str:
    """文本的指纹（``sha256:<hex>``）——敏感值的唯一可落盘形态。"""
    return "sha256:" + hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def fingerprint_file(path: str | Path) -> dict[str, Any]:
    """文件摘要：``{"sha256": ..., "bytes": ...}``；读不到时只给 ``{"bytes": 0, "error": ...}``。"""
    try:
        data = Path(path).read_bytes()
    except OSError as exc:
        return {"bytes": 0, "error": type(exc).__name__}
    return {"sha256": fingerprint_text(data.decode("utf-8", errors="replace")), "bytes": len(data)}


def fingerprint_dir(path: str | Path, *, max_files: int = 512) -> dict[str, Any]:
    """目录摘要：``{"files": n, "sha256": ...}``（按相对路径排序后逐文件累积，``max_files`` 截断）。"""
    root = Path(path)
    entries: list[tuple[str, str]] = []
    try:
        for item in sorted(root.rglob("*")):
            if not item.is_file():
                continue
            entries.append((str(item.relative_to(root)), fingerprint_file(item).get("sha256", "")))
            if len(entries) >= max_files:
                break
    except OSError as exc:
        return {"files": len(entries), "error": type(exc).__name__}
    rolling = fingerprint_text("|".join(f"{name}:{digest}" for name, digest in entries))
    return {"files": len(entries), "sha256": rolling}


# ── 记录模型 ────────────────────────────────────────────────────


class AuditEntry(BaseModel):
    """一行审计记录的公共面：时间 / 操作者 / 类别 / 链字段（``frozen``：记录发出后不该被就地改）。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    ts: str
    operator: str
    kind: str
    prev: str = ""
    digest: str = ""


class ToolAuditEntry(AuditEntry):
    """一次工具执行：参数已脱敏，``status`` 为 ``ok`` / ``error`` / ``blocked``。"""

    kind: Literal["tool"] = "tool"
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    status: Literal["ok", "error", "blocked"]
    duration_ms: int | None = None
    error_kind: str | None = None


class OperationAuditEntry(AuditEntry):
    """一次敏感操作：``before`` / ``after`` 只放摘要（哈希 / 指纹 / 计数），不放明文。"""

    kind: Literal["operation"] = "operation"
    operation: str
    target: str
    before: dict[str, Any] | None = None
    after: dict[str, Any] | None = None


class SegmentAuditEntry(AuditEntry):
    """段头记录：轮转后新文件的首行，用 ``continues_from`` 承接上一段末行 ``digest``。

    ``prev`` 与 ``continues_from`` 同值（段头自身也参与链），因此 :func:`verify_chain` 可以在
    **不含前段文本**的情况下从任意段继续校验——归档段被删掉时「接不上」是可检出的。
    """

    kind: Literal["segment"] = "segment"
    continues_from: str = ""


class ChainVerdict(BaseModel):
    """链校验结论：``first_broken_line`` 为 ``None`` 即完整（``lines`` 为参与校验的非空行数）。"""

    model_config = ConfigDict(frozen=True)

    path: str
    lines: int
    first_broken_line: int | None = None
    reason: str = ""

    @property
    def ok(self) -> bool:
        """哈希链是否完好（首个断链行为 `None` 即完好）。"""
        return self.first_broken_line is None


# ── 写 ──────────────────────────────────────────────────────────


def _utc_now() -> str:
    """记录时间戳：**带时区**的 UTC ISO（无时区的 ts 会让 ``--since`` 口径随机器漂移）。"""
    return datetime.now(UTC).isoformat(timespec="seconds")


def _canonical(payload: dict[str, Any]) -> str:
    """规范化 JSON（键排序、无空格、非 ASCII 原样）：同内容必得同字节，链哈希才可复算。"""
    return json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)


def _digest_of(payload: dict[str, Any]) -> str:
    """``payload`` 去掉 ``digest`` 键后的指纹（``prev`` 参与计算）。"""
    return fingerprint_text(_canonical({key: value for key, value in payload.items() if key != "digest"}))


def _clamp(value: Any, *, depth: int = 2) -> Any:
    """把参数值收进「可 JSON 化 + 有界」的形状：长串截断、浅层容器递归、其余转 ``str``。"""
    if isinstance(value, str):
        return value if len(value) <= MAX_FIELD_CHARS else f"{value[:MAX_FIELD_CHARS]}…(truncated)"
    if isinstance(value, dict) and depth > 0:
        return {str(key): _clamp(item, depth=depth - 1) for key, item in value.items()}
    if isinstance(value, (list, tuple)) and depth > 0:
        return [_clamp(item, depth=depth - 1) for item in value]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return _clamp(str(value), depth=0)


def _redact_args(args: dict[str, Any] | None) -> dict[str, Any]:
    """脱敏 + 截断：脱敏**先于**截断（否则半截密钥形状会漏过模式匹配）。"""
    if not args:
        return {}
    redacted = {str(key): _clamp(value) for key, value in redact_details(dict(args)).items()}
    text = _canonical(redacted)
    if len(text) > MAX_ARGS_CHARS:
        return {"_truncated": True, "keys": sorted(redacted), "chars": len(text)}
    return redacted


def _read_tail_line(path: Path) -> str:
    """回看文件尾部若干字节，返回最后一条非空行（不存在 / 空文件返回空串）。"""
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            size = handle.tell()
            handle.seek(max(0, size - _TAIL_WINDOW_BYTES))
            tail = handle.read().decode("utf-8", errors="replace")
    except FileNotFoundError:
        return ""
    lines = [line for line in tail.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def _append_line(path: Path, line: str) -> None:
    """追加一行（父目录按需创建）。

    用内建的追加模式（``O_APPEND`` 语义）：不引入第三处 ``os.open``——较低层的打开面只允许留在
    ``tools/path_safety``（安全读）与 ``pub/persist``（跨进程锁）两处（见
    ``tests/test_architecture_contracts.py`` 的同名契约）。单次写入一行，配合调用方的进程内锁，
    同进程不会交错；跨进程窗口见模块 docstring 的已知局限。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"{line}\n")


def _append(entry: AuditEntry, path: Path, *, prev_hint: str | None = None, allow_rotate: bool = True) -> bool:
    """算链并追加一行；任何异常只 WARNING 并返回 ``False``（不改变调用方结果）。

    ``prev_hint``：文件还没有尾行时用的 ``prev``（段头用它承接上一段末 ``digest``）。
    ``allow_rotate``：写前是否检查段大小（段头自身写入时必须关掉，否则会无限轮转）。
    """
    try:
        with _APPEND_LOCK:
            if allow_rotate:
                _maybe_rotate_locked(path)
            prev = ""
            tail = _read_tail_line(path)
            if tail:
                prev = str(json.loads(tail).get("digest", ""))
            elif prev_hint is not None:
                prev = prev_hint
            payload = dict(entry.model_dump(mode="json"))
            payload["prev"] = prev
            payload["digest"] = _digest_of(payload)
            _append_line(path, _canonical(payload))
        return True
    except Exception:  # noqa: BLE001 - 审计是旁路：写失败只降级为「少一条记录」
        safe_log(logger, logging.WARNING, "audit record dropped (write failed): %s", path, exc_info=True)
        return False


def segment_bytes() -> int:
    """当前段大小上限：环境变量优先，非法/未设取 :data:`DEFAULT_SEGMENT_BYTES`；``0`` = 关闭轮转。"""
    raw = os.environ.get(SEGMENT_BYTES_ENV, "").strip()
    if not raw:
        return DEFAULT_SEGMENT_BYTES
    try:
        value = int(raw)
    except ValueError:
        safe_log(
            logger,
            logging.WARNING,
            "%s=%r is not an integer; using default %d bytes",
            SEGMENT_BYTES_ENV,
            raw,
            DEFAULT_SEGMENT_BYTES,
        )
        return DEFAULT_SEGMENT_BYTES
    return value if value >= 0 else DEFAULT_SEGMENT_BYTES


def segment_files(path: str | Path) -> list[Path]:
    """已归档段文件（按段号升序）；主文件名形如 ``tool-audit.seg-001.jsonl``。"""
    target = Path(path)
    return sorted(target.parent.glob(f"{target.stem}.seg-*{target.suffix}"))


def _rotate_locked(path: Path) -> Path | None:
    """把当前段改名为下一段归档文件，并在新主文件写一条段头（持锁调用）。"""
    tail = _read_tail_line(path)
    previous = str(json.loads(tail).get("digest", "")) if tail else ""
    index = len(segment_files(path)) + 1
    archived = path.with_name(f"{path.stem}.seg-{index:03d}{path.suffix}")
    try:
        path.rename(archived)
    except OSError:
        safe_log(logger, logging.WARNING, "audit segment rotation failed: %s", path, exc_info=True)
        return None
    head = SegmentAuditEntry(
        ts=_utc_now(),
        operator=current_operator(),
        continues_from=previous,
    )
    _append(head, path, prev_hint=previous, allow_rotate=False)
    logger.info("audit segment rotated: %s -> %s", path.name, archived.name)
    return archived


def _maybe_rotate_locked(path: Path) -> None:
    """段大小达上限即轮转（未达/关闭/文件不存在都静默返回，写路径上不做额外 I/O 之外的判断）。"""
    limit = segment_bytes()
    if limit <= 0:
        return
    try:
        size = path.stat().st_size
    except OSError:
        return
    if size >= limit:
        _rotate_locked(path)


def rotate_audit(path: str | Path, *, threshold: int | None = None, force: bool = False) -> Path | None:
    """手动轮转：达 ``threshold``（缺省取 :func:`segment_bytes`）才动，``force=True`` 无条件轮转。

    返回归档段路径；未达阈值 / 文件不存在 / 改名失败返回 ``None``（轮转失败不影响写入面，
    下一次 append 会重试）。运维面用它做「按天归档」一类的主动切段。
    """
    target = Path(path)
    if not target.exists():
        return None
    if not force:
        limit = segment_bytes() if threshold is None else threshold
        if limit <= 0:
            return None
        try:
            if target.stat().st_size < limit:
                return None
        except OSError:
            return None
    with _APPEND_LOCK:
        return _rotate_locked(target)


def record_tool_execution(
    *,
    tool: str,
    args: dict[str, Any] | None = None,
    status: Literal["ok", "error", "blocked"] = "ok",
    duration_ms: int | None = None,
    error_kind: str | None = None,
    operator: str | None = None,
    state_dir: str | Path | None = None,
    root: str | Path | None = None,
) -> bool:
    """落一行工具执行审计，返回是否写成功（``False`` = 已降级为 WARNING）。"""
    entry = ToolAuditEntry(
        ts=_utc_now(),
        operator=operator or current_operator(),
        tool=tool,
        args=_redact_args(args),
        status=status,
        duration_ms=duration_ms,
        error_kind=error_kind,
    )
    return _append(entry, resolve_audit_path(state_dir=state_dir, root=root))


def record_operation(
    *,
    operation: str,
    target: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    operator: str | None = None,
    state_dir: str | Path | None = None,
    root: str | Path | None = None,
) -> bool:
    """落一行敏感操作审计（``before`` / ``after`` 只允许摘要），返回是否写成功。"""
    entry = OperationAuditEntry(
        ts=_utc_now(),
        operator=operator or current_operator(),
        operation=operation,
        target=target,
        before=before,
        after=after,
    )
    return _append(entry, resolve_audit_path(state_dir=state_dir, root=root))


# ── 读与校验 ────────────────────────────────────────────────────


def _raw_lines(path: str | Path) -> list[str]:
    """按行读回原文（缺文件返回空表；编码损坏的字节按替换字符解，不中断读取面）。"""
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return []
    return [line for line in text.splitlines() if line.strip()]


def read_entries(path: str | Path, *, include_segments: bool = False) -> list[dict[str, Any]]:
    """逐行 ``json.loads`` 的读取面；坏行跳过并 WARNING（不抛——查询面不该被一行坏数据拦住）。

    ``include_segments=True`` 时按段号升序先读归档段、再读主文件（查询面要看到全历史；
    只读主文件是「只看当前段」）。
    """
    targets = [*segment_files(path), Path(path)] if include_segments else [Path(path)]
    entries: list[dict[str, Any]] = []
    for target in targets:
        for number, line in enumerate(_raw_lines(target), start=1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                safe_log(logger, logging.WARNING, "audit line %d of %s is not JSON; skipped", number, target)
                continue
            if isinstance(record, dict):
                entries.append(record)
    return entries


def parse_since(text: str) -> datetime:
    """解析 ``--since``：ISO-8601（``Z`` 视作 UTC）；无时区的按**本地时**理解。"""
    raw = text.strip()
    parsed = datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    return parsed if parsed.tzinfo is not None else parsed.astimezone()


def _entry_time(record: dict[str, Any]) -> datetime | None:
    """记录的 ``ts`` → 带时区 datetime；解析不了返回 ``None``（该条不参与时间过滤）。"""
    raw = record.get("ts")
    if not isinstance(raw, str) or not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.astimezone()


def filter_entries(
    entries: list[dict[str, Any]],
    *,
    since: datetime | None = None,
    name: str | None = None,
) -> list[dict[str, Any]]:
    """按时间窗与名称过滤：``name`` 同时匹配工具名（``tool``）与敏感操作名（``operation``）。

    时间戳缺失/不可解析的记录在给了 ``since`` 时**保留**（宁可多给一条，不让坏行静默消失）。
    """
    selected: list[dict[str, Any]] = []
    for entry in entries:
        if name is not None and name not in (entry.get("tool"), entry.get("operation")):
            continue
        if since is not None:
            stamp = _entry_time(entry)
            if stamp is not None and stamp < since:
                continue
        selected.append(entry)
    return selected


def verify_chain(path: str | Path) -> ChainVerdict:
    """校验整条链，返回首个断链行号；缺文件 = 空链（``ok``）。"""
    lines = _raw_lines(path)
    previous = ""
    for number, line in enumerate(lines, start=1):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            return ChainVerdict(path=str(path), lines=len(lines), first_broken_line=number, reason="unparsable line")
        if not isinstance(record, dict):
            return ChainVerdict(
                path=str(path), lines=len(lines), first_broken_line=number, reason="line is not an object"
            )
        digest = record.get("digest")
        if not isinstance(digest, str) or not digest:
            return ChainVerdict(path=str(path), lines=len(lines), first_broken_line=number, reason="missing digest")
        if _digest_of(record) != digest:
            return ChainVerdict(
                path=str(path),
                lines=len(lines),
                first_broken_line=number,
                reason="digest mismatch (record content was altered)",
            )
        if number == 1 and record.get("kind") == "segment":
            # 段头：``prev`` 必须等于它声明的 ``continues_from``（承接上一段末行 digest）。
            if record.get("prev") != record.get("continues_from"):
                return ChainVerdict(
                    path=str(path),
                    lines=len(lines),
                    first_broken_line=number,
                    reason="segment head is not self-consistent",
                )
        elif record.get("prev") != previous:
            return ChainVerdict(
                path=str(path),
                lines=len(lines),
                first_broken_line=number,
                reason="prev mismatch (a record before this one was removed or reordered)",
            )
        previous = digest
    return ChainVerdict(path=str(path), lines=len(lines))


def verify_chain_segments(path: str | Path) -> ChainVerdict:
    """跨段校验：逐段自查 + 段间续接（段头 ``continues_from`` 必须等于前段末行 ``digest``）。

    段边界不成立（缺段头却接了前段 / 段头接不上前段）与段内断链一样算断链，``first_broken_line``
    是**跨段累计**行号；没有归档段时与 :func:`verify_chain` 等价。
    """
    target = Path(path)
    files = [*segment_files(target), target]
    previous = ""
    total = 0
    for candidate in files:
        lines = _raw_lines(candidate)
        if not lines:
            continue
        verdict = verify_chain(candidate)
        if not verdict.ok:
            broken = total + (verdict.first_broken_line or 1)
            return ChainVerdict(
                path=str(candidate),
                lines=total + verdict.lines,
                first_broken_line=broken,
                reason=f"{candidate.name}: {verdict.reason}",
            )
        first = json.loads(lines[0])
        if isinstance(first, dict) and first.get("kind") == "segment":
            if first.get("continues_from") != previous:
                return ChainVerdict(
                    path=str(candidate),
                    lines=total + len(lines),
                    first_broken_line=total + 1,
                    reason=f"{candidate.name}: segment head does not continue the previous segment",
                )
        elif previous:
            return ChainVerdict(
                path=str(candidate),
                lines=total + len(lines),
                first_broken_line=total + 1,
                reason=f"{candidate.name}: no segment head but a previous segment exists",
            )
        last = json.loads(lines[-1])
        previous = str(last.get("digest", "")) if isinstance(last, dict) else ""
        total += len(lines)
    return ChainVerdict(path=str(target), lines=total)


__all__ = [
    "AUDIT_DIRNAME",
    "AUDIT_FILENAME",
    "MAX_ARGS_CHARS",
    "MAX_FIELD_CHARS",
    "DEFAULT_SEGMENT_BYTES",
    "OPERATOR_ENV",
    "SEGMENT_BYTES_ENV",
    "AuditEntry",
    "ChainVerdict",
    "OperationAuditEntry",
    "SegmentAuditEntry",
    "ToolAuditEntry",
    "current_operator",
    "filter_entries",
    "fingerprint_dir",
    "fingerprint_file",
    "fingerprint_text",
    "parse_since",
    "read_entries",
    "record_operation",
    "record_tool_execution",
    "resolve_audit_path",
    "rotate_audit",
    "segment_bytes",
    "segment_files",
    "state_dir_for",
    "verify_chain",
    "verify_chain_segments",
]
