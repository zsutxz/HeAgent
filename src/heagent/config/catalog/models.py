"""配置面 Pydantic 模型（ConfigReport / ConfigItem / ConfigGroupSpec 等 12 个）。

自 ``heagent.config.catalog`` 单文件拆出（E3 绞杀者），行为零改动。
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# ── 常量 ──

#: UTF-8 BOM 的字符形式（``"\ufeff".encode() == b"\xef\xbb\xbf"``）。
BOM = "\ufeff"

#: 未知键列表的上界：条目来自文件内容，必须有界（响应体不随 `.env` 内容膨胀）。
MAX_UNKNOWN_KEYS = 64

#: 文件级诊断（重复键 / 空值键）列表的上界：同样来自文件内容，同样必须有界。
MAX_FILE_DIAGNOSTIC_KEYS = 64


class ConfigSource(StrEnum):
    """有效值的来源层（自下而上覆盖，记录**最后**写入者）。"""

    DEFAULT = "default"
    GLOBAL_SETTING = "global_setting"
    PROJECT_ENV = "project_env"
    SYSTEM_ENV = "system_env"


# ── 模型 ──


class ConfigGuard(BaseModel):
    """某个键的合法约束（枚举集合或上下界）：供 UI 提示与写通道复用（AC11）。

    弱校验键（``LOG_LEVEL`` / ``RETRY_*``）在 ``Settings`` 里**没有**足够约束（实测：前者连
    metadata 都没有，后者只有下界）⇒ 实际可接受的极值写在 :data:`VALUE_GUARDS`，与
    ``Settings`` 字段元数据派生出的边界合并后返回。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["enum", "range"]
    values: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None
    exclusive_minimum: bool = False
    exclusive_maximum: bool = False
    min_length: int | None = None
    allow_empty: bool = False


class ConfigClassification(BaseModel):
    """一个 env 键的分组 / 可写性 / 只读原因（``reason=None`` ⇔ 可写）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    group: str
    writable: bool
    reason: str | None = None


class RoutingPoolView(BaseModel):
    """一条**有效**路由池（来自 ``Settings.routing_pool_map`` —— 既有解析器的结果，不是第二套解析）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    entry: str
    tiers: dict[str, str] = Field(default_factory=dict)
    roles: dict[str, str] = Field(default_factory=dict)
    default: str | None = None
    keywords: dict[str, str] = Field(default_factory=dict)


class RoutingPoolsReport(BaseModel):
    """``ROUTING_POOLS`` 的**有效**结果（T8）：池名 / 档位映射 / 被整条忽略的条目 / 非法 JSON。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    declared_entries: tuple[str, ...] = ()
    effective: tuple[RoutingPoolView, ...] = ()
    ignored_entries: tuple[str, ...] = ()
    invalid_json: bool = False


class ConfigItem(BaseModel):
    """配置面板里的一条（``value`` 一律取自 ``Settings`` 的 JSON 化快照）。

    ``source`` 是**求解器**给出的最后写入层；``notes`` 是稳定码诊断（重复键 / 空值行 / BOM 前缀 /
    行内注释），中文文案在 :data:`LABELS` 里由响应一并回给客户端。凭证项 ``value=None``、
    ``masked=MASK``（或未配置时 ``None``）。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    group: str
    value: Any = None
    source: ConfigSource
    writable: bool
    read_only_reason: str | None = None
    is_secret: bool = False
    configured: bool = False
    masked: str | None = None
    guards: ConfigGuard | None = None
    impact: str = "normal"  # 高影响标记：由 ``impact_for`` 从 ``RESOURCE_CEILINGS`` 派生
    notes: tuple[str, ...] = ()
    routing: RoutingPoolsReport | None = None


class ConfigGroupReport(BaseModel):
    """一组配置项（分组由声明式常量驱动，不是按字段名猜的）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    label: str
    items: tuple[ConfigItem, ...] = ()


class EnvFileReport(BaseModel):
    """项目 ``.env`` 的文件状态（T7）：路径 / 存在与否 / 指纹（写通道的冲突判据）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    exists: bool
    readable: bool
    fingerprint: str | None = None
    has_bom: bool = False
    line_count: int = 0
    duplicate_keys: tuple[str, ...] = ()
    blank_keys: tuple[str, ...] = ()


class UnknownKeyReport(BaseModel):
    """未知 / 拼错的键（AC5）：**不并入**有效值列表，单列标「不生效」。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    key: str
    source: ConfigSource


class ConfigReport(BaseModel):
    """一次配置面板查询的完整结果（响应体的域模型；协议镜像见 ``http_console_protocol``）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    field_count: int
    groups: tuple[ConfigGroupReport, ...] = ()
    env_file: EnvFileReport
    unknown_keys: tuple[UnknownKeyReport, ...] = ()
    labels: dict[str, str] = Field(default_factory=dict)
    notes: tuple[str, ...] = ()

    @property
    def items(self) -> tuple[ConfigItem, ...]:
        """展平的条目序列（测试与调用方的便利视图；不参与序列化）。"""
        return tuple(item for group in self.groups for item in group.items)


class EnvScan(BaseModel):
    """``.env`` 的**行级诊断**结果（不是解析器：不含任何"有效值"语义）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str | None = None
    exists: bool = False
    readable: bool = False
    encoding_ok: bool = True
    has_bom: bool = False
    fingerprint: str | None = None
    line_count: int = 0
    declared_keys: tuple[str, ...] = ()
    name_by_lower: dict[str, str] = Field(default_factory=dict)
    duplicate_keys: tuple[str, ...] = ()
    blank_keys: tuple[str, ...] = ()
    inline_comment_keys: tuple[str, ...] = ()


# ── 声明式常量：分组 / 白名单 / 排除规则（单一来源） ──


class ConfigGroupSpec(BaseModel):
    """一个分组：**要么**显式列键（可写组），**要么**用模式表达（排除组）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    label: str
    keys: tuple[str, ...] = ()
    patterns: tuple[str, ...] = ()
    reason: str | None = None


#: 一层 ``.env`` 的原始内容：小写键 → 原始字符串值（**只**用于「是否为空值」判定，绝不作有效值）。
LayerMap = dict[ConfigSource, dict[str, str | None]]
