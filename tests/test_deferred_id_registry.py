"""A 编号登记表契约：唯一事实源、撤号不复用、活动数与台账活动区一致、代码引用不悬空。

钉住的漂移形状（都在本仓真实发生过）：
- 台账活动区标题写 5 条、正文实际 8 条（2026-09-28 校正）；
- 同一编号在两份文档里指不同事项（A19 曾同时指「掩码域后缀制」与「原生目录选择端点默认开」；A17/A21 同指 R5）；
- 产品代码注释引用台账编号（`src/heagent/network/http_server.py` 的 A9① ②③ 等）——编号一改就指向空号。

口径：A 编号的唯一事实源 = `_bmad-output/implementation-artifacts/deferred-work-archive.md` 的「A 编号登记表」。
`Z-Dn` 是独立的勘察 / 归档序号，同一事项可双号（A2/Z-D24 等），不算同号异义。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "_bmad-output" / "implementation-artifacts" / "deferred-work-archive.md"
OVERVIEW = ROOT / "_bmad-output" / "consolidated-overview.md"

REGISTRY_HEADING = "## A 编号登记表"
ALIAS_HEADING = "**旧号对照（撤号 / 让号）**"
A_ID = re.compile(r"A\d+")
# 引用形态：前后不是字母 / 数字 / 下划线 / 连字符 / 引号（排掉 FR-A1、A1b、AD-1、字符串夹具 "A1"）
CITE = re.compile(r"(?<![A-Za-z0-9_'\"-])A(0|[1-9]\d*)(?![0-9A-Za-z])")
_STRIP = re.compile(r"[`*~（）()\s]")


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip("|").split("|")]


def _table(path: Path, heading: str, stops: tuple[str, ...]) -> list[list[str]]:
    """取小节内的表格数据行（跳过表头 / 分隔行）。"""
    lines = _lines(path)
    start = next((i for i, ln in enumerate(lines) if ln.startswith(heading)), None)
    assert start is not None, f"{path.name}: 找不到 {heading!r}"
    rows: list[list[str]] = []
    for ln in lines[start + 1 :]:
        if ln.startswith(stops):
            break
        if not ln.startswith("| ") or set(ln.strip("| ")) <= {"-", "|", " "}:
            continue
        rows.append(_cells(ln))
    assert rows, f"{path.name}: {heading!r} 下没解析到数据行（格式漂移？）"
    return rows


def registry_rows() -> list[list[str]]:
    rows = [r for r in _table(ARCHIVE, REGISTRY_HEADING, (ALIAS_HEADING,)) if A_ID.fullmatch(r[0])]
    assert len(rows) >= 20, f"登记表只解析到 {len(rows)} 行"
    return rows


def registry() -> dict[str, dict[str, str]]:
    return {r[0]: {"item": r[1], "status": r[2], "where": r[3]} for r in registry_rows()}


def alias_rows() -> list[list[str]]:
    return [r for r in _table(ARCHIVE, ALIAS_HEADING, ("## ",)) if r[0].startswith("旧 ")]


def withdrawn_ids() -> set[str]:
    out = set()
    for r in alias_rows():
        old = A_ID.fullmatch(r[0].split("（")[0].replace("旧 ", "").strip())
        if old and "撤号" in r[1]:
            out.add(old.group(0))
    return out


def renamed_ids() -> set[str]:
    out = set()
    for r in alias_rows():
        old = A_ID.fullmatch(r[0].split("（")[0].replace("旧 ", "").strip())
        if old and "让号" in r[1]:
            out.add(old.group(0))
    return out


def alias_targets() -> dict[str, str]:
    out = {}
    for r in alias_rows():
        old = A_ID.fullmatch(r[0].split("（")[0].replace("旧 ", "").strip())
        new = A_ID.fullmatch(r[2].strip("*"))
        if old and new:
            out[old.group(0)] = new.group(0)
    return out


def active_ids() -> set[str]:
    return {k for k, v in registry().items() if "活动" in v["status"]}


def archive_active_count() -> int:
    lines = _lines(ARCHIVE)
    start = next(i for i, ln in enumerate(lines) if ln.startswith("## 活动（未闭合）"))
    end = next(i for i, ln in enumerate(lines) if ln.startswith("## 闭合归档"))
    return sum(1 for ln in lines[start:end] if ln.startswith("- source_spec:"))


def overview_rows() -> dict[str, str]:
    lines = _lines(OVERVIEW)
    start = next(i for i, ln in enumerate(lines) if ln.startswith("#### A. 活动台账未闭合条目"))
    out: dict[str, str] = {}
    for ln in lines[start + 1 :]:
        if ln.startswith(("#### ", "---")):
            break
        if ln.startswith("| ") and A_ID.fullmatch(_cells(ln)[0]):
            out[_cells(ln)[0]] = ln
    return out


def longest_common_run(a: str, b: str) -> int:
    """最长公共子串长度（用于判断两处描述的是不是同一事项；中文按字符比足够区分）。"""
    best = 0
    for i in range(len(a)):
        for j in range(len(b)):
            k = 0
            while i + k < len(a) and j + k < len(b) and a[i + k] == b[j + k]:
                k += 1
            best = max(best, k)
    return best


def code_citations() -> dict[str, list[str]]:
    """产品代码与测试注释里对 A 号的引用（字符串字面量里的形态不参与判定，如夹具 `_users("A1")`）。"""
    self_name = Path(__file__).name
    cited: dict[str, list[str]] = {}
    for base in (ROOT / "src" / "heagent", ROOT / "tests"):
        for path in sorted(base.rglob("*.py")):
            if path.name == self_name:
                continue
            for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for m in CITE.finditer(line):
                    cited.setdefault(f"A{int(m.group(1))}", []).append(f"{path.relative_to(ROOT)}:{i}")
    return cited


def test_registry_rows_are_unique() -> None:
    ids = [r[0] for r in registry_rows()]
    dupes = sorted({x for x in ids if ids.count(x) > 1})
    assert not dupes, f"登记表里同一编号出现多次：{dupes}"


def test_withdrawn_ids_are_never_reused_but_renamed_ids_stay_live() -> None:
    ids = set(registry())
    assert not (ids & withdrawn_ids()), f"撤号被复用（登记表里又出现了）：{sorted(ids & withdrawn_ids())}"
    assert renamed_ids() == {"A19"}, f"「让号」只有旧 A19 一处，实为 {sorted(renamed_ids())}"
    assert "A19" in ids, "让号后 A19 必须仍由先占它的条目持有"


def test_ids_and_withdrawn_ids_cover_a_contiguous_range() -> None:
    union = sorted(int(x[1:]) for x in set(registry()) | withdrawn_ids())
    assert union == list(range(1, len(union) + 1)), f"A 编号有空洞或重复：{union}"


def test_alias_targets_are_live_registered_ids() -> None:
    ids = set(registry())
    targets = alias_targets()
    assert targets == {"A19": "A23", "A20": "A11", "A21": "A17", "A22": "A19"}, targets
    for old, new in targets.items():
        assert new in ids, f"旧号 {old} 指向未登记（或已撤）的 {new}"


def test_registry_active_rows_match_the_archive_active_area() -> None:
    live = active_ids()
    count = archive_active_count()
    assert len(live) == count, f"登记表标「活动」{len(live)} 条，台账活动区实际 {count} 条：{sorted(live)}"
    for k in live:
        assert "活动区" in registry()[k]["where"], f"{k} 标为活动但正文位置不是活动区"


def test_overview_rows_match_registry_one_for_one() -> None:
    rows, ov = registry(), overview_rows()
    assert set(ov) == set(rows), (
        f"总览 §17.4-A 与登记表编号集合不同：仅总览 {sorted(set(ov) - set(rows))}，"
        f"仅登记表 {sorted(set(rows) - set(ov))}"
    )
    overview_active = {k for k, ln in ov.items() if "~~" not in ln}
    assert overview_active == active_ids(), (
        f"活动判定不一致：总览 {sorted(overview_active)} vs 登记表 {sorted(active_ids())}"
    )
    for aid, ln in ov.items():
        want = _STRIP.sub("", rows[aid]["item"])
        got = _STRIP.sub("", _cells(ln)[1])
        assert longest_common_run(want, got) >= 6, f"总览 {aid} 行与登记表不是同一事项：{want[:30]} / {got[:30]}"


def test_state_overview_rows_match_registry() -> None:
    """台账自己的「状态总览」里出现的 A 行，必须与登记表同号同义。"""
    lines = _lines(ARCHIVE)
    start = next(i for i, ln in enumerate(lines) if ln.startswith("## 状态总览"))
    end = next(i for i, ln in enumerate(lines) if ln.startswith(REGISTRY_HEADING))
    rows = registry()
    checked = 0
    for ln in lines[start:end]:
        if not ln.startswith("| "):
            continue
        cells = _cells(ln)
        if len(cells) < 3 or not A_ID.fullmatch(cells[0]):
            continue
        item = cells[2] if cells[1].startswith("Epic") else cells[1]
        want = _STRIP.sub("", rows[cells[0]]["item"])
        assert longest_common_run(want, _STRIP.sub("", item)) >= 6, (
            f"状态总览 {cells[0]} 行与登记表不是同一事项：{want[:30]} / {item[:30]}"
        )
        checked += 1
    assert checked >= 7, f"状态总览里只解析到 {checked} 个 A 行（解析口径可能失效）"


def test_code_cites_only_registered_ids() -> None:
    rows, cited = registry(), code_citations()
    unknown = {k: v[:3] for k, v in cited.items() if k not in rows}
    assert not unknown, f"代码引用了未登记的 A 编号：{unknown}"
    withdrawn_cited = {k: v[:3] for k, v in cited.items() if k in withdrawn_ids()}
    assert not withdrawn_cited, f"代码引用了已撤的编号：{withdrawn_cited}"


def test_archive_active_heading_matches_the_row_count() -> None:
    """活动区标题声明的条数必须等于实际条目数（2026-09-27 曾声明「5 条」而正文 8 条）。"""
    heading = next((ln for ln in _lines(ARCHIVE) if ln.startswith("## 活动（未闭合）条目")), None)
    assert heading is not None, "找不到活动区标题"
    m = re.search(r"——(\d+) 条", heading)
    assert m, f"活动区标题缺条数声明：{heading}"
    actual = archive_active_count()
    assert int(m.group(1)) == actual, f"标题声明与实际不符：{heading} vs 实际 {actual} 条"


def _table_rows(path: Path, heading_prefix: str) -> list[list[str]]:
    lines = _lines(path)
    start = next(i for i, ln in enumerate(lines) if ln.startswith(heading_prefix))
    rows: list[list[str]] = []
    for ln in lines[start + 1 :]:
        if ln.startswith(("**", "## ", "---")):
            break
        if ln.startswith("| ") and not set(ln.strip("| ")) <= {"-", "|", " "} and not ln.startswith("| ID"):
            rows.append(_cells(ln))
    return rows


def test_closed_archive_counts_match_the_tables() -> None:
    """归档引言声明「共 N 条：A 条勘察类 + B 条回填」必须等于两表实际行数（2026-09-28 曾把重复登记计两次）。"""
    lines = _lines(ARCHIVE)
    intro = next(ln for ln in lines if ln.startswith("> 当前闭合归档共"))
    m = re.search(r"共 (\d+) 条：(\d+) 条勘察类正文保留在本文件，(\d+) 条已按归属 Epic 回填", intro)
    assert m, f"归档引言格式变了：{intro[:80]}"
    total, kept, backfilled = (int(x) for x in m.groups())

    t1 = next(ln for ln in lines if ln.startswith("**① 勘察类"))
    t2 = next(ln for ln in lines if ln.startswith("**② 已按归属"))
    assert f"——{kept} 条" in t1, f"① 标题与引言不符：{t1}"
    assert f"——{backfilled} 条" in t2, f"② 标题与引言不符：{t2}"

    rows1 = _table_rows(ARCHIVE, "**① 勘察类")
    rows2 = _table_rows(ARCHIVE, "**② 已按归属")
    assert len(rows1) == kept, f"① 实有 {len(rows1)} 行、标题声明 {kept}"
    assert len(rows2) == backfilled, f"② 实有 {len(rows2)} 行、标题声明 {backfilled}"
    assert total == kept + backfilled, f"总数 {total} ≠ {kept} + {backfilled}"
    ids = [r[0] for r in rows1 + rows2]
    dupes = [x for x in ids if ids.count(x) > 1]
    assert len(ids) == len(set(ids)), f"两张表之间有重复编号（同一事项登记两次）：{dupes}"
