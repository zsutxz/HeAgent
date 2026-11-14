"""取值守卫与影响面：字段上界、值域守卫与 impact 分级。

自 ``heagent.config.catalog`` 单文件拆出（E3 绞杀者），行为零改动。
"""

from __future__ import annotations

from typing import Any, Literal, get_args, get_origin

from heagent.config import Settings

from .models import ConfigGuard

#: **白名单里所有「只有下界」的数值键**的上界表。
#:
#: 为什么需要它：``Settings`` 对这些字段只给了下界（``ge=…``），而守卫清单只收弱校验键
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
#:   ``MAX_OUTPUT_TOKENS`` 则取最大真实模型输出窗口的约 8 倍）、归档节流 ``31536000`` 秒（1 年；
#:   其默认值 1 天已比 seconds 族高两个量级，理由见 :data:`RESOURCE_CEILINGS` 表尾）。
RESOURCE_CEILINGS: dict[str, float] = {
    # days = 3650：保留期 / 时间窗（默认值 7–30 天）
    "EDIT_SNAPSHOT_RETENTION_DAYS": 3650.0,
    "LEDGER_RETENTION_DAYS": 3650.0,
    "LOG_RETENTION_DAYS": 3650.0,
    "RUN_RETENTION_DAYS": 3650.0,
    # 同族时间窗按小时计：3650 天 = 87600 小时（陈旧 running 收尾阈值，默认 6h）
    "RUN_STALE_IDLE_HOURS": 87600.0,
    "SANDBOX_DIR_RETENTION_DAYS": 3650.0,
    "SESSION_RETENTION_DAYS": 3650.0,
    "SKILL_CURATOR_STALE_DAYS": 3650.0,
    # seconds = 604800：间隔 / 超时（默认值 60 / 900 秒）
    "CRON_TICK_SECONDS": 604800.0,
    "PRUNE_MIN_INTERVAL_SECONDS": 604800.0,
    # bytes = 8388608：文本预算（默认值 32768 / 98304 / 49152）
    "CONTEXT_FILES_MAX_BYTES": 8_388_608.0,
    "MEMORY_INJECT_MAX_BYTES": 8_388_608.0,
    "MEMORY_ARCHIVE_TRIGGER_BYTES": 8_388_608.0,
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
    # 归档节流（自成刻度）= 31536000（1 年）：默认值 1 天（86 400 s）比 seconds 族其它键（60–900 s）
    # 高两个量级 —— 套用 604800 会违反「上界 ≥ 10 × 默认值」这条护栏；「禁用节流」用 0 表达。
    "MEMORY_ARCHIVE_MIN_INTERVAL_SECONDS": 31_536_000.0,
}


#: 弱校验键的**字段级守卫**（开放弱校验键的强制前提；不改 ``Settings`` 定义）。
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


#: 高影响键的**事实源**：与 ``RESOURCE_CEILINGS`` 同源 —— 有上界的键就是「极端值能让一次运行不可
#: 完成」的资源旋钮（「写入被标记为高影响的键必须显式确认」的后端风险标记）。
#: 刻意**不新造分类表**：``RESOURCE_CEILINGS`` 已被测试钉死，且它的语义正是这个分级要表达的东西。
IMPACT_HIGH = "high"
IMPACT_NORMAL = "normal"


def impact_for(env_key: str) -> str:
    """该键的风险标记：``high`` = 资源旋钮（有上界），否则 ``normal``。

    **只作用于面板提示**（defense-in-depth）：写通道的值守卫与 fail-closed 校验不因它改变。
    分级完全由服务端声明 —— 前端不得硬编码任何键名（冻结边界：硬编码清单是第二份事实源，
    必然与 :func:`whitelist` / :data:`RESOURCE_CEILINGS` 漂移）。
    """
    return IMPACT_HIGH if env_key in RESOURCE_CEILINGS else IMPACT_NORMAL


def guards_for(env_key: str) -> ConfigGuard | None:
    """该键的合法约束（``None`` = 无约束可用）。"""
    field_info = Settings.model_fields.get(env_key.lower())
    derived = _derive_guard(field_info) if field_info is not None else None
    explicit = VALUE_GUARDS.get(env_key)
    if explicit is not None:
        return _merge_guard(explicit, derived)
    return derived
