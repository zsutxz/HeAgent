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

import fnmatch
import hashlib
import json
import logging
import re
from enum import StrEnum
from pathlib import Path
from typing import Any, ClassVar, Literal, NamedTuple, get_args, get_origin

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import DotEnvSettingsSource, EnvSettingsSource

from heagent.config import GLOBAL_CONFIG_FILE, Settings

logger = logging.getLogger(__name__)

# ── 常量 ──

#: UTF-8 BOM 的字符形式（``"\ufeff".encode() == b"\xef\xbb\xbf"``）。
BOM = "\ufeff"

#: 凭证的**定长**掩码：常量、零信息量（既不反映长度也不含原文字符）。
MASK = "********"

#: 未知键列表的上界：条目来自文件内容，必须有界（响应体不随 `.env` 内容膨胀）。
MAX_UNKNOWN_KEYS = 64

#: 文件级诊断（重复键 / 空值键）列表的上界：同样来自文件内容，同样必须有界。
MAX_FILE_DIAGNOSTIC_KEYS = 64

_INLINE_COMMENT_RE = re.compile(r"\s#")


class ConfigSource(StrEnum):
    """有效值的来源层（自下而上覆盖，记录**最后**写入者）。"""

    DEFAULT = "default"
    GLOBAL_ENV = "global_env"
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


# ── 声明式常量：分组 / 白名单 / 排除规则（单一来源，Story 50-5 复用） ──


class ConfigGroupSpec(BaseModel):
    """一个分组：**要么**显式列键（可写组），**要么**用模式表达（排除组）。"""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    label: str
    keys: tuple[str, ...] = ()
    patterns: tuple[str, ...] = ()
    reason: str | None = None


#: 可写白名单（fail-closed：显式允许子集，**不是**排除法）——46 键，D3 裁定后口径。
WHITELIST_GROUPS: tuple[ConfigGroupSpec, ...] = (
    ConfigGroupSpec(
        id="models",
        label="模型",
        keys=(
            "DEFAULT_MODEL",
            "DEEPSEEK_MODEL",
            "KIMI_MODEL",
            "GLM_MODEL",
            "OPENAI_MODEL",
            "OLLAMA_MODEL",
        ),
    ),
    ConfigGroupSpec(
        id="routing",
        label="智能路由",
        keys=("ROUTING_POOLS", "ROUTING_REASONING_CONTINUITY"),
    ),
    ConfigGroupSpec(
        id="limits",
        label="迭代与限额",
        keys=(
            "MAX_ITERATIONS",
            "GOAL_MAX_ITERATIONS",
            "SUBAGENT_MAX_ITERATIONS",
            "SUBAGENT_MAX_DEPTH",
            "MAX_OUTPUT_TOKENS",
            "SHELL_TIMEOUT",
            "ANNOUNCE_PROGRESS",
        ),
    ),
    ConfigGroupSpec(
        id="context",
        label="上下文",
        keys=(
            "MAX_CONTEXT_TOKENS",
            "COMPRESSION_THRESHOLD",
            "WINDOW_RESET_THRESHOLD",
            "CONTEXT_STRATEGY",
            "TOKENIZER",
            "CONTEXT_FILES_ENABLED",
            "CONTEXT_FILES_MAX_BYTES",
            "CONTEXT_FILES_USER_LEVEL",
        ),
    ),
    ConfigGroupSpec(
        id="memory_skills",
        label="记忆与技能",
        keys=(
            "MEMORY_NUDGE_ENABLED",
            "MEMORY_INJECT_MAX_BYTES",
            "SKILL_MATCH_THRESHOLD",
            "SKILL_MAX_AUTO_INVOKE",
            "SKILL_MAX_AUTO_INVOKE_TOKENS",
            "SKILL_MAX_MANUAL_LOAD_TOKENS",
            "SKILL_CURATOR_STALE_DAYS",
        ),
    ),
    ConfigGroupSpec(
        id="retention",
        label="保留期与回收",
        keys=(
            "LEDGER_RETENTION_DAYS",
            "RUN_RETENTION_DAYS",
            "LOG_RETENTION_DAYS",
            "SESSION_RETENTION_DAYS",
            "EDIT_SNAPSHOT_RETENTION_DAYS",
            # D2 裁定：显式白名单 > 模式排除 ⇒ 本键可写（保留天数是运维可调项，非隔离姿态）。
            "SANDBOX_DIR_RETENTION_DAYS",
            "PRUNE_MIN_INTERVAL_SECONDS",
        ),
    ),
    ConfigGroupSpec(id="cron", label="定时调度", keys=("CRON_TICK_SECONDS",)),
    ConfigGroupSpec(
        id="observability",
        label="日志与观测",
        keys=("LOG_LEVEL", "LOG_FILE_LEVEL", "EVENTS_ROLLOUT_ENABLED"),
    ),
    ConfigGroupSpec(
        id="providers",
        label="Provider 行为",
        keys=("ANTHROPIC_PROMPT_CACHING", "OLLAMA_ENABLED"),
    ),
    ConfigGroupSpec(
        id="resilience",
        label="重试与退避",
        keys=("RETRY_MAX_ATTEMPTS", "RETRY_BASE_DELAY", "RETRY_MAX_DELAY"),
    ),
)

#: 只读排除组（**显式行 > 模式行**，同型按表内顺序取首条 —— 脊柱 §8 R-c）。
EXCLUSION_GROUPS: tuple[ConfigGroupSpec, ...] = (
    # ── 显式键行（先于一切模式行求值 ⇒ HTTP_CONSOLE_* 的只读原因是「控制台自身」而非「监听面」）──
    ConfigGroupSpec(
        id="console",
        label="控制台自身",
        keys=("HTTP_CONSOLE_WRITE_ENABLED", "HTTP_CONSOLE_PROJECTS_FILE"),
        reason="console_itself",
    ),
    ConfigGroupSpec(
        id="dream_supervision",
        label="无人监督的后台巩固",
        keys=("DREAM_CRON", "DREAM_IDLE_MINUTES", "DREAM_MAX_ITERATIONS", "DREAM_SESSION_LOOKBACK"),
        reason="dream_supervision",
    ),
    ConfigGroupSpec(
        id="process_spawn",
        label="进程拉起与后台执行",
        keys=("HOOKS_ENABLED", "MCP_ENABLED", "MCP_CONFIG_PATH", "CRON_ENABLED", "DREAM_ENABLED"),
        reason="process_spawn",
    ),
    ConfigGroupSpec(
        id="safety",
        label="安全闸门",
        keys=("SAFETY_BLOCKED_TOOLS", "APPROVAL_TOOLS"),
        reason="safety_gate",
    ),
    ConfigGroupSpec(
        id="paths",
        label="宿主路径与工作流",
        keys=("LOG_DIR", "GOAL_WORKFLOW_SKILL"),
        reason="host_path",
    ),
    ConfigGroupSpec(id="outbound", label="出站与端点", keys=("ACTIVE_PROVIDER",), reason="outbound_redirect"),
    ConfigGroupSpec(
        id="run_semantics",
        label="运行语义开关",
        keys=("PLAN_MODE", "MODEL_PRICING"),
        reason="run_semantics",
    ),
    # ── 模式行 ──
    ConfigGroupSpec(
        id="credentials",
        label="凭证",
        patterns=("*_API_KEY", "*_API_KEYS"),
        reason="credential",
    ),
    ConfigGroupSpec(
        id="listening",
        label="监听面",
        patterns=("HTTP_*", "TCP_*"),
        reason="listening_surface",
    ),
    ConfigGroupSpec(
        id="sandbox",
        label="沙箱与执行后端",
        patterns=("SANDBOX_*",),
        reason="sandbox_posture",
    ),
    ConfigGroupSpec(
        id="outbound",
        label="出站与端点",
        patterns=("*_BASE_URL",),
        reason="outbound_redirect",
    ),
    ConfigGroupSpec(
        id="run_semantics",
        label="运行语义开关",
        patterns=("GOAL_*_MODE",),
        reason="run_semantics",
    ),
)

#: 兜底分组：划分破损时条目仍可见（由完备性测试断言其恒为空）。
UNKNOWN_GROUP = ConfigGroupSpec(id="unclassified", label="未分类", reason="unknown_key")

#: 只读原因 / 诊断码的中文文案（响应随 ``labels`` 一并回给客户端，UI 无需硬编码）。
LABELS: dict[str, str] = {
    # 只读原因
    "system_env": "被系统环境变量提供：改 .env 不会影响本次进程",
    "credential": "凭证项：永不回传、永不写入",
    "listening_surface": "监听面 / 暴露面：改动需要重启服务",
    "sandbox_posture": "沙箱与执行后端：改动等于改变 OS 级隔离姿态",
    "process_spawn": "进程拉起 / 无人监督后台执行开关",
    "dream_supervision": "无人监督的后台巩固参数（其开关 DREAM_ENABLED 本身只读）",
    "host_path": "宿主路径 / 任意工作流加载面",
    "safety_gate": "安全闸门：降低 defense-in-depth 等于自我削权",
    "outbound_redirect": "出站重定向：可把凭证送往往意端点（准外泄通道）",
    "run_semantics": "运行语义开关：静默改变行为，超出「配置展示」范围",
    "console_itself": "控制台自身开关：写入面不得给自己解锁",
    "unknown_key": "未知键（不在 Settings 字段集内）",
    # 项目 / 全局 .env 的诊断
    "duplicate_in_project_env": "项目 .env 中该键出现多次（后者生效）",
    "duplicate_in_global_env": "全局 .env 中该键出现多次（后者生效）",
    "empty_in_project_env": "项目 .env 中该键为空值（显式置空，不生效）",
    "empty_in_global_env": "全局 .env 中该键为空值（显式置空，不生效）",
    "ineffective_in_project_env": "项目 .env 中该键未被解析（写法不受支持）",
    "ineffective_in_global_env": "全局 .env 中该键未被解析（写法不受支持）",
    "bom_prefixed_in_project_env": "项目 .env 中该键带 BOM 前缀 ⇒ 不生效（请删除该字节）",
    "bom_prefixed_in_global_env": "全局 .env 中该键带 BOM 前缀 ⇒ 不生效（请删除该字节）",
    "bom_stripped_in_project_env": "项目 .env 文件头带 BOM，已按容差读取（盘上字节未改）",
    "inline_comment_in_project_env": "项目 .env 中该键带行内注释",
    "inline_comment_in_global_env": "全局 .env 中该键带行内注释",
    "routing_pools_invalid": "ROUTING_POOLS 不是合法 JSON 对象 ⇒ **整份配置被忽略**，已回落各条目 `<条目>_MODEL`",
    "routing_pools_entries_ignored": "ROUTING_POOLS 中这些条目被整条忽略（未知条目名或规格非法）⇒ 该池不生效",
    # 文件级 / 响应级
    "project_env_missing": "项目 .env 不存在：全部字段回退到全局 .env / 默认值",
    "project_env_unreadable": "项目 .env 不可读：全部字段回退到全局 .env / 默认值",
    "project_env_bom_stripped": "项目 .env 带文件头 BOM：已剥离后求解（盘上字节未改）",
    "project_env_blank_values": (
        "项目 .env 含空值键（`KEY=`）：bool/int 等字段会因此**拒绝加载**配置，故本次求解把空值"
        "当作「未提供」（请填值或删除该行；文件未改动）"
    ),
    "project_env_invalid": "项目 .env 的值非法：本次求解不含项目层（文件未改动）",
    "env_files_unavailable": "所有 .env 都不可用：本次求解只有系统环境变量与默认值",
    "bom_prefixed_keys": "存在带 BOM 前缀的键名 ⇒ 这些键不生效（见对应条目）",
    "unknown_keys_truncated": f"未知键过多，只列出前 {MAX_UNKNOWN_KEYS} 条",
    "file_diagnostics_truncated": f"文件级诊断（重复键 / 空值键）过多，只列出前 {MAX_FILE_DIAGNOSTIC_KEYS} 条",
    "write_channel_disabled": (
        "服务启动时未开启配置写入（HTTP_CONSOLE_WRITE_ENABLED）：所有可写项在本页只读；"
        "网页无法自行开启，需在启动配置（系统环境变量 / 项目 .env / 全局 .env）里开启后重启服务"
    ),
    # 面板级**一行短状态**（Story 50-8 R4）：上面那句长文案仍保留（写进 HTML `title` / 直接调 API
    # 的客户端仍能读到完整解释），版面上只显示短文案；**R9 之后逐项那份重复已撤**（可写项只在头部
    # 的徽标上说一次），本键改作徽标 `title` 的第一句。
    "write_channel_short": "未开启配置写入：可写项在本页只读",
    # R9：挂在设置面板头部**项目名后面的紧凑徽标**文案。宽度是硬约束：设置列只有 ~364px，
    # 「项目设置 + 项目名徽标」已占 ~160px，再长的文案会换行 ⇒ 又变成「独占一行」。
    # 因此徽标只显示「只读」，完整原因（`write_channel_short` + `write_channel_disabled`）见 `title`。
    "write_channel_badge": "只读",
    # 写入通道（Story 50-5）：写已生效但审计没落盘 —— 必须显式，不能让人误以为「已审计」。
    "audit_not_recorded": "写入已生效，但审计记录未能落盘（服务端有 ERROR 日志；请检查 console 目录写权限）",
}

#: **白名单里所有「只有下界」的数值键**的上界表（缺口闭合：Z-D13 的 5 个 + 同族批次补齐其余 16 个）。
#:
#: 为什么需要它：``Settings`` 对这些字段只给了下界（``ge=…``），而 D3 的守卫清单原本只收了弱校验键
#: ⇒ 一旦开启写闸门，白名单内的写入就能把它们设成 ``10^9``（保留期变成永不回收、预算变成不可完成）。
#:
#: 口径 = **同族同刻度 + 至少是默认值的 10 倍 + 只挡人类尺度之外的极值**：
#:
#: - 逐键拍数字无法复核（凭什么 37 天而不是 38 天？）；按族给刻度则有可陈述的判据，新增同类键时
#:   不必重新立法，且「≥ 10 × 默认值」是可执行断言（见 ``tests/test_config_catalog.py``）；
#: - 每一条都远高于任何真实用法，触发的是「挡住手滑与 ``10^9``」，**不是限制用户**：上界只作用于
#:   写入通道与面板展示，手工改 ``.env`` 完全不受约束。
#:
#: 刻度与理由：
#:
#: - **``days`` = 3650（10 年）**：保留期与时间窗。**上界不剥夺任何意图** —— 这批键都支持 ``0``
#:   （= 禁用回收 / 不限制），「永久保留」用 ``0`` 表达比写 ``36500`` 更明确；
#: - **``seconds`` = 604800（7 天）**：间隔与超时。会话 / 维护尺度的间隔与超时超过一周已无实际用途；
#: - **``bytes`` = 8388608（8 MiB）**：上下文文件与记忆注入的文本预算（约 2M token 量级的文本）；
#: - **``tokens`` = 1000000**：技能正文 / 自动注入的 token 预算（与 ``MAX_OUTPUT_TOKENS`` 同刻度）；
#: - **``count`` = 100**：条数与嵌套深度（一次注入 100 个技能、嵌套 100 层都已是不可完成量级）；
#: - **自成刻度（不并入上面任何一族，量纲不同）**：迭代预算 ``10000`` 次（无人值守的长任务确实需要
#:   很多轮，与「条数」不是一回事）、上下文窗口 ``16000000`` tokens（那是**模型属性**量级，
#:   ``MAX_OUTPUT_TOKENS`` 则取最大真实模型输出窗口的约 8 倍）。
RESOURCE_CEILINGS: dict[str, float] = {
    # days = 3650：保留期 / 时间窗（默认值 7–30 天）
    "EDIT_SNAPSHOT_RETENTION_DAYS": 3650.0,
    "LEDGER_RETENTION_DAYS": 3650.0,
    "LOG_RETENTION_DAYS": 3650.0,
    "RUN_RETENTION_DAYS": 3650.0,
    "SANDBOX_DIR_RETENTION_DAYS": 3650.0,
    "SESSION_RETENTION_DAYS": 3650.0,
    "SKILL_CURATOR_STALE_DAYS": 3650.0,
    # seconds = 604800：间隔 / 超时（默认值 60 / 120 / 900 秒）
    "CRON_TICK_SECONDS": 604800.0,
    "PRUNE_MIN_INTERVAL_SECONDS": 604800.0,
    "SHELL_TIMEOUT": 604800.0,
    # bytes = 8388608：文本预算（默认值 32768 / 49152）
    "CONTEXT_FILES_MAX_BYTES": 8_388_608.0,
    "MEMORY_INJECT_MAX_BYTES": 8_388_608.0,
    # tokens = 1000000：token 预算（默认值 None / 8192）
    "MAX_OUTPUT_TOKENS": 1_000_000.0,
    "SKILL_MAX_AUTO_INVOKE_TOKENS": 1_000_000.0,
    "SKILL_MAX_MANUAL_LOAD_TOKENS": 1_000_000.0,
    # count = 100：条数 / 深度（默认值 3）
    "SKILL_MAX_AUTO_INVOKE": 100.0,
    "SUBAGENT_MAX_DEPTH": 100.0,
    # 迭代预算 = 10000（默认值 50 / 20 / 20）
    "MAX_ITERATIONS": 10_000.0,
    "GOAL_MAX_ITERATIONS": 10_000.0,
    "SUBAGENT_MAX_ITERATIONS": 10_000.0,
    # 上下文窗口 = 16000000（默认值 512000）
    "MAX_CONTEXT_TOKENS": 16_000_000.0,
}


#: 弱校验键的**字段级守卫**（脊柱 §8「开放弱校验键的强制前提」；不改 ``Settings`` 定义）。
#:
#: 两类条目：
#:
#: - **弱校验键**（``LOG_LEVEL`` / ``LOG_FILE_LEVEL`` / ``RETRY_*``）：``Settings`` 对它们没有约束
#:   或只有下界，候选构造（I6）因此是**空门** —— 它们的全部约束只能来自这里；
#: - **上界**（:data:`RESOURCE_CEILINGS` 合并进来的 21 个键）：字段元数据只给下界，上界由那张表提供。
#:
#: 两条边界（改这张表前先读）：
#:
#: 1. 守卫**只作用于写入通道与面板展示**，不改 ``Settings`` 定义语义 —— 盘上已有的配置文件仍按原样
#:   加载（给字段加 ``le=`` 会改变既有配置的可加载性，那是另一个决定）；
#: 2. **完备性已闭合**：白名单里的数值键现在**全部**有上界，由
#:   ``tests/test_config_catalog.py::TestGuards::test_no_whitelisted_numeric_key_is_left_unbounded``
#:   钉住 —— 新增白名单数值键时若不给出上界，该用例会红。
VALUE_GUARDS: dict[str, ConfigGuard] = {
    "CONTEXT_STRATEGY": ConfigGuard(kind="enum", values=("compressor", "reset")),
    "LOG_LEVEL": ConfigGuard(kind="enum", values=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")),
    "LOG_FILE_LEVEL": ConfigGuard(
        kind="enum", values=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"), allow_empty=True
    ),
    "RETRY_MAX_ATTEMPTS": ConfigGuard(kind="range", maximum=10.0),
    "RETRY_BASE_DELAY": ConfigGuard(kind="range", maximum=60.0),
    "RETRY_MAX_DELAY": ConfigGuard(kind="range", maximum=600.0),
    # 资源旋钮 / 预算 / 保留期的上界：全部来自 RESOURCE_CEILINGS（单一事实源，见其 docstring 的口径）。
    **{key: ConfigGuard(kind="range", maximum=ceiling) for key, ceiling in RESOURCE_CEILINGS.items()},
}

_SECRET_SUFFIXES = ("_API_KEY", "_API_KEYS")


# ── 分类 ──


def _all_specs() -> tuple[ConfigGroupSpec, ...]:
    return (*WHITELIST_GROUPS, *EXCLUSION_GROUPS)


def whitelist() -> frozenset[str]:
    """可写白名单（46 键）——由分组常量派生，不重复书写。"""
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


def is_secret_key(env_key: str) -> bool:
    """是否凭证键（``*_API_KEY`` / ``*_API_KEYS``）——这类键永不回传、永不写入。"""
    return env_key.endswith(_SECRET_SUFFIXES)


def _derive_guard(field_info: Any) -> ConfigGuard | None:
    """从 ``Settings`` 字段元数据派生守卫（``Literal`` ⇒ 枚举；``Ge``/``Le``/``Gt``/``Lt`` ⇒ 上下界）。

    约束对象按**属性名**读取而非 import ``annotated_types``：后者是 pydantic 的传递依赖，
    不是本项目的直接依赖（``pyproject.toml`` 未列），import 它会引入未声明的耦合。
    """
    annotation = getattr(field_info, "annotation", None)
    literals: tuple[str, ...] = ()
    if get_origin(annotation) is Literal:
        literals = tuple(str(arg) for arg in get_args(annotation))

    minimum = maximum = None
    exclusive_minimum = exclusive_maximum = False
    min_length = None
    for meta in field_info.metadata:
        ge = getattr(meta, "ge", None)
        le = getattr(meta, "le", None)
        gt = getattr(meta, "gt", None)
        lt = getattr(meta, "lt", None)
        if ge is not None:
            minimum = float(ge)
        if le is not None:
            maximum = float(le)
        if gt is not None:
            minimum, exclusive_minimum = float(gt), True
        if lt is not None:
            maximum, exclusive_maximum = float(lt), True
        length = getattr(meta, "min_length", None)
        if isinstance(length, int):
            min_length = length

    if literals:
        return ConfigGuard(kind="enum", values=literals, min_length=min_length)
    if minimum is None and maximum is None and min_length is None:
        return None
    return ConfigGuard(
        kind="range",
        minimum=minimum,
        maximum=maximum,
        exclusive_minimum=exclusive_minimum,
        exclusive_maximum=exclusive_maximum,
        min_length=min_length,
    )


def _merge_guard(explicit: ConfigGuard, derived: ConfigGuard | None) -> ConfigGuard:
    """显式守卫（写通道口径）补上字段元数据派生的边界：显式值优先，缺口才用派生值。"""
    if derived is None:
        return explicit
    return ConfigGuard(
        kind=explicit.kind,
        values=explicit.values,
        minimum=explicit.minimum if explicit.minimum is not None else derived.minimum,
        maximum=explicit.maximum if explicit.maximum is not None else derived.maximum,
        exclusive_minimum=explicit.exclusive_minimum or derived.exclusive_minimum,
        exclusive_maximum=explicit.exclusive_maximum or derived.exclusive_maximum,
        min_length=explicit.min_length if explicit.min_length is not None else derived.min_length,
        allow_empty=explicit.allow_empty,
    )


def guards_for(env_key: str) -> ConfigGuard | None:
    """该键的合法约束（``None`` = 无约束可用）。"""
    field_info = Settings.model_fields.get(env_key.lower())
    derived = _derive_guard(field_info) if field_info is not None else None
    explicit = VALUE_GUARDS.get(env_key)
    if explicit is not None:
        return _merge_guard(explicit, derived)
    return derived


# ── 行级扫描（只产诊断，绝不产值）──


def _looks_blank(raw_value: str) -> bool:
    """行内原始值是否**看起来**为空（启发式；权威判据是该键缺席于来源层）。

    引号包裹的值一律算「有值」，避免 ``KEY=" # "`` 被误判成空值。
    """
    value = raw_value.strip()
    if not value or value.startswith("#"):
        return True
    if len(value) > 2 and value[0] in "\"'" and value.endswith(value[0]):
        return False
    head = value.split("#", 1)[0] if _INLINE_COMMENT_RE.search(value) else value
    return head.strip() == ""


def scan_env_file(path: str | Path | None) -> EnvScan:
    """读 ``.env`` 的**行级诊断**（重复键 / 空值行 / 行内注释 / 键的原写法）。

    刻意**不**解析值语义（那是 ``pydantic_settings`` 的职责）：这里的输出只用于给条目挂
    ``notes``。非 UTF-8 文件用 ``errors="replace"`` 兜底（fail-soft，与 Z-D12 同立场）。
    文件头 BOM 在这里同样被剥掉——口径与 :class:`_BomTolerantDotEnvSource` 一致（只剥头部）。
    """
    if path is None:
        return EnvScan()
    file_path = Path(path)
    try:
        raw = file_path.read_bytes()
    except OSError:
        return EnvScan(path=str(file_path), exists=file_path.exists(), readable=False)

    try:
        raw.decode("utf-8")
        encoding_ok = True
    except UnicodeDecodeError:
        # 非 UTF-8（编码坏了）：值求解会整体降级，行级诊断也只能 best-effort——键名可能被替换字符
        # 污染，因此**不用它**判定「未知键」（否则会报出乱码键名）。
        encoding_ok = False
    text = raw.decode("utf-8", errors="replace")
    has_bom = text.startswith(BOM)
    if has_bom:
        text = text[len(BOM) :]

    # ``splitlines()``：0 字节文件算 0 行、末行换行不额外算一行（评审发现·镜头二⑤：原先按
    # ``split("\n")`` 段数计，0 字节 .env 会谎报 1 行）。
    lines = text.replace("\r\n", "\n").splitlines()
    counts: dict[str, int] = {}
    names: dict[str, str] = {}
    blanks: set[str] = set()
    commented: set[str] = set()
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, raw_value = stripped.partition("=")
        name = name.strip()
        if name.lower().startswith("export "):
            name = name[len("export ") :].strip()
        if not name:
            continue
        lower = name.lower()
        counts[lower] = counts.get(lower, 0) + 1
        names.setdefault(lower, name)
        if _looks_blank(raw_value):
            blanks.add(lower)
        if _INLINE_COMMENT_RE.search(raw_value):
            commented.add(lower)

    return EnvScan(
        path=str(file_path),
        exists=True,
        readable=True,
        encoding_ok=encoding_ok,
        has_bom=has_bom,
        fingerprint=hashlib.sha256(raw).hexdigest(),
        line_count=len(lines),
        declared_keys=tuple(names.values()),
        name_by_lower=names,
        duplicate_keys=tuple(names[key] for key in names if counts[key] > 1),
        blank_keys=tuple(names[key] for key in names if key in blanks),
        inline_comment_keys=tuple(names[key] for key in names if key in commented),
    )


# ── 四层来源求解 ──


class _BomTolerantDotEnvSource(DotEnvSettingsSource):
    """``DotEnvSettingsSource`` + **文件头 BOM** 容差（复用父类解析，不改值语义）。

    只剥「映射里第一个键」的 BOM：文件头 BOM 必然落在首个被解析的键上；文件**中部**的 BOM
    刻意保留（那种情况由 :func:`bom_prefixed_keys` 显式标注，而不是静默吞掉）。
    """

    def _read_env_file(self, file_path: Path) -> Any:
        """读单文件并剥掉**首个键**的 BOM（其余键原样保留，供 :func:`bom_prefixed_keys` 检出）。"""
        data = super()._read_env_file(file_path)
        head = next(iter(data), None)
        if isinstance(head, str) and head.startswith(BOM):
            clean = head[len(BOM) :]
            return {(clean if key is head else key): value for key, value in data.items()}
        return data


class _Solved(NamedTuple):
    """求解结果：有效 ``Settings`` + 参与归属的层 + 真正生效的 dotenv 层 + 降级说明。"""

    settings: Settings
    layers: LayerMap
    used: tuple[ConfigSource, ...]
    notes: tuple[str, ...] = ()


class _CatalogSettings(Settings):
    """只有 dotenv 源被换成 BOM 容差版的 ``Settings``：字段与校验**完全同源**。

    ``_ENV_IGNORE_EMPTY`` 决定「``KEY=``（空值）」算不算「该键被提供了」：**忠实口径**（``False``，
    与运行期默认一致）下空值以 ``''`` 进层，bool/int 字段随即校验失败（实测）；**容错口径**
    （``True``）下空值整条消失，等价于「未提供」。
    """

    _ENV_IGNORE_EMPTY: ClassVar[bool] = False

    @classmethod
    def settings_customise_sources(  # type: ignore[override]
        cls,
        settings_cls: type[Settings],
        init_settings: Any,
        env_settings: Any,
        dotenv_settings: Any,
        file_secret_settings: Any,
    ) -> tuple[Any, ...]:
        return (
            init_settings,
            env_settings,
            _BomTolerantDotEnvSource(
                settings_cls,
                env_file=getattr(dotenv_settings, "env_file", None),
                env_file_encoding=getattr(dotenv_settings, "env_file_encoding", "utf-8"),
                env_ignore_empty=cls._ENV_IGNORE_EMPTY,
            ),
            file_secret_settings,
        )


class _LenientSettings(_CatalogSettings):
    """把 ``KEY=``（空值）当作「未提供」——只在忠实口径构造失败时启用（见 :func:`_solve`）。"""

    _ENV_IGNORE_EMPTY: ClassVar[bool] = True


#: 一层 ``.env`` 的原始内容：小写键 → 原始字符串值（**只**用于「是否为空值」判定，绝不作有效值）。
LayerMap = dict[ConfigSource, dict[str, str | None]]


def _dotenv_layer(path: Path | None, *, ignore_empty: bool) -> dict[str, str | None]:
    """某一层 ``.env`` 的原始键值（小写键）；不存在时**不读**，不可读时返回空（不抛）。"""
    if path is None or not path.is_file():
        return {}
    try:
        return dict(_BomTolerantDotEnvSource(Settings, env_file=path, env_ignore_empty=ignore_empty)())
    except Exception as exc:  # noqa: BLE001 - 单个层级不可用不得带崩整个面板（fail-soft）
        logger.warning("config layer %s is unusable: %s", path, exc)
        return {}


def _dotenv_layers(global_file: Path | None, project_file: Path, *, ignore_empty: bool) -> LayerMap:
    """两层 ``.env`` 的原始内容（口径与同时求解的候选一致）。"""
    return {
        ConfigSource.GLOBAL_ENV: _dotenv_layer(global_file, ignore_empty=ignore_empty),
        ConfigSource.PROJECT_ENV: _dotenv_layer(project_file, ignore_empty=ignore_empty),
    }


def _system_layer() -> dict[str, str | None]:
    """系统环境变量层（只见**已声明字段**的名字：``EnvSettingsSource`` 会丢掉未知变量）。"""
    try:
        return dict(EnvSettingsSource(Settings)())
    except Exception as exc:  # noqa: BLE001 - 同上
        logger.warning("system environment layer is unusable: %s", exc)
        return {}


def system_env_keys() -> frozenset[str]:
    """当前进程环境里**提供了值**的字段名集合（小写字段名）。

    单一求解器：与 :func:`_solve` 的 ``system_env`` 层同一实现。写通道用它与面板的 ``writable=false``
    同源判定（脊柱 §8 第 3 步 / AC12）——系统环境变量优先级高于 ``.env``，因此写进 ``.env`` 的值
    当下**不生效**（实测：候选文件里的同名值根本不会被解析），必须拒绝而不是「写个日后生效的坏值」。
    """
    return frozenset(_system_layer())


def _solve(global_file: Path | None, project_file: Path) -> _Solved:
    """求解有效 ``Settings`` 与参与归属的层（显式 ``[全局, 项目]`` 路径，**不是**进程 cwd）。

    四级候选，逐级降级且**层与取值同步降级**（否则「来源说 project_env、值却来自全局」会自相矛盾，AC8）：

    1. **忠实口径**（``env_ignore_empty=False``，与运行期默认一致）+ ``[全局, 项目]``；
    2. **容错口径**（空值 = 未提供）——项目 ``.env`` 里存在 ``KEY=`` 时，bool/int 字段会让候选 1
       直接构造失败（实测，见探针 ``epic50_probe13``），此时按「空值即未提供」求解并点名该文件；
    3. **只留全局层**——项目 ``.env`` 的值非法（如 ``MAX_ITERATIONS=abc``）或编码不可解析；
    4. **一个 ``.env`` 都不读**——连全局文件都不可用。

    四级全败说明**系统环境变量**本身非法（进程级配置错误：运行时 ``Settings()`` 同样会失败），
    此时向上抛，不假装知道「有效值」。
    """
    global_files = [str(global_file)] if global_file is not None else []
    both_files = [*global_files, str(project_file)]
    attempts: tuple[tuple[type[_CatalogSettings], bool, list[str], tuple[ConfigSource, ...], tuple[str, ...]], ...] = (
        (_CatalogSettings, False, both_files, (ConfigSource.GLOBAL_ENV, ConfigSource.PROJECT_ENV), ()),
        (
            _LenientSettings,
            True,
            both_files,
            (ConfigSource.GLOBAL_ENV, ConfigSource.PROJECT_ENV),
            ("project_env_blank_values",),
        ),
        (_CatalogSettings, False, global_files, (ConfigSource.GLOBAL_ENV,), ("project_env_invalid",)),
        (_CatalogSettings, False, [], (), ("env_files_unavailable",)),
    )
    last_error: Exception | None = None
    for settings_cls, ignore_empty, env_files, used, notes in attempts:
        try:
            # ``_env_file`` 是 pydantic-settings 的**运行时**参数（`BaseSettings.__init__` 从 kwargs
            # 里取走它），但 pydantic 的 mypy 插件按字段合成的 `__init__` 签名看不到它。
            settings = settings_cls(_env_file=env_files)  # type: ignore[call-arg]
        except Exception as exc:  # noqa: BLE001 - 降级而非带崩：候选非法 ⇒ 换下一档
            last_error = exc
            logger.warning("config solve tier %s failed: %s", used, exc)
            continue
        layers = _dotenv_layers(global_file, project_file, ignore_empty=ignore_empty)
        layers[ConfigSource.SYSTEM_ENV] = _system_layer()
        for source in (ConfigSource.GLOBAL_ENV, ConfigSource.PROJECT_ENV):
            if source not in used:
                layers[source] = {}
        return _Solved(settings=settings, layers=layers, used=used, notes=notes)
    raise last_error if last_error is not None else RuntimeError("no configuration tier available")


def bom_prefixed_keys(layers: LayerMap) -> tuple[str, ...]:
    """所有层里**带 BOM 前缀**的键（T9b②：这些键不生效，必须显式标注而不是静默落 ``default``）。

    留作**绊线**：文件头 BOM 已由 :class:`_BomTolerantDotEnvSource` 剥掉，所以正常输入下这里是空的；
    一旦某个来源（或文件中部）漏出 ``'\\ufeffxxx'`` 形式的键名，面板就会点名它。
    """
    return tuple(sorted({key for keys in layers.values() for key in keys if key.startswith(BOM)}))


def _resolve_source(field_lower: str, layers: LayerMap) -> ConfigSource:
    """最后写入者（系统环境变量 > 项目 .env > 全局 .env > 默认值）。"""
    for source in (ConfigSource.SYSTEM_ENV, ConfigSource.PROJECT_ENV, ConfigSource.GLOBAL_ENV):
        if field_lower in layers[source]:
            return source
    return ConfigSource.DEFAULT


def _item_notes(
    field_lower: str, layers: LayerMap, scans: dict[ConfigSource, EnvScan], active: tuple[ConfigSource, ...]
) -> tuple[str, ...]:
    """该键在两层 ``.env`` 里的诊断（重复 / 空值 / 未解析 / BOM 前缀 / 行内注释）。

    ``active`` 是**真正参与归属**的层：整体被降级摘掉的层不再产逐项诊断（否则文件里每个键都会被
    标成「未解析」，把响应级的那一条 ``project_env_invalid`` 稀释成噪声）。
    """
    notes: list[str] = []
    for source in (ConfigSource.PROJECT_ENV, ConfigSource.GLOBAL_ENV):
        if source not in active:
            continue
        suffix = source.value
        values = layers[source]
        if f"{BOM}{field_lower}" in values:
            notes.append(f"bom_prefixed_in_{suffix}")
        scan = scans[source]
        if not scan.readable:
            continue
        as_written = scan.name_by_lower.get(field_lower)
        if as_written is None:
            # 文件里没有该键（键名被 BOM 前缀污染的情形已在上面的分支单独标注）。
            continue
        if values.get(field_lower) == "":
            # 空值行被接受成了一个空串（str 字段）——生效值确实是空的，如实标注。
            notes.append(f"empty_in_{suffix}")
            continue
        if field_lower not in values:
            # 声明了却没进层：空值（被当作未提供）或写法不受支持（如 export 之外的怪形式）。
            notes.append(f"empty_in_{suffix}" if as_written in scan.blank_keys else f"ineffective_in_{suffix}")
            continue
        if as_written in scan.duplicate_keys:
            notes.append(f"duplicate_in_{suffix}")
        if as_written in scan.inline_comment_keys:
            notes.append(f"inline_comment_in_{suffix}")
    return tuple(dict.fromkeys(notes))


def routing_report(settings: Settings) -> RoutingPoolsReport:
    """``ROUTING_POOLS`` 的**有效**结果（T8）：复用 ``Settings.routing_pool_map``（既有解析器）。

    「声明了但被忽略的条目」= 原始 JSON 里的条目名减去生效集合——只做**诊断**用的浅层 JSON 读取，
    绝不参与取值（取值与生效判据都来自既有解析器，它与运行期同源）。
    """
    raw = settings.routing_pools
    specs = settings.routing_pool_map
    payload: object | None
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except (json.JSONDecodeError, TypeError):
        payload = None
    declared = tuple(str(entry) for entry in payload) if isinstance(payload, dict) else ()
    return RoutingPoolsReport(
        declared_entries=declared,
        effective=tuple(
            RoutingPoolView(
                entry=entry,
                tiers=dict(spec.tiers),
                roles=dict(spec.roles),
                default=spec.default,
                keywords=dict(spec.keywords),
            )
            for entry, spec in specs.items()
        ),
        ignored_entries=tuple(entry for entry in declared if entry not in specs),
        invalid_json=bool(raw.strip()) and not isinstance(payload, dict),
    )


def _build_item(
    env_key: str,
    *,
    values: dict[str, Any],
    layers: LayerMap,
    scans: dict[ConfigSource, EnvScan],
    active: tuple[ConfigSource, ...],
    bom_stripped_head: str | None,
    routing: RoutingPoolsReport | None = None,
) -> ConfigItem:
    """装配一条配置项（值一律来自 ``Settings`` 快照）。"""
    field_lower = env_key.lower()
    secret = is_secret_key(env_key)
    source = _resolve_source(field_lower, layers)
    classification = classify(env_key)
    writable = classification.writable
    reason = classification.reason
    if writable and source is ConfigSource.SYSTEM_ENV:
        # 系统环境变量提供 ⇒ 改 .env 不生效（覆盖不了进程环境），因此不可写（AC2）。
        writable, reason = False, "system_env"
    notes = list(_item_notes(field_lower, layers, scans, active))
    if bom_stripped_head is not None and bom_stripped_head.lower() == field_lower:
        notes.append("bom_stripped_in_project_env")
    routing_view = routing if env_key == "ROUTING_POOLS" else None
    if routing_view is not None:
        if routing_view.invalid_json:
            notes.append("routing_pools_invalid")
        if routing_view.ignored_entries:
            notes.append("routing_pools_entries_ignored")
    configured = source is not ConfigSource.DEFAULT
    return ConfigItem(
        key=env_key,
        group=classification.group,
        value=None if secret else values.get(field_lower),
        source=source,
        writable=writable,
        read_only_reason=reason,
        is_secret=secret,
        configured=configured,
        masked=MASK if secret and configured else None,
        guards=guards_for(env_key),
        notes=tuple(notes),
        routing=routing_view,
    )


def _bounded(names: tuple[str, ...], limit: int = MAX_FILE_DIAGNOSTIC_KEYS) -> tuple[tuple[str, ...], bool]:
    """把**来自文件内容**的诊断列表截到上界（响应体不随 ``.env`` 膨胀）。"""
    return names[:limit], len(names) > limit


def _unknown_keys(
    scans: dict[ConfigSource, EnvScan], known: frozenset[str]
) -> tuple[tuple[UnknownKeyReport, ...], tuple[str, ...]]:
    """未知 / 拼错的键（AC5）+ 是否发生截断。

    依据**行级扫描**（文件里写了什么）而不是「参与归属的层」：整层因降级被摘掉时，文件里的未知键
    仍必须报出来——否则 AC5 的诊断恰在最需要它的输入上消失（评审发现·镜头二③）。两个门：文件不可读
    或**非 UTF-8**（键名会被替换字符污染）时不报。注意 ``EnvSettingsSource`` 会**丢掉**未知的系统
    环境变量（实测），因此系统层不可能贡献未知键。
    """
    found: list[UnknownKeyReport] = []
    for source, scan in scans.items():
        if not scan.readable or not scan.encoding_ok:
            continue
        for name in scan.declared_keys:
            if name.lower() in known:
                continue
            found.append(UnknownKeyReport(key=name, source=source))
    truncated = len(found) > MAX_UNKNOWN_KEYS
    return tuple(found[:MAX_UNKNOWN_KEYS]), (("unknown_keys_truncated",) if truncated else ())


def _group_reports(
    *,
    values: dict[str, Any],
    layers: LayerMap,
    scans: dict[ConfigSource, EnvScan],
    active: tuple[ConfigSource, ...],
    bom_stripped_head: str | None,
    routing: RoutingPoolsReport | None = None,
) -> tuple[ConfigGroupReport, ...]:
    """按声明式分组装配全部条目（每个 env 键恰好落在一组）。

    同一个 ``id`` 可以出现在多条 :class:`ConfigGroupSpec` 上（如 ``outbound`` / ``run_semantics``
    各有一条显式键行与一条模式行）——这里按 ``id`` **合并成一组**，标签取首次出现的那个。
    """
    labels: dict[str, str] = {}
    members: dict[str, list[str]] = {}
    for spec in (*_all_specs(), UNKNOWN_GROUP):
        labels.setdefault(spec.id, spec.label)
        members.setdefault(spec.id, [])
    for env_key in sorted(key.upper() for key in Settings.model_fields):
        members[classify(env_key).group].append(env_key)
    reports: list[ConfigGroupReport] = []
    for group_id, group_label in labels.items():
        keys = members[group_id]
        if not keys:
            continue
        items = tuple(
            _build_item(
                env_key,
                values=values,
                layers=layers,
                scans=scans,
                active=active,
                bom_stripped_head=bom_stripped_head,
                routing=routing,
            )
            for env_key in keys
        )
        reports.append(ConfigGroupReport(id=group_id, label=group_label, items=items))
    return tuple(reports)


def build_config_report(
    project_env_file: str | Path, *, global_env_file: str | Path | None = GLOBAL_CONFIG_FILE
) -> ConfigReport:
    """求解一个项目的有效配置（值 + 来源 + 可写性 + 诊断）。

    ``project_env_file`` 必须是**该项目**的 ``<工作区根>/.env`` 绝对路径（脊柱 I2：相对 ``.env``
    会按进程 cwd 解析，多项目下必然错位）。成本**实测**中位 14.0 ms/次（n=7，探针 ``epic50_probe14``；
    其中 ``Settings`` 构造 4.5 ms、行级扫描 0.13 ms、``model_dump`` 0.16 ms，其余为三个来源实例），
    响应约 38 KB——面板请求量级下**不引入缓存**：以指纹为键的缓存本身也要读文件，而陈旧快照与
    「生效语义 = 下一次 run」（I10）冲突。
    """
    project = Path(project_env_file).expanduser()
    global_file = Path(global_env_file).expanduser() if global_env_file is not None else None
    scans = {
        ConfigSource.PROJECT_ENV: scan_env_file(project),
        ConfigSource.GLOBAL_ENV: scan_env_file(global_file),
    }
    solved = _solve(global_file, project)
    layers = solved.layers

    notes: list[str] = list(solved.notes)
    project_scan = scans[ConfigSource.PROJECT_ENV]
    if not project_scan.exists:
        notes.append("project_env_missing")
    elif not project_scan.readable:
        notes.append("project_env_unreadable")
    if project_scan.has_bom:
        notes.append("project_env_bom_stripped")
    if bom_prefixed_keys(layers):
        notes.append("bom_prefixed_keys")

    values: dict[str, Any] = solved.settings.model_dump(mode="json")
    known = frozenset(key.lower() for key in Settings.model_fields)
    unknown, unknown_notes = _unknown_keys(scans, known)
    notes.extend(unknown_notes)
    duplicate_keys, duplicates_truncated = _bounded(project_scan.duplicate_keys)
    blank_keys, blanks_truncated = _bounded(project_scan.blank_keys)
    if duplicates_truncated or blanks_truncated:
        notes.append("file_diagnostics_truncated")
    bom_stripped_head = project_scan.declared_keys[0] if project_scan.has_bom and project_scan.declared_keys else None

    return ConfigReport(
        field_count=len(Settings.model_fields),
        groups=_group_reports(
            values=values,
            layers=layers,
            scans=scans,
            active=solved.used,
            bom_stripped_head=bom_stripped_head,
            routing=routing_report(solved.settings),
        ),
        env_file=EnvFileReport(
            path=str(project),
            exists=project_scan.exists,
            readable=project_scan.readable,
            fingerprint=project_scan.fingerprint,
            has_bom=project_scan.has_bom,
            line_count=project_scan.line_count,
            duplicate_keys=duplicate_keys,
            blank_keys=blank_keys,
        ),
        unknown_keys=unknown,
        labels=dict(LABELS),
        notes=tuple(dict.fromkeys(notes)),
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
    "is_secret_key",
    "routing_report",
    "scan_env_file",
    "system_env_keys",
    "whitelist",
]
