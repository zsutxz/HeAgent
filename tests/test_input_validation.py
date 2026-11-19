"""统一输入验证框架（``heagent.pub.validation``）与配置写入接入点的判定测试（Story 67.1）。

三块：

1. 六类内置规则（required / type / min_length / max_length / pattern / enum）各自的失败形状；
2. 自定义规则（callable）与聚合形状（逐字段一行、每字段最多一条、多字段全列）；
3. **接入点**：``config.write.guard_reason`` 改写前后的对外形状 —— 原因文案逐字不变，且判定确实
   经过框架（``heagent.config.write.validate`` 被调用，不存在框架之外的第二套取值判定）。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from heagent.config.write import (
    ConfigChange,
    ConfigWriteCode,
    ConfigWriteRejection,
    guard_reason,
    validate_changes,
)
from heagent.pub.exceptions import HeAgentError
from heagent.pub.validation import InputValidationError, Rule, ValidationIssue, collect_issues, validate

SRC = Path(__file__).resolve().parents[1] / "src"


def _issues(data: dict[str, object], *rules: Rule) -> list[ValidationIssue]:
    return collect_issues(data, rules)


class TestRequiredRule:
    def test_missing_field_is_reported(self) -> None:
        issues = _issues({}, Rule(field="name", required=True))

        assert [(issue.field, issue.rule, issue.message) for issue in issues] == [("name", "required", "is required")]

    def test_none_counts_as_missing(self) -> None:
        assert _issues({"name": None}, Rule(field="name", required=True))[0].rule == "required"

    def test_optional_field_may_be_absent(self) -> None:
        assert _issues({}, Rule(field="name")) == []
        assert _issues({}, Rule(field="name", type="string")) == []


class TestTypeRule:
    @pytest.mark.parametrize(
        ("rule_type", "value", "message"),
        [
            ("string", 1, "must be a string"),
            ("integer", "1", "must be an integer"),
            ("number", "1.5", "must be a number"),
            ("boolean", "true", "must be a boolean"),
            ("array", "item", "must be a list"),
            ("object", ["item"], "must be an object"),
        ],
    )
    def test_type_mismatch(self, rule_type: str, value: object, message: str) -> None:
        issues = _issues({"value": value}, Rule(field="value", type=rule_type))  # type: ignore[arg-type]

        assert issues[0].rule == "type"
        assert issues[0].message == message

    def test_bool_is_not_a_number(self) -> None:
        """``True`` 是 ``int`` 子类，但「布尔不是数字」——否则 ``type="number"`` 会放行 ``True``。"""
        assert _issues({"n": True}, Rule(field="n", type="number"))[0].message == "must be a number"
        assert _issues({"n": True}, Rule(field="n", type="integer"))[0].message == "must be an integer"

    def test_matching_type_passes(self) -> None:
        assert _issues({"n": 1}, Rule(field="n", type="integer")) == []
        assert _issues({"n": 1.5}, Rule(field="n", type="number")) == []
        assert _issues({"n": False}, Rule(field="n", type="boolean")) == []


class TestLengthRules:
    def test_below_min_length(self) -> None:
        issues = _issues({"name": "ab"}, Rule(field="name", min_length=3))

        assert issues[0].rule == "min_length"
        assert issues[0].message == "must be at least 3 characters"

    def test_above_max_length(self) -> None:
        issues = _issues({"name": "abcd"}, Rule(field="name", max_length=3))

        assert issues[0].rule == "max_length"
        assert issues[0].message == "must be at most 3 characters"

    def test_length_applies_to_sized_containers(self) -> None:
        assert _issues({"tags": []}, Rule(field="tags", min_length=1))[0].rule == "min_length"

    def test_within_bounds_passes(self) -> None:
        assert _issues({"name": "abcd"}, Rule(field="name", min_length=3)) == []
        assert _issues({"name": "ab"}, Rule(field="name", max_length=3)) == []

    def test_non_sized_value_is_left_to_the_type_rule(self) -> None:
        """不可度量的值只报一条（``type``），不额外报长度——避免级联噪声。"""
        issues = _issues({"n": 5}, Rule(field="n", type="number", max_length=3))

        assert [issue.rule for issue in issues] == []


class TestPatternRule:
    def test_pattern_mismatch(self) -> None:
        issues = _issues({"code": "abc-1"}, Rule(field="code", pattern=r"^[a-z]+$"))

        assert issues[0].rule == "pattern"
        assert issues[0].message == r"must match ^[a-z]+$"

    def test_pattern_uses_search_semantics(self) -> None:
        """``pattern`` 与 JSON Schema 同义（``re.search``）：不要求整串匹配。"""
        assert _issues({"code": "abc123"}, Rule(field="code", pattern=r"^[a-z]+")) == []


class TestEnumRule:
    def test_out_of_range_value(self) -> None:
        issues = _issues({"level": "BANANA"}, Rule(field="level", enum=("DEBUG", "INFO")))

        assert (issues[0].rule, issues[0].message) == ("enum", "must be one of DEBUG, INFO")

    def test_member_passes(self) -> None:
        assert _issues({"level": "INFO"}, Rule(field="level", enum=("DEBUG", "INFO"))) == []


class TestCustomRule:
    def test_false_uses_the_rule_label(self) -> None:
        issues = _issues({"port": 1}, Rule(field="port", label="port", check=lambda value: value > 1024))

        assert (issues[0].rule, issues[0].message) == ("port", "must satisfy port")

    def test_returned_string_is_the_reason(self) -> None:
        def check(value: object) -> str | None:
            return None if value == "ok" else "must be exactly ok"

        issues = _issues({"state": "bad"}, Rule(field="state", label="state", check=check))

        assert (issues[0].rule, issues[0].message) == ("state", "must be exactly ok")

    def test_true_and_none_pass(self) -> None:
        assert _issues({"n": 1}, Rule(field="n", check=lambda value: True)) == []
        assert _issues({"n": 1}, Rule(field="n", check=lambda value: None)) == []

    def test_illegal_return_value_fails_loud(self) -> None:
        """契约外返回值必须炸——静默当通过会让「校验器写错」变成「校验形同虚设」。"""
        with pytest.raises(TypeError, match="must return"):
            collect_issues({"n": 1}, [Rule(field="n", check=lambda value: 42)])


class TestAggregation:
    def test_pass_is_silent(self) -> None:
        validate({"name": "ok", "level": "INFO"}, [Rule(field="name", required=True), Rule(field="level")])

    def test_error_lists_every_field_once(self) -> None:
        rules = [
            Rule(field="name", required=True, type="string"),
            Rule(field="level", enum=("DEBUG", "INFO")),
        ]

        with pytest.raises(InputValidationError) as excinfo:
            validate({"level": "BANANA"}, rules)

        error = excinfo.value
        assert isinstance(error, HeAgentError)
        assert [issue.field for issue in error.issues] == ["name", "level"]
        assert str(error) == "invalid input: name: is required; level: must be one of DEBUG, INFO"

    def test_fields_property_dedupes_and_keeps_order(self) -> None:
        error = InputValidationError(
            [
                ValidationIssue(field="a", rule="required", message="is required"),
                ValidationIssue(field="b", rule="type", message="must be a string"),
                ValidationIssue(field="a", rule="enum", message="must be one of x"),
            ]
        )

        assert error.fields == ("a", "b")

    def test_unrelated_keys_are_ignored(self) -> None:
        """字段形状归 Pydantic 模型管；框架只判它声明的字段。"""
        assert _issues({"name": "ok", "extra": object()}, Rule(field="name", type="string")) == []


class TestLayerBoundary:
    """``pub/`` 层零 heagent 依赖：只许 stdlib + pydantic + 同层 ``pub``（``network/`` 因此可用）。"""

    def test_validation_module_only_imports_stdlib_and_pydantic(self) -> None:
        tree = ast.parse((SRC / "heagent" / "pub" / "validation.py").read_text(encoding="utf-8"))
        heagent_imports: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("heagent"):
                heagent_imports.update(f"{node.module}.{alias.name}" for alias in node.names)
            elif isinstance(node, ast.Import):
                heagent_imports.update(alias.name for alias in node.names if alias.name.startswith("heagent"))

        assert heagent_imports == {"heagent.pub.exceptions.InputValidationError"}


class TestConfigWriteEntryPoint:
    """接入点 ``config.write.guard_reason``：**对外原因文案逐字不变**，判定经框架。"""

    @pytest.mark.parametrize(
        ("key", "value", "reason"),
        [
            # 枚举（框架原生 enum 规则）
            ("LOG_LEVEL", "BANANA", "must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL"),
            # 空串放行 + 枚举（自定义 check）
            ("LOG_FILE_LEVEL", "", None),
            ("LOG_FILE_LEVEL", "LOUD", "must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL"),
            # 上下界（自定义 check）：解析 → 有限性 → 边界，顺序即报错顺序
            ("RETRY_MAX_ATTEMPTS", "11", "must be at most 10"),
            ("RETRY_BASE_DELAY", "-1", "must be at least 0"),
            ("RETRY_BASE_DELAY", "abc", "must be a number"),
            ("RETRY_BASE_DELAY", "nan", "must be a finite number"),
            ("MAX_ITERATIONS", "999999", "must be at most 10000"),
            # 无约束的键不判定
            ("DEFAULT_MODEL", "anything", None),
        ],
    )
    def test_reason_shape_is_unchanged(self, key: str, value: str, reason: str | None) -> None:
        assert guard_reason(key, value) == reason

    def test_decision_runs_through_the_framework(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """守卫的「过/不过」只由框架判：打桩后枚举与上下界两条路径都必须走到 ``validate``。"""
        from heagent.config import write as write_module

        calls: list[tuple[object, tuple[object, ...]]] = []
        original = write_module.validate

        def spy(data: object, fields: object) -> None:
            calls.append((data, tuple(fields)))  # type: ignore[arg-type]
            original(data, fields)  # type: ignore[arg-type]

        monkeypatch.setattr(write_module, "validate", spy)

        assert guard_reason("LOG_LEVEL", "BANANA") == "must be one of DEBUG, INFO, WARNING, ERROR, CRITICAL"
        assert guard_reason("RETRY_MAX_ATTEMPTS", "11") == "must be at most 10"
        assert guard_reason("DEFAULT_MODEL", "anything") is None  # 无守卫 ⇒ 不判定

        assert [data for data, _ in calls] == [{"LOG_LEVEL": "BANANA"}, {"RETRY_MAX_ATTEMPTS": "11"}]
        enum_rule, range_rule = calls[0][1][0], calls[1][1][0]
        # 枚举走框架原生 enum 规则（未设 label ⇒ 天然是 "enum"）；上下界走自定义 check + label。
        assert (enum_rule.field, enum_rule.enum, enum_rule.check) == (
            "LOG_LEVEL",
            ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
            None,
        )
        assert (range_rule.field, range_rule.label, range_rule.enum) == ("RETRY_MAX_ATTEMPTS", "range", None)

    def test_framework_error_is_internal_only(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """框架异常不外泄：对外仍是 ``ConfigWriteRejection``，原因等于框架的首条 issue message。"""
        from heagent.config import write as write_module

        captured: list[InputValidationError] = []
        original = write_module.validate

        def capture(data: object, fields: object) -> None:
            try:
                original(data, fields)  # type: ignore[arg-type]
            except InputValidationError as exc:
                captured.append(exc)
                raise

        monkeypatch.setattr(write_module, "validate", capture)

        with pytest.raises(ConfigWriteRejection) as excinfo:
            validate_changes([ConfigChange(key="MAX_ITERATIONS", value="999999")])

        assert excinfo.value.code == ConfigWriteCode.INVALID_VALUE
        assert str(excinfo.value) == "MAX_ITERATIONS: must be at most 10000"
        assert [(issue.field, issue.rule, issue.message) for issue in captured[0].issues] == [
            ("MAX_ITERATIONS", "range", "must be at most 10000")
        ]

    def test_every_issue_carries_the_key_it_was_judged_for(self) -> None:
        """守卫是每键单值判定：框架里 ``field`` 就是 env 键，issue 直接可定位。"""
        issues = collect_issues({"LOG_FORMAT": "xml"}, [Rule(field="LOG_FORMAT", enum=("text", "json"))])

        assert issues[0].field == "LOG_FORMAT"
        assert guard_reason("LOG_FORMAT", "xml") == issues[0].message
