"""单次 loop run 的持久化快照（store）。

本模块属于 ``engine/`` 运行时治理层（见 ``docs/frame.md`` 4.12）。``RunStore`` 把一次 run
的完整可恢复状态写到 ``.heagent/runs/<run_id>.json``：context / prompt / system /
messages / results / final_answer / error。AgentLoop 在 ``run()`` 中经 ``start()`` 起始、
迭代中经 ``checkpoint()`` 持续落盘，使崩溃 / resume 成为可能。

另提供 :class:`RunNode` + :meth:`RunStore.build_run_tree`，按 ``parent_run_id`` 把多次 run
（含子 Agent run）聚合成**树 / 森林**，供 task_status 等工具查询委派层级（P5-4；确定性输出：
按 sorted id 访问，子节点亦排序）。

> 注意：与 ``context/session.py``（``.heagent/sessions/``，跨轮**对话历史**）用途不同——
> RunStore 是**单次 run 的可恢复快照**（见 frame.md 4.5 / 4.12）。
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from pydantic import BaseModel, Field

# noqa: TC001 — RunContext/Message/ToolResult 是 Pydantic 模型字段类型，
# 需运行期导入以构建 schema（ruff TC001 为误报）。
from heagent.engine.context import RunContext, RunStatus  # noqa: TC001
from heagent.engine.persist import atomic_write_text, load_json_model
from heagent.types import Message, ToolResult  # noqa: TC001


class RunSnapshot(BaseModel):
    """一次 run 的持久化快照（完整可恢复状态）。"""

    # 该 run 的上下文（含 run_id / parent_run_id / status / iteration / metadata）。
    context: RunContext
    # 用户原始提示词。
    prompt: str
    # 生效的系统提示词（拼接 skill / memory / role 等之后）。
    system: str | None = None
    # 对话消息历史（含 assistant / tool 消息）。
    messages: list[Message] = Field(default_factory=list)
    # 本 run 产出的工具结果。
    results: list[ToolResult] = Field(default_factory=list)
    # 最终答案（run 正常完成时）。
    final_answer: str | None = None
    # 错误信息（run 失败时）。
    error: str | None = None


class RunNode(BaseModel):
    """run 层级树中的一个节点，经 ``parent_run_id`` 链接。"""

    run_id: str
    # 父 run 的 run_id；顶层 run 为 None。
    parent_run_id: str | None = None
    # 该 run 的结束状态（从快照 context 读出）。
    status: RunStatus | None = None
    # 子 run 节点（按 sorted id 顺序填充，见 build_run_tree）。
    children: list[RunNode] = Field(default_factory=list)


# RunNode.children 自引用（list[RunNode]），需 rebuild 以正确构建 Pydantic schema。
RunNode.model_rebuild()


class RunStore:
    """JSON 文件后端的 run 快照存储。"""

    def __init__(self, base_dir: str = ".heagent/runs") -> None:
        # 快照根目录；按需在 save() 时创建。
        self._base = Path(base_dir)

    async def start(self, context: RunContext, *, prompt: str, system: str | None = None) -> str:
        """创建或覆盖一个 run 的初始快照，返回写入路径。"""
        snapshot = RunSnapshot(context=context.model_copy(deep=True), prompt=prompt, system=system)
        return await self.save(snapshot)

    async def checkpoint(
        self,
        context: RunContext,
        *,
        prompt: str,
        system: str | None = None,
        messages: list[Message] | None = None,
        results: list[ToolResult] | None = None,
        final_answer: str | None = None,
        error: str | None = None,
    ) -> str:
        """持久化 run 的最新状态（增量合并：load 已有快照 → 覆盖传入字段 → save）。

        各可选参数为 None 时保留原值；深拷贝入参，避免外部对象被后续修改污染快照。
        """
        snapshot = await self.load(context.run_id)
        if snapshot is None:
            snapshot = RunSnapshot(context=context.model_copy(deep=True), prompt=prompt, system=system)
        snapshot.context = context.model_copy(deep=True)
        snapshot.prompt = prompt
        snapshot.system = system
        if messages is not None:
            snapshot.messages = [m.model_copy(deep=True) for m in messages]
        if results is not None:
            snapshot.results = [r.model_copy(deep=True) for r in results]
        if final_answer is not None:
            snapshot.final_answer = final_answer
        if error is not None:
            snapshot.error = error
        return await self.save(snapshot)

    async def save(self, snapshot: RunSnapshot) -> str:
        """把一份快照原子写到磁盘（按 run_id 命名），返回路径字符串。"""
        path = self._path(snapshot.context.run_id)
        payload = snapshot.model_dump(mode="json")
        text = json.dumps(payload, ensure_ascii=False, indent=2)
        await asyncio.to_thread(atomic_write_text, path, text)
        return str(path)

    async def load(self, run_id: str) -> RunSnapshot | None:
        """按 run_id 加载一份快照；不存在或损坏则返回 None。"""
        path = self._path(run_id)
        if not await asyncio.to_thread(path.exists):
            return None
        return await asyncio.to_thread(load_json_model, path, RunSnapshot)

    async def list_runs(self) -> list[str]:
        """列出全部已持久化的 run_id（排序）。"""
        if not await asyncio.to_thread(self._base.exists):
            return []
        paths = await asyncio.to_thread(lambda: list(self._base.glob("*.json")))
        return sorted(path.stem for path in paths)

    async def build_run_tree(self, root_id: str | None = None) -> list[RunNode]:
        """按 ``parent_run_id`` 把全部 run 聚合成树 / 森林。

        不传 ``root_id``：返回所有「根 run」——即 ``parent_run_id`` 为 None、或指向**不在
        store 中**的 run（断链视为根）；每个根携带其完整子树。传 ``root_id``：返回以该 run
        为根的子树（单元素列表；未知 run 返回空列表）。输出确定：按 sorted id 访问，故同一
        父下的子节点亦按 id 排序。
        """
        # 第一趟：为每个 run 建节点（带 parent_run_id / status）。
        nodes: dict[str, RunNode] = {}
        for run_id in await self.list_runs():
            snapshot = await self.load(run_id)
            if snapshot is None:
                continue
            ctx = snapshot.context
            nodes[run_id] = RunNode(
                run_id=run_id,
                parent_run_id=ctx.parent_run_id,
                status=ctx.status,
            )

        # 第二趟：把每个节点挂到父节点的 children；父不在 store 则视为根。
        roots: list[RunNode] = []
        for node in nodes.values():
            parent = node.parent_run_id
            if parent is not None and parent in nodes:
                nodes[parent].children.append(node)
            else:
                roots.append(node)

        if root_id is not None:
            target = nodes.get(root_id)
            return [target] if target is not None else []
        return roots

    async def delete(self, run_id: str) -> bool:
        """删除一份已存储的 run 快照；不存在则返回 False。"""
        path = self._path(run_id)
        if not await asyncio.to_thread(path.exists):
            return False
        await asyncio.to_thread(path.unlink)
        return True

    def _path(self, run_id: str) -> Path:
        """run_id → 快照文件路径（``<base>/<run_id>.json``）。"""
        return self._base / f"{run_id}.json"
