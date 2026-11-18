"""统一输入验证框架：一条 ``Rule`` 链 + 结构化 issue + 统一异常。

为什么住 ``pub/``：各入口原先自行校验，失败形状互不相同（HTTP 用 Pydantic 的错误串、CLI 用 Click 的
参数错误、配置写入用 ``config/write`` 的守卫文案）。本模块给它们一个共同的**最小**判定面——而
``network/`` 只被允许依赖 stdlib + Pydantic + ``pub``，所以这里也是传输层唯一可用的落点。

分工（刻意不重造类型系统）：Pydantic 模型继续负责**结构**校验；本框架只补「业务级 / 需要逐字段可读
原因」的规则，以及把失败收敛成同一形状。判定顺序固定为

    required → type → min_length → max_length → pattern → enum → check

**每个字段最多报一条** issue：缺字段时不再连带报「类型不符」这类级联噪声，多字段的问题仍会全部列出
（一个字段一行）。

自定义规则就是 :attr:`Rule.check`（callable），返回约定：

- ``None`` / ``True`` —— 通过；
- ``False`` —— 失败，原因取 ``must satisfy <label>``；
- ``str`` —— 失败，且该字符串**就是**原因（域内特有文案不必改框架）。

用法::

    validate(
        {"level": "BANANA"},
        [Rule(field="level", required=True, enum=("DEBUG", "INFO"))],
    )   # → raise InputValidationError: "invalid input: level: must be one of DEBUG, INFO"

:func:`collect_issues` 是同一判定的列表版（不抛异常），供「先收集再一起展示」的调用方使用。
"""

from __future__ import annotations

import re
from collections.abc import Callable  # noqa: TC003 - pydantic 在类创建期解析注解，运行期需真实对象
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from heagent.pub.exceptions import HeAgentError

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

#: ``Rule.type`` 的取值域（JSON Schema 的常用子集；``array`` 读作「列表」）。
RuleType = Literal["string", "number", "integer", "boolean", "array", "object"]

#: 类型规则失败时的可读宾语（``must be a number`` / ``must be an integer``）。
_TYPE_NOUNS: dict[str, str] = {
    "string": "a string",
    "number": "a number",
    "integer": "an integer",
    "boolean": "a boolean",
    "array": "a list",
    "object": "an object",
}


def _is_number(value: Any) -> bool:
    """``bool`` 是 ``int`` 的子类，但 ``True`` 不是「一个数字」——类型规则必须显式排除。"""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


_TYPE_CHECKS: dict[str, Callable[[Any], bool]] = {
    "string": lambda value: isinstance(value, str),
    "number": _is_number,
    "integer": lambda value: isinstance(value, int) and not isinstance(value, bool),
    "boolean": lambda value: isinstance(value, bool),
    "array": lambda value: isinstance(value, (list, tuple)),
    "object": lambda value: isinstance(value, dict),
}


class ValidationIssue(BaseModel):
    """一条失败判定：**哪个字段**（``field``）、**哪条规则**（``rule``）、**为什么**（``message``）。

    ``message`` **不含**字段名前缀——调用方据此决定自己怎么拼（配置写入要的就是这条裸原因，
    聚合展示则由 :class:`InputValidationError` 统一加前缀）。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str
    rule: str
    message: str


class InputValidationError(HeAgentError):
    """统一失败异常：``str()`` 逐字段列出问题，CLI / HTTP 可直接展示，不必二次拼装。"""

    def __init__(self, issues: Iterable[ValidationIssue]) -> None:
        self.issues: tuple[ValidationIssue, ...] = tuple(issues)
        super().__init__("invalid input: " + "; ".join(f"{issue.field}: {issue.message}" for issue in self.issues))

    @property
    def fields(self) -> tuple[str, ...]:
        """涉及的字段名（按 issue 顺序去重）——调用方可用它高亮对应的输入项。"""
        return tuple(dict.fromkeys(issue.field for issue in self.issues))


class Rule(BaseModel):
    """一个字段的判定规则；**未设置的项不参与判定**（判定顺序见模块 docstring）。

    ``pattern`` 用 :func:`re.search` 语义（与 JSON Schema 的 ``pattern`` 一致，不要求整串匹配）；
    长度规则只对可度量（有 ``len``）的值生效，不可度量的值交给 ``type`` 规则报错、不重复报。
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    field: str = Field(min_length=1)
    required: bool = False
    type: RuleType | None = None
    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=0)
    pattern: str | None = None
    enum: tuple[str, ...] | None = None
    check: Callable[[Any], Any] | None = None
    #: ``check`` 失败时进 ``ValidationIssue.rule`` 的名字，同时用于 ``must satisfy <label>``。
    label: str = Field(default="custom", min_length=1)


def _length(value: Any) -> int | None:
    """长度规则的度量；不可度量时返回 ``None``（由 ``type`` 规则负责报错）。"""
    try:
        return len(value)
    except TypeError:
        return None


def _first_failure(rule: Rule, value: Any) -> tuple[str, str] | None:
    """按固定顺序找该字段的**第一条**失败判定，返回 ``(规则名, 原因)``；``None`` = 通过。"""
    if rule.type is not None and not _TYPE_CHECKS[rule.type](value):
        return "type", f"must be {_TYPE_NOUNS[rule.type]}"
    if rule.min_length is not None or rule.max_length is not None:
        length = _length(value)
        if length is not None:
            if rule.min_length is not None and length < rule.min_length:
                return "min_length", f"must be at least {rule.min_length} characters"
            if rule.max_length is not None and length > rule.max_length:
                return "max_length", f"must be at most {rule.max_length} characters"
    if rule.pattern is not None and isinstance(value, str) and re.search(rule.pattern, value) is None:
        return "pattern", f"must match {rule.pattern}"
    if rule.enum is not None and value not in rule.enum:
        return "enum", f"must be one of {', '.join(rule.enum)}"
    if rule.check is not None:
        verdict = rule.check(value)
        if verdict is None or verdict is True:
            return None
        if verdict is False:
            return rule.label, f"must satisfy {rule.label}"
        if isinstance(verdict, str):
            return rule.label, verdict
        raise TypeError(f"Rule.check for {rule.field!r} must return None/True/False/str, got {type(verdict).__name__}")
    return None


def collect_issues(data: Mapping[str, Any], fields: Iterable[Rule]) -> list[ValidationIssue]:
    """纯收集版：返回全部 issue（每字段最多一条）；空列表 ⇔ 通过。

    ``data`` 里没有对应 :class:`Rule` 的键**不报错**——字段形状（多出来的键）归 Pydantic 模型管，
    本框架只判它声明的那些字段。
    """
    issues: list[ValidationIssue] = []
    for rule in fields:
        present = rule.field in data
        value = data.get(rule.field)
        if value is None or not present:
            if rule.required:
                issues.append(ValidationIssue(field=rule.field, rule="required", message="is required"))
            continue
        failure = _first_failure(rule, value)
        if failure is not None:
            kind, message = failure
            issues.append(ValidationIssue(field=rule.field, rule=kind, message=message))
    return issues


def validate(data: Mapping[str, Any], fields: Iterable[Rule]) -> None:
    """判定 ``data`` 是否满足 ``fields``：通过即静默返回，失败抛 :class:`InputValidationError`。

    统一走同一个入口（而不是「先 ``collect_issues`` 再自己拼异常」）：失败形状只有一种，
    调用方拿到的 ``str(exc)`` 就是可直接展示的逐字段说明。
    """
    issues = collect_issues(data, fields)
    if issues:
        raise InputValidationError(issues)
