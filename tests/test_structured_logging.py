"""结构化日志（`LOG_FORMAT`）判据：格式渲染 + 设置面 + 三个入口的装配。

三类断言：

- **渲染**：json 行必须是**可 `json.loads` 的单行**，含 `timestamp` / `level` / `logger` / `message`，
  `extra=` 注入落 `context`，异常落 `exc_info`；text 行必须与历史格式**逐字同形**
  （`runtime_stats` 等消费方按行正则解析，形状一变就是静默失采）。
- **设置面**：`LOG_FORMAT` 只接受 `text` / `json`，非法值在加载时炸（`Literal` 校验），
  不静默回落——「我明明配了 json」不该只在排障时才被发现。
- **装配**：`_setup_logging()` 真的按设置值选 formatter（而不是只在单测里渲染得漂亮）。
"""

from __future__ import annotations

import json
import logging
import re
import sys

import pytest
from pydantic import ValidationError

from heagent.config import Settings, get_settings, reset_settings
from heagent.pub.log_config import TEXT_FORMAT, JsonFormatter, make_formatter


def _record(**extra: object) -> logging.LogRecord:
    record = logging.LogRecord(
        name="heagent.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="hello %s",
        args=("world",),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


# ---------------------------------------------------------------- 渲染


def test_text_format_matches_the_historical_line_shape() -> None:
    """text 行：`2026-11-18 21:00:00 INFO [heagent.test] hello world`——形状不得漂移。"""
    formatter = make_formatter("text")
    rendered = formatter.format(_record())
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2} INFO \[heagent\.test\] hello world", rendered), rendered
    assert formatter._fmt == TEXT_FORMAT


def test_json_format_is_a_single_parseable_object() -> None:
    """json 行：单行 + 可解析 + 四个必备键（timestamp 带时区偏移）。"""
    rendered = make_formatter("json").format(_record())
    assert "\n" not in rendered
    payload = json.loads(rendered)
    assert set(payload) == {"timestamp", "level", "logger", "message"}
    assert payload["level"] == "INFO"
    assert payload["logger"] == "heagent.test"
    assert payload["message"] == "hello world"
    # 带偏移才可与另一时区进程写的日志对齐（本仓已知坑：容器写 UTC、宿主写 CST）。
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}[+-]\d{2}:\d{2}", payload["timestamp"]), payload


def test_json_format_carries_extra_context() -> None:
    """`extra=` 注入的字段落 `context`；标准属性不得混进去。"""
    payload = json.loads(make_formatter("json").format(_record(run_id="abc123", iteration=3)))
    assert payload["context"] == {"run_id": "abc123", "iteration": 3}


def test_json_format_includes_traceback() -> None:
    """异常信息以完整 traceback 字符串入 `exc_info`。"""
    try:
        raise ValueError("boom")
    except ValueError:
        record = logging.LogRecord(
            name="heagent.test",
            level=logging.ERROR,
            pathname=__file__,
            lineno=1,
            msg="failed",
            args=(),
            exc_info=sys.exc_info(),
        )
    payload = json.loads(make_formatter("json").format(record))
    assert "Traceback" in payload["exc_info"]
    assert "ValueError: boom" in payload["exc_info"]


def test_json_format_survives_unserializable_context() -> None:
    """不可 JSON 序列化的上下文退化为 str：日志设施故障不得让业务抛错。"""

    class Opaque:
        def __str__(self) -> str:
            return "<opaque>"

    payload = json.loads(make_formatter("json").format(_record(blob=Opaque())))
    assert payload["context"]["blob"] == "<opaque>"


def test_unknown_format_fails_loudly() -> None:
    """未知格式名显性失败（设置面已有 Literal 校验，走到这里只能是代码传错）。"""
    with pytest.raises(ValueError, match="unknown log format"):
        make_formatter("yaml")


# ---------------------------------------------------------------- 设置面


def test_settings_rejects_unknown_log_format() -> None:
    """非法 `LOG_FORMAT` 在构造时炸，不静默回落 text。"""
    with pytest.raises(ValidationError):
        Settings(log_format="yaml")  # type: ignore[arg-type]


def test_settings_accepts_json_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOG_FORMAT", "json")
    reset_settings()
    try:
        assert get_settings().log_format == "json"
    finally:
        monkeypatch.delenv("LOG_FORMAT", raising=False)
        reset_settings()


# ---------------------------------------------------------------- 装配


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


def test_cli_setup_logging_uses_the_configured_format(
    tmp_path, monkeypatch: pytest.MonkeyPatch, root_logging_restored
) -> None:
    """`_setup_logging()` 按 `LOG_FORMAT` 选 formatter（HTTP 入口复用同一函数，故一并覆盖）。"""
    from heagent.cli.console import _setup_logging

    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    monkeypatch.setenv("LOG_FORMAT", "json")
    reset_settings()
    try:
        _setup_logging()
        handlers = logging.getLogger().handlers
        assert handlers, "root logger has no handlers after _setup_logging()"
        assert all(isinstance(handler.formatter, JsonFormatter) for handler in handlers), [
            type(handler.formatter).__name__ for handler in handlers
        ]
        logging.getLogger("heagent.assembly.check").info("json line", extra={"run_id": "r1"})
        written = next(tmp_path.glob("heagent-*.log")).read_text(encoding="utf-8")
        payload = json.loads(written.strip().splitlines()[-1])
        assert payload["context"] == {"run_id": "r1"}
    finally:
        monkeypatch.delenv("LOG_FORMAT", raising=False)
        monkeypatch.delenv("LOG_DIR", raising=False)
        reset_settings()


def test_cli_setup_logging_defaults_to_text(tmp_path, monkeypatch: pytest.MonkeyPatch, root_logging_restored) -> None:
    """默认（不设 `LOG_FORMAT`）仍是 text——既有日志采集脚本不受影响。"""
    from heagent.cli.console import _setup_logging

    monkeypatch.setenv("LOG_DIR", str(tmp_path))
    reset_settings()
    try:
        _setup_logging()
        formatters = [handler.formatter for handler in logging.getLogger().handlers]
        assert formatters and not any(isinstance(formatter, JsonFormatter) for formatter in formatters)
    finally:
        monkeypatch.delenv("LOG_DIR", raising=False)
        reset_settings()
