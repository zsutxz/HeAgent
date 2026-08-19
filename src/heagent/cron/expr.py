"""5 字段 cron 表达式解析与匹配——纯叶子，零 heagent 导入。

抽自 :mod:`heagent.cron.scheduler`（解耦 ``memory/dream.py`` → ``cron.scheduler`` 横向
reach-through：dream 不再伸手进 ``CronScheduler`` 私有静态，改用本模块公共函数）。
本模块是纯函数簇（无 I/O、无 heagent 依赖），供 ``cron/scheduler``（包内）与
``memory/dream``（纯叶子依赖，类比 ``engine.persist``）共用。

DAG：零 heagent 导入——可被任意上层模块依赖而不引入横向耦合。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from datetime import datetime

__all__ = ["cron_matches"]


def cron_matches(cron_expr: str, dt: datetime) -> bool:
    """Evaluate a 5-field cron expression with range/step support (V2)."""
    parts = cron_expr.strip().split()
    if len(parts) != 5:
        return False

    # weekday：标准 cron 中 Sunday 同时用 0 和 7 表示，此处映射到 0；
    # _field_matches 内部对 weekday 字段 (max_val=7) 统一做 7→0 规范化。
    cron_weekday = (dt.weekday() + 1) % 7  # Monday=1...Sunday=0
    cron_values = (dt.minute, dt.hour, dt.day, dt.month, cron_weekday)
    # 每个字段的合法范围（用于解析范围表达式）
    field_ranges = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))
    return all(
        _field_matches(expr, value, min_val=rng[0], max_val=rng[1])
        for expr, value, rng in zip(parts, cron_values, field_ranges, strict=True)
    )


def _field_matches(expr: str, value: int, *, min_val: int = 0, max_val: int = 59) -> bool:
    """Return whether one cron field matches one numeric value.

    V2 扩展：支持范围表达式（``1-5``）和步进组合（``*/15`` / ``1-30/10``）。
    内部走 ``_parse_field`` 统一解析 → 查值是否在展开列表中。

    P1-12 扩展修复：对 weekday 字段 (max_val==7) 统一把 cron ``"7"``（周日）
    映射到内部值 0（周日），覆盖单值 ``"7"``、范围 ``"5-7"``、列表 ``"1,3,7"``
    等全部语法。原修复仅覆盖 ``expr=="7"`` 的精确匹配，范围/列表中的 7 会漏判周日。
    """
    values = _parse_field(expr, min_val=min_val, max_val=max_val)
    if max_val == 7:
        values = [0 if v == 7 else v for v in values]
    return value in values


def _parse_field(raw: str, *, min_val: int = 0, max_val: int = 59) -> list[int]:
    """统一解析 cron 字段为展开数值列表（V2 新增）。

    支持的语法：
    - ``*`` → [min_val, ..., max_val]
    - 单个数值 ``"5"`` → [5]
    - 逗号列表 ``"1,3,5"`` → [1, 3, 5]
    - 范围 ``"1-5"`` → [1, 2, 3, 4, 5]
    - 步进 ``"*/15"`` → 从 min_val 开始每隔 step 的值
    - 范围+步进 ``"1-30/10"`` → [1, 11, 21]
    """
    raw = raw.strip()
    result: list[int] = []

    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue

        # 范围+步进: "1-30/10"
        if "/" in part and "-" in part:
            range_part, step_str = part.split("/", 1)
            # 畸形输入如 "*/5-10"（"-" 仅出现在步进侧）会让 range_part 缺 "-"，
            # 直接 split 解包会抛内部 "not enough values to unpack"；此处先校验，
            # 抛域级错误（Epic 35 收尾）。
            if "-" not in range_part:
                raise ValueError(f"Invalid cron field expression: {part!r}")
            start_str, end_str = range_part.split("-", 1)
            start, end, step = _validate_range_parts(start_str, end_str, step_str, min_val, max_val)
            result.extend(range(start, end + 1, step))

        # 纯步进: "*/15"
        elif part.startswith("*/"):
            step_str = part[2:]
            if not step_str or not step_str.isdigit():
                raise ValueError(f"Invalid step in cron field: {part!r}")
            step = int(step_str)
            if step <= 0:
                raise ValueError(f"Cron step must be positive: {step}")
            result.extend(range(min_val, max_val + 1, step))

        # 纯范围: "1-5"
        elif "-" in part:
            start_str, end_str = part.split("-", 1)
            start, end = _parse_range_bounds(start_str, end_str, min_val, max_val)
            result.extend(range(start, end + 1))

        # 通配符 "*"
        elif part == "*":
            result.extend(range(min_val, max_val + 1))

        # 单个数值 "5"
        elif part.isdigit():
            v = int(part)
            if v < min_val or v > max_val:
                raise ValueError(f"Cron value {v} out of range [{min_val}, {max_val}]")
            result.append(v)

        else:
            raise ValueError(f"Invalid cron field expression: {part!r}")

    return sorted(set(result))


def _parse_range_bounds(start_str: str, end_str: str, min_val: int, max_val: int) -> tuple[int, int]:
    """解析并校验范围边界。"""
    if not start_str.isdigit() or not end_str.isdigit():
        raise ValueError(f"Invalid cron range: {start_str}-{end_str}")
    start = int(start_str)
    end = int(end_str)
    if start < min_val or end > max_val:
        raise ValueError(f"Cron range {start}-{end} out of [{min_val}, {max_val}]")
    if start > end:
        raise ValueError(f"Cron range start {start} > end {end}")
    return start, end


def _validate_range_parts(
    start_str: str, end_str: str, step_str: str, min_val: int, max_val: int
) -> tuple[int, int, int]:
    """解析并校验范围+步进参数。"""
    start, end = _parse_range_bounds(start_str, end_str, min_val, max_val)
    if not step_str.isdigit():
        raise ValueError(f"Invalid cron step: {step_str!r}")
    step = int(step_str)
    if step <= 0:
        raise ValueError(f"Cron step must be positive: {step}")
    return start, end, step
