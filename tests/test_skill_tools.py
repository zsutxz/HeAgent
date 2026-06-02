"""Tests for skill management tools: skill_create, skill_update, skill_list, skill_delete."""

from __future__ import annotations

import pytest

from heagent.memory.skills import SkillStore
from heagent.tools.builtins.skills import (
    configure_skill_tools,
    reset_skill_tools,
    skill_create,
    skill_delete,
    skill_list,
    skill_update,
)


@pytest.fixture()
def skill_store(tmp_path: object) -> SkillStore:
    """创建临时 SkillStore 并注入到工具模块。"""
    store = SkillStore(base_dir=str(tmp_path / "skills"))  # type: ignore[operator]
    configure_skill_tools(store)
    yield store
    reset_skill_tools()


# ---- skill_create ----


class TestSkillCreate:
    @pytest.mark.asyncio
    async def test_create_success(self, skill_store: SkillStore) -> None:
        result = await skill_create("deploy", "Deploy app", "deploy to production", "push|deploy")
        assert "created" in result
        assert skill_store.load("deploy") is not None

    @pytest.mark.asyncio
    async def test_create_duplicate(self, skill_store: SkillStore) -> None:
        await skill_create("dup", "desc", "pat", "step1")
        result = await skill_create("dup", "desc2", "pat2", "step2")
        assert "already exists" in result

    @pytest.mark.asyncio
    async def test_create_empty_steps(self, skill_store: SkillStore) -> None:
        result = await skill_create("empty", "desc", "pat", "|||")
        assert "at least one step" in result

    @pytest.mark.asyncio
    async def test_create_no_store(self) -> None:
        reset_skill_tools()
        result = await skill_create("x", "d", "p", "s")
        assert "not configured" in result

    @pytest.mark.asyncio
    async def test_create_chinese_name_rejected(self, skill_store: SkillStore) -> None:
        result = await skill_create("生产环境部署", "desc", "pat", "step1")
        assert "English" in result or "english" in result.lower() or "Error" in result


# ---- skill_update ----


class TestSkillUpdate:
    @pytest.mark.asyncio
    async def test_update_description(self, skill_store: SkillStore) -> None:
        await skill_create("up", "old desc", "pat", "s1|s2")
        result = await skill_update("up", description="new desc")
        assert "updated" in result
        parsed = skill_store.parse("up")
        assert parsed is not None
        assert parsed.description == "new desc"
        assert parsed.steps == ["s1", "s2"]  # 未修改

    @pytest.mark.asyncio
    async def test_update_pattern(self, skill_store: SkillStore) -> None:
        await skill_create("up2", "desc", "old pattern", "step")
        result = await skill_update("up2", pattern="new pattern")
        assert "updated" in result
        parsed = skill_store.parse("up2")
        assert parsed is not None
        assert parsed.pattern == "new pattern"

    @pytest.mark.asyncio
    async def test_update_steps(self, skill_store: SkillStore) -> None:
        await skill_create("up3", "desc", "pat", "old1|old2")
        result = await skill_update("up3", steps="new1|new2|new3")
        assert "updated" in result
        parsed = skill_store.parse("up3")
        assert parsed is not None
        assert parsed.steps == ["new1", "new2", "new3"]

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, skill_store: SkillStore) -> None:
        result = await skill_update("ghost", description="x")
        assert "not found" in result

    @pytest.mark.asyncio
    async def test_update_empty_fields_keep_existing(self, skill_store: SkillStore) -> None:
        """空字段不修改已有值。"""
        await skill_create("keep", "orig desc", "orig pat", "s1")
        result = await skill_update("keep")  # 所有字段为空
        assert "updated" in result
        parsed = skill_store.parse("keep")
        assert parsed is not None
        assert parsed.description == "orig desc"
        assert parsed.pattern == "orig pat"
        assert parsed.steps == ["s1"]


# ---- skill_list ----


class TestSkillList:
    @pytest.mark.asyncio
    async def test_list_empty(self, skill_store: SkillStore) -> None:
        result = await skill_list()
        assert "No skills" in result

    @pytest.mark.asyncio
    async def test_list_populated(self, skill_store: SkillStore) -> None:
        await skill_create("alpha", "Alpha skill", "pat", "s1")
        await skill_create("beta", "Beta skill", "pat", "s1")
        result = await skill_list()
        assert "alpha" in result
        assert "beta" in result
        assert "Alpha skill" in result


# ---- skill_delete ----


class TestSkillDelete:
    @pytest.mark.asyncio
    async def test_delete_success(self, skill_store: SkillStore) -> None:
        await skill_create("del_me", "desc", "pat", "step")
        result = await skill_delete("del_me")
        assert "deleted" in result
        assert skill_store.load("del_me") is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent(self, skill_store: SkillStore) -> None:
        result = await skill_delete("ghost")
        assert "not found" in result
