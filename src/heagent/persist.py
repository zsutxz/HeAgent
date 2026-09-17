"""持久化辅助：原子写 + 容错读 + 可选的跨进程文件锁。

供 ``ledger`` / ``store`` 共用。原子写避免崩溃中途留下截断 JSON 破坏 resume /
幂等；容错读让单条坏记录不致以 ``JSONDecodeError`` / ``ValidationError`` 中断
整个 run（记 ``logger.error`` 保持可观测——「显性失败」的可观测版本，而非静默吞错）。

V2 新增：可选的跨进程文件锁（``lock=True``），通过 ``.lock`` 文件实现平台自适应
排他锁（POSIX ``fcntl.flock`` / Windows ``msvcrt.locking``），防止多进程并发写
``.heagent/`` 时数据损坏。锁默认关闭以保持单进程场景零开销。

另提供 prune 的**批量 I/O 内核**（``scan_dir`` / ``delete_entries``）：``store`` 与
``ledger`` 两处过期清理共用同一实现，避免「只改一边」漂移；批量语义是性能前提——
万级文件下逐条 ``await asyncio.to_thread(path.stat)`` 的线程跳转成本远超 I/O 本身
（实测 .heagent/runs 2 万条目：逐条 4.8s → 批量 ~0.1s）。

``prune_entries_by_mtime`` 是**文件级产物**（sessions / logs / edit-snapshots）回收的唯一序列
（2026-09-15 内核化；此前三处各持一份逐字副本，任一处漏改即静默分叉）。store / ledger 的
多集合判定（记录 + 配套锁 + 产物目录）与 ``prune_sandbox_dirs`` 的目录判活语义不同，仍各自
实现——见该函数 docstring 的「不合并的兄弟实现」段。

顶层底层模块（与 types / config 同层；2026-09 自 ``engine/`` 迁出——彼时 5 个下层模块
反向导入 ``heagent.engine.persist``，形成 engine ↔ tools / memory 包级环），被
engine / tools / context / memory / cron / goal / housekeeping / 入口层共用。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import sys
import tempfile
import time
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
R = TypeVar("R")

# ── prune 的批量 I/O 内核（store / ledger 共用）───────────────────


@dataclass(frozen=True)
class DirEntry:
    """目录里的一个条目：路径 / mtime / 是否目录（prune 判定只需这些）。"""

    path: Path
    mtime: float
    is_dir: bool


def scan_dir(base: Path) -> list[DirEntry]:
    """一次 ``os.scandir`` 列出 ``base`` 下全部条目的 mtime（整批只占一次线程跳转）。

    为什么不用 ``base.glob()`` + 逐个 ``Path.stat()``：那是「每个文件一次
    ``await asyncio.to_thread``」，万级文件时线程跳转成为主要成本。``DirEntry.stat()``
    在多数平台上复用目录读取时已取得的 stat，整批只跳一次线程。

    单个条目出错（权限 / 读取过程中被删）只跳过该条目，不中断整批；``base`` 不存在时
    返回空列表（与「无过期项」等价）。
    """
    try:
        with os.scandir(base) as it:
            entries: list[DirEntry] = []
            for entry in it:
                try:
                    stat = entry.stat()
                except OSError:
                    logger.debug("scan_dir: stat failed on %s; skipping", entry.path, exc_info=True)
                    continue
                entries.append(DirEntry(Path(entry.path), stat.st_mtime, entry.is_dir()))
            return entries
    except OSError:
        logger.debug("scan_dir: cannot scan %s; treating as empty", base, exc_info=True)
        return []


def prune_stamp_path(base: Path, *, stamp_root: Path | None = None) -> Path:
    """prune 节流标记的路径：``<stamp_root 或 base 的父目录>/.<base 名>.prune-stamp``。

    默认放在被扫描目录**之外**（父目录），避免它出现在 prune 自己的扫描结果里、也不污染
    ``.heagent/runs/`` 这类会被外部工具 glob 的目录。``stamp_root`` 用于把标记收进
    ``.heagent/`` —— 工作区级目标（如 ``logs/``）的父目录就是仓库根，默认落点会在仓库根
    留下一个未跟踪文件（实测踩到：``git status`` 出现 ``.logs.prune-stamp``）。
    """
    root = stamp_root if stamp_root is not None else base.parent
    return root / f".{base.name}.prune-stamp"


def stamp_is_recent(path: Path, min_interval_seconds: int) -> bool:
    """标记文件是否在 ``min_interval_seconds`` 内被写过（``min_interval_seconds <= 0`` 恒 False）。

    标记缺失 / 读取失败一律视为「不新鲜」——宁可多做一次清理，也不要因坏标记永远不清理。
    """
    if min_interval_seconds <= 0:
        return False
    try:
        return (time.time() - path.stat().st_mtime) < min_interval_seconds
    except OSError:
        return False


def touch_prune_stamp(path: Path) -> None:
    """写/刷新节流标记；失败只记 ``debug``（节流是优化，坏掉不能影响 prune 本身）。"""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(time.time()), encoding="utf-8")
    except OSError:
        logger.debug("touch_prune_stamp: cannot write %s", path, exc_info=True)


def delete_entries(files: Sequence[Path], dirs: Sequence[Path]) -> tuple[int, int]:
    """批量删除文件与目录树，返回 ``(删除的文件数, 删除的目录数)``。

    单条失败（权限 / 竞态 / 目标是目录等）只记 ``debug`` 后继续——prune 是后台清理，
    不能因一条坏记录中断整批。整批只占一次线程跳转。
    """
    deleted_files = 0
    deleted_dirs = 0
    for path in files:
        try:
            path.unlink()
            deleted_files += 1
        except FileNotFoundError:
            logger.debug("delete_entries: %s already gone", path)
        except OSError:
            logger.debug("delete_entries: unlink failed on %s; continuing", path, exc_info=True)
    for path in dirs:
        try:
            shutil.rmtree(path, ignore_errors=False)
            deleted_dirs += 1
        except FileNotFoundError:
            logger.debug("delete_entries: %s already gone", path)
        except OSError:
            logger.debug("delete_entries: rmtree failed on %s; continuing", path, exc_info=True)
    return deleted_files, deleted_dirs


async def prune_entries_by_mtime(
    base: Path,
    *,
    retention_days: int,
    suffix: str | None = None,
    include_dirs: bool = False,
    min_interval_seconds: int = 0,
    stamp_root: Path | None = None,
) -> int:
    """按 mtime 回收 ``base`` 下的过期条目，返回删除数（``retention_days <= 0`` 时禁用）。

    这是「文件级产物回收」的唯一序列：守卫 → 跨进程节流 → **一次**批量扫描 → cutoff 判定
    → **一次**批量删除 → 打节流标记。sessions / logs / edit-snapshots 三类产物只差「后缀过滤」
    与「是否连目录一起删」，故共用本内核——2026-09-15 之前三者各持一份逐字副本，意味着
    :func:`scan_dir` 的批量 I/O 优化必须重复施加三次（且任一处漏改即静默分叉）。

    ``suffix=None`` 不过滤后缀；``include_dirs=True`` 时目录也按 mtime 参与回收（文件与目录
    各计 1）。符号链接不特殊处理（``scan_dir`` 的 ``is_dir()`` 跟随链接），与内核化前各实现
    逐字一致。``stamp_root`` 语义见 :func:`prune_stamp_path`。

    不合并的兄弟实现（语义确属不同，**不是**漏改）：``RunStore.prune`` / ``ExecutionLedger.prune``
    判定的是「记录 + 配套锁 + 产物目录」多集合（后者还要读 JSON 判终态），``prune_sandbox_dirs``
    判活要连带直接子项且拒绝穿透符号链接。
    """
    if retention_days <= 0:
        return 0
    stamp = prune_stamp_path(base, stamp_root=stamp_root)
    if await asyncio.to_thread(stamp_is_recent, stamp, min_interval_seconds):
        return 0
    entries = await asyncio.to_thread(scan_dir, base)
    cutoff = time.time() - retention_days * 86_400
    files = [
        e.path
        for e in entries
        if not e.is_dir and e.mtime < cutoff and (suffix is None or e.path.name.endswith(suffix))
    ]
    dirs = [e.path for e in entries if e.is_dir and e.mtime < cutoff] if include_dirs else []
    deleted_files, deleted_dirs = await asyncio.to_thread(delete_entries, files, dirs)
    await asyncio.to_thread(touch_prune_stamp, stamp)
    return deleted_files + deleted_dirs


# ── 平台自适应文件锁 ──────────────────────────────────────────────

_LOCK_POLL_INTERVAL = 0.1


def _acquire_lock_posix(fd: int, timeout: float) -> None:
    """POSIX ``fcntl.flock`` 排他锁。"""
    import fcntl

    fcntl_mod: Any = fcntl  # typeshed 在 win32 上无 flock 属性，统一走 Any 避免平台差异
    deadline = time.monotonic() + timeout
    while True:
        try:
            fcntl_mod.flock(fd, fcntl_mod.LOCK_EX | fcntl_mod.LOCK_NB)
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

    # 经 Any 访问：msvcrt 是 Windows 专属模块，Linux 平台（CI 的 mypy 跑在 Ubuntu）
    # typeshed 不暴露其属性——与 :func:`_release_lock_posix` 的 fcntl 同法。
    msvcrt_mod: Any = msvcrt

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
            msvcrt_mod.locking(fd, msvcrt_mod.LK_NBLCK, 1)
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

    fcntl_mod: Any = fcntl
    fcntl_mod.flock(fd, fcntl_mod.LOCK_UN)


def _release_lock_windows(fd: int) -> None:
    import msvcrt

    msvcrt_mod: Any = msvcrt  # Linux 平台下 typeshed 不暴露其属性（同 _acquire_lock_windows）
    try:
        msvcrt_mod.locking(fd, msvcrt_mod.LK_UNLCK, 1)
    except OSError:
        pass  # 文件可能已被关闭；静默忽略


def _release_lock(fd: int) -> None:
    """平台自适应释放锁。"""
    if sys.platform == "win32":
        _release_lock_windows(fd)
    else:
        _release_lock_posix(fd)


# ── 原子替换（Windows 读者兼容）──────────────────────────────────

_REPLACE_ATTEMPTS = 5
_REPLACE_BACKOFF = 0.02


def _is_windows_sharing_violation(exc: PermissionError) -> bool:
    """Return whether *exc* is a retryable Windows sharing/access conflict."""
    return sys.platform == "win32" and getattr(exc, "winerror", None) in {5, 32}


def _replace_with_retry(tmp: Path, path: Path) -> None:
    """Replace a same-directory temporary file, retrying transient Windows sharing conflicts."""
    for attempt in range(_REPLACE_ATTEMPTS):
        try:
            os.replace(tmp, path)
            return
        except PermissionError as exc:
            if not _is_windows_sharing_violation(exc) or attempt == _REPLACE_ATTEMPTS - 1:
                raise
            time.sleep(_REPLACE_BACKOFF * (attempt + 1))


def _write_temp_text(path: Path, text: str) -> Path:
    """Write text to a unique temporary sibling so concurrent writers cannot alias it."""
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent, text=True)
    tmp = Path(raw_tmp)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return tmp


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
    lock_path: Path | None = None

    if lock:
        lock_path = path.with_name(path.name + ".lock")
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
        try:
            _acquire_lock(lock_fd, lock_timeout)
        except BaseException:
            os.close(lock_fd)
            raise

    try:
        tmp = _write_temp_text(path, text)
        try:
            _replace_with_retry(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
    finally:
        if lock and lock_fd is not None:
            try:
                _release_lock(lock_fd)
            except Exception:
                logger.debug("Failed to release lock on %s", path, exc_info=True)
            finally:
                os.close(lock_fd)
                # 注意：刻意不删除 .lock 文件。删除锁文件存在经典竞态——进程 B 可能
                # 正在等待旧 inode 上的锁，进程 C 新建 .lock 并加锁成功，导致 B/C 的
                # 互斥失效。保留 0 字节锁文件换取跨进程互斥的正确性；过期 .lock 由各自的
                # prune 随记录一并回收（ledger → engine/ledger.py；runs → engine/store.py）。


def atomic_update_text(path: Path, update: Callable[[str], tuple[str, R]], *, lock_timeout: float = 5.0) -> R:
    """Read, update, and replace a text file while holding one cross-process lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    lock_path = path.with_name(path.name + ".lock")
    lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR)
    try:
        _acquire_lock(lock_fd, lock_timeout)
        try:
            current = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            current = ""
        replacement, result = update(current)
        tmp = _write_temp_text(path, replacement)
        try:
            _replace_with_retry(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)
        return result
    finally:
        try:
            _release_lock(lock_fd)
        finally:
            os.close(lock_fd)


@asynccontextmanager
async def file_lock(path: Path, *, timeout: float = 5.0) -> AsyncIterator[None]:
    """跨进程排他锁上下文管理器（平台自适应 flock / msvcrt.locking）。

    与 :func:`atomic_write_text(lock=True)` 的单文件写锁不同，本原语保护**一段**
    读改写临界区（如 goal 的「读 current 指针 → 推进 → 写 checkpoint / workflow.json /
    GOAL.md」）——per-file 锁覆盖不了「两个进程从同一状态各自推进后互相覆盖」的竞态。

    锁文件刻意保留不删（同 ``atomic_write_text`` 的 unlink 竞态论证）；advisory 锁随
    进程退出自动释放，crash 不留死锁。获取/释放经 ``asyncio.to_thread`` 卸载（内部
    锁轮询含 ``time.sleep``），不阻塞事件循环。超时抛 ``OSError``——显性失败，由调用方
    决定重试或放弃，不静默降级。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = await asyncio.to_thread(os.open, str(path), os.O_CREAT | os.O_RDWR)
    try:
        await asyncio.to_thread(_acquire_lock, fd, timeout)
    except BaseException:
        os.close(fd)
        raise
    try:
        yield
    finally:
        try:
            await asyncio.to_thread(_release_lock, fd)
        except Exception:
            logger.debug("Failed to release lock on %s", path, exc_info=True)
        finally:
            os.close(fd)


def load_json_model(path: Path, model_cls: type[T]) -> T | None:
    """容错读：``read_text`` → ``json.loads`` → ``model_cls.model_validate``。

    文件缺失（``FileNotFoundError``）静默返回 None——属正常情况（首次 acquire / 尚无记录），
    不计为错误。其余读 / 解析 / 校验失败（``OSError`` / ``ValueError`` / ``JSONDecodeError`` /
    ``ValidationError``）记 ``logger.error`` 并返回 None，不向调用方抛——单条坏记录不应
    中断整个 run。

    ``ValueError`` 覆盖 ``UnicodeDecodeError``（``read_text(encoding="utf-8")`` 在文件编码
    损坏时抛出），此前仅捕获 ``OSError`` 漏掉了该路径（P1-23）。
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        logger.error("Failed to read JSON from %s: %s", path, exc)
        return None
    try:
        return model_cls.model_validate(payload)
    except ValidationError as exc:
        logger.error("Failed to validate %s from %s: %s", model_cls.__name__, path, exc)
        return None
