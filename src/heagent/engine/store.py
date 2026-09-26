"""单次 loop run 的持久化快照（store）。

本模块属于 ``engine/`` 运行时治理层（见 ``docs/frame.md`` 4.12）。``RunStore`` 把一次 run
的完整可恢复状态写到 ``.heagent/runs/<run_id>.json``：context / prompt / system /
messages / results / final_answer / error。AgentLoop 在 ``run()`` 中经 ``start()`` 起始、
迭代中经 ``checkpoint()`` 持续落盘，使崩溃 / resume 成为可能。

另提供 :class:`RunNode` + :meth:`RunStore.build_run_tree`，按 ``parent_run_id`` 把多次 run
（含子 Agent run）聚合成**树 / 森林**，供 task_status 等工具查询委派层级（P5-4；确定性输出：
按 sorted id 访问，子节点亦排序）。

另提供 :meth:`RunStore.prune`：按保留期清理过期快照，并**随记录一并回收配套 ``.lock``**
（``persist.py`` 刻意不删除锁文件以规避 unlink 竞态，本方法是 runs 侧唯一的合法清理时机）
以及该 run 的产物目录（``<run_id>/``，如 rollout）。清理由 ``EngineContainer.prune_runs_once``
在全新 run 启动时触发一次（与 ledger 同构）。

> 注意：与 ``context/session.py``（``.heagent/sessions/``，跨轮**对话历史**）用途不同——
> RunStore 是**单次 run 的可恢复快照**（见 frame.md 4.5 / 4.12）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from pydantic import BaseModel, Field

# noqa: TC001 — RunContext/Message/ToolResult 是 Pydantic 模型字段类型，
# 需运行期导入以构建 schema（ruff TC001 为误报）。
from heagent.engine.context import RunContext, RunStatus  # noqa: TC001
from heagent.pub.persist import (
    atomic_write_text,
    delete_entries,
    load_json_model,
    prune_stamp_path,
    scan_dir,
    stamp_is_recent,
    touch_prune_stamp,
)
from heagent.pub.types import Message, ToolResult  # noqa: TC001

logger = logging.getLogger(__name__)

# prune 进度日志间隔（每处理 N 个条目打一次 info，避免万级文件时静默过久）。
_PRUNE_PROGRESS_INTERVAL = 500
# 锁文件后缀（与 persist.py 的 ``path.name + ".lock"`` 约定一致）。
_LOCK_SUFFIX = ".lock"


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
        # 跨进程文件锁开关（经 EngineContainer.enable_file_locks 注入，V2）。
        self._enable_locks: bool = False

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
        # P1-9 修复：system 为 None 时保留原值，不覆写为 None 清空有效系统提示词。
        if system is not None:
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
        await asyncio.to_thread(atomic_write_text, path, text, lock=self._enable_locks)
        return str(path)

    async def load(self, run_id: str) -> RunSnapshot | None:
        """按 run_id 加载一份快照；不存在或损坏则返回 None。"""
        return await asyncio.to_thread(load_json_model, self._path(run_id), RunSnapshot)

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

        .. note::

           损坏或解析失败的 run 快照记录在跳过时记 ``logger.warning``（含 run_id），
           不阻塞其余正常 run 的树构造。这与 :meth:`load` 的单条容错策略一致。
        """
        # 第一趟：为每个 run 建节点（带 parent_run_id / status）。
        nodes: dict[str, RunNode] = {}
        for run_id in await self.list_runs():
            snapshot = await self.load(run_id)
            if snapshot is None:
                # 文件存在但解析失败（损坏 JSON / schema 不匹配）→ 记日志后跳过，
                # 不阻塞其余正常 run 的树构造（P1-2 修复：显性可观测替代静默丢失）。
                logger.warning("Skipping corrupted or unreadable run snapshot: %s", run_id)
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

    async def prune(self, *, retention_days: int, min_interval_seconds: int = 0) -> int:
        """按保留期清理过期 run 快照，返回**删除项数**。``retention_days <= 0`` 时禁用（返回 0）。

        ``min_interval_seconds > 0`` 时再加一层**跨进程节流**：距上次清理不足该间隔就直接
        返回 0（不扫描）。生产由 ``PRUNE_MIN_INTERVAL_SECONDS`` 给定，避免每次 CLI 启动都
        重新扫一遍万级目录；短命进程（每次调用都是新进程）正是这层节流的主要受益者。

        删除范围（每项各计 1）：

        * 过期记录 ``<run_id>.json``（mtime 早于 cutoff）**及其配套 ``<run_id>.json.lock``**；
        * 过期记录的产物目录 ``<run_id>/``（如 rollout.jsonl）——避免留下无主产物；
        * **无主锁** ``<run_id>.json.lock``：记录已不存在（如被 :meth:`delete` 单独删除）且
          锁本身已过期。``persist.py`` 刻意不删除锁文件以规避 unlink 竞态，此处是 runs 侧
          唯一的合法回收时机（与 ``ledger.prune`` 同约定）。

        设计要点：

        * **轻量判定**：只看文件 ``mtime``，**不 load** 任何 Pydantic 模型（对齐 ``ledger.prune``
          的 P1-23 重写：万级文件下避免逐条 ``model_validate``）。
        * **不会误删在途 run**：在途 run 每次 ``checkpoint`` 都会刷新 mtime，而保留期以天计，
          远大于一次 run 的写入间隔。
        * **失败不中断**：单条 ``stat``/``unlink``/``rmtree`` 失败仅 ``debug`` 日志后继续；
          每 ``_PRUNE_PROGRESS_INTERVAL`` 条打一次进度 info（万级文件时不静默）。
        """
        if retention_days <= 0:
            return 0
        stamp = prune_stamp_path(self._base)
        if await asyncio.to_thread(stamp_is_recent, stamp, min_interval_seconds):
            return 0
        if not await asyncio.to_thread(self._base.exists):
            return 0
        cutoff = time.time() - retention_days * 86_400
        entries = await asyncio.to_thread(scan_dir, self._base)
        records = [e for e in entries if not e.is_dir and e.path.name.endswith(".json")]
        locks = [e for e in entries if not e.is_dir and e.path.name.endswith(_LOCK_SUFFIX)]
        dir_names = {e.path.name for e in entries if e.is_dir}
        lock_names = {e.path.name for e in locks}

        to_unlink: list[Path] = []
        to_rmtree: list[Path] = []
        # 第一遍：过期记录 + 其配套锁 + 产物目录（每项各计 1）。
        for i, entry in enumerate(records):
            if i > 0 and i % _PRUNE_PROGRESS_INTERVAL == 0:
                logger.info("run store prune: scanned %d/%d records", i, len(records))
            if entry.mtime >= cutoff:
                continue
            to_unlink.append(entry.path)
            lock_path = entry.path.with_name(entry.path.name + _LOCK_SUFFIX)
            if lock_path.name in lock_names:
                to_unlink.append(lock_path)
            run_id = entry.path.name[: -len(".json")]
            directory = self._base / run_id
            # 仅当目录确实是 self._base 的直接子目录时才删——run_id 来自目录内文件名，
            # 该断言防「名字里带路径分隔符 / 符号链接」导致的越界删除。
            if run_id in dir_names and directory.parent == self._base:
                to_rmtree.append(directory)
        # 第二遍：无主锁（记录已不存在）仅在自身也过期时回收。
        swept = {p.name for p in to_unlink}
        record_names = {e.path.name for e in records}
        for i, entry in enumerate(locks):
            if i > 0 and i % _PRUNE_PROGRESS_INTERVAL == 0:
                logger.info("run store prune: scanned %d/%d locks", i, len(locks))
            record_name = entry.path.name[: -len(_LOCK_SUFFIX)]  # <run_id>.json.lock → <run_id>.json
            if record_name in record_names or entry.path.name in swept:
                continue
            if entry.mtime >= cutoff:
                continue
            to_unlink.append(entry.path)

        files_deleted, dirs_deleted = await asyncio.to_thread(delete_entries, to_unlink, to_rmtree)
        deleted = files_deleted + dirs_deleted
        await asyncio.to_thread(touch_prune_stamp, stamp)

        total = len(records) + len(locks)
        if total >= _PRUNE_PROGRESS_INTERVAL:
            logger.info("run store prune: done — deleted %d of %d entries", deleted, total)
        return deleted

    def _path(self, run_id: str) -> Path:
        """run_id → 快照文件路径（``<base>/<run_id>.json``）。"""
        return self._base / f"{run_id}.json"
