"""Tests for /goal command family (Story 41.1：skill 直读 + goal 目录/指针 + 单步工作流)。

机制层契约：skill 正文从 ``.heagent/skills/goal/SKILL.md`` 路径直读注入；每步一个
全新 SubAgent 会话（独立 run 记录）；机器只扫 GOAL.md 的 status 行 / checkbox /
in-progress 标记；goal 目录与 current 指针经 ``atomic_write_text`` 落盘。
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from heagent.agent.loop import AgentLoop
from heagent.cli import (
    _build_slash_registry,
    _goal_auto_goal_id,
    _goal_cron_advance,
    _goal_runner,
    _handle_slash,
    _scan_goal_md,
)
from heagent.config import get_settings, reset_settings
from heagent.context.window_reset import WindowResetConfig
from heagent.cron.jobs import JobStore
from heagent.providers.base import ProviderMetadata
from heagent.types import Message, ProviderResponse, Role, TokenUsage, ToolCall

SKILL_TEXT = "---\nname: goal\ndescription: 测试契约\n---\n\n# goal\n\n## 规程\n契约正文标记（planning / story）。\n"

PLANNING_FINAL = "拆分理由：两条 story。"


def _usage() -> TokenUsage:
    return TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)


def _final(content: str) -> ProviderResponse:
    return ProviderResponse(content=content, usage=_usage(), model="stub", finish_reason="stop")


def _tc(call_id: str, name: str, args: dict[str, object] | None = None) -> ToolCall:
    return ToolCall(id=call_id, name=name, arguments=args or {})


def _tool_resp(calls: list[ToolCall], content: str = "") -> ProviderResponse:
    return ProviderResponse(content=content, tool_calls=calls, usage=_usage(), model="stub", finish_reason="tool_calls")


def _goal_md_text(*, status: str = "executing", total: int = 2, done: int = 0) -> str:
    """构造一份合规 GOAL.md（status 首行 + N 条 story checkbox）。"""
    stories = "\n".join(
        f"- [{'x' if i <= done else ' '}] S{i}: story {i}\n  - 验收: 标准 {i}" for i in range(1, total + 1)
    )
    return f"status: {status}\n\n# 测试目标\n\n## Stories\n\n{stories}\n"


def _check_first_story(text: str) -> str:
    """把最早一条未勾选 story 勾上（模拟 story 会话对 GOAL.md 的写回）。"""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("- [ ]"):
            lines[i] = ln.replace("- [ ]", "- [x]", 1)
            break
    return "\n".join(lines) + "\n"


def _user_prompt(messages: list[Message]) -> str:
    for m in messages:
        if m.role == Role.USER:
            return m.content
    raise AssertionError("provider 收到的消息里没有 USER 消息")


def _path_from_prompt(prompt: str) -> str:
    for line in prompt.splitlines():
        if line.startswith("GOAL.md 路径："):
            return line.split("：", 1)[1].strip()
    raise AssertionError("prompt 缺少 GOAL.md 路径行")


def _goal_block(prompt: str) -> str:
    """取 story prompt 中「GOAL.md 路径：」行之后的 GOAL.md 全文（skill 正文无该标记行）。"""
    lines = prompt.splitlines()
    idx = next(i for i, ln in enumerate(lines) if ln.startswith("GOAL.md 路径："))
    return "\n".join(lines[idx + 1 :]).lstrip("\n")


class StubProvider:
    """按预配置序列返回响应的内存 provider（不写任何文件）。"""

    def __init__(self, responses: list[ProviderResponse]) -> None:
        self._responses = list(responses)
        self._idx = 0
        self.calls: list[list[Message]] = []

    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        self.calls.append([m.model_copy(deep=True) for m in messages])
        if self._idx < len(self._responses):
            resp = self._responses[self._idx]
            self._idx += 1
            return resp
        return _final("no more responses")

    async def stream(self, messages: list[Message], *, tools: list[object] | None = None) -> object:
        yield await self.send(messages, tools=tools)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


class ScriptedGoalProvider:
    """模拟遵循 goal skill 契约的会话 LLM。

    从 prompt 的「GOAL.md 路径：」行取目标文件：planning 会话 ``file_write`` 写
    planning_md；story 会话把 prompt 注入的 GOAL.md 全文勾上最早一条 story 写回；
    写完后的下一轮给最终答复（模拟收口）。
    """

    def __init__(self, planning_md: str | None = None, final: str = PLANNING_FINAL) -> None:
        self._planning_md = planning_md if planning_md is not None else _goal_md_text()
        self._final_text = final
        self._wrote = False
        self.calls: list[list[Message]] = []

    async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
        self.calls.append([m.model_copy(deep=True) for m in messages])
        if self._wrote:
            return _final(self._final_text)
        self._wrote = True
        prompt = _user_prompt(messages)
        path = _path_from_prompt(prompt)
        content = self._planning_md
        if "执行 story 规程" in prompt:
            content = _check_first_story(_goal_block(prompt))
        return _tool_resp([_tc("w1", "file_write", {"path": path, "content": content})])

    async def stream(self, messages: list[Message], *, tools: list[object] | None = None) -> object:
        yield await self.send(messages, tools=tools)

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


def _seed_goal(cwd: Path, *, status: str = "executing", total: int = 2, done: int = 0) -> Path:
    """预置活跃 goal（目录 + goal.txt + GOAL.md + current 指针），返回 GOAL.md 路径。"""
    goal_id = "deadbeef"
    goal_dir = cwd / ".heagent" / "goals" / goal_id
    goal_dir.mkdir(parents=True, exist_ok=True)
    (goal_dir / "goal.txt").write_text("预置目标", encoding="utf-8")
    md = goal_dir / "GOAL.md"
    md.write_text(_goal_md_text(status=status, total=total, done=done), encoding="utf-8")
    (cwd / ".heagent" / "goals" / "current").write_text(goal_id, encoding="utf-8")
    return md


def _current_goal_id(cwd: Path) -> str:
    return (cwd / ".heagent" / "goals" / "current").read_text(encoding="utf-8").strip()


@pytest.fixture(autouse=True)
def _reset_settings() -> Iterator[None]:
    reset_settings()
    yield
    reset_settings()


@pytest.fixture()
def goal_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """切到 tmp cwd 并预置 ``.heagent/skills/goal/SKILL.md``（skill 直读命中）。"""
    monkeypatch.chdir(tmp_path)
    skill = tmp_path / ".heagent" / "skills" / "goal" / "SKILL.md"
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(SKILL_TEXT, encoding="utf-8")
    return tmp_path


class TestScanGoalMd:
    def test_valid_counts(self) -> None:
        prog = _scan_goal_md("status: executing\n\n- [ ] S1: a\n- [x] S2: b\n")
        assert (prog.status, prog.total, prog.done, prog.in_progress) == ("executing", 2, 1, None)

    def test_leading_blank_lines_tolerated(self) -> None:
        assert _scan_goal_md("\n\nstatus: blocked\n- [ ] S1: a\n").status == "blocked"

    def test_invalid_status_value(self) -> None:
        assert _scan_goal_md("status: weird\n- [ ] S1: a\n").status is None

    def test_status_not_first_nonempty_line(self) -> None:
        assert _scan_goal_md("# 标题\nstatus: executing\n- [ ] S1: a\n").status is None

    def test_uppercase_x_counts_as_done(self) -> None:
        prog = _scan_goal_md("status: executing\n- [X] S1: a\n- [ ] S2: b\n")
        assert (prog.total, prog.done) == (2, 1)

    def test_nested_checkboxes_are_not_stories(self) -> None:
        prog = _scan_goal_md(
            "status: executing\n\n- [ ] S1: a\n  - [ ] acceptance check\n- [x] S2: b\n  - [x] note check\n"
        )
        assert (prog.total, prog.done) == (2, 1)

    def test_in_progress_marker_parsed(self) -> None:
        text = "status: executing\n\n- [ ] S1: a\n\n> in-progress: S1\n"
        assert _scan_goal_md(text).in_progress == "1"

    def test_in_progress_malformed_or_absent_is_none(self) -> None:
        assert _scan_goal_md("status: executing\n- [ ] S1: a\n> in-progress: S9x\n").in_progress is None
        assert _scan_goal_md("status: executing\n- [ ] S1: a\n").in_progress is None


class TestGoalSkillMissing:
    @pytest.mark.asyncio
    async def test_any_subcommand_errors_with_creation_guidance(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        monkeypatch.chdir(tmp_path)  # 无 SKILL.md
        provider = ScriptedGoalProvider()
        await _goal_runner(provider, None, "把测试改绿")
        err = capsys.readouterr().err
        assert ".heagent/skills/goal/SKILL.md" in err  # 创建指引含路径
        assert "name: goal" in err  # 含 frontmatter 最小示例
        assert provider.calls == []  # 不开会话


class TestGoalNew:
    @pytest.mark.asyncio
    async def test_missing_description_prints_usage(self, goal_cwd: Path, capsys: pytest.CaptureFixture[str]) -> None:
        provider = ScriptedGoalProvider()
        await _goal_runner(provider, None, "new")
        assert "/goal new <目标描述>" in capsys.readouterr().err
        assert provider.calls == []
        assert not (goal_cwd / ".heagent" / "goals").exists()  # 未建 goal 目录

    @pytest.mark.asyncio
    async def test_planning_success_creates_goal_and_injects_skill(
        self, goal_cwd: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        provider = ScriptedGoalProvider()
        await _goal_runner(provider, None, "把测试改绿")
        goals = goal_cwd / ".heagent" / "goals"
        goal_id = _current_goal_id(goal_cwd)
        assert len(goal_id) == 8 and all(c in "0123456789abcdef" for c in goal_id)
        assert (goals / goal_id / "goal.txt").read_text(encoding="utf-8") == "把测试改绿"
        md = goals / goal_id / "GOAL.md"
        prog = _scan_goal_md(md.read_text(encoding="utf-8"))
        assert (prog.status, prog.total, prog.done) == ("executing", 2, 0)
        # prompt 为确定性注入：skill 正文 + 任务段 + 目标 + GOAL.md 绝对路径
        user = _user_prompt(provider.calls[0])
        assert user.startswith(SKILL_TEXT)
        assert "# 任务：执行 planning 规程" in user
        assert "目标：把测试改绿" in user
        assert str(md.resolve()) in user
        out = capsys.readouterr()
        assert "0/2" in out.err  # 回显进度
        assert PLANNING_FINAL in out.out  # 会话收口答复

    @pytest.mark.asyncio
    async def test_session_without_goal_md_fails_loudly_dir_kept(
        self, goal_cwd: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        provider = StubProvider([_final("我没写文件")])  # 会话直接收口，不落盘
        await _goal_runner(provider, None, "把测试改绿")
        err = capsys.readouterr().err
        assert "GOAL.md 缺失" in err
        goal_id = _current_goal_id(goal_cwd)
        assert (goal_cwd / ".heagent" / "goals" / goal_id / "goal.txt").exists()  # 目录保留可重试

    @pytest.mark.asyncio
    async def test_planning_session_failure_short_circuits_validation(
        self, goal_cwd: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        class WriteThenBoom(ScriptedGoalProvider):
            async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
                if self._wrote:
                    raise RuntimeError("mid-session crash")
                return await super().send(messages, tools=tools)

        await _goal_runner(WriteThenBoom(), None, "把测试改绿")
        err = capsys.readouterr().err
        assert "会话失败" in err and "mid-session crash" in err
        assert "planning 完成" not in err  # 失败即收口，不出「失败+完成」矛盾结论
        # GOAL.md 确已写出（检视交给 /goal status），本分支不再回显结论
        md = goal_cwd / ".heagent" / "goals" / _current_goal_id(goal_cwd) / "GOAL.md"
        assert _scan_goal_md(md.read_text(encoding="utf-8")).status == "executing"

    @pytest.mark.asyncio
    async def test_invalid_status_line_fails_loudly(self, goal_cwd: Path, capsys: pytest.CaptureFixture[str]) -> None:
        provider = ScriptedGoalProvider(planning_md="# 标题先行\nstatus: executing\n\n- [ ] S1: s\n")
        await _goal_runner(provider, None, "把测试改绿")
        assert "首非空行" in capsys.readouterr().err
        assert (goal_cwd / ".heagent" / "goals" / _current_goal_id(goal_cwd)).is_dir()  # 目录保留

    @pytest.mark.asyncio
    async def test_planning_status_not_executing_fails(
        self, goal_cwd: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        provider = ScriptedGoalProvider(planning_md=_goal_md_text(status="planning", total=1))
        await _goal_runner(provider, None, "把测试改绿")
        assert "不合规" in capsys.readouterr().err

    @pytest.mark.asyncio
    async def test_multiple_news_coexist_pointer_switches(
        self, goal_cwd: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        await _goal_runner(ScriptedGoalProvider(), None, "目标一")
        first = _current_goal_id(goal_cwd)
        await _goal_runner(ScriptedGoalProvider(), None, "目标二")
        second = _current_goal_id(goal_cwd)
        assert first != second  # current 指针切到最新
        assert (goal_cwd / ".heagent" / "goals" / first / "goal.txt").exists()  # 旧目录保留
        assert (goal_cwd / ".heagent" / "goals" / second / "goal.txt").read_text(encoding="utf-8") == "目标二"


class TestGoalDecodeAndWriteGuards:
    """GBK 存档与写侧 OSError 均显性回显——不崩 REPL、不开会话。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("target", ["skill", "current", "goal_md"])
    async def test_gbk_bytes_fail_explicitly(
        self, goal_cwd: Path, capsys: pytest.CaptureFixture[str], target: str
    ) -> None:
        provider = ScriptedGoalProvider()
        if target == "skill":
            (goal_cwd / ".heagent" / "skills" / "goal" / "SKILL.md").write_bytes(b"\xd6\xd0\xce\xc4")
            await _goal_runner(provider, None, "把测试改绿")
        elif target == "current":
            _seed_goal(goal_cwd)
            (goal_cwd / ".heagent" / "goals" / "current").write_bytes(b"\xd6\xd0\xce\xc4")
            await _goal_runner(provider, None, "next")
        else:
            _seed_goal(goal_cwd)
            (goal_cwd / ".heagent" / "goals" / "deadbeef" / "GOAL.md").write_bytes(b"\xd6\xd0\xce\xc4")
            await _goal_runner(provider, None, "next")
        err = capsys.readouterr().err
        assert "[goal]" in err
        if target == "current":
            assert "current 指针读取失败" in err
        assert provider.calls == []  # 不开会话

    @pytest.mark.asyncio
    async def test_atomic_write_failure_echoed(
        self, goal_cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def boom(path: object, text: object, **kw: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr("heagent.cli.atomic_write_text", boom)
        provider = ScriptedGoalProvider()
        await _goal_runner(provider, None, "把测试改绿")
        err = capsys.readouterr().err
        assert "落盘失败" in err and "disk full" in err
        assert not (goal_cwd / ".heagent" / "goals" / "current").exists()
        assert provider.calls == []

    @pytest.mark.asyncio
    async def test_reset_unlink_failure_echoed(
        self, goal_cwd: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_goal(goal_cwd)

        def boom(self: object, missing_ok: bool = False) -> None:  # noqa: ARG001
            raise OSError("permission denied")

        monkeypatch.setattr(Path, "unlink", boom)
        await _goal_runner(ScriptedGoalProvider(), None, "reset")
        assert "落盘失败" in capsys.readouterr().err
        assert (goal_cwd / ".heagent" / "goals" / "current").exists()  # 指针未被清


class TestGoalRecovery:
    """goal.txt 恢复路径：GOAL.md 缺失时用原始描述重跑 planning（复用目录/指针）。"""

    @pytest.mark.asyncio
    async def test_next_recovers_planning_from_goal_txt(
        self, goal_cwd: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        md = _seed_goal(goal_cwd)
        md.unlink()  # GOAL.md 未落盘（planning 白跑）
        provider = ScriptedGoalProvider()
        await _goal_runner(provider, None, "next")
        out = capsys.readouterr()
        assert "重跑 planning" in out.err
        assert "planning 完成：0/2" in out.err
        assert "目标：预置目标" in _user_prompt(provider.calls[0])  # 用 goal.txt 原始描述
        assert _current_goal_id(goal_cwd) == "deadbeef"  # 指针不动
        dirs = [g.name for g in (goal_cwd / ".heagent" / "goals").iterdir() if g.is_dir()]
        assert dirs == ["deadbeef"]  # 不建新目录
        prog = _scan_goal_md(md.read_text(encoding="utf-8"))
        assert (prog.status, prog.total) == ("executing", 2)
        # 恢复后指针可用：再次 /goal next 走正常 story 路径
        await _goal_runner(ScriptedGoalProvider(), None, "next")
        assert _scan_goal_md(md.read_text(encoding="utf-8")).done == 1

    @pytest.mark.asyncio
    async def test_next_without_goal_txt_fails_explicitly(
        self, goal_cwd: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        md = _seed_goal(goal_cwd)
        md.unlink()
        (md.parent / "goal.txt").unlink()
        provider = ScriptedGoalProvider()
        await _goal_runner(provider, None, "next")
        assert "GOAL.md 缺失" in capsys.readouterr().err
        assert provider.calls == []


class TestGoalNext:
    @pytest.mark.asyncio
    async def test_no_active_goal_errors(self, goal_cwd: Path, capsys: pytest.CaptureFixture[str]) -> None:
        provider = ScriptedGoalProvider()
        await _goal_runner(provider, None, "next")
        assert "/goal new" in capsys.readouterr().err
        assert provider.calls == []

    @pytest.mark.asyncio
    async def test_all_done_no_session(self, goal_cwd: Path, capsys: pytest.CaptureFixture[str]) -> None:
        md = _seed_goal(goal_cwd, total=2, done=2, status="done")
        provider = ScriptedGoalProvider()
        await _goal_runner(provider, None, "next")
        assert "已完成" in capsys.readouterr().err
        assert provider.calls == []  # 不开会话
        prog = _scan_goal_md(md.read_text(encoding="utf-8"))
        assert (prog.status, prog.total, prog.done) == ("done", 2, 2)  # GOAL.md 未被改动

    @pytest.mark.asyncio
    async def test_next_runs_story_and_keeps_independent_run_records(
        self, goal_cwd: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        md = _seed_goal(goal_cwd)
        provider = ScriptedGoalProvider()
        await _goal_runner(provider, None, "next")
        # prompt：skill 正文 + 单 story 指令 + GOAL.md 当前全文
        user = _user_prompt(provider.calls[0])
        assert user.startswith(SKILL_TEXT)
        assert "# 任务：执行 story 规程（仅一条）" in user
        assert _goal_md_text() in user
        assert str(md.resolve()) in user
        prog = _scan_goal_md(md.read_text(encoding="utf-8"))
        assert (prog.status, prog.total, prog.done) == ("executing", 2, 1)  # 会话勾选了 S1
        out = capsys.readouterr()
        assert "1/2" in out.err
        assert PLANNING_FINAL in out.out
        runs_after_first = set((goal_cwd / ".heagent" / "runs").glob("*.json"))
        # 第二条 story：全新会话 + 独立 run 记录
        await _goal_runner(ScriptedGoalProvider(), None, "next")
        prog = _scan_goal_md(md.read_text(encoding="utf-8"))
        assert (prog.status, prog.total, prog.done) == ("executing", 2, 2)
        runs_after_second = set((goal_cwd / ".heagent" / "runs").glob("*.json"))
        assert len(runs_after_second - runs_after_first) >= 1

    @pytest.mark.asyncio
    async def test_session_failure_echoed(self, goal_cwd: Path, capsys: pytest.CaptureFixture[str]) -> None:
        class Boom(ScriptedGoalProvider):
            async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
                self.calls.append([m.model_copy(deep=True) for m in messages])
                raise RuntimeError("api down")

        md = _seed_goal(goal_cwd)
        await _goal_runner(Boom(), None, "next")
        out = capsys.readouterr()
        assert "api down" in out.err
        assert "进度：" not in out.err  # 失败即收口，不再回显进度结论
        prog = _scan_goal_md(md.read_text(encoding="utf-8"))
        assert (prog.status, prog.total, prog.done) == ("executing", 2, 0)  # 状态未被破坏

    @pytest.mark.asyncio
    async def test_ctrl_c_during_session_no_traceback(self, goal_cwd: Path, capsys: pytest.CaptureFixture[str]) -> None:
        class Interrupted(ScriptedGoalProvider):
            async def send(self, messages: list[Message], *, tools: list[object] | None = None) -> ProviderResponse:
                raise KeyboardInterrupt

        _seed_goal(goal_cwd)
        await _goal_runner(Interrupted(), None, "next")  # 不应抛出
        assert "/goal next 可续跑" in capsys.readouterr().err


class TestGoalNoProgressDetection:
    """run 白跑可检测：会话零变化 / 全勾未翻 done 均显性回显（纯读侧对比，不写 GOAL.md）。"""

    @pytest.mark.asyncio
    async def test_session_without_progress_warns(self, goal_cwd: Path, capsys: pytest.CaptureFixture[str]) -> None:
        md = _seed_goal(goal_cwd)
        provider = StubProvider([_final("我说做完了但没写文件")])  # 会话不写 GOAL.md
        await _goal_runner(provider, None, "next")
        assert "未推进任何 story" in capsys.readouterr().err
        assert _scan_goal_md(md.read_text(encoding="utf-8")).done == 0

    @pytest.mark.asyncio
    async def test_all_checked_but_status_not_done_warns(
        self, goal_cwd: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        md = _seed_goal(goal_cwd, total=2, done=1)
        await _goal_runner(ScriptedGoalProvider(), None, "next")  # 勾上最后一条，status 仍 executing
        err = capsys.readouterr().err
        assert "status 未翻 done" in err
        prog = _scan_goal_md(md.read_text(encoding="utf-8"))
        assert (prog.done, prog.status) == (2, "executing")


class TestGoalIntegrity:
    """current 指针内容校验与 goal_id 防碰撞。"""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad", ["../../etc", "DEADBEEF", "short", "deadbee"])
    async def test_illegal_pointer_content_rejected(
        self, goal_cwd: Path, capsys: pytest.CaptureFixture[str], bad: str
    ) -> None:
        goals = goal_cwd / ".heagent" / "goals"
        goals.mkdir(parents=True, exist_ok=True)
        (goals / "current").write_text(bad, encoding="utf-8")
        provider = ScriptedGoalProvider()
        await _goal_runner(provider, None, "next")
        err = capsys.readouterr().err
        assert "指针内容非法" in err and bad in err
        assert provider.calls == []

    @pytest.mark.asyncio
    async def test_uuid_collision_does_not_overwrite_existing_goal(
        self, goal_cwd: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        occupied = goal_cwd / ".heagent" / "goals" / "41414141"
        occupied.mkdir(parents=True)
        (occupied / "goal.txt").write_text("旧 goal 哨兵", encoding="utf-8")
        real_uuid4 = uuid.uuid4
        seq = iter(["41414141", "42424242"])

        def fake_uuid4() -> object:
            try:
                return SimpleNamespace(hex=next(seq))
            except StopIteration:
                return real_uuid4()

        monkeypatch.setattr(uuid, "uuid4", fake_uuid4)
        await _goal_runner(ScriptedGoalProvider(), None, "新目标")
        assert _current_goal_id(goal_cwd) == "42424242"  # 撞号后换新号
        assert (occupied / "goal.txt").read_text(encoding="utf-8") == "旧 goal 哨兵"  # 旧 goal 未被覆写


class TestGoalStatus:
    @pytest.mark.asyncio
    async def test_bare_goal_prints_progress_and_full_text(
        self, goal_cwd: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_goal(goal_cwd)
        provider = ScriptedGoalProvider()
        await _goal_runner(provider, None, "")
        out = capsys.readouterr()
        assert "0/2" in out.err
        assert "status: executing" in out.err
        assert "S1: story 1" in out.out  # GOAL.md 全文
        assert provider.calls == []

    @pytest.mark.asyncio
    async def test_explicit_status_subcommand(self, goal_cwd: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _seed_goal(goal_cwd)
        await _goal_runner(ScriptedGoalProvider(), None, "status")
        assert "0/2" in capsys.readouterr().err

    @pytest.mark.asyncio
    async def test_no_active_goal_errors(self, goal_cwd: Path, capsys: pytest.CaptureFixture[str]) -> None:
        await _goal_runner(ScriptedGoalProvider(), None, "status")
        assert "无活跃 goal" in capsys.readouterr().err


class TestGoalReset:
    @pytest.mark.asyncio
    async def test_clears_pointer_keeps_dir(self, goal_cwd: Path, capsys: pytest.CaptureFixture[str]) -> None:
        md = _seed_goal(goal_cwd)
        await _goal_runner(ScriptedGoalProvider(), None, "reset")
        assert not (goal_cwd / ".heagent" / "goals" / "current").exists()
        assert md.exists()  # goal 目录与文件全保留
        assert (md.parent / "goal.txt").exists()
        assert str(goal_cwd / ".heagent" / "goals") in capsys.readouterr().err  # 回显目录路径


class TestGoalAuto:
    @pytest.mark.asyncio
    async def test_rejects_cron_with_wrong_field_count(
        self, goal_cwd: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_goal(goal_cwd)
        store = JobStore(str(goal_cwd / "jobs.json"))
        await _goal_runner(ScriptedGoalProvider(), None, "auto * * *", cron_store=store)
        assert "5 字段" in capsys.readouterr().err
        assert store.list_jobs() == []

    @pytest.mark.asyncio
    async def test_rejects_cron_with_empty_comma_segment(
        self, goal_cwd: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _seed_goal(goal_cwd)
        store = JobStore(str(goal_cwd / "jobs.json"))
        await _goal_runner(ScriptedGoalProvider(), None, "auto 1,,2 * * * *", cron_store=store)
        assert "空的逗号分段" in capsys.readouterr().err
        assert store.list_jobs() == []

    @pytest.mark.asyncio
    async def test_new_goal_removes_previous_auto_job(self, goal_cwd: Path) -> None:
        await _goal_runner(ScriptedGoalProvider(), None, "旧目标")
        old_id = _current_goal_id(goal_cwd)
        store = JobStore(str(goal_cwd / "jobs.json"))
        store.add(store.create_job(f"goal-advance {old_id}", "*/15 * * * *"))
        await _goal_runner(ScriptedGoalProvider(), None, "新目标", cron_store=store)
        assert all(job.prompt != f"goal-advance {old_id}" for job in store.list_jobs())

    @pytest.mark.asyncio
    async def test_stale_auto_job_is_removed_after_reset(self, goal_cwd: Path) -> None:
        _seed_goal(goal_cwd)
        store = JobStore(str(goal_cwd / "jobs.json"))
        store.add(store.create_job("goal-advance deadbeef", "*/15 * * * *"))
        (goal_cwd / ".heagent" / "goals" / "current").unlink()
        await _goal_cron_advance(ScriptedGoalProvider(), None, store, "deadbeef")
        assert store.list_jobs() == []

    def test_only_exact_goal_auto_prompts_are_routed(self) -> None:
        assert _goal_auto_goal_id("goal-advance deadbeef") == "deadbeef"
        assert _goal_auto_goal_id("goal-advance write report") is None


class TestGoalUsageAndDispatch:
    @pytest.mark.asyncio
    async def test_unimplemented_subcommands_print_usage(
        self, goal_cwd: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        provider = ScriptedGoalProvider()
        await _goal_runner(provider, None, "run")
        await _goal_runner(provider, None, "auto")
        assert capsys.readouterr().err.count("/goal next") >= 2  # 用法表打印两次
        assert provider.calls == []
        assert not (goal_cwd / ".heagent" / "goals").exists()

    @pytest.mark.asyncio
    async def test_unknown_first_token_treated_as_description(
        self, goal_cwd: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # 解析契约锁定：首 token 非保留子命令即整段视为目标描述（含疑似拼错的
        # 单 token——与中文单 token 目标无法结构性区分，由 planning 会话显性呈现）。
        provider = ScriptedGoalProvider()
        await _goal_runner(provider, None, "stat")
        assert provider.calls != []  # 开了 planning 会话
        goal_id = _current_goal_id(goal_cwd)
        assert (goal_cwd / ".heagent" / "goals" / goal_id / "goal.txt").read_text(encoding="utf-8") == "stat"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("args", ["reset xyz", "status now", "next one"])
    async def test_reserved_with_trailing_text_prints_usage(
        self, goal_cwd: Path, capsys: pytest.CaptureFixture[str], args: str
    ) -> None:
        _seed_goal(goal_cwd)
        provider = ScriptedGoalProvider()
        await _goal_runner(provider, None, args)
        err = capsys.readouterr().err
        assert "/goal" in err  # 用法表（显性拒绝，不静默吞尾文本）
        assert (goal_cwd / ".heagent" / "goals" / "current").exists()  # reset 变体：指针未清
        assert provider.calls == []

    @pytest.mark.asyncio
    async def test_registered_and_routed_via_real_registry(
        self, goal_cwd: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        provider = ScriptedGoalProvider()
        loop = AgentLoop(provider)
        registry = _build_slash_registry(provider, None, None, "s1", loop, None)
        assert registry.has("goal")
        assert await _handle_slash("/goal next", registry) is True
        assert "无活跃 goal" in capsys.readouterr().err  # 子命令解析经真实 dispatch 生效
        assert provider.calls == []


class TestSessionWiring:
    @pytest.mark.asyncio
    async def test_goal_session_builds_loop_with_window_reset_and_fresh_context(
        self, goal_cwd: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """验收锁定：会话 loop 携带 WindowResetConfig(threshold=设置阈值) + 全新 RunContext。"""
        _seed_goal(goal_cwd)
        captured: dict[str, object] = {}
        from heagent.agent import loop as loop_module

        real_init = loop_module.AgentLoop.__init__

        def spy_init(loop_self: object, provider: object, **kwargs: object) -> None:
            captured["window_reset"] = kwargs.get("window_reset")
            captured["engine"] = kwargs.get("engine")
            captured["run_context"] = kwargs.get("run_context")
            assert real_init is not None
            real_init(loop_self, provider, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(loop_module.AgentLoop, "__init__", spy_init)
        await _goal_runner(ScriptedGoalProvider(), None, "next")
        wr = captured["window_reset"]
        assert isinstance(wr, WindowResetConfig)
        assert wr.threshold == get_settings().window_reset_threshold
        assert captured["engine"] is not None  # engine 注入（None 时 SubAgent 兜底默认容器）
        rc = captured["run_context"]
        assert rc is not None and rc.run_id  # type: ignore[attr-defined]  # 独立 RunContext
