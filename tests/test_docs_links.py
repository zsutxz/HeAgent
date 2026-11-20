"""仓库内文档链接与页内锚点的守卫（**仓库读者口径**，不是 mkdocs 站点口径）。

为什么需要这层守卫：`docs/framework.md` 的大目录与跨文档引用都是**手写** Markdown 链接，而
`mkdocs.yml` 的 `validation.links.anchors` 已 ignore（中文标题 + 反引号在 python-markdown 与
GitHub 的 slug 算法下结果不同，站点侧必然报「no such anchor」）。于是「标题改了、TOC 没跟」
这类漂移机器无从发现：标题补后缀、跨文件链接的相对路径多写一层 `../`，链接都会静默失效。

slug 口径按 GitHub（github-slugger）：小写 → 删除 ASCII 标点（保留 `-` `_`）与 Unicode 标点／
全角区段（`、（）；：` 都在内）→ 空格转 `-`；中文与字母数字保留。仓库读者（GitHub、编辑器
预览、`git diff` 阅读）用的就是这套规则。

范围只覆盖**当前事实文档**：`docs/**/*.md`、根 `README.md` / `AGENTS.md` / `CLAUDE.md`、
`_bmad-output/README.md`。历史归档（`_bmad-output/epics/**`、`retrospective-all-cycles.md` 等）
是证据而非当前事实，允许指向已归档位置，不在此列。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

#: github-slugger 的删除字符类（截取本仓会用到的区段：ASCII 标点 + Unicode 标点 + 全角）。
_SLUG_STRIP = re.compile(
    r"[\0-\x1f!-,./:-@\[-\^`{-~\x7f"
    r"\u2000-\u206f\u2010-\u2027\u2030-\u205e"
    r"\u3000-\u3004\u3008-\u3020\u3030\u303d\ufe45\ufe46\ufe49-\ufe4f"
    r"\uff01-\uff9f]"
)
_FENCE = re.compile(r"^```.*?^```", re.DOTALL | re.MULTILINE)
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)
_LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)")

#: 当前事实文档（新增此类文档时补进来，守卫才覆盖）。
CURRENT_DOCS: tuple[str, ...] = (
    "README.md",
    "AGENTS.md",
    "CLAUDE.md",
    "_bmad-output/README.md",
)


def _current_doc_paths() -> list[Path]:
    paths = [ROOT / name for name in CURRENT_DOCS]
    paths += sorted((ROOT / "docs").rglob("*.md"))
    return [p for p in paths if p.is_file()]


def _slug(heading: str) -> str:
    """标题 → GitHub 锚点。反引号与链接等行内装饰先剥掉再套规则。"""
    text = heading.strip()
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = text.replace("`", "").replace("**", "")
    text = _SLUG_STRIP.sub("", text.lower())
    return text.replace(" ", "-")


def _file_slug(text: str) -> str:
    """相对路径 → 仓库内 slug 键（POSIX 分隔符、去前导 `./`）。"""
    return text.replace("\\", "/").removeprefix("./")


def _headings(path: Path) -> set[str]:
    text = _FENCE.sub("", path.read_text(encoding="utf-8"))
    return {_slug(m.group(2)) for m in _HEADING.finditer(text)}


def _links(path: Path) -> list[str]:
    """文档里的本地链接目标（去锚点前的原样文本；外部链接与站点绝对路径跳过）。"""
    text = _FENCE.sub("", path.read_text(encoding="utf-8"))
    out = []
    for match in _LINK.finditer(text):
        target = match.group(1).strip()
        if target.startswith(("http://", "https://", "mailto:", "/")):
            continue
        out.append(target)
    return out


def test_slug_rule_matches_github_samples() -> None:
    """slug 规则自身的回归样本（取自本仓真实标题，GitHub 上可直接对照）。"""
    assert _slug("4.10 配置管理 (`config/` 包)") == "410-配置管理-config-包"
    assert (
        _slug("4.14 技能资源读取 TOCTOU 评估与安全打开加固（Epic 46.1/46.2）")
        == "414-技能资源读取-toctou-评估与安全打开加固epic-461462"
    )
    assert _slug("一、项目定位") == "一项目定位"


def test_in_file_anchors_resolve_to_headings() -> None:
    """同文件 `](#anchor)` 必须命中本文件的某个标题。"""
    bad: list[str] = []
    for path in _current_doc_paths():
        heads = _headings(path)
        for target in _links(path):
            if not target.startswith("#"):
                continue
            anchor = target[1:]
            if anchor and anchor not in heads:
                bad.append(f"{path.relative_to(ROOT)} -> {target}")
    assert not bad, "页内锚点失效（标题改了就同步链接）:\n" + "\n".join(bad)


def test_cross_file_links_and_anchors_resolve() -> None:
    """跨文件链接的目标文件必须存在；带 `#anchor` 时锚点必须命中目标文件的标题。"""
    bad: list[str] = []
    for path in _current_doc_paths():
        for target in _links(path):
            path_part, _, fragment = target.partition("#")
            if not path_part:
                continue  # 同文件锚点已在上面覆盖
            if not path_part.endswith(".md"):
                continue  # 非 Markdown 目标（脚本、目录、图片）不在锚点口径内
            resolved = (path.parent / path_part).resolve()
            if not resolved.is_file():
                bad.append(f"{path.relative_to(ROOT)} -> {target}（目标文件不存在）")
                continue
            if fragment and fragment not in _headings(resolved):
                bad.append(f"{path.relative_to(ROOT)} -> {target}（目标文件无此标题）")
    assert not bad, "跨文件链接失效:\n" + "\n".join(bad)


def test_framework_toc_entries_match_its_headings() -> None:
    """`docs/framework.md` 的手写目录必须与正文标题一一对得上（本仓最大的手写 TOC）。"""
    frame = ROOT / "docs" / "framework.md"
    text = _FENCE.sub("", frame.read_text(encoding="utf-8"))
    heads = _headings(frame)
    toc = text.split("\n## 一、项目定位")[0]
    entries = [m.group(1) for m in _LINK.finditer(toc) if m.group(1).startswith("#")]
    assert entries, "framework.md 的目录区没有任何锚点链接"
    missing = [e for e in entries if e[1:] not in heads]
    assert not missing, "framework.md 目录锚点与标题不一致:\n" + "\n".join(missing)
