"""Tests for slash command system (Epic 31)."""

from __future__ import annotations

import pytest

from heagent.cli import _handle_slash
from heagent.slash import SlashRegistry, load_custom_commands


class TestSlashRegistry:
    @pytest.mark.asyncio
    async def test_dispatch_hits_and_misses(self) -> None:
        registry = SlashRegistry()
        calls: list[str] = []

        async def handler(args: str) -> None:
            calls.append(args)

        registry.register("foo", "a command", handler)
        assert registry.has("foo")
        assert registry.has("FOO")  # 大小写不敏感
        assert not registry.has("bar")
        assert (await registry.dispatch("foo", "hello world")) is True
        assert calls == ["hello world"]
        assert (await registry.dispatch("bar", "")) is False

    def test_names_sorted_and_describe(self) -> None:
        registry = SlashRegistry()

        async def handler(args: str) -> None:
            return None

        registry.register("b", "bee", handler)
        registry.register("a", "aye", handler)
        assert registry.names() == ["a", "b"]
        assert registry.describe("a") == "aye"
        assert registry.describe("missing") == ""


class TestLoadCustomCommands:
    def test_loads_frontmatter(self, tmp_path) -> None:
        (tmp_path / "review.md").write_text(
            "---\nname: review\ndescription: Review code\n---\n请审查代码变更", encoding="utf-8"
        )
        cmds = load_custom_commands([str(tmp_path)])
        assert len(cmds) == 1
        assert cmds[0].name == "review"
        assert cmds[0].description == "Review code"
        assert cmds[0].prompt == "请审查代码变更"

    def test_falls_back_to_filename_when_no_name(self, tmp_path) -> None:
        (tmp_path / "foo.md").write_text("正文内容", encoding="utf-8")
        cmds = load_custom_commands([str(tmp_path)])
        assert len(cmds) == 1
        assert cmds[0].name == "foo"

    def test_skips_empty_prompt(self, tmp_path) -> None:
        (tmp_path / "empty.md").write_text("---\nname: empty\n---\n   \n", encoding="utf-8")
        cmds = load_custom_commands([str(tmp_path)])
        assert cmds == []

    def test_later_dir_overrides_earlier(self, tmp_path) -> None:
        d1 = tmp_path / "global"
        d2 = tmp_path / "project"
        d1.mkdir()
        d2.mkdir()
        (d1 / "x.md").write_text("---\nname: x\n---\nglobal prompt", encoding="utf-8")
        (d2 / "x.md").write_text("---\nname: x\n---\nproject prompt", encoding="utf-8")
        cmds = load_custom_commands([str(d1), str(d2)])
        assert len(cmds) == 1
        assert cmds[0].prompt == "project prompt"

    def test_nonexistent_dir_yields_empty(self, tmp_path) -> None:
        assert load_custom_commands([str(tmp_path / "nope")]) == []


class TestHandleSlash:
    @pytest.mark.asyncio
    async def test_dispatches_to_registry(self) -> None:
        registry = SlashRegistry()
        got: list[str] = []

        async def handler(args: str) -> None:
            got.append(args)

        registry.register("test", "", handler)
        assert (await _handle_slash("/test a b", registry)) is True
        assert got == ["a b"]

    @pytest.mark.asyncio
    async def test_unknown_returns_false(self) -> None:
        registry = SlashRegistry()
        assert (await _handle_slash("/nope", registry)) is False

    @pytest.mark.asyncio
    async def test_non_slash_returns_false(self) -> None:
        registry = SlashRegistry()
        assert (await _handle_slash("hello", registry)) is False
