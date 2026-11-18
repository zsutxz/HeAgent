"""大文件读写进度契约：阈值、四要素、分块字节等价、既有语义不变、成本上界。

大文件在 ``tmp_path`` 现造（12 MB），无网络、无真实 API；时间断言只给宽松上界，避免 flaky。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import pytest

from heagent.cli.progress import FileProgressBridge, FileProgressSample, format_file_progress
from heagent.tools.builtins.file import (
    _FILE_READ_MAX_BYTES,
    FILE_PROGRESS_CHUNK_BYTES,
    FILE_PROGRESS_MIN_BYTES,
    _FILE_PROGRESS,
    _read_bytes_bounded,
    _read_text_bounded,
    file_progress,
    file_read,
    file_write,
)
from heagent.tools.path_safety import reset_workspace_root, set_workspace_root

if TYPE_CHECKING:
    from collections.abc import Generator
    from pathlib import Path

MB = 1024 * 1024
BIG = 12 * MB


@pytest.fixture(autouse=True)
def _workspace(tmp_path: Path) -> Generator[None, None, None]:
    set_workspace_root(tmp_path.resolve())
    yield
    reset_workspace_root()


@pytest.fixture
def reports() -> list[tuple[int, int]]:
    return []


@pytest.fixture
def big_text(tmp_path: Path) -> Path:
    path = tmp_path / "big.txt"
    path.write_bytes(b"a" * BIG)
    return path


class _Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def _recorder(sink: list[tuple[int, int]]):
    def report(processed: int, total: int) -> None:
        sink.append((processed, total))

    return report


# ── 阈值 ──────────────────────────────────────────────────────────────────


async def test_small_file_read_reports_nothing(tmp_path: Path, reports: list[tuple[int, int]]) -> None:
    """≤10 MB 的文件读写不显示进度：零回调。"""
    (tmp_path / "small.txt").write_bytes(b"x" * MB)
    with file_progress(_recorder(reports)):
        assert await file_read("small.txt") == "x" * MB
    assert reports == []


async def test_small_file_write_reports_nothing(tmp_path: Path, reports: list[tuple[int, int]]) -> None:
    with file_progress(_recorder(reports)):
        receipt = await file_write("small.txt", "hello\n")
    assert reports == []
    assert receipt.startswith("OK: wrote small.txt (6 chars)")
    assert (tmp_path / "small.txt").read_bytes() == b"hello\n"


def test_unbound_reporter_is_none(tmp_path: Path) -> None:
    """上报器只做上下文内绑定，不污染进程默认值。"""
    assert _FILE_PROGRESS.get() is None
    recorder = _recorder([])
    with file_progress(recorder):
        assert _FILE_PROGRESS.get() is recorder
    assert _FILE_PROGRESS.get() is None


# ── 上报内容 ──────────────────────────────────────────────────────────────


async def test_large_file_read_reports_monotonic_progress(big_text: Path, reports: list[tuple[int, int]]) -> None:
    """>10 MB 的读按块上报；总量恒为计划读取量，末次上报到 100%。"""
    with file_progress(_recorder(reports)):
        text = await file_read("big.txt")

    planned = min(BIG, _FILE_READ_MAX_BYTES)
    assert len(reports) >= 2
    assert {total for _, total in reports} == {planned}
    processed = [p for p, _ in reports]
    assert processed == sorted(processed)
    assert processed[-1] == planned
    # 既有语义逐字不变：超上限仍附同一句截断尾注
    assert text.endswith("(truncated — file exceeds the 10 MB read cap; use offset/limit to read later lines)")


async def test_large_file_write_reports_progress_and_writes_identical_bytes(
    tmp_path: Path, reports: list[tuple[int, int]]
) -> None:
    content = "x" * BIG
    payload = content.encode("utf-8")
    with file_progress(_recorder(reports)):
        receipt = await file_write("big_out.txt", content)

    assert receipt.startswith("OK: wrote big_out.txt")
    assert (tmp_path / "big_out.txt").read_bytes() == payload
    assert {total for _, total in reports} == {len(payload)}
    assert reports[-1] == (len(payload), len(payload))
    assert [p for p, _ in reports] == sorted(p for p, _ in reports)


async def test_empty_write_creates_empty_file(tmp_path: Path) -> None:
    """空内容没有分块循环：仍须建出空文件（与旧 ``write_bytes(b"")`` 等价）。"""
    receipt = await file_write("empty.txt", "")
    assert receipt.startswith("OK: wrote empty.txt (0 chars)")
    assert (tmp_path / "empty.txt").read_bytes() == b""


# ── 分块字节等价 ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "size",
    [0, 1, FILE_PROGRESS_CHUNK_BYTES - 1, FILE_PROGRESS_CHUNK_BYTES, FILE_PROGRESS_CHUNK_BYTES + 1, 3 * MB + 7],
)
def test_chunked_read_matches_single_read(tmp_path: Path, size: int) -> None:
    """分块读与一次 ``read(cap + 1)`` 返回完全相同的字节（含恰好落在块边界的长度）。"""
    path = tmp_path / "payload.bin"
    path.write_bytes(bytes(range(256)) * (size // 256) + bytes(range(size % 256)))
    cap = 3 * MB
    with path.open("rb") as fh:
        expected = fh.read(cap + 1)

    raw, truncated = _read_bytes_bounded(path, cap)
    assert raw == expected
    assert truncated is (size > cap)


def test_chunked_read_matches_single_read_on_big_file(big_text: Path) -> None:
    cap = _FILE_READ_MAX_BYTES
    with big_text.open("rb") as fh:
        expected = fh.read(cap + 1)
    raw, truncated = _read_bytes_bounded(big_text, cap)
    assert raw == expected
    assert truncated is True


def test_big_file_text_form_matches_whole_read(big_text: Path) -> None:
    """``_read_text_bounded`` 的文本形态与改动前一致：截断到上限、行尾归一、去 BOM 语义不变。"""
    text, truncated = _read_text_bounded(big_text)
    assert truncated is True
    assert text == "a" * _FILE_READ_MAX_BYTES


def test_thresholds_are_module_constants() -> None:
    assert FILE_PROGRESS_MIN_BYTES == 10 * MB
    assert FILE_PROGRESS_CHUNK_BYTES <= FILE_PROGRESS_MIN_BYTES


# ── 渲染四要素 ────────────────────────────────────────────────────────────


def test_format_file_progress_has_four_elements() -> None:
    sample = FileProgressSample(processed=5 * MB, total=10 * MB, started_at=0.0)
    assert format_file_progress(sample, now=2.0) == "5.0 MB/10.0 MB 50% · 约剩 2.0s"


def test_format_file_progress_reports_completion() -> None:
    sample = FileProgressSample(processed=MB, total=MB, started_at=0.0)
    line = format_file_progress(sample, now=1.0)
    assert "100%" in line
    assert "已完成" in line


def test_bridge_keeps_start_time_per_operation_and_resets_on_new_one() -> None:
    clock = _Clock()
    bridge = FileProgressBridge(clock)
    bridge.report(MB, 10 * MB)
    started = bridge.sample.started_at if bridge.sample is not None else None
    assert started == 0.0

    clock.now = 5.0
    bridge.report(2 * MB, 10 * MB)
    assert bridge.sample is not None
    assert bridge.sample.started_at == started  # 同一操作沿用起始时刻
    assert bridge.fragment(5.0).startswith("2.0 MB/10.0 MB 20%")

    clock.now = 9.0
    bridge.report(0, 4 * MB)  # 总量变了 ⇒ 视为新操作
    assert bridge.sample.started_at == 9.0

    bridge.reset()
    assert bridge.fragment(10.0) == ""


# ── 成本上界 ──────────────────────────────────────────────────────────────


def test_progress_does_not_double_read_cost(tmp_path: Path) -> None:
    """进度开启相对关闭的读耗时差异有上界（页缓存预热后比较，宽松上界防 flaky）。"""
    path = tmp_path / "perf.txt"
    path.write_bytes(b"a" * (11 * MB))
    _read_text_bounded(path)  # 预热页缓存

    start = time.perf_counter()
    _read_text_bounded(path)
    baseline = time.perf_counter() - start

    calls: list[int] = []

    def report(processed: int, total: int) -> None:
        calls.append(processed)

    start = time.perf_counter()
    with file_progress(report):
        _read_text_bounded(path)
    with_progress = time.perf_counter() - start

    assert calls
    assert with_progress <= baseline * 3 + 0.1
