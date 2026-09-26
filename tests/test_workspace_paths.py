from pathlib import Path

import pytest
from pydantic import ValidationError

from heagent.engine.container import EngineContainer
from heagent.context.session import SessionStore
from heagent.memory.facts import FactStore
from heagent.memory.profile import ProfileStore
from heagent.memory.skill_store import SkillStore
from heagent.tools.path_safety import build_internal_state_dirs
from heagent.workspace import WorkspacePaths


def test_root_is_the_only_path_input(tmp_path: Path) -> None:
    paths = WorkspacePaths(root=tmp_path)
    assert paths.sessions == tmp_path / ".heagent" / "sessions"
    with pytest.raises(ValidationError):
        WorkspacePaths(root=tmp_path, sessions=tmp_path / "outside")


def test_default_engine_keeps_legacy_relative_stores() -> None:
    engine = EngineContainer.default(sandbox_backend="passthrough")
    assert engine.run_store._base == Path(".heagent/runs")
    assert engine.ledger._base == Path(".heagent/ledger")


def test_handler_keeps_injected_workspace_after_chdir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from heagent.cli.http_console import HttpAgentHandler
    from heagent.config import Settings
    from tests.test_agent_loop import StubProvider

    root = tmp_path / "project"
    engine = EngineContainer.default(workspace_root=str(root), sandbox_backend="passthrough")
    handler = HttpAgentHandler(StubProvider([]), Settings(_env_file=None), engine=engine)
    monkeypatch.chdir(tmp_path)
    loop = handler.new_loop()
    assert loop.context_dir == str(root)
    assert handler.skills._base == root / ".heagent" / "skills"


def test_network_handler_uses_explicit_settings(tmp_path: Path) -> None:
    from heagent.cli.http_console import HttpAgentHandler
    from heagent.config import Settings
    from tests.test_agent_loop import StubProvider

    settings = Settings(_env_file=None, cron_enabled=False, context_strategy="reset")
    handler = HttpAgentHandler(StubProvider([]), settings)
    loop = handler.new_loop()
    assert handler.engine.runtime_config is not None
    assert handler.engine.runtime_config.cron_enabled is False
    assert loop.window_reset is not None
    assert loop.compressor is None


def test_workspace_paths_derive_all_state_from_root(tmp_path: Path) -> None:
    paths = WorkspacePaths.from_root(tmp_path)
    assert paths.root == tmp_path.resolve()
    assert paths.runs == tmp_path / ".heagent" / "runs"
    assert paths.profile_file == tmp_path / ".heagent" / "user" / "USER.md"
    assert paths.edit_snapshots == tmp_path / ".heagent" / "tmp" / "edit-snapshots"
    assert len(build_internal_state_dirs(tmp_path)) == 12


def test_engine_default_binds_run_and_ledger_to_workspace(tmp_path: Path) -> None:
    engine = EngineContainer.default(workspace_root=str(tmp_path), sandbox_backend="passthrough")
    assert engine.run_store._base == tmp_path / ".heagent" / "runs"
    assert engine.ledger._base == tmp_path / ".heagent" / "ledger"
    assert engine.policy.workspace_root == str(tmp_path)


def test_workspace_stores_are_isolated(tmp_path: Path) -> None:
    first = WorkspacePaths.from_root(tmp_path / "one")
    second = WorkspacePaths.from_root(tmp_path / "two")
    SkillStore(str(first.skills)).save("alpha", "Alpha", "pattern", ["step"])
    FactStore(str(first.memory_file)).add("fact-one")
    ProfileStore(str(first.profile_file)).save("profile-one")
    SessionStore(str(first.sessions)).save("session-one", [])
    assert SkillStore(str(second.skills)).load("alpha") is None
    assert not second.memory_file.exists()
    assert not second.profile_file.exists()
    assert not (second.sessions / "session-one.json").exists()


@pytest.mark.parametrize(
    "subdir", ["user", "cron", "checkpoints", "tmp/edit-snapshots", "sandboxes", "console", "backups"]
)
async def test_runtime_state_reads_are_denied(tmp_path: Path, subdir: str) -> None:
    from heagent.tools.path_safety import bind_workspace_root, check_read_denied

    root = tmp_path / "project"
    with bind_workspace_root(root):
        assert check_read_denied(str(root / ".heagent" / subdir / "private.txt")) is not None
        assert check_read_denied(str(root / "notes.txt")) is None


async def test_two_workspace_runs_keep_state_and_fences_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from heagent.cli.http_console import HttpAgentHandler
    from heagent.config import Settings
    from heagent.engine.policy import ToolExecutionMode
    from heagent.tools.path_safety import resolve_workspace_path, workspace_root
    from heagent.tools.edits import snapshot_root
    from heagent.types import ToolCall
    from tests.test_engine_p0 import StubProvider, _final

    handlers = []
    for name in ("one", "two"):
        root = tmp_path / name
        root.mkdir()
        engine = EngineContainer.default(workspace_root=str(root), sandbox_backend="passthrough")
        handlers.append(HttpAgentHandler(StubProvider([_final(name)]), Settings(_env_file=None), engine=engine))
    monkeypatch.chdir(tmp_path)
    for index, handler in enumerate(handlers):
        loop = handler.new_loop()
        root = Path(handler.engine.workspace_root)
        assert loop.context_dir == str(root)
        context = handler.engine.create_run_context()
        with loop._runtime_scope(context):
            assert workspace_root() == root
            assert resolve_workspace_path("notes.txt") == root / "notes.txt"
            assert snapshot_root() == root / ".heagent/tmp/edit-snapshots" / context.run_id
            verdict = handler.engine.policy.evaluate_tool_call(
                ToolCall(id="r", name="file_read", arguments={"path": str(root / "notes.txt")})
            )
            assert verdict.mode is ToolExecutionMode.DIRECT
            other_root = Path(handlers[1 - index].engine.workspace_root)
            blocked = handler.engine.policy.evaluate_tool_call(
                ToolCall(id="x", name="file_read", arguments={"path": str(other_root / "notes.txt")})
            )
            assert blocked.mode is not ToolExecutionMode.DIRECT
        await loop.run("hello")
        run_id = loop.last_run_context.run_id
        assert await handler.engine.run_store.load(run_id) is not None
        assert await handlers[1 - index].engine.run_store.load(run_id) is None


@pytest.mark.asyncio
async def test_file_tool_denies_relative_internal_state_after_workspace_binding(tmp_path: Path) -> None:
    from heagent.tools.builtins.file import file_read
    from heagent.tools.path_safety import bind_workspace_root

    root = tmp_path / "project"
    target = root / ".heagent" / "console" / "private.txt"
    target.parent.mkdir(parents=True)
    target.write_text("secret", encoding="utf-8")
    with bind_workspace_root(root):
        result = await file_read(".heagent/console/private.txt")
    assert "internal HeAgent state" in result
