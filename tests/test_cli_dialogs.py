"""``heagent.cli_dialogs`` 的单测：**假子进程**（绝不开真窗口）+ 后端选择 + 边界。

为什么假造子进程：真对话框需要图形后端与人工点击，CI 与本地自动化都不能依赖它。被测的**不是**
tkinter / PowerShell 本身，而是我们自己写的四条纪律——单在途、超时后 kill + 回收、只解析标记行、
脏值按取消、环境剥离凭证、argv 冻结且不经 shell。
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any

import pytest

from heagent import cli_dialogs
from heagent.cli_dialogs import (
    BACKENDS,
    DEFAULT_TIMEOUT_SECONDS,
    MARKER,
    DialogBusyError,
    DialogUnavailableError,
    DirectoryPicker,
    parse_marked_path,
    resolve_backend,
)


class FakeProcess:
    """最小子进程替身：记录 kill、可控 stdout、可选「永不返回」。"""

    def __init__(self, *, stdout: bytes = b"", returncode: int = 0, hang: bool = False) -> None:
        self._stdout = stdout
        self.returncode = returncode
        self.hang = hang
        self.killed = False
        self.communicate_calls = 0

    async def communicate(self) -> tuple[bytes, bytes]:
        self.communicate_calls += 1
        if self.hang and not self.killed:
            await asyncio.sleep(3600)  # 被 wait_for 取消；kill 之后立即返回
        return self._stdout, b""

    def kill(self) -> None:
        self.killed = True


class FakeSpawner:
    """``cli_dialogs._spawn`` 的替身：记录 argv / script，可注入失败。"""

    def __init__(self, proc: FakeProcess | None = None, *, error: OSError | None = None) -> None:
        self.proc = proc if proc is not None else FakeProcess()
        self.error = error
        self.calls: list[tuple[list[str], str]] = []

    async def __call__(self, argv: list[str], script: str) -> FakeProcess:
        self.calls.append((list(argv), script))
        if self.error is not None:
            raise self.error
        return self.proc


@pytest.fixture
def tkinter_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """把「本机有 tkinter」钉成前提（后端选择的结果因此与运行测试的机器无关）。"""
    monkeypatch.setattr(cli_dialogs, "_tkinter_available", lambda: True)


@pytest.fixture
def spawned(monkeypatch: pytest.MonkeyPatch) -> FakeSpawner:
    """默认的假 spawn 缝（各用例可按需替换 ``.proc`` / ``.error``）。"""
    spawner = FakeSpawner()
    monkeypatch.setattr(cli_dialogs, "_spawn", spawner)
    return spawner


class TestResolveBackend:
    def test_auto_prefers_tkinter(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cli_dialogs, "_tkinter_available", lambda: True)
        monkeypatch.setattr(cli_dialogs, "_powershell_path", lambda: "powershell.exe")
        assert resolve_backend("auto") == "tkinter"

    def test_auto_falls_back_to_powershell(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cli_dialogs, "_tkinter_available", lambda: False)
        monkeypatch.setattr(cli_dialogs, "_powershell_path", lambda: "powershell.exe")
        assert resolve_backend("auto") == "powershell"

    def test_auto_without_any_backend_is_unavailable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cli_dialogs, "_tkinter_available", lambda: False)
        monkeypatch.setattr(cli_dialogs, "_powershell_path", lambda: None)
        with pytest.raises(DialogUnavailableError, match="no native directory dialog backend"):
            resolve_backend("auto")

    def test_none_backend_is_explicitly_unavailable(self) -> None:
        with pytest.raises(DialogUnavailableError, match="disabled"):
            resolve_backend("none")

    def test_explicit_tkinter_requires_it_to_be_importable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cli_dialogs, "_tkinter_available", lambda: False)
        with pytest.raises(DialogUnavailableError, match="tkinter is not available"):
            resolve_backend("tkinter")

    def test_explicit_powershell_requires_it_on_the_machine(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cli_dialogs, "_powershell_path", lambda: None)
        with pytest.raises(DialogUnavailableError, match="PowerShell is not available"):
            resolve_backend("powershell")

    def test_unknown_backend_is_a_programming_error(self) -> None:
        with pytest.raises(ValueError, match="unknown dialog backend"):
            resolve_backend("gtedit")

    def test_picker_rejects_unknown_backend_at_construction(self) -> None:
        with pytest.raises(ValueError, match="unknown dialog backend"):
            DirectoryPicker("nope")


class TestParseMarkedPath:
    def test_marker_line_yields_the_directory(self, tmp_path: Path) -> None:
        assert parse_marked_path(f"noise\n{MARKER}{tmp_path}\n".encode()) == str(tmp_path)

    def test_last_marker_line_wins(self, tmp_path: Path) -> None:
        other = tmp_path / "other"
        other.mkdir()
        assert parse_marked_path(f"{MARKER}{tmp_path}\n{MARKER}{other}\n".encode()) == str(other)

    def test_no_marker_means_cancelled(self) -> None:
        assert parse_marked_path(b"anything\n") is None

    def test_empty_payload_after_marker_means_cancelled(self) -> None:
        assert parse_marked_path(f"{MARKER}\n".encode()) is None

    def test_file_instead_of_directory_is_cancelled(self, tmp_path: Path) -> None:
        target = tmp_path / "file.txt"
        target.write_text("x", encoding="utf-8")
        assert parse_marked_path(f"{MARKER}{target}\n".encode()) is None

    def test_nonexistent_path_is_cancelled(self, tmp_path: Path) -> None:
        assert parse_marked_path(f"{MARKER}{tmp_path / 'ghost'}\n".encode()) is None

    def test_non_utf8_bytes_do_not_raise(self) -> None:
        assert parse_marked_path(b"\xff\xfe not utf-8\n") is None


class TestSpawnDiscipline:
    def test_kwargs_are_pipe_only_and_never_use_shell(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("HEAGENT_STORY58_API_KEY", "secret-value")
        monkeypatch.setenv("HEAGENT_STORY58_TOKEN", "secret-value")
        kwargs = cli_dialogs._spawn_kwargs()
        assert kwargs["stdout"] is asyncio.subprocess.PIPE
        assert kwargs["stderr"] is asyncio.subprocess.PIPE
        assert "shell" not in kwargs, "绝不能经 shell 拉起（没有 shell 键）"
        env = kwargs["env"]
        assert "HEAGENT_STORY58_API_KEY" not in env
        assert "HEAGENT_STORY58_TOKEN" not in env
        assert env["PYTHONIOENCODING"] == "utf-8"

    def test_tkinter_argv_is_the_frozen_script(self, tkinter_ok: None) -> None:
        argv, script = cli_dialogs._command_for("tkinter")
        assert argv == [sys.executable, "-c"]
        assert script == cli_dialogs._TK_SCRIPT

    def test_powershell_argv_is_frozen_and_non_interactive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(cli_dialogs, "_powershell_path", lambda: "powershell.exe")
        argv, script = cli_dialogs._command_for("powershell")
        assert argv == ["powershell.exe", "-NoProfile", "-NonInteractive", "-STA", "-Command"]
        assert script == cli_dialogs._POWERSHELL_SCRIPT

    def test_scripts_print_the_same_ascii_marker(self) -> None:
        assert MARKER.isascii()
        for script in (cli_dialogs._TK_SCRIPT, cli_dialogs._POWERSHELL_SCRIPT):
            assert MARKER in script
            assert script.count(cli_dialogs._TITLE) == 1  # 唯一的插值就是固定标题

    def test_frozen_scripts_are_valid_python_syntax(self) -> None:
        """冻结脚本**永不在 CI 里执行**（CI 的 Linux 镜像可能根本没有 ``tkinter``），
        所以这里只编译不执行——钉住「它至少是个能编译的脚本」，免得拼错只能靠人工发现。"""
        compile(cli_dialogs._TK_SCRIPT, "<heagent-dialog-script>", "exec")


class TestDirectoryPicker:
    async def test_pick_returns_path_from_backend(
        self, spawned: FakeSpawner, tmp_path: Path, tkinter_ok: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(cli_dialogs, "_spawn", spawned)
        spawned.proc = FakeProcess(stdout=f"{MARKER}{tmp_path}\n".encode())
        assert await DirectoryPicker("auto").pick() == str(tmp_path)

    async def test_cancel_returns_none(self, spawned: FakeSpawner, tkinter_ok: None) -> None:
        assert await DirectoryPicker("auto").pick() is None

    async def test_nonzero_exit_is_unavailable_not_cancel(self, spawned: FakeSpawner, tkinter_ok: None) -> None:
        """后端自身失败**不能**伪装成「用户取消」——UI 要能说出原因。"""
        spawned.proc = FakeProcess(returncode=2)
        with pytest.raises(DialogUnavailableError, match="exited with status 2"):
            await DirectoryPicker("auto").pick()

    async def test_spawn_failure_is_unavailable(self, monkeypatch: pytest.MonkeyPatch, tkinter_ok: None) -> None:
        monkeypatch.setattr(cli_dialogs, "_spawn", FakeSpawner(error=OSError("no such executable")))
        with pytest.raises(DialogUnavailableError, match="could not start"):
            await DirectoryPicker("auto").pick()

    async def test_timeout_kills_the_child_and_cancels(self, spawned: FakeSpawner, tkinter_ok: None) -> None:
        spawned.proc = FakeProcess(hang=True)
        picker = DirectoryPicker("auto", timeout=0.05)
        assert await picker.pick() is None
        assert spawned.proc.killed is True, "超时必须终止子进程，否则会留下孤儿窗口"
        assert picker.in_flight is False

    async def test_cancellation_kills_the_child_and_releases(self, spawned: FakeSpawner, tkinter_ok: None) -> None:
        """外层取消同样要 kill + 归还名额（两条清理路径一致，否则留下孤儿窗口）。"""
        spawned.proc = FakeProcess(hang=True)
        picker = DirectoryPicker("auto", timeout=30.0)
        task = asyncio.create_task(picker.pick())
        await asyncio.sleep(0.02)
        assert picker.in_flight is True
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert spawned.proc.killed is True
        assert picker.in_flight is False

    async def test_busy_while_another_pick_is_in_flight(self, spawned: FakeSpawner, tkinter_ok: None) -> None:
        spawned.proc = FakeProcess(hang=True)
        picker = DirectoryPicker("auto", timeout=0.2)
        first = asyncio.create_task(picker.pick())
        await asyncio.sleep(0.02)  # 等第一个真的进入在途再断言
        assert picker.in_flight is True
        with pytest.raises(DialogBusyError, match="already open"):
            await picker.pick()
        assert await first is None  # 超时收尾
        assert picker.in_flight is False
        assert spawned.proc.killed is True

    async def test_in_flight_is_released_after_success(
        self, spawned: FakeSpawner, tmp_path: Path, tkinter_ok: None
    ) -> None:
        spawned.proc = FakeProcess(stdout=f"{MARKER}{tmp_path}\n".encode())
        picker = DirectoryPicker("auto")
        await picker.pick()
        await picker.pick()  # 第二次仍可（名额已归还）
        assert len(spawned.calls) == 2

    async def test_pick_uses_the_selected_backend_script(self, spawned: FakeSpawner, tkinter_ok: None) -> None:
        await DirectoryPicker("auto").pick()
        argv, script = spawned.calls[0]
        assert argv[0] == sys.executable
        assert script == cli_dialogs._TK_SCRIPT

    async def test_none_backend_never_spawns(self, spawned: FakeSpawner) -> None:
        with pytest.raises(DialogUnavailableError):
            await DirectoryPicker("none").pick()
        assert spawned.calls == []

    def test_defaults_and_backend_names(self) -> None:
        assert DEFAULT_TIMEOUT_SECONDS == 300.0
        assert DirectoryPicker("auto").backend == "auto"
        assert set(BACKENDS) == {"auto", "tkinter", "powershell", "none"}
