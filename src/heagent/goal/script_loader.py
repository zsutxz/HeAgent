"""Load and statically constrain package-local GoalScript resources."""

from __future__ import annotations

import ast
from dataclasses import dataclass

from heagent.memory.skill_packages import SkillPackage, SkillPackageResourceError

#: GoalScript 的**唯一入口名**（单一真源：加载期校验与运行时取用同源，两处永不漂移）。
#: 名字沿用专项方案的示意接口（``async def build_workflow(goal)``）；非此名的定义一律
#: 加载期拒绝——辅助函数是递归与复杂宿主控制流的载体。
SCRIPT_ENTRYPOINT = "build_workflow"


class GoalScriptLoadError(ValueError):
    """Raised when a script is missing or contains a forbidden capability."""


_FORBIDDEN_NAMES = frozenset(
    {
        "open",
        "exec",
        "eval",
        "compile",
        "__import__",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "vars",
    }
)
_FORBIDDEN_MODULES = frozenset(
    {
        "asyncio",
        "os",
        "pathlib",
        "socket",
        "subprocess",
        "sys",
        "shutil",
        "git",
        "requests",
        "urllib",
        "httpx",
    }
)


@dataclass(frozen=True)
class GoalScriptResource:
    name: str
    source: str
    tree: ast.Module


def load_script(package: SkillPackage, resource: str) -> GoalScriptResource:
    """Read one ``scripts/`` resource through the package integrity channel."""
    try:
        source = package.read_script(resource)
    except SkillPackageResourceError as exc:
        raise GoalScriptLoadError(str(exc)) from exc
    try:
        tree = ast.parse(source, filename=f"scripts/{resource}", mode="exec")
    except SyntaxError as exc:
        raise GoalScriptLoadError(f"invalid GoalScript syntax in {resource}: {exc}") from exc
    _validate_tree(tree, resource)
    return GoalScriptResource(name=resource, source=source, tree=tree)


def _validate_tree(tree: ast.Module, resource: str) -> None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = [alias.name.split(".", 1)[0] for alias in node.names]
            if any(name in _FORBIDDEN_MODULES for name in names):
                raise GoalScriptLoadError(f"forbidden import in GoalScript resource: {resource}")
        elif isinstance(node, ast.Name) and (node.id in _FORBIDDEN_NAMES or node.id.startswith("__")):
            raise GoalScriptLoadError(f"forbidden capability '{node.id}' in GoalScript resource: {resource}")
        elif isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise GoalScriptLoadError(f"private attribute access is forbidden in GoalScript resource: {resource}")
        elif isinstance(node, ast.While):
            raise GoalScriptLoadError(f"while loops are forbidden in GoalScript resource: {resource}")
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name != SCRIPT_ENTRYPOINT:
            raise GoalScriptLoadError(f"only {SCRIPT_ENTRYPOINT}() may be defined in GoalScript resource: {resource}")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr
            in {
                "run",
                "Popen",
                "system",
                "popen",
            }
        ):
            raise GoalScriptLoadError(f"process execution is forbidden in GoalScript resource: {resource}")
