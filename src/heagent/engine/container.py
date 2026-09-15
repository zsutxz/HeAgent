"""运行时服务的依赖注入（DI）容器。

本模块属于 ``engine/`` 运行时治理层（见 ``docs/frame.md`` 4.12）。``EngineContainer``
把全部运行时服务（策略 / 执行器 / 运行快照 / 幂等账本 / 事件总线）聚合到一个对象，
经 :meth:`EngineContainer.default` 装配后注入 :class:`~heagent.agent.loop.AgentLoop`：

- 主 Agent 经 ``engine=EngineContainer.default()`` 持有；
- 子 Agent 经 ``parent_run_id`` **继承父 engine**（运行时服务复用，仅按角色替换 PolicyEngine，
  见 ``docs/frame.md`` 4.2 / D4）。

V2 新增：``enable_file_locks`` 参数——开启后 ``RunStore``/``ExecutionLedger`` 的写操作
自动获取跨进程文件锁，防止多进程并发写 ``.heagent/`` 时数据损坏。
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from heagent.engine.context import RunContext
from heagent.engine.executor import ToolExecutor
from heagent.engine.hooks import HookManager
from heagent.engine.ledger import ExecutionLedger
from heagent.engine.observability import EventBus, LoggingObserver
from heagent.engine.policy import PolicyEngine
from heagent.engine.store import RunStore

if TYPE_CHECKING:
    from heagent.engine.approval import ApprovalHandler
    from heagent.tools.sandbox import CommandRunner

logger = logging.getLogger(__name__)


@dataclass
class EngineContainer:
    """跨多次 loop 执行共享的运行时服务集合。"""

    policy: PolicyEngine = field(default_factory=PolicyEngine)
    executor: ToolExecutor = field(default_factory=ToolExecutor)
    run_store: RunStore = field(default_factory=RunStore)
    ledger: ExecutionLedger = field(default_factory=ExecutionLedger)
    events: EventBus = field(default_factory=lambda: EventBus([LoggingObserver()]))
    workspace_root: str | None = None
    command_runner: CommandRunner | None = None
    approval_handler: ApprovalHandler | None = None
    hooks: HookManager | None = None
    enable_file_locks: bool = False
    # ledger 自动清理保留天数（0=禁用）；default() 从 Settings 读，手动构造默认 0。
    ledger_retention_days: int = 0
    # run 快照自动清理保留天数（0=禁用）；default() 从 Settings 读，手动构造默认 0。
    run_retention_days: int = 0
    # 过期清理的跨进程节流秒数（0=每次都扫）；default() 从 Settings 读，手动构造默认 0（测试无节流）。
    prune_min_interval_seconds: int = 0
    # 沙箱会话目录开关（E40-D4）：None = 跟随 Settings（env）；True/False = 显式覆盖
    # （CLI `--sandbox-session-workspace` / `--no-sandbox-session-workspace`）。
    sandbox_session_workspace: bool | None = None
    # 沙箱会话目录 teardown 保留开关（E40-D4）：None = 跟随 Settings；True/False = 显式覆盖
    # （CLI `--sandbox-session-keep` / `--no-sandbox-session-keep`）。
    sandbox_session_keep: bool | None = None
    # 进程内去重标志：同一容器 prune_*_once 仅首次 run 触发（sub agent 继承父 engine 时不重复扫）。
    # 两者独立：ledger 与 runs 各自的清理互不阻塞。
    _ledger_pruned: bool = field(default=False, init=False, repr=False)
    _runs_pruned: bool = field(default=False, init=False, repr=False)

    def __post_init__(self) -> None:
        # 注入 cross-process file locks（V2）
        if self.enable_file_locks:
            self.run_store._enable_locks = True
            self.ledger._enable_locks = True

        # P1-22 修复：仅在 executor 未显式设置 sandbox_runner 时注入（含显式 None），
        # 避免覆盖调用方「禁用沙箱」的意图。command_runner 非 None 而 executor 已有
        # runner 时记 warning，使运营方可感知配置冲突。
        if self.command_runner is not None:
            if self.executor.sandbox_runner is not None:
                logger.warning(
                    "command_runner is set but executor.sandbox_runner is already %s; command_runner is ignored",
                    type(self.executor.sandbox_runner).__name__,
                )
            else:
                self.executor.sandbox_runner = self.command_runner

    def _session_workspace_enabled(self) -> bool:
        """沙箱会话目录是否开启（E40-D4）：容器显式值（CLI）优先，否则跟随 Settings（env）。

        与 executor 授权同源：开关开启即写 metadata（后端是否真吃该目录由 executor 判定）。
        """
        if self.sandbox_session_workspace is not None:
            return self.sandbox_session_workspace
        from heagent.config import get_settings

        return get_settings().sandbox_session_workspace

    def _session_keep_enabled(self) -> bool:
        """run 结束后是否保留沙箱会话目录（E40-D4）：同上，CLI 值优先于 Settings。"""
        if self.sandbox_session_keep is not None:
            return self.sandbox_session_keep
        from heagent.config import get_settings

        return get_settings().sandbox_session_keep

    async def prune_ledger_once(self) -> int:
        """首次调用时清理过期 ledger 记录，之后短路返回 0（去重）。

        ``ledger_retention_days <= 0`` 时禁用。清理 IO 故障不中断 run（对齐
        ``persist.load_json_model`` 容错哲学）；已置 ``_ledger_pruned`` 标志本次不再重试。

        ``CancelledError`` 不吞（透传给调用方处理 task 取消语义）；其余 ``Exception``
        打含异常类型+消息的 error 日志并返回 0 继续 run。
        """
        if self._ledger_pruned or self.ledger_retention_days <= 0:
            return 0
        self._ledger_pruned = True
        try:
            n = await self.ledger.prune(
                retention_days=self.ledger_retention_days, min_interval_seconds=self.prune_min_interval_seconds
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "Ledger prune failed (%s: %s); skipping this run",
                type(exc).__name__,
                exc,
            )
            return 0
        if n:
            logger.info("Ledger pruned %d expired records (retention=%dd)", n, self.ledger_retention_days)
        return n

    async def prune_runs_once(self) -> int:
        """首次调用时清理过期 run 快照，之后短路返回 0（去重）。

        与 :meth:`prune_ledger_once` 同构：``run_retention_days <= 0`` 时禁用；清理 IO 故障
        不中断 run（``CancelledError`` 不吞，其余异常打 error 日志后返回 0）；``_runs_pruned``
        与 ledger 的去重标志**相互独立**——两者互不阻塞。

        为什么需要它：``RunStore`` 每次 run 写 ``<run_id>.json`` + ``.json.lock``，而
        ``persist.py`` 刻意不删锁文件，若无人回收则 runs 目录随运行次数单调增长
        （实测 84 天积累 6 万个文件 / 700MB）。
        """
        if self._runs_pruned or self.run_retention_days <= 0:
            return 0
        self._runs_pruned = True
        try:
            n = await self.run_store.prune(
                retention_days=self.run_retention_days, min_interval_seconds=self.prune_min_interval_seconds
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error(
                "Run snapshot prune failed (%s: %s); skipping this run",
                type(exc).__name__,
                exc,
            )
            return 0
        if n:
            logger.info("Run snapshots pruned %d expired entries (retention=%dd)", n, self.run_retention_days)
        return n

    @classmethod
    def default(
        cls,
        *,
        workspace_root: str | None = None,
        sandbox_backend: str | None = None,
        sandbox_session_workspace: bool | None = None,
        sandbox_session_keep: bool | None = None,
    ) -> EngineContainer:
        """为当前工作区创建默认装配的容器。

        读取 ``Settings.sandbox_backend`` 自动构造对应的 ``CommandRunner``（FR-S4）：
        - ``"passthrough"`` → ``command_runner=None``（透传快速路径）
        - ``"firejail"`` → ``FirejailBackend`` 实例
        - ``"winjob"`` → ``WinJobBackend`` 实例（FR-A3，Windows Job Objects）

        ``sandbox_backend`` 显式传入时优先于 Settings。``sandbox_session_workspace`` /
        ``sandbox_session_keep`` 为 ``None`` 时跟随 Settings（env），显式传值时覆盖
        （CLI 开关，E40-D4——三态语义使 ``--no-...`` 能反向覆盖 env 的 true）。
        """
        from heagent.config import get_settings

        settings = get_settings()
        backend = sandbox_backend if sandbox_backend is not None else settings.sandbox_backend
        backend = backend.strip().lower()
        if backend == "auto":
            # P0-2：自动档只认 firejail（Linux/macOS 的真实 OS 级隔离）。Windows 的 Job
            # Objects 需显式指定——它无文件系统隔离，自动启用会改掉所有 shell 命令的进程
            # 语义而隔离收益有限（诚实取舍，见 docs/frame.md 配置表）。
            import shutil as _shutil

            backend = "firejail" if _shutil.which(settings.sandbox_firejail_path) else "passthrough"
            logger.info("sandbox backend 'auto' resolved to %r", backend)
        command_runner: CommandRunner | None = None
        if backend == "firejail":
            from heagent.tools.sandbox import FirejailBackend

            command_runner = FirejailBackend(
                firejail_path=settings.sandbox_firejail_path,
                workspace_root=workspace_root,
                network=settings.sandbox_network,
            )
        elif backend == "winjob":
            from heagent.tools.sandbox import WinJobBackend

            if WinJobBackend.available():
                command_runner = WinJobBackend()
            else:
                logger.warning("WinJobBackend requested but not available; falling back to Passthrough")

        # 默认装配开启跨进程文件锁：CLI/GUI 可能多进程共享同一 .heagent/ 目录
        # （如 cron + 交互式实例并存），RunStore/ledger 写入需要跨进程互斥。
        # 锁文件由 persist.py 刻意保留（规避 unlink 竞态），回收时机是各自的 prune：
        # ledger 随过期记录、runs 随过期快照一并清理（见 engine/ledger.py、engine/store.py），
        # 故不会无限累积——但前提是 retention 未被禁用（0）。
        container = cls(
            workspace_root=workspace_root,
            command_runner=command_runner,
            enable_file_locks=True,
            sandbox_session_workspace=sandbox_session_workspace,
            sandbox_session_keep=sandbox_session_keep,
        )
        container.ledger_retention_days = settings.ledger_retention_days
        container.run_retention_days = settings.run_retention_days
        container.prune_min_interval_seconds = settings.prune_min_interval_seconds
        # P0-2 权限档位：由 Settings 注入（非法值已在 sandbox_mode_resolved 回退 + 告警）。
        container.policy.sandbox_mode = settings.sandbox_mode_resolved
        if settings.approval_tool_list:
            container.policy.approval_tools = set(settings.approval_tool_list)
        # P0-2 沙箱强制：**仅在探测到真实后端时**把 shell 纳入沙箱工具集——passthrough
        # 平台保持零行为变更，不制造「命令已在沙箱里跑」的假象（诚实立场见 CLAUDE.md）。
        # 授权由 create_run_context 与策略同源写入 metadata，故不会出现「策略要求沙箱却
        # 未授权」导致 shell 全线被拒的整类故障。
        if settings.sandbox_enforce and command_runner is not None:
            container.policy.sandbox_tools.add("shell")
            tier = getattr(getattr(command_runner, "tier", None), "value", None)
            if not settings.sandbox_network and tier != "firejail":
                logger.info(
                    "SANDBOX_NETWORK=false but backend %r cannot restrict outbound traffic; "
                    "network isolation is NOT in effect",
                    backend,
                )
        # hooks 是用户自配置的本地命令：默认**不**加载（HOOKS_ENABLED=false），防不可信
        # 仓库投放的 .heagent/hooks.json 在 clone 后自动执行；路径按 workspace_root 解析
        # （缺省回退 CWD）。文件存在但未开启时告警，避免「配置了却不生效」的静默失效。
        hooks_path = Path(workspace_root or ".") / ".heagent" / "hooks.json"
        if settings.hooks_enabled:
            container.hooks = HookManager.load(hooks_path)
        elif hooks_path.exists():
            logger.warning("%s found but HOOKS_ENABLED is false; not loading (opt in via .env)", hooks_path)
        if workspace_root and not container.policy.workspace_root:
            container.policy.workspace_root = workspace_root
        return container

    def create_run_context(
        self,
        *,
        session_id: str | None = None,
        parent_run_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        workspace_root: str | None = None,
    ) -> RunContext:
        root: str | None = workspace_root
        if root is None:
            root = self.workspace_root
        if root is None:
            root = self.policy.workspace_root
        if root is None:
            root = str(Path.cwd().resolve())
        ctx = RunContext(
            session_id=session_id,
            parent_run_id=parent_run_id,
            workspace_root=root,
            metadata=dict(metadata or {}),
        )
        # P0-2：**仅在真实沙箱后端在位时**才自动授权（与 EngineContainer.default 的 enforce
        # 同条件）。后端缺席（passthrough）时不写该键——策略要求沙箱而无授权仍按既有
        # fail-safe 阻断，既不制造「已在沙箱里跑」的假象，也不放宽「未授权即拒绝」的契约。
        if self.executor.sandbox_runner is not None:
            sandboxed_tools = sorted(self.policy.sandbox_tools)
            if sandboxed_tools:
                ctx.metadata["sandboxed_tools"] = sandboxed_tools
        # FR-1（沙箱会话目录）：开关开启时解析 per-run 目录并写入 metadata，
        # 由 ToolExecutor.execute_in_sandbox bind 给后端（Firejail --private 根 /
        # WinJob 子进程 cwd）。目录根锚定 workspace_root 回退链（root，上方已解析：
        # 参数→container→policy→cwd）而非进程 cwd——目录落在 file 工具围栏内；
        # 目标路径在 try 外预推导，except 严禁二次 Path.cwd() 重建（POSIX cwd 消失时
        # 二次推导会抛新异常掩盖原始错误）。目录创建失败（权限/磁盘）→ 显性失败
        # （NFR-1），严禁静默降级为「无目录继续跑」。
        from heagent.tools.sandbox import sandbox_session_dir, sandbox_sessions_root

        if self._session_workspace_enabled():
            base = sandbox_sessions_root(Path(root))
            target = base / ctx.run_id
            try:
                ctx.metadata["sandbox_workspace"] = str(sandbox_session_dir(ctx.run_id, base=base))
            except OSError as exc:
                raise RuntimeError(
                    f"Failed to create sandbox session workspace {target} "
                    "(sandbox_session_workspace enabled; failing run start, no silent fallback)"
                ) from exc
        else:
            # 开关关闭：清除 caller 预含键——残留会使 executor 误 bind 过期目录。
            ctx.metadata.pop("sandbox_workspace", None)
        return ctx

    async def close_run(self, run_context: RunContext) -> None:
        """run 结束 teardown：清理该 run 的沙箱会话目录（保留/删除）。

        FR-4：正常结束路径（AgentLoop._persist_and_cache 调用）。crash 孤儿目录由
        ``housekeeping.prune_sandbox_dirs``（CLI/GUI 启动时，E40-D1）按保留期回收。
        会话非安全边界（须 OS 级沙箱兜底）。
        """
        from heagent.tools.sandbox import pop_session

        session = pop_session(run_context.run_id)
        if session is not None:
            await session.close(keep=self._session_keep_enabled())
