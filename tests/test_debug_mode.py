"""调试模式（`DEBUG_MODE`）判据：设置面 + 两个行为面（日志级别、错误 traceback）。

票面 verify 是「输出完整堆栈追踪与中间变量，可经环境变量启用」。两句各有一个判据：

- **中间变量** → 日志级别被强制到 `DEBUG`（既有插桩里有大量 `logger.debug` 的入参/中间量），
  判据是装配后的 root level 与两个 handler 的 level；`LOG_LEVEL=INFO` 也压不过它。
- **完整堆栈追踪** → CLI 错误出口（`cli/errors.with_hints` 及其 family）在调试模式下追加
  `Traceback (DEBUG_MODE=true):` 段；**默认不追加**（既有错误块形状是契约，测试逐字断言）。
"""

from __future__ import annotations

import logging

import pytest

from heagent.cli.errors import TRACEBACK_HEADER, with_hints
from heagent.config import Settings, get_settings, reset_settings


@pytest.fixture
def settings_isolated(monkeypatch: pytest.MonkeyPatch):
    """每个用例前后重置 Settings 缓存，避免 debug 开关泄漏到别的用例。"""
    reset_settings()
    try:
        yield monkeypatch
    finally:
        monkeypatch.delenv("DEBUG_MODE", raising=False)
        reset_settings()


@pytest.fixture
def root_logging_restored():
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    yield
    for handler in root.handlers[:]:
        if handler not in saved_handlers:
            handler.close()
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)


# ---------------------------------------------------------------- 设置面


def test_debug_mode_defaults_to_off() -> None:
    """默认关闭：调试模式是 opt-in，不给生产环境凭空多出 traceback 与 DEBUG 噪声。"""
    assert Settings().debug_mode is False


def test_debug_mode_reads_the_environment(settings_isolated: pytest.MonkeyPatch) -> None:
    settings_isolated.setenv("DEBUG_MODE", "true")
    assert get_settings().debug_mode is True


# ---------------------------------------------------------------- 错误出口


def test_error_block_is_unchanged_when_debug_mode_is_off() -> None:
    """默认（关闭）时错误块逐字不变——三段块形状是既有契约。"""
    rendered = with_hints("boom", options=["do this"])
    assert TRACEBACK_HEADER not in rendered
    assert rendered == "boom\n  Try:\n    - do this\n  Docs: docs/errors.md"


def test_error_block_carries_traceback_when_debug_mode_is_on(settings_isolated: pytest.MonkeyPatch) -> None:
    """开启时在既有三段之后追加 traceback 段，且仍以 traceback 收尾（顺序固定）。"""
    settings_isolated.setenv("DEBUG_MODE", "true")
    reset_settings()
    try:
        raise ValueError("boom-debug")
    except ValueError:
        rendered = with_hints("boom", options=["do this"])
    assert "  Try:\n    - do this\n  Docs: docs/errors.md\n" in rendered
    assert rendered.rstrip().splitlines()[0] == "boom"
    tail = rendered[rendered.index(TRACEBACK_HEADER) :]
    assert "ValueError: boom-debug" in tail
    assert "Traceback (most recent call last)" in tail
    assert rendered.rstrip().splitlines()[-1].strip() == "ValueError: boom-debug"


def test_no_traceback_section_outside_an_exception(settings_isolated: pytest.MonkeyPatch) -> None:
    """调试模式开着但没有异常在飞时，不产出 `NoneType: None` 这类假 traceback。"""
    settings_isolated.setenv("DEBUG_MODE", "true")
    reset_settings()
    rendered = with_hints("boom", options=["do this"])
    assert TRACEBACK_HEADER not in rendered


# ---------------------------------------------------------------- 日志级别


def _setup_logging_with(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    from heagent.cli.console import _setup_logging

    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    reset_settings()
    _setup_logging()


def test_debug_mode_forces_debug_level(tmp_path, settings_isolated: pytest.MonkeyPatch, root_logging_restored) -> None:
    """`LOG_LEVEL=INFO` + `DEBUG_MODE=true` ⇒ 两个 handler 都是 DEBUG（调试模式压过级别设置）。"""
    settings_isolated.setenv("LOG_LEVEL", "INFO")
    settings_isolated.setenv("DEBUG_MODE", "true")
    try:
        _setup_logging_with(tmp_path, settings_isolated)
        assert logging.getLogger().level == logging.DEBUG
        assert [handler.level for handler in logging.getLogger().handlers] == [logging.DEBUG, logging.DEBUG]
    finally:
        settings_isolated.delenv("LOG_LEVEL", raising=False)
        settings_isolated.delenv("LOG_DIR", raising=False)


def test_level_setting_is_honoured_without_debug_mode(
    tmp_path, settings_isolated: pytest.MonkeyPatch, root_logging_restored
) -> None:
    """未开调试模式时 `LOG_LEVEL` 照常生效（调试模式不是唯一入口）。"""
    settings_isolated.setenv("LOG_LEVEL", "WARNING")
    try:
        _setup_logging_with(tmp_path, settings_isolated)
        assert logging.getLogger().level == logging.WARNING
    finally:
        settings_isolated.delenv("LOG_LEVEL", raising=False)
        settings_isolated.delenv("LOG_DIR", raising=False)
