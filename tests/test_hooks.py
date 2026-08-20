"""Tests for user-configurable hooks (Epic 32)."""

from __future__ import annotations

import json
import os
import shutil
import sys
import time
import uuid
from pathlib import Path

import pytest

from heagent.agent.loop import AgentLoop
from heagent.config import reset_settings
from heagent.engine import EngineContainer, HookConfig, HookManager
from heagent.providers.base import ProviderMetadata
from heagent.tools.registry import ToolRegistry
from heagent.types import Message, ProviderResponse, TokenUsage, ToolCall, ToolSchema


class StubProvider:
    def __init__(self, responses: list[ProviderResponse]) -> None:
        self._responses = list(responses)
        self._idx = 0

    async def send(self, messages: list[Message], *, tools=None) -> ProviderResponse:
        if self._idx < len(self._responses):
            response = self._responses[self._idx]
            self._idx += 1
            return response
        return ProviderResponse(
            content="done",
            usage=TokenUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
            model="stub",
            finish_reason="stop",
        )

    async def stream(self, messages: list[Message], *, tools=None):
        yield await self.send(messages, tools=tools)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


def _usage() -> TokenUsage:
    return TokenUsage(prompt_tokens=3, completion_tokens=2, total_tokens=5)


def _touch_cmd(path: Path) -> str:
    """生成跨平台「写标记文件」hook 命令（供 hook 触发的副作用断言）。"""
    return f'"{sys.executable}" -c "open(r\'{path}\', \'w\').write(\'ok\')"'


def _tool_response(tool_name: str, args: dict[str, object]) -> ProviderResponse:
    return ProviderResponse(
        content="",
        tool_calls=[ToolCall(id="tc1", name=tool_name, arguments=args)],
        usage=_usage(),
        model="stub",
        finish_reason="tool_calls",
    )


def _final(text: str) -> ProviderResponse:
    return ProviderResponse(content=text, usage=_usage(), model="stub", finish_reason="stop")


@pytest.fixture()
def workspace_dir() -> Path:
    base = Path.cwd() / ".test-workdirs"
    path = base / f"hooks-{uuid.uuid4().hex[:8]}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


class TestHookLoad:
    def test_load_parses(self, tmp_path) -> None:
        p = tmp_path / "hooks.json"
        p.write_text(
            json.dumps({"hooks": [{"event": "PreToolUse", "command": "echo hi", "matcher": "shell", "block": True}]}),
            encoding="utf-8",
        )
        mgr = HookManager.load(str(p))
        assert len(mgr._hooks) == 1
        assert mgr._hooks[0].matcher == "shell"
        assert mgr._hooks[0].block is True

    def test_load_nonexistent(self, tmp_path) -> None:
        assert HookManager.load(str(tmp_path / "nope.json"))._hooks == []

    def test_load_invalid_json(self, tmp_path) -> None:
        p = tmp_path / "hooks.json"
        p.write_text("not json", encoding="utf-8")
        assert HookManager.load(str(p))._hooks == []

    def test_load_skips_invalid_entry(self, tmp_path) -> None:
        p = tmp_path / "hooks.json"
        p.write_text(
            json.dumps(
                {
                    "hooks": [
                        {"event": "PreToolUse"},  # 缺 command，应跳过
                        {"event": "PreToolUse", "command": "echo hi"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        assert len(HookManager.load(str(p))._hooks) == 1

    def test_load_rejects_unknown_event(self, tmp_path) -> None:
        """拼错事件名（Literal 校验失败）→ 加载期跳过，而非静默注册永不触发的 hook。"""
        p = tmp_path / "hooks.json"
        p.write_text(
            json.dumps({"hooks": [{"event": "PostToolUs", "command": "echo hi"}]}),
            encoding="utf-8",
        )
        assert HookManager.load(str(p))._hooks == []

    def test_load_warns_matcher_on_session_event(self, tmp_path, caplog) -> None:
        """session 事件配 matcher（恒不生效）→ 保留加载但告警，防静默错配置。"""
        p = tmp_path / "hooks.json"
        p.write_text(
            json.dumps({"hooks": [{"event": "SessionStart", "command": "echo hi", "matcher": "shell"}]}),
            encoding="utf-8",
        )
        with caplog.at_level("WARNING"):
            mgr = HookManager.load(str(p))
        assert len(mgr._hooks) == 1  # matcher 无害，保留
        assert any("matcher" in r.message for r in caplog.records)


class TestPreToolHook:
    @pytest.mark.asyncio
    async def test_block_on_nonzero(self) -> None:
        hooks = [HookConfig(event="PreToolUse", command="exit 1", matcher="shell", block=True)]
        result = await HookManager(hooks).run_pre_tool(ToolCall(id="1", name="shell", arguments={}))
        assert result.blocked is True

    @pytest.mark.asyncio
    async def test_allow_on_zero(self) -> None:
        hooks = [HookConfig(event="PreToolUse", command="exit 0", matcher="shell", block=True)]
        result = await HookManager(hooks).run_pre_tool(ToolCall(id="1", name="shell", arguments={}))
        assert result.blocked is False

    @pytest.mark.asyncio
    async def test_non_block_hook_never_blocks(self) -> None:
        hooks = [HookConfig(event="PreToolUse", command="exit 1", matcher="shell", block=False)]
        result = await HookManager(hooks).run_pre_tool(ToolCall(id="1", name="shell", arguments={}))
        assert result.blocked is False

    @pytest.mark.asyncio
    async def test_matcher_filters(self) -> None:
        hooks = [HookConfig(event="PreToolUse", command="exit 1", matcher="shell", block=True)]
        result = await HookManager(hooks).run_pre_tool(ToolCall(id="1", name="file_read", arguments={}))
        assert result.blocked is False

    @pytest.mark.asyncio
    async def test_stdout_becomes_feedback(self) -> None:
        """block hook 的 stdout 应作为反馈进入 HookResult（而非仅退出码）。"""
        hooks = [HookConfig(event="PreToolUse", command="echo why-not && exit 1", matcher="shell", block=True)]
        result = await HookManager(hooks).run_pre_tool(ToolCall(id="1", name="shell", arguments={}))
        assert result.blocked is True
        assert "why-not" in result.feedback

    @pytest.mark.asyncio
    async def test_command_not_found_blocks_fail_safe(self) -> None:
        """hook 命令崩溃（如命令不存在，shell 返回非 0）时 fail-safe 阻断，不静默放行。"""
        hooks = [HookConfig(event="PreToolUse", command="no-such-cmd-xyz-qq", matcher="shell", block=True)]
        result = await HookManager(hooks).run_pre_tool(ToolCall(id="1", name="shell", arguments={}))
        assert result.blocked is True
        assert result.feedback != ""


class TestHookTimeout:
    @pytest.mark.asyncio
    async def test_timeout_blocks_and_returns_promptly(self) -> None:
        """挂死 hook 超时后 fail-safe 阻断；kill+wait 回收使 _run 及时返回（不等满 sleep）。"""
        sleep_cmd = f'"{sys.executable}" -c "import time; time.sleep(10)"'
        hooks = [HookConfig(event="PreToolUse", command=sleep_cmd, block=True)]
        mgr = HookManager(hooks, timeout=0.5)
        start = time.monotonic()
        result = await mgr.run_pre_tool(ToolCall(id="1", name="shell", arguments={}))
        elapsed = time.monotonic() - start
        assert result.blocked is True
        assert "timed out" in result.feedback
        assert elapsed < 5, f"timeout path took {elapsed:.1f}s; child likely not killed/reaped"

    @pytest.mark.skipif(sys.platform == "win32", reason="pid 探活依赖 POSIX 信号 0")
    @pytest.mark.asyncio
    async def test_timeout_kills_child_process(self, tmp_path) -> None:
        """超时后子进程须被 kill（pid 探活：进程已死才抛 ProcessLookupError）。"""
        pid_file = tmp_path / "hook.pid"
        hooks = [
            HookConfig(event="PreToolUse", command=f"echo $$ > {pid_file}; sleep 10", block=True)
        ]
        mgr = HookManager(hooks, timeout=0.5)
        result = await mgr.run_pre_tool(ToolCall(id="1", name="shell", arguments={}))
        assert result.blocked is True
        pid = int(pid_file.read_text().strip())
        with pytest.raises(ProcessLookupError):
            os.kill(pid, 0)  # 进程已被 kill → 探活必失败


class TestHookEnvWhitelist:
    @pytest.mark.asyncio
    async def test_sensitive_env_stripped(self, monkeypatch) -> None:
        """hook 子进程不继承白名单外的环境变量（防 API key 等外传）。"""
        monkeypatch.setenv("SECRET_MARKER_FOR_HOOK_TEST", "leak-me")
        probe = "import os;print(os.environ.get('SECRET_MARKER_FOR_HOOK_TEST','EMPTY'))"
        hooks = [
            HookConfig(
                event="PreToolUse",
                command=f'"{sys.executable}" -c "{probe}" && exit 1',
                block=True,
            )
        ]
        result = await HookManager(hooks).run_pre_tool(ToolCall(id="1", name="shell", arguments={}))
        assert "leak-me" not in result.feedback
        assert "EMPTY" in result.feedback

    @pytest.mark.asyncio
    async def test_event_env_injected(self, monkeypatch) -> None:
        """HEAGENT_EVENT / HEAGENT_TOOL_NAME 照常注入供 hook 读取。"""
        monkeypatch.delenv("HEAGENT_EVENT", raising=False)
        probe = "import os;print(os.environ.get('HEAGENT_EVENT','NONE'), os.environ.get('HEAGENT_TOOL_NAME','NONE'))"
        hooks = [
            HookConfig(
                event="PreToolUse",
                command=f'"{sys.executable}" -c "{probe}" && exit 1',
                block=True,
            )
        ]
        result = await HookManager(hooks).run_pre_tool(ToolCall(id="1", name="shell", arguments={}))
        assert "PreToolUse" in result.feedback
        assert "shell" in result.feedback


class TestHookIntegration:
    @pytest.mark.asyncio
    async def test_pre_tool_hook_blocks_in_loop(self, workspace_dir: Path) -> None:
        registry = ToolRegistry()
        calls: list[str] = []
        registry.register(
            ToolSchema(name="shell", description="shell", parameters={"type": "object", "properties": {}}),
            lambda command="": calls.append(command) or "ran",
        )
        engine = EngineContainer.default(workspace_root=str(workspace_dir))
        engine.run_store = engine.run_store.__class__(base_dir=str(workspace_dir / "runs"))
        engine.hooks = HookManager([HookConfig(event="PreToolUse", command="exit 1", matcher="shell", block=True)])
        provider = StubProvider([_tool_response("shell", {"command": "dir"}), _final("done")])
        loop = AgentLoop(provider, registry=registry, engine=engine, context_dir=str(workspace_dir))

        result = await loop.run("run shell")

        assert result == "done"
        assert calls == []  # 被 hook 阻断，handler 未执行
        snapshot = await engine.run_store.load(loop.last_run_context.run_id)
        assert snapshot is not None
        assert snapshot.results[0].is_error is True
        assert "blocked by hook" in snapshot.results[0].content

    @pytest.mark.asyncio
    async def test_non_block_hook_does_not_block(self, workspace_dir: Path) -> None:
        registry = ToolRegistry()
        calls: list[str] = []
        registry.register(
            ToolSchema(name="shell", description="shell", parameters={"type": "object", "properties": {}}),
            lambda command="": calls.append(command) or "ran",
        )
        engine = EngineContainer.default(workspace_root=str(workspace_dir))
        engine.run_store = engine.run_store.__class__(base_dir=str(workspace_dir / "runs"))
        engine.hooks = HookManager([HookConfig(event="PreToolUse", command="exit 0", matcher="shell", block=True)])
        provider = StubProvider([_tool_response("shell", {"command": "dir"}), _final("done")])
        loop = AgentLoop(provider, registry=registry, engine=engine, context_dir=str(workspace_dir))

        result = await loop.run("run shell")

        assert result == "done"
        assert calls == ["dir"]  # hook 放行，handler 正常执行

    @pytest.mark.asyncio
    async def test_post_tool_hook_runs_after_handler(self, workspace_dir: Path) -> None:
        """PostToolUse hook 在工具执行后触发（副作用文件验证）。"""
        marker = workspace_dir / "post.txt"
        registry = ToolRegistry()
        registry.register(
            ToolSchema(name="shell", description="shell", parameters={"type": "object", "properties": {}}),
            lambda command="": "ran",
        )
        engine = EngineContainer.default(workspace_root=str(workspace_dir))
        engine.run_store = engine.run_store.__class__(base_dir=str(workspace_dir / "runs"))
        engine.hooks = HookManager([HookConfig(event="PostToolUse", command=_touch_cmd(marker))])
        provider = StubProvider([_tool_response("shell", {"command": "dir"}), _final("done")])
        loop = AgentLoop(provider, registry=registry, engine=engine, context_dir=str(workspace_dir))

        await loop.run("run shell")

        assert marker.read_text() == "ok"

    @pytest.mark.asyncio
    async def test_session_hooks_fire_on_run(self, workspace_dir: Path) -> None:
        """SessionStart / SessionEnd 在 run 生命周期首尾各触发一次。"""
        start_marker = workspace_dir / "start.txt"
        end_marker = workspace_dir / "end.txt"
        engine = EngineContainer.default(workspace_root=str(workspace_dir))
        engine.run_store = engine.run_store.__class__(base_dir=str(workspace_dir / "runs"))
        engine.hooks = HookManager(
            [
                HookConfig(event="SessionStart", command=_touch_cmd(start_marker)),
                HookConfig(event="SessionEnd", command=_touch_cmd(end_marker)),
            ]
        )
        provider = StubProvider([_final("done")])
        loop = AgentLoop(provider, engine=engine, context_dir=str(workspace_dir))

        await loop.run("hi")

        assert start_marker.read_text() == "ok"
        assert end_marker.read_text() == "ok"


class TestHooksEnabledSwitch:
    """H2：hooks.json 默认不加载（防不可信仓库投放自动执行），须 HOOKS_ENABLED 显式开启。"""

    @pytest.fixture(autouse=True)
    def _reset(self):
        reset_settings()
        yield
        reset_settings()

    def _write_hooks(self, workspace_dir: Path) -> Path:
        hooks_dir = workspace_dir / ".heagent"
        hooks_dir.mkdir(parents=True, exist_ok=True)
        path = hooks_dir / "hooks.json"
        path.write_text(
            json.dumps({"hooks": [{"event": "PreToolUse", "command": "echo hi", "block": True}]}),
            encoding="utf-8",
        )
        return path

    def test_disabled_by_default_ignores_file(self, workspace_dir: Path, monkeypatch, caplog) -> None:
        """HOOKS_ENABLED 缺省 false：hooks.json 存在也不加载，且告警（不静默失效）。"""
        monkeypatch.delenv("HOOKS_ENABLED", raising=False)
        self._write_hooks(workspace_dir)
        with caplog.at_level("WARNING"):
            engine = EngineContainer.default(workspace_root=str(workspace_dir))
        assert engine.hooks is None
        assert any("HOOKS_ENABLED" in r.message for r in caplog.records)

    def test_enabled_loads_file(self, workspace_dir: Path, monkeypatch) -> None:
        """HOOKS_ENABLED=true：从 workspace_root/.heagent/hooks.json 加载。"""
        monkeypatch.setenv("HOOKS_ENABLED", "true")
        self._write_hooks(workspace_dir)
        engine = EngineContainer.default(workspace_root=str(workspace_dir))
        assert engine.hooks is not None
        assert len(engine.hooks._hooks) == 1

    def test_enabled_without_file_is_noop(self, workspace_dir: Path, monkeypatch) -> None:
        """开启但无 hooks.json：不报错、加载为空（无 hook 可触发）。"""
        monkeypatch.setenv("HOOKS_ENABLED", "true")
        engine = EngineContainer.default(workspace_root=str(workspace_dir))
        assert engine.hooks is None or engine.hooks._hooks == []
