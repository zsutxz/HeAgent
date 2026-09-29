"""Read-only preflight of a configured Goal workflow and its role packages."""

from collections.abc import Callable

from heagent.engine.workflow_resource import WorkflowResource
from heagent.memory.skill_packages import SkillPackage


def diagnose_workflow(
    workflow: WorkflowResource,
    package: SkillPackage,
    resolve_role: Callable[[str], SkillPackage | None],
) -> list[str]:
    """Return explicit problems; package reads enforce their existing hash checks."""
    problems: list[str] = []
    try:
        package.read_entry()
        package.read_resource("workflow.md")
    except (OSError, ValueError) as exc:
        problems.append(f"workflow package: {exc}")
    for role in sorted({step.role for step in workflow.steps if step.role}):
        role_package = resolve_role(role)
        if role_package is None:
            problems.append(f"role package missing: {role}")
            continue
        try:
            role_package.read_entry()
        except (OSError, ValueError) as exc:
            problems.append(f"role package {role}: {exc}")
    return problems
