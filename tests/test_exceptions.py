"""Story 69.1 / 69.2 / 69.3：异常层次、模块专用异常与统一错误码的契约测试。

三条判据各自可执行：

- **层次**：每个框架异常都继承 ``HeAgentException``（``HeAgentError`` 的别名），且恰有一个
  「分类」祖先（根与分类自身除外）——分类层是 ``except`` 一整类的唯一依据。
- **覆盖**：provider / tool / engine / agent 四类各 ≥3 个专用异常；新增类必须有真实 ``raise``
  点（源码文本判据），不允许为凑数加死类。
- **错误码**：code 唯一、形态 ``E_*``；``error_catalog()`` 与 ``docs/errors.md`` 的码表逐条一致
  （文档不手抄第二份事实）。
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from heagent.pub import exceptions as exc_mod
from heagent.pub.exceptions import (
    AgentError,
    ConfigurationError,
    EngineError,
    HeAgentError,
    HeAgentException,
    ProviderError,
    SessionError,
    ToolError,
    error_catalog,
    error_code_of,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "heagent"
DOCS = Path(__file__).resolve().parents[1] / "docs" / "errors.md"

#: 分类层（直接挂在根下的第二级基类）。
CATEGORIES = (ProviderError, ToolError, EngineError, AgentError, SessionError, ConfigurationError)

#: 每个分类至少要有多少个具体异常（票面：provider / tool / engine / agent 各 ≥3）。
MIN_PER_CATEGORY = 3

#: 69.1 增补的专用异常：这些类必须有真实 ``raise`` 点（既有类里 ``PolicyViolation`` 走
#: 「构造后映射成事件」、``BudgetExceeded`` 走 ``except`` 兼容面，不以 raise 形态出现）。
STORY_69_1_EXCEPTIONS = (
    "ProviderAuthError",
    "ProviderRateLimitError",
    "ProviderTimeoutError",
    "ProviderResponseFormatError",
    "ToolArgumentError",
    "ToolExecutionError",
    "UnknownToolError",
    "LedgerError",
    "PolicyExecutionError",
    "WorkflowExecutionError",
    "IterationLimitError",
    "SubAgentError",
    "AgentResumeError",
    "ConfigurationError",
)


def _all_exception_classes() -> list[type[HeAgentError]]:
    """本模块定义的**全部**异常类（含根与分类）；按类对象去重（``HeAgentException`` 是别名）。"""
    seen: dict[int, type[HeAgentError]] = {}
    for _name, obj in inspect.getmembers(exc_mod, inspect.isclass):
        if issubclass(obj, HeAgentError) and obj.__module__ == exc_mod.__name__:
            seen.setdefault(id(obj), obj)
    return list(seen.values())


def _concrete_classes() -> list[type[HeAgentError]]:
    """具体异常 = 不是分类层、也不是根的那些。"""
    return [cls for cls in _all_exception_classes() if cls is not HeAgentError and cls not in CATEGORIES]


class TestHierarchy:
    def test_exception_alias_is_the_root_class(self) -> None:
        """票面措辞是 ``HeAgentException``；它是别名而不是第二个基类。"""
        assert HeAgentException is HeAgentError

    def test_every_exception_inherits_the_root(self) -> None:
        for cls in _all_exception_classes():
            assert issubclass(cls, HeAgentException), f"{cls.__name__} 未继承 HeAgentException"
            assert issubclass(cls, HeAgentError)

    def test_every_concrete_exception_has_exactly_one_category_ancestor(self) -> None:
        """恰好一个分类祖先：两个会让 ``except`` 的归属含糊，零个会让分类 ``except`` 漏掉它。"""
        for cls in _concrete_classes():
            ancestors = [category for category in CATEGORIES if issubclass(cls, category)]
            assert len(ancestors) == 1, f"{cls.__name__} 的分类祖先 = {[a.__name__ for a in ancestors]}"

    def test_categories_are_themselves_root_based(self) -> None:
        for category in CATEGORIES:
            assert issubclass(category, HeAgentError)
            assert not any(issubclass(category, other) for other in CATEGORIES if other is not category)

    def test_category_catch_covers_its_children(self) -> None:
        with pytest.raises(ProviderError):
            raise exc_mod.ProviderRateLimitError("429")
        with pytest.raises(ToolError):
            raise exc_mod.ToolArgumentError("bad args")
        with pytest.raises(EngineError):
            raise exc_mod.LedgerError("lease lost")
        with pytest.raises(AgentError):
            raise exc_mod.IterationLimitError("too many iterations")


class TestMessages:
    @pytest.mark.parametrize(
        ("exc_cls", "message"),
        [
            pytest.param(HeAgentError, "test error", id="base"),
            pytest.param(ProviderError, "api failed", id="provider"),
            pytest.param(ToolError, "execution failed", id="tool"),
            pytest.param(exc_mod.SafetyViolation, "dangerous command", id="safety"),
            pytest.param(exc_mod.BudgetExceeded, "max iterations reached", id="budget"),
        ],
    )
    def test_error_carries_message_and_inherits_base(self, exc_cls: type[HeAgentError], message: str) -> None:
        """既有判据（保留）：携带 message、``str()`` 直返原文、继承 ``HeAgentError``。"""
        err = exc_cls(message)
        assert err.message == message
        assert str(err) == message
        assert isinstance(err, HeAgentError)


class TestModuleCoverage:
    @pytest.mark.parametrize("category", [ProviderError, ToolError, EngineError, AgentError])
    def test_each_module_has_at_least_three_dedicated_exceptions(self, category: type[HeAgentError]) -> None:
        children = [cls for cls in _concrete_classes() if issubclass(cls, category) and cls is not category]
        assert len(children) >= MIN_PER_CATEGORY, f"{category.__name__} 只有 {len(children)} 个专用异常"

    def test_story_69_1_exceptions_are_really_raised(self) -> None:
        """69.1 增补的类不许是死代码：源码里必须存在 ``raise <Class>``。"""
        missing = [name for name in STORY_69_1_EXCEPTIONS if not re.search(rf"raise\s+{name}\b", _sources())]
        assert missing == [], f"这些新增异常类从未被 raise：{missing}"

    def test_every_concrete_exception_is_instantiated_or_raised(self) -> None:
        """全部具体异常至少被用到一次（``raise X`` 或构造 ``X(``）——纯粹的孤儿类会被点名。"""
        haystack = _sources()
        unused = [
            cls.__name__
            for cls in _concrete_classes()
            if not re.search(rf"raise\s+{cls.__name__}\b", haystack) and not re.search(rf"\b{cls.__name__}\(", haystack)
        ]
        assert unused == [], f"这些异常类既没被 raise 也没被构造：{unused}"


class TestErrorCodes:
    def test_codes_are_unique_and_well_formed(self) -> None:
        codes = [cls.code for cls in _all_exception_classes()]
        assert len(codes) == len(set(codes)), "错误码必须唯一"
        for code in codes:
            assert re.fullmatch(r"E_[A-Z0-9_]+", code), f"错误码形态不合法：{code}"

    def test_instance_exposes_the_class_code(self) -> None:
        error = exc_mod.ProviderAuthError("401")
        assert error.code == exc_mod.ProviderAuthError.code

    def test_catalog_covers_every_class(self) -> None:
        catalog = error_catalog()
        assert {entry.class_name for entry in catalog} == {cls.__name__ for cls in _all_exception_classes()}
        for entry in catalog:
            assert entry.description and entry.suggestion

    def test_unknown_exception_maps_to_the_fallback_code(self) -> None:
        assert error_code_of(ValueError("plain")) == "E_UNKNOWN"
        assert error_code_of(exc_mod.ProviderAuthError("401")) == "E_PROVIDER_AUTH"

    def test_docs_code_table_matches_the_catalog(self) -> None:
        """``docs/errors.md`` 的码表与 ``error_catalog()`` 逐条一致（行序与内容都不许漂）。"""
        rows = _parse_docs_code_table()
        catalog = error_catalog()
        assert len(rows) == len(catalog), f"文档码表 {len(rows)} 行，catalog {len(catalog)} 行"
        for (code, class_name, description, suggestion), entry in zip(rows, catalog, strict=True):
            assert (code, class_name) == (entry.code, entry.class_name), f"文档码表与代码不一致：{code}"
            assert description == entry.description
            assert suggestion == entry.suggestion


def _sources() -> str:
    """``src/heagent`` 全部源码文本拼成的检索面（判「有没有人用这个类」）。"""
    return "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in SRC.rglob("*.py")
        if "__pycache__" not in str(path)
    )


def _parse_docs_code_table() -> list[tuple[str, str, str, str]]:
    """解析 ``docs/errors.md`` 第二节的码表为 ``(code, class, description, suggestion)``。"""
    text = DOCS.read_text(encoding="utf-8")
    section = text.split("## 二、框架异常", 1)[1].split("## 三、CLI 与启动期错误", 1)[0]
    rows: list[tuple[str, str, str, str]] = []
    in_table = False
    for line in section.splitlines():
        stripped = line.strip()
        if stripped.startswith("| 码 |"):
            in_table = True
            continue
        if not in_table:
            continue
        if not stripped.startswith("|"):
            if rows:
                break
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) != 4 or set(cells[0]) <= {"-", " "}:
            continue
        rows.append((cells[0].strip("`"), cells[1].strip("`"), cells[2], cells[3]))
    assert rows, "未从 docs/errors.md 解析出错码表"
    return rows
