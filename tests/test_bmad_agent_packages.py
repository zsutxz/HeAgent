"""Regression coverage for the local BMad role packages (bmad-agent-* canonical)."""

from __future__ import annotations

from pathlib import Path

import pytest

from heagent.memory.skill_packages import SkillCatalog, SkillPackageResourceError, SkillResolver


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / ".heagent" / "skills"
# canonical bmad id -> legacy he-* alias that must still resolve to the same package
EXPECTED = {
    "bmad-agent-pm": "he-agent-pm",
    "bmad-agent-analyst": "he-agent-analyst",
    "bmad-agent-architect": "he-agent-architect",
    "bmad-agent-ux-designer": "he-agent-ux",
    "bmad-agent-dev": "he-agent-dev",
}


def test_bmad_agent_packages_are_discoverable_with_compat_aliases() -> None:
    entries = {entry.canonical_id: entry for entry in SkillCatalog([PACKAGE_ROOT]).scan()}

    assert set(EXPECTED) <= set(entries)
    for canonical_id, legacy_alias in EXPECTED.items():
        entry = entries[canonical_id]
        assert entry.source_id == canonical_id
        assert legacy_alias in entry.aliases
        assert entry.package is not None
        text = entry.package.read_entry().text
        assert "## Inputs" in text
        assert "## Outputs" in text
        assert "## Responsibilities" in text
        assert "## Decision Boundaries" in text
        assert "## Checklist" in text
        assert "## Stop Conditions" in text
        assert "never advances a Goal phase" in text


@pytest.mark.parametrize("requested", [*EXPECTED, *EXPECTED.values()])
def test_bmad_agent_ids_resolve_to_root_fenced_packages(requested: str) -> None:
    catalog = SkillCatalog([PACKAGE_ROOT])
    catalog.scan()
    package = SkillResolver(catalog).resolve(requested)

    assert package.root == (PACKAGE_ROOT / package.skill_id).resolve()
    with pytest.raises(SkillPackageResourceError):
        package.read_resource("../AGENTS.md")
