"""G-8：传输层不得带文档站链接（`network/` 出站零文档 URL）。

为什么这是一条契约而不是风格偏好：`network/` 是唯一可能把字符串**发到网络上**的层——
它拼的 URL、`Link` 头、SSE 注释里的说明文字，都可能被客户端当作可点击导航。
一旦传输层引用 `/docs/...`、`mkdocs` 站点或 `readthedocs`，文档站就成了对外契约的一部分
（改文档即改传输面），且本地/对外两种 listener 会给出不同可达性的链接。

判据是 AST 静态扫描**字符串常量**（不做正则全文匹配）：注释与 docstring 里的"提到 mkdocs"
是讨论，不是出站内容；只有真正会被拼进响应/日志字段的字符串字面量才算。docstring 在 AST 里
是 `ast.Constant`，因此会被纳入——这是刻意的：docstring 会被 `help()`、`__doc__` 端点或
调试工具直接吐给用户，一并约束更省心。

Q6 + 切片预算（Step 04 裁决）：若首跑有命中，**不改 `network/`**，而是逐条登记
`_bmad-output/implementation-artifacts/deferred-work-archive.md` 并回审批门。
"""

from __future__ import annotations

import ast

from pathlib import Path

NETWORK_ROOT = Path(__file__).resolve().parents[2] / "src" / "heagent" / "network"

#: 三个 token 即 G-8 原文；大小写不敏感（`MKDOCS_DIR`、`ReadTheDocs` 同样算命中）。
FORBIDDEN_TOKENS = ("/docs/", "mkdocs", "readthedocs")


def _iter_string_constants(tree: ast.Module) -> list[tuple[int, str]]:
    """`(行号, 字符串值)`：覆盖普通常量、f-string 片段与隐式拼接。"""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.append((getattr(node, "lineno", 0), node.value))
    return found


def test_network_layer_has_no_documentation_links() -> None:
    """`src/heagent/network/**` 的字符串常量里三个 token 都 0 命中。"""
    assert NETWORK_ROOT.is_dir(), f"missing network package: {NETWORK_ROOT}"
    hits: list[str] = []
    scanned = 0
    for path in sorted(NETWORK_ROOT.rglob("*.py")):
        scanned += 1
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, value in _iter_string_constants(tree):
            lowered = value.lower()
            for token in FORBIDDEN_TOKENS:
                if token in lowered:
                    rel = path.relative_to(NETWORK_ROOT.parents[1]).as_posix()
                    hits.append(f"{rel}:{lineno} token={token!r} value={value[:80]!r}")
    # 扫描面必须非空：目录挪走/改名时这条守卫不许静默变绿。
    assert scanned > 0, f"no python files scanned under {NETWORK_ROOT}"
    assert not hits, (
        "G-8 violated: transport layer references documentation sites\n"
        + "\n".join(f"  - {hit}" for hit in hits)
        + "\n（处置口径：不改 network/，逐条登记 deferred-work-archive.md 并回审批门）"
    )


def test_scan_actually_sees_strings() -> None:
    """自证判据强度：扫描器必须能在同一套 AST 逻辑下认出构造出来的命中。

    否则「0 命中」可能只是扫描逻辑失效（例如树没解析、只看模块顶层常量）。
    """
    probe = ast.parse('X = "see /docs/getting-started"\nY = f"https://x.readthedocs.io"\nZ = "mkdocs.yml"\n')
    values = [value for _, value in _iter_string_constants(probe)]
    hit_tokens = {token for token in FORBIDDEN_TOKENS for value in values if token in value.lower()}
    assert hit_tokens == set(FORBIDDEN_TOKENS), f"scanner blind to: {set(FORBIDDEN_TOKENS) - hit_tokens}"
