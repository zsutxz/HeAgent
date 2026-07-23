"""Story A.2: Cron 范围表达式扩展测试。"""

from datetime import datetime

import pytest

from heagent.cron.scheduler import CronScheduler, _parse_field


class TestCronRangeExpressions:
    """V2 新增：Cron 范围表达式支持。"""

    def test_range_basic_1_5(self):
        """_parse_field("1-5", min_val=1, max_val=31) → [1,2,3,4,5]"""
        result = _parse_field("1-5", min_val=1, max_val=31)
        assert result == [1, 2, 3, 4, 5]

    def test_range_hour_9_17(self):
        """_parse_field("9-17", min_val=0, max_val=23) → [9,...,17]"""
        result = _parse_field("9-17", min_val=0, max_val=23)
        assert result == list(range(9, 18))

    def test_step_basic_star_15(self):
        """_parse_field("*/15", min_val=0, max_val=59) → [0,15,30,45]"""
        result = _parse_field("*/15", min_val=0, max_val=59)
        assert result == [0, 15, 30, 45]

    def test_step_hour_star_4(self):
        """_parse_field("*/4", min_val=0, max_val=23) → [0,4,8,12,16,20]"""
        result = _parse_field("*/4", min_val=0, max_val=23)
        assert result == [0, 4, 8, 12, 16, 20]

    def test_range_with_step_1_30_10(self):
        """_parse_field("1-30/10", min_val=1, max_val=31) → [1,11,21]"""
        result = _parse_field("1-30/10", min_val=1, max_val=31)
        assert result == [1, 11, 21]

    def test_comma_with_range(self):
        """_parse_field("1-3,7-9", min_val=0, max_val=59) → [1,2,3,7,8,9]"""
        result = _parse_field("1-3,7-9", min_val=0, max_val=59)
        assert result == [1, 2, 3, 7, 8, 9]

    def test_star_alone(self):
        """_parse_field("*", min_val=0, max_val=5) → [0,1,2,3,4,5]"""
        result = _parse_field("*", min_val=0, max_val=5)
        assert result == [0, 1, 2, 3, 4, 5]

    def test_single_digit(self):
        """_parse_field("5", min_val=0, max_val=59) → [5]"""
        result = _parse_field("5", min_val=0, max_val=59)
        assert result == [5]

    def test_comma_list(self):
        """_parse_field("1,3,5,7", min_val=0, max_val=59) → [1,3,5,7]"""
        result = _parse_field("1,3,5,7", min_val=0, max_val=59)
        assert result == [1, 3, 5, 7]

    def test_invalid_range_non_numeric_raises(self):
        """_parse_field("a-b", min_val=0, max_val=59) → ValueError"""
        with pytest.raises(ValueError, match="Invalid cron range"):
            _parse_field("a-b", min_val=0, max_val=59)

    def test_invalid_range_out_of_bounds_raises(self):
        """_parse_field("1-100", min_val=0, max_val=59) → ValueError"""
        with pytest.raises(ValueError, match="out of"):
            _parse_field("1-100", min_val=0, max_val=59)

    def test_invalid_step_zero_raises(self):
        """_parse_field("*/0", min_val=0, max_val=59) → ValueError"""
        with pytest.raises(ValueError, match="must be positive"):
            _parse_field("*/0", min_val=0, max_val=59)

    def test_invalid_range_reversed_raises(self):
        """_parse_field("5-1", min_val=0, max_val=59) → ValueError"""
        with pytest.raises(ValueError, match="start"):
            _parse_field("5-1", min_val=0, max_val=59)

    def test_out_of_bounds_value_raises(self):
        """_parse_field("60", min_val=0, max_val=59) → ValueError"""
        with pytest.raises(ValueError, match="out of range"):
            _parse_field("60", min_val=0, max_val=59)

    def test_invalid_expression_raises(self):
        """_parse_field("abc", min_val=0, max_val=59) → ValueError"""
        with pytest.raises(ValueError, match="Invalid cron field"):
            _parse_field("abc", min_val=0, max_val=59)


class TestCronMatchesWithRanges:
    """端到端：CronScheduler._matches 对范围表达式的行为。"""

    def test_weekday_range_mon_to_fri(self):
        """工作日 9-17 每 30 分钟：*/30 9-17 * * 1-5"""
        expr = "*/30 9-17 * * 1-5"
        # 周三 10:00 → 匹配
        dt_match = datetime(2026, 7, 22, 10, 0)  # 周三
        assert CronScheduler._matches(expr, dt_match) is True
        # 周三 10:15 → 30 分步进不匹配
        dt_nomatch = datetime(2026, 7, 22, 10, 15)
        assert CronScheduler._matches(expr, dt_nomatch) is False

    def test_weekday_range_saturday_excluded(self):
        """工作日表达式在周六不匹配"""
        expr = "0 9 * * 1-5"
        dt = datetime(2026, 7, 25, 9, 0)  # 周六
        assert CronScheduler._matches(expr, dt) is False

    def test_weekday_range_sunday_excluded(self):
        """工作日表达式在周日不匹配"""
        expr = "0 9 * * 1-5"
        dt = datetime(2026, 7, 26, 9, 0)  # 周日
        assert CronScheduler._matches(expr, dt) is False

    def test_hour_range_inside_matches(self):
        """小时范围 9-17 内匹配"""
        expr = "0 9-17 * * *"
        dt = datetime(2026, 7, 22, 14, 0)
        assert CronScheduler._matches(expr, dt) is True

    def test_hour_range_outside_no_match(self):
        """小时范围 9-17 外不匹配"""
        expr = "0 9-17 * * *"
        dt = datetime(2026, 7, 22, 8, 0)
        assert CronScheduler._matches(expr, dt) is False

    def test_day_range_inside_matches(self):
        """日期范围 1-15 内匹配"""
        expr = "0 0 1-15 * *"
        dt = datetime(2026, 7, 10, 0, 0)
        assert CronScheduler._matches(expr, dt) is True

    def test_day_range_outside_no_match(self):
        """日期范围 1-15 外不匹配"""
        expr = "0 0 1-15 * *"
        dt = datetime(2026, 7, 20, 0, 0)
        assert CronScheduler._matches(expr, dt) is False

    def test_range_with_step_in_cron_expr(self):
        """1-31/5 * * * * → 在第 1/6/11/16/21/26/31 天匹配"""
        expr = "0 0 1-31/5 * *"
        assert CronScheduler._matches(expr, datetime(2026, 7, 1, 0, 0)) is True
        assert CronScheduler._matches(expr, datetime(2026, 7, 6, 0, 0)) is True
        assert CronScheduler._matches(expr, datetime(2026, 7, 2, 0, 0)) is False
        assert CronScheduler._matches(expr, datetime(2026, 7, 3, 0, 0)) is False

    def test_backward_compat_star_still_works(self):
        """V1 '*' 语法仍然工作"""
        expr = "* * * * *"
        dt = datetime(2026, 7, 22, 10, 30)
        assert CronScheduler._matches(expr, dt) is True

    def test_backward_compat_comma_still_works(self):
        """V1 逗号语法仍然工作"""
        expr = "0 9,12,18 * * *"
        assert CronScheduler._matches(expr, datetime(2026, 7, 22, 9, 0)) is True
        assert CronScheduler._matches(expr, datetime(2026, 7, 22, 12, 0)) is True
        assert CronScheduler._matches(expr, datetime(2026, 7, 22, 10, 0)) is False

    def test_backward_compat_step_still_works(self):
        """V1 */step 语法仍然工作"""
        expr = "*/5 * * * *"
        assert CronScheduler._matches(expr, datetime(2026, 7, 22, 10, 30)) is True
        assert CronScheduler._matches(expr, datetime(2026, 7, 22, 10, 32)) is False

    def test_sunday_0_and_7_both_work(self):
        """Sunday 用 0 和 7 都匹配"""
        # July 26 2026 is Sunday
        expr0 = "0 0 * * 0"
        expr7 = "0 0 * * 7"
        dt = datetime(2026, 7, 26, 0, 0)
        assert CronScheduler._matches(expr0, dt) is True
        assert CronScheduler._matches(expr7, dt) is True

    def test_sunday_range_5_to_7_matches_sunday(self):
        """P1-12 扩展：周五-周日范围 (5-7) 匹配周日——7→0 规范化覆盖范围语法"""
        # July 24 2026 = Friday, July 25 = Saturday, July 26 = Sunday
        expr = "0 0 * * 5-7"
        assert CronScheduler._matches(expr, datetime(2026, 7, 24, 0, 0)) is True  # 周五
        assert CronScheduler._matches(expr, datetime(2026, 7, 25, 0, 0)) is True  # 周六
        assert CronScheduler._matches(expr, datetime(2026, 7, 26, 0, 0)) is True  # 周日
        assert CronScheduler._matches(expr, datetime(2026, 7, 22, 0, 0)) is False  # 周三

    def test_sunday_range_0_to_7_matches_sunday(self):
        """周日经由范围 0-7 匹配（0 和 7 都在范围内）"""
        expr = "0 0 * * 0-7"
        dt = datetime(2026, 7, 26, 0, 0)  # 周日
        assert CronScheduler._matches(expr, dt) is True

    def test_sunday_comma_list_with_7_matches_sunday(self):
        """周末列表 0,6,7 匹配周日——7→0 规范化覆盖逗号列表"""
        expr = "0 0 * * 0,6,7"
        # July 26 2026 = Sunday
        assert CronScheduler._matches(expr, datetime(2026, 7, 26, 0, 0)) is True  # 周日
        assert CronScheduler._matches(expr, datetime(2026, 7, 25, 0, 0)) is True  # 周六
        assert CronScheduler._matches(expr, datetime(2026, 7, 22, 0, 0)) is False  # 周三

    def test_sunday_step_with_7_normalized(self):
        """隔天步进 */2 在周日匹配——7→0 规范化不影响步进展开"""
        # */2 over 0-7 → [0,2,4,6]; after 7→0 normalization → [0,2,4,6]
        # July 26 2026 = Sunday (value=0) → 0 in [0,2,4,6] → True
        expr = "0 0 * * */2"
        dt = datetime(2026, 7, 26, 0, 0)  # 周日
        assert CronScheduler._matches(expr, dt) is True
