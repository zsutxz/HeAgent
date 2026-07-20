"""Builtin tools for skill management."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING

from heagent.tools.decorator import tool
from heagent.tools.runtime import RuntimeSlot

if TYPE_CHECKING:
    from collections.abc import Iterator

    from heagent.memory.skills import SkillStore


@dataclass(slots=True)
class SkillToolRuntime:
    """Runtime dependencies for skill tools."""

    store: SkillStore | None


_skill_runtime = RuntimeSlot[SkillToolRuntime]("heagent_skill_tools")


def configure_skill_tools(store: SkillStore | None) -> None:
    """Set the fallback skill store used outside an agent run."""
    _skill_runtime.configure(SkillToolRuntime(store=store))


def reset_skill_tools() -> None:
    """Clear the fallback skill store."""
    _skill_runtime.reset()


@contextmanager
def bind_skill_tools(store: SkillStore | None) -> Iterator[None]:
    """Bind a skill store for the current run context."""
    with _skill_runtime.bind(SkillToolRuntime(store=store)):
        yield


def _store() -> SkillStore | None:
    runtime = _skill_runtime.get()
    return runtime.store if runtime is not None else None


@tool
async def skill_create(
    name: str,
    description: str,
    pattern: str,
    steps: str,
    tags: str = "",
) -> str:
    """Create a reusable skill."""
    store = _store()
    if store is None:
        return "Error: skill tools not configured."
    if await asyncio.to_thread(store.load, name) is not None:
        return f"Error: skill '{name}' already exists. Use skill_update to modify it."
    step_list = [step.strip() for step in steps.split("|") if step.strip()]
    if not step_list:
        return "Error: at least one step is required."
    tag_list = [tag.strip() for tag in tags.split("|") if tag.strip()] if tags else None
    try:
        path = await asyncio.to_thread(store.save, name, description, pattern, step_list, tags=tag_list)
    except ValueError as exc:
        return f"Error: {exc}"
    return f"Skill '{name}' created at {path}"


@tool
async def skill_update(
    name: str,
    description: str = "",
    pattern: str = "",
    steps: str = "",
    tags: str = "",
) -> str:
    """Update an existing skill."""
    store = _store()
    if store is None:
        return "Error: skill tools not configured."
    if await asyncio.to_thread(store.parse, name) is None:
        return f"Error: skill '{name}' not found. Use skill_create first."
    description_value = description or None
    pattern_value = pattern or None
    step_list = [step.strip() for step in steps.split("|") if step.strip()] if steps else None
    tag_list = [tag.strip() for tag in tags.split("|") if tag.strip()] if tags else None
    path = await asyncio.to_thread(
        store.update, name,
        description=description_value, pattern=pattern_value, steps=step_list, tags=tag_list,
    )
    if path is None:
        return f"Error: failed to update skill '{name}'."
    return f"Skill '{name}' updated at {path}"


@tool
async def skill_list() -> str:
    """List stored skills."""
    store = _store()
    if store is None:
        return "Error: skill tools not configured."
    names = await asyncio.to_thread(store.list_skills)
    if not names:
        return "No skills stored yet. Use skill_create to add one."

    def _build_lines() -> list[str]:
        lines: list[str] = []
        for name in names:
            parsed = store.parse(name)
            description = parsed.description if parsed is not None else "(unable to parse)"
            lines.append(f"- {name}: {description}")
        return lines

    lines = await asyncio.to_thread(_build_lines)
    return "\n".join(lines)


@tool
async def skill_delete(name: str) -> str:
    """Delete one stored skill."""
    store = _store()
    if store is None:
        return "Error: skill tools not configured."
    if await asyncio.to_thread(store.delete, name):
        return f"Skill '{name}' deleted."
    return f"Error: skill '{name}' not found."


@tool
async def skill_curate(days: str = "30") -> str:
    """List stale skills that have not been used recently."""
    store = _store()
    if store is None:
        return "Error: skill tools not configured."
    try:
        stale_days = int(days)
    except ValueError:
        return "Error: days must be a number."
    stale = await asyncio.to_thread(store.stale_skills, days=stale_days)
    if not stale:
        return f"No stale skills found (all used within {stale_days} days)."

    def _build_curate_lines() -> list[str]:
        lines = [f"Found {len(stale)} stale skill(s) (unused for {stale_days}+ days):\n"]
        for name in stale:
            parsed = store.parse(name)
            if parsed is None:
                lines.append(f"- {name}: (parse error)")
            else:
                lines.append(f"- {name}: used {parsed.usage_count}x, last: {parsed.last_used or 'never'}")
        return lines

    lines = await asyncio.to_thread(_build_curate_lines)
    return "\n".join(lines)


@tool
async def skill_archive(name: str) -> str:
    """Archive one stored skill."""
    store = _store()
    if store is None:
        return "Error: skill tools not configured."
    if await asyncio.to_thread(store.archive, name):
        return f"Skill '{name}' archived to .heagent/skills/.archive/"
    return f"Error: skill '{name}' not found."
