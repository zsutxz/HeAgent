"""WS 项目通道的入口层适配器：把网页控制台的项目面翻译成 WS 帧模型（Epic 75）。

职责边界 = **只翻译**。``ProjectChannelService`` 的三个方法分别做「投影成帧」「提交并收窄」
「前置校验」，判断全部留在控制台（``cli/http_console.py``）与注册表（``pub/projects.py``）：
本模块不解析项目目录、不探测目录是否在盘上、不读注册表文件——「传输层与适配器都不认识项目
目录」因此是结构保证，而不是纪律要求。

错误码纪律：``ConsoleOperationError.code`` 与 ``ProjectRegistryError.code`` **逐字**搬进
``HttpRunConflictError``，不改写、不折叠。未登记进 ``HttpErrorCode`` 的码让 ``ValueError``
直接冒出（漏译必须显性），连接骨架随后把它收敛成 ``server_error``。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

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
            registry_state=self._registry_health(),
        )

    async def start_project_run(self, project_id: str, prompt: str) -> SubmittedRun:
        """提交到该项目，把结果收窄成 ``SubmittedRun``（``session_id`` 不出入口层）。"""
        try:
            response = await self._console.start_project_run(project_id, ProjectRunRequest(prompt=prompt))
        except (ConsoleOperationError, ProjectRegistryError) as exc:
            raise _conflict(exc) from exc
        return SubmittedRun(run_id=response.run_id, status=response.status)

    async def ensure_available(self, project_id: str) -> str:
        """提交前置校验：借控制台的解析读径，成功时原样返回 ``project_id``。

        控制台的 ``get_project_config`` 是 ``ConsoleHandler`` 端口上唯一的**纯读解析**方法
        （解析项目运行时后只读配置，不建 run、不占名额、不写注册表）⇒ ``unknown_project`` /
        ``project_unavailable`` 的判据仍只有控制台一份，适配器不复制「id 在不在表里 / 目录还在
        不在」这类判断。
        """
        try:
            await self._console.get_project_config(project_id)
        except (ConsoleOperationError, ProjectRegistryError) as exc:
            raise _conflict(exc) from exc
        return project_id
