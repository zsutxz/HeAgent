"""Tests for P5-4 — RunStore.build_run_tree parent/child aggregation."""

from __future__ import annotations

from heagent.engine.context import RunContext, RunStatus
from heagent.engine.store import RunNode, RunStore


def _persist(store: RunStore, rc: RunContext, *, prompt: str = "p") -> RunContext:
    """Write one run snapshot so it shows up in build_run_tree."""
    store.start(rc, prompt=prompt, system=None)
    store.checkpoint(rc, prompt=prompt, system=None, messages=[])
    return rc


def test_build_run_tree_forest(tmp_path) -> None:
    """一个父 run 下挂两个子 run → 单根森林，根带两个孩子。"""
    store = RunStore(str(tmp_path / "runs"))
    parent = _persist(store, RunContext())
    _persist(store, RunContext(parent_run_id=parent.run_id))
    _persist(store, RunContext(parent_run_id=parent.run_id))

    roots = store.build_run_tree()
    assert len(roots) == 1
    assert roots[0].run_id == parent.run_id
    assert len(roots[0].children) == 2
    assert all(c.parent_run_id == parent.run_id for c in roots[0].children)


def test_build_run_tree_subtree(tmp_path) -> None:
    """root_id 取指定 run 的子树；未知 run_id 返回空。"""
    store = RunStore(str(tmp_path / "runs"))
    parent = _persist(store, RunContext())
    child = _persist(store, RunContext(parent_run_id=parent.run_id))

    sub_parent = store.build_run_tree(root_id=parent.run_id)
    assert [n.run_id for n in sub_parent] == [parent.run_id]
    assert len(sub_parent[0].children) == 1

    sub_child = store.build_run_tree(root_id=child.run_id)
    assert [n.run_id for n in sub_child] == [child.run_id]
    assert sub_child[0].children == []

    assert store.build_run_tree(root_id="nope") == []


def test_build_run_tree_orphan_treated_as_root(tmp_path) -> None:
    """parent_run_id 指向不存在的 run 时，该 run 视为根（不丢失）。"""
    store = RunStore(str(tmp_path / "runs"))
    orphan = _persist(store, RunContext(parent_run_id="missing-run"))

    roots = store.build_run_tree()
    assert [n.run_id for n in roots] == [orphan.run_id]
    assert roots[0].children == []


def test_build_run_tree_empty(tmp_path) -> None:
    store = RunStore(str(tmp_path / "runs"))
    assert store.build_run_tree() == []


def test_build_run_tree_records_status(tmp_path) -> None:
    """节点 status 取自 RunContext。"""
    store = RunStore(str(tmp_path / "runs"))
    rc = RunContext()
    rc.touch(status=RunStatus.COMPLETED)
    _persist(store, rc)

    roots = store.build_run_tree()
    assert roots[0].status == RunStatus.COMPLETED


def test_run_node_is_pydantic_recursive(tmp_path) -> None:
    """RunNode 自引用可嵌套序列化（孙节点深度 ≥2）。"""
    store = RunStore(str(tmp_path / "runs"))
    grandparent = _persist(store, RunContext())
    parent = _persist(store, RunContext(parent_run_id=grandparent.run_id))
    _persist(store, RunContext(parent_run_id=parent.run_id))

    roots = store.build_run_tree()
    assert len(roots) == 1
    assert roots[0].run_id == grandparent.run_id
    # 序列化自引用模型不应抛错，且能还原出三层结构
    dumped = roots[0].model_dump_json()
    restored = RunNode.model_validate_json(dumped)
    assert restored.children[0].children[0].parent_run_id == parent.run_id
