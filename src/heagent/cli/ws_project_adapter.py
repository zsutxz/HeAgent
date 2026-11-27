"""WS 项目通道的入口层适配器：把网页控制台的项目面翻译成 WS 帧模型（Epic 75）。

职责边界 = **只翻译**。``ProjectChannelService`` 的三个方法分别做「投影成帧」「提交并收窄」
「前置校验」，判断全部留在控制台（``cli/http_console.py``）与注册表（``pub/projects.py``）——
本模块不解析项目目录、不探测目录是否在盘上、不读注册表文件，「传输层与适配器都不认识项目目录」
因此是结构保证，而不是纪律要求。

错误码纪律：``ConsoleOperationError.code`` 与 ``ProjectRegistryError.code`` **逐字**搬进
``HttpRunConflictError``，不改写、不折叠。未登记进 ``HttpErrorCode`` 的码让 ``ValueError``
直接冒出（漏译必须显性），连接骨架随后把它收敛成 ``server_error``。

幂等表（Epic 77 D1）住 `cli/ws_submission_cache.py`：本模块只负责在提交前后调它
（在途合流 / 成功重放 / 失败移出），窗口语义与有界内存都在那边单点实现。

端口超时（「超时是实现方义务」的承兑处）：端口签名不带 ``timeout``（契约钉死），上界住构造期
``submit_timeout``（默认 30s），控制台调用经 ``wait_for`` 兜底，超时映射具名 ``timeout`` 码。

注册表健康守卫：注册表读不出/解析不了时**提交径 fail-loud** 回 ``project_registry_unreadable``
——注册表的读路径是 fail-soft（不可读 ⇒ 空表），若不在这里先判，「注册表坏了」会在下游被译成
``unknown_project``，客户端会把「服务端坏了、重试无用」误读成「这个项目不存在、换个 id 试试」。
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Final, Literal, TypeVar

from heagent.cli.ws_submission_cache import SubmissionCache, SubmissionKey
from heagent.network.http_console_protocol import ConsoleOperationError, ProjectRunRequest
from heagent.network.http_protocol import HttpErrorCode, HttpRunConflictError
from heagent.network.ws_protocol import ProjectChannelEntry, SubmittedRun, WsProjectsFrame
from heagent.pub.projects import ProjectRegistryError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from heagent.network.http_console_protocol import ConsoleHandler

# ``WsProjectsFrame.registry_state`` 的两值集合：注入的探针与帧字段必须同型。
RegistryState = Literal["ok", "unreadable"]

# 「超时是实现方义务」的本实现方默认上界（秒）；提交链含配置求解，给足余量；测试注入小值。
DEFAULT_SUBMIT_TIMEOUT_SECONDS: Final[float] = 30.0

_ResultT = TypeVar("_ResultT")


def _conflict(error: ConsoleOperationError | ProjectRegistryError) -> HttpRunConflictError:
    """入口层 / 注册表的稳定码 → 传输层冲突异常（``code`` 逐字搬运）。"""
    return HttpRunConflictError(str(error), code=HttpErrorCode(error.code))


class ProjectChannelAdapter:
    """``ProjectChannelService`` 的入口层实现；一个实例注入同一条 listener 的两个端点。"""

    def __init__(
        self,
        console: ConsoleHandler,
        registry_health: Callable[[], RegistryState],
        *,
        submit_timeout: float = DEFAULT_SUBMIT_TIMEOUT_SECONDS,
    ) -> None:
        self._console = console
        self._registry_health = registry_health
        self._submit_timeout = submit_timeout
        self._submissions = SubmissionCache()

    async def list_projects(self) -> WsProjectsFrame:
        """项目列表 → 帧：每条只留恰三键、顺序沿用控制台给定顺序；宿主目录字段一律不出入口层。"""
        listing = await self._console.list_projects()
        return WsProjectsFrame(
            projects=[
                ProjectChannelEntry(id=item.id, name=item.name, available=item.available) for item in listing.projects
            ],
            registry_state=await self._health(),
        )

    async def _health(self) -> RegistryState:
        """探针读盘**不占事件循环**：注入的探针是同步读盘调用，走线程池。"""
        return await asyncio.to_thread(self._registry_health)

    async def _guard_registry(self, project_id: str) -> None:
        """注册表不可读 ⇒ 提交径 fail-loud 回 ``project_registry_unreadable``；``default`` 豁免（理由见模块 docstring）。"""
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
        """提交并收窄成 ``SubmittedRun``（``session_id`` 不出入口层）。带键时窗口内只真正提交一次：
        owner 写 ``Future``，合流者经 ``asyncio.shield`` 等同一结果（挡取消连坐）；失败先交异常再移出
        窗口，owner 被取消则连坐取消；**键不含 prompt**，同键不同 prompt 静默重放第一次结果。
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
            # owner 被取消 ≠ 提交失败：合流者也不该拿到假结果，一律取消并放掉窗口。
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

    async def _bounded(self, call: Awaitable[_ResultT], *, what: str, outcome_unknown: bool = False) -> _ResultT:
        """把一次控制台调用包在构造期上界里；**超时只由本方法判定**（A77）。

        用 ``asyncio.wait`` 而不是 ``wait_for``：``wait_for`` 自己的超时与内层代码自抛的超时都是
        内置 ``TimeoutError``，两者不可区分 ⇒ 「控制台里的 HTTP 客户端超时」会被重写成这里
        30s 的话术，排障时会去查一个根本没生效的上界。``wait`` 只回答「任务在期限内结束了吗」：
        pending 才是本方法的时间到；done 就用 ``task.result()`` 把内层异常**原样**抛出去（含
        ``TimeoutError``，由连接骨架收敛成 ``server_error``——与本模块「不认识的异常不漏译」
        同一立场，不替控制台编造一个码）。
        """
        task: asyncio.Task[_ResultT] = asyncio.ensure_future(call)
        try:
            _, pending = await asyncio.wait({task}, timeout=self._submit_timeout)
        except asyncio.CancelledError:
            # 外层（连接 / 合流者）被取消：连内层一起取消，不留孤儿提交任务。
            task.cancel()
            raise
        if not pending:
            return task.result()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        detail = "; outcome unknown" if outcome_unknown else ""
        raise HttpRunConflictError(
            f"{what} did not complete within {self._submit_timeout:g}s{detail}",
            code=HttpErrorCode.TIMEOUT,
        )

    async def _submit(self, project_id: str, prompt: str) -> SubmittedRun:
        """一次**真实**提交（幂等窗口之外的那一半）：健康守卫 + 上界兜底的控制台调用 + 收窄。"""
        await self._guard_registry(project_id)
        try:
            response = await self._bounded(
                self._console.start_project_run(project_id, ProjectRunRequest(prompt=prompt)),
                what="the project run submission",
                outcome_unknown=True,
            )
        except (ConsoleOperationError, ProjectRegistryError) as exc:
            raise _conflict(exc) from exc
        return SubmittedRun(run_id=response.run_id, status=response.status)

    async def ensure_available(self, project_id: str) -> str:
        """提交前置校验：借控制台的轻量探测（在表 + 目录在盘，不求解配置）判可提交性。
        判据仍只有控制台一份，适配器不复制「id 在不在表里 / 目录还在不在」；上界同 ``_submit``。
        """
        await self._guard_registry(project_id)
        try:
            await self._bounded(self._console.check_project(project_id), what="the project availability probe")
        except (ConsoleOperationError, ProjectRegistryError) as exc:
            raise _conflict(exc) from exc
        return project_id
