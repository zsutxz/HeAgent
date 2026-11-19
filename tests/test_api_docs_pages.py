"""Epic 68 / 台账 A64：API 参考页的覆盖判据（`docs/api/` 与「非入口层包」集合相等）。

**为什么是「包页 + `show_submodules`」而不是逐模块页**：公开 API 的枚举口径已由
`tests/test_api_docstrings.py` 钉住（每个公开符号必须有 docstring），API 参考只需保证
「每个核心包都有渲染入口」——包内新增模块会被 `show_submodules` 自动展开，于是新增模块
**不必**同时新增一个 md 壳（那会变成两份事实，迟早漂移）。

三条判据：

1. `docs/api/<pkg>.md` 的集合 == `src/heagent/` 下的非入口层包（新增包漏加页即红）；
2. 每个包页都含 `::: heagent.<pkg>` 且开启 `show_submodules`（壳写错 ⇒ 站点上是白页）；
3. `mkdocs.yml` 的 nav 为每个包页登记了入口（没登记 = 站点上不可达；`--strict` 只报
   「nav 之外存在页面」的提示，不保证可达性）。

判据不解析站点产物：`mkdocs build --strict` 由 CI 的 docs 门与 `scripts/build_docs.py` 负责，
本文件只钉「页面存在、指向正确、导航可达」这三件静态事实。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_DIR = REPO_ROOT / "docs" / "api"
SRC = REPO_ROOT / "src" / "heagent"
MKDOCS = REPO_ROOT / "mkdocs.yml"

#: 入口层与静态投递面：它们的可读性由 CLI 输出 / 测试覆盖，不进 API 参考（同 68.2 口径）。
NON_API_PACKAGES = frozenset({"cli", "gui", "goal", "web"})

_PAGE_DIRECTIVE = re.compile(r"^::: heagent\.(?P<pkg>[A-Za-z_][A-Za-z0-9_]*)$", flags=re.MULTILINE)


def _package_dirs() -> set[str]:
    """`src/heagent/` 下所有「是包」且不属于入口层/静态面的一级目录名。"""
    return {
        path.name
        for path in SRC.iterdir()
        if path.is_dir()
        and (path / "__init__.py").is_file()
        and path.name not in NON_API_PACKAGES
        and not path.name.startswith("_")
    }


def _page_names() -> set[str]:
    """`docs/api/` 下的包页名（去掉 `index.md` 与后缀）。"""
    return {path.stem for path in API_DIR.glob("*.md") if path.stem != "index"}


def test_every_core_package_has_an_api_page() -> None:
    """包页集合必须与核心包集合**相等**：新增包漏加页即红，删包留空页也红。"""
    packages = _package_dirs()
    pages = _page_names()
    assert packages, "src/heagent 下没有识别到任何核心包（扫描面失效，不要就此判绿）"
    missing, extra = sorted(packages - pages), sorted(pages - packages)
    assert pages == packages, f"docs/api 与核心包集合不一致：缺页 {missing}，多余页 {extra}"


def test_each_page_renders_its_package_with_submodules() -> None:
    """每个包页恰好一个 `::: heagent.<pkg>` 指令，且开启 `show_submodules`（否则只渲染包 `__init__`）。"""
    for package in sorted(_package_dirs()):
        text = (API_DIR / f"{package}.md").read_text(encoding="utf-8")
        directives = _PAGE_DIRECTIVE.findall(text)
        assert directives == [package], f"docs/api/{package}.md 的渲染指令 = {directives}，期望 ['{package}']"
        assert "show_submodules: true" in text, f"docs/api/{package}.md 未开启 show_submodules"


def test_mkdocs_nav_registers_every_api_page() -> None:
    """nav 里必须有每个 API 页的入口（含索引）；未登记的页面在站点上不可达。"""
    nav = MKDOCS.read_text(encoding="utf-8")
    expected = {f"api/{package}.md" for package in _package_dirs()} | {"api/index.md"}
    missing = sorted(path for path in expected if path not in nav)
    assert not missing, f"mkdocs.yml 的 nav 缺少这些 API 页：{missing}"


def test_index_lists_every_package_page() -> None:
    """索引页必须逐个链接到包页（索引是站点读者的入口，漏一项就等于该包不可发现）。"""
    index = (API_DIR / "index.md").read_text(encoding="utf-8")
    missing = [package for package in sorted(_package_dirs()) if f"({package}.md)" not in index]
    assert not missing, f"docs/api/index.md 未链接这些包页：{missing}"
