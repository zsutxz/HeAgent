"""控制台端点装配：项目 / 会话 / 配置 / 原生目录选择（Story 62.1 自 ``network/http_server.py`` 拆出）。

网络层在这里只做三件事：**校验会话 id 形态**（非法即 ``invalid_session_id``）、把不透明 id 交给
注入的 console、把稳定错误码映射为状态码；分组、来源求解、白名单、保真写、备份与审计一律留在
入口层（脊柱 I1：网络层不认识项目与配置）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from heagent.network.exposure import is_loopback_host
from heagent.network.http_console_protocol import (
    ConfigWriteRequest,
    ProjectRegisterRequest,
    ProjectRenameRequest,
    ProjectRunRequest,
    SessionCreateRequest,
    SessionRenameRequest,
    is_valid_session_id,
)
from heagent.network.http_protocol import HttpErrorCode

from .pipeline import _console_error_response, _json_error, _read_model

if TYPE_CHECKING:
    from heagent.network.http_console_protocol import ConsoleHandler

    from .config import HttpServerConfig


def _project_source(request: Any) -> str:
    """路径里的项目 id（不透明字符串；缺失/未知由注入的 console 判为 ``unknown_project``）。"""
    return str(request.path_params.get("project_id", ""))


def _loopback_error(responses: Any, request: Any) -> Any | None:
    """**写类**操作要求本机回环来源；非回环 → 403 ``loopback_required``（脊柱 §9）。

    判定复用 ``network.exposure.is_loopback_host``（含 IPv4 映射形式 ``::ffff:127.0.0.1``）。
    这是 defense-in-depth 而**不是认证**：能连上回环端口的本机进程可以伪造请求头。

    适用面：项目登记 / 移除（Story 50-2）与**配置写入**（Story 50-5 流水线第 2 步——那一步
    留在传输层，因为网络层不认识 ``Settings``，见 ``heagent.config.write`` 的模块 docstring）。
    **重命名无回环门**——framework.md「已知缺口」有裁定维持现状，勿据旧文补门。
    """
    client = getattr(request, "client", None)
    host = getattr(client, "host", "") if client is not None else ""
    if is_loopback_host(str(host)):
        return None
    return _json_error(
        responses,
        HttpErrorCode.LOOPBACK_REQUIRED,
        "this change requires a loopback client",
        status_code=403,
    )


def _confirm_required(responses: Any, request: Any, *, action: str) -> Any | None:
    """危险操作的服务端确认闸门（缺 ``?confirm=true`` → 400 ``confirm_required``）。

    确认放在**服务端**而不只靠 UI：项目移除与会话删除都走这里，缺一即拒（story 50-2 AC6 /
    50-3 AC6 同一口径）。
    """
    if request.query_params.get("confirm") == "true":
        return None
    return _json_error(
        responses,
        HttpErrorCode.CONFIRM_REQUIRED,
        f"{action} requires confirm=true",
        status_code=400,
    )


def _build_project_endpoints(  # noqa: C901 - 四个端点闭包共享同一套分支
    responses: Any, console: ConsoleHandler, config: HttpServerConfig
) -> tuple[Any, ...]:
    """项目注册表的四条路由（Story 50-2），全部围绕注入的入口层 handler 构造。"""

    async def list_projects(request: Any) -> Any:  # noqa: ARG001
        try:
            result = await console.list_projects()
        except Exception as exc:
            return _console_error_response(responses, exc, event="project_list_failed")
        return responses.JSONResponse(result.model_dump(mode="json"))

    async def register_project(request: Any) -> Any:
        denied = _loopback_error(responses, request)
        if denied is not None:
            return denied
        parsed, error = await _read_model(request, model=ProjectRegisterRequest, config=config, responses=responses)
        if error is not None:
            return error
        try:
            result = await console.register_project(parsed)
        except Exception as exc:
            return _console_error_response(responses, exc, event="project_register_failed")
        return responses.JSONResponse(result.model_dump(mode="json"), status_code=201)

    async def rename_project(request: Any) -> Any:
        parsed, error = await _read_model(request, model=ProjectRenameRequest, config=config, responses=responses)
        if error is not None:
            return error
        try:
            result = await console.rename_project(_project_source(request), parsed)
        except Exception as exc:
            return _console_error_response(responses, exc, event="project_rename_failed")
        return responses.JSONResponse(result.model_dump(mode="json"))

    async def remove_project(request: Any) -> Any:
        project_id = _project_source(request)
        denied = _confirm_required(responses, request, action="project removal")
        if denied is not None:
            return denied
        if project_id != "default":
            denied = _loopback_error(responses, request)
            if denied is not None:
                return denied
        try:
            if project_id != "default" and await console.project_has_inflight_run(project_id):
                return _json_error(
                    responses,
                    HttpErrorCode.PROJECT_BUSY,
                    "project has a run in progress",
                    status_code=409,
                )
            await console.remove_project(project_id)
        except Exception as exc:
            return _console_error_response(responses, exc, event="project_remove_failed")
        return responses.Response(status_code=204)

    return list_projects, register_project, rename_project, remove_project


def _build_session_endpoints(  # noqa: C901 - 六个端点闭包共享同一套分支
    responses: Any, console: ConsoleHandler, config: HttpServerConfig
) -> tuple[Any, ...]:
    """会话 API 与项目内运行入口（Story 50-3）：五条会话路由 + 一条运行入口。

    网络层在这里只做三件事：**校验会话 id 形态**（非法即回 ``invalid_session_id``，不触碰文件
    系统）、把不透明 id 交给注入的 console、把稳定码映射为状态码。会话 JSON 的解析、标题派生、
    在途判定与项目路径解析一律在入口层（脊柱 I1 的「网络层不认识项目」）。
    """

    def session_source(request: Any) -> tuple[str, Any | None]:
        """路径里的会话 id（已过形态校验；错误路径回 ``("", error)``，调用方必须先短路 error）。

        形态校验放在**网络层**（非法即 ``invalid_session_id``，且**不触碰文件系统**）；入口层还有第二道
        同样的守卫（``cli.http._guarded_session_id``），两点各自 fail-closed。
        """
        session_id = str(request.path_params.get("session_id", ""))
        if not is_valid_session_id(session_id):
            return "", _json_error(
                responses,
                HttpErrorCode.INVALID_SESSION_ID,
                "session id is invalid",
                status_code=400,
            )
        return session_id, None

    async def list_sessions(request: Any) -> Any:
        try:
            result = await console.list_sessions(_project_source(request))
        except Exception as exc:
            return _console_error_response(responses, exc, event="session_list_failed")
        return responses.JSONResponse(result.model_dump(mode="json"))

    async def create_session(request: Any) -> Any:
        parsed, error = await _read_model(request, model=SessionCreateRequest, config=config, responses=responses)
        if error is not None:
            return error
        try:
            result = await console.create_session(_project_source(request), parsed)
        except Exception as exc:
            return _console_error_response(responses, exc, event="session_create_failed")
        return responses.JSONResponse(result.model_dump(mode="json"), status_code=201)

    async def get_session(request: Any) -> Any:
        session_id, error = session_source(request)
        if error is not None:
            return error
        try:
            result = await console.get_session(_project_source(request), session_id)
        except Exception as exc:
            return _console_error_response(responses, exc, event="session_read_failed")
        return responses.JSONResponse(result.model_dump(mode="json"))

    async def rename_session(request: Any) -> Any:
        session_id, error = session_source(request)
        if error is not None:
            return error
        parsed, error = await _read_model(request, model=SessionRenameRequest, config=config, responses=responses)
        if error is not None:
            return error
        try:
            result = await console.rename_session(_project_source(request), session_id, parsed)
        except Exception as exc:
            return _console_error_response(responses, exc, event="session_rename_failed")
        return responses.JSONResponse(result.model_dump(mode="json"))

    async def delete_session(request: Any) -> Any:
        """删除会话：危险操作，确认由**服务端**把关（与会话 / 项目删除同一口径）。"""
        session_id, error = session_source(request)
        if error is not None:
            return error
        denied = _confirm_required(responses, request, action="session removal")
        if denied is not None:
            return denied
        try:
            await console.delete_session(_project_source(request), session_id)
        except Exception as exc:
            return _console_error_response(responses, exc, event="session_delete_failed")
        return responses.Response(status_code=204)

    async def create_project_run(request: Any) -> Any:
        """``POST /api/projects/{id}/runs``：项目内运行，``run_id`` 复用既有 SSE/取消端点。"""
        parsed, error = await _read_model(
            request,
            model=ProjectRunRequest,
            config=config,
            responses=responses,
            blank_code=HttpErrorCode.EMPTY_PROMPT,
        )
        if error is not None:
            return error
        try:
            result = await console.start_project_run(_project_source(request), parsed)
        except Exception as exc:
            return _console_error_response(responses, exc, event="project_run_failed")
        return responses.JSONResponse(result.model_dump(mode="json"), status_code=201)

    async def session_malformed(request: Any) -> Any:  # noqa: ARG001 - 端点的固定签名
        """会话路径下多出来的段 ⇒ 会话 id 必然非法（AC7：拒绝且不触碰 console / 文件系统）。

        必须存在这条兜底路由：``%2F`` 会在**路由之前**被解码成 ``/``，于是 ``sessions/..%2Fescape``
        落成 5 段路径——不兜底就回 404 ``not_found``，与 AC7 承诺的稳定码 ``invalid_session_id`` 不符
        （且把「路由存不存在」的差异暴露给客户端）。注册顺序在具体会话路由**之后**，因此绝不会遮蔽
        正常的单段 id。
        """
        return _json_error(responses, HttpErrorCode.INVALID_SESSION_ID, "session id is invalid", status_code=400)

    return (
        list_sessions,
        create_session,
        get_session,
        rename_session,
        delete_session,
        create_project_run,
        session_malformed,
    )


def _build_config_endpoint(responses: Any, console: ConsoleHandler, config: HttpServerConfig) -> tuple[Any, Any]:
    """配置面板的两条路由（``GET`` 只读 / ``PUT`` 写入；Story 50-4 + 50-5）。

    网络层只把不透明的项目 id 与协议模型交给注入的 console，并把稳定错误码映射为状态码；分组、
    来源求解、白名单、保真写、备份与审计一律留在入口层与顶层模块（脊柱 I1：网络层不认识配置）。

    ``PUT`` 另外要求本机回环来源（流水线第 2 步；非回环时**不触碰** console ⇒ 文件 / 备份 / 审计
    三者都不会变，AC10）。
    """

    async def get_project_config(request: Any) -> Any:
        try:
            result = await console.get_project_config(_project_source(request))
        except Exception as exc:
            return _console_error_response(responses, exc, event="project_config_failed")
        return responses.JSONResponse(result.model_dump(mode="json"))

    async def update_project_config(request: Any) -> Any:
        """``PUT /api/projects/{id}/config``：白名单内的项目级非凭证配置，fail-closed 写入。"""
        denied = _loopback_error(responses, request)
        if denied is not None:
            return denied
        parsed, error = await _read_model(request, model=ConfigWriteRequest, config=config, responses=responses)
        if error is not None:
            return error
        try:
            result = await console.update_project_config(_project_source(request), parsed)
        except Exception as exc:
            return _console_error_response(responses, exc, event="project_config_write_failed")
        return responses.JSONResponse(result.model_dump(mode="json"))

    return get_project_config, update_project_config


def _build_dialog_endpoint(responses: Any, console: ConsoleHandler) -> Any:
    """``POST /api/dialogs/pick-directory``：在**服务端所在机器**弹出原生目录选择窗口（Story 50-8）。

    三条边界（都不是安全边界）：

    - **回环来源**：非回环 → 403 ``loopback_required``（复用 :func:`_loopback_error`）。远程客户端不该让
      服务机弹窗——那是窗口注入 / 骚扰面，而且弹在别人机器上的窗口对调用者毫无用处；
    - **只回用户明确选中的那一个目录**：取消 / 超时 / 后端脏值一律 ``cancelled=true``，**不回传任何
      目录列表**（这里没有目录浏览能力）；
    - **单在途**由入口层持有（原生窗口不能叠着开），并发 → 409 ``dialog_busy``。

    用 ``POST`` 而不是 ``GET``：避免被 ``<img>`` / 链接意外触发（与写类端点同一姿态）。
    """

    async def pick_directory(request: Any) -> Any:
        denied = _loopback_error(responses, request)
        if denied is not None:
            return denied
        try:
            result = await console.pick_directory()
        except Exception as exc:
            return _console_error_response(responses, exc, event="dialog_pick_failed")
        return responses.JSONResponse(result.model_dump(mode="json"))

    return pick_directory
