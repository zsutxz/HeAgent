"""持久化辅助：原子写 + 容错读 + 可选的跨进程文件锁。

供 ``ledger`` / ``store`` 共用。原子写避免崩溃中途留下截断 JSON 破坏 resume /
幂等；容错读让单条坏记录不致以 ``JSONDecodeError`` / ``ValidationError`` 中断
整个 run（记 ``logger.error`` 保持可观测——「显性失败」的可观测版本，而非静默吞错）。

V2 新增：可选的跨进程文件锁（``lock=True``），通过 ``.lock`` 文件实现平台自适应
排他锁（POSIX ``fcntl.flock`` / Windows ``msvcrt.locking``），防止多进程并发写
``.heagent/`` 时数据损坏。锁默认关闭以保持单进程场景零开销。

属于 ``engine/`` 运行时治理层（见 ``docs/frame.md`` 4.12）。
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# ── 平台自适应文件锁 ──────────────────────────────────────────────

_LOCK_POLL_INTERVAL = 0.1


def _acquire_lock_posix(fd: int, timeout: float) -> None:
    """POSIX ``fcntl.flock`` 排他锁。"""
    import fcntl

    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            if time.monotonic() >= deadline:
                raise OSError(f"Failed to acquire file lock within {timeout}s")
            time.sleep(_LOCK_POLL_INTERVAL)


def _acquire_lock_windows(fd: int, timeout: float) -> None:
    """Windows ``msvcrt.locking`` 排他锁。

    需确保文件至少 1 字节（``msvcrt.locking`` 要求非零长度），空文件先写哨兵字节。
    """
    import msvcrt

    # 空文件写哨兵字节（msvcrt.locking 对 0 字节文件行为未定义）
    try:
        cur = os.lseek(fd, 0, os.SEEK_END)
        if cur == 0:
            os.write(fd, b"\x00")
    except OSError:
        pass

    deadline = time.monotonic() + timeout
    while True:
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return
        except OSError:
            if time.monotonic() >= deadline:
                raise OSError(f"Failed to acquire file lock within {timeout}s")
            time.sleep(_LOCK_POLL_INTERVAL)


def _acquire_lock(fd: int, timeout: float) -> None:
    """平台自适应排他锁。"""
    if sys.platform == "win32":
        _acquire_lock_windows(fd, timeout)
    else:
        _acquire_lock_posix(fd, timeout)


def _release_lock_posix(fd: int) -> None:
    import fcntl

    fcntl.flock(fd, fcntl.LOCK_UN)


def _release_lock_windows(fd: int) -> None:
    import msvcrt

    try:
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except OSError:
        pass  # 文件可能已被关闭；静默忽略


def _release_lock(fd: int) -> None:
    """平台自适应释放锁。"""
    if sys.platform == "win32":
        _release_lock_windows(fd)
    else:
        _release_lock_posix(fd)


# ── 公开 API ─────────────────────────────────────────────────────


def atomic_write_text(
    path: Path,
    text: str,
    *,
    lock: bool = False,
    lock_timeout: float = 5.0,
) -> None:
    """原子写：同目录写临时文件 → ``os.replace`` 原子替换。

    ``os.replace`` 在同目录内为原子 rename（POSIX ``rename(2)`` / Windows
    ``MoveFileEx`` REPLACE_EXISTING 语义），避免 write 中途崩溃留下截断的目标文件。
    临时文件名为 ``<name>.tmp``——注意 ``glob("*.json")`` 不会匹配它。

    Parameters
    ----------
    lock:
        若为 True，写入前获取跨进程排他锁，防止并发写数据损坏。
        默认 False（单进程场景零开销）。
    lock_timeout:
        锁获取超时（秒）。超时抛 ``OSError``。仅在 ``lock=True`` 时有效。
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    lock_fd: int | None = None

    if lock:
        lock_path = path.with_name(path.name + ".lock")
        lock_fd = os.open(lock_path, os.O_CREAT | os.O_RDWR)
        try:
            _acquire_lock(lock_fd, lock_timeout)
        except BaseException:
            os.close(lock_fd)
            raise

    try:
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, path)
    finally:
        if lock and lock_fd is not None:
            try:
                _release_lock(lock_fd)
            except Exception:
                logger.debug("Failed to release lock on %s", path, exc_info=True)
            finally:
                os.close(lock_fd)


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
