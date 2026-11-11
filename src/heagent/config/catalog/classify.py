"""键名分类：可写白名单、分类结果与系统环境键枚举。

自 ``heagent.config.catalog`` 单文件拆出（E3 绞杀者），行为零改动。
"""

from __future__ import annotations

import fnmatch

from .groups import EXCLUSION_GROUPS, UNKNOWN_GROUP, WHITELIST_GROUPS
from .models import ConfigClassification
from .sources import _system_layer

# ── 分类 ──


def whitelist() -> frozenset[str]:
    """可写白名单——由分组常量派生，不重复书写。"""
    return frozenset(key for spec in WHITELIST_GROUPS for key in spec.keys)


def classify(env_key: str) -> ConfigClassification:
    """判定一个 env 键的分组 / 可写性 / 只读原因。

    优先级（脊柱 §8「D2 裁定」+「R-c 收紧」）：

    1. **显式白名单**优先于任何排除规则 ⇒ ``SANDBOX_DIR_RETENTION_DAYS`` 可写（D2）；
    2. 排除规则中**显式键行**优先于**模式行**，同型按 :data:`EXCLUSION_GROUPS` 表内顺序取首条
       ⇒ ``HTTP_CONSOLE_*`` 的原因是 ``console_itself`` 而不是 ``listening_surface``；
    3. 都没命中 ⇒ 兜底 ``unclassified`` / ``unknown_key``（完备性测试断言它恒为空）。
    """
    for spec in WHITELIST_GROUPS:
        if env_key in spec.keys:
            return ConfigClassification(group=spec.id, writable=True)
    for spec in EXCLUSION_GROUPS:
        if spec.keys and env_key in spec.keys:
            return ConfigClassification(group=spec.id, writable=False, reason=spec.reason)
    for spec in EXCLUSION_GROUPS:
        if any(fnmatch.fnmatchcase(env_key, pattern) for pattern in spec.patterns):
            return ConfigClassification(group=spec.id, writable=False, reason=spec.reason)
    return ConfigClassification(group=UNKNOWN_GROUP.id, writable=False, reason=UNKNOWN_GROUP.reason)


def system_env_keys() -> frozenset[str]:
    """当前进程环境里**提供了值**的字段名集合（小写字段名）。

    单一求解器：与 :func:`_solve` 的 ``system_env`` 层同一实现。写通道用它与面板的 ``writable=false``
    同源判定（脊柱 §8 第 3 步 / AC12）——系统环境变量优先级高于 ``.env``，因此写进 ``.env`` 的值
    当下**不生效**（实测：候选文件里的同名值根本不会被解析），必须拒绝而不是「写个日后生效的坏值」。
    """
    return frozenset(_system_layer())
