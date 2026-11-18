"""密钥轮换提醒（Story 67.4）：记录每个密钥名**首次被观测到**的日期，超期在启动期提醒。

**只记名，不记值**——状态文件 ``<项目状态根>/key_rotation.json`` 的内容形如::

    {"version": 1, "first_seen": {"DEEPSEEK_API_KEY": "2026-11-18"}}

密钥本身从不写入（本模块的入参只有名字，值只在 :func:`secret_names` 内部用于判「是否已配置」，
不进返回值、不进文件、不进日志）。

**写一次**：某键首次观测到即落盘，之后**永不改写**（轮换后重新计时是运维动作，不由启动期猜；
真要重置就删掉该条目）。因此本模块对状态文件只做「补缺」，不做「更新”。

**0 = 关闭**：``KEY_ROTATION_REMIND_DAYS=0`` 时整个功能不运行（不落盘、不告警），而不是「每次启动
都超期」。

状态文件损坏 / 不可写一律降级：提醒是维护动作，不是功能，绝不阻断启动（调用方
``housekeeping`` 另有兜底 try）。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date
from typing import TYPE_CHECKING

from heagent.config.keyring_store import get_secret

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from heagent.config import Settings

logger = logging.getLogger(__name__)

#: 状态文件名（落在 ``<项目状态根>/.heagent/`` 下）。
ROTATION_FILE_NAME = "key_rotation.json"

#: 状态文件结构版本（结构变更时递增；读到更高版本只按已知部分处理）。
_FILE_VERSION = 1

#: ``Settings`` 里视为「密钥」的字段后缀（派生观测名单，不手工维护清单）。
_SECRET_FIELD_SUFFIXES = ("_api_key", "_api_keys")


@dataclass(frozen=True)
class RotationEntry:
    """一条超期记录：密钥名 + 首次观测日 + 已使用天数。"""

    name: str
    first_seen: date
    age_days: int


@dataclass(frozen=True)
class RotationReport:
    """一次启动期比对的结论（供日志与测试断言）。"""

    recorded: tuple[str, ...] = ()
    overdue: tuple[RotationEntry, ...] = field(default_factory=tuple)
    disabled: bool = False


def secret_names(settings: Settings) -> tuple[str, ...]:
    """当前**已配置**的密钥名（大写设置键名），由 ``Settings`` 的密钥字段派生。

    值是「是否配置」的判据：经 :func:`heagent.config.keyring_store.get_secret` 取，
    因此 keyring 里提供的证书也计入观测（与装配层同一收敛点）。
    """
    fields = getattr(type(settings), "model_fields", {})
    names: list[str] = []
    for field_name in fields:
        if field_name.endswith(_SECRET_FIELD_SUFFIXES) and get_secret(field_name, settings=settings):
            names.append(field_name.upper())
    return tuple(names)


def observe(
    names: Iterable[str],
    *,
    state_root: Path,
    remind_days: int,
    today: date | None = None,
) -> RotationReport:
    """补记首次观测日，并返回超期条目。

    Args:
        names: 已配置的密钥名（见 :func:`secret_names`）。
        state_root: 项目状态根（通常是 ``<workspace>/.heagent``）。
        remind_days: 提醒阈值天数；``<= 0`` 表示关闭（不落盘、不报告）。
        today: 注入当天日期（测试用；默认取系统日期）。
    """
    if remind_days <= 0:
        return RotationReport(disabled=True)

    day = today or date.today()
    path = state_root / ROTATION_FILE_NAME
    first_seen = _load(path)

    pending = [name for name in names if name not in first_seen]
    recorded: tuple[str, ...] = ()
    if pending:
        for name in pending:
            first_seen[name] = day
        _save(path, first_seen)
        recorded = tuple(pending)

    overdue = [
        RotationEntry(name=name, first_seen=seen, age_days=(day - seen).days)
        for name, seen in first_seen.items()
        if (day - seen).days >= remind_days
    ]
    overdue.sort(key=lambda entry: (-entry.age_days, entry.name))
    return RotationReport(recorded=recorded, overdue=tuple(overdue))


def _load(path: Path) -> dict[str, date]:
    """读状态文件；缺失即空，损坏即告警后当空（不猜、不抛）。"""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        logger.warning("key rotation state file %s is unreadable; starting a fresh record", path, exc_info=True)
        return {}
    if not isinstance(raw, dict):
        logger.warning("key rotation state file %s has an unexpected shape; starting a fresh record", path)
        return {}
    entries = raw.get("first_seen")
    if not isinstance(entries, dict):
        return {}
    loaded: dict[str, date] = {}
    for name, value in entries.items():
        if not isinstance(name, str) or not isinstance(value, str):
            continue
        try:
            loaded[name] = date.fromisoformat(value)
        except ValueError:
            # 单条坏记录不该抹掉整份历史：跳过它，其余照常沿用。
            logger.debug("key rotation: ignoring malformed first_seen for %r (%r)", name, value)
    return loaded


def _save(path: Path, first_seen: dict[str, date]) -> None:
    """原子写状态文件；失败只告警（提醒不阻断启动）。"""
    payload = {
        "version": _FILE_VERSION,
        "first_seen": {name: seen.isoformat() for name, seen in sorted(first_seen.items())},
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        logger.warning(
            "key rotation: cannot write %s; the record will be retried on a later startup", path, exc_info=True
        )
