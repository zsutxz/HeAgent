"""API 参考的覆盖判据（`docs/api.md` 的渲染指令与「非入口层包」集合相等）。

**为什么是「单页 + 每包一条 `:::` 指令 + `show_submodules`」而不是逐模块页**：公开 API 的枚举口径
已由 `tests/test_api_docstrings.py` 钉住（每个公开符号必须有 docstring），API 参考只需保证
「每个核心包都有渲染入口」——包内新增模块会被 `show_submodules` 自动展开，于是新增模块
**不必**同时新增文档（那会变成两份事实，迟早漂移）；包页同理，一包一页已合并为单页。

五条判据：

1. `docs/api.md` 的 `::: heagent.<pkg>` 指令集合 == `src/heagent/` 下的非入口层包（新增包漏加指令即红）；
2. 每条指令都开启 `show_submodules: true`（否则只渲染包 `__init__`，子模块在站点上不可见）；
3. `mkdocs.yml` 的 nav 登记了这一页（没登记 = 站点上不可达；`--strict` 只报「nav 之外存在页面」
   的提示，不保证可达性）；
4. 页首索引表逐包列出（表是读者进页的总览，漏一项 = 该包没有一句话定位）；
5. `docs/api/` 目录不得回潮（一包一页与单页并存 = 同一事实两份载体，迟早漂移）。

判据不解析站点产物：`mkdocs build --strict` 由 CI 的 docs 门与 `scripts/build_docs.py` 负责，
本文件只钉「指令齐全、选项正确、导航可达」这些静态事实。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
API_PAGE = REPO_ROOT / "docs" / "api.md"
API_DIR = REPO_ROOT / "docs" / "api"
SRC = REPO_ROOT / "src" / "heagent"
MKDOCS = REPO_ROOT / "mkdocs.yml"

#: 入口层与静态投递面：它们的可读性由 CLI 输出 / 测试覆盖，不进 API 参考。
NON_API_PACKAGES = frozenset({"cli", "gui", "goal", "web"})

#: 一条渲染指令 + 紧随其后的缩进选项块（到下一条指令或下一个顶格行为止）。
_DIRECTIVE_BLOCK = re.compile(
    r"^::: heagent\.(?P<pkg>[A-Za-z_][A-Za-z0-9_]*)$\n(?P<options>(?:[ \t]+.*\n|\n)*)",
    flags=re.MULTILINE,
)


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


def _directive_blocks() -> list[tuple[str, str]]:
    """`docs/api.md` 里的 ``(包名, 选项块)``，按出现顺序。"""
    text = API_PAGE.read_text(encoding="utf-8")
    return [(match.group("pkg"), match.group("options")) for match in _DIRECTIVE_BLOCK.finditer(text)]


def test_every_core_package_has_a_render_directive() -> None:
    """渲染指令集合必须与核心包集合**相等**：新增包漏加指令即红，删包留指令也红。"""
    packages = _package_dirs()
    directives = {package for package, _ in _directive_blocks()}
    assert packages, "src/heagent 下没有识别到任何核心包（扫描面失效，不要就此判绿）"
    missing, extra = sorted(packages - directives), sorted(directives - packages)
    assert directives == packages, f"docs/api.md 的渲染指令与核心包集合不一致：缺 {missing}，多余 {extra}"


def test_every_directive_renders_submodules() -> None:
    """每条渲染指令都开启 `show_submodules: true`（否则只渲染包 `__init__`，子模块在站点上不可见）。"""
    without = [package for package, options in _directive_blocks() if "show_submodules: true" not in options]
    assert not without, f"docs/api.md 这些渲染指令未开启 show_submodules：{without}"


def test_mkdocs_nav_registers_the_api_page() -> None:
    """nav 里必须有这一页的入口；未登记的页面在站点上不可达。"""
    nav = MKDOCS.read_text(encoding="utf-8")
    assert re.search(r": api\.md$", nav, flags=re.MULTILINE), "mkdocs.yml 的 nav 缺少 api.md"


def test_overview_table_lists_every_package() -> None:
    """页首索引表必须逐包列出（表在第一条渲染指令之前；漏一项 = 该包没有一句话定位）。"""
    table = API_PAGE.read_text(encoding="utf-8").split("\n::: ")[0]
    missing = [package for package in sorted(_package_dirs()) if f"`heagent.{package}`" not in table]
    assert not missing, f"docs/api.md 索引表未列出这些包：{missing}"


def test_api_reference_stays_a_single_page() -> None:
    """`docs/api/` 目录不得回潮：一包一页与单页并存 = 同一事实两份载体，迟早漂移。"""
    assert not API_DIR.exists(), "API 参考已合并为单页 docs/api.md，不要再新建 docs/api/<包>.md"
