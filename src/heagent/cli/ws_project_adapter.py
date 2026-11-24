"""WS 项目通道的入口层适配器：把网页控制台的项目面翻译成 WS 帧模型（Epic 75）。

职责边界 = **只翻译**。``ProjectChannelService`` 的三个方法分别做「投影成帧」「提交并收窄」
「前置校验」，判断全部留在控制台（``cli/http_console.py``）与注册表（``pub/projects.py``）：
本模块不解析项目目录、不探测目录是否在盘上、不读注册表文件——「传输层与适配器都不认识项目
目录」因此是结构保证，而不是纪律要求。

错误码纪律：``ConsoleOperationError.code`` 与 ``ProjectRegistryError.code`` **逐字**搬进
``HttpRunConflictError``，不改写、不折叠。未登记进 ``HttpErrorCode`` 的码让 ``ValueError``
直接冒出（漏译必须显性），连接骨架随后把它收敛成 ``server_error``。

幂等表（Epic 77 D1）住 `cli/ws_submission_cache.py`：本模块只负责在提交前后调它
（在途合流 / 成功重放 / 失败移出），窗口语义与有界内存都在那边单点实现。

注册表健康守卫：注册表读不出/解析不了时**提交径 fail-loud** 回 ``project_registry_unreadable``
——注册表的读路径是 fail-soft（不可读 ⇒ 空表），若不在这里先判，「注册表坏了」会在下游被译成
``unknown_project``，客户端会把「服务端坏了、重试无用」误读成「这个项目不存在、换个 id 试试」。
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Literal

from heagent.cli.ws_submission_cache import SubmissionCache, SubmissionKey
from heagent.network.http_console_protocol import ConsoleOperationError, ProjectRunRequest
from heagent.network.http_protocol import HttpErrorCode, HttpRunConflictError
from heagent.network.ws_protocol import ProjectChannelEntry, SubmittedRun, WsProjectsFrame
from heagent.pub.projects import ProjectRegistryError

if TYPE_CHECKING:
    from collections.abc import Callable

    from heagent.network.http_console_protocol import ConsoleHandler

# ``WsProjectsFrame.registry_state`` 的两值集合：注入的探针与帧字段必须同型。
RegistryState = Literal["ok", "unreadable"]


def _conflict(error: ConsoleOperationError | ProjectRegistryError) -> HttpRunConflictError:
    """入口层 / 注册表的稳定码 → 传输层冲突异常（``code`` 逐字搬运）。"""
    return HttpRunConflictError(str(error), code=HttpErrorCode(error.code))


class ProjectChannelAdapter:
    """``ProjectChannelService`` 的入口层实现；一个实例注入同一条 listener 的两个端点。"""

    def __init__(self, console: ConsoleHandler, registry_health: Callable[[], RegistryState]) -> None:
        self._console = console
        self._registry_health = registry_health
        self._submissions = SubmissionCache()

    async def list_projects(self) -> WsProjectsFrame:
        """项目列表 → 帧：每条只留客户端用得上的三项，顺序沿用控制台给定顺序。

        ``path`` / ``last_opened_at`` / ``is_default`` 一律不出入口层：远程客户端不靠它们决策，
        而它们会把宿主目录结构暴露给任何持 token 的对端。
        """
        listing = await self._console.list_projects()
        return WsProjectsFrame(
            projects=[
                ProjectChannelEntry(id=item.id, name=item.name, available=item.available) for item in listing.projects
            ],
            registry_state=await self._health(),
        )

    async def _health(self) -> RegistryState:
        """探针读盘**不占事件循环**：注入的探针是同步读盘调用，与 ``list_projects`` 同档走线程池。"""
        return await asyncio.to_thread(self._registry_health)

    async def _guard_registry(self, project_id: str) -> None:
        """注册表不可读 ⇒ 提交径立即失败，**不**退化成 ``unknown_project``。

        注册表读路径是 fail-soft（不可读 ⇒ 空表），照原样走下去「服务端坏了」会变成「这个项目不存在」：
        客户端重试只会一直拿到同一个误导性的码。列表径不受影响——那里能自报 ``registry_state``。

        ``default`` 豁免：它由注册表句柄的启动工作区**直接合成**、完全不读注册表（``find("default")``
        短路），注册表坏了也照样能跑。把默认项目一起拒掉，等于让「登记表被改坏」升级为「服务不可用」。
        """
        if project_id == "default":
            return
        if await self._health() != "ok":
            raise HttpRunConflictError(
                "the project registry is unreadable",
                code=HttpErrorCode.PROJECT_REGISTRY_UNREADABLE,
            )

    async def start_project_run(
        self,
        project_id: str,
        prompt: str,
        request_id: str | None = None,
    ) -> SubmittedRun:
        """提交到该项目，把结果收窄成 ``SubmittedRun``（``session_id`` 不出入口层）。

        ``request_id`` 缺省 = 每次都是新提交（旧帧逐字等价）。带键时窗口内只真正提交一次：owner 走
        :meth:`_submit` 把结果写进 ``Future``，合流者经 ``asyncio.shield`` 等同一个结果。shield 挡的是
        「一个合流者的取消连坐兄弟合流者」（``InvalidStateError`` 由下方 ``future.done()`` 守卫挡掉，实测
        去掉 shield 是兄弟收 ``CancelledError``）；失败先交异常再移出窗口，owner 被取消则连坐取消。
        **键不含 prompt**：同键不同 prompt 静默重放第一次结果——键是客户端的不透明承诺，服务端不比对载荷。
        """
        if request_id is None:
            return await self._submit(project_id, prompt)
        key: SubmissionKey = (project_id, request_id)
        future, owner = self._submissions.reserve(key)
        if not owner:
            return await asyncio.shield(future)
        try:
            result = await self._submit(project_id, prompt)
        except asyncio.CancelledError:
            # owner 被取消 ≠ 提交失败：合流者也不该拿到一个假结果，一律取消并放掉窗口。
            self._submissions.drop(key, reason="cancelled")
            future.cancel()
            raise
        except Exception as exc:
            self._submissions.drop(key, reason="failed")
            future.set_exception(exc)
            # 没有合流者时也标记「已取回」，避免 "Future exception was never retrieved" 噪声。
            future.exception()
            raise
        if not future.done():
            future.set_result(result)
        return result

    async def _submit(self, project_id: str, prompt: str) -> SubmittedRun:
        """一次**真实**提交（幂等窗口之外的那一半）：健康守卫 + 控制台调用 + 收窄。"""
        await self._guard_registry(project_id)
        try:
            response = await self._console.start_project_run(project_id, ProjectRunRequest(prompt=prompt))
        except (ConsoleOperationError, ProjectRegistryError) as exc:
            raise _conflict(exc) from exc
        return SubmittedRun(run_id=response.run_id, status=response.status)

    async def ensure_available(self, project_id: str) -> str:
        """提交前置校验：借控制台的轻量探测读径，成功时原样返回 ``project_id``。

        控制台的 ``check_project`` 是 ``ConsoleHandler`` 端口上专门的**提交前置探测**（只做
        「在表 + 目录在盘」判定，不求解配置、不构建运行时）⇒ ``unknown_project`` /
        ``project_unavailable`` 的判据仍只有控制台一份，适配器不复制「id 在不在表里 / 目录还在
        不在」这类判断，同时全量配置求解也不落在提交热路径上。
        """
        await self._guard_registry(project_id)
        try:
            await self._console.check_project(project_id)
        except (ConsoleOperationError, ProjectRegistryError) as exc:
            raise _conflict(exc) from exc
        return project_id
