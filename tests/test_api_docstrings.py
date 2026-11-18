"""Story 68.2：核心模块公开 API 的 docstring 覆盖判据（ratchet）。

「公开 API」的界定是**可枚举**的：`src/heagent/` 下除入口层（`cli/`、`gui/`）外，模块级非下划线
函数/类，以及类的非下划线方法（含 property、pydantic 钩子、Protocol 声明）。入口层不在此列——
它们的可读性由 CLI 输出与测试覆盖，docstring 不是主要消费面。

判据两条：

1. 每个公开符号都有非空 docstring，且首行不是 `TODO` / `FIXME` 这类占位；
2. 新增公开符号漏写 docstring 即红（本测试**没有**允许清单——补完就是零容忍）。

刻意不要求 `Args:` / `Returns:` / `Raises:` 段：本仓 docstring 是散文式说明「为什么/边界」，
参数细节通常已写在散文里或由类型注解表达；机械补段落会与既有风格冲突且不增加信息。
@overload 的重复声明只查实现体（同一个函数名只判一次）。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "heagent"

#: 检查范围：核心模块（入口层 `cli/` / `gui/` 不在内，见模块 docstring）。
CORE_MODULES = (
    "agent",
    "config",
    "context",
    "cron",
    "engine",
    "events",
    "memory",
    "network",
    "providers",
    "pub",
    "skills",
    "tools",
)

_PLACEHOLDER_PREFIXES = ("todo", "fixme", "xxx", "docstring", "docs")


def _is_overload(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        name = target.attr if isinstance(target, ast.Attribute) else getattr(target, "id", "")
        if name == "overload":
            return True
    return False


def _public_symbols(path: Path) -> list[ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if not node.name.startswith("_") and not _is_overload(node):
                found.append(node)
        elif isinstance(node, ast.ClassDef) and not node.name.startswith("_"):
            found.append(node)
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)) and not sub.name.startswith("_"):
                    found.append(sub)
    return found


def _missing_docstrings() -> list[str]:
    missing: list[str] = []
    for module in CORE_MODULES:
        for path in sorted((SRC / module).rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            for symbol in _public_symbols(path):
                doc = (ast.get_docstring(symbol) or "").strip()
                relative = path.relative_to(SRC.parent.parent)
                if not doc:
                    missing.append(f"{relative}:{symbol.name}")
                    continue
                first_line = doc.splitlines()[0].strip().lower()
                if first_line.startswith(_PLACEHOLDER_PREFIXES):
                    missing.append(f"{relative}:{symbol.name}（占位 docstring）")
    return missing


class TestPublicDocstrings:
    def test_every_public_symbol_is_documented(self) -> None:
        missing = _missing_docstrings()
        assert missing == [], f"{len(missing)} 个公开符号缺 docstring：\n" + "\n".join(missing)

    def test_scope_actually_contains_symbols(self) -> None:
        """防止判据退化成空扫（目录写错/改名时立刻红，而不是假绿）。"""
        count = sum(len(_public_symbols(path)) for path in (SRC / "pub").rglob("*.py"))
        assert count > 20, f"扫描面疑似失效：pub/ 只找到 {count} 个公开符号"

    @pytest.mark.parametrize("module", CORE_MODULES)
    def test_module_directories_exist(self, module: str) -> None:
        assert (SRC / module).is_dir(), f"检查范围里的模块不存在：{module}"
