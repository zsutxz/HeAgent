"""日志卫生的单一实现：**安全日志**（故障不传播）与**启发式脱敏**。

定位：顶层底层共用模块（与 ``persist.py`` / ``frontmatter.py`` 同层，任何模块均可依赖），
运行期零 heagent 依赖——``network/``（不得依赖 engine/agent）与 ``engine/`` / ``agent/``
共用同一实现，避免「同一约定、多处各写一份」。

两个关注点：

1. :func:`safe_log` —— **日志设施故障不得中断业务**。``logging`` 的 ``Handler.handle``
   **不**捕获 ``emit`` 抛出的异常（与 ``logging.raiseExceptions`` 取值无关，实测），
   因此第三方/自定义 handler 在 ``emit`` 中抛错时，任何 ``logger.*`` 调用都会向上抛。
   凡 docstring 自称 best-effort 的插桩路径（事件发射、观察者、沙箱与 ledger 告警、
   run 快照落盘等）必须经本函数，否则「观测故障」会被上层当成「运行失败」。
   逐调用点收口只能覆盖「我们记得改」的地方；运行栈的普通进度日志（``logger.info``
   等）数量多且会新增，故另配进程级单点守卫 :func:`install_logging_fault_guard`。
2. :func:`redact_secrets` / :func:`redact_details` —— 命令与路径里的凭证**不进日志行**
   的启发式掩码（``API_KEY=…`` / ``sk-…`` / ``Bearer …`` / URL userinfo 等）。

⚠ **两者都不是安全边界**（与 ``SafetyGuard`` / ``path_safety`` 同一立场）：脱敏是模式
匹配启发式，必然有漏网形态；``.heagent/runs/``（run 快照与 rollout JSONL）按设计保存完整
prompt 与消息，**不在**本模块覆盖范围内。处理不可信输入或凭证时仍须 OS 级沙箱与最小权限
（见 CLAUDE.md 安全声明）。
"""

from __future__ import annotations

import contextlib
import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Mapping

# 掩码替换串：保留字段名与分隔符，只吃掉值，便于事后判断「这里本来有个凭证」。
_MASK = "***"

# ① 键值形态：``API_KEY=…`` / ``token: …`` / ``password="…"``（.env 行、命令行导出、配置文件）。
_KEY_VALUE = re.compile(
    r"""(?ix)
    \b(?P<key>api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|auth[_-]?token|client[_-]?secret
       |secret|token|password|passwd|pwd|private[_-]?key)\b
    (?P<keyq>["']?)      # key 后的引号：JSON/YAML 形态 {"token": "…"}
    (?P<sep>\s*[:=]\s*)
    (?P<valq>["']?)
    (?P<value>[^\s"']+)  # 值：到下一个空白/引号为止
    (?P<endq>["']?)
    """
)

# ② CLI 旗标形态：``--api-key sk-…`` / ``--token=…``。
_FLAG_VALUE = re.compile(
    r"""(?ix)
    (--?(?:api[_-]?key|access[_-]?key|auth[_-]?token|token|password|passwd|secret)\b(?:=|\s+))
    (\S+)
    """
)

# ③ 已知凭证形状（前缀即厂商，掩码保留前缀的可辨识度交给「字段名」而非值）。
_TOKEN_SHAPES = (
    re.compile(r"\bsk-[A-Za-z0-9_-]{6,}"),
    re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{16,}"),
    re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{30,}"),
    re.compile(r"\bhf_[A-Za-z0-9]{20,}"),
    # JWT：三段 base64url，首段固定以 eyJ 开头（`{"` 的 base64）。
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{4,}"),
)

# ④ ``Authorization: Bearer <token>``。
_BEARER = re.compile(r"(?i)\b(bearer\s+)([A-Za-z0-9._-]{8,})")

# ⑤ 键名即凭证：结构里的 ``{"secret": "x"}`` 这类短值靠形状识别不出来，
#    故对凭证命名的键直接掩码其值（键名匹配，值不看形状）。
_CREDENTIAL_KEY_NAME = re.compile(
    r"""(?ix)
    (api[_-]?key|apikey|access[_-]?token|refresh[_-]?token|auth[_-]?token|client[_-]?secret
     |secret|token|password|passwd|pwd|private[_-]?key|authorization)
    """
)

# ⑤ URL 内嵌凭证：``https://user:pass@host`` → ``https://user:***@host``。
_URL_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^/\s:@]+):([^/\s@]+)@")

# 默认遍历深度：足够覆盖 ``details`` 这类浅层结构，又不为深层嵌套付出代价。
_REDACT_MAX_DEPTH = 3


def safe_log(
    logger_: logging.Logger,
    level: int,
    message: str,
    *args: object,
    exc_info: bool = False,
) -> bool:
    """记一条日志，**绝不**让日志设施故障向上传播。

    返回 ``True`` 表示正常记录，``False`` 表示日志设施本身出故障、本次记录被吞掉。
    吞掉而非「再 warning 一次」：出故障的就是日志设施本身，任何补救日志都会同样抛错。
    调用方通常忽略返回值；需要断言「观测故障已隔离」的测试可用它——注意装了进程级
    :func:`install_logging_fault_guard` 之后，handler 故障在更下层就被吞掉，本函数
    几乎不再返回 ``False``（两层是叠加关系，不是二选一）。

    ``logger_`` 显式传入（而非模块级 logger）是刻意的：本模块可被 ``network/`` 等
    低层包依赖，不能替调用方决定 logger 归属。
    """
    try:
        logger_.log(level, message, *args, exc_info=exc_info)
    except Exception:  # noqa: BLE001 - 见 docstring：日志故障降级为「少一条日志」
        return False
    return True


# 安装前捕获的 stdlib 实现：守卫只做「包一层」，不改变 stdlib 的既有行为。
# 公开出来供两类调用方使用：测试（要在同一进程内验证「有/无守卫」两种行为）与库消费者
# （想自行掌控 logging 语义时据此还原）。
ORIGINAL_HANDLER_HANDLE = logging.Handler.handle


def _guarded_handler_handle(self: logging.Handler, record: logging.LogRecord) -> bool:
    """``logging.Handler.handle`` 的守卫版：失败只诊断，不传播。

    返回 ``bool`` 与 stdlib 签名一致（记录是否被 handler 处理）；失败时返回 ``True``
    ——「这条日志已由该 handler 接手（虽然写失败）」，语义上等价于被 filter 放过。
    """
    try:
        return ORIGINAL_HANDLER_HANDLE(self, record)
    except Exception:  # noqa: BLE001 - 见 install_logging_fault_guard 的契约
        # 复用 stdlib 诊断路径：按 raiseExceptions 打印 '--- Logging error ---' 与当前异常的
        # traceback，因此「不抛」不等于「无声」。连诊断都失败时只能放弃这条日志（再没有
        # 可用的报告通道了）。
        with contextlib.suppress(Exception):
            self.handleError(record)
        return True


def install_logging_fault_guard() -> bool:
    """让 handler 的故障永不向业务传播（进程级单点，幂等）。

    ``logging`` 的 ``Handler.handle`` **不**捕获 ``emit`` 抛出的异常（与
    ``logging.raiseExceptions`` 无关，实测），故第三方/自定义 handler 一旦在 ``emit``
    中抛错，**任何** ``logger.*`` 调用都会向上抛——一次 run 里的进度日志就能把
    成功的运行变成失败（``docs/frame.md`` 五「运行栈日志非观测故障免疫」）。

    本函数把 ``Handler.handle`` 换成 :func:`_guarded_handler_handle`：handler 失败时
    走 stdlib 的 ``handleError``（照旧打印诊断、照旧尊重 ``raiseExceptions``），
    但异常不再逃出 ``logger.*``。逐调用点用 :func:`safe_log` 只覆盖我们改到的地方，
    本守卫覆盖**运行期全部** logger 调用（含将来新增的）。

    返回本次是否完成安装；已经装过（或已由调用方替换）时返回 ``False``。
    **副作用是进程级的**（改的是 stdlib 类的类属性），故由入口层（``cli``/GUI/TCP）
    在配置 logging 时显式调用，而不是在 import 时自动生效；库消费者想自行掌控
    logging 语义时可以不装。
    """
    current: Any = logging.Handler.handle
    if current is _guarded_handler_handle:
        return False
    # 进程级的 stdlib 类属性替换是本函数的**目的**（见 docstring 的副作用说明）。
    logging.Handler.handle = _guarded_handler_handle  # type: ignore[method-assign]
    return True


def redact_secrets(text: str) -> str:
    """把 ``text`` 中的凭证形态替换为 :data:`_MASK`（启发式，非安全边界）。

    只做「模式可识别」的替换：字段名 + 值、CLI 旗标、厂商前缀（``sk-`` / ``ghp_`` /
    ``AKIA`` 等）、``Bearer`` 头、URL 内嵌 userinfo。无凭证时逐字节原样返回。
    本函数不抛异常——意外情形返回 ``[redaction error]``（fail-closed：绝不回吐原文）。
    """
    try:
        masked = _KEY_VALUE.sub(lambda m: f"{m['key']}{m['keyq']}{m['sep']}{m['valq']}{_MASK}{m['endq']}", text)
        masked = _FLAG_VALUE.sub(lambda m: f"{m.group(1)}{_MASK}", masked)
        for pattern in _TOKEN_SHAPES:
            masked = pattern.sub(_MASK, masked)
        masked = _BEARER.sub(lambda m: f"{m.group(1)}{_MASK}", masked)
        return _URL_USERINFO.sub(lambda m: f"{m.group(1)}:{_MASK}@", masked)
    except Exception:  # noqa: BLE001 - 脱敏失败不得回吐原文
        return "[redaction error]"


def redact_details(value: Any, *, depth: int = _REDACT_MAX_DEPTH) -> Any:
    """对事件 ``details`` 之类的浅层结构做脱敏（dict/list/tuple/str，其余原样）。

    两条判据并用：**值**按凭证形状掩码（:func:`redact_secrets`），**键名**命中凭证
    词表时整个值掩码（``{"secret": "x"}`` 这种短值没有形状可认）。

    超过 ``depth`` 层或遇到非容器类型时原样返回——事件载荷里出现超深嵌套属异常形状，
    宁可少脱敏也不做无界的递归遍历（也避免自引用结构导致死循环）。
    """
    if depth <= 0:
        return value
    if isinstance(value, str):
        return redact_secrets(value)
    if isinstance(value, dict):
        return {
            key: (_MASK if _CREDENTIAL_KEY_NAME.fullmatch(str(key).strip()) else redact_details(item, depth=depth - 1))
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_details(item, depth=depth - 1) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_details(item, depth=depth - 1) for item in value)
    return value


def redact_mapping(mapping: Mapping[str, Any]) -> dict[str, Any]:
    """``redact_details`` 的 Mapping 入口（供 :class:`LoggingObserver` 等调用）。"""
    return {key: redact_details(value) for key, value in mapping.items()}
