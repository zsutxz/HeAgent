"""Contracts for the compact deferred-work archive."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "_bmad-output" / "implementation-artifacts" / "deferred-work-archive.md"
OVERVIEW = ROOT / "_bmad-output" / "consolidated-overview.md"
EPICS = ROOT / "_bmad-output" / "epics"
ID = re.compile(r"(?:A\d+|Z-D\d+|[ES]\d+(?:-[A-Z]?\d+)?)")
# Citation shape: the A-number must not be glued to letters/digits/hyphens/quotes
# (rejects FR-A1, A1b, AD-1, string fixtures like "A1", and the A256 inside SHA256).
CITE = re.compile(r"(?<![A-Za-z0-9_'\"-])A(0|[1-9]\d*)(?![0-9A-Za-z])")


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip("|").split("|")]


def _heading_index(lines: list[str], heading: str) -> int:
    index = next((i for i, line in enumerate(lines) if line.startswith(heading)), None)
    assert index is not None, f"missing heading {heading!r}"
    return index


def _table(path: Path, heading: str) -> list[list[str]]:
    lines = _lines(path)
    start = _heading_index(lines, heading)
    rows: list[list[str]] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        if line.startswith("| ") and set(line.strip("| ")) > {"-", "|", " "}:
            rows.append(_cells(line))
    return rows


def _epic_ledgers() -> list[Path]:
    return sorted(EPICS.rglob("deferred-work.md"))


def _documented_a_numbers() -> set[str]:
    paths = [ARCHIVE, *_epic_ledgers()]
    return {f"A{int(match.group(1))}" for path in paths for line in _lines(path) for match in CITE.finditer(line)}


def _code_citations() -> dict[str, list[str]]:
    cited: dict[str, list[str]] = {}
    self_name = Path(__file__).name
    for base in (ROOT / "src" / "heagent", ROOT / "tests"):
        for path in sorted(base.rglob("*.py")):
            if path.name == self_name:
                continue
            for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                for match in CITE.finditer(line):
                    cited.setdefault(f"A{int(match.group(1))}", []).append(f"{path.relative_to(ROOT)}:{line_number}")
    return cited


def test_archive_uses_the_current_compact_shape() -> None:
    lines = _lines(ARCHIVE)
    start = _heading_index(lines, "## 活动（未闭合）条目")
    end = _heading_index(lines, "## 已按 Epic 归档")
    assert lines[start + 2].strip() == "无。"
    assert "当前活动项为 0 条" in lines[2]
    assert not any(line.startswith("## A 编号登记表") for line in lines[start:end])


def test_archive_epic_index_has_existing_targets() -> None:
    rows = _table(ARCHIVE, "## 已按 Epic 归档")
    assert rows
    for row in rows:
        assert len(row) == 4
        links = re.findall(r"\]\(([^)]+)\)", row[3])
        assert links, f"archive row has no target: {row[0]}"
        target_dir = Path(links[0]).parent.name
        assert list(EPICS.glob(f"{target_dir}/deferred-work.md")), f"archive row target does not resolve: {links[0]}"


def test_code_cites_only_documented_a_numbers() -> None:
    documented = _documented_a_numbers()
    unknown = {key: locations[:3] for key, locations in _code_citations().items() if key not in documented}
    assert not unknown, f"code cites undocumented A numbers: {unknown}"


def test_epic_ledgers_without_id_sections_carry_a_no_active_marker() -> None:
    files = _epic_ledgers()
    assert len(files) == 10, f"expected 10 Epic ledgers, found {len(files)}"
    for path in files:
        lines = _lines(path)
        has_id_sections = any(line.startswith(("## ", "### ")) and ID.search(line) for line in lines)
        if not has_id_sections:
            text = "\n".join(lines)
            assert "当前活动项无" in text or "只登记已闭合项" in text, (
                f"{path.name}: no ID sections and no no-active marker"
            )


def test_all_active_count_declarations_are_zero() -> None:
    sites = (
        ARCHIVE,
        OVERVIEW,
        ROOT / "_bmad-output" / "README.md",
        ROOT / "_bmad-output" / "retrospective-all-cycles.md",
    )
    for path in sites:
        text = path.read_text(encoding="utf-8")
        # (?<!\d) so a nonzero count ending in 0 (e.g. "10 条") cannot pass as zero.
        assert re.search(r"活动(?:项|区|台账)[^\n]{0,30}(?<!\d)0 条", text), (
            f"{path.name} has no zero active-count declaration"
        )
