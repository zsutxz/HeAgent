"""`docs/frame/` 扩展页布局契约：索引、站点导航与编号归属一一对应。

为什么需要这层守卫（2026-11-24 整理）：`docs/framework.md` 只留架构与边界，逐模块的机制细节按原 `4.x`
编号分册到 `docs/frame/`。这套布局的价值全靠两条纪律——**编号不变**（正文里「见 4.16」仍指该页）与
**一处只讲一遍**（同一小节不出现两份事实）——而这两条都只能靠机器守住：

1. 每个扩展页都在 `docs/frame/README.md` 的索引表里（否则读者找不到它）；
2. 每个扩展页都在 `mkdocs.yml` 的 nav 里（否则站点上不可见）；
3. 一个 `4.x` 编号只在一个扩展页里当标题出现（否则同一小节有两份事实，改一处漏一处）。

反向句（索引/导航里列了但文件不存在、跨页锚点失效）由 `tests/test_docs_links.py` 的跨文件链接判据覆盖。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FRAME = ROOT / "docs" / "frame"
INDEX = FRAME / "README.md"
MKDOCS = ROOT / "mkdocs.yml"

_PAGES = sorted(path.name for path in FRAME.glob("*.md") if path.name != "README.md")
#: 扩展页的顶层小节形如 `## 4.16.1 WebSocket 入口（…）`；`###` 及以下不参与编号归属判据。
_NUMBERED = re.compile(r"^## (\d+\.\d+(?:\.\d+)?) ", re.MULTILINE)


def test_every_frame_page_is_indexed() -> None:
    """`frame/README.md` 是读者入口：新增一页却不登记，等于那页不存在。"""
    text = INDEX.read_text(encoding="utf-8")
    missing = [name for name in _PAGES if f"]({name})" not in text]
    assert not missing, "frame/README.md 索引缺少这些页:\n" + "\n".join(missing)


def test_every_frame_page_is_in_the_docs_nav() -> None:
    """mkdocs nav 决定站点可见性：漏登记时页面构建成功但没人点得到。"""
    nav = MKDOCS.read_text(encoding="utf-8")
    missing = [name for name in _PAGES if f"frame/{name}" not in nav]
    assert not missing, "mkdocs.yml 的 nav 缺少这些扩展页:\n" + "\n".join(missing)


def test_a_section_number_lives_in_exactly_one_frame_page() -> None:
    """同一 `4.x` 出现在两页 = 两份事实；拆页时先删旧页再建新页，不留并存。"""
    owners: dict[str, list[str]] = {}
    for path in sorted(FRAME.glob("*.md")):
        if path.name == "README.md":
            continue
        for number in _NUMBERED.findall(path.read_text(encoding="utf-8")):
            owners.setdefault(number, []).append(path.name)
    duplicated = {number: pages for number, pages in owners.items() if len(pages) > 1}
    assert not duplicated, f"同一 4.x 编号出现在多个扩展页（会造两份事实）: {duplicated}"
