"""进程状态聚合的来源适配（``GET /api/status`` 的入口层实现）。

传输层只认注入的 :class:`~heagent.network.http_server.StatusSource` 契约；本模块是**唯一**能同时
看到运行服务、WS 中枢、listener 与配置面的地方，因此这些事实在这里聚合成协议模型
（``StatusResponse``）。网络层因此不必认识运行栈，依赖边界保持不变。

两处**晚绑定**（装配顺序决定，不是设计喜好）：

- ``HttpServer`` 先于 ``build_ws_servers`` 构造 ⇒ WS 计数与 listener 列表只能「先注入 source、后
  ``bind_status_source``」；
- listener 的**实际端口**（``port=0`` 或端口顺延时）只有绑定完成才知道 ⇒ ``status()`` 在请求时读
  ``server.port``，而不是在构造期抄下配置值。

通知中枢**全局一份**（同一实例挂在每个 listener 上）：计数必须取那一份，按 listener 逐个相加会
把同一批连接重复计。
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from heagent.cron.jobs import JobStore
from heagent.memory.facts import FactStore
from heagent.network.http_protocol import (
    CronJobInfo,
    ErrorCodeCount,
    ListenerInfo,
    ListenerMode,
    RequestMetricsSummary,
    RoutingPoolInfo,
    RunStatusCounts,
    StatusResponse,
    TlsIdentityInfo,
    WsConnectionCounts,
)
from heagent.network.proc_stats import read_process_stats
from heagent.network.tls_identity import TlsIdentityError, certificate_info
from heagent.pub.safe_logging import safe_log
from heagent.pub.workspace import WorkspacePaths
from heagent.skills.skill_store import SkillStore, default_skill_roots

logger = logging.getLogger("heagent.cli.http_status")


def _parse_iso(value: object) -> datetime | None:
    """把落盘的 ISO 时间戳解析成**带时区**的 ``datetime``；缺失或非法一律 ``None``（不猜时间）。

    ``cron/jobs.py`` 落盘的 ``last_run`` 是 ``strftime("%Y-%m-%dT%H:%M:%S")``——**naive 的 UTC**。
    直接原样下发会让客户端按本地时解释（CST 下差 8 小时），所以这里按仓库既有约定
    （``cron/status.py``：naive 时间戳即 UTC）补上 UTC 时区。
    """
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip())
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed


if TYPE_CHECKING:
    from collections.abc import Sequence

    from heagent.config import Settings
    from heagent.network.http_server import HttpRunService

# 后台任务计数的读取窗口：注册表只为**终态**条目设保留上限（默认 32 条），在途条目是个位数，
# 取一个明显大于两者之和的窗口 ⇒ 计数即整表。窗口满了只会少算多出来的那些，不会让端点失败。
_BACKGROUND_TASK_WINDOW = 256

# 协议字段的字符/条数上限（与 ``http_protocol`` 的模型同界）。状态面是**展示用途**：超长或超量
# 就截断/取前 N 条，绝不因为一条异常配置把整条响应变成 500。
_MAX_HOST_CHARS = 255
_MAX_BACKEND_CHARS = 32
_MAX_PROVIDER_CHARS = 64
_MAX_POOL_NAME_CHARS = 64
_MAX_TIER_CHARS = 64
_MAX_TIERS = 64
_MAX_CRON_JOBS = 32
_MAX_CRON_TEXT = 128
_MAX_JOB_ID = 64
_MAX_STATUS_CHARS = 32
# 依赖态（cron 作业表 / 技能数 / 记忆条数）读的是**盘上文件**：状态面每被轮询一次就读一次盘是
# 不可接受的，故在来源侧缓存 ``_DEPENDENCY_CACHE_SECONDS``；端点本身仍然只读内存。
_DEPENDENCY_CACHE_SECONDS = 5.0


def _clip(value: object, limit: int) -> str:
    """把任意配置值收敛成不超过协议上限的字符串（``None`` → 空串）。"""
    return str(value or "")[:limit]


def _connection_count(hub: Any | None) -> int:
    """中枢当前的连接数；未注册（``None``）即 0。"""
    return 0 if hub is None else int(hub.connection_count)


def _notification_hub_of(servers: Sequence[Any]) -> Any | None:
    """取第一个 listener 上挂着的通知中枢（同一实例按设计挂在每个 listener 上）。"""
    for server in servers:
        hub = getattr(server, "notification_hub", None)
        if hub is not None:
            return hub
    return None


def _provider_name(provider: Any | None) -> str:
    """当前生效的 provider 条目名（可切换/组合 provider 暴露 ``active``）；取不到即空串。"""
    return _clip(getattr(provider, "active", None), _MAX_PROVIDER_CHARS)


def _effective_sandbox_backend(owner: Any | None) -> str | None:
    """本进程**实际生效**的沙箱档位（取自引擎构造期的 ``sandbox_decision``）。

    ``--sandbox`` / ``SANDBOX_BACKEND`` 只是**请求**档位：``auto`` 或 daemon 不可用时引擎会降级成
    ``passthrough``（``EngineContainer.default`` 在构造期就定下 ``effective_backend``）。状态面报
    请求值会让人以为命令跑在沙箱里，因此有决策时一律报生效档位；取不到（注入替身 / 未建引擎）时
    返回 ``None``，由调用点回落到请求值。
    """
    decision = getattr(getattr(owner, "engine", None), "sandbox_decision", None)
    return _clip(getattr(decision, "effective_backend", None), _MAX_BACKEND_CHARS) or None


def _deployment(
    settings: Settings,
    *,
    sandbox_backend: str | None = None,
    provider: Any | None = None,
) -> tuple[str, bool, str, list[RoutingPoolInfo]]:
    """装配期就能确定的部署标量：沙箱后端、写入闸门、生效 provider、路由池档位名。

    ``sandbox_backend`` 必须是**本进程实际使用的档位**（``--sandbox`` 是命令行覆盖，配置里可能仍是
    ``auto``）；``provider`` 同理取运行中的 provider 实例，而不是配置里钉的那个名字。

    池只取 ``tiers`` 的**键**（池内名，即 ``/model`` 接受的名字）：模型名与 ``base_url`` 属供应商
    细节，状态面不回答「档位指向谁」。所有字符串按协议上限截断——状态面宁可截断，也不能因为一条
    超长配置让整个端点 500。
    """
    pools = [
        RoutingPoolInfo(
            pool=_clip(name, _MAX_POOL_NAME_CHARS),
            tiers=[_clip(tier, _MAX_TIER_CHARS) for tier in list(spec.tiers)[:_MAX_TIERS]],
        )
        for name, spec in sorted(settings.routing_pool_map.items())
    ]
    backend = sandbox_backend or settings.sandbox_backend
    active = _provider_name(provider) or str(settings.active_provider or "")
    return (
        _clip(backend, _MAX_BACKEND_CHARS),
        bool(settings.http_console_write_enabled),
        _clip(active, _MAX_PROVIDER_CHARS),
        pools,
    )


class _TlsIdentityCache:
    """按「材料路径 + mtime」缓存证书身份：状态端点可能每 5 秒被轮询一次，不能每次都读盘并解析。

    失败同样入缓存（key 里的 mtime 缺失记 ``-1``）：材料不可读时只记**一次** WARNING，轮询不会把
    日志刷满；材料被换掉（mtime 变）或文件出现，key 随之变化 ⇒ 下一次请求自动重试。
    """

    def __init__(self) -> None:
        self._key: tuple[str, int] | None = None
        self._info: TlsIdentityInfo = TlsIdentityInfo()

    def info(self, cert_file: str) -> TlsIdentityInfo:
        """材料没换就复用上次读数；换了（或首次）才读盘解析。"""
        key = self._key_for(cert_file)
        if key != self._key:
            self._key, self._info = key, self._resolve(cert_file)
        return self._info

    @staticmethod
    def _key_for(cert_file: str) -> tuple[str, int]:
        try:
            return (cert_file, Path(cert_file).stat().st_mtime_ns)
        except OSError:
            return (cert_file, -1)

    @staticmethod
    def _resolve(cert_file: str) -> TlsIdentityInfo:
        """读一次身份；读不出来就降级为「未启用」，绝不把状态端点拖成 500。"""
        try:
            info = certificate_info(cert_file)
        except (TlsIdentityError, OSError) as exc:
            safe_log(
                logger,
                logging.WARNING,
                "status event=tls_identity_unreadable cert=%s error=%s",
                cert_file,
                exc,
            )
            return TlsIdentityInfo()
        return TlsIdentityInfo(
            enabled=True,
            spki_sha256=info.spki_sha256,
            short_fingerprint=info.short_fingerprint,
            not_after=info.not_after,
            san=info.san,
        )


def _listener_infos(
    http_server: Any | None, ws_servers: Sequence[Any], tls_cache: _TlsIdentityCache
) -> list[ListenerInfo]:
    """已装配 listener 的事实列表：http 在前，ws 按装配顺序（主 listener 是第一条）。

    端口读**运行中的** listener（``port=0`` / 端口顺延后配置值不等于真实值）；HTTP listener 在本
    产品里恒为明文（无 TLS 配置项），故其身份面恒为「未启用 + 四项 null」。WS 启用 TLS 时证书身份
    由 :mod:`heagent.network.tls_identity` 解析，读数过 ``tls_cache``（材料不变就不重复读盘）。
    """
    infos: list[ListenerInfo] = []
    if http_server is not None:
        config = http_server.config
        infos.append(
            ListenerInfo(
                kind="http",
                label="http",
                host=_clip(config.host, _MAX_HOST_CHARS),
                port=int(http_server.port),
                mode=ListenerMode(config.mode),
                tls=TlsIdentityInfo(),
            )
        )
    for index, server in enumerate(ws_servers):
        config = server.config
        # ``tls_enabled`` 本身就是「证书与私钥都配齐」的判定，故启用时证书路径必然存在。
        identity = tls_cache.info(str(config.tls_cert_file)) if config.tls_enabled else TlsIdentityInfo()
        infos.append(
            ListenerInfo(
                kind="ws",
                label="ws-primary" if index == 0 else "ws-external",
                host=_clip(config.host, _MAX_HOST_CHARS),
                port=int(server.port),
                mode=ListenerMode(config.mode),
                tls=identity,
            )
        )
    return infos


class HttpStatusSource:
    """把运行服务 / WS 中枢 / listener / 配置面聚合成 :class:`StatusResponse`。

    ``run_service`` 为 ``None`` 时（HTTP 只提供健康检查与静态页的形态）运行态报 0——没有运行服务
    就不可能有 run，也不可能挂着运行订阅连接，这是事实而不是缺项。
    """

    def __init__(
        self,
        *,
        version: str,
        max_inflight_runs: int,
        run_service: HttpRunService | None = None,
        task_registry: Any | None = None,
        settings: Settings | None = None,
        sandbox_backend: str | None = None,
        provider: Any | None = None,
        workspace_root: str | None = None,
    ) -> None:
        self._version = version
        self._max_inflight_runs = max_inflight_runs
        self._run_service = run_service
        self._task_registry = task_registry
        self._cli_hub: Any | None = None
        self._notification_hub: Any | None = None
        self._http_server: Any | None = None
        self._ws_servers: tuple[Any, ...] = ()
        self._workspace_root = workspace_root
        # TLS 身份面的读数缓存：状态端点被轮询，材料不变就不该重复读盘解析。
        self._tls_cache = _TlsIdentityCache()
        # provider 实例保留到运行期：``/provider`` 切换会改 ``SwitchableProvider.active``，装配期抄成
        # 字符串会让状态面板一直报启动时那个名字。
        self._provider = provider
        # 存储实例**只建一次**：``SkillStore`` 的「同名遮蔽」告警按实例去重，每次刷新新建一个
        # 会让全局根/项目根同名技能每 5 秒刷一批 WARNING。
        self._skills: Any | None = None
        self._facts: Any | None = None
        # 依赖态的 5 秒缓存：(取数时刻, 载荷)。``None`` = 还没读过。
        self._dependency_cache: tuple[float, tuple[list[CronJobInfo], int, int]] | None = None
        self._metrics: Any | None = None
        deployment = (
            _deployment(settings, sandbox_backend=sandbox_backend, provider=provider)
            if settings is not None
            else ("", False, "", [])
        )
        self._sandbox_backend, self._config_write_enabled, self._active_provider, self._routing_pools = deployment

    def bind_ws(
        self,
        servers: Sequence[Any] = (),
        *,
        cli_hub: Any | None = None,
        notification_hub: Any | None = None,
    ) -> None:
        """绑定 WS 侧来源（必须在 ``build_ws_servers`` 之后调用）。

        ``cli_hub`` 是 CLI 旁路中枢（旁路未启用 / 因 listener 身份被跳过时为 ``None``，
        两种情况对 status 等价）；通知中枢显式传入优先，否则取 listener 上那一份。
        """
        self._ws_servers = tuple(servers)
        self._cli_hub = cli_hub
        self._notification_hub = notification_hub if notification_hub is not None else _notification_hub_of(servers)

    def bind_listeners(self, http_server: Any | None = None) -> None:
        """绑定 HTTP listener（``None`` 表示本次进程没有装配它）。"""
        self._http_server = http_server

    def status(self) -> StatusResponse:
        """进程状态的只读快照（同步：只读内存计数；依赖态走 5 秒缓存，不在每次请求里读盘）。"""
        service = self._run_service
        dependency = self._dependency()
        resources = self._resources()
        return StatusResponse(
            version=self._version,
            active_runs=service.active_runs if service is not None else 0,
            # 没有运行服务就没有名额可谈（``/api/runs`` 也未注册）：报 0 而不是配置里的每项目上限。
            max_inflight_runs=self._max_inflight_runs if service is not None else 0,
            run_records=service.run_records if service is not None else 0,
            run_status=service.run_status_counts() if service is not None else RunStatusCounts(),
            ws_connections=WsConnectionCounts(
                runs=service.ws_connections if service is not None else 0,
                cli=_connection_count(self._cli_hub),
                notifications=_connection_count(self._notification_hub),
            ),
            background_tasks=self._background_tasks(),
            listeners=_listener_infos(self._http_server, self._ws_servers, self._tls_cache),
            sandbox_backend=self._sandbox_backend,
            config_write_enabled=self._config_write_enabled,
            active_provider=_provider_name(self._provider) or self._active_provider,
            routing_pools=list(self._routing_pools),
            started_at=self._started_at(),
            uptime_seconds=self._uptime_seconds(),
            cron_jobs=dependency[0],
            skill_count=dependency[1],
            memory_facts=dependency[2],
            **resources,
            requests=self._request_metrics(),
        )

    def attach_metrics(self, metrics: Any) -> None:
        """挂上 app 持有的请求计数载体（app 装配期调用；未挂上时计数全 0）。"""
        self._metrics = metrics

    def _request_metrics(self) -> RequestMetricsSummary:
        """本进程的请求计数与延迟快照（未挂载载体时全 0）。"""
        metrics = self._metrics
        if metrics is None:
            return RequestMetricsSummary()
        return RequestMetricsSummary(
            total=metrics.total,
            status_2xx=metrics.status_class("2xx"),
            status_3xx=metrics.status_class("3xx"),
            status_4xx=metrics.status_class("4xx"),
            status_5xx=metrics.status_class("5xx"),
            latency_p50_ms=metrics.latency_p50_ms(),
            latency_max_ms=metrics.latency_max_ms(),
            error_codes=[ErrorCodeCount(code=code, count=count) for code, count in metrics.error_codes()[:16]],
        )

    @staticmethod
    def _resources() -> dict[str, Any]:
        """本进程资源快照（不可得项为 ``None``，并标注采样通路）。"""
        stats = read_process_stats()
        return {
            "rss_bytes": stats.rss_bytes,
            "threads": stats.threads,
            "cpu_seconds": stats.cpu_seconds,
            "resource_source": stats.source,
        }

    def _started_at(self) -> datetime | None:
        """启动时刻（未启动 / 未绑定 listener 时为 ``None``）。"""
        return getattr(self._http_server, "started_at", None)

    def _uptime_seconds(self) -> float | None:
        """已运行秒数（未启动时为 ``None``——0 会被读成「刚启动」）。"""
        value = getattr(self._http_server, "uptime_seconds", None)
        return None if value is None else float(value)

    def _dependency(self) -> tuple[list[CronJobInfo], int, int]:
        """cron 作业 / 技能数 / 记忆条数（``_DEPENDENCY_CACHE_SECONDS`` 内复用同一份读数）。"""
        if self._workspace_root is None:
            return ([], 0, 0)
        now = time.monotonic()
        if self._dependency_cache is not None and now - self._dependency_cache[0] < _DEPENDENCY_CACHE_SECONDS:
            return self._dependency_cache[1]
        payload = self._read_dependency()
        self._dependency_cache = (now, payload)
        return payload

    def _read_dependency(self) -> tuple[list[CronJobInfo], int, int]:
        """读一次盘上的依赖态；任一项读失败只降级该项（状态面不该因为资产文件坏掉而 500）。"""
        root = self._workspace_root
        if root is None:  # pragma: no cover - _dependency 已提前返回
            return ([], 0, 0)
        paths = WorkspacePaths.from_root(root)
        return (self._cron_jobs(paths), self._skill_count(paths), self._memory_facts(paths))

    def _cron_jobs(self, paths: Any) -> list[CronJobInfo]:
        """服务进程工作区的 cron 作业定义与最近一次执行。

        只报**进程工作区**那一份 ``jobs.json``：网页入口不启动调度器，作业由交互模式 / GUI 的调度器
        执行，跨项目汇总属另一件事（见 epic 残差）。
        """
        try:
            jobs = JobStore(str(paths.cron_file)).list_jobs()
            # 先滤掉畸形条目（空 id / 空 cron 能被 ``JobStore`` 正常加载，但过不了协议模型的最小长度
            # 校验）再截断：反过来会让排在前面的坏条目吃掉容量，把后面的**正常**作业挤掉。
            valid = [job for job in jobs if str(job.id or "").strip() and str(job.cron or "").strip()]
            return [
                CronJobInfo(
                    job_id=_clip(job.id, _MAX_JOB_ID),
                    cron=_clip(job.cron, _MAX_CRON_TEXT),
                    last_run=_parse_iso(job.last_run),
                    last_status=_clip(job.last_status, _MAX_STATUS_CHARS),
                )
                for job in valid[:_MAX_CRON_JOBS]
            ]
        except Exception:  # noqa: BLE001 - 辅助信息：读失败降级为空列表并留 WARNING
            safe_log(logger, logging.WARNING, "status event=cron_read_failed root=%s", paths.root, exc_info=True)
            return []

    def _skill_count(self, paths: Any) -> int:
        """技能库条目数（同名技能按全局优先去重后计数）。"""
        try:
            if self._skills is None:
                self._skills = SkillStore(default_skill_roots(paths.root))
            return len(self._skills.list_skills())
        except Exception:  # noqa: BLE001 - 辅助信息：读失败降级为 0
            safe_log(logger, logging.WARNING, "status event=skill_count_failed root=%s", paths.root, exc_info=True)
            return 0

    def _memory_facts(self, paths: Any) -> int:
        """长期记忆条目数（``MEMORY.md`` 的 ``- `` 行数）。"""
        try:
            if self._facts is None:
                self._facts = FactStore(str(paths.memory_file))
            return len(self._facts.load())
        except Exception:  # noqa: BLE001 - 辅助信息：读失败降级为 0
            safe_log(logger, logging.WARNING, "status event=memory_count_failed root=%s", paths.root, exc_info=True)
            return 0

    def _background_tasks(self) -> int:
        """后台任务注册表里当前可见的条目数（注册表未注入即 0）。"""
        if self._task_registry is None:
            return 0
        return len(self._task_registry.snapshot(limit=_BACKGROUND_TASK_WINDOW))


def build_status_source(
    *,
    version: str,
    max_inflight_runs: int,
    run_service: HttpRunService | None,
    task_registry: Any | None,
    settings: Settings | None,
    sandbox_backend: str | None = None,
    provider: Any | None = None,
    workspace_root: str | None = None,
    enabled: bool,
) -> HttpStatusSource | None:
    """按「HTTP listener 是否启用」构造状态来源；未启用即 ``None``（路由随之不注册）。

    判定与构造放在同一次调用里：调用方因此不必再写分支——``cli/http.py`` 的两个入口函数已在
    复杂度上限边缘，多一个 ``if`` 就会撞 C901。
    """
    if not enabled:
        return None
    return HttpStatusSource(
        version=version,
        max_inflight_runs=max_inflight_runs,
        run_service=run_service,
        task_registry=task_registry,
        settings=settings,
        sandbox_backend=sandbox_backend,
        provider=provider,
        workspace_root=workspace_root,
    )


def bind_status_source(
    source: HttpStatusSource | None,
    servers: Sequence[Any] = (),
    *,
    http_server: Any | None = None,
    cli_hub: Any | None = None,
    notification_hub: Any | None = None,
) -> None:
    """把 listener 与 WS 侧来源绑到状态来源上（``None`` 来源即空操作）。

    必须在 ``HttpServer`` 与 ``build_ws_servers`` **之后**调用：注入的是同一个 source 对象，
    因此晚绑定对已经构造好的 app 同样可见。
    """
    if source is None:
        return
    source.bind_listeners(http_server)
    source.bind_ws(servers, cli_hub=cli_hub, notification_hub=notification_hub)


__all__ = ["HttpStatusSource", "bind_status_source", "build_status_source"]
