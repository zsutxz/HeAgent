"""持久化辅助：原子写 + 容错读。

供 ``ledger`` / ``store`` 共用。原子写避免崩溃中途留下截断 JSON 破坏 resume /
幂等；容错读让单条坏记录不致以 ``JSONDecodeError`` / ``ValidationError`` 中断
整个 run（记 ``logger.error`` 保持可观测——「显性失败」的可观测版本，而非静默吞错）。

属于 ``engine/`` 运行时治理层（见 ``docs/frame.md`` 4.12）。
"""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, TypeVar

from pydantic import BaseModel, ValidationError

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)


def atomic_write_text(path: Path, text: str) -> None:
    """原子写：同目录写临时文件 → ``os.replace`` 原子替换。

    ``os.replace`` 在同目录内为原子 rename（POSIX ``rename(2)`` / Windows
    ``MoveFileEx`` REPLACE_EXISTING 语义），避免 write 中途崩溃留下截断的目标文件。
    临时文件名为 ``<name>.tmp``——注意 ``glob("*.json")`` 不会匹配它。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def load_json_model(path: Path, model_cls: type[T]) -> T | None:
    """容错读：``read_text`` → ``json.loads`` → ``model_cls.model_validate``。

    文件缺失（``FileNotFoundError``）静默返回 None——属正常情况（首次 acquire / 尚无记录），
    不计为错误。其余读 / 解析 / 校验失败（``OSError`` / ``JSONDecodeError`` /
    ``ValidationError``）记 ``logger.error`` 并返回 None，不向调用方抛——单条坏记录不应
    中断整个 run。
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Failed to read JSON from %s: %s", path, exc)
        return None
    try:
        return model_cls.model_validate(payload)
    except ValidationError as exc:
        logger.error("Failed to validate %s from %s: %s", model_cls.__name__, path, exc)
        return None
