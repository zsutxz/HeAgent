"""Regression coverage for the migrated HeAgent BMad role packages."""

from __future__ import annotations

from pathlib import Path

import pytest

from heagent.memory.skill_packages import SkillCatalog, SkillPackageResourceError, SkillResolver


ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / ".heagent" / "skills"
EXPECTED = {
    "he-agent-pm": "bmad-agent-pm",
    "he-agent-analyst": "bmad-agent-analyst",
    "he-agent-architect": "bmad-agent-architect",
    "he-agent-ux": "bmad-agent-ux-designer",
    "he-agent-dev": "bmad-agent-dev",
}


def test_bmad_agent_packages_are_discoverable_with_traced_ids() -> None:
    entries = {entry.canonical_id: entry for entry in SkillCatalog([PACKAGE_ROOT]).scan()}

    assert set(EXPECTED) <= set(entries)
    for canonical_id, source_id in EXPECTED.items():
        entry = entries[canonical_id]
        assert entry.source_id == source_id
        assert source_id in entry.aliases
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
def test_bmad_agent_aliases_resolve_to_root_fenced_packages(requested: str) -> None:
    catalog = SkillCatalog([PACKAGE_ROOT])
    catalog.scan()
    package = SkillResolver(catalog).resolve(requested)

    assert package.root == (PACKAGE_ROOT / package.skill_id).resolve()
    with pytest.raises(SkillPackageResourceError):
        package.read_resource("../AGENTS.md")
