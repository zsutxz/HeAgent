"""Coverage tests for engine/store.py uncovered lines.

Targets:
- checkpoint() 不传 system 保留原值（P1-9 已修复）
- checkpoint() 传 messages/results 更新
- delete() 不存在返回 False
- delete() 成功返回 True
- build_run_tree() 损坏文件被跳过
"""

from __future__ import annotations

import pytest

from heagent.engine.context import RunContext
from heagent.engine.store import RunStore
from heagent.types import Message, ToolResult


# ── checkpoint ────────────────────────────────────────────────────


class TestCheckpointPreserveSystem:
    @pytest.mark.asyncio
    async def test_checkpoint_preserves_system_when_not_passed(self, tmp_path) -> None:
        """checkpoint() 不传 system 时保留原值，不覆写为 None清空有效系统提示词。"""
        store = RunStore(base_dir=str(tmp_path / "runs"))
        ctx = RunContext()

        await store.start(ctx, prompt="hello", system="initial-system")

        # checkpoint without system kwarg → must preserve "initial-system"
        await store.checkpoint(ctx, prompt="hello")

        snapshot = await store.load(ctx.run_id)
        assert snapshot is not None
        assert snapshot.system == "initial-system"


class TestCheckpointUpdateFields:
    @pytest.mark.asyncio
    async def test_checkpoint_updates_messages(self, tmp_path) -> None:
        """checkpoint() 传 messages 更新 messages 字段。"""
        store = RunStore(base_dir=str(tmp_path / "runs"))
        ctx = RunContext()

        await store.start(ctx, prompt="hello")

        msgs = [
            Message(role="user", content="hello"),
            Message(role="assistant", content="hi there"),
        ]
        await store.checkpoint(ctx, prompt="hello", messages=msgs)

        snapshot = await store.load(ctx.run_id)
        assert snapshot is not None
        assert len(snapshot.messages) == 2
        assert snapshot.messages[0].role == "user"
        assert snapshot.messages[0].content == "hello"
        assert snapshot.messages[1].role == "assistant"

    @pytest.mark.asyncio
    async def test_checkpoint_updates_results(self, tmp_path) -> None:
        """checkpoint() 传 results 更新 results 字段。"""
        store = RunStore(base_dir=str(tmp_path / "runs"))
        ctx = RunContext()

        await store.start(ctx, prompt="hello")

        results = [
            ToolResult(tool_call_id="tc-a", content="output-a"),
            ToolResult(tool_call_id="tc-b", content="output-b", is_error=True),
        ]
        await store.checkpoint(ctx, prompt="hello", results=results)

        snapshot = await store.load(ctx.run_id)
        assert snapshot is not None
        assert len(snapshot.results) == 2
        assert snapshot.results[0].tool_call_id == "tc-a"
        assert snapshot.results[1].is_error is True


# ── delete ────────────────────────────────────────────────────────


class TestDelete:
    @pytest.mark.asyncio
    async def test_delete_returns_false_when_not_exists(self, tmp_path) -> None:
        """delete() 对不存在的 run_id 返回 False。"""
        store = RunStore(base_dir=str(tmp_path / "runs"))
        result = await store.delete("nonexistent-run-id")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_returns_true_when_success(self, tmp_path) -> None:
        """delete() 成功删除已存在的 run 返回 True，后续 load 返回 None。"""
        store = RunStore(base_dir=str(tmp_path / "runs"))
        ctx = RunContext()

        await store.start(ctx, prompt="hello")
        assert await store.load(ctx.run_id) is not None  # 确认存在

        result = await store.delete(ctx.run_id)
        assert result is True
        assert await store.load(ctx.run_id) is None  # 确认已删除


# ── build_run_tree corrupted file ─────────────────────────────────


class TestBuildRunTreeSkipsCorrupted:
    @pytest.mark.asyncio
    async def test_build_run_tree_skips_corrupted_file(self, tmp_path) -> None:
        """build_run_tree() 遇到损坏 JSON 文件时跳过，不抛异常，仅含正常 run。"""
        store = RunStore(base_dir=str(tmp_path / "runs"))

        # 创建一个合法 run
        valid_ctx = RunContext()
        await store.start(valid_ctx, prompt="valid run")

        # 直接在 runs 目录下写一个损坏的 JSON 文件
        bad_path = tmp_path / "runs" / "corrupted-run.json"
        bad_path.write_text("{this is not valid json at all", encoding="utf-8")

        # build_run_tree 不应抛异常；结果仅含合法 run
        roots = await store.build_run_tree()
        assert len(roots) == 1
        assert roots[0].run_id == valid_ctx.run_id
