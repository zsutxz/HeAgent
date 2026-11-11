"""配置目录：分组、可写白名单、只读原因、凭证掩码与**四层来源求解**（Story 50-4 / 脊柱 §7–§8）。

本模块是**顶层**模块——只依赖标准库、Pydantic 与 :mod:`heagent.config`；网络层不得 import 它
（脊柱 I1），入口层负责把 :class:`ConfigReport` 映射成 ``network.http_console_protocol`` 的协议模型。

四条口径（违反即偏离 story 边界）：

1. **来源求解器只有一套**：分层用 ``pydantic_settings`` 的 ``DotEnvSettingsSource`` /
   ``EnvSettingsSource``，有效值取自 ``Settings`` 实例（NFR-3：禁止第二套 `.env` 解析）。
2. **行级扫描只产诊断**：:func:`scan_env_file` 给出「重复键 / 空值行 / 行内注释 / 未知键原写法」，
   这些只进 ``notes``，**永不参与取值**。行级**改写**归 Story 50-5 的 ``envfile.py``。
3. **凭证零回传**：``*_API_KEY`` / ``*_API_KEYS`` 只回 ``configured`` + **定长掩码**（常量、
   零信息量、不反映真实长度、不含任何原文字符）。
4. **BOM 容差只剥文件头**：UTF-8 BOM 会让首个键名变成 ``'\ufeffMAX_ITERATIONS'`` 而静默落回上层 /
   默认值（实测，见探针 ``epic50_probe9/10``）。:class:`_BomTolerantDotEnvSource` 只剥离**文件首个
   键**的 BOM（读路径不写盘），**文件中部**的 BOM 仍留在键名里——那种情况由
   :func:`bom_prefixed_keys` 检出并标成「BOM 前缀导致不生效」，绝不静默显示为 ``default``。

键名口径（脊柱 §7 校正 C6）：内部一律用**大写 env 键**表达，映射到字段集时用 ``.upper()`` /
``.lower()``；``Settings`` 零 alias（111 字段 ↔ 111 env 键双射，由测试钉住）。
"""

from __future__ import annotations

from .classify import (
    classify as classify,
)
from .classify import (
    system_env_keys as system_env_keys,
)
from .classify import (
    whitelist as whitelist,
)
from .envscan import (
    _INLINE_COMMENT_RE as _INLINE_COMMENT_RE,
)
from .envscan import (
    SettingMdScan as SettingMdScan,
)
from .envscan import (
    _looks_blank as _looks_blank,
)
from .envscan import (
    _scan_file_common as _scan_file_common,
)
from .envscan import (
    _ScanRead as _ScanRead,
)
from .envscan import (
    bom_prefixed_keys as bom_prefixed_keys,
)
from .envscan import (
    scan_env_file as scan_env_file,
)
from .envscan import (
    scan_setting_md as scan_setting_md,
)
from .groups import (
    EXCLUSION_GROUPS as EXCLUSION_GROUPS,
)
from .groups import (
    LABELS as LABELS,
)
from .groups import (
    UNKNOWN_GROUP as UNKNOWN_GROUP,
)
from .groups import (
    WHITELIST_GROUPS as WHITELIST_GROUPS,
)
from .guards import (
    IMPACT_HIGH as IMPACT_HIGH,
)
from .guards import (
    IMPACT_NORMAL as IMPACT_NORMAL,
)
from .guards import (
    RESOURCE_CEILINGS as RESOURCE_CEILINGS,
)
from .guards import (
    VALUE_GUARDS as VALUE_GUARDS,
)
from .guards import (
    _derive_guard as _derive_guard,
)
from .guards import (
    _merge_guard as _merge_guard,
)
from .guards import (
    guards_for as guards_for,
)
from .guards import (
    impact_for as impact_for,
)
from .masking import (
    _SECRET_SUFFIXES as _SECRET_SUFFIXES,
)
from .masking import (
    MASK as MASK,
)
from .masking import (
    USER_ONLY_SETTING_KEYS as USER_ONLY_SETTING_KEYS,
)
from .masking import (
    is_secret_key as is_secret_key,
)
from .models import (
    BOM as BOM,
)
from .models import (
    MAX_FILE_DIAGNOSTIC_KEYS as MAX_FILE_DIAGNOSTIC_KEYS,
)
from .models import (
    MAX_UNKNOWN_KEYS as MAX_UNKNOWN_KEYS,
)
from .models import (
    ConfigClassification as ConfigClassification,
)
from .models import (
    ConfigGroupReport as ConfigGroupReport,
)
from .models import (
    ConfigGroupSpec as ConfigGroupSpec,
)
from .models import (
    ConfigGuard as ConfigGuard,
)
from .models import (
    ConfigItem as ConfigItem,
)
from .models import (
    ConfigReport as ConfigReport,
)
from .models import (
    ConfigSource as ConfigSource,
)
from .models import (
    EnvFileReport as EnvFileReport,
)
from .models import (
    EnvScan as EnvScan,
)
from .models import (
    LayerMap as LayerMap,
)
from .models import (
    RoutingPoolsReport as RoutingPoolsReport,
)
from .models import (
    RoutingPoolView as RoutingPoolView,
)
from .models import (
    UnknownKeyReport as UnknownKeyReport,
)
from .report import (
    _bounded as _bounded,
)
from .report import (
    _build_item as _build_item,
)
from .report import (
    _group_reports as _group_reports,
)
from .report import (
    _item_notes as _item_notes,
)
from .report import (
    _resolve_source as _resolve_source,
)
from .report import (
    _unknown_keys as _unknown_keys,
)
from .report import (
    build_config_report as build_config_report,
)
from .report import (
    routing_report as routing_report,
)
from .sources import (
    _BomTolerantDotEnvSource as _BomTolerantDotEnvSource,
)
from .sources import (
    _CatalogSettings as _CatalogSettings,
)
from .sources import (
    _dotenv_layer as _dotenv_layer,
)
from .sources import (
    _layer_map as _layer_map,
)
from .sources import (
    _LenientSettings as _LenientSettings,
)
from .sources import (
    _md_layer as _md_layer,
)
from .sources import (
    _solve as _solve,
)
from .sources import (
    _Solved as _Solved,
)
from .sources import (
    _system_layer as _system_layer,
)

__all__ = [
    "BOM",
    "EXCLUSION_GROUPS",
    "LABELS",
    "MAX_FILE_DIAGNOSTIC_KEYS",
    "MAX_UNKNOWN_KEYS",
    "MASK",
    "RESOURCE_CEILINGS",
    "UNKNOWN_GROUP",
    "USER_ONLY_SETTING_KEYS",
    "VALUE_GUARDS",
    "WHITELIST_GROUPS",
    "ConfigClassification",
    "ConfigGroupReport",
    "ConfigGroupSpec",
    "ConfigGuard",
    "ConfigItem",
    "ConfigReport",
    "ConfigSource",
    "EnvFileReport",
    "EnvScan",
    "LayerMap",
    "RoutingPoolView",
    "RoutingPoolsReport",
    "UnknownKeyReport",
    "bom_prefixed_keys",
    "build_config_report",
    "classify",
    "guards_for",
    "impact_for",
    "is_secret_key",
    "routing_report",
    "scan_env_file",
    "system_env_keys",
    "whitelist",
]
