"""``engine/persist.py`` 原子写的平台回归：Windows 读者占用重试。

发现背景（2026-09-14）：CI 的 test 矩阵在 windows-latest 上偶发
``[WinError 5] 拒绝访问。: 'SKILL.md.tmp' -> 'SKILL.md'``，导致并行子代理个别失败。
根因是 Windows ``open`` 不共享删除权限（无 ``FILE_SHARE_DELETE``）：同进程内另一个
线程只要持有目标文件的读句柄，``os.replace`` 就会以 ``PermissionError`` 失败。
实测 3 个持续读文件的线程可让 300 次替换中的 288 次失败。
"""

from __future__ import annotations

import os
import sys
import threading
import time
import types
from pathlib import Path

import pytest

from heagent import persist


def _fake_msvcrt() -> types.ModuleType:
    """最小 ``msvcrt`` 替身，供在 POSIX 上模拟 Windows 的测试使用。

    ``persist._acquire_lock_windows`` 里 ``import msvcrt`` 是**真导入**；POSIX 上无此模块，
    不注入替身就会 ``ModuleNotFoundError``（测不到被测的替换重试语义，而是直接报错）。
    """
    mod = types.ModuleType("msvcrt")
    mod.LK_NBLCK = 1
    mod.LK_UNLCK = 2
    mod.locking = lambda fd, mode, nbytes: None  # noqa: ARG005 - 替身只需可调用
    return mod


def _fake_windows(monkeypatch: pytest.MonkeyPatch) -> None:
    """把当前测试伪装成 Windows 进程：平台钉 + ``msvcrt`` 替身。

    平台钉让 ``persist`` 走 Windows 分支（共享冲突重试语义）；``msvcrt`` 替身使该分支在
    POSIX 上也能跑完加锁/解锁——否则 CI 的 linux/macOS 矩阵必失败（仅 Windows 能过）。
    """
    monkeypatch.setattr(persist.sys, "platform", "win32")
    monkeypatch.setitem(sys.modules, "msvcrt", _fake_msvcrt())


def _permission_error(tmp: Path, target: Path) -> PermissionError:
    exc = PermissionError(13, "拒绝访问。", str(tmp), str(target))
    exc.winerror = 5
    return exc


class TestReplaceRetry:
    """重试语义：瞬时占用可恢复，持久失败与其它错误不吞。"""

    def test_write_retries_transient_sharing_violation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _fake_windows(monkeypatch)
        target = tmp_path / "SKILL.md"
        real_replace = os.replace
        attempts: list[int] = []

        def flaky_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
            attempts.append(1)
            if len(attempts) <= 2:
                raise _permission_error(Path(src), Path(dst))
            real_replace(src, dst)

        monkeypatch.setattr(persist.os, "replace", flaky_replace)
        persist.atomic_write_text(target, "payload")

        assert target.read_text(encoding="utf-8") == "payload"
        assert len(attempts) == 3  # 两次被占用 + 一次成功

    def test_update_retries_transient_sharing_violation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        _fake_windows(monkeypatch)
        target = tmp_path / "SKILL.md"
        target.write_text("count=1\n", encoding="utf-8")
        real_replace = os.replace
        attempts: list[int] = []

        def flaky_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
            attempts.append(1)
            if len(attempts) == 1:
                raise _permission_error(Path(src), Path(dst))
            real_replace(src, dst)

        monkeypatch.setattr(persist.os, "replace", flaky_replace)
        result = persist.atomic_update_text(target, lambda raw: (raw.replace("1", "2"), "updated"))

        assert result == "updated"
        assert target.read_text(encoding="utf-8") == "count=2\n"
        assert len(attempts) == 2

    def test_persistent_occupation_fails_visibly(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """持续占用不静默吞错：按次数重试后仍抛出最后一次异常。"""
        _fake_windows(monkeypatch)
        target = tmp_path / "SKILL.md"
        attempts: list[int] = []

        def always_busy(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
            attempts.append(1)
            raise _permission_error(Path(src), Path(dst))

        monkeypatch.setattr(persist.os, "replace", always_busy)
        with pytest.raises(PermissionError):
            persist.atomic_write_text(target, "payload")

        assert len(attempts) == persist._REPLACE_ATTEMPTS

    def test_non_windows_permission_errors_are_not_retried(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "SKILL.md"
        attempts: list[int] = []

        def denied(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
            attempts.append(1)
            raise PermissionError(13, "Permission denied", str(src), str(dst))

        monkeypatch.setattr(persist.os, "replace", denied)
        with pytest.raises(PermissionError):
            persist.atomic_write_text(target, "payload")

        assert len(attempts) == 1

    def test_other_os_errors_are_not_retried(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """非占用类 ``OSError``（如磁盘满）立即上抛，不做无意义重试。"""
        target = tmp_path / "SKILL.md"
        attempts: list[int] = []

        def full_disk(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
            attempts.append(1)
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(persist.os, "replace", full_disk)
        with pytest.raises(OSError, match="No space left"):
            persist.atomic_write_text(target, "payload")

        assert len(attempts) == 1


class TestTemporaryFiles:
    def test_failed_replace_cleans_its_unique_temporary_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _fake_windows(monkeypatch)
        target = tmp_path / "SKILL.md"

        def always_busy(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
            raise _permission_error(Path(src), Path(dst))

        monkeypatch.setattr(persist.os, "replace", always_busy)
        with pytest.raises(PermissionError):
            persist.atomic_write_text(target, "payload")

        assert list(tmp_path.glob(".*.tmp")) == []

    def test_concurrent_writers_use_distinct_temporary_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = tmp_path / "SKILL.md"
        real_replace = os.replace
        first_replace = threading.Event()
        release_first = threading.Event()
        seen_sources: list[Path] = []

        def delayed_replace(src: str | os.PathLike[str], dst: str | os.PathLike[str]) -> None:
            seen_sources.append(Path(src))
            if len(seen_sources) == 1:
                first_replace.set()
                assert release_first.wait(timeout=5)
            real_replace(src, dst)

        monkeypatch.setattr(persist.os, "replace", delayed_replace)
        first = threading.Thread(target=persist.atomic_write_text, args=(target, "first"))
        first.start()
        assert first_replace.wait(timeout=5)
        second = threading.Thread(target=persist.atomic_write_text, args=(target, "second"))
        second.start()
        second.join(timeout=5)
        release_first.set()
        first.join(timeout=5)

        assert not first.is_alive() and not second.is_alive()
        assert len(set(seen_sources)) == 2
        assert target.read_text(encoding="utf-8") in {"first", "second"}


@pytest.mark.skipif(sys.platform != "win32", reason="Windows reader sharing is platform-specific")
class TestWindowsReaderSharingRegression:
    def test_brief_reader_occupation_is_retried(self, tmp_path: Path) -> None:
        target = tmp_path / "SKILL.md"
        target.write_text("seed\n", encoding="utf-8")
        opened = threading.Event()
        release = threading.Event()
        writer_error: list[BaseException] = []

        def reader() -> None:
            with target.open("r", encoding="utf-8"):
                opened.set()
                assert release.wait(timeout=5)

        def writer() -> None:
            try:
                persist.atomic_write_text(target, "payload\n")
            except BaseException as exc:
                writer_error.append(exc)

        reader_thread = threading.Thread(target=reader)
        reader_thread.start()
        assert opened.wait(timeout=5)
        writer_thread = threading.Thread(target=writer)
        writer_thread.start()
        time.sleep(persist._REPLACE_BACKOFF * 1.5)
        release.set()
        reader_thread.join(timeout=5)
        writer_thread.join(timeout=5)

        assert not reader_thread.is_alive() and not writer_thread.is_alive()
        assert writer_error == []
        assert target.read_text(encoding="utf-8") == "payload\n"


class TestAtomicUpdateBytes:
    """``atomic_update_bytes``（Story 50-5）：字节级读改写 + 锁内回读校验 + 回滚。"""

    def test_missing_file_is_reported_as_none_and_created(self, tmp_path: Path) -> None:
        path = tmp_path / ".env"
        seen: list[bytes | None] = []

        def update(current: bytes | None) -> tuple[bytes, int]:
            seen.append(current)
            return b"A=1\n", 7

        assert persist.atomic_update_bytes(path, update) == 7
        assert seen == [None]  # 文本版会把「不存在」折叠成 ""，字节版必须能区分
        assert path.read_bytes() == b"A=1\n"

    def test_bytes_are_written_verbatim_without_newline_translation(self, tmp_path: Path) -> None:
        """文本模式会做行尾翻译；字节版必须原样落盘（这正是保真写的前提）。"""
        path = tmp_path / ".env"
        persist.atomic_update_bytes(path, lambda current: (b"A=1\r\nB=2\n", None))

        assert path.read_bytes() == b"A=1\r\nB=2\n"

    def test_update_failure_leaves_the_file_untouched(self, tmp_path: Path) -> None:
        path = tmp_path / ".env"
        path.write_bytes(b"A=1\n")

        def boom(current: bytes | None) -> tuple[bytes, None]:
            raise RuntimeError("nope")

        with pytest.raises(RuntimeError):
            persist.atomic_update_bytes(path, boom)

        assert path.read_bytes() == b"A=1\n"

    def test_verify_failure_restores_the_previous_content(self, tmp_path: Path) -> None:
        path = tmp_path / ".env"
        path.write_bytes(b"A=1\n")

        def reject(written: bytes) -> None:
            raise RuntimeError(f"not what I expected: {written!r}")

        with pytest.raises(RuntimeError, match="not what I expected"):
            persist.atomic_update_bytes(path, lambda current: (b"A=2\n", None), verify=reject)

        assert path.read_bytes() == b"A=1\n"  # 已还原

    def test_verify_failure_removes_a_newly_created_file(self, tmp_path: Path) -> None:
        path = tmp_path / ".env"

        def reject(written: bytes) -> None:
            raise RuntimeError("nope")

        with pytest.raises(RuntimeError):
            persist.atomic_update_bytes(path, lambda current: (b"A=2\n", None), verify=reject)

        assert not path.exists()

    def test_verify_sees_the_written_bytes_and_can_read_them_back(self, tmp_path: Path) -> None:
        path = tmp_path / ".env"
        observed: list[bytes] = []

        def verify(written: bytes) -> None:
            observed.append(written)
            assert path.read_bytes() == written  # 校验发生在锁内、替换之后

        persist.atomic_update_bytes(path, lambda current: (b"A=9\n", None), verify=verify)

        assert observed == [b"A=9\n"]

    @pytest.mark.skipif(os.name != "posix", reason="Windows 无 POSIX 模式位（ACL 随目录继承）")
    def test_posix_mode_is_preserved(self, tmp_path: Path) -> None:
        path = tmp_path / ".env"
        path.write_bytes(b"A=1\n")
        os.chmod(path, 0o600)

        persist.atomic_update_bytes(path, lambda current: (b"A=2\n", None))

        assert os.stat(path).st_mode & 0o777 == 0o600  # mkstemp 的 0600 不能反向覆盖用户原有的模式
        os.chmod(path, 0o644)
        persist.atomic_update_bytes(path, lambda current: (b"A=3\n", None))
        assert os.stat(path).st_mode & 0o777 == 0o644

    def test_atomic_write_bytes_creates_a_new_file(self, tmp_path: Path) -> None:
        path = tmp_path / "sub" / ".env"

        persist.atomic_write_bytes(path, b"A=1\r\n")

        assert path.read_bytes() == b"A=1\r\n"
