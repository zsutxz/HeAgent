"""Builtin tools for long-term memory and profile updates."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from heagent.tools.decorator import tool
from heagent.tools.runtime import RuntimeSlot

if TYPE_CHECKING:
    from collections.abc import Iterator

    from heagent.memory.facts import FactStore
    from heagent.memory.profile import ProfileStore


@dataclass(slots=True)
class MemoryToolRuntime:
    """Runtime dependencies for memory tools."""

    facts: FactStore | None
    profile: ProfileStore | None


_memory_runtime = RuntimeSlot[MemoryToolRuntime]("heagent_memory_tools")


def configure_memory_tools(
    facts: FactStore | None = None,
    profile: ProfileStore | None = None,
) -> None:
    """Set fallback stores used by memory tools outside an agent run."""
    _memory_runtime.configure(MemoryToolRuntime(facts=facts, profile=profile))


def reset_memory_tools() -> None:
    """Clear fallback memory tool bindings."""
    _memory_runtime.reset()


@contextmanager
def bind_memory_tools(
    *,
    facts: FactStore | None = None,
    profile: ProfileStore | None = None,
) -> Iterator[None]:
    """Bind memory stores for the current run context."""
    with _memory_runtime.bind(MemoryToolRuntime(facts=facts, profile=profile)):
        yield


def _runtime() -> MemoryToolRuntime | None:
    return _memory_runtime.get()


@tool
async def fact_add(fact: str) -> str:
    """Save one long-term fact."""
    runtime = _runtime()
    store = runtime.facts if runtime is not None else None
    if store is None:
        return "Error: fact tools not configured."
    added = await asyncio.to_thread(store.add, fact)
    if added:
        return f"Fact saved: {fact}"
    return "Fact already exists (duplicate detected)."


@tool
async def profile_update(section: str, value: str) -> str:
    """Update one profile section."""
    runtime = _runtime()
    store = runtime.profile if runtime is not None else None
    if store is None:
        return "Error: profile tools not configured."
    await asyncio.to_thread(store.update_section, section, value)
    return f"Profile section '{section}' updated."
