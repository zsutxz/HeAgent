"""日志格式的单一实现：``text``（默认，人读）与 ``json``（机读，带上下文字段）。

**为什么在 `pub/` 层**：三个入口各自装配日志（CLI 的 stderr+文件、GUI 的文件、HTTP 入口复用 CLI 的
装配），格式就在这里分叉；把格式实现下沉到 `pub/` 后，入口只决定「级别 / 落点 / 用哪种格式」，
行格式本身只有一份，不会出现「CLI 的 json 有 context 而 GUI 没有」这类不对称。

两个格式的口径：

- ``text``：与历史输出**逐字一致**（``%(asctime)s %(levelname)s [%(name)s] %(message)s``），
  默认值，保证既有日志采集脚本（`runtime_stats` 等按行正则解析的消费方）不受影响。
- ``json``：一行一个 JSON 对象，键 ``timestamp`` / ``level`` / ``logger`` / ``message``，
  有 ``extra=`` 注入时追加 ``context``，有异常时追加 ``exc_info``（完整 traceback 字符串）。
  ``timestamp`` 是带本地时区偏移的 ISO-8601（毫秒精度）——跨进程抓日志时区混放是本仓已知坑
  （容器进程写 UTC、宿主进程写 CST），带偏移才可事后对齐。

**这不是安全边界**：``message`` 与 ``context`` 里的内容按原样输出，脱敏仍靠
:func:`heagent.pub.safe_logging.redact_secrets` 等调用点约定。
"""

from __future__ import annotations

import datetime as _datetime
import json
import logging
from typing import Any, Final

#: 人读格式（与历史输出逐字一致；改这里等于改所有既有日志行的形状，慎动）。
TEXT_FORMAT: Final = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
TEXT_DATE_FORMAT: Final = "%Y-%m-%d %H:%M:%S"

#: 合法格式名。设置面的取值域由 ``Settings.log_format``（``Literal``）与
#: ``config.catalog`` 的枚举守卫共同约束，这里是运行期最后一道。
LOG_FORMATS: Final = ("text", "json")

#: ``LogRecord`` 的标准属性：JSON 输出里**除这些之外**的字段都算「上下文」（``extra=`` 注入）。
#: 逐个列举而非用黑名单，是为了让「新增标准属性」在本仓以显式改动呈现（升级 Python 时若有新增，
#: 未列出的属性会以额外 context 键出现——可见的小噪声，好过静默丢上下文）。
_STANDARD_ATTRS: Final[frozenset[str]] = frozenset(
    {
        "args",
        "asctime",
        "created",
        "exc_info",
        "exc_text",
        "filename",
        "funcName",
        "levelname",
        "levelno",
        "lineno",
        "message",
        "module",
        "msecs",
        "msg",
        "name",
        "pathname",
        "process",
        "processName",
        "relativeCreated",
        "stack_info",
        "taskName",
        "thread",
        "threadName",
    }
)


class JsonFormatter(logging.Formatter):
    """把一条日志记录渲染成单行 JSON。

    上下文取 ``record.__dict__`` 里非标准、非下划线开头的键（即 ``logger.info("…", extra={...})``
    注入的那些）。值不可 JSON 序列化时退化为 ``str(value)``——日志设施的故障不得让业务抛错
    （与 :mod:`heagent.pub.safe_logging` 同一立场）。
    """

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": _iso_timestamp(record.created),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        context = {
            key: value
            for key, value in record.__dict__.items()
            if key not in _STANDARD_ATTRS and not key.startswith("_")
        }
        if context:
            payload["context"] = context
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str)


def _iso_timestamp(created: float) -> str:
    """``record.created`` → 带本地时区偏移的 ISO-8601（毫秒）。"""
    moment = _datetime.datetime.fromtimestamp(created).astimezone()
    return moment.isoformat(timespec="milliseconds")


def make_formatter(log_format: str) -> logging.Formatter:
    """按格式名返回 formatter；未知取值**显性失败**（不静默回落 text）。

    静默回落会让「我明明配了 json」变成一个只在排查时才发现的假象——设置面已有
    ``Literal`` 校验，能走到这里的只能是代码传错，那就该炸。
    """
    normalized = (log_format or "text").strip().lower()
    if normalized == "text":
        return logging.Formatter(TEXT_FORMAT, datefmt=TEXT_DATE_FORMAT)
    if normalized == "json":
        return JsonFormatter()
    raise ValueError(f"unknown log format {log_format!r}; expected one of {LOG_FORMATS}")
