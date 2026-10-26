"""S-7：遗留台账的**条目守恒判据**（四断言：全集相等 / 互斥 / 落点非空 / 反僵尸）。

为什么需要它：台账是「哪个问题还没修」的唯一真源。历史上真实发生过三种失真——
同一 A 号在两地异义（A19）、代码引用未登记的 A 号、活动计数长期不同步（2026-10-20 四份文档仍写 0）。
既有 `tests/test_deferred_id_registry.py` 盯的是**形状与计数**；本文件盯的是**守恒**：一条都不许悄悄消失，
也不许无痕重生。

设计要点：
- 判据写成**纯函数** `audit(archive_text, entry_text) -> list[str]`，真实文件与合成样本走同一条代码路径；
  否则「负面用例」只能靠改真实文件，既危险又不可复跑。
- 基线 `BASELINE_IDS` = S-6 归一退出时的 67 个 ID 快照。它是「反僵尸」的锚：不在这份快照里的新 ID
  必须在同一行带 `origin=新增` 标记，否则视为「归档条目被无痕复制回来」。
- 只读 markdown、只用 stdlib。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "_bmad-output" / "implementation-artifacts" / "deferred-work-archive.md"
ENTRY = ROOT / "_bmad-output" / "implementation-artifacts" / "deferred-work.md"

ID_RE = re.compile(r"(?:Z-D\d+|A\d+)")
ACTIVE = "活动（未闭合）条目"
CLOSED = "本轮闭合"
RETIRED = "显式退役"
ARCHIVED = "已按 Epic 归档"
INDEX = "跨周期勘察与裁定索引"
SECTION_NAMES = (ACTIVE, CLOSED, RETIRED, ARCHIVED, INDEX)

#: S-6（2026-10-26）归一退出时的条目快照，共 67 个 ID。新增条目必须带 `origin=新增` 才能越过它。
BASELINE_IDS = frozenset(
    {
        "A1",
        "A2",
        "A3",
        "A4",
        "A5",
        "A6",
        "A8",
        "A9",
        "A10",
        "A11",
        "A12",
        "A15",
        "A16",
        "A17",
        "A18",
        "A19",
        "A23",
        "A24",
        "A25",
        "A26",
        "A27",
        "A28",
        "A29",
        "A30",
        "A31",
        "A32",
        "A33",
        "A34",
        "A35",
        "A36",
        "A37",
        "A38",
        "A39",
        "A40",
        "A41",
        "A42",
        "A43",
        "A44",
        "A45",
        "A46",
        "A47",
        "A48",
        "A49",
        "Z-D1",
        "Z-D2",
        "Z-D3",
        "Z-D4",
        "Z-D5",
        "Z-D6",
        "Z-D7",
        "Z-D8",
        "Z-D9",
        "Z-D10",
        "Z-D11",
        "Z-D12",
        "Z-D13",
        "Z-D14",
        "Z-D15",
        "Z-D16",
        "Z-D17",
        "Z-D18",
        "Z-D19",
        "Z-D20",
        "Z-D21",
        "Z-D22",
        "Z-D23",
        "Z-D24",
    }
)

#: 合法状态取值（`## 活动（未闭合）条目` 的「状态」列）。
VALID_STATES = frozenset({"active", "scheduled", "frozen"})


def split_sections(text: str) -> dict[str, str]:
    """按 ``## <名字>`` 切段；只认本文件关心的五段（其余忽略）。"""
    found: dict[str, str] = {}
    for name in SECTION_NAMES:
        match = re.search(rf"^## {re.escape(name)}.*?$(.*?)(?=^## |\Z)", text, flags=re.S | re.M)
        found[name] = match.group(1) if match else ""
    return found


def rows(section_text: str) -> list[list[str]]:
    """取表格数据行（跳过表头与分隔线）。"""
    out: list[list[str]] = []
    for line in section_text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not cells or set("".join(cells)) <= {"-", " "}:
            continue  # 分隔线
        if ID_RE.search(cells[0]) is None:
            continue  # 表头
        out.append(cells)
    return out


def ids_in(cell: str) -> list[str]:
    return ID_RE.findall(cell)


def _ids_by_section(sections: dict[str, str]) -> dict[str, list[str]]:
    """各段的 ID 序列（按出现顺序，保留重复以便查重）。"""
    return {name: [ident for row in rows(sections[name]) for ident in ids_in(row[0])] for name in SECTION_NAMES}


def _check_mutex(planned: dict[str, list[str]]) -> list[str]:
    """断言 2：互斥（同一 ID 不得同时处于两种状态）+ 段内不重复登记。"""
    findings: list[str] = []
    live = set(planned[ACTIVE])
    for other_name, key in (("本轮闭合", CLOSED), ("显式退役", RETIRED)):
        overlap = live & set(planned[key])
        if overlap:
            findings.append(f"互斥破坏：{sorted(overlap)} 同时出现在「活动」与「{other_name}」")
    overlap = set(planned[CLOSED]) & set(planned[RETIRED])
    if overlap:
        findings.append(f"互斥破坏：{sorted(overlap)} 同时出现在「本轮闭合」与「显式退役」")
    for name in (ACTIVE, CLOSED, RETIRED):
        collected = planned[name]
        dupes = sorted({ident for ident in collected if collected.count(ident) > 1})
        if dupes:
            findings.append(f"重复登记：{dupes} 在「{name}」段出现多次")
    return findings


def _check_landing(sections: dict[str, str]) -> list[str]:
    """断言 3：落点非空（列数、状态取值、frozen 的裁定指针、退役 5 字段）。"""
    findings: list[str] = []
    for row in rows(sections[ACTIVE]):
        if len(row) != 4 or not all(row):
            findings.append(f"落点为空或列数不为 4：{row}")
            continue
        if row[2] not in {f"`{state}`" for state in VALID_STATES}:
            findings.append(f"状态取值非法：{row[0]} -> {row[2]}")
        if row[2] == "`frozen`" and "裁定指针" not in row[3]:
            findings.append(f"frozen 缺裁定指针：{row[0]}")
    for row in rows(sections[CLOSED]):
        if len(row) != 3 or not all(row):
            findings.append(f"本轮闭合行落点为空：{row}")
    for row in rows(sections[RETIRED]):
        if len(row) != 6:
            findings.append(f"退役行不是 6 列：{row}")
            continue
        if row[0].startswith("（当前"):
            continue  # 空表占位行
        blanks = [index for index, cell in enumerate(row[1:], start=1) if not cell or cell == "—"]
        if blanks:
            findings.append(f"退役条目字段空缺（列 {blanks}）：{row[0]}")
    return findings


def _check_conservation(archive_ids: set[str]) -> list[str]:
    """断言 1：全集相等（基线里的条目一条都不许静默消失）。"""
    dropped = sorted(BASELINE_IDS - archive_ids)
    return [f"条目静默消失（基线有、台账无）：{dropped}"] if dropped else []


def _check_anti_zombie(archive_text: str, archive_ids: set[str]) -> list[str]:
    """断言 4：反僵尸（新 ID 必须带 ``origin=新增`` 标记，且标记不得悬空）。"""
    marked: set[str] = set()
    for line in archive_text.splitlines():
        if "origin=新增" in line:
            marked |= set(ids_in(line.split("origin=新增")[0]))
    findings: list[str] = []
    unmarked = sorted((archive_ids - BASELINE_IDS) - marked)
    if unmarked:
        findings.append(f"未登记的新 ID 缺少 origin=新增 标记：{unmarked}")
    stale = sorted(marked - archive_ids)
    if stale:
        findings.append(f"origin=新增 标记悬空（该 ID 不在任何段）：{stale}")
    return findings


def _check_single_source(entry_text: str, planned: dict[str, list[str]]) -> list[str]:
    """断言 1b：单一真源（入口表 == 活动段；已闭合/已退役不得仍挂入口）。"""
    entry_rows = rows(split_sections(entry_text).get(ACTIVE, "")) or rows(entry_text)
    entry_ids = [ident for row in entry_rows for ident in ids_in(row[0])]
    live = set(planned[ACTIVE])
    findings: list[str] = []
    if set(entry_ids) != live:
        findings.append(
            f"入口表与活动段不一致：入口缺 {sorted(live - set(entry_ids))}，入口多 {sorted(set(entry_ids) - live)}"
        )
    stale = sorted(set(entry_ids) & (set(planned[CLOSED]) | set(planned[RETIRED])))
    if stale:
        findings.append(f"已闭合/已退役条目仍出现在入口表：{stale}")
    return findings


def audit(archive_text: str, entry_text: str) -> list[str]:
    """四断言审计；返回发现列表（空 = 守恒）。"""
    sections = split_sections(archive_text)
    planned = _ids_by_section(sections)
    archive_ids = {ident for collected in planned.values() for ident in collected}
    return [
        *_check_mutex(planned),
        *_check_landing(sections),
        *_check_conservation(archive_ids),
        *_check_anti_zombie(archive_text, archive_ids),
        *_check_single_source(entry_text, planned),
    ]


# --------------------------------------------------------------------------- 真实台账


def test_real_ledgers_are_conserved() -> None:
    """四断言对真实台账全绿：S-6 归一后的结构确实守恒。"""
    findings = audit(ARCHIVE.read_text(encoding="utf-8"), ENTRY.read_text(encoding="utf-8"))
    assert findings == [], "台账不守恒：\n" + "\n".join(f"  - {item}" for item in findings)


# --------------------------------------------------------------------------- 负面用例（合成样本）


def _archive_text() -> str:
    return ARCHIVE.read_text(encoding="utf-8")


def _entry_text() -> str:
    return ENTRY.read_text(encoding="utf-8")


def _synthetic(active_rows: list[str], retired_rows: list[str] | None = None) -> str:
    """最小可解析台账：五段齐备，只填活动行（用于负面用例，避免依赖真实文件的措辞）。

    基线里的大量 ID 会缺席 ⇒ 审计**必然**同时报「条目静默消失」；负面用例一律用 ``any(...)``
    断言自己关心的那条发现，不被旁证干扰。
    """
    retired = retired_rows or ["| （当前 0 条） | — | — | — | — | — |"]
    return (
        "# Deferred Work Archive\n\n"
        "## 活动（未闭合）条目\n\n| ID | 主题 | 状态 | 说明 |\n| --- | --- | --- | --- |\n"
        + "\n".join(active_rows)
        + "\n\n## 已按 Epic 归档\n\n| ID | 主题 | 状态 | 正文 |\n| --- | --- | --- | --- |\n"
        + "\n## 本轮闭合\n\n| ID | 主题 | 证据 |\n| --- | --- | --- |\n"
        + "\n## 显式退役\n\n"
        + "| ID | retired_reason | replaced_by | decision_ref | retired_on | recheck_condition |\n"
        + "| --- | --- | --- | --- | --- | --- |\n"
        + "\n".join(retired)
        + "\n\n## 跨周期勘察与裁定索引\n\n| ID | 主题 | 结论 |\n| --- | --- | --- |\n"
    )


def test_duplicate_across_states_is_reported() -> None:
    """同一 ID 同时出现在「活动」与「本轮闭合」⇒ 互斥断言必须报。"""
    mutated = _archive_text().replace(
        "| A45 | `KeyboardInterrupt`",
        "| A34 | `KeyboardInterrupt`",
        1,
    )
    findings = audit(mutated, _entry_text())
    assert any("互斥破坏" in item and "A34" in item for item in findings), findings


def test_dropped_id_is_reported() -> None:
    """把一条活动条目整行删掉 ⇒ 全集断言必须点名它。"""
    lines = [line for line in _archive_text().splitlines() if not line.startswith("| A49 |")]
    findings = audit("\n".join(lines), _entry_text())
    assert any("条目静默消失" in item and "A49" in item for item in findings), findings


def test_entry_table_must_track_active_ids() -> None:
    """入口表漏掉一条活动 ID ⇒ 单一真源断言必须报（而不是静默只读一半）。"""
    mutated = "\n".join(line for line in _entry_text().splitlines() if not line.startswith("| A49 |"))
    findings = audit(_archive_text(), mutated)
    assert any("入口表与活动段不一致" in item and "A49" in item for item in findings), findings


def test_empty_landing_is_reported() -> None:
    """活动行的说明列被清空 ⇒ 落点非空断言必须报。"""
    findings = audit(_synthetic(["| A34 | 主题 | `active` |  |"]), _entry_text())
    assert any("落点为空" in item for item in findings), findings


def test_frozen_without_pointer_is_reported() -> None:
    """frozen 条目丢了「裁定指针」⇒ 必须报（挂起没有指针就不是状态，是遗忘）。"""
    mutated = _archive_text().replace(
        "**裁定指针：AD-20（OQ-4 未裁）**；短期靠围栏预防层降低概率",
        "短期靠围栏预防层降低概率",
        1,
    )
    findings = audit(mutated, _entry_text())
    assert any("frozen 缺裁定指针" in item and "A41" in item for item in findings), findings


def test_unregistered_new_id_needs_origin_marker() -> None:
    """新增一条基线里没有的 ID：不带标记必须红，带 `origin=新增` 则必须放过。"""
    phantom = f"A{99}"
    row = f"| {phantom} | 假想新条目 | `active` | 触发条件：测试 |"
    findings = audit(_synthetic([row]), _entry_text())
    assert any("origin=新增" in item and phantom in item for item in findings), findings

    marked_row = f"| {phantom} | 假想新条目 | `active` | 触发条件：测试 origin=新增 |"
    findings_with_marker = audit(_synthetic([marked_row]), _entry_text())
    assert not any(phantom in item and "origin=新增" in item for item in findings_with_marker), findings_with_marker


def test_retired_entry_requires_all_five_fields() -> None:
    """退役条目缺一个字段 ⇒ 必须报（5 字段缺一即无效）。"""
    retired = f"| A{99} | 不再修 | `src/x.py:1` | 2026-10-26 决策日志 | — | 出现真实案例 |"
    findings = audit(_synthetic(["| A34 | 主题 | `active` | 说明 |"], [retired]), _entry_text())
    assert any("退役条目字段空缺" in item and f"A{99}" in item for item in findings), findings
