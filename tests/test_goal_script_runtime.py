from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from heagent.goal.script_api import ScriptResponse
from heagent.goal.script_loader import SCRIPT_ENTRYPOINT, GoalScriptLoadError, load_script
from heagent.goal.script_runtime import GoalScriptRuntimeError, ScriptRuntime
from heagent.memory.skill_packages import SkillPackage

ENTRY = SCRIPT_ENTRYPOINT


def _package(tmp_path: Path, source: str, *, name: str = "script.py") -> SkillPackage:
    root = tmp_path / "he-script"
    root.mkdir()
    (root / "SKILL.md").write_text("---\ncanonical_id: he-script\n---\n", encoding="utf-8")
    scripts = root / "scripts"
    scripts.mkdir()
    (scripts / name).write_text(source, encoding="utf-8")
    return SkillPackage(skill_id="he-script", root=root)


@pytest.mark.asyncio
async def test_runtime_exposes_only_typed_facade_operations(tmp_path: Path) -> None:
    package = _package(
        tmp_path,
        f"async def {ENTRY}(goal):\n"
        "    value = await goal.input('answer', 'fallback')\n"
        "    await goal.step('plan', value=value)\n"
        "    return value\n",
    )
    seen = []

    async def request(item):
        seen.append(item)
        return ScriptResponse(value=item.value)

    result = await ScriptRuntime().run(package, "script.py", inputs={}, request=request)
    assert result.value == "fallback"
    assert [item.operation for item in seen] == ["input", "step"]
    assert all(item.__class__.__name__ == "ScriptRequest" for item in result.requests)


def test_runtime_rejects_forbidden_capabilities(tmp_path: Path) -> None:
    package = _package(tmp_path, f"import subprocess\nasync def {ENTRY}(goal):\n    return 1\n")
    with pytest.raises(GoalScriptLoadError, match="forbidden import"):
        load_script(package, "script.py")


@pytest.mark.asyncio
async def test_runtime_enforces_request_limit(tmp_path: Path) -> None:
    package = _package(
        tmp_path,
        f"async def {ENTRY}(goal):\n    await goal.step('one')\n    await goal.step('two')\n",
    )

    async def request(item):
        return ScriptResponse()

    with pytest.raises(RuntimeError, match="request limit"):
        await ScriptRuntime(max_requests=1).run(package, "script.py", request=request)


@pytest.mark.asyncio
async def test_runtime_timeout_is_bounded(tmp_path: Path) -> None:
    package = _package(tmp_path, f"async def {ENTRY}(goal):\n    await goal.step('slow')\n")

    async def slow_request(item):
        await asyncio.sleep(10)
        return ScriptResponse()

    with pytest.raises(asyncio.TimeoutError):
        await ScriptRuntime(timeout_seconds=0.001).run(package, "script.py", request=slow_request)


def test_runtime_rejects_non_async_entrypoint(tmp_path: Path) -> None:
    package = _package(tmp_path, f"def {ENTRY}(goal):\n    return 1\n")

    async def request(item):
        return ScriptResponse()

    with pytest.raises(GoalScriptRuntimeError, match="must be async"):
        asyncio.run(ScriptRuntime().run(package, "script.py", request=request))


def test_missing_entrypoint_is_rejected(tmp_path: Path) -> None:
    package = _package(tmp_path, "PLACEHOLDER = 1\n")

    async def request(item):
        return ScriptResponse()

    with pytest.raises(GoalScriptRuntimeError, match="must define callable"):
        asyncio.run(ScriptRuntime().run(package, "script.py", request=request))


def test_private_facade_access_is_rejected(tmp_path: Path) -> None:
    package = _package(tmp_path, f"async def {ENTRY}(goal):\n    return goal._inputs\n")
    with pytest.raises(GoalScriptLoadError, match="private attribute"):
        load_script(package, "script.py")


def test_unbounded_while_loop_is_rejected(tmp_path: Path) -> None:
    package = _package(tmp_path, f"async def {ENTRY}(goal):\n    while True:\n        pass\n")
    with pytest.raises(GoalScriptLoadError, match="while loops"):
        load_script(package, "script.py")


def test_nested_helper_function_is_rejected(tmp_path: Path) -> None:
    package = _package(tmp_path, f"def helper():\n    return 1\n\nasync def {ENTRY}(goal):\n    return helper()\n")
    with pytest.raises(GoalScriptLoadError, match="only build_workflow"):
        load_script(package, "script.py")


@pytest.mark.parametrize(
    "body",
    ["return open('x')", "return eval('1')", "return __import__('os')", "return vars()"],
)
def test_file_and_eval_builtins_are_rejected(tmp_path: Path, body: str) -> None:
    package = _package(tmp_path, f"async def {ENTRY}(goal):\n    {body}\n")
    with pytest.raises(GoalScriptLoadError, match="forbidden capability"):
        load_script(package, "script.py")


def test_benign_script_loads(tmp_path: Path) -> None:
    package = _package(
        tmp_path,
        f"async def {ENTRY}(goal):\n    for name in ['a', 'b']:\n        await goal.step(name)\n    return 'done'\n",
    )
    resource = load_script(package, "script.py")
    assert resource.name == "script.py"
