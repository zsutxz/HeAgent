"""Coverage gap tests for tools/builtins/memory.py.

Covers previously untested branches:
  - fact_add(): runtime None → error, store None → error, duplicate → "already exists"
  - profile_update(): runtime None → error, store None → error
  - configure_memory_tools / reset_memory_tools / bind_memory_tools basic call paths
"""

from __future__ import annotations

import pytest

from heagent.memory.facts import FactStore
from heagent.memory.profile import ProfileStore
from heagent.tools.builtins.memory import (
    bind_memory_tools,
    configure_memory_tools,
    fact_add,
    profile_update,
    reset_memory_tools,
)


@pytest.fixture(autouse=True)
def _reset_after() -> None:
    """Wipe module-level memory tool state between tests to avoid cross-test pollution."""
    yield
    reset_memory_tools()


# ---------------------------------------------------------------------------
# fact_add  error paths
# ---------------------------------------------------------------------------

class TestFactAddErrors:
    """fact_add() → "Error: fact tools not configured." branches."""

    async def test_runtime_none_no_configuration(self) -> None:
        """No configure / no bind → _runtime() returns None → error."""
        result = await fact_add(fact="anything")
        assert result == "Error: fact tools not configured."

    async def test_store_none_when_facts_is_none(self) -> None:
        """Runtime exists (configure called) but facts=None → store is None → error."""
        configure_memory_tools(facts=None)
        result = await fact_add(fact="anything")
        assert result == "Error: fact tools not configured."


# ---------------------------------------------------------------------------
# fact_add  duplicate path
# ---------------------------------------------------------------------------

class TestFactAddDuplicate:
    """fact_add() → "Fact already exists (duplicate detected)." branch."""

    async def test_exact_duplicate(self, tmp_path: object) -> None:
        """Adding the identical string twice triggers the dedup path."""
        store = FactStore(path=str(tmp_path / "facts.md"))  # type: ignore[operator]
        configure_memory_tools(facts=store)

        await fact_add(fact="Python is great")
        result = await fact_add(fact="Python is great")
        assert result == "Fact already exists (duplicate detected)."

    async def test_similar_fact_word_overlap_above_70_percent(self, tmp_path: object) -> None:
        """Dedup via keyword overlap > 70 % also returns the same message."""
        store = FactStore(path=str(tmp_path / "facts.md"))  # type: ignore[operator]
        configure_memory_tools(facts=store)

        await fact_add(fact="the user prefers dark mode")
        # "user prefers dark mode always" overlaps "user prefers dark mode"
        result = await fact_add(fact="user prefers dark mode always")
        assert result == "Fact already exists (duplicate detected)."


# ---------------------------------------------------------------------------
# profile_update  error paths
# ---------------------------------------------------------------------------

class TestProfileUpdateErrors:
    """profile_update() → "Error: profile tools not configured." branches."""

    async def test_runtime_none_no_configuration(self) -> None:
        """No configure / no bind → _runtime() returns None → error."""
        result = await profile_update(section="style", value="concise")
        assert result == "Error: profile tools not configured."

    async def test_store_none_when_profile_is_none(self) -> None:
        """Runtime exists but profile=None → store is None → error."""
        configure_memory_tools(profile=None)
        result = await profile_update(section="style", value="concise")
        assert result == "Error: profile tools not configured."


# ---------------------------------------------------------------------------
# configure_memory_tools
# ---------------------------------------------------------------------------

class TestConfigure:
    """configure_memory_tools() basic call paths."""

    async def test_full_configure_then_both_tools_succeed(self, tmp_path: object) -> None:
        """Configure both stores → fact_add + profile_update both work."""
        facts = FactStore(path=str(tmp_path / "facts.md"))  # type: ignore[operator]
        profile = ProfileStore(path=str(tmp_path / "profile.md"))  # type: ignore[operator]
        configure_memory_tools(facts=facts, profile=profile)

        r1 = await fact_add(fact="hello")
        r2 = await profile_update(section="bg", value="developer")
        assert r1 == "Fact saved: hello"
        assert r2 == "Profile section 'bg' updated."

    async def test_configure_facts_only_profile_still_errors(self, tmp_path: object) -> None:
        """When only facts is set, profile_update still reports not configured."""
        facts = FactStore(path=str(tmp_path / "facts.md"))  # type: ignore[operator]
        configure_memory_tools(facts=facts)

        r_fact = await fact_add(fact="hello")
        r_prof = await profile_update(section="bg", value="dev")
        assert r_fact == "Fact saved: hello"
        assert r_prof == "Error: profile tools not configured."

    async def test_configure_profile_only_facts_still_errors(self, tmp_path: object) -> None:
        """When only profile is set, fact_add still reports not configured."""
        profile = ProfileStore(path=str(tmp_path / "profile.md"))  # type: ignore[operator]
        configure_memory_tools(profile=profile)

        r_fact = await fact_add(fact="hello")
        r_prof = await profile_update(section="bg", value="dev")
        assert r_fact == "Error: fact tools not configured."
        assert r_prof == "Profile section 'bg' updated."


# ---------------------------------------------------------------------------
# reset_memory_tools
# ---------------------------------------------------------------------------

class TestReset:
    """reset_memory_tools() basic call path."""

    async def test_reset_after_configure_breaks_tools(self, tmp_path: object) -> None:
        """After reset, a previously-configured tool returns the error string."""
        facts = FactStore(path=str(tmp_path / "facts.md"))  # type: ignore[operator]
        configure_memory_tools(facts=facts)

        await fact_add(fact="before reset")
        reset_memory_tools()

        result = await fact_add(fact="after reset")
        assert result == "Error: fact tools not configured."


# ---------------------------------------------------------------------------
# bind_memory_tools  (context manager)
# ---------------------------------------------------------------------------

class TestBind:
    """bind_memory_tools() context-manager paths."""

    async def test_bind_overrides_configured_default(self, tmp_path: object) -> None:
        """bind temporarily replaces the configured default store."""
        store_default = FactStore(path=str(tmp_path / "default.md"))  # type: ignore[operator]
        store_bound = FactStore(path=str(tmp_path / "bound.md"))  # type: ignore[operator]

        configure_memory_tools(facts=store_default)
        await fact_add(fact="from default")

        with bind_memory_tools(facts=store_bound):
            r = await fact_add(fact="from bind")
            assert r == "Fact saved: from bind"

        # After exiting the block the default store is active again
        r = await fact_add(fact="after bind")
        assert r == "Fact saved: after bind"
        assert store_default.load() == ["from default", "after bind"]
        assert store_bound.load() == ["from bind"]

    async def test_bind_without_prior_configure(self, tmp_path: object) -> None:
        """bind works even when no default was configured."""
        store = FactStore(path=str(tmp_path / "bound_only.md"))  # type: ignore[operator]

        # No configure — outside bind tools error
        assert "not configured" in await fact_add(fact="outside")

        with bind_memory_tools(facts=store):
            r = await fact_add(fact="inside bind")
            assert r == "Fact saved: inside bind"

        # Back to error outside
        assert "not configured" in await fact_add(fact="after bind")

    async def test_bind_none_disables_tools_inside_block(self, tmp_path: object) -> None:
        """bind with None stores → both tools error inside the block."""
        facts = FactStore(path=str(tmp_path / "f.md"))  # type: ignore[operator]
        configure_memory_tools(facts=facts)

        with bind_memory_tools(facts=None, profile=None):
            r_fact = await fact_add(fact="test")
            r_prof = await profile_update(section="s", value="v")
            assert r_fact == "Error: fact tools not configured."
            assert r_prof == "Error: profile tools not configured."

        # Outside the block tools work again
        r = await fact_add(fact="after")
        assert r == "Fact saved: after"

    async def test_bind_only_profile_facts_becomes_none(self, tmp_path: object) -> None:
        """bind only sets profile → facts=None inside (no merge with default)."""
        profile = ProfileStore(path=str(tmp_path / "p.md"))  # type: ignore[operator]
        configure_memory_tools(facts=None, profile=None)

        with bind_memory_tools(profile=profile):
            # facts was not passed → defaults to None
            r_fact = await fact_add(fact="test")
            r_prof = await profile_update(section="s", value="v")
            assert r_fact == "Error: fact tools not configured."
            assert r_prof == "Profile section 's' updated."

    async def test_bind_only_facts_profile_becomes_none(self, tmp_path: object) -> None:
        """bind only sets facts → profile=None inside (no merge with default)."""
        facts = FactStore(path=str(tmp_path / "f.md"))  # type: ignore[operator]
        configure_memory_tools(facts=None, profile=None)

        with bind_memory_tools(facts=facts):
            r_fact = await fact_add(fact="test")
            r_prof = await profile_update(section="s", value="v")
            assert r_fact == "Fact saved: test"
            assert r_prof == "Error: profile tools not configured."
