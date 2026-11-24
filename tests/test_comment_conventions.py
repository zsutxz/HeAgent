"""注释与 docstring 口径守卫（规范见 ``docs/framework.md`` §8.4 第 5 条）。

三条可执行口径：

1. **语言分面**：docstring 默认中文；只有**机器 / 用户可见面**保持英文——``@tool`` 装饰的函数
   docstring（被 :func:`heagent.tools.decorator.tool` 取作模型可见的工具描述）与
   ``@click.command`` / ``@*.command`` / ``@*.group`` 装饰的函数 docstring（Click 的 CLI help）。
   其余英文 docstring 一律视为「忘译」。
2. **段标题单一形态**：注释里的段标题与分隔线只用 ``# ── 段名 ──``；``# ----`` / ``# ====`` 这类
   dash / equals 分隔线不再使用（同一仓库两套分隔线会让「找某个段」变成猜风格）。
3. **每个模块都有模块 docstring**：包的说明写在模块顶端，不在 ``AGENTS.md`` 里复制第二份。
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "heagent"

_CJK = re.compile(r"[\u4e00-\u9fff]")
_CALLABLE = (ast.FunctionDef, ast.AsyncFunctionDef)
_CLI_FACING = re.compile(r"(^|\.)(command|group)\(")
_OLD_SEPARATOR = re.compile(r"^#\s*(?:-{3,}|={2,})")  # `# ---` / `# ===` 分隔线；`# --flag` 是命令行参数，不算


def _python_files() -> list[Path]:
    return sorted(path for path in SRC.rglob("*.py") if "__pycache__" not in path.parts)


def _is_visible_surface(node: ast.AST) -> bool:
    """该节点的 docstring 是否属于「保持英文」的对外面（工具描述 / CLI help）。"""
    decorators = [ast.unparse(item) for item in getattr(node, "decorator_list", [])]
    for decorator in decorators:
        if decorator == "tool" or decorator.startswith("tool("):
            return True
        if _CLI_FACING.search(decorator):
            return True
    return False


def _english_docstrings(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    offenders: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, (*_CALLABLE, ast.ClassDef)):
            continue
        docstring = ast.get_docstring(node, clean=False)
        if docstring is None or _CJK.search(docstring):
            continue
        if _is_visible_surface(node):
            continue
        offenders.append(f"{path.relative_to(SRC.parents[1])}:{node.lineno} {node.name}")
    return offenders


def test_docstrings_are_chinese_except_model_and_cli_surfaces() -> None:
    offenders: list[str] = []
    for path in _python_files():
        offenders.extend(_english_docstrings(path))
    assert offenders == [], (
        "以下 docstring 只有英文：维护者阅读面请用中文（`@tool` / Click 命令的 docstring "
        "是对外可见面，保持英文）：\n" + "\n".join(offenders)
    )


def test_every_module_has_a_docstring() -> None:
    missing = [
        str(path.relative_to(SRC.parents[1]))
        for path in _python_files()
        if ast.get_docstring(ast.parse(path.read_text(encoding="utf-8"))) is None
    ]
    assert missing == [], "以下模块缺模块 docstring：\n" + "\n".join(missing)


def test_section_headers_use_a_single_style() -> None:
    offenders: list[str] = []
    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type != tokenize.COMMENT:
                continue
            if _OLD_SEPARATOR.match(token.string):
                offenders.append(f"{path.relative_to(SRC.parents[1])}:{token.start[0]} {token.string.strip()}")
    assert offenders == [], "段标题 / 分隔线统一用 `# ── 段名 ──`（不要 `# ---- … ----` 或 `# ====`）：\n" + "\n".join(
        offenders
    )


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        ("def f():\n    pass", False),
        ("@tool\ndef f():\n    pass", True),
        ("@tool(read_only=True)\ndef f():\n    pass", True),
        ("@main.command('x')\ndef f():\n    pass", True),
        ("@click.group('x')\ndef f():\n    pass", True),
        ("@dataclass\ndef f():\n    pass", False),
    ],
)
def test_visible_surface_detection_is_exact(node: str, expected: bool) -> None:
    """阳性 / 阴性控制：避免守卫退化成「永远通过」或豁免过宽。"""
    func = ast.parse(node).body[-1]
    assert _is_visible_surface(func) is expected
