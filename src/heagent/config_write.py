"""配置写入通道：脊柱 §8 的 **10 步执行 + 1 项生效语义**（Story 50-5）。

本模块是**顶层**模块——只依赖标准库、Pydantic、:mod:`heagent.config`、:mod:`heagent.config_catalog`、
:mod:`heagent.envfile` 与 :mod:`heagent.persist`；不得依赖 ``network`` / ``engine`` / ``agent`` /
入口层（网络层只把不透明项目 id 与协议模型交给注入的 console，脊柱 I1）。

流水线（顺序固定，任一步失败即拒绝且**文件不变**）：

1. 闸门 ``HTTP_CONSOLE_WRITE_ENABLED``（默认 ``False``）→ ``write_disabled``；
2. 来源（仅本机回环）→ ``loopback_required`` —— **在传输层执行**（见「分层」）；
3. 键：显式白名单 **且** 不得被系统环境变量提供（后者与 50-4 面板的 ``writable=false`` 同源，
   ``config_catalog.system_env_keys``）→ ``field_not_writable``；
4. 值：字段级守卫（枚举 / 上下界，D3 的强制前提）+ 能否在 ``.env`` 中无损表达 → ``invalid_value``；
5. 指纹：客户端持有的指纹 ≠ 当前文件 sha256 → ``config_conflict``（不改任何东西）；
6. 候选：行级替换/追加 → 临时文件 → ``Settings(_env_file=候选)`` 构造成功 + ``ROUTING_POOLS``
   池解析校验 → 否则 ``invalid_value``（把「写坏 = 起不来」前移，I6）；
7. 备份：当前内容复制到 ``config_backups``（时间戳 + 指纹前缀，条目数与保留期有上限）；
8. 写入：``persist.atomic_update_bytes``（跨进程锁贯穿读改写，**字节级**保真，I7）；
9. 回读：重新读盘 + 指纹比对（**在同一把锁内**）→ 不符则还原原内容并 ``config_write_failed``；
10. 审计：一行 JSONL 到 ``<项目状态根>/console/audit.jsonl``（时间 / 来源 / 键名 / 旧新值**哈希与
    长度** / 结果 —— **不含值**，I9）。审计追加失败**不阻断**已成功的写，但结果里如实带
    ``audit_recorded=false``（绝不让人误以为「已审计」）。

第 11 项是**生效语义**（I10）：写成功后由控制台把该项目运行时的配置代标记过期 —— 当前在途 run 继续
用旧快照，下一次 run 重新解析。本模块只负责「落盘」，不假装知道谁在跑。

分层：第 2 步留在传输层（``network.http_server._loopback_error``，与 50-2 的项目登记同一判定与同一
辅助函数）——网络层不认识 ``Settings``（I1），把闸门状态的副本塞进 ``HttpServerConfig`` 会制造第二个
事实源（过期副本会「谎报已开启」）。代价是「非回环 + 闸门关闭」时先回 ``loopback_required``：对远端
客户端少说一句本机策略，方向是收紧而不是放松。

审计口径：只有**真的改动了文件**的路径落审计 —— 成功（``applied``）与「写下去但回读不符、已还原」
（``rolled_back``，磁盘级异常必须留下痕迹）。闸门/白名单/值/指纹这些**文件未变**的拒绝不落审计：
它们可以由一个回环客户端无限重放，逐条落盘等于给审计文件开了个灌水口。
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, field_validator

from heagent import envfile
from heagent.config import GLOBAL_CONFIG_FILE, Settings
from heagent.config_catalog import classify, guards_for, routing_report, system_env_keys
from heagent.persist import atomic_update_bytes

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)

# ── 常量 ──

#: 一次请求最多改几个键（协议模型镜像同一上界，由测试钉住）。
MAX_CONFIG_WRITE_CHANGES = 64

#: 审计文件名（落在 ``WorkspacePaths.console_dir`` 内）。
AUDIT_FILENAME = "audit.jsonl"

#: ``ROUTING_POOLS`` —— 唯一需要「额外语义校验」的键（JSON + 池条目）。
ROUTING_POOLS_KEY = "ROUTING_POOLS"

#: 写锁的等待上限（秒）：超过即 ``OSError`` → ``config_write_failed``（绝不无界等待）。
WRITE_LOCK_TIMEOUT = 5.0

#: 错误信息里单条字段级原因的长度上界（响应体不随异常文本膨胀）。
MAX_REASON_CHARS = 240


class ConfigWriteCode(StrEnum):
    """写入通道的稳定错误码（与 ``network.http_protocol.HttpErrorCode`` 的成员同名，网络层映射状态码）。

    ``loopback_required`` 不在此列：第 2 步在传输层执行，本模块永远不会产出该码。
    """

    INVALID_REQUEST = "invalid_request"
    WRITE_DISABLED = "write_disabled"
    FIELD_NOT_WRITABLE = "field_not_writable"
    INVALID_VALUE = "invalid_value"
    CONFIG_CONFLICT = "config_conflict"
    CONFIG_WRITE_FAILED = "config_write_failed"


class ConfigWriteRejection(Exception):
    """写入被拒（fail-closed）：``code`` 是稳定错误码，``message`` 是给客户端的原因（字段级、无凭证）。"""

    def __init__(self, code: ConfigWriteCode, message: str) -> None:
        super().__init__(message)
        self.code = code


# ── 模型 ──


class ConfigChange(BaseModel):
    """一个键的目标值（``value`` 一律是字符串：``.env`` 是文本，类型/范围由第 4/6 步校验）。

    ``key`` 归一化为**大写**并去空白（env 键大小写不敏感，脊柱 §7 校正 C6）；``value`` **绝不做任何
    归一化**——首尾空白会让「写的值」与「解析出的值」不一致，由第 4 步显式拒绝而不是静默裁剪。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str = Field(min_length=1, max_length=envfile.MAX_KEY_CHARS)
    value: str = Field(max_length=envfile.MAX_VALUE_CHARS)

    @field_validator("key", mode="before")
    @classmethod
    def _normalize_key(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value


class ConfigAuditEntry(BaseModel):
    """审计里的一个键：**只有**哈希与长度，没有值（I9）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    old_hash: str | None = None
    old_length: int | None = None
    new_hash: str
    new_length: int


class ConfigAuditRecord(BaseModel):
    """一行审计（JSONL）：时间 / 来源 / 结果 / 前后文件指纹 / 每个键的哈希与长度。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timestamp: str
    source: str
    result: str
    fingerprint_before: str | None = None
    fingerprint_after: str | None = None
    entries: tuple[ConfigAuditEntry, ...] = ()

    def to_jsonl(self) -> str:
        """单行 JSON（LF 行尾由写入方保证；``ensure_ascii=False`` 保留中文来源说明）。"""
        return json.dumps(self.model_dump(mode="json"), ensure_ascii=False, separators=(",", ":"))


class ConfigWriteResult(BaseModel):
    """一次成功写入的结果（控制台据此刷新徽标与提示「下一次运行生效」）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    fingerprint: str
    keys: tuple[str, ...] = ()
    backup: str | None = None
    audit_recorded: bool = False


@dataclass
class _WriteState:
    """写锁内累积的中间状态（内部状态对象 ⇒ dataclass，与 ``AgentState`` 同例）。"""

    expected_fingerprint: str | None
    source: str
    fingerprint_before: str | None = None
    fingerprint_after: str | None = None
    backup_name: str | None = None
    readback_failed: bool = False
    entries: list[ConfigAuditEntry] = field(default_factory=list)


# ── 第 3/4 步：键与值（锁外，纯校验） ──


def _number(value: float) -> str:
    """数字文案（``10.0`` → ``10``），让字段级原因读起来是配置而不是浮点。"""
    return f"{value:g}"


def guard_reason(key: str, value: str) -> str | None:
    """值是否满足该键的守卫约束；不满足返回**字段级原因**（``None`` = 通过或该键无约束）。

    ``config_catalog.guards_for`` 已经把「显式守卫（写通道口径）」与「``Settings`` 字段元数据派生的
    边界」合并：``MAX_ITERATIONS`` 这类强校验字段因此也会先在这里被挡下（更早给出可读原因），
    而弱校验字段（``LOG_LEVEL`` / ``RETRY_*``，I6 对它们是**空门**）的全部约束都来自这张表。
    """
    guard = guards_for(key)
    if guard is None:
        return None
    if value == "" and guard.allow_empty:
        return None
    if guard.kind == "enum":
        if value not in guard.values:
            return f"must be one of {', '.join(guard.values)}"
        return None
    try:
        number = float(value)
    except ValueError:
        return "must be a number"
    if not math.isfinite(number):
        return "must be a finite number"
    if guard.minimum is not None and (number < guard.minimum or (guard.exclusive_minimum and number == guard.minimum)):
        return f"must be {'greater than' if guard.exclusive_minimum else 'at least'} {_number(guard.minimum)}"
    if guard.maximum is not None and (number > guard.maximum or (guard.exclusive_maximum and number == guard.maximum)):
        return f"must be {'less than' if guard.exclusive_maximum else 'at most'} {_number(guard.maximum)}"
    return None


def validate_changes(changes: Sequence[ConfigChange]) -> tuple[ConfigChange, ...]:
    """第 3/4 步：白名单 + 系统环境变量 + 字段级守卫 + 值能否在 ``.env`` 中无损表达。

    整批**原子**：任何一个键被拒 → 整次请求被拒，文件不变（不做部分写入）。
    """
    if not changes:
        raise ConfigWriteRejection(ConfigWriteCode.INVALID_REQUEST, "at least one change is required")
    seen: set[str] = set()
    for change in changes:
        if change.key.lower() in seen:
            raise ConfigWriteRejection(ConfigWriteCode.INVALID_REQUEST, f"duplicate key {change.key}")
        seen.add(change.key.lower())
    provided_by_system = system_env_keys()
    for change in changes:
        verdict = classify(change.key)
        if not verdict.writable:
            raise ConfigWriteRejection(
                ConfigWriteCode.FIELD_NOT_WRITABLE, f"{change.key} is read-only ({verdict.reason})"
            )
        if change.key.lower() in provided_by_system:
            raise ConfigWriteRejection(
                ConfigWriteCode.FIELD_NOT_WRITABLE,
                f"{change.key} is provided by the process environment and cannot be changed from .env",
            )
        reason = guard_reason(change.key, change.value)
        if reason is not None:
            raise ConfigWriteRejection(ConfigWriteCode.INVALID_VALUE, f"{change.key}: {reason}")
        try:
            envfile.check_key(change.key)
            envfile.check_value(change.value, key=change.key)
        except envfile.EnvWriteError as exc:
            raise ConfigWriteRejection(ConfigWriteCode.INVALID_VALUE, f"{change.key}: {exc}") from exc
    return tuple(changes)


# ── 第 6 步：候选构造（I6） ──


def _short(text: object, limit: int = MAX_REASON_CHARS) -> str:
    """把异常文本压成单行、有界的原因串（响应体不随异常膨胀）。"""
    collapsed = " ".join(str(text).split())
    return collapsed if len(collapsed) <= limit else f"{collapsed[: limit - 1]}…"


def _candidate_settings(candidate: bytes, global_env_file: Path | None) -> Settings:
    """用候选内容构造一次 ``Settings``（口径与项目运行期一致：``_env_file=[全局, 候选]`` + 系统环境变量）。"""
    fd, raw = tempfile.mkstemp(prefix="heagent-config-candidate-", suffix=".env")
    path = Path(raw)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(candidate)
        env_files = [str(global_env_file)] if global_env_file is not None else []
        env_files.append(str(path))
        # ``_env_file`` 是 pydantic-settings 的运行时参数（mypy 按字段合成的签名看不到它）。
        return Settings(_env_file=env_files)  # type: ignore[call-arg]
    finally:
        path.unlink(missing_ok=True)


def _candidate_reason(exc: Exception) -> str:
    """把候选构造的失败压成**点名字段**的一行原因（``MAX_ITERATIONS: Input should be a valid integer``）。

    取第一条错误即可：写通道一次只改少量键，点名第一个坏字段已经足够可操作；整段 ``ValidationError``
    文本既冗长又包含 pydantic 的文档链接（响应体不随异常文本膨胀）。
    """
    errors = getattr(exc, "errors", None)
    if callable(errors):
        items = errors()
        first = items[0] if items else None
        if isinstance(first, dict):
            field = ".".join(str(part) for part in first.get("loc", ()) if str(part))
            message = str(first.get("msg", "invalid value"))
            return f"{field.upper() or 'value'}: {message}"
    return f"candidate configuration is invalid: {_short(exc)}"


def validate_candidate(candidate: bytes, *, global_env_file: Path | None, changes: Sequence[ConfigChange]) -> Settings:
    """候选必须能被 ``Settings`` 构造成功（I6），且 ``ROUTING_POOLS`` 的池条目确实生效。

    ``Settings`` 构造只是**必要条件**：对弱校验字段它是空门（``LOG_LEVEL`` 自由 ``str``、``retry_*``
    只有下界），因此第 4 步的字段级守卫才是那类键的真实闸门（D3）。
    """
    try:
        settings = _candidate_settings(candidate, global_env_file)
    except Exception as exc:  # noqa: BLE001 - 候选构造失败一律视为「值非法」（把「写坏 = 起不来」前移）
        raise ConfigWriteRejection(ConfigWriteCode.INVALID_VALUE, _candidate_reason(exc)) from exc
    if any(change.key == ROUTING_POOLS_KEY for change in changes):
        report = routing_report(settings)
        if report.invalid_json:
            raise ConfigWriteRejection(
                ConfigWriteCode.INVALID_VALUE,
                "ROUTING_POOLS: not a valid JSON object (the whole config would be ignored)",
            )
        if report.ignored_entries:
            raise ConfigWriteRejection(
                ConfigWriteCode.INVALID_VALUE,
                "ROUTING_POOLS: these entries are invalid and would be ignored: " + ", ".join(report.ignored_entries),
            )
    return settings


# ── 第 10 步：审计 ──


def append_audit(console_dir: Path, record: ConfigAuditRecord) -> bool:
    """追加一行 JSONL 到 ``console_dir/audit.jsonl``；失败只 WARNING 并返回 ``False``（不阻断已成功的写）。

    与 ledger 回写失败的立场一致：把「已经发生的事实」记不下来，不该让事实本身变成错误。但**调用方
    必须把 ``False`` 体现在响应里**（``audit_recorded=false``），否则会给人「已审计」的错觉（T3）。
    """
    path = console_dir / AUDIT_FILENAME
    try:
        console_dir.mkdir(parents=True, exist_ok=True)
        # newline="\n"：JSONL 必须 LF，禁止平台行尾翻译（Windows 上会变 CRLF）。
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(f"{record.to_jsonl()}\n")
    except OSError:
        logger.warning("Failed to append config audit record to %s", path, exc_info=True)
        return False
    return True


def _value_hash(value: str | None) -> tuple[str | None, int | None]:
    """（sha256 十六进制, 字符数）；``None`` 原样透传（键此前不存在）。"""
    if value is None:
        return None, None
    return hashlib.sha256(value.encode("utf-8")).hexdigest(), len(value)


def _audit(state: _WriteState, *, console_dir: Path, result: str) -> bool:
    """落一条审计（``applied`` / ``rolled_back``）。时间戳显式 UTC（``Z`` 后缀，无时区歧义）。"""
    record = ConfigAuditRecord(
        timestamp=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        source=state.source,
        result=result,
        fingerprint_before=state.fingerprint_before,
        fingerprint_after=state.fingerprint_after,
        entries=tuple(state.entries),
    )
    return append_audit(console_dir, record)


# ── 第 5/6/7 步：锁内（读改写 + 候选 + 备份） ──


def _read_back(path: Path) -> bytes:
    """回读校验的**唯一读点**（测试在这里注入「盘上内容与预期不符」）。"""
    return path.read_bytes()


def _apply_locked(
    current: bytes | None,
    *,
    target: Path,
    state: _WriteState,
    changes: Sequence[ConfigChange],
    global_env_file: Path | None,
    backups_dir: Path,
    max_backups: int,
    backup_retention_days: int,
) -> bytes:
    """锁内的读改写：指纹冲突 → 行级替换 → 候选构造 → 备份 → 返回待写入字节。

    抛出的任何异常都会在 ``atomic_update_bytes`` 写盘**之前**传播出去 ⇒ 文件、备份、审计三者都不变
    （fail-closed 的落点就在这里：校验全部发生在替换文件之前）。
    """
    state.fingerprint_before = envfile.fingerprint(current) if current is not None else None
    if state.expected_fingerprint != state.fingerprint_before:
        raise ConfigWriteRejection(
            ConfigWriteCode.CONFIG_CONFLICT,
            "the project .env changed since it was loaded; reload the panel before writing",
        )
    if current is None:
        text = ""
    else:
        try:
            text = current.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ConfigWriteRejection(
                ConfigWriteCode.CONFIG_WRITE_FAILED,
                "the project .env is not valid UTF-8; refusing to rewrite it",
            ) from exc

    for change in changes:
        old_value = envfile.read_value(text, change.key)
        text = envfile.replace_or_append(text, change.key, change.value)
        old_hash, old_length = _value_hash(old_value)
        new_hash, new_length = _value_hash(change.value)
        state.entries.append(
            ConfigAuditEntry(
                key=change.key,
                old_hash=old_hash,
                old_length=old_length,
                new_hash=new_hash or "",
                new_length=new_length or 0,
            )
        )
    replacement = text.encode("utf-8")

    validate_candidate(replacement, global_env_file=global_env_file, changes=changes)

    if current is not None:
        backup_path = envfile.backup(target, backups_dir, state.fingerprint_before or "")
        state.backup_name = backup_path.name if backup_path is not None else None
        pruned = envfile.prune_backups(backups_dir, retention_days=backup_retention_days, max_entries=max_backups)
        if pruned:
            logger.info("Pruned %d config backup(s) in %s", pruned, backups_dir)

    state.fingerprint_after = envfile.fingerprint(replacement)
    return replacement


def _guard_destination(env_file: Path) -> Path:
    """写入目的地**只**能是项目的 ``.env``（绝对路径）——这是编程错误的断言，不是客户端可选的参数。"""
    path = Path(env_file)
    if path.name != ".env" or not path.is_absolute():
        raise ValueError(f"config writes only target a project .env file, got {path!r}")
    return path


# ── 流水线 ──


def apply_config_write(
    changes: Sequence[ConfigChange],
    *,
    env_file: Path,
    backups_dir: Path,
    audit_dir: Path,
    write_enabled: bool,
    expected_fingerprint: str | None,
    global_env_file: Path | None = GLOBAL_CONFIG_FILE,
    source: str = "http-loopback",
    max_backups: int = envfile.MAX_CONFIG_BACKUPS,
    backup_retention_days: int = envfile.CONFIG_BACKUP_RETENTION_DAYS,
) -> ConfigWriteResult:
    """执行写入流水线（**同步**；调用方负责经 ``asyncio.to_thread`` 卸载——锁与文件 I/O 都在里面）。

    ``expected_fingerprint`` 为 ``None`` 表示客户端声明「文件尚不存在」：若盘上确有文件，指纹不匹配
    ⇒ ``config_conflict``（fail-closed，绝不做「客户端没给指纹就随便覆盖」）。
    """
    target = _guard_destination(env_file)
    if not write_enabled:
        raise ConfigWriteRejection(
            ConfigWriteCode.WRITE_DISABLED,
            "config writing is disabled; enable HTTP_CONSOLE_WRITE_ENABLED when starting the service",
        )
    validated = validate_changes(changes)
    state = _WriteState(expected_fingerprint=expected_fingerprint, source=source)

    def _update(current: bytes | None) -> tuple[bytes, None]:
        replacement = _apply_locked(
            current,
            target=target,
            state=state,
            changes=validated,
            global_env_file=global_env_file,
            backups_dir=backups_dir,
            max_backups=max_backups,
            backup_retention_days=backup_retention_days,
        )
        return replacement, None

    def _verify(written: bytes) -> None:
        """第 9 步：回读比对（**锁内**，见 ``persist.atomic_update_bytes`` 的 ``verify`` 语义）。"""
        actual = _read_back(target)
        if envfile.fingerprint(actual) != envfile.fingerprint(written):
            state.readback_failed = True
            raise ConfigWriteRejection(
                ConfigWriteCode.CONFIG_WRITE_FAILED,
                "post-write verification failed; the project .env was rolled back to its previous content",
            )

    try:
        atomic_update_bytes(target, _update, verify=_verify, lock_timeout=WRITE_LOCK_TIMEOUT)
    except ConfigWriteRejection:
        if state.readback_failed:
            # 写下去又还原 = 磁盘级异常，必须留痕（审计追加失败只能告警，绝不再抛）。
            _audit(state, console_dir=audit_dir, result="rolled_back")
        raise
    except OSError as exc:
        raise ConfigWriteRejection(ConfigWriteCode.CONFIG_WRITE_FAILED, f"config write failed: {_short(exc)}") from exc

    recorded = _audit(state, console_dir=audit_dir, result="applied")
    if not recorded:
        logger.error("Config write applied but the audit record could not be written to %s", audit_dir)
    return ConfigWriteResult(
        fingerprint=state.fingerprint_after or "",
        keys=tuple(change.key for change in validated),
        backup=state.backup_name,
        audit_recorded=recorded,
    )


__all__ = [
    "AUDIT_FILENAME",
    "MAX_CONFIG_WRITE_CHANGES",
    "MAX_REASON_CHARS",
    "ROUTING_POOLS_KEY",
    "WRITE_LOCK_TIMEOUT",
    "ConfigAuditEntry",
    "ConfigAuditRecord",
    "ConfigChange",
    "ConfigWriteCode",
    "ConfigWriteRejection",
    "ConfigWriteResult",
    "append_audit",
    "apply_config_write",
    "guard_reason",
    "validate_candidate",
    "validate_changes",
]
