"""密钥解析的单一收敛点（Story 67.5）：可配的系统 keyring，未命中回退环境变量 / ``.env``。

**优先级**（``KEYRING_ENABLED=true`` 时）：系统 keyring → :class:`heagent.config.Settings` 字段
（其自身优先级为 系统环境变量 > 项目 ``.env`` > 用户 ``~/.heagent/setting.md``）。
``KEYRING_ENABLED=false``（默认）时**完全不碰** keyring，取值与引入本模块之前逐字一致。

**写入 keyring 不属本模块职责**（只做读取，票面边界），手工一次即可::

    pip install "heagent[keyring]"
    keyring set heagent DEEPSEEK_API_KEY      # 提示输入值，交给系统凭据存储

服务名固定 :data:`KEYRING_SERVICE`，账户名 = 设置键的大写形式（``DEEPSEEK_API_KEY``）；查询时
大小写两种写法都接受（``deepseek_api_key`` 等价）。

**不变量**：本模块只把明文返回给调用方——日志里**只出现键名**，永不出现值（与 ``config`` 层
既有的凭证脱敏口径一致）。``keyring`` 是可选依赖，缺失时给**一次**显性 WARNING 后回退，
既不抛错也不静默。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from heagent.config import Settings

logger = logging.getLogger(__name__)

#: 系统 keyring 的服务名（凭证存储里的命名空间；账户名是设置键的大写形式）。
KEYRING_SERVICE = "heagent"

#: keyring 未安装的 WARNING 只打一次（每次密钥解析都刷屏等于噪声）。
_MISSING_DEP_WARNED = False


def get_secret(name: str, *, settings: Settings | None = None, default: str | None = None) -> str | None:
    """按名解析一个密钥：keyring（可配）→ 环境变量 / ``.env`` → ``default``。

    Args:
        name: 键名，``DEEPSEEK_API_KEY`` 与 ``deepseek_api_key`` 两种写法等价。
        settings: 配置句柄（默认取进程单例）；显式传入便于装配层复用自己的快照。
        default: 两侧都未命中时的兜底值。

    Returns:
        命中的明文，或 ``default``。空串 / ``None`` 一律视为「未配置」——与装配层
        ``if settings.<key>`` 的真值口径完全相同。

    Raises:
        ValueError: ``name`` 不是 :class:`Settings` 的字段（拼错键名不该静默返回 ``None``）。
    """
    conf = settings if settings is not None else _default_settings()
    field = _field_name(name, conf)
    if getattr(conf, "keyring_enabled", False):
        account = field.upper()
        stored = _keyring_lookup(account)
        if stored:
            logger.debug("secret %s resolved from system keyring", account)
            return stored
    value = getattr(conf, field, None)
    if isinstance(value, str) and value:
        return value
    return default


def _default_settings() -> Settings:
    from heagent.config import get_settings  # 延迟导入：避免 config 包初始化期循环

    return get_settings()


def _field_name(name: str, conf: Settings) -> str:
    """把外部写法收敛成 ``Settings`` 字段名，并校验它真的存在。"""
    field = name.strip().lower()
    known = getattr(type(conf), "model_fields", None)
    if known is not None and field not in known:
        raise ValueError(f"Unknown secret name: {name!r}")
    return field


def _keyring_lookup(account: str) -> str | None:
    """查系统 keyring；``keyring`` 缺失或后端报错都回退（不抛、不静默）。"""
    try:
        import keyring
    except ImportError:
        _warn_missing_keyring()
        return None
    try:
        value = keyring.get_password(KEYRING_SERVICE, account)
        # 后端返回 Any（无 stub）：非字符串视作「取不到」，不让 Any 漏进调用方。
        return value if isinstance(value, str) else None
    except Exception:
        # 后端不可用（无 DBus / 无桌面会话 / 凭据库锁定）同属「取不到」，回退即可。
        logger.warning(
            "keyring lookup for %s failed; falling back to environment variables / .env",
            account,
            exc_info=True,
        )
        return None


def _warn_missing_keyring() -> None:
    global _MISSING_DEP_WARNED
    if _MISSING_DEP_WARNED:
        return
    _MISSING_DEP_WARNED = True
    logger.warning(
        "KEYRING_ENABLED=true but the optional 'keyring' package is not installed; "
        'falling back to environment variables / .env. Install it with: pip install "heagent[keyring]"',
    )
