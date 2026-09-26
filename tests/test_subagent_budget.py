"""嵌套子代理迭代预算的解析契约：显式参数 > 角色声明 > Settings.subagent_max_iterations。

回归背景：验证器子代理曾在 20 轮上限被饿死（`/goal` step-07 的 task_parallel 验证批次），
根因是 20 被写死在 `SubAgent` 兜底与角色解析里。现改为可配置，且内置 tester 不再钉死 20。
"""

from __future__ import annotations

from pathlib import Path

from heagent.agent.loop import AgentLoop
from heagent.agent.sub import SubAgent
from heagent.config import Settings, get_settings
from heagent.roles import RoleSpec, get_role, load_agent_roles
from heagent.providers.base import ProviderMetadata
from heagent.types import Message, ProviderResponse, TokenUsage


class _OneShotProvider:
    """第一轮即返回最终答案的 provider（子 loop 立刻收尾，测试不依赖轮数）。"""

    async def send(self, messages: list[Message], *, tools=None) -> ProviderResponse:  # noqa: ANN001, ARG002
        return ProviderResponse(content="done", usage=TokenUsage(), model="stub", finish_reason="stop")

    async def stream(self, messages: list[Message], *, tools=None):  # noqa: ANN001, ARG002
        yield ProviderResponse(content="done", usage=TokenUsage(), model="stub", finish_reason="stop")

    def get_metadata(self) -> ProviderMetadata:
        return ProviderMetadata(name="stub", model="stub")


def _capture_child_budget(monkeypatch) -> list[int]:  # noqa: ANN001
    """捕获 SubAgent 创建的子 AgentLoop 实际收到的 max_iterations（公开可观测行为）。"""
    seen: list[int] = []
    original = AgentLoop.__init__

    def spy(self, provider, **kwargs):  # noqa: ANN001
        seen.append(kwargs["max_iterations"])
        original(self, provider, **kwargs)

    monkeypatch.setattr(AgentLoop, "__init__", spy)
    return seen


async def test_child_loop_follows_setting_when_role_undeclared(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    """角色未声明预算时跟随 Settings（原来固定 20，是验证器饿死的根因）。"""
    monkeypatch.setattr(get_settings(), "subagent_max_iterations", 60)
    seen = _capture_child_budget(monkeypatch)

    await SubAgent(_OneShotProvider(), context_dir=str(tmp_path)).run("task")

    assert seen == [60]


async def test_role_declaration_wins_over_setting(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    """角色显式声明仍然优先于全局配置（不悄悄改写既有角色语义）。"""
    monkeypatch.setattr(get_settings(), "subagent_max_iterations", 60)
    seen = _capture_child_budget(monkeypatch)
    role = RoleSpec(name="custom", system="be terse", max_iterations=7)

    await SubAgent(_OneShotProvider(), role=role, context_dir=str(tmp_path)).run("task")

    assert seen == [7]


async def test_explicit_argument_wins_over_role_and_setting(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    """显式参数优先级最高（委派调用点可直接指定预算）。"""
    monkeypatch.setattr(get_settings(), "subagent_max_iterations", 60)
    seen = _capture_child_budget(monkeypatch)
    role = RoleSpec(name="custom", system="be terse", max_iterations=7)

    agent = SubAgent(_OneShotProvider(), role=role, max_iterations=3, context_dir=str(tmp_path))
    await agent.run("task")

    assert seen == [3]


async def test_builtin_tester_follows_setting(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    """内置 tester 不再钉死 20——它正是被饿死的「验证器」角色，改由配置决定。"""
    assert get_role("tester").max_iterations is None
    monkeypatch.setattr(get_settings(), "subagent_max_iterations", 60)
    seen = _capture_child_budget(monkeypatch)

    await SubAgent(_OneShotProvider(), role=get_role("tester"), context_dir=str(tmp_path)).run("task")

    assert seen == [60]


def test_other_builtin_roles_keep_explicit_budgets() -> None:
    """有意保留的角色差异化阶梯不受本次改动影响。"""
    assert get_role("planner").max_iterations == 15
    assert get_role("coder").max_iterations == 25
    assert get_role("supervisor").max_iterations == 30


def test_role_md_without_max_iterations_is_undeclared(tmp_path: Path) -> None:
    """角色 .md 的 frontmatter 未声明 max_iterations 时不再是写死的 20，而是 None（跟随配置）。"""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    (agents_dir / "budget-probe.md").write_text(
        "---\nname: budget-probe\ndescription: 未声明迭代预算\n---\n\n你是探针角色。\n",
        encoding="utf-8",
    )

    loaded = load_agent_roles([agents_dir])

    spec = next(spec for spec in loaded if spec.name == "budget-probe")
    assert spec.max_iterations is None


def test_default_setting_preserves_legacy_behavior() -> None:
    """默认值仍是 20：不配置时行为与改动前逐字一致。"""
    assert get_settings().subagent_max_iterations == 20


async def test_cli_dream_runner_passes_dream_max_iterations(monkeypatch, tmp_path: Path) -> None:  # noqa: ANN001
    """composition 组合根把 Settings.dream_max_iterations 真的传给了 dreamer SubAgent（防退化为死字段）。"""
    from heagent.cli import composition
    from heagent.context.session import SessionStore
    from heagent.engine import EngineContainer
    from heagent.memory.facts import FactStore
    from heagent.memory.profile import ProfileStore
    from heagent.memory.skills import SkillStore

    settings = Settings(_env_file=None, dream_enabled=True, dream_max_iterations=42)
    captured: list[int] = []
    original = SubAgent.__init__

    def spy(self, provider, **kwargs):  # noqa: ANN001
        captured.append(kwargs["max_iterations"])
        original(self, provider, **kwargs)

    monkeypatch.setattr(SubAgent, "__init__", spy)

    scheduler = composition._build_dream_scheduler(
        settings,
        _OneShotProvider(),
        EngineContainer(),
        SessionStore(base_dir=str(tmp_path / "sessions")),
        SkillStore(base_dir=str(tmp_path / "skills")),
        FactStore(path=str(tmp_path / "MEMORY.md")),
        ProfileStore(path=str(tmp_path / "USER.md")),
        None,
    )
    assert scheduler is not None

    await scheduler._run_dream("cron")

    assert captured == [42]
